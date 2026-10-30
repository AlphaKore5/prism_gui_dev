# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Prism desktop app — one spec, all three OSes.

Run it through packaging/build.py rather than directly; that script generates
the icons first and packs the result into the archive people download.

Deliberately a onedir build, not onefile. undetected-chromedriver downloads and
PATCHES a chromedriver binary at runtime, and a onefile bundle re-extracts to a
fresh temp directory on every launch — so every run would re-download the
driver, and the patched copy would be thrown away each time. onedir also starts
noticeably faster and lets antivirus scan the payload once instead of on every
launch.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
GUI_DIR = os.path.dirname(SPEC_DIR)
sys.path.insert(0, GUI_DIR)
import app_meta   # noqa: E402

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

# ── the build will not ship without a production signing key ────────────────
# licensing/keys.py trusts its DEVELOPMENT keys only when running from source,
# so a frozen build with an empty PRODUCTION map trusts nothing and rejects
# every customer's licence with "issued for a different version of Prism".
#
# Nothing else catches this: the app starts, the window opens, and
# licensing.selftest() still passes, because it verifies the committed test
# vector against that vector's own key rather than against PRODUCTION. The
# first sign would be every client of the release failing to activate at once.
import licensing.keys as _keys   # noqa: E402

if not _keys.PRODUCTION and not os.environ.get("PRISM_UNLICENSED_TEST_BUILD"):
    raise SystemExit(
        "\n  Refusing to build: licensing/keys.py has no PRODUCTION key.\n"
        "  A packaged Prism would reject every licence you issue.\n\n"
        "  Generate the production keypair on the licence server, then paste\n"
        "  its PUBLIC half into PRODUCTION in licensing/keys.py:\n\n"
        '      PRODUCTION = {"k1": "<64 hex chars>"}\n\n'
        "  See license_server/.env.example for the generator command.\n"
        "  (Building packaging smoke tests only? "
        "PRISM_UNLICENSED_TEST_BUILD=1 — the result cannot activate.)\n")

ENGINE_DIR = os.path.join(GUI_DIR, "prism_terminal")

icon = os.path.join(SPEC_DIR, "icons",
                    "prism.ico" if IS_WIN else "prism.icns" if IS_MAC else "prism.png")

# ── which licence server this build talks to ─────────────────────────────────
# A frozen app ignores PRISM_LICENSE_SERVER at runtime (that override would be
# a bypass), so the URL has to be decided here. PRISM_SERVER_URL lets a test
# build point at a laptop or a LAN address without editing source; unset, the
# DEFAULT_SERVER already in licensing/client.py ships.
_server_url = os.environ.get("PRISM_SERVER_URL", "").strip()
if _server_url:
    _client_py = os.path.join(GUI_DIR, "licensing", "client.py")
    with open(_client_py, "r", encoding="utf-8") as _f:
        _src = _f.read()
    import re as _re
    # subn, not sub: what matters is whether the PATTERN MATCHED, not whether
    # the text changed. Those come apart in one ordinary case — the URL in
    # source already being the URL we are baking in — and the old `_patched ==
    # _src` test read that as "DEFAULT_SERVER not found" and killed the build
    # over a line sitting right there in the file.
    #
    # It cost two rounds of chasing, because it is invisible locally: with
    # PRISM_SERVER_URL unset this whole branch is skipped, so every local build
    # passed while CI failed on all three platforms.
    _patched, _hits = _re.subn(r'^DEFAULT_SERVER = ".*"$',
                               f'DEFAULT_SERVER = "{_server_url}"', _src,
                               count=1, flags=_re.M)
    if not _hits:
        raise SystemExit("PRISM_SERVER_URL set but DEFAULT_SERVER not found "
                         "in licensing/client.py — has it been renamed?")
    # Written back so the analyser bundles the patched module. build.py restores
    # the original afterwards; if a build is interrupted, `git diff` shows it.
    with open(_client_py, "w", encoding="utf-8") as _f:
        _f.write(_patched)
    print(f"[prism] licence server baked in: {_server_url}")

