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
licence and runs.

How it isolates (changed 2026-10-27, RELEASE_ISSUES.md ISS-009): it replaces
Python's os.path.expanduser so "~" means the dev data folder, and leaves the
process environment ALONE. It used to set HOME and USERPROFILE, which also
moved Windows' own idea of Downloads, Documents and Desktop (they are defined
through %USERPROFILE%), so file pickers on a dev build lost those folders.
Everything that computes ~/.prism from Python, engine and GUI alike, import
time or call time, still lands in the dev folder; native code (Qt, the Windows
shell) keeps seeing the real home. Use real_home() for anything the USER
should see in a picker.
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


def _make_expanduser(original, home: str):
    """An expanduser that answers "~" and "~/x" with `home`, and defers for
    everything else ("~someone" included). Pure, so it can be tested without
    touching the process."""
    def expanduser(path):
        p = os.fspath(path)
        if isinstance(p, bytes):
            if p == b"~" or p.startswith((b"~/", b"~\\")):
                return os.fsencode(home) + p[1:]
            return original(p)
        if p == "~" or p.startswith(("~/", "~\\")):
            return home + p[1:]
        return original(p)
    expanduser._prism_home = home
    expanduser._prism_original = original
    return expanduser


_HOOK = None        # the expanduser this module installed, if any (compared by identity)


def _original_expanduser():
    """The real os.path.expanduser, whether or not our hook is installed. By
    identity, not by attribute: a test's mock answers every attribute lookup."""
    current = os.path.expanduser
    if _HOOK is not None and current is _HOOK:
        return _HOOK._prism_original
    return current


def _install_hook(home: str) -> None:
    global _HOOK
    current = os.path.expanduser
    if _HOOK is not None and current is _HOOK and _HOOK._prism_home == home:
        return
    _HOOK = _make_expanduser(_original_expanduser(), home)
    os.path.expanduser = _HOOK


def remove_hook() -> None:
    """Undo _install_hook. For tests; a running app never needs it."""
    global _HOOK
    if _HOOK is not None and os.path.expanduser is _HOOK:
        os.path.expanduser = _HOOK._prism_original
    _HOOK = None


def real_home(environ=None) -> str:
    """The user's real home folder, whatever isolation is active. Start file
    pickers and visible default folders here, never in the data folder.

    With no argument (the app) this is exactly what os.path.expanduser("~")
    gave before isolation existed, so an ordinary build behaves as it always
    did. A dev build records the real home in PRISM_REAL_HOME before it
    replaces expanduser. A private dict (tests) is read as an environment."""
    original = _original_expanduser()
    if environ is None:
        return os.environ.get("PRISM_REAL_HOME") or original("~")
    return (environ.get("PRISM_REAL_HOME") or environ.get("USERPROFILE")
            or environ.get("HOME") or original("~"))


def isolate_home(environ=None, *, install=None) -> str:
    """Point Prism's idea of "~" at a private folder, if this is a dev build or
    a source checkout asked to via PRISM_HOME. Returns that folder, or "" when
    nothing changed.

    Must be called before the first import that reads `~` (main.py does it
    before PySide6 and the engine load). Idempotent.

    The process environment is not modified (see the module docstring), apart
    from two markers a child process can read: PRISM_HOME_ISOLATED and
    PRISM_REAL_HOME. `install` defaults to "only when working on the real
    environment"; tests that pass their own dict leave Python untouched.

    A prod build ignores PRISM_HOME entirely: a customer's environment must
    not be able to move the folder their licence lives in.
    """
    env = os.environ if environ is None else environ
    do_install = (environ is None) if install is None else install
    requested = env.get("PRISM_HOME", "")
    marked = env.get("PRISM_HOME_ISOLATED", "")

    if marked:                               # a second call, or a child process
        target = marked
    elif is_dev():
        target = requested or os.path.join(real_home(env), DEV_HOME_NAME)
    elif requested and not _frozen():
        target = requested
    else:
        return ""

    if not os.path.isabs(target):
        raise ValueError(f"PRISM_HOME must be an absolute path, got {target!r}")
    os.makedirs(target, exist_ok=True)
    env.setdefault("PRISM_REAL_HOME", real_home(env))
    env["PRISM_HOME_ISOLATED"] = target
    if do_install:
        _install_hook(target)
    return target
