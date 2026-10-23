#!/usr/bin/env python3
"""Build the Prism desktop app for whichever OS you run this on.

    python packaging/build.py                  # build + sign + archive
    python packaging/build.py --no-archive     # just dist/Prism*, for testing
    python packaging/build.py --clean          # wipe build/ and dist/ first
    python packaging/build.py --engine nuitka  # compile instead of freeze
    python packaging/build.py --no-sign        # skip code signing

Produces, in dist/:
    Linux    Prism-<version>-linux-<arch>.tar.gz   (+ Prism-<version>.AppImage
                                                     when appimagetool is on PATH)
    Windows  Prism-<version>-windows-<arch>.zip
    macOS    Prism-<version>-macos-<arch>.dmg      (falls back to .zip without hdiutil)

Neither engine can cross-compile: whatever OS you run this on is the OS you
get. All three are built together by .github/workflows/build.yml, which runs
this same script on three runners.

────────────────────────────────────────────────────────────────────────────
TWO ENGINES, AND WHY
────────────────────────────────────────────────────────────────────────────
`pyinstaller` (default) BUNDLES the .pyc files. Anyone can unpack the archive
with a public tool and decompile it back to readable source in about a minute.
That is the state Prism ships in today, and for the licensing system it does
not matter — the security boundary is the backend, which cannot be patched
from a customer's laptop.

It matters for two other things: the routing prompts and the engine's
heuristics are the actual intellectual property, and a readable
`licensing/__init__.py` is a map of where to patch.

`nuitka` COMPILES to C and then to a native binary. There are no .pyc files to
extract and no bytecode to decompile — reading it means reading disassembly of
compiled C.

Do NOT read that as "uncrackable". It is not, and nothing is: the binary still
runs on a machine the attacker controls, and anyone willing to spend an
afternoon in a disassembler can find and flip a branch. What it does is move
casual inspection and casual modification from "minutes with a public tool"
to "real reverse-engineering work", and that difference is the entire, honest
claim.

The security argument is unchanged either way: a patched client still holds no
private key, so it still cannot obtain an authorisation lease, and everything
worth protecting is behind one.
"""
from __future__ import annotations
import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile

# Windows consoles default to cp1252, which cannot encode the ✓/✗ these
# scripts print — the Windows CI build once FAILED after building successfully,
# purely on printing "✓ built". Force UTF-8, degrade characters rather than die.
#
# Under __main__ only: at import time sys.stdout belongs to the importer,
# not to us. devtools/mint.py is imported by five test files, so at module
# level this block would re-encode pytest's own capture stream as a side
# effect of collecting a test — a script reaching into its caller's I/O.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
GUI = os.path.dirname(HERE)
DIST = os.path.join(GUI, "dist")
BUILD = os.path.join(GUI, "build")
sys.path.insert(0, GUI)
import app_meta   # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"
IS_LINUX = sys.platform.startswith("linux")
OS_TAG = "windows" if IS_WIN else "macos" if IS_MAC else "linux"
ARCH = {"x86_64": "x64", "AMD64": "x64", "aarch64": "arm64",
        "arm64": "arm64"}.get(platform.machine(), platform.machine())
STEM = f"{app_meta.NAME}-{app_meta.VERSION}-{OS_TAG}-{ARCH}"


