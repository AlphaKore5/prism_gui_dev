"""Where Prism's files live, in both of the two worlds it runs in.

Run from a checkout, everything sits next to this module. Run from a packaged
app, PyInstaller has unpacked the same files into a temporary folder it points
at with sys._MEIPASS, and __file__ no longer says anything useful about where
the data went. Every read of a bundled asset — fonts, the stylesheet, the logo,
the engine's notes files — has to go through resource() so the same code works
frozen and unfrozen.

Note the split this module keeps honest:
  · resource()  — read-only things we ship. Inside the app bundle. Wiped and
                  re-extracted on every launch of a onefile build, so nothing
                  written here survives.
  · user_dir()  — everything the user owns (config, runs, the Chrome profile).
                  Always ~/.prism, identical for the CLI and the packaged app,
                  so installing the app doesn't orphan a CLI user's setup.
"""
from __future__ import annotations
import os
import sys


def is_frozen() -> bool:
    """True in ANY packaged build — PyInstaller or Nuitka.

    Deliberately not `hasattr(sys, "_MEIPASS")`: that marker is PyInstaller's
    alone, so a Nuitka build reported "running from source" and switched on
    three bypasses at once — the DEVELOPMENT signing key (licensing/keys.py,
    which calls it "a universal skeleton key for the whole product"),
    PRISM_LICENSE_OFFLINE_DEV (licensing/__init__.py) and PRISM_LICENSE_SERVER
    (licensing/client.py). The app would start and run normally, which is what
    made it dangerous. build.py recommends Nuitka *for tamper resistance*, so
    the engine someone reaches for to harden the app was the one that opened it.
    """
    if "__compiled__" in globals():                 # Nuitka standalone
        return True
    return bool(getattr(sys, "frozen", False))      # PyInstaller


def bundle_dir() -> str:
    """Root of the read-only payload: _MEIPASS when frozen, else the repo.

    Must not read sys._MEIPASS unconditionally on the frozen branch — under
    Nuitka is_frozen() is now True and that attribute does not exist.
    """
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        return meipass
    return os.path.dirname(os.path.abspath(__file__))


def resource(*parts: str) -> str:
    """Absolute path to a file we ship, e.g. resource('assets', 'fonts')."""
    return os.path.join(bundle_dir(), *parts)


def user_dir(*parts: str) -> str:
    """Absolute path inside ~/.prism — the user's own state, never bundled."""
    return os.path.join(_home_dir(), ".prism", *parts)


def _home_dir() -> str:
    """The user's home directory — guaranteed absolute, guaranteed stable.

    os.path.expanduser("~") can silently fail to expand. On Windows that
    happens when neither USERPROFILE nor HOMEPATH is set — a scheduled task, a
    service account, some app-virtualisation and remote-execution wrappers
    that never load a profile. On POSIX it happens when HOME is unset AND the
    passwd database has no entry for the running uid — some sandboxed or
    containerised desktop environments. Either way expanduser returns the
    literal two characters "~", unchanged, and nothing downstream notices:
    os.path.join treats "~" as an ordinary folder NAME, not a substitution
    that failed. ~/.prism then silently becomes a RELATIVE folder that
    follows the current working directory — launch Prism from two different
    places (two shortcuts, a scheduled autostart entry vs. a desktop icon, an
    updater relaunching it from its own folder) and it is two different
    folders, with two different licence files and two different device ids.
    A customer who definitely activated once keeps being asked for the key,
    on every launch that does not happen to share the first one's working
    directory — which reads as "the licence just isn't checked".

    The fallbacks below are the same sources expanduser itself tries on
    Windows, checked directly, and — failing all of them — an anchor beside
    the app rather than the working directory. That last one may not be
    where a real home directory would have been, but it is at least the SAME
    place on every launch, which is the actual property this function exists
    to guarantee.
    """
    home = os.path.expanduser("~")
    if home != "~" and os.path.isabs(home):
        return home
    for var in ("USERPROFILE", "HOME"):
        value = os.environ.get(var)
        if value and os.path.isabs(value):
            return value
    homepath = os.environ.get("HOMEPATH")
    if homepath:
        candidate = os.environ.get("HOMEDRIVE", "") + homepath
        if os.path.isabs(candidate):
            return candidate
    return os.path.join(app_root(), ".prism-home")


