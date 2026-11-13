"""
Leads & Outreach — sequences (the "Sequences" editor in "Prism CRM: interface mockups", 3 Nov 2026)
─────────────────────────────────────────────────────────────────────────────────────────────────────
A sequence is a short run of touches: what to say, and how many days after the first message each one is due. This file keeps the definitions
(sequences.json, in the contacts folder, the way deals.json is kept) and works out where each enrolled person stands.

What it does NOT do, and says so: it sends nothing. "Add to sequence" in the workbench still sends touch 1 itself; the later touches are
DRAFTED here with the person's name and company filled in and listed in Due today when they fall due, where the owner copies and sends them.
Nothing leaves the PC without a click, and no scheduler runs in the background.

Who is enrolled: a contact whose `via` holds "sequence" (contacts.py: put there when touch 1 was sent from "Add to sequence"). Where they stand
is read from what is stored, never remembered separately:

    touches done   how many "sent" lines their history holds, up to the number of steps
    next due       the first send plus the next step's `after_days`
    stopped        their stage says so — the four stops the screen lists:
                       replied      Replied / Interested / Not Interested
                       said stop    Do Not Contact
                       bounced      Bad Data
                       stage moved  Unresponsive / Changed Job

Qt-free and path-free: every call takes the folder.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

from addons.leads import store

SCHEMA = 1
FILE = "sequences.json"
_KEY = "sequences"
_WHAT = "your sequences"
_LOCK = threading.RLock()

MAX_STEPS = 8
# (what the screen says, the stages that stop a sequence for that reason)
STOPS = (("They reply", ("Replied", "Interested", "Not Interested")),
         ("They say STOP", ("Do Not Contact",)),
         ("It bounces", ("Bad Data",)),
         ("You change their stage", ("Unresponsive", "Changed Job")))
_STOP_WORDS = {"Replied": "replied", "Interested": "replied", "Not Interested": "replied", "Do Not Contact": "said stop",
               "Bad Data": "bounced", "Unresponsive": "stage changed", "Changed Job": "stage changed"}


class SequenceError(ValueError):
    """A change the rules refuse, in words for the owner."""


@dataclass
class Step:
    after_days: int = 0
    subject: str = ""
    body: str = ""


@dataclass
class Sequence:
    id: str
    name: str
    steps: list = field(default_factory=list)


@dataclass
class Enrolment:
    contact: object
    sequence: Sequence
    done: int                        # touches sent so far
    next_due: Optional[date]         # None when stopped or finished
    status: str                      # "Not started" | "Waiting" | "Due" | "Finished" | "Stopped: replied" …
    late_days: int = 0

    @property
    def total(self) -> int:
        return len(self.sequence.steps)

    @property
    def next_step(self) -> Optional[Step]:
        return self.sequence.steps[self.done] if self.done < self.total else None

    def is_due(self) -> bool:
        return self.status == "Due"


def default_steps() -> list:
    return [Step(0, "Quick question about {company}", "Hi {first_name},\n\n"),
            Step(3, "Re: Quick question about {company}", "Hi {first_name}, a short nudge in case this got buried.\n\n"),
            Step(7, "Last note about {company}", "Hi {first_name}, a last, polite note that is easy to decline.\n\n")]


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _step(item) -> Optional[Step]:
    if not isinstance(item, dict):
        return None
    try:
        days = max(0, min(365, int(item.get("after_days") or 0)))
    except (TypeError, ValueError):
        days = 0
    return Step(days, _text(item.get("subject")), item.get("body") if isinstance(item.get("body"), str) else "")


def _sequence(item) -> Optional[Sequence]:
    if not isinstance(item, dict) or not _text(item.get("id")) or not _text(item.get("name")):
        return None
    steps = [s for s in (_step(i) for i in item.get("steps") or ()) if s is not None][:MAX_STEPS]
    return Sequence(_text(item["id"]), _text(item["name"]), steps)


def _row(seq: Sequence) -> dict:
    return {"id": seq.id, "name": seq.name,
            "steps": [{"after_days": s.after_days, "subject": s.subject, "body": s.body} for s in seq.steps]}


def _read(items) -> list:
    return [s for s in (_sequence(i) for i in items or ()) if s is not None]


def list_sequences(folder) -> list:
    """Every sequence, in the order made. Never raises: no file is no sequences."""
    _state, items, _why = store.read(folder, FILE, _KEY, SCHEMA)
    return _read(items)


def _write(folder, doing: str, change):
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        seqs = _read(items)
        result = change(seqs)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state, [_row(s) for s in seqs])
        return result


def _checked(name: str, steps) -> tuple:
    name = _text(name)
    if not name:
        raise SequenceError("Give the sequence a name.")
    steps = [s for s in steps if isinstance(s, Step)]
    if not steps:
        raise SequenceError("A sequence needs at least one touch.")
    if len(steps) > MAX_STEPS:
        raise SequenceError(f"A sequence can have at most {MAX_STEPS} touches.")
    if any(not s.subject.strip() and not s.body.strip() for s in steps):
        raise SequenceError("Every touch needs a subject or some text.")
    return name, [Step(max(0, int(s.after_days)), s.subject.strip(), s.body) for s in steps]


def add(folder, name: str, steps=None) -> Sequence:
    """Make a sequence; with no steps it starts from the three-touch default."""
    name, steps = _checked(name, default_steps() if steps is None else steps)
    seq = Sequence(uuid.uuid4().hex[:10], name, steps)
    _write(folder, "Couldn't save this sequence", lambda seqs: seqs.append(seq))
    return seq


def update(folder, seq_id: str, name: str, steps) -> bool:
    """Replace a sequence's name and touches. False when it is not there."""
    name, steps = _checked(name, steps)

    def change(seqs) -> bool:
        seq = next((s for s in seqs if s.id == seq_id), None)
        if seq is None:
            return False
        seq.name, seq.steps = name, steps
        return True
    return _write(folder, "Couldn't change this sequence", change)