# ── what ships alongside the code ────────────────────────────────────────────
# paths.resource() resolves these at runtime; the destination names must match
# the layout the sources expect ("assets/…", "prism_terminal/…").
datas = [
    (os.path.join(GUI_DIR, "assets"), "assets"),
    (os.path.join(GUI_DIR, "style.qss"), "."),
    # Read in-app via dialogs/legal_dialog.py (Settings → Help & more →
    # Legal) so a customer never needs a network connection just to read
    # what they agreed to.
    (os.path.join(GUI_DIR, "TERMS_OF_USE.md"), "."),
    (os.path.join(GUI_DIR, "PRIVACY_POLICY.md"), "."),
    # The translation catalogue and every language pack. i18n.load() reads
    # these through paths.resource(), and a build that ships without them
    # doesn't fail — it just quietly renders in English no matter what the
    # customer picked, which is a far harder bug to be told about.
    (os.path.join(GUI_DIR, "lang"), "lang"),
    # The Google OAuth client, if this build has one. Optional on purpose:
    # gdrive.configured() reports "not set up" rather than failing, so a build
    # made without it still ships — it just has no Drive picker.
    *([(os.path.join(GUI_DIR, "integrations", "google_client.json"),
        "integrations")]
      if os.path.exists(os.path.join(GUI_DIR, "integrations",
                                     "google_client.json")) else []),
    # The committed licence-token test vector. main.py's --selftest verifies a
    # real signature against it, which is the only check that proves the
    # crypto survived freezing on this platform — an import succeeding says
    # nothing about whether the native backend actually works.
    (os.path.join(GUI_DIR, "licensing", "testdata", "vector.json"),
     os.path.join("licensing", "testdata")),
]

# devtools/ is deliberately absent: it holds the token-signing logic and a
# private key. Nothing in it may ever reach a build.

# The engine's DATA ships as files. Its CODE comes from the archive — pathex
# below plus the enumerated core.* hiddenimports.
#
# This used to ship the sources too, and that was the whole product in editable
# form sitting next to the binary: 19 .py files at mode 0664, including
# automation.py, boq.py and a prism.py with a complete licence-free main().
# Two bypasses came free with it. core_bridge put this directory AHEAD of the
# archive on sys.path, so editing a file here changed what the "compiled" app
# did — verified, not theorised. And run_prism.command shipped at mode 0755:
# double-click it and a venv builds itself, pip installs requirements.txt and
# runs the engine with no licence check at all, needing no Python knowledge.
#
# The launchers and requirements.txt exist to start the CLI from a source
# checkout and have no purpose in a bundle. requirements.txt is worth removing
# on its own account: it is unpinned, so that launcher also pulled whatever
# PyPI served that day into the customer's install folder.
_ENGINE_SKIP = {"run_prism.bat", "run_prism.command", "requirements.txt",
                # A submodule's .git is a one-line gitlink file, so the dirs
                # filter below never catches it. Harmless, and it has no
                # business in a customer's install folder.
                ".git", ".gitignore", ".gitmodules"}
# demo/ is sample CSVs for a walkthrough that is not part of the product, and
# nothing in the app reads it.
# skills/ is handled by its own entry below, because its checks.py files
# are DATA -- loaded from a path by core/skills.py, never imported -- and
# the loop below drops every .py as code.
_ENGINE_SKIP_DIRS = ("__pycache__", ".git", ".venv", "demo", "tests", "skills")
for root, dirs, files in os.walk(ENGINE_DIR):
    dirs[:] = [d for d in dirs if d not in _ENGINE_SKIP_DIRS]
    for name in files:
        if name.endswith((".py", ".pyc", ".pyo")) or name in _ENGINE_SKIP:
            continue
        src = os.path.join(root, name)
        rel = os.path.relpath(root, GUI_DIR)
        datas.append((src, rel))

# The skills: house doctrine, and the checkers that enforce it. Shipped as a
# whole tree INCLUDING the .py files, which the engine-data loop above has to
# skip -- everything else ending in .py under prism_terminal/ is engine source
# and shipping it was a licence bypass (see the note above). A skill's
# checks.py is different in kind: nothing imports it, core/skills.py loads it
# from its path, and without it every skill silently becomes advice with
# nothing checking it. Destination matches skills.SHIPPED_DIRS, which walks up
# from core/ at runtime.
# Walked file by file rather than added as a whole tree, for one reason:
# loading a checks.py leaves a __pycache__ beside it on the developer's
# machine, and a directory entry would ship that too.
_SKILLS_DIR = os.path.join(ENGINE_DIR, "skills")
_n = 0
for _root, _dirs, _files in os.walk(_SKILLS_DIR):
    _dirs[:] = [d for d in _dirs if d != "__pycache__"]
    _rel = os.path.relpath(_root, ENGINE_DIR)
    for _name in sorted(_files):
        # README.md is for people writing a skill, not for the app, and every
        # shipped file is one more asset against GitHub's 1,000-per-release
        # cap -- Linux sits at 978 with the skills in.
        if _name.endswith((".pyc", ".pyo")) or _name in (".gitignore", "README.md"):
            continue
        datas.append((os.path.join(_root, _name),
                      os.path.join("prism_terminal", _rel)))
        _n += _name == "SKILL.md"