def run(cmd: list[str], **kw):
    print("»", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def preflight(engine: str = "pyinstaller"):
    """Fail with something actionable instead of a build-tool stack trace."""
    if engine == "nuitka":
        try:
            import nuitka  # noqa: F401
        except ImportError:
            sys.exit("Nuitka is missing — pip install nuitka\n"
                     "(also needs a C compiler: MSVC on Windows, Xcode CLT on "
                     "macOS, gcc on Linux)")
    else:
        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            sys.exit("PyInstaller is missing — pip install -r packaging/requirements-build.txt")
    try:
        import PySide6  # noqa: F401
    except ImportError:
        sys.exit("PySide6 is missing — pip install -r requirements.txt")
    if sys.version_info >= (3, 13):
        print("!  Python 3.13+ dropped the stdlib audioop module: voice input "
              "will be disabled in this build unless audioop-lts is installed.")
    engine = os.path.join(GUI, "prism_terminal", "core")
    if not os.path.isdir(engine):
        sys.exit("prism_terminal/core is missing — run:\n"
                 "    git submodule update --init --recursive")
    # Silently-degrading dependencies, asserted where a miss is loud. Both of
    # these are imported inside a function at runtime and fall back rather than
    # raise, which is correct on a customer machine and wrong in a build: the
    # build succeeds and every shipped copy has the feature dead.
    try:
        import dns.resolver  # noqa: F401
    except ImportError:
        sys.exit("dnspython is missing — pip install dnspython\n"
                 "Without it core/inbox.py's mx_host() returns '' and "
                 "mail-server discovery ships broken, with the symptom it was "
                 "written to fix: 'the mail server didn't answer' on a "
                 "perfectly good hosted mailbox.")


def build(engine: str = "pyinstaller"):
    run([sys.executable, os.path.join(HERE, "make_icons.py")])
    # prism.spec rewrites DEFAULT_SERVER in place when PRISM_SERVER_URL is set,
    # because a frozen build cannot take the URL from the environment. Keep a
    # copy so the working tree is not left modified by a build.
    #
    # The same restore has to cover the Nuitka path: it compiles the same
    # source tree, so it needs the same rewrite, and leaving a staging URL
    # baked into a developer's working copy is exactly how a release ends up
    # pointed at a laptop.
    client_py = os.path.join(GUI, "licensing", "client.py")
    original = None
    if os.environ.get("PRISM_SERVER_URL"):
        with open(client_py, "r", encoding="utf-8") as f:
            original = f.read()
    # A dev-channel build bakes CHANNEL and UPDATE_REPO the same way, and the
    # working tree is restored afterwards for the same reason.
    channel_py = os.path.join(GUI, "channel.py")
    updater_py = os.path.join(GUI, "updater.py")
    restore: dict[str, str] = {}
    if requested_channel() == "dev":
        for path in (channel_py, updater_py):
            with open(path, "r", encoding="utf-8") as f:
                restore[path] = f.read()
        new_channel, new_updater = patch_channel(
            restore[channel_py], restore[updater_py],
            os.environ.get("PRISM_UPDATE_REPO", DEV_UPDATE_REPO))
        for path, text in ((channel_py, new_channel), (updater_py, new_updater)):
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        print("[prism] DEV channel baked in -- do not ship this build to customers")
    try:
        if engine == "nuitka":
            _bake_server_url(client_py)
            run([sys.executable, "-m", "nuitka", *nuitka_args()])
        else:
            run([sys.executable, "-m", "PyInstaller", "--noconfirm",
                 "--distpath", DIST, "--workpath", BUILD,
                 os.path.join(HERE, "prism.spec")])
    finally:
        if original is not None:
            with open(client_py, "w", encoding="utf-8") as f:
                f.write(original)
        for path, text in restore.items():
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)


def patch_channel(channel_src: str, updater_src: str, repo: str) -> tuple[str, str]:
    """Return (channel.py, updater.py) source rewritten for a DEV build.

    The repository keeps CHANNEL = "prod" and UPDATE_REPO as plain literals so
    nothing can redirect a shipped build at runtime (tests/test_update_channel
    .py guards both). A dev build gets its own values the same way
    DEFAULT_SERVER is baked: rewrite the literal, build, restore. Fails loudly
    when a marker has moved, because a silently unbaked dev build would update
    from the PRODUCTION repository.
    """
    channel_old = 'CHANNEL = "prod"'
    repo_old = 'UPDATE_REPO = "HitarthTrivedi/prism_gui"'
    if channel_old not in channel_src:
        sys.exit('packaging: channel.py no longer contains CHANNEL = "prod" '
                 "-- refusing to build a dev channel that is not baked.")
    if repo_old not in updater_src:
        sys.exit("packaging: updater.py no longer contains the UPDATE_REPO "
                 "literal -- refusing to build a dev channel that would "
                 "update from the production repository.")
    if "/" not in repo or repo.count("/") != 1 or " " in repo or '"' in repo:
        sys.exit(f"packaging: PRISM_UPDATE_REPO must look like owner/name, "
                 f"got {repo!r}")
    return (channel_src.replace(channel_old, 'CHANNEL = "dev"', 1),
            updater_src.replace(repo_old, f'UPDATE_REPO = "{repo}"', 1))


