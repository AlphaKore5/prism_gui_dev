"""Swap a staged update into place — the one step in the whole in-app-update
design that runs OUTSIDE the process being replaced.

Nothing in this module downloads or verifies anything; by the time any
function here runs, updater.py has already: verified the manifest's
signature, checked it isn't expired, checked it's for a version newer than
anything seen before, downloaded every changed file, verified every file's
hash, and re-verified the WHOLE staged tree against the manifest one more
time. This module's only job is the mechanical part: get the running Prism
out of the way, move the verified tree into its place, and come back up as
the new version — or put everything back exactly as it was if that doesn't
work cleanly.

Why this can't happen inside the process being replaced: on Windows, a
running .exe and every DLL it has loaded are locked by the OS for as long as
the process is alive (see update-research-inapp-download.md §2) — nothing
running AS that process can rename its own directory out from under itself.
The fix used here, and by every serious self-updater surveyed in
update-research.md (Squirrel, Sparkle, electron-updater, Firefox), is the
same: something OUTSIDE the install folder waits for the old PID to exit,
does the swap, and starts the new build.

On Linux and macOS that something is Prism itself, relaunched with a hidden
flag in a new detached process — the folder can be renamed out from under a
running process there, so this is safe and it is the path the tests
exercise. See main.py's `--prism-apply-update` handling.

On WINDOWS it cannot be Prism, and for a year it was: the helper was
Prism.exe, started from inside the very directory it then tried to rename,
which Windows refuses while an executable in it is running. Every Windows
in-app update therefore staged perfectly, swapped nothing, relaunched
nothing, and left the customer opening the same version — with no log to say
so. The Windows path now writes a small script to ~/.prism/updates and runs
it through cmd.exe (see _WIN_HELPER), which is what
update-research-inapp-download.md specified in the first place.

╔══════════════════════════════════════════════════════════════════════════╗
║ UNVERIFIED ON REAL WINDOWS/macOS HARDWARE — read before touching this.    ║
║                                                                            ║
║ This module was written and tested on Linux only. The Linux swap path    ║
║ (rename a directory out from under a running process) is genuinely       ║
║ tested here — Linux lets you do that, no special handling needed. The    ║
║ Windows and macOS code paths below are implemented per the design in     ║
║ update-research-inapp-download.md §2/§5.4, but TWO assumptions they      ║
║ depend on have never been exercised on real hardware:                    ║
║                                                                            ║
║   Windows: the helper is now an external .bat (the in-process one could  ║
║   never have worked — see the docstring above), but how long antivirus   ║
║   or the PyInstaller bootloader holds a lock on the folder AFTER the     ║
║   process exits is still unmeasured. Both the .bat and perform_swap()    ║
║   retry for ~60s before giving up and leaving everything as it was.      ║
║   ~/.prism/logs/update-apply.log now records which of those happened.    ║
║                                                                            ║
║   macOS: does a .app bundle written to disk by another running app       ║
║   (rather than downloaded via a browser) pick up the same Gatekeeper/    ║
║   quarantine treatment a browser download gets? Untested. (Expected not  ║
║   to: only apps that opt in via LSFileQuarantineEnabled tag what they    ║
║   write, and shutil.copy2 does not carry xattrs on macOS.) What IS fixed ║
║   is the unit being swapped — updater.install_dir() now returns the      ║
║   whole `Prism.app`, never `Contents/MacOS` (that rename gutted the      ║
║   bundle), and the pending marker sits beside the bundle, not inside it. ║
║                                                                            ║
║ Do not remove this banner or treat either path as proven until both      ║
║ have actually been run on the hardware in question.                      ║
╚══════════════════════════════════════════════════════════════════════════╝

Known scope cut (documented, not hidden): startup-success confirmation here
is self-reported — the newly-relaunched Prism has to run far enough to call
confirm_startup_success() before its next restart, or the next launch treats
it as failed and rolls back. This catches "the new version starts and then
crashes" and "the new version never gets past licensing/import". It does NOT
catch "the OS refuses to start the new executable at all" (e.g. a missing
shared library making the process exit before a single line of Python
runs) — that would need a supervisor process watching the relaunched PID's
exit code, which is deferred; see update-plan.md's Phase 3 list.
"""
from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import time