print(f"[prism] skills bundled: {_n}")

# Modules in the archive use paths relative to ``core`` at runtime, whereas
# the generic engine-data loop above preserves the source checkout prefix.
# Keep these browser modules in the location their frozen imports resolve.
for _asset_dir in ("studio_assets", os.path.join("motion", "runtime")):
    _source = os.path.join(ENGINE_DIR, "core", _asset_dir)
    if os.path.isdir(_source):
        datas.append((_source, os.path.join("core", _asset_dir)))

# When frozen, core.router is imported from the archive, so its __file__ points
# at <bundle>/core/router.py and its notes lookup walks up to the bundle root —
# not to prism_terminal/. Put a copy there too, or the tool notes silently stop
# reaching the router prompt.
for note in ("pros_cons.txt", "tool_notes.md", "tool_notes.txt"):
    src = os.path.join(ENGINE_DIR, note)
    if os.path.exists(src):
        datas.append((src, "."))

# undetected_chromedriver ships non-Python files and imports its patcher
# dynamically; without this the frozen app raises at driver setup, which is the
# one moment the user is furthest from a terminal that would show the error.
datas += collect_data_files("undetected_chromedriver")
# RapidOCR keeps its detection/recognition models and its config inside the
# package; without them core.ocr imports fine and then reads nothing.
try:
    datas += collect_data_files("rapidocr_onnxruntime")
except Exception:                                       # not installed: source-only
    pass

# pypdfium2 (addons/boq's HVAC PDF-takeoff, item 26) ships pdfium's own
# compiled binary inside the package and loads it by a path read from its
# own data files -- the same class of bug rapidocr_onnxruntime's own
# comment above already describes, so it gets the same guarded treatment
# rather than trusting PyInstaller's static analysis to find a binary
# loaded this indirectly. pdfplumber is pure Python on top of it and needs
# no such help; included here only so both land in one place.
try:
    datas += collect_data_files("pypdfium2")
except Exception:                                       # not installed: source-only
    pass

# rapidocr (the NEW package hvac_takeoff.py imports -- genuinely separate
# from rapidocr_onnxruntime above, see requirements.txt's own comment)
# ships its yaml configs (default_models.yaml etc.) inside the package;
# this bundles THOSE. It does NOT solve the real gap found 27 Oct 2026:
# the actual model weights (~30MB of .onnx files) are not in the wheel
# at all -- rapidocr/download_file.py fetches them from modelscope.cn
# the first time RapidOCR() actually runs, same as RapidOCR's own
# install-time note elsewhere in this file already says for a different
# model set. A frozen build with no network reachable at first use will
# have a working takeoff button that fails the moment OCR is reached --
# not fixed here; needs either bundling pre-downloaded models into datas
# explicitly (find them under site-packages/rapidocr/models after a
# build-machine run that primed the cache) or accepting the first-run
# network dependency as a documented limitation.
try:
    datas += collect_data_files("rapidocr")
except Exception:                                       # not installed: source-only
    pass

# OpenCV, which RapidOCR imports. cv2's __init__ loads its compiled extension
# by a path it reads from its own config files, and on the macOS arm64 bundle
# that left "recursion is detected during loading of cv2 binary extensions" —
# the whole of RapidOCR unusable, while Windows and Linux were fine. Taking
# everything cv2 ships (extension, config, submodules, dylibs) leaves it
# nothing to go looking for.
from PyInstaller.utils.hooks import collect_all as _collect_all
_cv_datas, _cv_binaries, _cv_hidden = _collect_all("cv2")
datas += _cv_datas
_extra_binaries = list(_cv_binaries)
hiddenimports_cv2 = list(_cv_hidden)

# The FFmpeg executable, which lives inside the imageio_ffmpeg package as a
# data file rather than as Python. include_py_files is off, so this picks up
# the binary and nothing else.
#
# A build without it produces an app whose Reel button fails on a customer's
# machine with an install guide — which is exactly what happened to the first
# Windows user. There is a runtime download as a fallback (core/ffmpeg.py),
# but a customer should never meet it.
try:
    import imageio_ffmpeg  # noqa: F401
    datas += collect_data_files("imageio_ffmpeg")
    print("[prism] FFmpeg bundled")
except ImportError:
    print("[prism] WARNING: imageio-ffmpeg is not installed, so this build "
          "ships no FFmpeg. Reel will have to download it on first use.")

