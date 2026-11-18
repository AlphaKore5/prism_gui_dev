"""A task page conversation, as it is kept in the run record.

There is no second store. A run record (config.save_run, ~/.prism/runs/run_*.json,
what History lists) gains one key, `thread`, a list of items:

    {"kind": "user",   "text", "files": [names], "ts"}
    {"kind": "steps",  "label", "steps": [{"stage","agent","title","state",
                                           "seconds","note","text"}], "ts"}
    {"kind": "answer", "text", "by", "stage", "ts"}
    {"kind": "files",  "paths": [...], "ts"}
    {"kind": "note",   "text", "bad", "ts"}

A record written before this existed has no `thread`: `thread_of` builds the
same list from its query, responses and follow-ups, so an old run opens as a
transcript and can be continued like any other. No Qt in here.
"""
from __future__ import annotations

import os
import time

KINDS = ("user", "steps", "answer", "files", "note")
MAX_TEXT = 60000
MAX_ITEMS = 400


def _clip(text) -> str:
    return str(text or "")[:MAX_TEXT]


def _texts(value) -> str:
    items = value if isinstance(value, list) else [value]
    return "\n\n".join(str(t) for t in items if str(t or "").strip())


def latest_answer(responses: dict, skip=()) -> tuple[str, str]:
    """(stage, text) of the newest non-empty step, ignoring `skip`."""
    for stage, texts in reversed(list((responses or {}).items())):
        if stage in skip:
            continue
        text = _texts(texts)
        if text.strip():
            return stage, text
    return "", ""


def _step(stage, agent, title, state, seconds, note, text) -> dict:
    return {"stage": stage, "agent": agent or "", "title": title or "",
            "state": state, "seconds": seconds, "note": note or "",
            "text": _clip(text)}


def _turn(label, responses, agents, durations, skip=()) -> list[dict]:
    steps = []
    for stage, texts in (responses or {}).items():
        text = _texts(texts)
        if not text.strip():
            continue
        steps.append(_step(stage, (agents or {}).get(stage, ""), "", "completed",
                           (durations or {}).get(stage),
                           "", "" if stage in skip else text))
    out = []
    if steps:
        out.append({"kind": "steps", "label": label, "steps": steps})
    stage, text = latest_answer(responses, skip)
    if text:
        out.append({"kind": "answer", "text": _clip(text), "stage": stage,
                    "by": (agents or {}).get(stage, "")})
    return out


def derive(record: dict) -> list[dict]:
    """The thread of a record that has none: query, steps, answer, then each
    follow-up the same way."""
    items: list[dict] = []
    query = (record.get("query") or "").strip()
    if query:
        files = [a if isinstance(a, str) else (a or {}).get("name", "")
                 for a in (record.get("attachments") or [])]
        items.append({"kind": "user", "text": query,
                      "files": [f for f in files if f]})
    followups = [f for f in (record.get("followups") or []) if isinstance(f, dict)]
    # A follow-up that re-ran a step overwrote it in the record's own
    # responses, so the first turn keeps only the steps nobody redid.
    redone = {s for fu in followups for s in (fu.get("responses") or {})}
    responses = record.get("responses") or {}
    first = {s: t for s, t in responses.items() if s not in redone} if followups else responses
    items += _turn("First run" if followups else "", first,
                   record.get("agents"), record.get("durations"))
    for n, fu in enumerate(followups, 1):
        if fu.get("query"):
            items.append({"kind": "user", "text": str(fu["query"])})
        items += _turn(f"Follow-up {n}", fu.get("responses"), fu.get("agents"),
                       fu.get("durations"))
        if fu.get("error"):
            items.append({"kind": "note", "text": str(fu["error"]), "bad": True})
    err = record.get("error") or record.get("latest_error") or ""
    if err and not followups:
        items.append({"kind": "note", "text": str(err), "bad": True})
    local = [v for v in (record.get("links") or {}).values()
             if isinstance(v, str) and os.path.isabs(v) and os.path.isfile(v)]
    if local:
        items.append({"kind": "files", "paths": local})
    return items


def thread_of(record: dict) -> list[dict]:
    """The stored thread, or the one derived from an older record."""
    stored = record.get("thread")
    if isinstance(stored, list):
        clean = [i for i in stored if isinstance(i, dict) and i.get("kind") in KINDS]
        if clean:
            return clean
    return derive(record)


def for_record(items: list[dict]) -> list[dict]:
    """What gets written: the newest MAX_ITEMS, every item stamped."""
    now = time.time()
    out = []
    for item in items[-MAX_ITEMS:]:
        item = dict(item)
        item.setdefault("ts", now)
        out.append(item)
    return out


def turns_for_model(items: list[dict]) -> list[tuple[str, str]]:
    """The conversation as the model should read it: what the person wrote and
    what Prism AI answered. (Step cards are working, not conversation.) The
    engine's replay caps the total, newest kept."""
    turns = []
    for item in items:
        if item.get("kind") == "user" and item.get("text"):
            turns.append(("USER", str(item["text"])))
        elif item.get("kind") == "answer" and item.get("text"):
            turns.append(("ASSISTANT", str(item["text"])))
    return turns


def user_count(items: list[dict]) -> int:
    return sum(1 for i in items if i.get("kind") == "user")
