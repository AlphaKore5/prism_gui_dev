#!/usr/bin/env python3
"""Pre-release check. Run it before any release commit or tag:

    python3 devtools/prerelease_check.py            # quick: everything but the suite
    python3 devtools/prerelease_check.py --suite    # also the whole test suite

It exists because 1.6.2 shipped two stale copies of addons/inquiry/dialog.py and
quotation.py that silently overwrote the pipeline-board work: the Email
inquiries screen crashed on open, and nothing in the release process looked at
what had DISAPPEARED between two releases. Exit status 0 = every automatic check
passed; the manual list at the end is still yours to tick.

Checks
  1  git      clean tree, on main, level with origin, engine commit is on the
              engine's origin/main (push the engine first)
  2  version  VERSION is newer than the last release tag and CHANGES.md has it
  3  removed  every function/class/test that existed in the last release and is
              GONE now — a stale overwrite shows up here at once. Intentional
              removals go in devtools/prerelease_removed_ok.txt, one
              "path::name" per line, with a reason in a comment above it.
  4  contract main_window only passes enter()/signals what the targets accept
              (the 1.6.2 crash), and the Speak button is still wired
  5  selftest PRISM_SELFTEST=1 offscreen
  6  suite    (--suite) one pytest process per file; failures are compared with
              devtools/prerelease_known_failures.txt — a NEW failure blocks
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

# A Windows console is not UTF-8: the ✓/✗ below would raise UnicodeEncodeError.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            pass

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / ".venv" / "bin" / "python"
if not PY.exists():
    PY = ROOT / ".venv" / "Scripts" / "python.exe"
PY = str(PY) if PY.exists() else sys.executable

WATCHED = ("addons", "widgets", "dialogs", "licensing", "tests")
WATCHED_FILES = ("core_bridge.py", "main_window.py", "workers.py", "updater.py",
                 "inquiry_config.py", "email_config.py", "theme.py", "wakeword.py")

results: list[tuple[str, bool, str]] = []


def say(ok: bool, name: str, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("  ✓ " if ok else "  ✗ ") + name + (f"\n      {detail}" if detail and not ok else ""))


def git(*args: str, cwd: Path = ROOT, check: bool = False) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout.strip()


# ── 1 git ─────────────────────────────────────────────────────────────────
def check_git() -> None:
    print("1  git")
    dirty = git("status", "--porcelain")
    say(not dirty, "working tree clean", dirty[:400])
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    say(branch == "main", f"on main (on {branch})")
    git("fetch", "-q")
    behind = git("rev-list", "--count", "HEAD..origin/main")
    say(behind == "0", f"not behind origin/main ({behind} behind) — pull first",
        "rebase onto origin/main, never merge")
    engine = ROOT / "prism_terminal"
    if engine.exists():
        git("fetch", "-q", cwd=engine)
        pinned = git("rev-parse", "HEAD", cwd=engine)
        on_origin = subprocess.run(
            ["git", "merge-base", "--is-ancestor", pinned, "origin/main"],
            cwd=engine).returncode == 0
        say(on_origin, "engine commit is on the engine's origin/main",
            f"{pinned[:8]} is not pushed — push prism_terminal BEFORE prism_gui")
        edirty = git("status", "--porcelain", cwd=engine)
        say(not edirty, "engine working tree clean", edirty[:200])


# ── 2 version ─────────────────────────────────────────────────────────────
def last_release() -> str:
    tags = git("tag", "--sort=-v:refname").splitlines()
    for t in tags:
        if re.fullmatch(r"v\d+\.\d+\.\d+", t):
            return t
    return ""


def vtuple(v: str) -> tuple:
    return tuple(int(x) for x in v.lstrip("v").split("."))


def check_version(tag: str) -> None:
    print("2  version")
    text = (ROOT / "app_meta.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([\d.]+)"', text, re.M)
    ver = m.group(1) if m else ""
    say(bool(ver) and (not tag or vtuple(ver) > vtuple(tag)),
        f"VERSION {ver} is newer than the last release {tag}")
    changes = (ROOT / "CHANGES.md").read_text(encoding="utf-8")
    say(re.search(rf"^# {re.escape(ver)}\b", changes, re.M) is not None,
        f"CHANGES.md has an entry for {ver}")


# ── 3 removed ─────────────────────────────────────────────────────────────
def names_in(source: str) -> set[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out: set[str] = set()

    def walk(node, prefix=""):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + child.name
                out.add(q)
                if isinstance(child, ast.ClassDef):
                    walk(child, q + ".")
    walk(tree)
    return out


def allowed_removals() -> set[str]:
    p = ROOT / "devtools" / "prerelease_removed_ok.txt"
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.lstrip().startswith("#")}


def watched_paths(tag: str) -> list[str]:
    files = git("ls-tree", "-r", "--name-only", tag).splitlines()
    return [f for f in files if f.endswith(".py") and (
        f in WATCHED_FILES or any(f.startswith(d + "/") for d in WATCHED))]


def check_removed(tag: str) -> None:
    print(f"3  removed since {tag or '(no release tag)'}")
    if not tag:
        say(True, "no earlier release to compare with")
        return
    ok_list = allowed_removals()
    gone: list[str] = []
    for f in watched_paths(tag):
        old = subprocess.run(["git", "show", f"{tag}:{f}"], cwd=ROOT,
                             capture_output=True, text=True).stdout
        path = ROOT / f
        if not path.exists():
            # A whole-file removal is allowed by listing the bare path (the
            # list's own entries for dialogs/ai_directory_dialog.py etc. do).
            if f not in ok_list:
                gone.append(f"{f}  (the whole file)")
            continue
        new = path.read_text(encoding="utf-8", errors="replace")
        for name in sorted(names_in(old) - names_in(new)):
            if f"{f}::{name}" not in ok_list:
                gone.append(f"{f}::{name}")
    say(not gone, f"nothing that shipped in {tag} has vanished",
        "\n      ".join(gone[:40]) + (f"\n      … and {len(gone) - 40} more" if len(gone) > 40 else "")
        + "\n      If a removal is deliberate, add it to devtools/prerelease_removed_ok.txt "
          "with the reason.")


# ── 4 contract ────────────────────────────────────────────────────────────
def check_contract() -> None:
    print("4  contract between the main window and its screens")
    import inspect
    src = (ROOT / "main_window.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "enter"
             and isinstance(n.func.value, ast.Attribute)
             and n.func.value.attr == "inquiry_work_panel"]
    dialog_src = (ROOT / "addons" / "inquiry" / "dialog.py").read_text(encoding="utf-8")
    dt = ast.parse(dialog_src)
    params: set[str] = set()
    for n in ast.walk(dt):
        if isinstance(n, ast.FunctionDef) and n.name == "enter":
            params = {a.arg for a in n.args.args + n.args.kwonlyargs}
    bad = [kw.arg for c in calls for kw in c.keywords if kw.arg not in params]
    say(bool(calls) and not bad, "InquiryDialog.enter() accepts every keyword main_window passes",
        f"main_window passes {bad}, enter() takes {sorted(params)}")
    wired = re.search(r"mic_toggle_clicked\.connect\(\s*self\._toggle_mic\s*\)", src)
    say(wired is not None, "the Speak button is wired to _toggle_mic")
    say("def _toggle_mic" in src and "RecordWorker" in src, "_toggle_mic still starts a RecordWorker")
    del inspect


# ── 5 selftest ────────────────────────────────────────────────────────────
def check_selftest() -> None:
    print("5  PRISM_SELFTEST")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", PRISM_SELFTEST="1")
    for k in ("GTK_PATH", "GIO_MODULE_DIR", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
              "GSETTINGS_SCHEMA_DIR", "GTK_MODULES", "LOCPATH"):
        env.pop(k, None)
    if env.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG"):
        env["XDG_DATA_DIRS"] = env["XDG_DATA_DIRS_VSCODE_SNAP_ORIG"]
    p = subprocess.run([PY, "main.py"], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    bad = [l for l in p.stdout.splitlines() if l.strip() and "✓" not in l
           and not l.startswith("Prism ")]
    say(p.returncode == 0 and not bad, "self-test passes", (p.stdout + p.stderr)[-600:])


# ── 6 suite ───────────────────────────────────────────────────────────────
def check_suite() -> None:
    print("6  full suite (one process per file — takes a while)")
    # The same runner CI uses, so "green here" and "green on GitHub" mean the
    # same thing. Known failures: devtools/ci_known_failures.txt.
    p = subprocess.run([PY, str(ROOT / "devtools" / "suite_runner.py")], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    out = p.stdout
    tail = "\n      ".join(l for l in out.splitlines()
                           if l.startswith(("  ", "CRASH", "FAIL")))[-1500:]
    summary = next((l for l in out.splitlines() if " tests in " in l), "")
    say(p.returncode == 0, f"every test file ran, no new failure ({summary.strip()})", tail)


MANUAL = """
MANUAL — tick each one on the real app (Windows and macOS first; Linux proves nothing for customers)
  [ ] Open the app from the BUILT package, not from source (the built app is what customers run)
  [ ] Main task: type a task and Make a plan; Start the work reaches a result
  [ ] Main task: press Speak, talk, press Stop — the words land in the task box
  [ ] Email inquiries opens; Pipeline / Client file / All mail all switch
  [ ] Check my mail now on a test mailbox finishes; the newest inquiry is first in the Inquiry column
  [ ] Prepare a quotation → PDF with the ₹ glyph → Send (to yourself) arrives
  [ ] Revised quotation: Rev 2 PDF attaches; they-countered / hold-the-price move the card
  [ ] Delete several rows with ctrl-click (cmd-click on a Mac); the right rows go
  [ ] Save as Excel opens in Excel with colours and ₹
  [ ] Lumi button: visible, drags, opens, remembers its place
  [ ] Settings → Check for updates offers the new version; Update installs it and the app starts
  [ ] 125% and 150% scaling: board, drawer and dialogs are not clipped
After publishing: signed manifests + every update file on windows-x64, linux-x64, macos-arm64-app;
Render LATEST_CLIENT_VERSION set; an older install actually updates.
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--suite", action="store_true", help="also run the whole test suite")
    ap.add_argument("--skip-selftest", action="store_true")
    args = ap.parse_args()
    tag = last_release()
    check_git()
    check_version(tag)
    check_removed(tag)
    check_contract()
    if not args.skip_selftest:
        check_selftest()
    if args.suite:
        check_suite()
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} automatic checks passed")
    print(MANUAL)
    if failed:
        print("NOT READY — fix the ✗ lines above first.")
        return 1
    print("Automatic checks pass. Do the manual list before publishing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
