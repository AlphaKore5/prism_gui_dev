"""The accuracy regression gate (replay mode): schema, checks, worst-of-3 scoring,
baseline handling, and the release gate itself. Runs the real runner end to end on
recorded answers; no network, no model, no credits.

test_release_gate_on_the_repo_cases is THE release gate: it fails when any case in
devtools/evals/cases scores below devtools/evals/baseline.json."""
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "devtools"))

from evals import checks, run, schema  # noqa: E402

REAL = {
    "id": "synthetic-real-001", "area": "boq", "weight": 2, "must_not_break": True,
    "source": "synthetic test fixture", "added": "2026-11-22",
    "input": {"task": "t", "files": [], "role": "boq.agent_a"},
    "accepted": {"fields": {"total": "50.00"}},
    "checks": [{"type": "json_keys", "keys": ["total"]},
               {"type": "equals", "path": "total", "value": "50.00"}],
    "recorded_runs": ['{"total": "50.00"}'] * 3,
}


def make_dir(*cases, baseline=None):
    d = Path(tempfile.mkdtemp(prefix="evalgate-"))
    (d / "cases").mkdir()
    for c in cases:
        (d / "cases" / f"{c['id']}.json").write_text(json.dumps(c), encoding="utf-8")
    results, _ = run.run_replay(d / "cases")
    (d / "baseline.json").write_text(run.baseline_text(results) if baseline is None else json.dumps(baseline),
                                     encoding="utf-8")
    return d


class Schema(unittest.TestCase):
    def test_a_real_case_is_valid(self):
        self.assertEqual(schema.validate_case(REAL), [])

    def test_a_case_without_an_accepted_answer_is_rejected(self):
        c = copy.deepcopy(REAL); del c["accepted"]
        self.assertTrue(any("accepted" in e for e in schema.validate_case(c)))

    def test_a_placeholder_may_omit_the_accepted_answer(self):
        c = copy.deepcopy(REAL); del c["accepted"]
        c["id"] = "placeholder-x"; c["placeholder"] = True; c["recorded_runs"] = ["{}"]
        self.assertEqual(schema.validate_case(c), [])

    def test_placeholder_flag_and_prefix_must_agree(self):
        a = copy.deepcopy(REAL); a["placeholder"] = True
        b = copy.deepcopy(REAL); b["id"] = "placeholder-x"
        self.assertTrue(schema.validate_case(a))
        self.assertTrue(schema.validate_case(b))

    def test_real_case_needs_exactly_three_runs(self):
        c = copy.deepcopy(REAL); c["recorded_runs"] = ['{"total": "50.00"}']
        self.assertTrue(any("exactly 3" in e for e in schema.validate_case(c)))

    def test_bad_checks_and_unknown_fields_are_named(self):
        c = copy.deepcopy(REAL)
        c["checks"] = [{"type": "nope"}, {"type": "equals", "path": "a"}]
        c["surprise"] = 1
        errs = " | ".join(schema.validate_case(c))
        self.assertIn("unknown check type", errs)
        self.assertIn("missing", errs)
        self.assertIn("unknown fields", errs)

    def test_every_case_file_in_the_repo_validates(self):
        _, problems = run.load_cases(run.CASES_DIR)
        self.assertEqual(problems, [])


class Checks(unittest.TestCase):
    def test_each_check_type_passes_and_fails(self):
        ans = '```json\n{"a": {"b": [3]}, "k": "x", "e": ""}\n```'
        P = lambda c: checks.run_check(c, ans)[0]
        self.assertTrue(P({"type": "json_keys", "keys": ["a", "k"]}))
        self.assertFalse(P({"type": "json_keys", "keys": ["zzz"]}))
        self.assertTrue(P({"type": "equals", "path": "a.b.0", "value": 3}))
        self.assertFalse(P({"type": "equals", "path": "a.b.0", "value": "3"}))  # exact, no coercion
        self.assertTrue(P({"type": "one_of", "path": "k", "values": ["x", "y"]}))
        self.assertFalse(P({"type": "one_of", "path": "k", "values": ["y"]}))
        self.assertTrue(P({"type": "not_empty", "path": "k"}))
        self.assertFalse(P({"type": "not_empty", "path": "e"}))
        self.assertTrue(P({"type": "must_contain", "text": "\"k\""}))
        self.assertTrue(P({"type": "must_not_contain", "text": "as an AI"}))
        self.assertFalse(P({"type": "max_length", "chars": 5}))
        self.assertTrue(P({"type": "min_length", "chars": 5}))

    def test_non_json_answer_fails_json_checks_without_crashing(self):
        self.assertFalse(checks.run_check({"type": "json_keys", "keys": ["a"]}, "Sorry, no.")[0])