PENDING_MARKER = ".prism_update_pending"


def log_path() -> str:
    """Where the swap writes what it did.

    The swap is the one step that runs with no Prism and no window, and
    until now it wrote nothing at all: a Windows update that staged
    perfectly and then silently failed to swap left the customer reopening
    the same version with no trace anywhere of why. Its own small log, in
    the folder every other Prism log lives in.
    """
    # PRISM_APPLY_LOG exists for the test suite, which must never write
    # into the developer's own ~/.prism.
    return (os.environ.get("PRISM_APPLY_LOG")
            or os.path.join(os.path.expanduser("~"), ".prism", "logs",
                            "update-apply.log"))


def note(line: str) -> None:
    """Append one line to the apply log. Never raises — a swap must not fail
    because it could not describe itself."""
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {line}\n")
    except OSError:
        pass


def _tidy_staging(staged_dir: str) -> None:
    """Remove what staging leaves behind once the swap has moved the tree.

    Staging now happens beside the install (updater.stage_root), so the
    leftover `<version>.VERSION` file and the empty staging folder would
    otherwise sit next to Prism.app or the install folder for ever. rmdir,
    not rmtree: the folder is removed only if the swap really emptied it.
    """
    base = staged_dir.rstrip(os.sep)
    for suffix in (".VERSION", ".token"):     # .token: updater.mark_ready's signed copy
        try:
            os.remove(base + suffix)
        except OSError:
            pass
    try:
        os.rmdir(os.path.dirname(base))
    except OSError:
        pass


def _move(src: str, dst: str) -> None:
    """Rename — or, ONLY when the two are on different volumes, copy and delete.

    `os.rename` fails with EXDEV across volumes, and a portable Prism on D:
    with its profile on C: is exactly that. shutil.move does the copy there.

    It must not do so for any other error, and the first version did. A
    rename refused because one file inside was still locked (antivirus, a
    straggling process) became a copy followed by a delete that stopped at
    the first locked file — leaving the live install holding that one file
    and nothing else, with no restore run. A rename is atomic: refused means
    nothing moved, so every other error goes back to perform_swap's retry
    loop untouched.
    """
    try:
        os.rename(src, dst)
    except OSError as e:
        cross_volume = (e.errno == errno.EXDEV
                        # ERROR_NOT_SAME_DEVICE, when Windows reports it raw.
                        or getattr(e, "winerror", None) == 17)
        if not cross_volume:
            raise
        shutil.move(src, dst)


class ApplyError(Exception):
    """The swap itself failed — the old tree is put back if at all
    possible before this is raised, so a bad update degrades to "nothing
    happened" rather than "Prism is now broken until reinstalled"."""


# ── is a process still alive? ───────────────────────────────────────────────
def pid_alive(pid: int) -> bool:
    """True if `pid` is a live process on this machine.

    Windows and POSIX genuinely need different mechanisms here — os.kill's
    signal-0 trick (POSIX: "would this signal be delivered") has no Windows
    equivalent, and os.kill on Windows only supports terminating a process,
    not probing one. The Windows branch below is part of the UNVERIFIED
    Windows path this module's docstring warns about; the POSIX branch is
    the one exercised by this module's own tests.
    """
    if sys.platform == "win32":
        # `import ctypes` alone does NOT make ctypes.wintypes available — it
        # is a submodule that must be imported by name. In the bare
        # --prism-apply-update helper nothing else has imported it, so the
        # DWORD() below raised AttributeError, perform_apply_and_relaunch()'s
        # catch-all swallowed it, and on Windows every in-app update through
        # 1.4.2 staged perfectly, then never swapped and never relaunched:
        # the customer reopened the same exe and was still on the old
        # version. Under pytest the attribute happened to exist (some other
        # import had loaded the submodule), which is why the Windows test
        # lane never saw it. tests/test_apply_update.py now runs this in a
        # bare interpreter.
        import ctypes
        import ctypes.wintypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.wintypes.DWORD()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(
                handle, ctypes.byref(exit_code))
            return bool(ok) and exit_code.value == STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Alive, just owned by someone else — still "alive" for our purposes.
        return True
    return True


