"""Which release channel this build belongs to, and keeping a dev build away
from the developer's real Prism data.

`CHANNEL` is fixed when a build is made, like `updater.UPDATE_HOST`: the build
script rewrites the line below to "dev" for a dev build. It is never read from
the environment or from a server, so a customer's prod build cannot be turned
into a dev one. See docs/UPDATE-SYSTEM.md.

Why isolate_home() exists: Prism keeps everything under ~/.prism, and the
engine (prism_terminal/core/config.py, automation.py, ffmpeg.py) computes that
path from os.path.expanduser("~") when it is imported. A dev build running on
a tester's machine would otherwise read and overwrite their real config.json,
licence and runs. Pointing HOME/USERPROFILE somewhere else, before anything is
imported, redirects the GUI, the engine and prospector at once without editing
any of them.
"""
from __future__ import annotations

import os
import sys

CHANNEL = "prod"          # "prod" | "dev" — rewritten by the build, not at runtime

DEV_HOME_NAME = ".prism-dev-home"


def is_dev() -> bool:
    return CHANNEL == "dev"


def _frozen() -> bool:
    # paths.is_frozen() would be the obvious call, but importing paths here
    # would run before the home is isolated. These are the same two markers.
    return bool(getattr(sys, "frozen", False)) or "__compiled__" in globals()


def isolate_home(environ=None) -> str:
    """Point the process's home directory at a private folder, if this is a
    dev build or a source checkout asked to via PRISM_HOME. Returns the new
    home, or "" when nothing changed.

    Must be called before the first import that reads `~` (main.py does it
    before PySide6 and the engine load). Idempotent.

    A prod build ignores PRISM_HOME entirely: a customer's environment must
    not be able to move the folder their licence lives in.
    """
    env = os.environ if environ is None else environ
    if env.get("PRISM_HOME_ISOLATED"):       # a child process, or a second call
        return env["PRISM_HOME_ISOLATED"]
    requested = env.get("PRISM_HOME", "")

    if is_dev():
        target = requested or os.path.join(_real_home(env), DEV_HOME_NAME)
    elif requested and not _frozen():
        target = requested
    else:
        return ""

    if not os.path.isabs(target):
        raise ValueError(f"PRISM_HOME must be an absolute path, got {target!r}")
    os.makedirs(target, exist_ok=True)
    env["HOME"] = target
    env["USERPROFILE"] = target          # os.path.expanduser on Windows reads this
    env.pop("HOMEPATH", None)
    env.pop("HOMEDRIVE", None)
    env["PRISM_HOME_ISOLATED"] = target
    return target


def _real_home(env) -> str:
    return env.get("USERPROFILE") or env.get("HOME") or os.path.expanduser("~")
