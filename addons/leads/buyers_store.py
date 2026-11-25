"""
Find my buyers — what is kept
─────────────────────────────
Two small files in the member's leads folder, written the way every store here
writes (addons/leads/store.py: atomic, never over a newer Prism's file, a
damaged one set aside):

  buyer_hunts.json   every hunt: the offer as it was, the buyer types, the cards
                     and what the owner decided about each. Newest first, 30 kept.
  buyer_offer.json   the offer the owner last described, so the page opens ready
                     to hunt again.
  buyer_memory.json  one line per card the owner accepted or put away (and why), kept apart from the
                     hunts so it outlives the 30 the hunts file keeps. A hunt reads it back
                     (prospector/buyers_learn.py): what was judged is not shown or read twice, and the
                     owner's taste goes to the model.

A card's decision (accepted, skipped, not a fit) is saved the moment it is made:
the owner never re-reads a card they already judged. Qt-free.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime

from addons.leads import store
from prospector import buyers as B

HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA = "buyer_hunts.json", "hunts", 1
OFFER_FILE, OFFER_KEY, OFFER_SCHEMA = "buyer_offer.json", "offers", 1
MEMORY_FILE, MEMORY_KEY, MEMORY_SCHEMA = "buyer_memory.json", "memory", 1
KEEP = 30
_LOCK = threading.Lock()
_WHAT = "your buyer searches"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _hunt(item):
    """A stored row → a hunt dict whose cards are Hit objects, or None."""
    if not isinstance(item, dict) or not item.get("id"):
        return None
    own = B.host_of(str((item.get("offer") or {}).get("website") or "")) if isinstance(item.get("offer"), dict) else ""
    # Cards from a hunt run before a page was learnt to be no buyer are filtered on the way back in: the file is
    # never rewritten for this, so nothing the owner decided is lost, it is only not shown.
    hits = [h for h in (B.hit_from_dict(x) for x in item.get("hits") or [])
            if h is not None and not B.blocked(h.url, own)]
    out = dict(item)
    out["hits"] = hits
    out["types"] = [t for t in item.get("types") or [] if isinstance(t, dict)]
    out["notes"] = [str(n) for n in item.get("notes") or []]
    out["stats"] = item.get("stats") if isinstance(item.get("stats"), dict) else {}
    return out


def _row(hunt: dict) -> dict:
    out = dict(hunt)
    out["hits"] = [B.asdict(h) if not isinstance(h, dict) else h for h in hunt.get("hits") or []]
    return out


def list_hunts(folder) -> list:
    """Every kept hunt, newest first. Never raises."""
    _state, items, _why = store.read(folder, HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA)
    return [h for h in (_hunt(i) for i in items) if h is not None]


def get_hunt(folder, hunt_id: str):
    for h in list_hunts(folder):
        if h["id"] == hunt_id:
            return h
    return None


def save_hunt(folder, *, offer: B.Offer, summary: str, types: list, channels, preview: bool,
              result: B.HuntResult) -> dict:
    """Keep a finished hunt; returns it as list_hunts() would. Raises
    store.StoreError, worded for the owner, when it cannot be written."""
    doing = "Couldn't save this buyer search"
    hunt = {"id": "h" + uuid.uuid4().hex[:10], "created_at": _now(), "offer": B.asdict(offer),
            "summary": summary, "types": [B.asdict(t) for t in types],
            "channels": [c for c in B.CHANNELS if c in set(channels or ())],
            "preview": bool(preview), "hits": result.hits, "stats": dict(result.stats),
            "notes": list(result.notes)}
    with _LOCK:
        state, items = store.for_writing(folder, HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA, doing, _WHAT)
        rows = [_row(hunt)] + [i for i in items if isinstance(i, dict)]
        store.commit(folder, HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA, doing, _WHAT, state, rows[:KEEP])
    return _hunt(_row(hunt))


def set_decisions(folder, hunt_id: str, card_ids, decision: str, reason: str = "") -> int:
    """Record a decision on cards of one hunt; how many changed. Raises
    store.StoreError when it cannot be written."""
    doing = "Couldn't save your decision"
    n = 0
    with _LOCK:
        state, items = store.for_writing(folder, HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA, doing, _WHAT)
        rows = []
        for item in items:
            if isinstance(item, dict) and item.get("id") == hunt_id:
                hits = [h for h in (B.hit_from_dict(x) for x in item.get("hits") or []) if h is not None]
                n = B.decide(hits, card_ids, decision, reason)
                item = dict(item)
                item["hits"] = [B.asdict(h) for h in hits]
            rows.append(item)
        if n:
            store.commit(folder, HUNTS_FILE, HUNTS_KEY, HUNTS_SCHEMA, doing, _WHAT, state, rows)
    return n


# ── the offer the owner last described ───────────────────────────────────────

def load_offer(folder) -> "tuple[B.Offer, str, list]":
    """(offer, summary, buyer types) as last saved; an empty offer when none."""
    _state, items, _why = store.read(folder, OFFER_FILE, OFFER_KEY, OFFER_SCHEMA)
    row = items[0] if items and isinstance(items[0], dict) else {}
    o = row.get("offer") if isinstance(row.get("offer"), dict) else {}
    offer = B.Offer(text=str(o.get("text") or ""), website=str(o.get("website") or ""),
                    regions=str(o.get("regions") or ""), competitors=str(o.get("competitors") or ""),
                    ideal=str(o.get("ideal") or ""),
                    company_kinds=tuple(str(k) for k in (o.get("company_kinds") or []) if str(k).strip()),
                    max_staff=int(o.get("max_staff") or 0),
                    channels=tuple(c for c in (o.get("channels") or []) if c in B.CHANNELS))
    types = []
    for t in row.get("types") or []:
        if isinstance(t, dict) and t.get("name"):
            known = {k: t[k] for k in B.BuyerType.__dataclass_fields__ if k in t}
            try:
                types.append(B.BuyerType(**known))
            except TypeError:
                pass
    return offer, str(row.get("summary") or ""), types


def save_offer(folder, offer: B.Offer, summary: str = "", types=()) -> None:
    doing = "Couldn't save what you sell"
    row = {"offer": B.asdict(offer), "summary": summary, "types": [B.asdict(t) for t in types],
           "saved_at": _now()}
    with _LOCK:
        state, _items = store.for_writing(folder, OFFER_FILE, OFFER_KEY, OFFER_SCHEMA, doing,
                                          "what you sell")
        store.commit(folder, OFFER_FILE, OFFER_KEY, OFFER_SCHEMA, doing, "what you sell", state, [row])


# ── what the owner has judged ────────────────────────────────────────────────

def load_memory(folder) -> list:
    """Every judged card, newest first. Never raises: a missing or damaged file is no memory."""
    try:
        _state, items, _why = store.read(folder, MEMORY_FILE, MEMORY_KEY, MEMORY_SCHEMA)
    except Exception:                                   # noqa: BLE001
        return []
    return [i for i in items if isinstance(i, dict)]


def remember(folder, hits, decision: str, reason: str = "") -> None:
    """Keep what the owner decided about `hits` (buyers_learn.remember). Raises store.StoreError, worded for the
    owner, when it cannot be written."""
    from prospector import buyers_learn as BL
    doing = "Couldn't remember your decision"
    with _LOCK:
        state, items = store.for_writing(folder, MEMORY_FILE, MEMORY_KEY, MEMORY_SCHEMA, doing, "your decisions")
        rows = BL.remember([i for i in items if isinstance(i, dict)], list(hits), decision, reason, _now())
        store.commit(folder, MEMORY_FILE, MEMORY_KEY, MEMORY_SCHEMA, doing, "your decisions", state, rows)
