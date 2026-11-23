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

CI splits the suite across parallel jobs:

    python devtools/suite_runner.py --shard 2/4 --summary-json s2.json
    python devtools/suite_runner.py --shard 2/4 --list    # which files, then exit
    python devtools/suite_runner.py --merge DIR --shards 4 # one verdict for all shards

Files are dealt to shards by their recorded duration on this platform
(devtools/test_timings.json, longest first, each to the lightest shard), so
every shard of one platform computes the same split from the same checkout.
A file with no recorded time is weighed by its size. Refresh the timings from
a CI run's logs with --timings-from-log windows=job.log linux=job.log.
"""
from __future__ import annotations

import argparse
import json
import os
import re
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
TIMINGS = ROOT / "devtools" / "test_timings.json"
PLATFORMS = ("windows", "linux", "macos")   # keys of TIMINGS, in fallback order


def this_platform() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    return "macos" if sys.platform == "darwin" else "linux"


def load_timings(path: Path = TIMINGS) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def shard_files(files: list[Path], index: int, count: int, platform: str,
                timings: dict) -> list[Path]:
    """The files shard `index` (1-based) of `count` runs, sorted by name.

    Longest file first, each to the shard with the least time so far (ties:
    the lower shard). Weight: this platform's recorded seconds, else another
    platform's, else the file's size at the average seconds-per-byte of the
    files that do have a time. Same inputs, same split, on every shard."""
    order = [platform] + [p for p in PLATFORMS if p != platform]
    known: dict[str, float] = {}
    for f in files:
        for p in order:
            if f.name in timings.get(p, {}):
                known[f.name] = float(timings[p][f.name])
                break
    sizes = {f.name: f.stat().st_size for f in files}
    timed_bytes = sum(sizes[n] for n in known)
    per_byte = (sum(known.values()) / timed_bytes) if timed_bytes else 1.0
    weight = {f.name: max(1.0, known.get(f.name, sizes[f.name] * per_byte)) for f in files}
    loads = [0.0] * count
    mine = []
    for f in sorted(files, key=lambda f: (-weight[f.name], f.name)):
        target = min(range(count), key=lambda i: (loads[i], i))
        loads[target] += weight[f.name]
        if target == index - 1:
            mine.append(f)
    return sorted(mine, key=lambda f: f.name)


# What main() prints for each file that reported: "ok    test_x.py  12 tests,
# 0 failing  (31s)"; a dead file: "KNOWN  test_y.py  <why>  (12s)".
_LOG_LINE = re.compile(r"\b(?:ok|FAIL|known|KNOWN|CRASH)\s+(test_\w+\.py)\s.*\((\d+)s\)")


def timings_from_logs(pairs: list[str]) -> dict:
    """{"windows": {"test_x.py": 31, ...}, ...} from `platform=logfile` pairs
    (a downloaded CI job log or a saved local run)."""
    out = {}
    for pair in pairs:
        platform, _, log = pair.partition("=")
        if platform not in PLATFORMS or not log:
            raise SystemExit(f"--timings-from-log wants one of {PLATFORMS}=LOGFILE, got {pair!r}")
        found = {}
        for line in Path(log).read_text(encoding="utf-8", errors="replace").splitlines():
            m = _LOG_LINE.search(line)
            if m:
                found[m.group(1)] = int(m.group(2))
        if not found:
            raise SystemExit(f"{log}: no per-file result lines found")
        out[platform] = dict(sorted(found.items()))
    return out


def merge_summaries(folder: Path, shards: int, files: list[Path]) -> int:
    """One verdict for a sharded run: every shard reported, every test file
    ran in exactly one shard, and no shard found a new failure or crash."""
    found = {}
    problems = []
    for path in sorted(folder.rglob("*.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        i, _, n = str(s.get("shard", "")).partition("/")
        if n != str(shards):
            problems.append(f"{path.name}: shard {s.get('shard')!r}, expected one of N={shards}")
        elif i in found:
            problems.append(f"shard {i}/{n} reported twice")
        else:
            found[i] = s
    missing = [str(i) for i in range(1, shards + 1) if str(i) not in found]
    if missing:
        problems.append("no summary from shard(s) " + ", ".join(f"{m}/{shards}" for m in missing)
                        + " (cancelled, or died before reporting: read that job)")
    ran = [name for s in found.values() for name in s["files"]]
    twice = sorted({n for n in ran if ran.count(n) > 1})
    expected = {f.name for f in files}
    if twice:
        problems.append("ran in more than one shard: " + ", ".join(twice))
    if not missing:
        never = sorted(expected - set(ran))
        if never:
            problems.append("ran in no shard: " + ", ".join(never))
    shards_in = [found[k] for k in sorted(found, key=int)]
    total = sum(s["tests"] for s in shards_in)
    passed = sum(s["passed"] for s in shards_in)
    print(f"{total} tests in {len(ran)} files, {passed} passed, {total - passed} failing, "
          f"across {len(found)} of {shards} shards")
    for s in shards_in:
        print(f"  shard {s['shard']}: {s['tests']} tests in {len(s['files'])} files, "
              f"{s['minutes']:.1f} min, exit {s['exit']}")
    fixed = [k for s in shards_in for k in s["fixed"]]
    crashes = [c for s in shards_in for c in s["crashes"]]
    new = [kv for s in shards_in for kv in s["new_failures"]]
    if fixed:
        print("Known failures that now pass — remove from ci_known_failures.txt:")
        for k in fixed:
            print("  ", k)
    if crashes:
        print("\nPROCESS CRASHES (not in the known list):")
        for c in crashes:
            print("  ", c)
    if new:
        print("\nNEW FAILURES:")
        for k, m in new:
            print("  ", k, "—", m)
    if problems:
        print("\nSHARDING PROBLEMS:")
        for p in problems:
            print("  ", p)
    bad = problems or crashes or new or any(s["exit"] != 0 for s in shards_in)
    return 1 if bad else 0


def load_known(path: Path = KNOWN) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


def _env(file_timeout: int = 0, hang_log: Path | None = None) -> dict:
    env = dict(os.environ, QT_QPA_PLATFORM=os.environ.get("QT_QPA_PLATFORM", "offscreen"),
               PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if file_timeout > 120:
        # tests/conftest.py arms faulthandler with this: one minute before the
        # runner would kill the file silently, the process prints every
        # thread's stack and exits. It covers what the per-test timeout cannot:
        # importing the file, setUpClass, and the process's own exit (a thread
        # left running). 1.8.8 hung twice in test_leads_filter_panel.py that way.
        env["PRISM_FILE_WATCHDOG"] = str(file_timeout - 60)
        if hang_log is not None:
            env["PRISM_FILE_WATCHDOG_LOG"] = str(hang_log)
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
    for marker in ("Fatal Python error", "Windows fatal exception", "Timeout ("):
        i = text.find(marker)
        if i != -1:
            return text[max(0, i - 300):i + size]
    return text[-1500:]


def case_key(test_file: Path, classname: str, name: str) -> str:
    """The id a known failure is listed under: `file.py::Class::test`, or
    `file.py::module::test` for a test outside a class.

    pytest builds the junit classname from the node id, which depends on where
    the file sits relative to the rootdir. Under the rootdir it is
    `tests.test_x.Class`. Outside it (Windows CI: temp dir on C:, checkout on
    D:) the classname kept the module's `.py` and taking the text after the
    last '.' gave `py`; on Linux it can come out empty. So drop a trailing
    `.py`, split on '.', '/' and '\\', and fall back to the file's stem."""
    cls = re.sub(r"\.py$", "", classname or "")
    part = re.split(r"[./\\]", cls)[-1]
    return f"{test_file.name}::{part or test_file.stem}::{name}"


