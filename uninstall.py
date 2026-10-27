"""Remove Prism from this computer, on purpose and without leaving a mess.

Two choices, exactly as the owner put it (2026-10-28): "uninstall should uninstall
Prism only, and if the user wants, delete it with all Prism-stored files: logs and
folders stored by Prism only."

  SCOPE_APP  the program only (and the updater's leftovers beside it). Settings,
             licence, History, logs and every file Prism made stay.
  SCOPE_ALL  the program, Prism's own data folder (settings, licence, History, logs,
             the browser profile), the licence key saved in the system's credential
             store, and the folders Prism created on its own in their usual places
             (Prism Artifacts, Prism Step, Prism Gerber, Prism Email, Prism Inquiries,
             Prism Leads), with the files in them. Nothing else.

A running program cannot delete itself, so this builds a small helper script,
starts it detached, and the caller quits Prism. The helper waits for Prism to
exit, deletes exactly the folders in the plan, writes a one-line log, and
removes itself.

Rules that keep this from ever deleting the wrong thing (each has a test):

  - It only runs from an installed build. Run from source it refuses.
  - The program folder is the one holding the running executable, found by
    updater.bundle_root(). The data folder is Prism's own (`.prism`, or a dev
    build's `.prism-dev-home`), by name.
  - A folder of made files is removed only if Prism chose it: one of the usual
    places, whose name starts with "Prism". A folder the person picked in
    Settings is never removed, whatever it is called ("Prism Photos" may be
    theirs); it is listed as left alone.
  - The team's shared workspace is never removed, whatever its name, and the
    data folder is not removed if the workspace lives inside it. Paths are
    compared after resolving case and links, so on Windows two spellings of
    one folder that differ only in capitals are the same folder.
  - A development build shares the made-file folders and the saved licence key
    with the normal Prism on the same computer, so it removes neither.
  - If Prism is still running when the helper stops waiting, nothing is removed.
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

#: What a Prism program folder may hold, besides the executable itself (packaging/build.py,
#: apply_update.py). Anything else means the folder is shared with the person's own files: the
#: Desktop or Downloads a build's contents were copied into. Then the folder is never deleted.
PROGRAM_FOLDER_ENTRIES = ("_internal", "install.sh", "in.alphakore.prism.desktop", "in.alphakore.prism.png",
                          ".prism_update_pending", ".prism-write-probe")

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
    extra_files: list[str] = field(default_factory=list)    # Linux launcher entries, update markers
    leftovers: list[str] = field(default_factory=list)      # Prism-named folders the updater left beside the program
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (path, why left alone)
    forget_licence: bool = False                   # also remove the key from the credential store

    def everything(self) -> list[str]:
        return [self.app_dir, *self.leftovers, *self.data_dirs, *self.output_dirs, *self.extra_files]


# ── what is safe to delete ────────────────────────────────────────────────────
def _home_candidates() -> set[str]:
    """The real home folder(s). Not a dev build's "~", which channel.py points at
    the dev data folder: that folder is exactly what "everything" removes there."""
    import channel
    homes = {os.path.abspath(channel._original_expanduser()("~")), os.path.abspath(channel.real_home())}
    return {h for h in homes if h}


def _norm(path: str) -> str:
    """One spelling per folder: resolved links, and Windows' case folded."""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.path.expanduser(str(path).strip()))))


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


# ── the folders Prism creates ─────────────────────────────────────────────────
def prism_folders(cfg: dict | None, config_module=None) -> tuple[list[str], list[str], list[str]]:
    """(folders Prism created on its own, folders the person chose, folders never to remove).

    Prism's own are the usual places it writes made files when nobody chose
    otherwise; they hold files from before a setting changed too. The person's
    choices are only ever listed as left alone. Logs need nothing here: they
    live in the data folder."""
    import output_folders
    import paths
    cfg = cfg or {}
    engine_default = output_folders.engine_default(config_module) if config_module is not None else ""
    fallback = getattr(config_module, "FALLBACK_ARTIFACTS_DIR", "") if config_module is not None else ""
    own = _unique([
        engine_default, fallback, paths.user_folder("Prism Artifacts"),
        output_folders.usual_dir("artifacts"), output_folders.usual_dir("step"), output_folders.usual_dir("gerber"),
        paths.user_folder("Prism Email"), paths.user_folder("Prism Inquiries"),
        paths.user_folder("Documents", "Prism Leads"),
    ])
    mine = {_norm(f) for f in own}
    chosen = [f for f in _unique([
        output_folders.configured(cfg, "artifacts"), output_folders.configured(cfg, "step"),
        output_folders.configured(cfg, "gerber"),
        str((cfg.get("email") or {}).get("folder") or ""), str((cfg.get("inquiry") or {}).get("folder") or ""),
    ]) if _norm(f) not in mine]
    protected = _unique([str(cfg.get("workspace_root") or "")])
    return own, chosen, protected


