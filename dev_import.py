"""Bring a normal Prism's settings into a development build.

A dev build keeps its own data folder (channel.py), so on first launch it is a
brand-new install: no Groq key (the microphone and every AI step need it), no
logged-in browser profile (so tasks that upload files to an AI site stop at a
login page), no traced folders, no History. Testers read that as a dozen
different bugs (RELEASE_ISSUES.md ISS-012). This copies the useful parts across.

Read-only on the source: nothing in the normal Prism's folder is ever written,
moved or deleted. Never copied, on purpose: the licence and authorisation files,
the device id and the update state, because those belong to one install and
sharing them is exactly what a separate folder prevents.
"""
from __future__ import annotations

import os
import shutil

import channel
import paths

#: choice -> (label, files, folders) relative to the data folder (~/.prism)
CHOICES = {
    "settings": ("Settings, Groq key and agents", ("config.json", "gui_favorites.json"), ()),
    "logins": ("Browser logins (so uploads to AI sites work)", (), ("chrome_profile",)),
    "history": ("History of past tasks", (), ("runs",)),
    "tools": ("Downloaded tools (ffmpeg and similar)", (), ("tools",)),
}

#: never copied, whatever is asked
NEVER = ("license.json", "authorization.json", "device_id", "update_state.json", "updates", "logs")
#: lock files a running Chrome leaves behind; copying them makes the profile look in use
SKIP_NAMES = ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile")


def source_dir() -> str:
    """The normal Prism's data folder: the real home's .prism."""
    return os.path.join(channel.real_home(), ".prism")


def dest_dir() -> str:
    return paths.user_dir()


def applicable() -> bool:
    """Only a dev build, and only when a normal install's data exists."""
    if not channel.is_dev():
        return False
    src, dst = source_dir(), dest_dir()
    return os.path.isdir(src) and os.path.abspath(src) != os.path.abspath(dst)


def sizes(src: str | None = None) -> dict[str, int]:
    """Bytes available per choice, 0 when absent. Walks folders, so call it off the UI thread for big ones."""
    src = src or source_dir()
    out = {}
    for key, (_label, files, folders) in CHOICES.items():
        total = 0
        for name in files:
            p = os.path.join(src, name)
            if os.path.isfile(p):
                total += os.path.getsize(p)
        for name in folders:
            for root, _dirs, names in os.walk(os.path.join(src, name)):
                for n in names:
                    try:
                        total += os.path.getsize(os.path.join(root, n))
                    except OSError:
                        pass
        out[key] = total
    return out


def copy(choices: list[str], src: str | None = None, dst: str | None = None) -> dict:
    """Copy the chosen parts. Returns {"copied": [...], "missing": [...], "backed_up": [...]}.
    An existing file in the destination is kept as <name>.before-import first."""
    src = os.path.abspath(src or source_dir())
    dst = os.path.abspath(dst or dest_dir())
    if src == dst:
        raise ValueError("The source and the destination are the same folder.")
    if not os.path.isdir(src):
        raise FileNotFoundError("There is no normal Prism data folder to copy from.")
    os.makedirs(dst, exist_ok=True)
    result = {"copied": [], "missing": [], "backed_up": []}
    for key in choices:
        if key not in CHOICES:
            raise ValueError(f"Unknown choice: {key}")
        _label, files, folders = CHOICES[key]
        for name in files:
            if name in NEVER:
                continue
            a, b = os.path.join(src, name), os.path.join(dst, name)
            if not os.path.isfile(a):
                result["missing"].append(name)
                continue
            if os.path.exists(b):
                shutil.copy2(b, b + ".before-import")
                result["backed_up"].append(name)
            shutil.copy2(a, b)
            try:
                os.chmod(b, 0o600)
            except OSError:
                pass
            result["copied"].append(name)
        for name in folders:
            if name in NEVER:
                continue
            a, b = os.path.join(src, name), os.path.join(dst, name)
            if not os.path.isdir(a):
                result["missing"].append(name)
                continue
            shutil.copytree(a, b, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*SKIP_NAMES), symlinks=True)
            result["copied"].append(name)
    return result