def _engine_modules() -> list[str]:
    """Every core.* module, read off disk rather than listed by hand.

    This used to be a hand-maintained list. It named 11 modules; the engine has
    25. The other 14 reached the archive only because PyInstaller also scans
    function-level imports and found core_bridge's lazy `def get_X(): from core
    import X` getters — an accident, not a plan, and one nobody could see.

    That was survivable only while the loose .py files also shipped and
    core_bridge put them ahead of the archive: a module missing from here was
    silently imported from disk instead. Now that the sources do not ship,
    anything missing from this list is an ImportError in front of a customer,
    in a windowed build with no console to print it. So enumerate, never list.

    RECURSIVE, not a listdir of core/*.py. That mattered: core/motion/ is a
    SUBPACKAGE, so the old flat scan never listed core.motion.generate,
    core.motion.render or core.motion.schema, and no frozen build has ever
    contained them. Motion Graphics has been shipped-but-disabled behind
    core/motion/render.py's _DISABLED_PENDING_ASSET_FIX kill-switch, so the
    omission has cost nothing yet -- turn that switch off without this change
    and the feature is an ImportError in a windowed build with no console.
    """
    core = os.path.join(ENGINE_DIR, "core")
    found = ["core"]
    for folder, dirs, files in os.walk(core):
        # pytest leaves .pytest_cache below packages it exercises.  Any hidden
        # directory is metadata rather than an importable Python package; if
        # it reaches this walk it becomes an invalid hidden import such as
        # ``core..pytest_cache`` and dirties (or can break) release builds.
        dirs[:] = [d for d in dirs
                   if d != "__pycache__" and not d.startswith(".")]
        rel = os.path.relpath(folder, core)
        package = "core" if rel == "." else "core." + rel.replace(os.sep, ".")
        if package != "core":
            found.append(package)          # the subpackage itself
        for name in sorted(files):
            if name.endswith(".py") and name != "__init__.py":
                found.append(package + "." + name[:-3])
    print(f"[prism] engine modules bundled: {len(found) - 1}")
    return found


def _addon_modules() -> list[str]:
    """Every module under addons/, so the shelf is not empty in a frozen build.

    Belt and braces. addons/registry.py imports each add-on's manifest
    STATICALLY, and those static imports are what PyInstaller's analyser
    actually follows; this walk is the backstop for a module that only the
    manifests' dotted strings refer to -- a panel or dialog named as
    "addons.gerber.panel:GerberPanel" and never imported anywhere.

    The failure this prevents is the worst one available in this design:
    development is perfect, the build succeeds, and the customer opens a
    windowed app with an empty add-on shelf and no console to say why.
    """
    import addons.registry as _registry
    found = list(_registry.addon_modules())
    print(f"[prism] add-on modules bundled: {len(found)} "
          f"({_registry.EXPECTED} add-ons registered)")
    return found


hiddenimports = _engine_modules() + _addon_modules() + [
    "rapidocr_onnxruntime", "onnxruntime",
    # Optional-at-runtime, imported inside functions.
    "pypdf", "docx", "openpyxl", "pyaudio",
    # Mail-server discovery: core/inbox.py does a lazy `import dns.resolver`
    # inside mx_host(), which degrades SILENTLY to guessing when absent. That
    # is right on a customer machine and wrong in a build — and it was already
    # happening: dnspython was installed on the build box and PyInstaller still
    # did not bundle it, because a function-level import of a package it has no
    # hook for is invisible. Every shipped copy had MX detection dead, which is
    # precisely the bug the lazy import was added to fix.
    "dns", "dns.resolver", "dns.rdatatype",
    # undetected_chromedriver's patcher imports distutils, gone from the 3.12
    # stdlib — rthook_distutils.py aliases setuptools' copy, which has to be
    # bundled for that to be possible.
    "setuptools", "setuptools._distutils", "setuptools._distutils.version",
    # Qt bits pulled in by name (QtSvg backs every icon we draw).
    "PySide6.QtSvg", "PySide6.QtNetwork",
    # Licence verification. cryptography loads its Rust/OpenSSL backend
    # dynamically, so the leaf modules have to be named — a build where these
    # are missing starts fine and then rejects every customer's licence.
    "cryptography", "cryptography.hazmat.backends.openssl",
    "cryptography.hazmat.bindings._rust",
    "cryptography.hazmat.primitives.asymmetric.ed25519",
    "cryptography.hazmat.primitives.ciphers.aead",
]

# Audio RMS calculation for wakeword: stdlib audioop on Python < 3.13,
# audioop-lts on Python >= 3.13.
try:
    import audioop  # noqa: F401
    hiddenimports.append("audioop")
except ImportError:
    pass
try:
    import audioop_lts  # noqa: F401
    hiddenimports.append("audioop_lts")
except ImportError:
    pass