DEV_UPDATE_REPO = "AlphaKore5/prism_gui_dev"      # create before the first dev build


def requested_channel() -> str:
    value = os.environ.get("PRISM_CHANNEL", "prod").strip().lower() or "prod"
    if value not in ("prod", "dev"):
        sys.exit(f"packaging: PRISM_CHANNEL must be prod or dev, got {value!r}")
    return value


def _bake_server_url(client_py: str) -> None:
    """Write PRISM_SERVER_URL into licensing/client.py's DEFAULT_SERVER.

    prism.spec does this for the PyInstaller path; Nuitka has no spec file, so
    it happens here. Deliberately fails loudly if the constant has been
    renamed: silently not baking the URL produces a build that talks to
    production while the whole point of setting the variable was that it
    should not.
    """
    url = os.environ.get("PRISM_SERVER_URL", "").rstrip("/")
    if not url:
        return
    with open(client_py, "r", encoding="utf-8") as f:
        source = f.read()
    marker = 'DEFAULT_SERVER = "'
    if marker not in source:
        sys.exit("packaging: DEFAULT_SERVER not found in licensing/client.py "
                 "— has it been renamed? Refusing to build with an unbaked "
                 "server URL.")
    head, _, tail = source.partition(marker)
    patched = f'{head}{marker}{url}"' + tail.partition('"')[2]
    with open(client_py, "w", encoding="utf-8") as f:
        f.write(patched)
    print(f"[prism] licence server baked in: {url}")


def nuitka_args() -> list[str]:
    """The Nuitka command line, mirroring what prism.spec bundles.

    Kept beside the spec rather than in a separate script so that the two
    stay visibly in step — a data file added to one and not the other is a
    build that works from source and fails on a customer's machine, which is
    the single most expensive class of packaging bug this project has already
    paid for twice (ezdxf, then Pillow).

    NOT yet validated on all three platforms. Nuitka's Qt plugin handling and
    undetected_chromedriver's runtime patching are both the kind of thing that
    needs a real run per OS, and packaging/smoke_test.py against the produced
    binary is what says whether it worked — it exercises the licence
    verification, the crypto backend, the TLS trust store and the browser
    automation, which is exactly the set a compiled build is most likely to
    break.
    """
    engine_dir = os.path.join(GUI, "prism_terminal")
    args = [
        "--assume-yes-for-downloads",
        "--standalone",
        f"--output-dir={DIST}",
        f"--output-filename={app_meta.NAME}",
        "--enable-plugin=pyside6",
        # Qt needs its platform plugins; without these the app builds and then
        # dies with "could not load the Qt platform plugin".
        "--include-qt-plugins=platforms,styles,imageformats",
        # Same payload as prism.spec's `datas`. paths.resource() resolves
        # these at runtime, so the destination names must match.
        f"--include-data-dir={os.path.join(GUI, 'assets')}=assets",
        f"--include-data-files={os.path.join(GUI, 'style.qss')}=style.qss",
        f"--include-data-dir={os.path.join(GUI, 'lang')}=lang",
        # The engine's DATA only. --include-package=core below compiles the
        # code in. Shipping the sources as well put an editable, directly
        # runnable, licence-free copy of the whole product next to the binary —
        # see the long note in prism.spec. router._tool_notes() reads these off
        # disk, which is the entire reason anything from the engine ships as a
        # file at all.
        *[f"--include-data-files={os.path.join(engine_dir, note)}={note}"
          for note in ("pros_cons.txt", "tool_notes.md", "tool_notes.txt")
          if os.path.exists(os.path.join(engine_dir, note))],
        # The committed licence + lease test vector. --selftest verifies real
        # signatures against it, which is the only check that proves the
        # crypto survived compilation on this platform.
        f"--include-data-dir={os.path.join(GUI, 'licensing', 'testdata')}"
        f"=licensing/testdata",
        # Dynamically imported, so nothing static can find them.
        "--include-package=core",
        # The add-on shelf. Nuitka follows registry.py's static imports, but
        # the manifests also name panels and dialogs by DOTTED STRING, and a
        # string is invisible to any analyser. Without this the Nuitka build
        # can compile cleanly and open with an empty shelf.
        "--include-package=addons",
        "--include-package=undetected_chromedriver",
        "--include-package=selenium",
        "--include-package=cryptography",
        # devtools/ is NOT here, and must never be: it holds the token-signing
        # logic and a private key. Same rule as prism.spec.
    ]
    if IS_WIN:
        args += ["--windows-console-mode=disable",
                 f"--windows-icon-from-ico="
                 f"{os.path.join(HERE, 'icons', 'prism.ico')}"]
    elif IS_MAC:
        args += ["--macos-create-app-bundle",
                 f"--macos-app-icon={os.path.join(HERE, 'icons', 'prism.icns')}",
                 f"--macos-app-name={app_meta.NAME}",
                 f"--macos-app-version={app_meta.VERSION}",
                 # Signed properly afterwards by codesign.py. Nuitka's own
                 # ad-hoc signature is enough to make the bundle launchable
                 # locally and is NOT enough to ship.
                 "--macos-signed-app-name=" + app_meta.BUNDLE_ID]
    args.append(os.path.join(GUI, "main.py"))
    return args


