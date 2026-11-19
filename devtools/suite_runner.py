#!/usr/bin/env python3
"""Run the test suite one file per process, and say exactly what broke.

    python devtools/suite_runner.py                 # the whole suite
    python devtools/suite_runner.py tests/test_x.py # just these files
    python devtools/suite_runner.py --timeout 300   # per-test timeout (needs pytest-timeout)

Why not `pytest` on the whole tree: ~4,700 Qt tests in ONE process. On
Windows and macOS a single native crash (heap corruption in a stray timer, a
Qt object used after deletion, the runner killing an over-large process) ends
the run at 30–60% with no result for everything after it — which is what CI
showed on every push before this (Windows 0xc0000374, macOS exit 137/139).
One process per file contains the damage: a crash names its file, is retried
once, and every other file still reports.

Exit status 0 only if there is no NEW failure and no unexpected crash.
Failures that are known and explained live in devtools/ci_known_failures.txt:

    test_x.py::SomeClass::test_name        # why, ideally with the platform
    crash:test_y.py                        # a file whose process dies

A known entry that starts passing is reported ("fixed — remove it") but does
not fail the run.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

if __name__ == "__main__":
    # A Windows console is not UTF-8; only the script itself should change it,
    # never an importer's streams.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                               # noqa: BLE001
            pass

ROOT = Path(__file__).resolve().parent.parent
KNOWN = ROOT / "devtools" / "ci_known_failures.txt"


def load_known(path: Path = KNOWN) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def _env() -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for k in ("GTK_PATH", "GIO_MODULE_DIR", "GTK_EXE_PREFIX", "GTK_IM_MODULE_FILE",
              "GSETTINGS_SCHEMA_DIR", "GTK_MODULES", "LOCPATH"):
        env.pop(k, None)
    if env.get("XDG_DATA_DIRS_VSCODE_SNAP_ORIG"):
        env["XDG_DATA_DIRS"] = env["XDG_DATA_DIRS_VSCODE_SNAP_ORIG"]
    return env


def _fault_excerpt(text: str, size: int = 2500) -> str:
    """The part of a dead process's output that says where it died, instead
    of its last lines (which are only pytest's own entry point).

    A native crash dump (faulthandler) lists the innermost frame FIRST, so
    start at it. A pytest-timeout dump lists each thread's stack innermost
    LAST, so keep each thread's header and its last frames. Without a dump,
    keep the end as before."""
    i = text.find("+ Timeout +")
    if i != -1:
        out, block = [], []
        for line in text[i:].splitlines():
            if "Stack of " in line or "+ Timeout +" in line:
                out += block[-16:]
                block = []
                out.append(line)
            else:
                block.append(line)
        out += block[-16:]
        return "\n".join(out)[-size * 2:]
    for marker in ("Fatal Python error", "Windows fatal exception"):
        i = text.find(marker)
        if i != -1:
            return text[max(0, i - 300):i + size]
    return text[-1500:]


def run_file(test_file: Path, out_dir: Path, per_test_timeout: int, file_timeout: int):
    """One pytest process for one file. Returns (cases, died, tail) where cases
    is [(key, status, message)] and died is a string if the process produced no
    report."""
    xml = out_dir / f"{test_file.stem}.xml"
    if xml.exists():
        xml.unlink()
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
           f"--junitxml={xml}", str(test_file)]
    if per_test_timeout:
        # thread method: a test stuck inside Qt's C++ event loop never runs a
        # Python signal handler, so the default (signal) method on Linux never
        # fired and the file sat until the 25-min file timeout (twice, with the
        # retry). The thread method dumps every thread's stack and ends the
        # process, which is what names the hung test.
        cmd[3:3] = [f"--timeout={per_test_timeout}", "--timeout-method=thread"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=_env(), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=file_timeout)
        rc, tail = p.returncode, _fault_excerpt(p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return [], f"timed out after {file_timeout}s", _fault_excerpt(out)
    if not xml.exists():
        return [], f"the process died before reporting (exit {rc})", tail
    cases = []
    for case in ET.parse(xml).getroot().iter("testcase"):
        key = f"{test_file.name}::{case.get('classname', '').split('.')[-1]}::{case.get('name')}"
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        if bad is not None:
            cases.append((key, "fail", (bad.get("message") or "")[:200]))
        else:
            cases.append((key, "pass", ""))
    return cases, "", tail


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--timeout", type=int, default=0, help="per-test timeout (pytest-timeout)")
    ap.add_argument("--file-timeout", type=int, default=1500)
    args = ap.parse_args(argv)

    files = [Path(f) for f in args.files] or sorted((ROOT / "tests").glob("test_*.py"))
    known = load_known()
    out_dir = Path(tempfile.mkdtemp(prefix="prism-suite-"))
    new_failures, crashes, fixed, total, passed = [], [], [], 0, 0
    started = time.monotonic()

    for f in files:
        t0 = time.monotonic()
        cases, died, tail = run_file(f, out_dir, args.timeout, args.file_timeout)
        retried = False
        if died:
            retried = True
            cases, died, tail = run_file(f, out_dir, args.timeout, args.file_timeout)
        secs = time.monotonic() - t0
        if died:
            tag = f"crash:{f.name}"
            ok_known = tag in known
            (crashes if not ok_known else []).append(f"{f.name}: {died}")
            print(f"{'KNOWN' if ok_known else 'CRASH'}  {f.name}  {died}  ({secs:.0f}s)", flush=True)
            if not ok_known and tail:
                print("    " + tail.replace("\n", "\n    "), flush=True)
            continue
        bad = [(k, m) for k, s, m in cases if s == "fail"]
        total += len(cases)
        passed += len(cases) - len(bad)
        for key, msg in bad:
            if key not in known:
                new_failures.append((key, msg))
        for key, status, _ in cases:
            if status == "pass" and key in known:
                fixed.append(key)
        mark = "ok   " if not bad else ("FAIL " if any(k not in known for k, _ in bad) else "known")
        note = "  (passed on retry after a crash)" if retried else ""
        print(f"{mark} {f.name}  {len(cases)} tests, {len(bad)} failing  ({secs:.0f}s){note}", flush=True)
        for key, msg in bad:
            print(f"      {'known ' if key in known else 'NEW   '}{key}  {msg}", flush=True)

    print(f"\n{total} tests in {len(files)} files, {passed} passed, "
          f"{total - passed} failing, in {(time.monotonic() - started) / 60:.1f} min")
    if fixed:
        print("Known failures that now pass — remove from ci_known_failures.txt:")
        for k in fixed:
            print("  ", k)
    if crashes:
        print("\nPROCESS CRASHES (not in the known list):")
        for c in crashes:
            print("  ", c)
    if new_failures:
        print("\nNEW FAILURES:")
        for k, m in new_failures:
            print("  ", k, "—", m)
    return 1 if (crashes or new_failures) else 0


if __name__ == "__main__":
    sys.exit(main())
