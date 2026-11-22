#!/usr/bin/env python3
"""Accuracy regression gate runner.

    python devtools/evals/run.py                 # replay: free, no network, deterministic
    python devtools/evals/run.py --print-baseline  # show a baseline for a human to review and commit

Replay mode scores the recorded answers stored in each case against its rule
checks. It opens no socket and spends no credits. Scoring is worst-of-3: a case
scores as its worst recorded run.

Baseline: baseline.json is only ever changed by a person committing it. This
runner never writes it. --print-baseline prints what it would be.

Exit codes: 0 gate passes, 1 a blocking regression, 2 a bad case/baseline file
or live mode (not implemented).
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from evals import checks, schema  # noqa: E402

CASES_DIR = HERE / "cases"
BASELINE = HERE / "baseline.json"


class LiveModeNotWired(NotImplementedError):
    pass


def load_cases(cases_dir):
    """Return (cases, problems). problems is a list of 'file: message'."""
    cases, problems = [], []
    seen = {}
    for p in sorted(Path(cases_dir).glob("*.json")):
        try:
            case = json.loads(p.read_text(encoding="utf-8"))
        except ValueError as e:
            problems.append(f"{p.name}: not valid JSON ({e})")
            continue
        errs = schema.validate_case(case)
        problems += [f"{p.name}: {e}" for e in errs]
        if not errs:
            if case["id"] in seen:
                problems.append(f"{p.name}: id {case['id']!r} already used by {seen[case['id']]}")
                continue
            seen[case["id"]] = p.name
            cases.append(case)
    return cases, problems


def score_case(case):
    """Worst-of-N over the recorded runs."""
    runs = [checks.score_run(case["checks"], a) for a in case["recorded_runs"]]
    worst = min(runs, key=lambda r: r[0])
    return {"score": worst[0], "passed": worst[0] == 1.0, "failures": worst[1]}


def run_replay(cases_dir=CASES_DIR):
    cases, problems = load_cases(cases_dir)
    return {c["id"]: dict(score_case(c), placeholder=bool(c.get("placeholder")),
                          weight=c["weight"], must_not_break=bool(c.get("must_not_break")))
            for c in cases}, problems


def run_live(*_a, **_k):
    """STUB. Live mode (real model calls through the server) is not built and
    is not wired to any paid call. Do not add one without the owner's go-ahead
    on a credit ceiling."""
    raise LiveModeNotWired("live mode is not implemented; use replay")


def load_baseline(path=BASELINE):
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, [f"baseline {path.name}: cannot read ({e})"]
    cases = data.get("cases") if isinstance(data, dict) else None
    if not isinstance(cases, dict) or any(
            not isinstance(v, dict) or not isinstance(v.get("score"), (int, float)) for v in cases.values()):
        return None, [f"baseline {path.name}: expected {{'cases': {{id: {{'score': n, 'passed': bool}}}}}}"]
    return cases, []


def compare(results, baseline):
    """Return (blocking, warnings). A real case blocks when it scores below its
    baseline, is missing from the baseline, or the baseline holds a case that
    is gone. Placeholder regressions are reported but never block."""
    blocking, warnings = [], []
    for cid, r in sorted(results.items()):
        sink = warnings if r["placeholder"] else blocking
        tag = " (placeholder, not blocking)" if r["placeholder"] else ""
        base = baseline.get(cid)
        if base is None:
            sink.append(f"{cid}: not in baseline.json; a person must commit its baseline{tag}")
        elif r["score"] < base["score"]:
            sink.append(f"{cid}: scored {r['score']:.2f}, baseline {base['score']:.2f}: "
                        f"{'; '.join(r['failures'])}{tag}")
        elif r["score"] > base["score"]:
            warnings.append(f"{cid}: improved {base['score']:.2f} -> {r['score']:.2f}; commit a new baseline to lock it in")
    for cid in sorted(set(baseline) - set(results)):
        blocking.append(f"{cid}: in baseline.json but no case file; removing a case needs a baseline commit")
    return blocking, warnings


def gate(cases_dir=CASES_DIR, baseline_path=BASELINE):
    """Run replay and compare. Return (ok, report_lines, results)."""
    results, problems = run_replay(cases_dir)
    baseline, bproblems = load_baseline(baseline_path)
    lines = list(problems + bproblems)
    if problems or bproblems:
        return False, lines, results
    blocking, warnings = compare(results, baseline)
    lines += [f"BLOCK {m}" for m in blocking] + [f"WARN  {m}" for m in warnings]
    return not blocking, lines, results


def baseline_text(results):
    return json.dumps({"cases": {cid: {"score": r["score"], "passed": r["passed"]}
                                 for cid, r in sorted(results.items())}}, indent=2) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--cases", default=str(CASES_DIR))
    ap.add_argument("--baseline", default=str(BASELINE))
    ap.add_argument("--print-baseline", action="store_true",
                    help="print a baseline for review; never writes baseline.json")
    ap.add_argument("--save-results", metavar="FILE", help="write the scored results here")
    a = ap.parse_args(argv)
    if a.mode == "live":
        try:
            run_live()
        except LiveModeNotWired as e:
            print(f"live mode: {e}", file=sys.stderr)
            return 2
    if a.print_baseline:
        results, problems = run_replay(a.cases)
        for m in problems:
            print(m, file=sys.stderr)
        if problems:
            return 2
        sys.stdout.write(baseline_text(results))
        return 0
    ok, lines, results = gate(a.cases, a.baseline)
    for ln in lines:
        print(ln)
    for cid, r in sorted(results.items()):
        print(f"{'ok  ' if r['passed'] else 'FAIL'} {cid} {r['score']:.2f}{' [placeholder]' if r['placeholder'] else ''}")
    if a.save_results:
        Path(a.save_results).write_text(json.dumps(results, indent=2), encoding="utf-8")
    bad_files = any(not ln.startswith(("BLOCK", "WARN")) for ln in lines)
    print("GATE PASS" if ok else "GATE FAIL")
    return 0 if ok else (2 if bad_files else 1)


if __name__ == "__main__":
    sys.exit(main())