# ── per-OS packaging ─────────────────────────────────────────────────────────

def _desktop_entry() -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={app_meta.NAME}\n"
        f"Comment={app_meta.DESCRIPTION}\n"
        f"Exec={app_meta.NAME}\n"
        f"Icon={app_meta.BUNDLE_ID}\n"
        "Terminal=false\n"
        # One main category only — two makes the app appear twice in the menu
        # (desktop-file-validate warns about exactly this).
        "Categories=Office;\n"
        f"X-AppImage-Version={app_meta.VERSION}\n"
    )


def archive_linux(app_dir: str) -> list[str]:
    made = []
    # A .desktop file and icon travel with the folder so `install.sh` can wire
    # it into the launcher menu.
    shutil.copy2(os.path.join(HERE, "icons", "prism.png"),
                 os.path.join(app_dir, f"{app_meta.BUNDLE_ID}.png"))
    with open(os.path.join(app_dir, f"{app_meta.BUNDLE_ID}.desktop"), "w") as f:
        f.write(_desktop_entry())
    shutil.copy2(os.path.join(HERE, "install.sh"), os.path.join(app_dir, "install.sh"))
    os.chmod(os.path.join(app_dir, "install.sh"), 0o755)

    tar_path = os.path.join(DIST, f"{STEM}.tar.gz")
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(app_dir, arcname=app_meta.NAME)
    made.append(tar_path)

    appimagetool = shutil.which("appimagetool") or shutil.which("appimagetool-x86_64.AppImage")
    if appimagetool:
        made.append(build_appimage(app_dir, appimagetool))
    else:
        print("!  appimagetool not on PATH — skipping the AppImage "
              "(the .tar.gz is complete on its own).")
    return made


def build_appimage(app_dir: str, appimagetool: str) -> str:
    """AppDir layout: AppRun + .desktop + icon at the root, payload in usr/."""
    appdir = os.path.join(BUILD, f"{app_meta.NAME}.AppDir")
    shutil.rmtree(appdir, ignore_errors=True)
    os.makedirs(os.path.join(appdir, "usr"), exist_ok=True)
    shutil.copytree(app_dir, os.path.join(appdir, "usr", "bin"))

    with open(os.path.join(appdir, f"{app_meta.BUNDLE_ID}.desktop"), "w") as f:
        f.write(_desktop_entry())
    shutil.copy2(os.path.join(HERE, "icons", "prism.png"),
                 os.path.join(appdir, f"{app_meta.BUNDLE_ID}.png"))
    apprun = os.path.join(appdir, "AppRun")
    with open(apprun, "w") as f:
        f.write('#!/bin/sh\n'
                'HERE="$(dirname "$(readlink -f "$0")")"\n'
                f'exec "$HERE/usr/bin/{app_meta.NAME}" "$@"\n')
    os.chmod(apprun, 0o755)

    out = os.path.join(DIST, f"{app_meta.NAME}-{app_meta.VERSION}-{ARCH}.AppImage")
    env = dict(os.environ, ARCH=platform.machine())
    # --appimage-extract-and-run: CI containers have no FUSE.
    run([appimagetool, "--appimage-extract-and-run", appdir, out], env=env)
    return out