def remove(folder, seq_id: str) -> bool:
    def change(seqs) -> bool:
        keep = [s for s in seqs if s.id != seq_id]
        gone = len(keep) != len(seqs)
        seqs[:] = keep
        return gone
    return _write(folder, "Couldn't delete this sequence", change)


# ── the message, filled in ───────────────────────────────────────────────────
def render(step: Step, lead) -> tuple:
    """(subject, body) with {first_name} {name} {company} {title} filled from the person. A field they lack becomes nothing, never the braces."""
    name = _text(getattr(lead, "name", ""))
    fields = {"first_name": name.split()[0] if name else "there", "name": name or "there",
              "company": _text(getattr(lead, "company", "")) or "your company", "title": _text(getattr(lead, "title", ""))}

    def fill(text: str) -> str:
        for key, value in fields.items():
            text = text.replace("{" + key + "}", value)
        return text
    return fill(step.subject), fill(step.body)


# ── where each person stands ─────────────────────────────────────────────────
def _day(stamp) -> Optional[date]:
    try:
        return date.fromisoformat(str(stamp or "").strip()[:10])
    except ValueError:
        return None


def stop_reason(stage: str) -> str:
    """"replied", "said stop", "bounced", "stage changed" — or "" when the stage does not stop a sequence."""
    return _STOP_WORDS.get(stage, "")


def standing(contact, seq: Sequence, today: Optional[date] = None) -> Enrolment:
    today = today or date.today()
    sends = sorted(d for d in (_day(h.get("at")) for h in getattr(contact, "history", None) or () if h.get("kind") == "sent")
                   if d is not None)
    done = min(len(sends), len(seq.steps))
    why = stop_reason(getattr(contact, "stage", ""))
    if why:
        return Enrolment(contact, seq, done, None, f"Stopped: {why}")
    if not sends:
        return Enrolment(contact, seq, 0, None, "Not started")
    if done >= len(seq.steps):
        return Enrolment(contact, seq, done, None, "Finished")
    due = sends[0] + timedelta(days=seq.steps[done].after_days)
    late = (today - due).days
    return Enrolment(contact, seq, done, due, "Due" if late >= 0 else "Waiting", max(0, late))


def enrolments(contacts, seq: Sequence, today: Optional[date] = None) -> list:
    """Everyone put in a sequence by "Add to sequence", with where they stand, the most overdue first."""
    out = [standing(c, seq, today) for c in contacts or () if "sequence" in (getattr(c, "via", None) or ())]
    out.sort(key=lambda e: (not e.is_due(), -e.late_days, e.contact.lead.name.casefold()))
    return out
