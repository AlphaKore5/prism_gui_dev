#!/usr/bin/env python3
"""Install the built setup.exe for real, run the INSTALLED Prism, update it the
way the in-app updater does, uninstall it, and check what is left.

    python packaging/windows/installer_check.py      # Windows CI only

What it proves, on the runner:
  * Setup installs per user, without asking for admin rights, into
    %LOCALAPPDATA%\\Programs\\<name>, registered under HKCU only;
  * the program folder holds exactly the files of dist/Prism, byte for byte,
    i.e. exactly what the update manifest describes; the uninstaller is not in it;
  * the updater, given the installed Prism.exe, swaps that folder and stages
    beside it (updater.bundle_root, updater.stage_root);
  * the installed Prism passes the packaged self-test (packaging/smoke_test.py,
    sandbox HOME);
  * after a simulated in-app update (apply_update.perform_swap, which adds a
    file Setup never installed and leaves the backup and marker behind), the
    uninstaller still exists and removes the program folder and the updater's
    leftovers, and a file in the user's data folder (%USERPROFILE%\\.prism)
    is still there.

The runner is an administrator, so "no admin needed" is shown by the install
mode (HKCU, LOCALAPPDATA), not by running as a limited user.

Refuses to run outside GitHub Actions: it installs and uninstalls Prism for the
current Windows user and writes into their .prism folder.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGING = os.path.dirname(HERE)
GUI = os.path.dirname(PACKAGING)
ISS = os.path.join(HERE, "prism.iss")
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
KEEP_ME = "installer-check-keep-me.txt"


def app_guids(iss_text: str) -> dict[str, str]:
    """{flavour: GUID} from prism.iss's `#if Flavour == "x"` / `#define AppGuid` pairs."""
    pairs = re.findall(r'#(?:el)?if Flavour == "(\w+)"\s*\n\s*#define AppGuid "\{\{([0-9A-Fa-f-]+)\}"',
                       iss_text)
    return dict(pairs)


def _fail(message: str) -> None:
    sys.exit(f"installer check: {message}")


def _reg_values(root, key: str) -> dict[str, str] | None:
    import winreg
    try:
        with winreg.OpenKey(root, key) as k:
            values, i = {}, 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(k, i)
                except OSError:
                    return values
                values[name] = value
                i += 1
    except OSError:
        return None