def real_home() -> str:
    """The user's real home folder, even in a dev build whose "~" means its own
    data folder (see channel.py). Use this for anything the person should be
    able to open themselves; use user_dir() for Prism's own private state."""
    import channel
    return channel.real_home()


def user_folder(*parts: str) -> str:
    """A visible folder under the user's real home, e.g. user_folder("Prism Email").
    In an ordinary build this is exactly what os.path.expanduser("~") gave."""
    return os.path.join(real_home(), *parts)


def desktop_dir() -> str:
    """<real home>/Desktop. Deliberately the plain path, not the shell's answer,
    so an ordinary build keeps writing exactly where it always did."""
    return os.path.join(real_home(), "Desktop")


def picker_start_dir() -> str:
    """Where a file or folder chooser should open: the user's real Downloads,
    else Documents, else their real home.

    Never the folder the app happens to run from (a frozen build's working
    directory is its install folder) and never a dev build's data folder: a
    chooser that opens somewhere empty reads as "Prism cannot see my files".
    Asks the operating system for the folder first, so a Downloads folder the
    user moved is found; falls back to the real home channel.real_home() keeps.
    """
    try:
        from PySide6.QtCore import QStandardPaths
        for where in (QStandardPaths.DownloadLocation, QStandardPaths.DocumentsLocation):
            folder = QStandardPaths.writableLocation(where)
            if folder and os.path.isdir(folder):
                return folder
    except Exception:                                  # noqa: BLE001 - Qt missing or not started
        pass
    import channel
    home = channel.real_home()
    for name in ("Downloads", "Documents"):
        folder = os.path.join(home, name)
        if os.path.isdir(folder):
            return folder
    return home


def ensure_user_dir() -> str:
    """Create ~/.prism owner-only, and tighten it if an older build did not.

    Call once at startup. Tightening the ROOT is the whole fix: a 0700 parent
    cannot be traversed by anyone else, so runs/, logs/, workspace/ and
    gui_favorites.json are covered without chasing each writer — every one of
    them creates its directory with the default mode, which under the usual
    0002 umask is 0775.

    The credentials themselves were never the problem: config.json,
    license.json, authorization.json and device_id are all written 0600. What
    sat at 0664 was the work — customer queries, BOQ outputs, run records —
    and device.py names shared workstations as a target deployment.

    Best-effort by design. A failure here must not stop the app starting; on
    Windows the mode is largely advisory anyway.
    """
    path = user_dir()
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
        os.chmod(path, 0o700)       # exist_ok=True ignores mode on an existing dir
    except OSError:
        pass
    return path


def is_local_result(url: str) -> bool:
    """A stage result that is a FILE on this machine, not a tool's tab.

    Local agents (the reel renderer) hand back a path where every scraped
    stage hands back a URL, and the UI treats the two the same everywhere —
    so a path was being fed to QUrl(), which has no scheme to open and fails
    silently. Anything that opens a result has to ask this first.
    """
    return bool(url) and "://" not in url and os.path.exists(url)


def open_result(url: str) -> None:
    """Open a stage result — a file with its default app, a URL in Chrome."""
    if not isinstance(url, (str, bytes, os.PathLike)) or not url:
        return
    url = str(url)
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(
        QUrl.fromLocalFile(url) if is_local_result(url) else QUrl(url))


def open_file(path: str) -> bool:
    """Open a file or folder in the machine's own default app — Preview or
    Photos for a picture, Excel for a sheet, Finder or Explorer for a folder.

    Each platform's own opener, not Qt's QDesktopServices: on a packaged Mac
    and Windows build the Qt route returned without doing anything for local
    files (a picture in STEP's Files tab did nothing on click), while `open`
    and `os.startfile` are what the OS itself uses and are what Reel's Play
    already relies on. Returns False if nothing could be started; falls back
    to Qt as a last resort."""
    if not isinstance(path, (str, bytes, os.PathLike)) or not path:
        return False
    path = os.path.normpath(str(path))
    if not os.path.exists(path):
        return False
    import subprocess
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: F821  (Windows-only API)
        else:
            env = os.environ.copy()
            # A parent editor's private library path must not reach the
            # viewer (see scrub_environment below).
            env.pop("LD_LIBRARY_PATH", None)
            env.pop("LD_PRELOAD", None)
            subprocess.Popen(["xdg-open", path], env=env)
        return True
    except Exception:                                   # noqa: BLE001
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        except Exception:                               # noqa: BLE001
            return False