# ── Every dependency a sold feature needs must be installed, or no build ───
# The try/except blocks below used to turn a missing package into a printed
# line and a build that shipped anyway — which is how customers met "STEP not
# installed", "Google Drive libraries not installed" and a Motion engine that
# was absent. A packaging runner is under our control, so a missing package is
# a runner bug to fix here, not a degraded feature to ship. This runs before
# anything is analysed, and names every gap at once.
import importlib.util as _ilu
_REQUIRED = {
    "cadquery": "STEP", "OCP": "STEP", "playwright": "Studio and Motion",
    "imageio_ffmpeg": "Reel and Motion encoding", "keyring": "licence key storage",
    "rapidocr_onnxruntime": "reading text in pictures", "onnxruntime": "reading text in pictures",
    "pyaudio": "voice input", "shapely": "Gerber", "gerbonara": "Gerber",
    "openpyxl": "Excel", "docx": "Word attachments", "pypdf": "PDF attachments",
    "dns": "mail-server discovery", "ezdxf": "BOQ", "PIL": "Reel", "numpy": "BOQ",
    "cryptography": "licensing", "certifi": "HTTPS trust",
    "selenium": "browser automation", "undetected_chromedriver": "browser automation",
    "googleapiclient": "Google Drive", "google_auth_oauthlib": "Google Drive",
}
if sys.platform == "darwin":
    _REQUIRED.update({"Vision": "reading text in pictures on a Mac",
                      "Quartz": "reading text in pictures on a Mac"})
_missing = [f"{m} ({why})" for m, why in _REQUIRED.items() if _ilu.find_spec(m) is None]
if _missing:
    raise SystemExit("Refusing to build: these packages are not installed on "
                     "this runner, so the app would ship with features that "
                     "say 'not installed':\n  " + "\n  ".join(_missing))

# The Google Drive libraries are imported lazily inside integrations/gdrive.py,
# so the analyser never sees them. Added only when they are actually installed
# on the build machine: a build without them still ships, with the Drive picker
# reporting itself unavailable rather than crashing.
try:
    import google_auth_oauthlib  # noqa: F401
    import googleapiclient       # noqa: F401
    hiddenimports += collect_submodules("googleapiclient")
    hiddenimports += collect_submodules("google_auth_oauthlib")
    hiddenimports += collect_submodules("google.oauth2")
    datas += collect_data_files("googleapiclient")
    print("[prism] Google Drive support bundled")
except ImportError:
    print("[prism] Google Drive libraries not installed - picker will be "
          "unavailable in this build")

# STEP's engine. OCP is OpenCascade's own Python bindings — dozens of
# separate compiled extension submodules (OCP.TopoDS, OCP.BRepBuilderAPI,
# …), each its own .pyd/.so, not one package with internal imports
# PyInstaller's static analysis can trace. Neither cadquery nor OCP ships a
# PyInstaller hook of its own (checked: no __pyinstaller/ in either
# package, and pyinstaller-hooks-contrib carries none for them either), so
# without this, the ones core.stepfile happens to import at analysis time
# bundle and the rest silently don't — a build that passed on the
# developer's machine and failed on a customer's with a DIFFERENT error
# than "no module named cadquery" (that one's just this requirements.txt
# missing the line; this is the next failure after that's fixed).
try:
    import cadquery    # noqa: F401
    import OCP          # noqa: F401
    hiddenimports += collect_submodules("OCP")
    hiddenimports += collect_submodules("cadquery")
    datas += collect_data_files("OCP")
    print("[prism] STEP's cadquery/OCP bundled")
except ImportError:
    print("[prism] cadquery not installed - STEP will be unavailable in "
          "this build")

# Prism Studio's browser. playwright._impl._driver.compute_driver_executable()
# locates both the Node driver AND the Chromium binary as a sibling of
# wherever `playwright.__file__` resolves to at runtime — under a frozen
# onedir build that's this bundle's own playwright/ folder, which is exactly
# what collect_data_files puts there. It only has anything to find because
# .github/workflows/build.yml ran `playwright install chromium` with
# PLAYWRIGHT_BROWSERS_PATH=0 first, landing Chromium INSIDE the package
# (playwright/driver/package/.local-browsers/…) instead of the OS cache dir a
# frozen build can never see. A build machine that skipped that step still
# builds — Studio just falls back to Prism Reel on every customer's machine,
# same as it always has, rather than failing here.
#
# The actual bundling is NOT the collect_submodules/collect_data_files call
# below — playwright ships its OWN PyInstaller hook (see
# playwright/_impl/__pyinstaller/hook-playwright.*.py in the installed
# package), which PyInstaller auto-runs the moment playwright.sync_api is
# discovered as a needed import (core/reel_web.py's own `from
# playwright.sync_api import sync_playwright`, found while analysing the
# core.reel_web hiddenimport below, is already enough — this try/except is a
# safety net for older playwright versions without that hook, not the
# primary path). That hook calls collect_data_files("playwright") with NO
# filtering, so anything trimmed from `datas` here gets silently re-added by
# it — the real filter is the one applied to `a.datas` after Analysis(), well
# below. See that comment for what gets trimmed and why.
try:
    import playwright  # noqa: F401
    hiddenimports += collect_submodules("playwright")
    datas += collect_data_files("playwright")
    print("[prism] Prism Studio's browser engine bundled")