def run_file(test_file: Path, out_dir: Path, per_test_timeout: int, file_timeout: int):
    """One pytest process for one file. Returns (cases, died, tail) where cases
    is [(key, status, message)] and died is a string if the process produced no
    report."""
    xml = out_dir / f"{test_file.stem}.xml"
    hang_log = out_dir / f"{test_file.stem}.hang.txt"
    for old in (xml, hang_log):
        if old.exists():
            old.unlink()
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
        p = subprocess.run(cmd, cwd=ROOT, env=_env(file_timeout, hang_log), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=file_timeout)
        rc, tail = p.returncode, _fault_excerpt(p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return [], f"timed out after {file_timeout}s", _fault_excerpt(out)
    hang = hang_log.read_text(encoding="utf-8", errors="replace") if hang_log.exists() else ""
    if hang.strip():
        # The watchdog fired: the file hung outside any single test. Even if
        # every test passed (it hung on the way out), that is a failure.
        return [], (f"hung for {file_timeout - 60}s outside any test (import, class setup "
                    f"or exit); every thread's stack follows"), _fault_excerpt(hang, 4000)
    if not xml.exists():
        return [], f"the process died before reporting (exit {rc})", tail
    cases = []
    for case in ET.parse(xml).getroot().iter("testcase"):
        key = case_key(test_file, case.get("classname", ""), case.get("name"))
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
    ap.add_argument("--file-timeout", type=int, default=480)   # slowest healthy file: 363 s (watchdog at 420 s)
    ap.add_argument("--shard", help="I/N: run only shard I (1-based) of N")
    ap.add_argument("--list", action="store_true", help="print the files that would run, then exit")
    ap.add_argument("--summary-json", help="also write this run's result here (for --merge)")
    ap.add_argument("--merge", metavar="DIR", help="combine the --summary-json files under DIR")
    ap.add_argument("--shards", type=int, help="with --merge: how many shards there must be")
    ap.add_argument("--timings-from-log", nargs="+", metavar="PLATFORM=LOG",
                    help=f"rewrite {TIMINGS.name} from per-file lines in these logs")
    args = ap.parse_args(argv)

    if args.timings_from_log:
        TIMINGS.write_text(json.dumps(timings_from_logs(args.timings_from_log), indent=1) + "\n",
                           encoding="utf-8")
        print(f"wrote {TIMINGS}")
        return 0

    files = [Path(f) for f in args.files] or sorted((ROOT / "tests").glob("test_*.py"))
    if args.merge:
        if not args.shards:
            ap.error("--merge needs --shards N")
        return merge_summaries(Path(args.merge), args.shards, files)
    shard = "1/1"
    if args.shard:
        m = re.fullmatch(r"(\d+)/(\d+)", args.shard)
        if not m or not 1 <= int(m.group(1)) <= int(m.group(2)):
            ap.error(f"--shard wants I/N with 1 <= I <= N, got {args.shard!r}")
        shard = args.shard
        files = shard_files(files, int(m.group(1)), int(m.group(2)), this_platform(), load_timings())
    if args.list:
        for f in files:
            print(f.name)
        return 0
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
            # Show the first attempt even if the retry passes: a hang or crash
            # that goes away on the second try is still a bug, and its stack
            # is the only evidence (1.8.8's filter-panel hang was lost this way).
            print(f"RETRY  {f.name}  first attempt: {died}", flush=True)
            if tail:
                print("    " + tail.replace("\n", "\n    "), flush=True)
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

    minutes = (time.monotonic() - started) / 60
    print(f"\n{total} tests in {len(files)} files, {passed} passed, "
          f"{total - passed} failing, in {minutes:.1f} min"
          + (f" (shard {shard})" if args.shard else ""))
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
    rc = 1 if (crashes or new_failures) else 0
    if args.summary_json:
        Path(args.summary_json).write_text(json.dumps({
            "shard": shard, "platform": this_platform(), "files": [f.name for f in files],
            "tests": total, "passed": passed, "minutes": round(minutes, 2),
            "new_failures": new_failures, "crashes": crashes, "fixed": fixed, "exit": rc,
        }, indent=1), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
