"""
Prism Sales Automation — a person's own mobile number
─────────────────────────────────────────────────────
`phones.py` finds the number a COMPANY publishes. This finds one PERSON's mobile,
from Apollo through the licence server (prism-license-server, /v1/leads/mobile-*),
which holds the Monid account behind it. Pooled only: this machine never holds the
key, and there is no developer's-own-key path for it.

Apollo reveals a mobile slowly — minutes — so a lookup is two calls: START (free;
it only checks the pool could pay) and then READS of the same lookup until it
finishes. The server charges only when a number comes back, and once however many
reads it took (gateway.mobile_result). `find` starts every lookup first and then
reads them all together, so ten people cost the wait of one.

What a number means: it is Apollo's, format-checked by the server (the same strict
reading as `phones.normal_phone`). Nothing has rung it. It is recorded with where
it came from — `provider: "apollo"`, `scope: "person"` — beside, never over, a
number the person came with.
"""
from __future__ import annotations

import time
from datetime import datetime

from . import gateway, phones
from .verify import _domain_of, _name_parts, _registrable

LIMIT = 25                      # people per press: each is a lookup of its own
POLL = 8.0                      # seconds between reads of the lookups still going
MAX_WAIT = 420.0                # Apollo takes "several minutes"; stop reading after 7


def _who(lead) -> tuple | None:
    """(first name, last name, company domain) — what Apollo needs to find one
    person — or None when the lead does not give all three."""
    first, last = _name_parts(getattr(lead, "name", ""))
    domain = _registrable(phones.domain_of(lead) or _domain_of(lead))
    return (first, last, domain) if first and last and domain else None


def has_mobile(lead) -> bool:
    """A mobile of the person's own is already on the lead."""
    return any(isinstance(p, dict) and p.get("scope") == "person" and p.get("kind") == "mobile"
               for p in (getattr(lead, "extra", None) or {}).get("phones") or ())


def entry_of(lead) -> dict | None:
    """The record of the person's own mobile (`extra["phones"]`, scope "person"), or None.
    It can sit beside a number the person came with, which `lead.phone` keeps."""
    for p in (getattr(lead, "extra", None) or {}).get("phones") or ():
        if isinstance(p, dict) and p.get("scope") == "person" and p.get("kind") == "mobile":
            return p
    return None


def needs_mobile(lead) -> bool:
    return lead is not None and not has_mobile(lead) and _who(lead) is not None


def apply(lead, number: str, kind: str = "mobile") -> bool:
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
                    "provider": "apollo", "checked": "format", "read": phones.READING})
    lead.extra["phones"] = entries
    if not str(lead.phone or "").strip() or replaces:
        lead.phone = number
    return True


def find(leads, cfg: dict | None = None, on_progress=None, *, sleep=time.sleep) -> dict:
    """Find the mobile of every lead that has none, up to LIMIT of them, and write
    what comes back onto those leads.

    Returns {"asked": lookups started, "found": numbers found, "given": leads that
    now have one, "failed": lookups that did not run or did not finish properly,
    "pending": lookups still going when it stopped reading, "why": the reasons,
    one sentence each, without repeats}. A pool that runs dry stops the starting:
    what was found is kept."""
    why: list = []
    out = {"asked": 0, "found": 0, "given": 0, "failed": 0, "pending": 0, "why": why}
    if not gateway.pooled():
        why.append("Mobile numbers are looked up through Prism's credits; this build is "
                   "using its own provider keys, which have no mobile source.")
        return out
    todo = [lead for lead in leads or () if needs_mobile(lead)][:LIMIT]
    total = len(todo)
    if on_progress:
        on_progress(0, total)
    running: dict = {}                                  # run id -> lead
    for lead in todo:
        if gateway.exhausted():
            out["failed"] += 1
            continue
        first, last, domain = _who(lead)
        run_id = gateway.start_mobile(first, last, domain, why)
        if run_id:
            running[run_id] = lead
            out["asked"] += 1
        else:
            out["failed"] += 1
    done = out["failed"]
    if on_progress:
        on_progress(done, total)
    waited = 0.0
    while running:
        for run_id, lead in list(running.items()):
            res = gateway.mobile_result(run_id, why)
            if res is None:
                out["failed"] += 1
            elif res["state"] == "done":
                if res.get("phone"):
                    out["found"] += 1
                    out["given"] += 1 if apply(lead, str(res["phone"]), str(res.get("kind") or "mobile")) else 0
            else:
                continue
            del running[run_id]
            done += 1
            if on_progress:
                on_progress(done, total)
        if not running or waited >= MAX_WAIT:
            break
        sleep(POLL)
        waited += POLL
    out["pending"] = len(running)
    if running:
        why.append("Apollo was still working on %d of them when Prism stopped waiting. "
                   "Nothing is charged for a number that has not come back." % len(running))
    out["why"] = list(dict.fromkeys(why))
    return out