def reveal_result(path: str) -> None:
    """Show the file in Finder/Explorer. Worth its own button because output
    lands in ~/.prism/runs, and a dot-folder is invisible in Finder — a user
    who is told the path still cannot get to it."""
    if not isinstance(path, (str, bytes, os.PathLike)) or not path:
        return
    path = str(path)
    import subprocess
    folder = os.path.dirname(path)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path])
        elif os.name == "nt":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception:
        open_result(folder)


# Variables a snap's launcher exports for ITS app, that are poison to any
# ordinary program started underneath it. Each names libraries, modules or
# schemas inside the snap, built against the snap's own glibc.
_SNAP_ONLY = ("GTK_PATH", "GIO_MODULE_DIR", "GTK_EXE_PREFIX",
              "GTK_IM_MODULE_FILE", "GSETTINGS_SCHEMA_DIR", "LOCPATH")
_SNAP_PATH_LISTS = ("LD_LIBRARY_PATH", "XDG_DATA_DIRS")


def scrub_environment() -> list:
    """Make os.environ safe to hand to a child process. Returns what changed.

    Everything Prism opens for the owner — the finished reel in their video
    player, a folder in the file manager, a result in the browser — starts
    as a child of Prism and inherits Prism's environment. Two things put
    poison in it, and both surfaced as the child dying rather than as
    anything about Prism:

      · PyInstaller points LD_LIBRARY_PATH at its own bundle so the frozen
        app finds the libraries it ships, and stashes the real value in
        LD_LIBRARY_PATH_ORIG. A video player started from a frozen Prism
        loads Prism's bundled libstdc++/glib instead of the system's.
        core.browser already undoes this for Chromium alone.
      · A snap (VS Code's, on 2026-09-07) exports GTK_PATH & co. into its
        terminals, and an app started from such a terminal — Prism, from a
        dev checkout — passes them on. The deb VLC then loaded the snap's
        GTK modules, built against the snap's glibc, and died on
        `libpthread.so.0: undefined symbol: __libc_pthread_init`. Pressing
        Play on a finished reel produced that, and nothing said why.

    Safe to do to Prism's OWN environment, at startup: the dynamic loader
    read LD_LIBRARY_PATH once when the process began and does not consult
    os.environ again, so a library Prism loads later still resolves as it
    did — only children see the change. Qt's openUrl(), xdg-open and every
    Popen inherit os.environ, so one scrub covers them all.

    Left alone when Prism itself IS the snap: those variables are then
    correct, and removing them would break Prism.
    """
    changed = []
    if not sys.platform.startswith("linux"):
        return changed
    env = os.environ

    original = env.pop("LD_LIBRARY_PATH_ORIG", None)
    if original is not None:
        env["LD_LIBRARY_PATH"] = original
        changed.append("LD_LIBRARY_PATH")
    elif is_frozen() and "LD_LIBRARY_PATH" in env:
        del env["LD_LIBRARY_PATH"]
        changed.append("LD_LIBRARY_PATH")

    if env.get("SNAP_NAME") and not sys.executable.startswith("/snap/"):
        for var in _SNAP_ONLY:
            if "/snap/" in env.get(var, ""):
                del env[var]
                changed.append(var)
        # The VS Code snap keeps the pre-snap value beside its own; anything
        # else gets the snap entries filtered out of the list.
        kept_orig = env.pop("XDG_DATA_DIRS_VSCODE_SNAP_ORIG", None)
        if kept_orig and "/snap/" in env.get("XDG_DATA_DIRS", ""):
            env["XDG_DATA_DIRS"] = kept_orig
            changed.append("XDG_DATA_DIRS")
        for var in _SNAP_PATH_LISTS:
            value = env.get(var, "")
            if "/snap/" not in value:
                continue
            # ":" not os.pathsep: these are Linux variables (a snap exists
            # nowhere else), and on the Windows CI runner os.pathsep is ";"
            # — which left the whole list as one "/snap/" entry and deleted
            # it, the one red test on the Windows lane for two releases.
            kept = [p for p in value.split(":") if p and "/snap/" not in p]
            if kept:
                env[var] = ":".join(kept)
            else:
                del env[var]
            if var not in changed:
                changed.append(var)
    return changed


def app_root() -> str:
    """The directory holding the executable (frozen) or the sources (dev).
    Used for logs and for telling the user where the app actually is."""
    if is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))