def wait_for_exit(pid: int, timeout: float = 30.0, poll: float = 0.2) -> bool:
    """Block until `pid` is gone or `timeout` elapses. Returns whether it
    actually exited — a caller must not proceed to swap files a still-live
    process might have open."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(poll)
    return not pid_alive(pid)


# ── the swap itself ──────────────────────────────────────────────────────
def perform_swap(install_dir: str, staged_dir: str, backup_dir: str, *,
                 retry_seconds: float = 30.0, retry_interval: float = 1.0) -> None:
    """Rename `install_dir` to `backup_dir`, then `staged_dir` to
    `install_dir`. Two renames, not one atomic operation — the same
    limitation every folder-swap updater surveyed in update-research.md
    accepts, because there is no cross-platform atomic "swap two
    directories" primitive. The retry loop is what update-plan.md §9 calls
    out for Windows specifically (antivirus or a lingering handle can hold a
    rename briefly); on Linux this normally succeeds on the first try.

    Raises ApplyError, with the old tree restored to `install_dir` if the
    second rename is what failed (the first rename succeeding but the second
    failing is the one partial-failure state this function must not leave on
    disk — "old build gone, new build not in place" is worse than either
    all-old or all-new).
    """
    if os.path.exists(backup_dir):
        # A backup from a previous update that was never cleaned up (e.g. the
        # confirm step never ran and a rollback already happened once) —
        # clear it rather than fail the whole swap over stale housekeeping.
        shutil.rmtree(backup_dir, ignore_errors=True)

    deadline = time.monotonic() + retry_seconds
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        try:
            _move(install_dir, backup_dir)
            break
        except OSError as e:
            last_error = e
            time.sleep(retry_interval)
    else:
        note(f"could not move aside {install_dir!r}: {last_error}")
        raise ApplyError(f"Could not move aside {install_dir!r} after "
                         f"{retry_seconds:.0f}s (still in use?): {last_error}")

    try:
        _move(staged_dir, install_dir)
    except OSError as e:
        # The one bad partial state: put the old tree straight back.
        note(f"could not move the new version into place: {e}")
        try:
            _move(backup_dir, install_dir)
        except OSError as restore_error:
            raise ApplyError(
                f"Update swap failed AND could not restore the previous "
                f"install: {e}; restore error: {restore_error}. The install "
                f"at {install_dir!r} may be missing — reinstall from "
                f"{staged_dir!r} or a fresh download.") from e
        raise ApplyError(f"Could not move the new version into place "
                         f"({e}); restored the previous version.") from e


# ── startup-success confirmation & rollback ────────────────────────────────
def confirm_marker_path(install_dir: str) -> str:
    """Where the "swapped in, not yet confirmed" marker lives.

    Inside the install folder for a plain onedir tree. BESIDE it for a macOS
    `.app`: the bundle's code-signature seal covers everything under
    `Contents/`, and Gatekeeper treats a bundle with unexpected files as
    "damaged" — a marker written into the bundle by the previous launch is
    exactly the kind of thing that turns a good update into "Prism.app is
    damaged and can't be opened" on the very next start.
    """
    if install_dir.rstrip(os.sep).endswith(".app"):
        return install_dir.rstrip(os.sep) + PENDING_MARKER
    return os.path.join(install_dir, PENDING_MARKER)


LAUNCHED_LINE = "launched"


def mark_pending_confirm(install_dir: str, from_version: str) -> None:
    """Written right after a successful swap, before relaunching.

    Two-phase, and the second phase is what makes an update survive its own
    first launch. The marker starts as just the outgoing version. The first
    startup of the swapped-in build finds it WITHOUT a "launched" line,
    appends one, and carries on — that launch is the one being judged. If
    the build gets as far as the main window it calls
    confirm_startup_success() and the marker goes. If instead the NEXT
    startup finds the marker WITH "launched" already in it, the previous
    launch never confirmed and the backup goes back.

    The one-phase version of this — "any marker at startup means roll
    back" — was the bug that made every in-app update through 1.4.1 undo
    itself: the new build's very first launch was the one that found the
    marker, and it rolled itself back before a single window opened.
    """
    with open(confirm_marker_path(install_dir), "w", encoding="utf-8") as f:
        f.write(from_version.strip() + "\n")


def pending_update_version(install_dir: str) -> str:
    """The version named in the "swapped in, not yet confirmed" marker, or ""
    when no swap is waiting for its first confirmed start.

    NOTE the marker holds the version that was swapped IN (stage_update writes
    the incoming version to <stage>.VERSION, which is what gets recorded), even
    though mark_pending_confirm()'s parameter is called from_version. Use this
    only to learn "this launch is the first after an update"; the version the
    update started from is updater.staged_from(). Read it BEFORE
    confirm_startup_success(), which removes the marker."""
    try:
        with open(confirm_marker_path(install_dir), encoding="utf-8") as f:
            first = f.readline().strip()
        return "" if first == LAUNCHED_LINE else first
    except OSError:
        return ""


def is_pending_confirm(install_dir: str) -> bool:
    return os.path.isfile(confirm_marker_path(install_dir))


def _marker_was_launched(install_dir: str) -> bool:
    try:
        with open(confirm_marker_path(install_dir), encoding="utf-8") as f:
            return LAUNCHED_LINE in f.read().split()
    except OSError:
        return False


def _note_launched(install_dir: str) -> None:
    try:
        with open(confirm_marker_path(install_dir), "a", encoding="utf-8") as f:
            f.write(LAUNCHED_LINE + "\n")
    except OSError:
        pass


def confirm_startup_success(install_dir: str, backup_dir: str) -> None:
    """Call once the new version has gotten far enough to trust — main.py
    calls this after the main window is up. Clears the marker and drops the
    kept-for-one-launch backup; never raises, since failing to tidy up a
    backup must not be treated as a startup failure."""
    try:
        os.remove(confirm_marker_path(install_dir))
    except OSError:
        pass
    if os.path.isdir(backup_dir):
        shutil.rmtree(backup_dir, ignore_errors=True)


def check_and_rollback_if_pending(install_dir: str, backup_dir: str) -> bool:
    """Call at the very start of a normal launch, before anything else that
    could fail. If the previous launch swapped in a version and never
    confirmed it started, put the backup back and report True so the caller
    can surface a "the last update didn't take, we rolled it back" banner.

    A failed update must never be worse than never having offered the
    update-plan.md's S5 — this is what makes that true.

    Returns False on the FIRST launch after a swap (see mark_pending_confirm
    for the two-phase marker) and True only when a previous launch already
    had its chance and never confirmed.
    """
    if not is_pending_confirm(install_dir):
        return False
    if not _marker_was_launched(install_dir):
        # This IS the first launch after the swap — the one under judgement.
        # Note it and let startup proceed; confirm_startup_success() clears
        # the marker once the window is up, and a launch that never gets
        # there leaves "launched" behind for the next one to act on.
        _note_launched(install_dir)
        return False
    try:
        os.remove(confirm_marker_path(install_dir))
    except OSError:
        pass
    if not os.path.isdir(backup_dir):
        # Nothing to roll back to — the marker is stale/orphaned. Leave the
        # (apparently working, since we got this far) current install alone.
        return False
    broken_dir = install_dir + ".failed-update"
    shutil.rmtree(broken_dir, ignore_errors=True)
    try:
        os.rename(install_dir, broken_dir)
        os.rename(backup_dir, install_dir)
    except OSError:
        # Could not even roll back — leave things as they are rather than
        # risk destroying the one tree that might still work.
        return False
    shutil.rmtree(broken_dir, ignore_errors=True)
    return True


# ── spawning the detached apply helper ─────────────────────────────────────
def spawn_detached(argv: list[str], cwd: str | None = None,
                   no_window: bool = False) -> None:
    """Launch `argv` as a process with no lifetime tie to the current one —
    get this wrong (e.g. a plain subprocess.Popen with no flags, whose child
    is killed alongside its parent's process group on some platforms/shells)
    and the swap helper dies the instant Prism calls QApplication.quit(),
    before it has waited for the PID or moved anything. See this module's
    top docstring for why POSIX is the branch actually exercised by tests
    here and Windows is not.

    `no_window` is for a console script on Windows. DETACHED_PROCESS gives
    cmd.exe no console at all, so each tasklist/find/ping it runs opens a
    console window of its own — two minutes of windows flashing up while
    the swap waits. CREATE_NO_WINDOW gives it one hidden console its
    children share.
    """
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP
            | (subprocess.CREATE_NO_WINDOW if no_window
               else subprocess.DETACHED_PROCESS))
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, cwd=cwd, **kwargs)


#: The Windows swap, as a script that lives OUTSIDE the folder being
#: replaced.
#:
#: This is the fix for "the update downloads, Prism restarts, and it is still
#: the old version". The helper used to be Prism.exe itself, relaunched with
#: a hidden flag — from inside the very directory it then tried to rename.
#: Windows will not rename a directory that contains a running executable, so
#: the rename failed every time, the retry loop ran its 30 seconds, the
#: helper exited with a code nobody could see, and nothing was ever swapped
#: or relaunched. update-research-inapp-download.md said so from the start:
#: "write a detached apply.bat … have the EXTERNAL script wait for the PID to
#: die, then ren Prism Prism.old and move the staged tree into place."
#:
#: Written to ~/.prism/updates, which is never the folder being swapped.
#:
#: Three details that each decide whether it works at all:
#:   · `cd /d "%~dp0"` first, and cwd= on the spawn. cmd.exe otherwise
#:     inherits Prism's working folder — the install folder, when Prism was
#:     started from Explorer or the Start menu — and Windows will not rename
#:     a folder that is some process's current directory. Every move would
#:     be refused for exactly the reason this script exists to avoid.
#:   · `chcp 65001`. The file is written as UTF-8 and cmd.exe reads a batch
#:     file in the console's code page, so a profile folder like "Jürgen"
#:     would turn every path in the script into a different one.
#:   · If the install cannot be moved aside, the old version is started
#:     again: the customer already closed Prism, and leaving them with no
#:     window at all is worse than the update not happening.
_WIN_HELPER = """@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enableextensions
set "LOG={log}"
>>"%LOG%" echo [%date% %time%] apply starting (pid {pid})

set "VER="
if exist "{verfile}" set /p VER=<"{verfile}"

set /a waited=0
:waitloop
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if errorlevel 1 goto gone
set /a waited+=1
if %waited% GEQ 120 goto neverleft
ping -n 2 127.0.0.1 >nul
goto waitloop

:neverleft
>>"%LOG%" echo [%time%] the old Prism never exited - nothing was changed
exit /b 1

:gone
if exist "{backup}" rmdir /s /q "{backup}"
set /a tries=0
:moveaside
move "{install}" "{backup}" >>"%LOG%" 2>&1
if not errorlevel 1 goto movedaside
set /a tries+=1
if %tries% GEQ 30 goto stuck
ping -n 2 127.0.0.1 >nul
goto moveaside

:stuck
>>"%LOG%" echo [%time%] could not move the install aside - nothing was changed, starting it again
start "" "{exe}"
exit /b 2

:movedaside
move "{staged}" "{install}" >>"%LOG%" 2>&1
if errorlevel 1 goto restore
>"{marker}" echo(%VER%
if exist "{verfile}" del /q "{verfile}" >nul 2>&1
rmdir "{stagingparent}" >nul 2>&1
>>"%LOG%" echo [%time%] swapped in, starting the new version
start "" "{exe}"
exit /b 0

:restore
>>"%LOG%" echo [%time%] could not move the new version in - putting the old one back
move "{backup}" "{install}" >>"%LOG%" 2>&1
start "" "{exe}"
exit /b 3
"""


def _windows_helper_dir() -> str:
    return os.path.join(os.path.expanduser("~"), ".prism", "updates")


def write_windows_helper(pid_to_wait: int, install_dir: str, staged_dir: str,
                         backup_dir: str, exe: str) -> str:
    """Write the .bat that performs the swap. Returns its path, or "".

    Separated from begin_apply() so it can be read and checked by a test on
    any platform — the thing that went wrong here was never visible in a
    Linux test run, and a script generated but never inspected is the same
    trap one level down.
    """
    try:
        folder = _windows_helper_dir()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "apply.bat")
        with open(path, "w", encoding="utf-8") as f:
            f.write(_WIN_HELPER.format(
                log=log_path(), pid=int(pid_to_wait),
                verfile=staged_dir.rstrip(os.sep) + ".VERSION",
                stagingparent=os.path.dirname(staged_dir.rstrip(os.sep)),
                install=install_dir.rstrip(os.sep),
                staged=staged_dir.rstrip(os.sep),
                backup=backup_dir.rstrip(os.sep),
                marker=confirm_marker_path(install_dir),
                exe=exe))
        return path
    except OSError as e:
        note(f"could not write the Windows helper: {e}")
        return ""


def begin_apply(pid_to_wait: int, install_dir: str, staged_dir: str,
                backup_dir: str, relaunch_argv: list[str]) -> None:
    """Called by the OLD (currently running) Prism, right before it quits.
    Spawns a detached copy of itself with the special flag; does not wait for
    anything itself — the caller must call QApplication.quit() (or exit)
    immediately after this returns, so the old process's own locks/handles
    are released for the new one to wait on.
    """
    note(f"asked to swap {staged_dir!r} into {install_dir!r} "
         f"(pid {pid_to_wait}, {sys.platform})")
    if sys.platform == "win32":
        # The helper must not live inside the folder it is about to rename —
        # see _WIN_HELPER. Only if the script cannot be written at all does
        # this fall back to the old in-place route, which is better than
        # nothing on a machine where ~/.prism is unwritable.
        script = write_windows_helper(pid_to_wait, install_dir, staged_dir,
                                      backup_dir,
                                      relaunch_argv[0] if relaunch_argv else "")
        if script:
            spawn_detached(["cmd.exe", "/c", script],
                           cwd=os.path.dirname(script), no_window=True)
            return
        note("falling back to the in-process helper — this cannot rename a "
             "folder that holds a running exe, and will most likely fail")
    helper_argv = [*relaunch_argv, "--prism-apply-update", str(pid_to_wait),
                  install_dir, staged_dir, backup_dir]
    spawn_detached(helper_argv)


def perform_apply_and_relaunch(pid_to_wait: int, install_dir: str,
                               staged_dir: str, backup_dir: str,
                               relaunch_argv: list[str]) -> int:
    """The detached helper's entire job, called from main.py's
    `--prism-apply-update` branch before QApplication is constructed.
    Returns a process exit code; never raises past this function (a helper
    that crashes with a traceback and no rollback is the worst outcome this
    whole design exists to avoid).
    """
    try:
        if not wait_for_exit(pid_to_wait, timeout=30.0):
            return 1  # old process never exited; leave everything alone.

        # updater.stage_update() writes the outgoing version to a sibling
        # `<staged_dir>.VERSION` file — not inside staged_dir itself, since
        # everything inside staged_dir is about to become the new
        # install_dir and must match the manifest's file list exactly.
        version = ""
        try:
            with open(staged_dir.rstrip(os.sep) + ".VERSION", "r",
                     encoding="utf-8") as f:
                version = f.read().strip()
        except OSError:
            pass

        perform_swap(install_dir, staged_dir, backup_dir)
        mark_pending_confirm(install_dir, version)
        _tidy_staging(staged_dir)
        note(f"swapped in {version or 'the new version'} — relaunching")
        spawn_detached(relaunch_argv)
        return 0
    except ApplyError as e:
        note(f"swap failed, previous version left in place: {e}")
        return 2
    except Exception as e:  # noqa: BLE001 - this process has no UI to report to
        note(f"swap helper crashed: {e}")
        return 3
