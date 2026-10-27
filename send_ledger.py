"""
Prism — the ledger of what has been sent from this computer
────────────────────────────────────────────────────────────
One plain JSON file, `~/Prism Email/sent.json`, one entry per press of Send.
Both Email and Leads write it and read today's count from it, so a daily limit
set once holds for every way of sending (review finding 7, 2026-10-01: Leads
used to send around it). It lives at the top level, stdlib-only, so neither
add-on has to import the other.

`addons/email/sent_log.py` re-exports this and keeps the words for the table.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile

import paths
DEFAULT_DIR = paths.user_folder("Prism Email")
FILE = "sent.json"
KEEP = 5000


def folder(cfg: dict) -> str:
    return ((cfg or {}).get("email") or {}).get("folder") or DEFAULT_DIR


def path(cfg: dict) -> str:
    return os.path.join(folder(cfg), FILE)


def load(cfg: dict) -> list[dict]:
    """Every entry, newest first. A missing or unreadable file is an empty
    list — the screen must open whatever state the disk is in."""
    try:
        with open(path(cfg), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [e for e in reversed(data) if isinstance(e, dict)]


def record(cfg: dict, *, to: list[dict], subject: str, body: str,
           sent: list[str], failed: list, attachments: list[str],
           list_name: str = "", stopped: bool = False,
           sender: str = "") -> dict:
    """Append one entry and return it. Never raises into a send that has
    already gone out — a log that cannot be written is reported, not fatal.

    `sender` is the address it left from -- what the daily limit is counted
    against now that there can be several."""
    now = _dt.datetime.now()
    entry = {
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "from": (sender or "").strip().lower(),
        "to": [{"email": r.get("email", ""), "name": r.get("name", "")}
               for r in to],
        "subject": subject,
        "body": body,
        "sent": list(sent),
        "failed": [[e, str(err)] for e, err in failed],
        "attachments": list(attachments),
        "list_name": list_name,
        "stopped": bool(stopped),
    }
    entries = list(reversed(load(cfg)))
    entries.append(entry)
    entries = entries[-KEEP:]
    os.makedirs(folder(cfg), exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".sent-", suffix=".json", dir=folder(cfg))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path(cfg))
    return entry


def sent_today(cfg: dict, sender: str = "", today: str = "") -> int:
    """How many messages have left `sender` today, off this log.

    An entry written before the log knew who sent it has no "from"; it
    counts against every address, because the cautious reading of an
    unknown sender is "it might have been this one" -- a daily limit that
    can be dodged by the log having been older is not a limit.
    """
    today = today or _dt.date.today().strftime("%Y-%m-%d")
    sender = (sender or "").strip().lower()
    n = 0
    for entry in load(cfg):
        if entry.get("date") != today:
            continue
        who = (entry.get("from") or "").strip().lower()
        if sender and who and who != sender:
            continue
        n += len(entry.get("sent") or [])
    return n
