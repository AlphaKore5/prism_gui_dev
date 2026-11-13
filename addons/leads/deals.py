"""
Leads & Outreach — deals (the "Deals" board in "Prism CRM: interface mockups", 3 Nov 2026)
────────────────────────────────────────────────────────────────────────────────────────
A deal is a piece of work you are trying to win: who it is with, what it is worth, where it stands and what happens next. One file,
deals.json, in the folder the caller names, kept the way contacts.py keeps its own (store.py: readers forgive, writers refuse, atomic).

    id           short, stable
    title        what the deal is ("Proposal ₹4.2L", "Panel order") — the card's headline
    company      who it is with
    person       the contact it came from, as written ("" when none)
    keys         that contact's identity keys (prospector.identity), so the person's drawer can show their deal
    value        rupees, a number; 0 until known
    stage        one of STAGES, or WON / LOST
    next_step    one line: "Call Thu", "Price call Fri"
    created_at, moved_at   ISO; moved_at is when it last changed stage, and what "stalled" is counted from
    closed_at    ISO, once it is won or lost
    lost_reason  why, when it was lost

The two rules the mockup states are kept here, not left to the screen: Won needs a value, and Lost needs a reason.

Qt-free and path-free: every call takes the folder.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from addons.leads import store

SCHEMA = 1
FILE = "deals.json"
_KEY = "deals"
_WHAT = "your deals"

STAGES = ("Qualified", "Proposal", "Negotiation", "PO received")     # open, in the order a deal travels
WON = "Won"
LOST = "Lost"
ALL_STAGES = STAGES + (WON, LOST)
STALL_DAYS = 7                      # an open deal with no movement for this long is flagged
LOST_REASONS = ("Price", "Went quiet", "Chose a rival", "Not now", "Other")

_LOCK = threading.RLock()


class DealError(ValueError):
    """A change the rules refuse, in words for the owner."""


@dataclass
class Deal:
    id: str
    title: str
    company: str = ""
    person: str = ""
    keys: list = field(default_factory=list)
    value: float = 0.0
    stage: str = STAGES[0]
    next_step: str = ""
    created_at: str = ""
    moved_at: str = ""
    closed_at: str = ""
    lost_reason: str = ""

    def is_open(self) -> bool:
        return self.stage in STAGES


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _day(stamp) -> Optional[date]:
    try:
        return date.fromisoformat(str(stamp or "").strip()[:10])
    except ValueError:
        return None


def _number(value) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n if n == n and n >= 0 else 0.0           # NaN and negatives are no value


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _deal(item) -> Optional[Deal]:
    """A stored row → Deal, or None for a row that is not one."""
    if not isinstance(item, dict) or not _text(item.get("id")) or not _text(item.get("title")):
        return None
    stage = item.get("stage") if item.get("stage") in ALL_STAGES else STAGES[0]
    keys = [k for k in item.get("keys") or () if isinstance(k, str) and k]
    return Deal(id=_text(item["id"]), title=_text(item["title"]), company=_text(item.get("company")),
                person=_text(item.get("person")), keys=keys, value=_number(item.get("value")), stage=stage,
                next_step=_text(item.get("next_step")), created_at=_text(item.get("created_at")),
                moved_at=_text(item.get("moved_at")), closed_at=_text(item.get("closed_at")),
                lost_reason=_text(item.get("lost_reason")))


def _row(d: Deal) -> dict:
    return {"id": d.id, "title": d.title, "company": d.company, "person": d.person, "keys": list(d.keys),
            "value": d.value, "stage": d.stage, "next_step": d.next_step, "created_at": d.created_at,
            "moved_at": d.moved_at, "closed_at": d.closed_at, "lost_reason": d.lost_reason}


def _read(items) -> list:
    return [d for d in (_deal(i) for i in items or ()) if d is not None]


def list_deals(folder) -> list:
    """Every deal, oldest first. Never raises: no file is no deals."""
    _state, items, _why = store.read(folder, FILE, _KEY, SCHEMA)
    return _read(items)


def _write(folder, doing: str, change):
    """Read the file for writing, let `change(deals)` edit the list, write it back. Returns what `change` returns."""
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        deals = _read(items)
        result = change(deals)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state, [_row(d) for d in deals])
        return result


def add(folder, title: str, company: str = "", value=0, stage: str = STAGES[0], next_step: str = "",
        person: str = "", keys=()) -> Deal:
    """Start a deal. It opens at `stage` (an open one); Won and Lost are reached with move()."""
    title = _text(title)
    if not title:
        raise DealError("Give the deal a name.")
    if stage not in STAGES:
        stage = STAGES[0]
    now = _now()
    deal = Deal(id=uuid.uuid4().hex[:10], title=title, company=_text(company), person=_text(person),
                keys=[k for k in keys if isinstance(k, str) and k], value=_number(value), stage=stage,
                next_step=_text(next_step), created_at=now, moved_at=now)
    _write(folder, "Couldn't save this deal", lambda deals: deals.append(deal))
    return deal


def move(folder, deal_id: str, stage: str, value=None, reason: str = "") -> bool:
    """Put a deal in another stage. Won needs a value, Lost needs a reason (DealError otherwise). False when the deal is
    not there or is already at that stage."""
    if stage not in ALL_STAGES:
        raise DealError("That is not a stage.")

    def change(deals) -> bool:
        deal = next((d for d in deals if d.id == deal_id), None)
        if deal is None or deal.stage == stage:
            return False
        new_value = deal.value if value is None else _number(value)
        if stage == WON and new_value <= 0:
            raise DealError("A won deal needs its value.")
        if stage == LOST and not _text(reason):
            raise DealError("A lost deal needs a reason.")
        now = _now()
        deal.value, deal.stage, deal.moved_at = new_value, stage, now
        deal.closed_at = now if stage in (WON, LOST) else ""
        deal.lost_reason = _text(reason) if stage == LOST else ""
        return True
    return _write(folder, "Couldn't move this deal", change)


def set_next_step(folder, deal_id: str, text: str) -> bool:
    def change(deals) -> bool:
        deal = next((d for d in deals if d.id == deal_id), None)
        if deal is None or deal.next_step == _text(text):
            return False
        deal.next_step = _text(text)
        return True
    return _write(folder, "Couldn't change this deal", change)


def remove(folder, deal_id: str) -> bool:
    def change(deals) -> bool:
        keep = [d for d in deals if d.id != deal_id]
        gone = len(keep) != len(deals)
        deals[:] = keep
        return gone
    return _write(folder, "Couldn't delete this deal", change)


def linked(folder, lead) -> list:
    """The deals tied to this person (their identity keys touch the deal's), newest first."""
    from prospector.identity import keys_of
    wanted = keys_of(lead)
    mine = [d for d in list_deals(folder) if wanted and not wanted.isdisjoint(d.keys)]
    return sorted(mine, key=lambda d: d.created_at, reverse=True)


# ── what the board reads ──────────────────────────────────────────────────────
def stalled_days(deal: Deal, today: Optional[date] = None) -> int:
    """Days an OPEN deal has sat without moving, when that is STALL_DAYS or more; 0 otherwise."""
    if not deal.is_open():
        return 0
    since = _day(deal.moved_at) or _day(deal.created_at)
    if since is None:
        return 0
    days = ((today or date.today()) - since).days
    return days if days >= STALL_DAYS else 0


def by_stage(deals) -> dict:
    """{stage: [deals]} for every open stage and Won, newest move first. Lost deals are not on the board."""
    out = {s: [] for s in STAGES + (WON,)}
    for d in sorted(deals, key=lambda d: d.moved_at, reverse=True):
        if d.stage in out:
            out[d.stage].append(d)
    return out


def total(deals) -> float:
    return sum(d.value for d in deals)


def open_pipeline(deals) -> float:
    return total(d for d in deals if d.is_open())


def won_in_month(deals, today: Optional[date] = None) -> float:
    """Value won in the calendar month of `today`."""
    today = today or date.today()
    return total(d for d in deals if d.stage == WON
                 and (c := _day(d.closed_at)) is not None and (c.year, c.month) == (today.year, today.month))


def inr(value: float) -> str:
    """₹4.2L, ₹1.8Cr, ₹95,000 — the way a rupee figure is read in India."""
    v = float(value or 0)
    if v >= 1e7:
        return f"₹{v / 1e7:.1f}Cr"
    if v >= 1e5:
        return f"₹{v / 1e5:.1f}L"
    return f"₹{v:,.0f}"
