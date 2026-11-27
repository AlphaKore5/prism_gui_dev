"""
Prism Sales Automation — a person's own mobile number
─────────────────────────────────────────────────────
`phones.py` finds the number a COMPANY publishes. This finds one PERSON's mobile, from three
sources asked in turn, cheapest first — ai_ark, then ReverseContact, then ContactOut — each of
which charges only for a number it returns (prospector/phone_waterfall.py, 24-Nov-2026).

  · On the credit pool the licence server asks them (prism-license-server, /v1/leads/mobile-find):
    it holds the Monid account, this machine never sees that key, and the customer is charged
    credits once, only for a number found. One request, answered in seconds.
  · With the owner's OWN Monid key (direct mode, `find_direct`) this machine asks them itself.

Either way the lookups run a few at a time, a key or wallet that is refused stops the batch, and
a person nobody knows costs nothing.

What a number means: it is a source's, format-checked (the same strict reading as
`phones.normal_phone`). Nothing has rung it. It is recorded with where it came from —
`provider: "ai_ark"` (and so on), `scope: "person"` — beside, never over, a number the person
came with.
"""
from __future__ import annotations

import time
from datetime import datetime

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import gateway, monid_run, phone_waterfall, phones
from .verify import _domain_of, _name_parts, _registrable

LIMIT = 25                      # people per press: each is a lookup of its own
WORKERS = 3                     # lookups asked at once: each waits on a few sources in turn


def _who(lead) -> tuple | None:
    """(first name, last name, company domain) — what Apollo needs to find one
    person — or None when the lead does not give all three."""
    first, last = _name_parts(getattr(lead, "name", ""))
    domain = _registrable(phones.domain_of(lead) or _domain_of(lead))
    return (first, last, domain) if first and last and domain else None


# A person's own number, as recorded: "mobile", or "unknown" when the digits cannot tell (a number that starts
# 6-8, or an international one) and the source did not say. Both are the person's number, and both stop a
# second lookup: counting only "mobile" asked for the same person again and charged again (24-Nov-2026).
_OWN_KINDS = ("mobile", "unknown")


def has_mobile(lead) -> bool:
    """A mobile of the person's own is already on the lead."""
    return any(isinstance(p, dict) and p.get("scope") == "person" and p.get("kind") in _OWN_KINDS
               for p in (getattr(lead, "extra", None) or {}).get("phones") or ())


def entry_of(lead) -> dict | None:
    """The record of the person's own mobile (`extra["phones"]`, scope "person"), or None.
    It can sit beside a number the person came with, which `lead.phone` keeps."""
    for p in (getattr(lead, "extra", None) or {}).get("phones") or ():
        if isinstance(p, dict) and p.get("scope") == "person" and p.get("kind") in _OWN_KINDS:
            return p
    return None


def needs_mobile(lead) -> bool:
    # An Apollo preview row (half a name) waits for Reveal: a mobile is bought by name.
    from . import apollo
    return (lead is not None and not apollo.is_preview(lead) and not has_mobile(lead)
            and _who(lead) is not None)


def apply(lead, number: str, kind: str = "mobile", provider: str = "apollo") -> bool:
    """Record a found mobile on a lead, in `extra["phones"]` with where it came from.
    It becomes `lead.phone` — the field the export, the drafts and the Call button
    read — when the lead has none, or has only a company number Find phones put
    there; a number the person came with (a sheet's, one typed in) is never
    replaced. True when it added."""
    if not number:
        return False
    lead.extra = lead.extra if isinstance(lead.extra, dict) else {}
    entries = [p for p in (lead.extra.get("phones") or []) if isinstance(p, dict)]
    if any(p.get("number") == number for p in entries):
        return False
    ours = phones.entry_for(lead)                       # a company number Find phones found
    replaces = ours is not None and ours.get("scope") == "company"
    entries.append({"number": number, "kind": kind or "mobile", "scope": "person",
                    "source": "other", "source_url": "",
                    "found_at": datetime.now().date().isoformat(),
                    "provider": provider or "apollo", "checked": "format", "read": phones.READING})
    lead.extra["phones"] = entries
    if not str(lead.phone or "").strip() or replaces:
        lead.phone = number
    return True


