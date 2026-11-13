"""
Leads & Outreach — Stats (the "Stats" screen in "Prism CRM: interface mockups", 3 Nov 2026)
───────────────────────────────────────────────────────────────────────────────────────────
Every number is read off what Prism stored: the saved contacts' history (contacts.py) and the deals (deals.py). Nothing is estimated, and a
figure with nothing behind it is None, never 0, so the screen can say "not enough yet" instead of showing a confident zero.

    contacted    contacts sent at least one e-mail in the window   (a "sent" line in their history)
    replied      of those, the ones who reached Replied or Interested (a stage line "… → Replied", or their stage now)
    interested   of those, the ones who reached Interested
    deals        deals started in the window         won   deals won in the window
    reply_rate   replied / contacted                  win_rate   won / (won + lost), both closed in the window
    median_reply_days   median days from the first send to the first reply, over the contacts who replied
    open_pipeline       rupees in open deals today    lost_reasons   {reason: count} for deals lost in the window

Not here, on purpose: the mockup's "reply rate by step". Prism records that a mail was sent, not which touch of a sequence it was, so a
per-touch rate would be invented. It arrives with the sequence engine, which will know.

Qt-free and path-free: a plain function over lists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Optional

from addons.leads import deals as DL

WINDOW_DAYS = 30
_REPLIED = ("Replied", "Interested")


@dataclass
class Stats:
    days: int = WINDOW_DAYS
    contacted: int = 0
    replied: int = 0
    interested: int = 0
    deals: int = 0
    won: int = 0
    lost: int = 0
    reply_rate: Optional[float] = None
    win_rate: Optional[float] = None
    median_reply_days: Optional[float] = None
    open_pipeline: float = 0.0
    lost_reasons: dict = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not (self.contacted or self.deals or self.won or self.lost or self.open_pipeline)


def _day(stamp) -> Optional[date]:
    try:
        return date.fromisoformat(str(stamp or "").strip()[:10])
    except ValueError:
        return None


def _went_to(history, stages) -> Optional[date]:
    """The first day a "… → <stage>" line names one of `stages`, or None."""
    for h in history:
        if h.get("kind") == "stage" and str(h.get("text", "")).split("→")[-1].strip() in stages:
            return _day(h.get("at"))
    return None


def _in_window(day: Optional[date], start: date, today: date) -> bool:
    return day is not None and start <= day <= today


def compute(contacts, deals, today: Optional[date] = None, days: int = WINDOW_DAYS) -> Stats:
    today = today or date.today()
    start = today - timedelta(days=days - 1)
    out = Stats(days=days)

    waits = []
    for c in contacts or ():
        history = list(getattr(c, "history", None) or ())
        sent = [d for d in (_day(h.get("at")) for h in history if h.get("kind") == "sent") if d is not None]
        if not any(_in_window(d, start, today) for d in sent):
            continue
        out.contacted += 1
        stage = getattr(c, "stage", "")
        reply_day = _went_to(history, _REPLIED)
        if stage in _REPLIED or reply_day is not None:
            out.replied += 1
            if reply_day is not None and min(sent) <= reply_day:
                waits.append((reply_day - min(sent)).days)
        if stage == "Interested" or _went_to(history, ("Interested",)) is not None:
            out.interested += 1
    if out.contacted:
        out.reply_rate = out.replied / out.contacted
    if waits:
        out.median_reply_days = float(median(waits))

    everyone = list(deals or ())
    out.deals = sum(1 for d in everyone if _in_window(_day(d.created_at), start, today))
    closed = [d for d in everyone if d.stage in (DL.WON, DL.LOST) and _in_window(_day(d.closed_at), start, today)]
    out.won = sum(1 for d in closed if d.stage == DL.WON)
    out.lost = sum(1 for d in closed if d.stage == DL.LOST)
    if out.won + out.lost:
        out.win_rate = out.won / (out.won + out.lost)
    for d in closed:
        if d.stage == DL.LOST:
            reason = d.lost_reason or "Other"
            out.lost_reasons[reason] = out.lost_reasons.get(reason, 0) + 1
    out.open_pipeline = DL.open_pipeline(everyone)
    return out
