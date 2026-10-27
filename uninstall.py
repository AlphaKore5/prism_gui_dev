"""Remove Prism from this computer, on purpose and without leaving a mess.

Two choices, both asked for by the owner (2026-10-27):

  SCOPE_APP  the program only. Settings, History and every file Prism made stay.
  SCOPE_ALL  the program and Prism's own data folder (settings, licence, History,
             the browser profile). The files Prism made for the person (Artifacts,
             STEP, Gerber, Email, Inquiries, Leads) are removed only when asked.

A running program cannot delete itself, so this builds a small helper script,
starts it detached, and the caller quits Prism. The helper waits for Prism to
exit, deletes exactly the folders in the plan, writes a one-line log, and
removes itself.

Rules that keep this from ever deleting the wrong thing (each has a test):

  - It only runs from an installed build. Run from source it refuses.
  - The program folder is the one holding the running executable, found by
    updater.bundle_root(). The data folder is Prism's own (`.prism`, or a dev
    build's `.prism-dev-home`), by name.
  - A folder of files the person made is removed only if its NAME starts with
    "Prism". If they pointed Artifacts at their Documents folder, that folder
    is left alone and reported as skipped.
  - Nothing is removed that is a drive root, a home folder, or a parent of one.
  - Paths containing quotes or line breaks are refused, because they go into a
    script.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field

SCOPE_APP = "app"
SCOPE_ALL = "all"

#: Per-user files `packaging/install.sh` puts on Linux next to the program.
LINUX_LAUNCHER_FILES = (
    ("~/.local/bin", "prism"),
    ("~/.local/share/applications", "in.alphakore.prism.desktop"),
    ("~/.local/share/icons/hicolor/256x256/apps", "in.alphakore.prism.png"),
)


class Refused(Exception):
    """This must not be removed (or cannot be from here). The text is shown to
    the person, so it says what to do instead."""


@dataclass
class Plan:
    scope: str
    app_dir: str                                   # the program folder (or .app bundle)
    data_dirs: list[str] = field(default_factory=list)      # Prism's own state
    output_dirs: list[str] = field(default_factory=list)    # files made for the person
    extra_files: list[str] = field(default_factory=list)    # Linux launcher entries
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (path, why left alone)

    def everything(self) -> list[str]:
        return [self.app_dir, *self.data_dirs, *self.output_dirs, *self.extra_files]


# ── what is safe to delete ────────────────────────────────────────────────────
def _home_candidates() -> set[str]:
    import channel
    homes = {os.path.abspath(os.path.expanduser("~")), os.path.abspath(channel.real_home())}
    return {h for h in homes if h}


def refuse_reason(path: str) -> str:
    """"" if `path` may be removed, otherwise why not. Pure path rules."""
    if not path or not isinstance(path, str):
        return "no folder given"
    if any(c in path for c in ('"', "\n", "\r", "\0")):
        return "the folder name contains a character that is not safe to pass to a script"
    if not os.path.isabs(path):
        return "the folder is not an absolute path"
    full = os.path.abspath(path)
    drive, rest = os.path.splitdrive(full)
    if rest in ("", os.sep, "/", "\\"):
        return "that is the top of a drive"
    for home in _home_candidates():
        if full == home:
            return "that is the user's home folder"
        if home.startswith(full.rstrip("\\/") + os.sep):
            return "that folder contains the user's home folder"
    if len([p for p in rest.replace("\\", "/").split("/") if p]) < 2:
        return "that folder is too close to the top of the drive"
    return ""


def _is_prisms_own_data(path: str) -> bool:
    import channel
    return os.path.basename(os.path.abspath(path)) in (".prism", channel.DEV_HOME_NAME)


def _looks_like_prisms_output(path: str) -> bool:
    return os.path.basename(os.path.abspath(path)).lower().startswith("prism")


# ── building a plan ───────────────────────────────────────────────────────────
def build_plan(scope: str, *, include_outputs: bool = False,
               output_candidates: list[str] | None = None,
               frozen: bool | None = None, executable: str | None = None,
               data_dir: str | None = None, home: str | None = None,
               platform: str | None = None) -> Plan:
    """What would be removed. Raises Refused when it must not run at all.
    Every argument but `scope` and `include_outputs` exists so tests can point
    it at a temporary folder; the app passes none of them."""
    import paths
    import updater
    if scope not in (SCOPE_APP, SCOPE_ALL):
        raise Refused("Unknown choice.")
    frozen = paths.is_frozen() if frozen is None else frozen
    if not frozen:
        raise Refused("Prism is running from its source files, not as an installed app, "
                      "so there is nothing to uninstall from here.")
    exe = executable or sys.executable
    app_dir = updater.bundle_root(exe)
    why = refuse_reason(app_dir)
    if why:
        raise Refused(f"Prism will not remove {app_dir}: {why}.")
    if not os.path.abspath(exe).startswith(os.path.abspath(app_dir)):
        raise Refused("Prism could not tell which folder holds the running program.")

    plan = Plan(scope=scope, app_dir=os.path.abspath(app_dir))
    plat = platform or sys.platform
    if plat.startswith("linux"):
        base = home or os.path.expanduser("~")
        for folder, name in LINUX_LAUNCHER_FILES:
            candidate = os.path.join(folder.replace("~", base, 1), name)
            if os.path.lexists(candidate):
                plan.extra_files.append(candidate)

    if scope == SCOPE_ALL:
        import channel
        if data_dir:
            mine = data_dir
        else:
            isolated = os.environ.get("PRISM_HOME_ISOLATED", "")
            # A dev build keeps everything in one folder of its own: remove all of it.
            mine = isolated if (isolated and os.path.basename(isolated) == channel.DEV_HOME_NAME) \
                else paths.user_dir()
        mine = os.path.abspath(mine)
        why = refuse_reason(mine)
        if why or not _is_prisms_own_data(mine):
            raise Refused(f"Prism will not remove {mine}: "
                          f"{why or 'it is not recognisably Prism’s own data folder'}.")
        plan.data_dirs.append(mine)
        if include_outputs:
            for candidate in output_candidates or []:
                if not candidate or not os.path.isdir(candidate):
                    continue
                full = os.path.abspath(candidate)
                reason = refuse_reason(full)
                if reason:
                    plan.skipped.append((full, reason))
                elif not _looks_like_prisms_output(full):
                    plan.skipped.append((full, "you chose this folder yourself, and its name does not "
                                               "start with “Prism”, so it may hold other things"))
                elif full not in plan.output_dirs:
                    plan.output_dirs.append(full)
    return plan


# ── the helper that runs after Prism has exited ──────────────────────────────
def posix_script(plan: Plan, pid: int, log_path: str) -> str:
    """The shell script for macOS and Linux."""
    removals = " ".join(shlex.quote(p) for p in [*plan.output_dirs, *plan.data_dirs, plan.app_dir])
    files = " ".join(shlex.quote(p) for p in plan.extra_files)
    lines = [
        "#!/bin/sh",
        "# Written by Prism's uninstaller. Waits for Prism to exit, removes what the plan lists, then itself.",
        "n=0",
        f"while kill -0 {int(pid)} 2>/dev/null && [ $n -lt 120 ]; do sleep 1; n=$((n+1)); done",
        f"rm -rf -- {removals}",
    ]
    if files:
        lines.append(f"rm -f -- {files}")
    lines += [
        f"echo \"Prism was removed on $(date)\" >> {shlex.quote(log_path)}",
        "rm -f -- \"$0\"",
    ]
    return "\n".join(lines) + "\n"


def windows_script(plan: Plan, pid: int, log_path: str) -> str:
    """The batch file for Windows. Retries each removal, because antivirus and
    the shell hold files for a moment after a program exits."""
    def q(path: str) -> str:
        return path.replace("%", "%%")
    out = [
        "@echo off",
        "rem Written by Prism's uninstaller. Waits for Prism to exit, removes what the plan lists, then itself.",
        "set /a waited=0",
        ":wait",
        f'tasklist /FI "PID eq {int(pid)}" 2>nul | find "{int(pid)}" >nul',
        "if not errorlevel 1 (",
        "  set /a waited+=1",
        "  if %waited% LSS 120 (",
        "    ping -n 2 127.0.0.1 >nul",
        "    goto wait",
        "  )",
        ")",
    ]
    for i, path in enumerate([*plan.output_dirs, *plan.data_dirs, plan.app_dir]):
        out += [
            f"set /a tries{i}=0",
            f":again{i}",
            f'if exist "{q(path)}" rmdir /s /q "{q(path)}"',
            f'if exist "{q(path)}" (',
            f"  set /a tries{i}+=1",
            f"  if %tries{i}% LSS 5 (",
            "    ping -n 3 127.0.0.1 >nul",
            f"    goto again{i}",
            "  )",
            ")",
        ]
    out += [
        f'echo Prism was removed on %date% %time% >> "{q(log_path)}"',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(out) + "\r\n"


def start(plan: Plan, *, pid: int | None = None, runner=subprocess.Popen, script_dir: str | None = None) -> str:
    """Write the helper and launch it detached. Returns the script's path. The
    caller must quit Prism straight afterwards; the helper waits for that."""
    for path in plan.everything():
        why = refuse_reason(path)
        if why:
            raise Refused(f"Prism will not remove {path}: {why}.")
    pid = os.getpid() if pid is None else pid
    folder = script_dir or tempfile.gettempdir()
    log_path = os.path.join(folder, "prism-uninstall.log")
    if sys.platform == "win32":
        script = os.path.join(folder, f"prism-uninstall-{pid}.bat")
        with open(script, "w", encoding="utf-8", newline="") as f:
            f.write(windows_script(plan, pid, log_path))
        flags = 0x08000000 | 0x00000008          # CREATE_NO_WINDOW | DETACHED_PROCESS
        runner(["cmd", "/c", script], creationflags=flags, close_fds=True,
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        script = os.path.join(folder, f"prism-uninstall-{pid}.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write(posix_script(plan, pid, log_path))
        os.chmod(script, 0o700)
        runner(["/bin/sh", script], start_new_session=True, close_fds=True,
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return script


def describe(plan: Plan) -> list[tuple[str, str]]:
    """(what, path) lines for the confirmation window."""
    rows = [("The Prism program", plan.app_dir)]
    rows += [("Prism's settings, licence and History", p) for p in plan.data_dirs]
    rows += [("Files Prism made for you", p) for p in plan.output_dirs]
    rows += [("Launcher entry", p) for p in plan.extra_files]
    return rows