def _unique(folders) -> list[str]:
    seen, out = set(), []
    for folder in folders:
        folder = str(folder or "").strip()
        if folder and _norm(folder) not in seen:
            seen.add(_norm(folder))
            out.append(os.path.abspath(os.path.expanduser(folder)))
    return out


def _overlaps(a: str, b: str) -> bool:
    a, b = _norm(a).rstrip("\\/"), _norm(b).rstrip("\\/")
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


def _inside(inner: str, outer: str) -> bool:
    inner, outer = _norm(inner).rstrip("\\/"), _norm(outer).rstrip("\\/")
    return inner == outer or inner.startswith(outer + os.sep)


# ── building a plan ───────────────────────────────────────────────────────────
def build_plan(scope: str, *, output_candidates: list[str] | None = None,
               chosen: list[str] | None = None, protect: list[str] | None = None,
               frozen: bool | None = None, executable: str | None = None,
               data_dir: str | None = None, home: str | None = None,
               platform: str | None = None) -> Plan:
    """What would be removed. Raises Refused when it must not run at all.
    `output_candidates`, `chosen` and `protect` come from prism_folders(); every other
    argument exists so tests can point
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

    app_dir = os.path.abspath(app_dir)
    if not app_dir.endswith(".app"):
        # The program folder must hold Prism and nothing else. If Prism's files were copied straight
        # into the Desktop or Downloads, deleting "the folder holding the program" would delete
        # everything in it.
        mine = {os.path.basename(exe), *PROGRAM_FOLDER_ENTRIES}
        others = sorted(e for e in os.listdir(app_dir) if e not in mine)
        if others:
            shown = ", ".join(others[:5]) + (f" and {len(others) - 5} more" if len(others) > 5 else "")
            raise Refused(f"The folder {app_dir} holds other things besides Prism ({shown}), so Prism will "
                          f"not delete it. Remove Prism by deleting {os.path.basename(exe)} and the _internal "
                          f"folder yourself.")

    plan = Plan(scope=scope, app_dir=app_dir)
    # What the updater leaves beside the program: its previous version, its staging folder, its marker.
    parent = os.path.dirname(app_dir)
    for candidate in (app_dir + ".old", os.path.join(parent, ".prism-update-staging")):
        if os.path.isdir(candidate) and not refuse_reason(candidate):
            plan.leftovers.append(candidate)
    marker = app_dir + ".prism_update_pending"
    if os.path.isfile(marker) and not refuse_reason(marker):
        plan.extra_files.append(marker)
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
        for shared in protect or []:
            if _inside(shared, mine):
                raise Refused(f"Your team's shared workspace ({shared}) is inside Prism's data folder {mine}, "
                              f"so removing that folder would remove the workspace too. Move the workspace "
                              f"in Settings first, or choose “Uninstall Prism”.")
        plan.data_dirs.append(mine)
        dev = os.path.basename(mine) == channel.DEV_HOME_NAME
        # The key in the credential store is shared with the normal Prism on this computer.
        plan.forget_licence = not dev
        for candidate in output_candidates or []:
            if not candidate or not os.path.isdir(candidate):
                continue
            full = os.path.abspath(candidate)
            reason = refuse_reason(full)
            if _inside(full, mine) or _inside(full, plan.app_dir):
                continue                                  # removed with the data or the program anyway
            if reason:
                plan.skipped.append((full, reason))
            elif dev:
                plan.skipped.append((full, "a development build shares this folder with your normal Prism"))
            elif any(_overlaps(full, p) for p in (protect or [])):
                plan.skipped.append((full, "this is your team's shared workspace, which other people use"))
            elif not _looks_like_prisms_output(full):
                plan.skipped.append((full, "its name does not start with “Prism”, so it may hold other things"))
            elif _inside(mine, full) or _inside(plan.app_dir, full):
                plan.skipped.append((full, "it holds the Prism program or Prism's data folder"))
            elif not any(_norm(full) == _norm(d) for d in plan.output_dirs):
                plan.output_dirs.append(full)
        for folder in chosen or []:
            if folder and os.path.isdir(folder) and not any(_overlaps(folder, d) for d in plan.output_dirs):
                plan.skipped.append((os.path.abspath(folder), "you chose this folder in Settings, so Prism leaves "
                                                              "it and the files in it alone"))
    return plan


# ── the helper that runs after Prism has exited ──────────────────────────────
def posix_script(plan: Plan, pid: int, log_path: str, wait: int = 120) -> str:
    """The shell script for macOS and Linux."""
    removals = " ".join(shlex.quote(p) for p in [*plan.output_dirs, *plan.data_dirs, *plan.leftovers, plan.app_dir])
    files = " ".join(shlex.quote(p) for p in plan.extra_files)
    lines = [
        "#!/bin/sh",
        "# Written by Prism's uninstaller. Waits for Prism to exit, removes what the plan lists, then itself.",
        "n=0",
        f"while kill -0 {int(pid)} 2>/dev/null && [ $n -lt {int(wait)} ]; do sleep 1; n=$((n+1)); done",
        # Still running: removing a program in use leaves half of it. Remove nothing.
        f"if kill -0 {int(pid)} 2>/dev/null; then echo \"Prism was still running on $(date); nothing was removed\" "
        f">> {shlex.quote(log_path)}; rm -f -- \"$0\"; exit 1; fi",
        f"rm -rf -- {removals}",
    ]
    if files:
        lines.append(f"rm -f -- {files}")
    lines += [
        f"echo \"Prism was removed on $(date)\" >> {shlex.quote(log_path)}",
        "rm -f -- \"$0\"",
    ]
    return "\n".join(lines) + "\n"


def windows_script(plan: Plan, pid: int, log_path: str, wait: int = 120) -> str:
    """The batch file for Windows. Retries each removal, because antivirus and
    the shell hold files for a moment after a program exits."""
    def q(path: str) -> str:
        return path.replace("%", "%%")
    # The file is UTF-8 and cmd reads a batch file in the console's code page,
    # so a path like C:\Users\José would be misread; chcp 65001 first.
    # Windows' own tools by full path: a Git or MSYS `find` earlier on PATH
    # would make a running Prism look gone.
    sys32 = r"%SystemRoot%\System32"
    out = [
        "@echo off",
        "chcp 65001 >nul",
        "rem Written by Prism's uninstaller. Waits for Prism to exit, removes what the plan lists, then itself.",
        "set /a waited=0",
        ":wait",
        f'{sys32}\\tasklist.exe /FI "PID eq {int(pid)}" 2>nul | {sys32}\\find.exe "{int(pid)}" >nul',
        "if not errorlevel 1 (",
        "  set /a waited+=1",
        f"  if %waited% LSS {int(wait)} (",
        f"    {sys32}\\ping.exe -n 2 127.0.0.1 >nul",
        "    goto wait",
        "  )",
        ")",
        # Still running: removing a program in use leaves half of it. Remove nothing.
        f'{sys32}\\tasklist.exe /FI "PID eq {int(pid)}" 2>nul | {sys32}\\find.exe "{int(pid)}" >nul',
        "if not errorlevel 1 goto stillrunning",
    ]
    for i, path in enumerate([*plan.output_dirs, *plan.data_dirs, *plan.leftovers, plan.app_dir]):
        out += [
            f"set /a tries{i}=0",
            f":again{i}",
            f'if exist "{q(path)}" rmdir /s /q "{q(path)}"',
            f'if exist "{q(path)}" (',
            f"  set /a tries{i}+=1",
            f"  if %tries{i}% LSS 5 (",
            f"    {sys32}\\ping.exe -n 3 127.0.0.1 >nul",
            f"    goto again{i}",
            "  )",
            ")",
        ]
    for path in plan.extra_files:
        out.append(f'if exist "{q(path)}" del /f /q "{q(path)}"')
    out += [
        f'echo Prism was removed on %date% %time% >> "{q(log_path)}"',
        '(goto) 2>nul & del "%~f0"',
        ":stillrunning",
        f'echo Prism was still running on %date% %time%; nothing was removed >> "{q(log_path)}"',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(out) + "\r\n"


def start(plan: Plan, *, pid: int | None = None, runner=subprocess.Popen, script_dir: str | None = None,
          wait: int = 120, forget=None) -> str:
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
            f.write(windows_script(plan, pid, log_path, wait))
        # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: a hidden console, not none
        # (DETACHED_PROCESS), because chcp needs one. A child outlives Prism either way.
        flags = 0x08000000 | 0x00000200
        # cwd: Windows will not delete a folder that is any process's working folder, and a
        # double-clicked Prism's working folder is usually its own program folder.
        cmd = os.environ.get("ComSpec") or os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "cmd.exe")
        runner([cmd, "/c", script], creationflags=flags, close_fds=True, cwd=folder,
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        script = os.path.join(folder, f"prism-uninstall-{pid}.sh")
        with open(script, "w", encoding="utf-8") as f:
            f.write(posix_script(plan, pid, log_path, wait))
        os.chmod(script, 0o700)
        runner(["/bin/sh", script], start_new_session=True, close_fds=True, cwd=folder,
               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if plan.forget_licence:
        # Only once the helper is running: if it could not start, Prism stays and still works.
        if forget is None:
            from licensing import secretstore
            forget = secretstore.forget_key
        forget()
    return script


def describe(plan: Plan) -> list[tuple[str, str]]:
    """(what, path) lines for the confirmation window."""
    rows = [("The Prism program", plan.app_dir)]
    rows += [("Left over from an earlier update", p) for p in plan.leftovers]
    rows += [("Prism's settings, licence, History and logs", p) for p in plan.data_dirs]
    if plan.forget_licence:
        rows.append(("The licence key saved in this computer's credential store", "Prism (Alphakore)"))
    rows += [("A folder Prism created, with the files in it", p) for p in plan.output_dirs]
    rows += [("Launcher entry", p) for p in plan.extra_files]
    return rows