except ImportError:
    print("[prism] WARNING: playwright is not installed, so this build ships "
          "no browser engine — Prism Studio will fall back to Prism Reel on "
          "every machine that runs it.")

hiddenimports += hiddenimports_cv2
if sys.platform == "darwin":
    # core.ocr imports these inside a function, so the analyser never sees them.
    hiddenimports += ["Vision", "Quartz", "Foundation", "objc", "CoreFoundation"]
hiddenimports += collect_submodules("undetected_chromedriver")
hiddenimports += collect_submodules("selenium")

# The OS credential store, for the licence key (licensing/secretstore.py).
# Optional in exactly the same way as the Drive libraries above: a build made
# without it falls back to the plaintext file the previous version used, and
# says so in diagnostics rather than failing.
#
# collect_submodules matters here — keyring picks its backend by ENTRY POINT
# at runtime, so nothing static imports keyring.backends.Windows, and a build
# that bundled only `keyring` itself would find no usable backend and silently
# degrade to the file on every machine.
try:
    import keyring  # noqa: F401
    hiddenimports += collect_submodules("keyring")
    print("[prism] OS credential store bundled - licence key will be "
          "kept in the keychain")
except ImportError:
    print("[prism] keyring not installed - the licence key will be stored in "
          "~/.prism/license.json instead")

# Qt is modular and PyInstaller takes the lot by default; these are the big
# ones Prism never touches. Dropping them roughly halves the download.
excludes = [
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuick3D", "PySide6.Qt3DCore",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngine",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtBluetooth", "PySide6.QtNfc",
    "PySide6.QtPositioning", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtSql",
    "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtPdf",
    "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech",
    "shiboken6.support",
    # Scientific/GUI stacks that sneak in via transitive imports.
    #
    # numpy and PIL are NOT in this list, and must not be added back:
    #   · ezdxf declares numpy as a hard dependency — excluding it made the
    #     BOQ add-on fail in every packaged build with "No module named
    #     'numpy'", while working perfectly from source.
    #   · Prism Reel draws its frames with Pillow (PIL).
    # Both add-ons are things we sell. They cost ~50MB in the bundle; a
    # flagship feature that only works on a developer's machine costs more.
    "tkinter", "matplotlib", "scipy", "pandas", "IPython",
    "pytest", "notebook",
]

# NOTE: there is no bytecode encryption here, and there cannot be — PyInstaller
# removed the `cipher`/`--key` option in 6.0, and this project requires >=6.3.
# The `block_cipher = None` / `cipher=block_cipher` arguments that used to sit
# here were inert and have been deleted rather than left implying protection
# that does not exist. What actually keeps the product closed is that the
# engine payload is not in this bundle at all — see docs/licensing/.