class Scoring(unittest.TestCase):
    def test_worst_of_three_wins(self):
        c = copy.deepcopy(REAL)
        c["recorded_runs"] = ['{"total": "50.00"}', '{"total": "50.00"}', '{"total": "49.00"}']
        r = run.score_case(c)
        self.assertEqual(r["score"], 0.5)
        self.assertFalse(r["passed"])

    def test_replay_is_deterministic(self):
        a, _ = run.run_replay(run.CASES_DIR)
        b, _ = run.run_replay(run.CASES_DIR)
        self.assertEqual(a, b)

    def test_replay_opens_no_socket(self):
        import socket
        real = socket.socket
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError("network used"))
        try:
            run.run_replay(run.CASES_DIR)
        finally:
            socket.socket = real


class TheGate(unittest.TestCase):
    def setUp(self):
        self.dirs = []

    def tearDown(self):
        for d in self.dirs:
            shutil.rmtree(d, ignore_errors=True)

    def d(self, *cases, **kw):
        p = make_dir(*cases, **kw); self.dirs.append(p); return p

    def gate(self, d):
        return run.gate(d / "cases", d / "baseline.json")

    def test_release_gate_on_the_repo_cases(self):
        ok, lines, _ = run.gate()
        self.assertTrue(ok, "\n".join(lines))

    def test_unchanged_real_case_passes(self):
        ok, lines, _ = self.gate(self.d(REAL))
        self.assertTrue(ok, lines)

    def test_DELIBERATE_REGRESSION_blocks(self):
        d = self.d(REAL)
        worse = copy.deepcopy(REAL)
        worse["recorded_runs"][1] = '{"total": "51.00"}'
        (d / "cases" / f"{worse['id']}.json").write_text(json.dumps(worse), encoding="utf-8")
        ok, lines, _ = self.gate(d)
        self.assertFalse(ok)
        self.assertTrue(any(l.startswith("BLOCK synthetic-real-001") for l in lines), lines)

    def test_cli_exit_code_is_one_on_regression(self):
        d = self.d(REAL)
        worse = copy.deepcopy(REAL); worse["recorded_runs"][0] = "no json"
        (d / "cases" / f"{worse['id']}.json").write_text(json.dumps(worse), encoding="utf-8")
        self.assertEqual(run.main(["--cases", str(d / "cases"), "--baseline", str(d / "baseline.json")]), 1)

    def test_placeholder_regression_is_reported_but_does_not_block(self):
        ph = copy.deepcopy(REAL); ph["id"] = "placeholder-r"; ph["placeholder"] = True
        d = self.d(ph)
        ph["recorded_runs"][2] = "garbage"
        (d / "cases" / "placeholder-r.json").write_text(json.dumps(ph), encoding="utf-8")
        ok, lines, res = self.gate(d)
        self.assertTrue(ok, lines)
        self.assertTrue(any("placeholder, not blocking" in l for l in lines))
        self.assertLess(res["placeholder-r"]["score"], 1.0)  # exercised, not skipped

    def test_new_real_case_without_baseline_blocks(self):
        d = self.d(REAL, baseline={"cases": {}})
        self.assertFalse(self.gate(d)[0])

    def test_case_deleted_but_in_baseline_blocks(self):
        d = self.d(REAL)
        (d / "cases" / f"{REAL['id']}.json").unlink()
        self.assertFalse(self.gate(d)[0])

    def test_a_malformed_case_file_fails_the_gate_even_if_placeholder(self):
        d = self.d(REAL)
        (d / "cases" / "placeholder-bad.json").write_text('{"id": "placeholder-bad"}', encoding="utf-8")
        ok, lines, _ = self.gate(d)
        self.assertFalse(ok)
        self.assertEqual(run.main(["--cases", str(d / "cases"), "--baseline", str(d / "baseline.json")]), 2)

    def test_missing_baseline_fails(self):
        d = self.d(REAL)
        (d / "baseline.json").unlink()
        self.assertFalse(self.gate(d)[0])

    def test_improvement_only_warns(self):
        d = self.d(REAL, baseline={"cases": {REAL["id"]: {"score": 0.5, "passed": False}}})
        ok, lines, _ = self.gate(d)
        self.assertTrue(ok)
        self.assertTrue(any(l.startswith("WARN") for l in lines))

    def test_running_never_rewrites_the_baseline(self):
        before = hashlib.sha256(run.BASELINE.read_bytes()).hexdigest()
        run.main([])
        run.main(["--print-baseline"])
        self.assertEqual(before, hashlib.sha256(run.BASELINE.read_bytes()).hexdigest())

    def test_live_mode_is_a_stub_and_calls_nothing(self):
        self.assertEqual(run.main(["--mode", "live"]), 2)
        with self.assertRaises(run.LiveModeNotWired):
            run.run_live()


if __name__ == "__main__":
    unittest.main()
