"""Layer 1: deterministic rule checks. Same answer in, same verdict out; no model, no network."""
from __future__ import annotations
import json
import re

_FENCE = re.compile(r"^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$", re.S)


def parse_json(answer):
    """Parse an answer as JSON, tolerating one surrounding code fence. None if it is not JSON."""
    text = answer.strip()
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except ValueError:
        return None


def dig(obj, path):
    """Follow 'a.b.0.c'. Returns (found, value)."""
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


def run_check(chk, answer):
    """Return (passed, reason)."""
    kind = chk["type"]
    if kind == "must_contain":
        return chk["text"] in answer, f"missing {chk['text']!r}"
    if kind == "must_not_contain":
        return chk["text"] not in answer, f"contains forbidden {chk['text']!r}"
    if kind == "max_length":
        return len(answer) <= chk["chars"], f"{len(answer)} chars > {chk['chars']}"
    if kind == "min_length":
        return len(answer) >= chk["chars"], f"{len(answer)} chars < {chk['chars']}"
    data = parse_json(answer)
    if data is None:
        return False, "answer is not valid JSON"
    if kind == "json_keys":
        miss = [k for k in chk["keys"] if not (isinstance(data, dict) and k in data)]
        return not miss, f"missing keys {miss}"
    found, val = dig(data, chk["path"])
    if not found:
        return False, f"no value at {chk['path']!r}"
    if kind == "equals":
        return (val == chk["value"] and type(val) is type(chk["value"])), f"{chk['path']} is {val!r}, expected {chk['value']!r}"
    if kind == "one_of":
        return val in chk["values"], f"{chk['path']} is {val!r}, not one of {chk['values']!r}"
    if kind == "not_empty":
        return val not in (None, "", [], {}), f"{chk['path']} is empty"
    raise ValueError(f"unknown check type {kind!r}")


def score_run(checks, answer):
    """Return (fraction passed, [failure reasons])."""
    fails = []
    for chk in checks:
        ok, why = run_check(chk, answer)
        if not ok:
            fails.append(f"{chk['type']}: {why}")
    return (len(checks) - len(fails)) / len(checks), fails
