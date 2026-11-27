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


_QUESTION_START = ("what", "why", "how", "who", "where", "when", "which",
                   "is ", "are ", "does", "do you", "can you explain",
                   "could you explain", "describe", "explain", "tell me")


def is_change_request(text: str) -> bool:
    """A message asking for something different, as opposed to a question
    about what is already there."""
    t = (text or "").strip().lower()
    if not t or t.endswith("?"):
        return False
    return not t.startswith(_QUESTION_START)


# ── finishing a reel that did not finish ─────────────────────────────────────
# "Continue this reel", "finish it", "try again", "make the video file now".
# Conservative on purpose: when the task's newest reel failed, a message made
# only of these words (and "reuse what is there" sentences) is a request to
# finish it, never a question for the writer. Anything else in the message
# ("make the logo blue", "why did it fail?") is not.

_FINISH_VERBS = {"continue", "finish", "complete", "resume", "retry", "redo",
                 "try", "wrap", "make"}
_FINISH_FILLER = {"please", "now", "again", "just", "ok", "okay", "then", "and",
                  "it", "this", "that", "the", "my", "a", "reel", "video", "file",
                  "task", "run", "9:16", "go", "ahead", "up", "for", "me", "thanks",
                  "can", "you", "could", "to", "so", "finally", "mp4", "film",
                  "movie", "instagram", "short"}
_REUSE_START = ("reuse", "re-use", "use the", "use what", "keep", "do not",
                "don't", "dont", "no new", "without", "never", "only", "nothing",
                "and do not", "and don't")


def is_finish_request(text: str) -> bool:
    """A message that only asks for the unfinished reel to be finished."""
    t = (text or "").strip().lower()
    if not t or "?" in t:
        return False
    import re
    sentences = [s.strip() for s in re.split(r"[.!;\n]+", t) if s.strip()]
    found = False
    for s in sentences:
        if s.startswith(_REUSE_START) or "already made" in s:
            continue
        words = re.findall(r"[a-z0-9:'-]+", s)
        rest = [w for w in words if w not in _FINISH_FILLER]
        if not rest or not set(rest) <= _FINISH_VERBS:
            return False
        found = True
    return found


_REEL_STAGES = ("media", "design", "artwork")


def reel_did_not_finish(items: list[dict]) -> bool:
    """True when the newest reel in the thread (a turn with a picture, design
    or film step) has no film step that completed. A reply from the writer
    after it does not hide it."""
    for item in reversed(items or []):
        if item.get("kind") != "steps":
            continue
        steps = {s.get("stage"): s.get("state") for s in item.get("steps") or []
                 if isinstance(s, dict)}
        if not any(k in steps for k in _REEL_STAGES):
            continue
        return steps.get("media") != "completed"
    return False


def saved_script(responses: dict) -> str:
    """The reel's script (the scenes JSON) a run already wrote, or ""."""
    skip = ("followup", "design", "media", "artwork", "visual")
    order = [s for s in ("content", "script", "brains") if s in (responses or {})]
    order += [s for s in (responses or {}) if s not in order and s not in skip]
    for stage in order:
        text = _texts((responses or {}).get(stage))
        if '"scenes"' in text:
            return text
    return ""


_PICTURE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def saved_pictures(links: dict, folder: str) -> list[str]:
    """The reel's pictures still on disk: the task folder's Artwork files, or
    the artwork link when the folder has none."""
    found = []
    if folder and os.path.isdir(folder):
        found = [os.path.join(folder, n) for n in sorted(os.listdir(folder))
                 if "artwork" in n.lower() and n.lower().endswith(_PICTURE_EXT)]
    link = (links or {}).get("artwork") or ""
    if not found and isinstance(link, str) and link.lower().endswith(_PICTURE_EXT):
        found = [link]
    return [p for p in found if os.path.isfile(p)]