def _same(a: str, b: str) -> bool:
    """Same folder? realpath also turns the runner's 8.3 short names (RUNNER~1) long."""
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _wait_until(done, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if done():
            return True
        time.sleep(1)
    return done()


def main() -> int:
    if sys.platform != "win32" or os.environ.get("GITHUB_ACTIONS") != "true":
        _fail("runs on a Windows GitHub Actions runner only (it installs and "
              "uninstalls Prism for this user)")
    import winreg
    sys.path.insert(0, GUI)
    sys.path.insert(0, PACKAGING)
    import app_meta
    import apply_update
    import build
    import flavour
    import smoke_test
    import update_manifest
    import updater

    ident = flavour.identity(build.FLAVOUR_BUILT)
    setup = os.path.join(build.DIST, f"{build.STEM}-setup.exe")
    zip_path = os.path.join(build.DIST, f"{build.STEM}.zip")
    bundle = os.path.join(build.DIST, app_meta.NAME)
    exe_name = f"{app_meta.NAME}.exe"
    for path in (setup, zip_path, bundle):
        if not os.path.exists(path):
            _fail(f"nothing built at {path}")
    with open(ISS, encoding="utf-8") as f:
        guid = app_guids(f.read())[build.FLAVOUR_BUILT]
    key = rf"{UNINSTALL_KEY}\{{{guid}}}_is1"
    if _reg_values(winreg.HKEY_CURRENT_USER, key) is not None:
        _fail(f"{ident['display']} is already installed for this user; refusing to touch it")

    programs = os.path.join(os.environ["LOCALAPPDATA"], "Programs")
    expected_dir = os.path.join(programs, ident["name"])
    shortcut = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu",
                            "Programs", f"{ident['display']}.lnk")
    work = tempfile.mkdtemp(prefix="prism-installer-check-")
    os.environ["PRISM_APPLY_LOG"] = os.path.join(work, "update-apply.log")

    # A file in the folder an installed Prism keeps the person's data in.
    data_dir = os.path.join(os.environ["USERPROFILE"], ".prism")
    os.makedirs(data_dir, exist_ok=True)
    keep_me = os.path.join(data_dir, KEEP_ME)
    with open(keep_me, "w", encoding="utf-8") as f:
        f.write("the uninstaller must leave this alone\n")

    # ── install ──────────────────────────────────────────────────────────────
    log = os.path.join(work, "setup.log")
    started = time.monotonic()
    rc = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER",
                         "/NORESTART", f"/LOG={log}"], cwd=work, timeout=1800).returncode
    install_s = time.monotonic() - started
    if rc != 0:
        with open(log, encoding="utf-8", errors="replace") as f:
            print(f.read()[-6000:])
        _fail(f"setup exited {rc}")
    print(f"✓ installed in {install_s:.0f} s")

    reg = _reg_values(winreg.HKEY_CURRENT_USER, key)
    if reg is None:
        _fail(f"no HKCU uninstall entry {key}")
    if _reg_values(winreg.HKEY_LOCAL_MACHINE, key) is not None:
        _fail("Setup wrote a machine-wide (HKLM) uninstall entry: it is not per user")
    install_dir = reg["InstallLocation"].rstrip("\\")
    if not _same(install_dir, expected_dir):
        _fail(f"installed into {install_dir}, expected {expected_dir}")
    uninstaller = reg["UninstallString"].strip('"')
    if not _same(os.path.dirname(uninstaller), os.path.join(programs, f"{ident['name']}-uninstall")):
        _fail(f"the uninstaller is at {uninstaller}, not beside the program folder")
    if not os.path.isfile(uninstaller) or not os.path.isfile(shortcut):
        _fail(f"missing after install: {uninstaller} or {shortcut}")
    print(f"✓ per user: {install_dir} (HKCU only), uninstaller {uninstaller}")

    # Exactly the update manifest's files: the updater compares the installed
    # tree with the manifest, and uninstall.py refuses a folder holding others.
    installed = update_manifest.build(install_dir, app_meta.VERSION)["files"]
    reference = update_manifest.build(bundle, app_meta.VERSION)["files"]
    if installed != reference:
        extra = sorted({e["path"] for e in installed} - {e["path"] for e in reference})
        missing = sorted({e["path"] for e in reference} - {e["path"] for e in installed})
        _fail(f"the installed tree differs from dist/{app_meta.NAME}: "
              f"extra {extra[:10]}, missing {missing[:10]}")
    print(f"✓ the program folder is dist/{app_meta.NAME} exactly ({len(installed)} files)")

    exe = os.path.join(install_dir, exe_name)
    if not _same(updater.bundle_root(exe), install_dir):
        _fail(f"updater.bundle_root({exe}) is {updater.bundle_root(exe)}")
    staging = os.path.join(programs, ".prism-update-staging")
    if not _same(updater.stage_root(install_dir), staging):
        _fail(f"updater would stage in {updater.stage_root(install_dir)}, not beside the install")
    print(f"✓ the updater swaps {install_dir} and stages in {staging}")

    # ── the installed Prism starts ───────────────────────────────────────────
    smoke_test.main(exe)

    # ── an in-app update, as apply_update does it ────────────────────────────
    staged = os.path.join(staging, app_meta.VERSION)
    shutil.copytree(install_dir, staged)
    with open(os.path.join(staged, "_internal", "added-by-an-update.txt"), "w") as f:
        f.write("a file Setup never installed\n")
    backup = install_dir + ".old"
    apply_update.perform_swap(install_dir, staged, backup)
    apply_update.mark_pending_confirm(install_dir, app_meta.VERSION)
    if not os.path.isfile(uninstaller):
        _fail("the in-app update swap removed the uninstaller")
    print(f"✓ swapped like an in-app update; {backup} and the marker left behind")

    # ── uninstall ────────────────────────────────────────────────────────────
    ulog = os.path.join(work, "uninstall.log")
    subprocess.run([uninstaller, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    f"/LOG={ulog}"], cwd=work, timeout=900)
    # The uninstaller hands over to a copy of itself in TEMP and may return first.
    if not _wait_until(lambda: not os.path.exists(uninstaller)
                       and _reg_values(winreg.HKEY_CURRENT_USER, key) is None, 600):
        _fail("the uninstaller did not finish within 10 minutes")
    left = [p for p in (install_dir, backup, staging, shortcut) if os.path.exists(p)]
    if left:
        if os.path.isfile(ulog):
            with open(ulog, encoding="utf-8", errors="replace") as f:
                print(f.read()[-6000:])
        _fail(f"left behind after uninstall: {left}")
    if os.path.exists(os.path.dirname(uninstaller)):
        print(f"::warning::the empty uninstaller folder {os.path.dirname(uninstaller)} was left behind")
    with open(keep_me, encoding="utf-8") as f:
        if f.read() != "the uninstaller must leave this alone\n":
            _fail(f"{keep_me} changed")
    os.remove(keep_me)
    print(f"✓ uninstalled: program folder, backup, staging and shortcut gone; {data_dir} kept")

    zip_mb, setup_mb = os.path.getsize(zip_path) / 1e6, os.path.getsize(setup) / 1e6
    line = (f"- {os.path.basename(setup)}: {setup_mb:.0f} MB vs "
            f"{os.path.basename(zip_path)}: {zip_mb:.0f} MB "
            f"({(setup_mb / zip_mb - 1) * 100:+.0f}%); installs in {install_s:.0f} s")
    print(line)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(line + "\n")
    shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
