#!/usr/bin/env python3
"""Launch the freshly built app and prove it actually starts.

A PyInstaller build that *completes* tells you nothing: a missed hidden import,
a data file that didn't get bundled or a Qt plugin left behind all produce a
perfectly clean build that dies the instant a user double-clicks it. That is
also the least debuggable failure there is, because a windowed app has no
console to print the traceback to.

So: run the real executable with PRISM_SELFTEST=1, which makes main.py build
the window, verify its resources, and exit with a status. Anything other than a
clean exit fails the build.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile

# Same cp1252 hazard as build.py: this script prints ✓, and it also READS the
# app's UTF-8 self-test output, which a cp1252 decode would reject.
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
sys.path.insert(0, GUI)
import app_meta   # noqa: E402

DIST = os.path.join(GUI, "dist")


def executable() -> str:
    if sys.platform == "darwin":
        inside = os.path.join(DIST, f"{app_meta.NAME}.app", "Contents",
                              "MacOS", app_meta.NAME)
        if os.path.exists(inside):
            return inside
    name = app_meta.NAME + (".exe" if sys.platform.startswith("win") else "")
    return os.path.join(DIST, app_meta.NAME, name)


def main(exe: str | None = None):
    """`exe` defaults to the build in dist/; packaging/windows/installer_check.py
    passes the INSTALLED Prism.exe instead."""
    exe = exe or executable()
    if not os.path.exists(exe):
        sys.exit(f"nothing built at {exe}")

    env = dict(os.environ, PRISM_SELFTEST="1")
    # No display on CI runners; Qt's offscreen platform needs no X server.
    env.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Run against a throwaway home, for two reasons. One, the build machine's
    # own ~/.prism must not change the result. Two — and this is what makes it
    # mandatory — MainWindow opens the Setup dialog MODALLY when no config
    # exists, so on a fresh CI runner the test would block on an invisible
    # dialog until it timed out. Seeding a config takes the configured path,
    # which also exercises config loading for real.
    home = tempfile.mkdtemp(prefix="prism-selftest-")
    os.makedirs(os.path.join(home, ".prism"), exist_ok=True)
    with open(os.path.join(home, ".prism", "config.json"), "w") as f:
        json.dump({"api_key": "selftest-not-a-real-key", "onboarded": True,
                   "profile": "packaging self-test",
                   "agents": {"research": "Perplexity", "content": "ChatGPT"}}, f)
    # expanduser reads HOME on POSIX and USERPROFILE on Windows — set both.
    env["HOME"] = home
    env["USERPROFILE"] = home

    print(f"» {exe} (PRISM_SELFTEST=1, HOME={home})")
    result = subprocess.run([exe], env=env, capture_output=True,
                            encoding="utf-8", errors="replace", timeout=180)
    print(result.stdout.strip())
    if result.stderr.strip():
        print("stderr:", result.stderr.strip()[:4000], file=sys.stderr)
    if result.returncode != 0:
        sys.exit(f"the packaged app failed to start (exit {result.returncode})")
    print("✓ the packaged app starts, loads its resources and builds its window")


if __name__ == "__main__":
    main()
