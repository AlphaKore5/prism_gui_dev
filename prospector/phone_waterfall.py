"""
Prism Sales Automation — one person's mobile, asked of three sources in turn
────────────────────────────────────────────────────────────────────────────
A person's own mobile number is bought, not found: each source below is a Monid endpoint that
charges only when it returns a number, and a no-match costs nothing. So the cheapest source goes
first and the next one is asked ONLY if it found nothing — a number is paid for once.

  ai_ark          anyapi /mobile_phone.ai_ark       $0.084 a number   name + company domain
  reversecontact  reversecontact /v2/contact/phone  $0.10  a number   name + company domain
  contactout      contactout /v1/people/enrich/...  $0.20  a number   name + company (+ title)

What was measured on 252 real people (24-Nov-2026), and why the order is this one: the three together
returned a number for 147 lookups at $0.1225 on average; ai_ark and ReverseContact cost about half what
ContactOut does per number, so ContactOut is the last resort, not the second. The order is only an
estimate of cost — nothing here checks that a number belongs to the person (no sheet, so nothing to
compare it with): it is what a source says, format-checked like every other number in Leads.

A source that fails (down, too slow) is skipped and the next one is tried; a key or wallet that Monid
refuses stops everything, because every later call would be refused the same way (MonidError).

Qt-free, stdlib only. The owner's own Monid key (direct mode): the licence server will make these calls
with its own key on the credit pool, and this module is not used there.
"""
from __future__ import annotations

from . import monid_run, phones

SOURCES = ("ai_ark", "reversecontact", "contactout")
LABEL = {"ai_ark": "AI Ark", "reversecontact": "ReverseContact", "contactout": "ContactOut"}
# Monid's own ceiling per run: the listed price plus a cent, so a price that changes is refused, not paid.
MAX_COST = {"ai_ark": 0.10, "reversecontact": 0.12, "contactout": 0.22}
# What the owner is told before a batch: the most one person can cost (the first source that finds a
# number is the last one paid, so this is the dearest single hit) and what a number costs on average.
WORST_PER_PERSON = 0.22
TYPICAL_PER_NUMBER = 0.1225


def request(source: str, name: str, domain: str, *, company: str = "", title: str = "") -> tuple:
    """(provider, endpoint, {"body": ...}) for one source. ValueError for a source this module has not got."""
    name, domain, company, title = (" ".join(str(x or "").split()) for x in (name, domain, company, title))
    if source == "ai_ark":
        return "anyapi", "/mobile_phone.ai_ark", {"body": {"domain": domain, "fullName": name}}
    if source == "reversecontact":
        return "reversecontact", "/v2/contact/phone", {"body": {"fullName": name, "companyDomain": domain}}
    if source == "contactout":
        body = {"full_name": name, "company": [company or domain], "company_domain": [domain],
                "include": ["phone"]}                    # NOT work_email: only the phone is bought
        if title:
            body["job_title"] = title
        return "contactout", "/v1/people/enrich/work-email", {"body": body}
    raise ValueError(f"unknown phone source {source!r}")


def _list(node) -> list:
    return node if isinstance(node, list) else []


def candidates(source: str, output) -> list:
    """The numbers a source's answer holds, as written, best first. Nothing here raises: an answer that is
    not the shape this was read from (24-Nov-2026) gives nothing, which reads as "not found"."""
    out = output if isinstance(output, dict) else {}
    if source == "ai_ark":
        data = out.get("data") if out.get("found") else None
        data = data if isinstance(data, dict) else {}
        return [x for x in _list(data.get("phones")) + [data.get("phone")] if isinstance(x, str) and x.strip()]
    if source == "reversecontact":
        data = out.get("data") if isinstance(out.get("data"), dict) else {}
        rows = [r for r in _list(data.get("result")) if isinstance(r, dict) and isinstance(r.get("value"), str)]
        rows.sort(key=lambda r: 0 if str(r.get("type")).lower() == "mobile" else 1)
        return [r["value"] for r in rows if r["value"].strip()]
    if source == "contactout":
        profile = out.get("profile") if isinstance(out.get("profile"), dict) else {}
        return [x for x in _list(profile.get("phone")) if isinstance(x, str) and x.strip()]
    return []


def number_from(source: str, run) -> tuple | None:
    """(E.164 number, kind) from a finished run, or None. A landline or toll-free line is a company's
    desk, not a person's mobile, so it does not count; a number whose kind the digits cannot tell
    ("unknown", an international one) does."""
    if not isinstance(run, dict) or run.get("output") is None or monid_run.http_status(run) not in (0, 200):
        return None
    for raw in candidates(source, run.get("output")):
        got = phones.normal_phone(raw)
        if got and got[1] in ("mobile", "unknown"):
            return got
    return None


def find(first: str, last: str, domain: str, *, key: str, company: str = "", title: str = "",
         sources=SOURCES, call=None) -> dict:
    """One person's mobile: the cheapest source first, the next only when nothing was found.
    {"number", "kind", "provider", "tried": [(source, "found" | "none" | "down")]}; "number" is "" when
    no source had one. Raises monid_run.MonidError when Monid refuses the key or the wallet is empty."""
    call = call or monid_run.call
    name = " ".join(p for p in (str(first or "").strip(), str(last or "").strip()) if p)
    tried: list = []
    for source in sources:
        provider, endpoint, kw = request(source, name, domain, company=company, title=title)
        run = call(provider, endpoint, key=key, max_cost=MAX_COST[source], **kw)
        if run is None:
            tried.append((source, "down"))
            continue
        got = number_from(source, run)
        if got:
            tried.append((source, "found"))
            return {"number": got[0], "kind": got[1], "provider": source, "tried": tried}
        tried.append((source, "none"))
    return {"number": "", "kind": "", "provider": "", "tried": tried}