def archive_windows(app_dir: str) -> list[str]:
    zip_path = os.path.join(DIST, f"{STEM}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(app_dir):
            for name in files:
                src = os.path.join(root, name)
                z.write(src, os.path.join(
                    app_meta.NAME, os.path.relpath(src, app_dir)))
    return [zip_path]


def archive_macos(app_bundle: str) -> list[str]:
    if not shutil.which("hdiutil"):
        zip_path = os.path.join(DIST, f"{STEM}.zip")
        run(["ditto", "-c", "-k", "--keepParent", app_bundle, zip_path])
        return [zip_path]
    staging = os.path.join(BUILD, "dmg")
    shutil.rmtree(staging, ignore_errors=True)
    os.makedirs(staging)
    run(["cp", "-R", app_bundle, staging])
    # The Applications symlink is what makes "drag the icon onto the folder"
    # work — without it people run the app from inside the mounted image.
    os.symlink("/Applications", os.path.join(staging, "Applications"))
    dmg = os.path.join(DIST, f"{STEM}.dmg")
    if os.path.exists(dmg):
        os.remove(dmg)
    run(["hdiutil", "create", "-volname", app_meta.NAME, "-srcfolder", staging,
         "-ov", "-format", "UDZO", dmg])
    return [dmg]


def checksum(path: str) -> str:
    """A SHA-256 beside each artifact.

    The only integrity signal a Linux customer gets — nothing on their machine
    checks a signature — and useful on the other two as a way to tell one
    download from another when someone reports a problem.
    """
    import hashlib

    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    out = path + ".sha256"
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"{digest.hexdigest()}  {os.path.basename(path)}\n")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe build/ and dist/ first")
    ap.add_argument("--no-archive", action="store_true", help="skip the archive step")
    ap.add_argument("--engine", choices=("pyinstaller", "nuitka"),
                    default=os.environ.get("PRISM_BUILD_ENGINE", "pyinstaller"),
                    help="pyinstaller freezes bytecode; nuitka compiles to a "
                         "native binary (see the module docstring)")
    ap.add_argument("--no-sign", action="store_true",
                    help="skip code signing even when credentials are present")
    args = ap.parse_args()

    preflight(args.engine)
    if args.clean:
        for d in (BUILD, DIST):
            shutil.rmtree(d, ignore_errors=True)
    build(args.engine)

    app_dir = os.path.join(DIST, app_meta.NAME)
    if args.engine == "nuitka" and not os.path.isdir(app_dir):
        # Nuitka names its output <script>.dist. Rename to the layout the rest
        # of this script, install.sh and the AppImage builder all expect.
        produced = os.path.join(DIST, "main.dist")
        if os.path.isdir(produced):
            shutil.rmtree(app_dir, ignore_errors=True)
            os.rename(produced, app_dir)
    bundle = os.path.join(DIST, f"{app_meta.NAME}.app")
    target = bundle if (IS_MAC and os.path.isdir(bundle)) else app_dir
    if not os.path.exists(target):
        sys.exit(f"build produced nothing at {target}")
    print(f"\n✓ built {target}")

    # Sign BEFORE archiving. A .dmg or .zip made from an unsigned bundle has
    # to be rebuilt, and the mistake is invisible until a customer's Mac
    # refuses to open it.
    if not args.no_sign:
        import codesign
        codesign.sign(target)

    if args.no_archive:
        return
    if IS_WIN:
        made = archive_windows(app_dir)
    elif IS_MAC:
        made = archive_macos(target)
        # The image is a separate signable object from the bundle inside it;
        # see codesign.sign_macos_archive for why both need doing.
        if not args.no_sign:
            for path in made:
                codesign.sign_macos_archive(path)
    else:
        made = archive_linux(app_dir)
    print("\n✓ artifacts:")
    for path in made:
        checksum(path)
        print(f"    {path}  ({os.path.getsize(path) / 1e6:.0f} MB)"
              f"  + .sha256")


if __name__ == "__main__":
    main()