a = Analysis(
    [os.path.join(GUI_DIR, "main.py")],
    # ENGINE_DIR on the search path is what lets the `core.*` hiddenimports
    # below resolve — and analysing them is what drags in the stdlib they use
    # (smtplib, ssl, csv, email, …), none of which the GUI itself imports.
    pathex=[GUI_DIR, ENGINE_DIR],
    binaries=_extra_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[
        os.path.join(SPEC_DIR, "rthook_distutils.py"),
        os.path.join(SPEC_DIR, "rthook_ssl_certs.py"),
    ],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

# `playwright install chromium` (.github/workflows/build.yml) pulls in two
# things nothing in this codebase calls: chromium-headless-shell and
# playwright's OWN bundled ffmpeg (only
# for its record_video_dir option, which nothing here uses either — Reel
# already carries imageio-ffmpeg for its own encoding). Together they were
# ~265MB of a ~730MB playwright payload for code with no path that reaches
# them, verified by grepping prism_terminal/core for "headless_shell" and
# "record_video" before writing this.
#
# THAT GREP WAS THE WRONG TEST, and this filter shipped a broken Windows and
# macOS build for it. Playwright 1.49 made `launch(headless=True)` — a plain
# p.chromium.launch(), which is what the code does — resolve to
# chrome-headless-shell rather than to Chromium; its registry decides it, not
# the caller, so no amount of grepping the caller could have shown it. Every
# packaged render died on Playwright's own "Executable doesn't exist at …\
# chromium_headless_shell-1234\chrome-headless-shell-win64\…", reported from
# a customer's Windows machine.
#
# What makes trimming it correct AGAIN is core/browser.py: every launch site
# now goes through launch_chromium(), which passes channel="chromium" and so
# runs the full build this bundle does carry. Do not remove that without
# putting the shell back — the two changes are one change.
#
# This can't be done by filtering `datas` before Analysis(): playwright ships
# its OWN PyInstaller hook (playwright/_impl/__pyinstaller/hook-playwright.*
# .py) that PyInstaller runs automatically once playwright.sync_api is
# discovered as a needed import, and that hook calls its own unfiltered
# collect_data_files("playwright") — silently re-adding anything trimmed
# beforehand. Filtering a.datas AFTER Analysis() is the one point past every
# hook's contribution, hook-independent by construction — it survives a
# playwright upgrade that changes what its hook bundles.
#
# TOC entries are (name, path, typecode) — PyInstaller's OWN documented
# order, name (destination) before path (source) — checked against both ends
# since the parts of the path that name the folder can legally land on
# either side depending on which hook contributed the entry.
#
# "playwright" AND the skip pattern, not the skip pattern alone: imageio_ffmpeg
# — Reel's real encoder, bundled separately above — ships its own binary as
# imageio_ffmpeg/binaries/ffmpeg-<platform>-v<version>, which "os.sep +
# 'ffmpeg-'" alone matches just as well as playwright's copy does. An
# unscoped filter would have silently deleted Reel's FFmpeg out of the
# bundle rather than trimming Studio's unused one — caught by inspecting
# what a first, unscoped version of this filter actually matched.
def _pw_keep(toc):
    skip = ("chromium_headless_shell-", os.sep + "ffmpeg-")
    before = len(toc)
    kept = [t for t in toc
           if not (("playwright" in t[0] or "playwright" in t[1])
                   and any(s in t[0] or s in t[1] for s in skip))]
    return kept, before - len(kept)

# The actual chrome-headless-shell and ffmpeg-linux EXECUTABLES don't stay in
# a.datas long enough for the filter above to see them: PyInstaller's own
# "binary vs. data reclassification" pass (every Analysis() runs one) moves
# anything it recognises as an ELF/PE/dylib — which is exactly what these
# are — out of datas and into a.binaries before this spec ever gets control
# back. First cut of this filter only touched a.datas, dropped 287 small
# support files, and left the two actual binaries (chrome-headless-shell,
# libvulkan.so.1, ffmpeg-linux) sitting right where they were — 663MB
# instead of the ~400MB this was supposed to land at. Filtering both TOCs is
# what the reclassification step makes necessary.
a.datas, _pw_dropped_data = _pw_keep(a.datas)
a.binaries, _pw_dropped_bin = _pw_keep(a.binaries)
if _pw_dropped_data or _pw_dropped_bin:
    print(f"[prism] trimmed {_pw_dropped_data + _pw_dropped_bin} unused "
          f"playwright headless-shell/ffmpeg files from the bundle "
          f"({_pw_dropped_data} data, {_pw_dropped_bin} binaries)")

if IS_MAC:
    # Chromium's macOS build is "Google Chrome for Testing.app" — a full
    # NESTED .app bundle (its own Contents/MacOS, Contents/Frameworks, the
    # works) sitting inside playwright's own directory tree. COLLECT()
    # ad-hoc re-signs every entry left in a.binaries one file at a time
    # (osxutils.sign_binary, called from process_collected_binary), and
    # codesign refuses to sign a bundle's inner executable that way:
    # "bundle format unrecognized, invalid, or unsuitable" — it needs the
    # OUTER .app signed as one unit (codesign --deep), not its raw Mach-O
    # binary signed in isolation. That crashed the whole build here, first
    # time this shipped for a real macOS CI run.
    #
    # The fix isn't to sign it correctly at this point — it's to not sign
    # it at all: Google already ships this build with its own valid Apple
    # signature, so PyInstaller's ad-hoc "-s -" was replacing a real
    # signature with a broken attempt at one, not adding a needed one.
    # Reclassifying these entries as DATA makes COLLECT() copy the bytes
    # (mode bits included, so the executable stays executable) with no
    # codesign call at all. packaging/codesign.py's own later pass over the
    # finished .app DOES use --deep, which is bundle-aware and is what
    # actually re-signs this correctly for a real release build.
    _pw_browser_dir = os.sep.join(
        ("playwright", "driver", "package", ".local-browsers"))
    _kept_binaries = []
    for t in a.binaries:
        if _pw_browser_dir in t[0] or _pw_browser_dir in t[1]:
            a.datas.append((t[0], t[1], "DATA"))
        else:
            _kept_binaries.append(t)
    _pw_moved = len(a.binaries) - len(_kept_binaries)
    a.binaries = _kept_binaries
    if _pw_moved:
        print(f"[prism] {_pw_moved} playwright browser binaries moved to "
              f"datas so PyInstaller's ad-hoc signer skips them")

# ── keep the file count under GitHub's 1000-assets-per-release cap ────────
# Every non-empty regular file in the bundle becomes one release asset for
# the in-app updater (packaging/manifest.py refuses a build over 1000).
# 1.4.1's Linux build had 1022 — 30 of them licence texts inside
# *.dist-info/ and 8 of them .pyi type stubs, none of which anything reads
# at runtime. Metadata that IS read at runtime (keyring's entry_points.txt,
# every RECORD/METADATA importlib.metadata resolves) is left alone.
_TRIM_SUFFIXES = (".pyi", ".h", ".c", ".cpp", ".hpp", ".cmake")
_kept_datas, _trimmed, _qt_qm = [], 0, 0
for t in a.datas:
    dest = t[0].replace("\\", "/")
    name = dest.rsplit("/", 1)[-1]
    licence_text = (".dist-info/" in dest
                    and ("/licenses/" in dest or name.upper().startswith(("LICENSE", "COPYING", "NOTICE", "AUTHORS"))
                         or name.lower().endswith((".md", ".rst"))))
    # Qt's own interface translations (qtbase_de.qm and a few hundred like
    # it). Prism never installs a QTranslator — i18n.py explains why it
    # translates its own strings instead — so not one of these is read, and
    # Qt has none for Hindi or Gujarati anyway. They were what pushed 1.5.6
    # over the cap once the picture-reading stack arrived: Linux 1053 files,
    # macOS 1028. Only .qm files go; QtWebEngine's locale packs (.pak) stay.
    qt_translation = "/Qt/translations/" in dest and name.endswith(".qm")
    # Design mockups, concept exploration HTML/JPGs, and raw reference
    # assets that were saved to assets/ but are never read at runtime.
    # The app loads lumi_spritesheet.png, lumi_avatar.png, and lumi_character.png;
    # loose concept cards and raw mockups pushed the release asset count
    # over GitHub's 1000-asset cap on macOS and Linux (see packaging/manifest.py).
    unused_asset = (
        "assets/card_concepts/" in dest
        or "assets/lumi/frames/" in dest
        or "assets/lumi/walk/" in dest
        or name in ("lumi_card_mockup.png", "lumi_card_reference.png", "lumi_logo.png", "lumi_2d.png", "dashboard-bg.png")
    )
    if licence_text or dest.endswith(_TRIM_SUFFIXES) or qt_translation or unused_asset:
        _trimmed += 1
        _qt_qm += qt_translation
        continue
    _kept_datas.append(t)
a.datas = _kept_datas
print(f"[prism] trimmed {_trimmed} licence texts / .pyi stubs / unused Qt "
      f"translations ({_qt_qm} .qm) from datas "
      "(release-asset cap; see packaging/manifest.py)")

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_meta.NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX-packed Qt DLLs are a reliable false-positive magnet
    console=False,      # a GUI app must not flash a terminal on Windows
    disable_windowed_traceback=False,
    argv_emulation=IS_MAC,   # lets Finder "Open with" pass file arguments
    target_arch=None,        # CI builds one arch per runner
    codesign_identity=None,  # unsigned: see BUILD.md for what users must do
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=app_meta.NAME,
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name=f"{app_meta.NAME}.app",
        icon=icon,
        bundle_identifier=app_meta.BUNDLE_ID,
        version=app_meta.VERSION,
        info_plist={
            "CFBundleShortVersionString": app_meta.VERSION,
            "CFBundleVersion": app_meta.VERSION,
            "NSHighResolutionCapable": True,
            # Prism records the user through PyAudio for voice input; without a
            # usage string macOS kills the app the instant it opens the mic.
            "NSMicrophoneUsageDescription":
                "Prism listens for the wake word and transcribes what you say "
                "into a task.",
            "NSAppleEventsUsageDescription":
                "Prism opens Chrome to drive the AI tools you are signed in to.",
            "LSMinimumSystemVersion": "11.0",
        },
    )
