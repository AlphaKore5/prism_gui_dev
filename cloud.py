"""Cloud drives that are already on the filesystem.

────────────────────────────────────────────────────────────────────────────
Why this exists instead of the Google Drive API
────────────────────────────────────────────────────────────────────────────
The obvious way to let someone attach a file from their Drive is the Google
Picker: the chooser you see inside Gmail. It looks credential-free. It is not
— it runs on an OAuth access token, and there is no way to read a person's
Drive without one. That means a Google Cloud project, a published consent
screen, a client ID shipped in the build, and refresh tokens that expire every
seven days until the screen is out of Testing. All of that, to open a file.

Google Drive for Desktop makes the whole problem disappear. It mounts the
user's Drive as an ordinary folder — on macOS at
~/Library/CloudStorage/GoogleDrive-<email>/My Drive, on Windows usually G:\\.
The files are simply there, under the account they are already signed into,
with Google's own sync client keeping them fresh and Google's own permissions
deciding what they can see. Prism does not need a token, a scope, or a consent
screen to open a file that is already on the disk.

So this module does the small, reliable thing: find those mounts, name them,
and offer them as places to attach from. `integrations/gdrive.py` (the OAuth
route) stays available for anyone who has not installed Drive for Desktop, but
it is no longer the way in.

What this buys, beyond the missing setup:
  · nothing expires — no seven-day reconnection
  · no cap on users, no consent screen review
  · the account is whichever one they are signed into, which is what they
    expect "my Drive" to mean
  · OneDrive, Dropbox and iCloud come free, because they mount the same way

The limitation, stated plainly: a file that is online-only (Drive's "stream"
mode keeps placeholders, not contents) is downloaded by the OS on first read.
That is a pause, not a failure, and it is the same pause Finder gives them.
"""
from __future__ import annotations

import os
import sys

# Folder names Google Drive for Desktop creates inside a mount. "My Drive" is
# the personal root; "Shared drives" is the team one, which in a company is
# usually where the interesting files are.
_GOOGLE_ROOTS = ("My Drive", "Shared drives")


def _exists(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def _google_accounts() -> list[tuple[str, str]]:
    """(label, path) for each signed-in Google Drive for Desktop account.

    A person can be signed into several — a personal Gmail and a work
    Workspace account — and Drive mounts each separately. Both are offered,
    labelled by address, because "which account?" is exactly the question the
    user would otherwise have to answer by guessing.
    """
    found: list[tuple[str, str]] = []
    import paths
    home = paths.real_home()

    # macOS, Drive for Desktop v45+ — one folder per account, named with the
    # address, which is the only place the account is written down.
    cloud = os.path.join(home, "Library", "CloudStorage")
    if _exists(cloud):
        try:
            for name in sorted(os.listdir(cloud)):
                if not name.startswith("GoogleDrive-"):
                    continue
                base = os.path.join(cloud, name)
                email = name.removeprefix("GoogleDrive-")
                for root in _GOOGLE_ROOTS:
                    target = os.path.join(base, root)
                    if _exists(target):
                        label = (f"Google Drive — {email}" if root == "My Drive"
                                 else f"Shared drives — {email}")
                        found.append((label, target))
        except OSError:
            pass

    # Older macOS mounts, and the classic Backup-and-Sync location.
    for legacy in (os.path.join("/Volumes", "GoogleDrive"),
                   os.path.join(home, "Google Drive")):
        if not _exists(legacy):
            continue
        placed = False
        for root in _GOOGLE_ROOTS:
            target = os.path.join(legacy, root)
            if _exists(target):
                found.append((f"Google Drive — {root}", target))
                placed = True
        if not placed:
            found.append(("Google Drive", legacy))

    # Windows: Drive for Desktop takes a drive letter, G: by default but the
    # user can pick any. Probe the plausible ones for the marker folder rather
    # than assuming — a wrong guess here shows a source that does not exist.
    if os.name == "nt":
        for letter in "GHIJKLMNOPQRSTUVWXYZ":
            for root in _GOOGLE_ROOTS:
                target = f"{letter}:\\{root}"
                if _exists(target):
                    found.append((f"Google Drive ({letter}:) — {root}", target))
        mydrive = os.path.join(home, "My Drive")
        if _exists(mydrive):
            found.append(("Google Drive", mydrive))
    return found


def _other_clouds() -> list[tuple[str, str]]:
    """OneDrive, Dropbox and iCloud, which mount exactly the same way.

    Included because the reason to support Drive is "the file is in the
    cloud, not on this laptop", and that is just as true of the other three.
    Excluding them would be an arbitrary loyalty to one vendor.
    """
    import paths
    home = paths.real_home()
    found: list[tuple[str, str]] = []

    cloud = os.path.join(home, "Library", "CloudStorage")
    if _exists(cloud):
        try:
            for name in sorted(os.listdir(cloud)):
                base = os.path.join(cloud, name)
                if not _exists(base):
                    continue
                if name.startswith("OneDrive-"):
                    found.append((f"OneDrive — {name.removeprefix('OneDrive-')}",
                                  base))
                elif name.startswith("Dropbox"):
                    found.append(("Dropbox", base))
        except OSError:
            pass

    for label, path in (
        ("OneDrive", os.path.join(home, "OneDrive")),
        ("Dropbox", os.path.join(home, "Dropbox")),
        ("iCloud Drive", os.path.join(home, "Library", "Mobile Documents",
                                      "com~apple~CloudDocs")),
    ):
        if _exists(path) and not any(p == path for _l, p in found):
            found.append((label, path))
    return found


def sources() -> list[dict]:
    """Every cloud folder on this machine, Google first.

    [{"label": "Google Drive — ravi@firm.com", "path": "/…", "kind": "google"}]

    Google leads because it is the one people ask for by name; the rest follow
    so the menu is "where is the file" rather than "Google or not".
    """
    out = [{"label": label, "path": path, "kind": "google"}
           for label, path in _google_accounts()]
    out += [{"label": label, "path": path, "kind": "other"}
            for label, path in _other_clouds()]

    # A path can be reached two ways (a symlink at ~/Google Drive pointing into
    # CloudStorage is common). Offer each real folder once.
    seen, unique = set(), []
    for entry in out:
        key = os.path.realpath(entry["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def google_sources() -> list[dict]:
    return [s for s in sources() if s["kind"] == "google"]


def has_google() -> bool:
    return bool(google_sources())


def install_hint() -> str:
    """What to tell someone who wants Drive and has not got it mounted."""
    where = ("google.com/drive/download" if sys.platform in ("darwin", "win32")
             else "google.com/drive/download (not available on Linux — use the "
                  "web and download the file first)")
    return (
        "Google Drive isn't set up on this computer yet.\n\n"
        "Install Google Drive for Desktop from " + where + " and sign in. "
        "Your Drive then appears as an ordinary folder, and Prism can attach "
        "straight from it — no extra setup, nothing to connect, and it stays "
        "signed in.")