def find(leads, cfg: dict | None = None, on_progress=None, *, sleep=None) -> dict:
    """Find the mobile of every lead that has none, up to LIMIT of them, and write what comes
    back onto those leads.

    Returns {"asked": people looked up, "found": numbers found, "given": leads that now have
    one, "failed": people who could not be looked up at all, "pending": 0 (kept for the callers
    that read it), "by": {source: numbers}, "why": the reasons, one sentence each, without
    repeats}. A pool that runs dry, or a Monid key or wallet that is refused, stops the batch:
    what was found is kept. `sleep` is accepted and ignored (the lookups no longer poll)."""
    if not gateway.pooled():
        return find_direct(leads, cfg, on_progress)
    return _batch(leads, on_progress, _ask_pool, cap=gateway.mobiles_left())


_STOPS = ("quota_numbers", "spend_cap")     # monthly refusals that every later lookup would meet too


def _ask_pool(lead):
    """One lookup on the credit pool: (result, messages, stop). `stop` is True when the pool is
    spent, which every later lookup would find too."""
    if gateway.exhausted():
        return None, [gateway.exhausted()], True
    if gateway.limited(*_STOPS):
        return None, [gateway.limited(*_STOPS)], True
    first, last, domain = _who(lead)
    why: list = []
    res = gateway.find_mobile(first, last, domain, company=str(getattr(lead, "company", "") or ""),
                              title=str(getattr(lead, "title", "") or ""), why=why)
    stop = bool(gateway.exhausted() or gateway.limited(*_STOPS))
    if res is None:
        return None, why, stop
    phone, provider = str(res.get("phone") or ""), str(res.get("provider") or "")
    return ({"number": phone, "kind": str(res.get("kind") or "mobile"), "provider": provider,
             "tried": [(provider or "server", "found" if phone else "none")]}, why, stop)


def _batch(leads, on_progress, ask, cap=None) -> dict:
    """The one loop: ask `ask(lead) -> (result | None, messages, stop)` for each person who needs a
    mobile, WORKERS at a time, and write the numbers onto the leads (here, on the calling thread)."""
    why: list = []
    out = {"asked": 0, "found": 0, "given": 0, "failed": 0, "pending": 0, "why": why, "by": {}}
    todo = [lead for lead in leads or () if needs_mobile(lead)][:LIMIT]
    if cap is not None:
        todo = todo[:cap]               # never ask for more than this month's promise has left
    total = len(todo)
    if on_progress:
        on_progress(0, total)
    stopped = threading.Event()

    def one(lead):
        if stopped.is_set():
            return lead, None, [], False
        res, messages, stop = ask(lead)
        if stop:
            stopped.set()
        return lead, res, list(messages or ()), stop

    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for future in as_completed([pool.submit(one, lead) for lead in todo]):
            lead, res, messages, _stop = future.result()
            done += 1
            why.extend(m for m in messages if m)
            if res is None:
                out["failed"] += 1
            else:
                tried = res.get("tried") or []
                if tried and all(state == "down" for _src, state in tried):
                    out["failed"] += 1              # every source was down: not "nobody has one"
                else:
                    out["asked"] += 1
                if res.get("number"):
                    out["found"] += 1
                    out["by"][res["provider"]] = out["by"].get(res["provider"], 0) + 1
                    if apply(lead, res["number"], res.get("kind") or "mobile", res["provider"] or "apollo"):
                        out["given"] += 1
            if on_progress:
                on_progress(done, total)
    out["why"] = list(dict.fromkeys(why))
    return out


# -- direct mode: the owner's own Monid wallet --------------------------------

NO_KEY = ("Finding a person's mobile number needs a Monid key — set MONID_API_KEY (or monid_api_key in "
          "the config) and press it again.")


def find_direct(leads, cfg: dict | None = None, on_progress=None, *, find_one=None) -> dict:
    """The same job as `find`, for the developer's / owner's own Monid key instead of the credit
    pool: each person is asked of the phone sources in turn, cheapest first, and the first number
    any of them returns is written onto the lead with the source named. A source charges only
    when it returns a number, so a person nobody knows costs nothing. Same result as `find`.
    `find_one(first, last, domain, key=, company=, title=)` is the test seam for the network."""
    key = monid_run.api_key(cfg)
    if not key:
        return {"asked": 0, "found": 0, "given": 0, "failed": 0, "pending": 0, "why": [NO_KEY], "by": {}}
    one = find_one or phone_waterfall.find

    def ask(lead):
        first, last, domain = _who(lead)
        try:
            return one(first, last, domain, key=key, company=str(getattr(lead, "company", "") or ""),
                       title=str(getattr(lead, "title", "") or "")), [], False
        except monid_run.MonidError as exc:
            return None, [str(exc)], True               # the key or the wallet: every later call would say the same
    return _batch(leads, on_progress, ask)
