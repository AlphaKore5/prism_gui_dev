"""Case file format and validation for the accuracy gate.

One JSON file per case in devtools/evals/cases/. validate_case() returns a list
of plain-language problems; an empty list means the case is usable. The runner
refuses to run, and the release gate fails, if any case file has a problem
(placeholder cases included: a malformed placeholder is still malformed).

A case that is not a placeholder MUST carry a recorded accepted answer
("accepted") and three recorded runs ("recorded_runs") so replay mode can score
it for free. A placeholder (id starting "placeholder-" AND "placeholder": true)
is synthetic, is exercised by the gate, and never blocks a release.
"""
from __future__ import annotations

PLACEHOLDER_PREFIX = "placeholder-"
RUNS_REQUIRED = 3  # worst-of-3 scoring

CHECK_FIELDS = {
    "json_keys": {"keys"},
    "equals": {"path", "value"},
    "one_of": {"path", "values"},
    "not_empty": {"path"},
    "must_contain": {"text"},
    "must_not_contain": {"text"},
    "max_length": {"chars"},
    "min_length": {"chars"},
}
TOP_KEYS = {"id", "area", "weight", "must_not_break", "source", "added", "placeholder",
            "input", "accepted", "checks", "recorded_runs", "judge"}
REQUIRED_TOP = {"id", "area", "weight", "source", "added", "input", "checks", "recorded_runs"}


def _is_str_list(v):
    return isinstance(v, list) and v and all(isinstance(x, str) and x for x in v)


def validate_check(chk, where):
    if not isinstance(chk, dict) or chk.get("type") not in CHECK_FIELDS:
        return [f"{where}: unknown check type {chk.get('type') if isinstance(chk, dict) else chk!r}"]
    kind = chk["type"]
    need = CHECK_FIELDS[kind]
    errs = []
    missing = need - set(chk)
    extra = set(chk) - need - {"type"}
    if missing:
        errs.append(f"{where}: {kind} is missing {sorted(missing)}")
    if extra:
        errs.append(f"{where}: {kind} has unknown fields {sorted(extra)}")
    if errs:
        return errs
    if kind == "json_keys" and not _is_str_list(chk["keys"]):
        errs.append(f"{where}: keys must be a non-empty list of names")
    if kind in ("equals", "one_of", "not_empty") and not (isinstance(chk["path"], str) and chk["path"]):
        errs.append(f"{where}: path must be a non-empty string")
    if kind == "one_of" and not (isinstance(chk["values"], list) and chk["values"]):
        errs.append(f"{where}: values must be a non-empty list")
    if kind in ("must_contain", "must_not_contain") and not (isinstance(chk["text"], str) and chk["text"]):
        errs.append(f"{where}: text must be a non-empty string")
    if kind in ("max_length", "min_length") and not (
            isinstance(chk["chars"], int) and not isinstance(chk["chars"], bool) and chk["chars"] >= 0):
        errs.append(f"{where}: chars must be a whole number")
    return errs


def validate_case(case):
    """Return a list of problems (empty = valid)."""
    if not isinstance(case, dict):
        return ["case is not a JSON object"]
    errs = []
    unknown = set(case) - TOP_KEYS
    if unknown:
        errs.append(f"unknown fields {sorted(unknown)}")
    missing = REQUIRED_TOP - set(case)
    if missing:
        errs.append(f"missing fields {sorted(missing)}")
        return errs
    cid = case["id"]
    if not (isinstance(cid, str) and cid):
        return errs + ["id must be a non-empty string"]
    flag = case.get("placeholder", False)
    if not isinstance(flag, bool):
        errs.append("placeholder must be true or false")
    elif flag != cid.startswith(PLACEHOLDER_PREFIX):
        errs.append(f'"placeholder" must be true exactly when the id starts with "{PLACEHOLDER_PREFIX}"')
    is_ph = flag is True
    if not (isinstance(case["area"], str) and case["area"]):
        errs.append("area must be a non-empty string")
    w = case["weight"]
    if isinstance(w, bool) or not isinstance(w, int) or w < 1:
        errs.append("weight must be a whole number of 1 or more")
    if "must_not_break" in case and not isinstance(case["must_not_break"], bool):
        errs.append("must_not_break must be true or false")
    if not (isinstance(case["source"], str) and case["source"]):
        errs.append("source must be a non-empty string")
    if not (isinstance(case["added"], str) and len(case["added"]) == 10):
        errs.append("added must be a date like 2026-12-01")
    inp = case["input"]
    if not (isinstance(inp, dict) and isinstance(inp.get("task"), str) and inp["task"]
            and isinstance(inp.get("role"), str) and inp["role"]):
        errs.append("input needs a non-empty task and role")
    elif not isinstance(inp.get("files", []), list):
        errs.append("input.files must be a list")
    acc = case.get("accepted")
    if acc is None:
        if not is_ph:
            errs.append("a recorded accepted answer (accepted) is required unless the case is a placeholder")
    elif not (isinstance(acc, dict) and (isinstance(acc.get("text"), str) and acc["text"] or acc.get("fields"))):
        errs.append("accepted needs a non-empty text or fields")
    checks = case["checks"]
    if not (isinstance(checks, list) and checks):
        errs.append("checks must be a non-empty list")
    else:
        for i, chk in enumerate(checks):
            errs += validate_check(chk, f"checks[{i}]")
    runs = case["recorded_runs"]
    if not (isinstance(runs, list) and runs and all(isinstance(r, str) for r in runs)):
        errs.append("recorded_runs must be a non-empty list of answer texts")
    elif not is_ph and len(runs) != RUNS_REQUIRED:
        errs.append(f"recorded_runs must hold exactly {RUNS_REQUIRED} runs for a real case")
    return errs
