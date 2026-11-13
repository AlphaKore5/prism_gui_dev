"""
Prism Sales Automation — a company's published phone number
───────────────────────────────────────────────────────────
Exa's agent reads a company's own website and its directory listings and returns
the number the company PUBLISHES, with the page it came from. That is the whole
promise, and this module never says more than that:

  * it is not a contact database. Apollo returns a validation status, a type and
    a do-not-call flag with each number; nothing here has rung the number, asked
    the network whether the line is live, or checked a do-not-call register;
  * it is the COMPANY's number (a switchboard, a sales desk, sometimes an owner's
    mobile the firm itself prints), not a named person's direct dial;
  * what Prism adds is a strict reading of the number — a plausible Indian or
    international number in one canonical form, with the kind its digits (and the
    page) suggest — and the source, always. The app says "published, not verified".

One lookup is made per COMPANY, up to 15 to a call, and only for leads that have
no phone yet: everyone at "Acme Works" shares one lookup. Pooled (the default) the
licence server asks Exa with its key and charges credits per number found
(gateway.company_phones, the server's leads_gateway.phones); the developer's
PRISM_LEADS_DIRECT=1 asks Exa with the developer's own key. The number-reading
rules and the question put to Exa are the SERVER'S too — the two copies are kept
in step by their tests, and by this comment.

Stdlib only, Qt-free.
"""
from __future__ import annotations

import re
import time
from datetime import datetime

BATCH = 15
EXA_AGENT_URL = "https://api.exa.ai/agent/runs"
EFFORT = "low"                      # Exa prices a run by this, not by its rows (21-Sep-2026)
READING = 2                         # which normal_phone rules read a saved number (see entry_for)
KINDS = ("mobile", "landline", "toll_free", "unknown")
SOURCES = ("own_website", "directory", "other")

QUERY = (
    "For each company, find the phone number the company itself publishes for reaching its "
    "office or sales desk: its own website's contact page first, otherwise a business-directory "
    "listing. Return ONE number per company, preferring the main sales or office number. Only "
    "return a number a page supports, and give that page's URL. Say whether the source is the "
    "company's own website, a directory, or something else, and whether the number is a mobile, "
    "a landline or a toll-free line if the page says. Return null when nothing is found. Never "
    "guess, complete or construct a number. Echo each row's ref back unchanged.")

_SAME_DIGIT = re.compile(r"^(\d)\1+$")
_FAKE_NUMBERS = frozenset({"1234567890", "0123456789", "9876543210", "1234512345"})
_HOST = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
_sleep = time.sleep                 # tests swap it, so a poll never really waits


# ── reading a number ─────────────────────────────────────────────────────────

def _std_apart(text: str) -> bool:
    """True when a number is WRITTEN with its STD code set apart from the rest —
    "+91 (80) 33422000", "080-3342 2000", "+91 79 2658 1234", "0755-2345678" — the
    way a landline is printed and a mobile ("98250 12345") never is. Only the
    writing is read here, not the digits."""
    t = re.sub(r"^\s*(?:\(?\+\s*91\)?|\(?0091\)?|\(?91\)?)[\s.\-]*(?:\(0\)[\s.\-]*)?", "", str(text or ""))
    return bool(re.match(r"\(\s*0?\d{2,4}\s*\)[\s.\-]*\d", t)        # (80) 33422000, (080) 3342 2000
                or re.match(r"0\d{2,4}[\s.\-]+\d", t)                # 080-33422000, 0755 2345678
                or re.match(r"\d{2,3}[\s.\-]+\d{3,4}", t))           # 80 3342 2000, 755-2345678


def normal_phone(raw, hint: str = "") -> tuple | None:
    """Read one published number strictly: (E.164 string, kind), or None when it
    is not a plausible number. `kind` is one of mobile / landline / toll_free /
    unknown and is only a FORMAT reading, so it claims only what the digits or the
    writing prove:

      * a leading 1-5 is a landline (STD codes 11, 22, 265…), whatever the hint;
      * a leading 9 is a mobile — no Indian STD code starts with 9;
      * a leading 6-8 cannot be told from the digits: mobile series and STD codes
        share them (Bhopal 755, Ahmedabad 79, Bengaluru 80…). The writing decides
        first — an STD code set apart, "+91 (80) 33422000", is a landline — then the
        `hint` (what the page or Exa said), else it is "unknown". It is never a
        mobile just because nothing said otherwise (27-Sep-2026: Siemens' Bengaluru
        switchboard was shown as "Looks like a mobile").

    A number missing its STD code cannot be made into E.164 without guessing the
    code, so it is dropped. (The same rules as the licence server's
    leads_gateway.normal_phone.)"""
    text = str(raw or "").strip()
    if not text or len(text) > 40:
        return None
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    international = text.startswith("+") or text.startswith("00")
    if text.startswith("00"):
        digits = digits[2:]
    if international and not digits.startswith("91"):
        if 8 <= len(digits) <= 15 and not _SAME_DIGIT.match(digits):
            return "+" + digits, "unknown"
        return None
    if international or (digits.startswith("91") and len(digits) == 12):
        national = digits[2:]
        if len(national) == 11 and national.startswith("0"):
            national = national[1:]         # "+91 (0)80 3342 2000": the trunk 0 written inside the +91
    elif digits.startswith("0"):
        national = digits[1:]
    else:
        national = digits
    if national.startswith(("1800", "1860")) and len(national) in (10, 11):
        return "+91" + national, ("toll_free" if national.startswith("1800") else "unknown")
    if len(national) != 10 or _SAME_DIGIT.match(national) or national in _FAKE_NUMBERS:
        return None
    hint = hint if hint in KINDS else ""
    if national[0] in "12345":
        kind = "landline"
    elif national[0] == "0":
        return None
    elif national[0] == "9":
        kind = "mobile"
    elif hint == "landline" or _std_apart(text):
        kind = "landline"
    elif hint == "mobile":
        kind = "mobile"
    else:
        kind = "unknown"
    return "+91" + national, kind


def display(number: str, kind: str = "") -> str:
    """"+91 98250 12345" from "+919825012345" for a mobile — the way an Indian
    mobile is read aloud. A landline (or a number whose kind is not known) is
    "+91 2652345678", ungrouped: where its STD code ends depends on the city, and
    a wrong split is worse than none. Anything not Indian is shown as stored."""
    n = str(number or "")
    m = re.match(r"^\+91(\d{10})$", n)
    if not m:
        return n
    d = m.group(1)
    return "+91 %s %s" % (d[:5], d[5:]) if kind == "mobile" else "+91 " + d


KIND_LABEL = {"mobile": "Looks like a mobile", "landline": "Office / landline line",
              "toll_free": "Toll-free line", "unknown": "Phone number"}
# What the person panel says under a found number: whole sentences, one per source,
# so each can be translated as written (devtools/extract_strings.py reads these).
SOURCE_LINE = {
    "own_website": "The company's number, published on their website · found {when} · not verified",
    "directory": "The company's number, published in a business directory · found {when} · not verified",
    "other": "The company's number, published on the web · found {when} · not verified",
}
# A PERSON's own mobile (prospector/mobiles.py) is not a company's published number, and the
# panel must not say it is: it comes from Apollo, and nobody has rung it.
PERSON_LINE = "Their own mobile number, from Apollo · found {when} · not called, format checked only"
# The same source in a few words, for the spreadsheet's Phone source column.
SOURCE_LABEL = {"own_website": "their website", "directory": "a business directory",
                "other": "the web"}


# ── the leads, by company ────────────────────────────────────────────────────

def host_of(value) -> str:
    v = str(value or "").strip().lower()
    v = re.sub(r"^https?://", "", v).split("/")[0].split("?")[0].replace("www.", "")
    return v if _HOST.match(v) else ""


def domain_of(lead) -> str:
    extra = getattr(lead, "extra", None) or {}
    return host_of(extra.get("company_domain")) or host_of(extra.get("website"))


def company_key(lead) -> str:
    """Who a lead works for, as a lookup is keyed: the company's name (case and
    punctuation aside), else its website. "" when the lead names no company."""
    name = re.sub(r"[^a-z0-9]+", " ", str(getattr(lead, "company", "") or "").lower()).strip()
    if name:
        return "n:" + name
    dom = domain_of(lead)
    return "d:" + dom if dom else ""


def has_phone(lead) -> bool:
    return bool(str(getattr(lead, "phone", "") or "").strip()
                or (getattr(lead, "extra", None) or {}).get("phones"))


def needs_phone(lead) -> bool:
    """A lead with no phone of any kind, at a company that can be looked up."""
    return lead is not None and not has_phone(lead) and bool(company_key(lead))


def entry_for(lead) -> dict | None:
    """The record of where a lead's phone came from, when Find phones found it:
    the `extra["phones"]` entry whose number is the lead's own. None for a number
    the person came with (a sheet's, one typed in) — nothing is claimed about those."""
    number = str(getattr(lead, "phone", "") or "").strip()
    for p in (getattr(lead, "extra", None) or {}).get("phones") or ():
        if isinstance(p, dict) and number and p.get("number") == number:
            return _as_read_now(p)
    return None


def _as_read_now(entry: dict) -> dict:
    """A number saved before 27-Sep-2026 was called "mobile" whenever it started 6-8
    and nothing said otherwise — Siemens' Bengaluru switchboard, +91 80 3342 2000,
    was shown as "Looks like a mobile". What was saved does not say whether a page
    or only that guess made it one, so such an entry is shown as "unknown" (an
    entry saved by the current rules carries `read` and is trusted as it is)."""
    number = str(entry.get("number") or "")
    if entry.get("read") == READING or entry.get("kind") != "mobile" or number.startswith("+919"):
        return entry
    return dict(entry, kind="unknown")


def groups(leads) -> list:
    """[{"key", "company": {name, domain, location}, "leads": [...]}] for every
    company with a lead that still needs a phone — one entry per company, in the
    order they first appear."""
    out: dict = {}
    for lead in leads or ():
        if not needs_phone(lead):
            continue
        key = company_key(lead)
        entry = out.setdefault(key, {"key": key, "leads": [],
                                     "company": {"name": "", "domain": "", "location": ""}})
        entry["leads"].append(lead)
        c, extra = entry["company"], (lead.extra or {})
        c["name"] = c["name"] or str(lead.company or "").strip() or domain_of(lead)
        c["domain"] = c["domain"] or domain_of(lead)
        c["location"] = c["location"] or str(extra.get("location") or "").strip()[:120]
    return list(out.values())


def companies_of(leads) -> int:
    """How many lookups these leads need — what the confirm box multiplies by the price."""
    return len(groups(leads))


# ── asking Exa (developer switch) ────────────────────────────────────────────

def schema(n: int) -> dict:
    return {"type": "object", "required": ["companies"], "properties": {"companies": {
        "type": "array", "maxItems": n, "items": {
            "type": "object", "required": ["ref"], "properties": {
                "ref": {"type": "string"},
                "phone": {"type": "string", "format": "phone"},
                "phone_type": {"type": "string", "enum": list(KINDS)},
                "source_kind": {"type": "string", "enum": list(SOURCES)},
                "source_url": {"type": "string"},
                "evidence": {"type": "string", "maxLength": 160}}}}}}


def build_body(batch: list) -> dict:
    return {"query": QUERY, "effort": EFFORT,
            "input": {"data": [{"ref": "c%d" % i, "company": c["name"], "website": c["domain"],
                                "city_or_state": c["location"]} for i, c in enumerate(batch)]},
            "outputSchema": schema(len(batch))}


def read_rows(batch: list, got: list) -> list:
    """The numbers worth keeping from what Exa returned, matched to the company
    asked by `ref`, read strictly, and dropped when the SAME number came back for
    two companies (a directory's helpline is evidence of nothing)."""
    by_ref = {str(g.get("ref")): g for g in got if isinstance(g, dict) and g.get("ref") is not None}
    read = []
    for i, company in enumerate(batch):
        g = by_ref.get("c%d" % i) or {}
        parsed = normal_phone(g.get("phone"), str(g.get("phone_type") or ""))
        if parsed is None:
            continue
        url = str(g.get("source_url") or "").strip()
        source = str(g.get("source_kind") or "")
        read.append({"name": company["name"], "domain": company["domain"], "phone": parsed[0],
                     "kind": parsed[1], "source_kind": source if source in SOURCES else "other",
                     "source_url": url[:300] if re.match(r"^https?://", url, re.I) else "",
                     "evidence": str(g.get("evidence") or "")[:160]})
    counts: dict = {}
    for r in read:
        counts[r["phone"]] = counts.get(r["phone"], 0) + 1
    day = datetime.now().date().isoformat()
    for r in read:
        r["found_at"] = day
    return [r for r in read if counts[r["phone"]] == 1]


def _json(r) -> dict:
    """An Exa reply's JSON body — {} when it has none, or is not an object."""
    try:
        body = r.json()
    except Exception:                                   # noqa: BLE001
        return {}
    return body if isinstance(body, dict) else {}


def _said(body: dict) -> str:
    """The sentence Exa itself gave for a refusal or a failed run, when it gave one."""
    for name in ("error", "message", "failureReason", "reason"):
        value = body.get(name)
        if isinstance(value, dict):
            value = value.get("message")
        if isinstance(value, str) and value.strip():
            return value.strip()[:160]
    return ""


def _exa_refused(r, stage: str) -> str:
    """Why an Exa reply is not the one wanted, as one sentence a person can act on.
    A spent account, a key Exa rejects and a rate limit are the causes seen or likely
    in practice, so those are named; anything else gets Exa's own words."""
    code = int(getattr(r, "status_code", 0) or 0)
    if code == 402:
        return "Exa says this account is out of credits — top it up at dashboard.exa.ai."
    if code in (401, 403):
        return ("Exa did not accept the API key (HTTP %d) — check it under Search settings › "
                "Keys & claims." % code)
    if code == 429:
        return "Exa is limiting this key for the moment (HTTP 429) — try again in a minute."
    if code >= 500:
        return "Exa had a problem on its side (HTTP %d) — try again shortly." % code
    said = _said(_json(r))
    return "Exa did not %s (HTTP %d)%s" % (stage, code, ": " + said if said else ".")


def _agent_run(body: dict, key: str, max_wait: float = 90.0, poll: float = 3.0,
               why: list | None = None):
    """One Exa agent run, started and waited for. The finished run, or None when it
    could not be started, failed or took too long — and then, when a `why` list is
    passed, a sentence saying which is appended to it (a lookup that fails and does
    not say why leaves the owner guessing: 26-Sep-2026, an Exa account with no credit
    left read as "couldn't be looked up")."""
    import requests

    def no(reason: str):
        if why is not None:
            why.append(reason)
        return None

    headers = {"x-api-key": key, "Content-Type": "application/json"}
    try:
        r = requests.post(EXA_AGENT_URL, headers=headers, json=body, timeout=40)
        if r.status_code not in (200, 201, 202):
            return no(_exa_refused(r, "start the lookup"))
        run_id = _json(r).get("id")
        if not isinstance(run_id, str) or not re.match(r"^[A-Za-z0-9_-]{6,80}$", run_id):
            return no("Exa started the lookup but gave no run Prism can follow.")
        waited = 0.0
        while waited <= max_wait:
            g = requests.get(EXA_AGENT_URL + "/" + run_id, headers=headers, timeout=40)
            if g.status_code != 200:
                return no(_exa_refused(g, "return the lookup's answer"))
            run = _json(g)
            state = run.get("status")
            if state == "completed":
                return run
            if state in ("failed", "cancelled"):
                said = _said(run)
                return no("Exa's lookup %s%s" % (state, ": " + said if said else "."))
            _sleep(poll)
            waited += poll
    except Exception as e:                              # noqa: BLE001
        # The class name only: an exception's text can carry the request's details.
        return no("Couldn't reach Exa (%s) — check the internet connection." % type(e).__name__)
    return no("Exa did not finish within %d seconds." % int(max_wait))


def _lookup(batch: list, key: str, why: list | None = None):
    """The numbers for one batch of companies: a list (maybe empty) when the lookup
    answered, None when it failed — with the reason appended to `why`."""
    from . import gateway
    if gateway.is_pool(key):
        return gateway.company_phones(batch, why)
    run = _agent_run(build_body(batch), key, why=why)
    got = (((run or {}).get("output") or {}).get("structured") or {}).get("companies")
    if isinstance(got, list):
        return read_rows(batch, got)
    if run is not None and why is not None:
        why.append("Exa finished, but its answer was not a list of companies Prism can read.")
    return None


# ── writing a number onto a lead ─────────────────────────────────────────────

def apply(lead, row: dict) -> bool:
    """Record a found number on a lead: in `extra["phones"]` with everything that
    says where it came from, and as `lead.phone` — the field the export, the
    drafts and the Call button read — when they have none. Never overwrites a
    number the person came with (a sheet's, one they typed). True when it added."""
    number = str(row.get("phone") or "")
    if not number:
        return False
    lead.extra = lead.extra if isinstance(lead.extra, dict) else {}
    phones = [p for p in (lead.extra.get("phones") or []) if isinstance(p, dict)]
    if any(p.get("number") == number for p in phones):
        return False
    phones.append({"number": number, "kind": row.get("kind") or "unknown", "scope": "company",
                   "source": row.get("source_kind") or "other",
                   "source_url": row.get("source_url") or "",
                   "found_at": row.get("found_at") or datetime.now().date().isoformat(),
                   "provider": "exa", "checked": "format", "read": READING})
    lead.extra["phones"] = phones
    if not str(lead.phone or "").strip():
        lead.phone = number
    return True


def _match(row: dict, entry: dict) -> bool:
    c = entry["company"]
    return (str(row.get("name") or "").strip().casefold() == c["name"].casefold()
            and (str(row.get("domain") or "") == c["domain"] or not c["domain"]))


def find(leads, cfg: dict | None, on_progress=None) -> dict:
    """Look up the published phone of every company that has a lead with none, 15
    to a call, and write what came back onto those leads.

    Returns {"asked": companies looked up, "found": of them, how many published a
    number, "given": leads that now have one, "failed": companies whose lookup did
    not run (a provider error, or the pool ran dry), "why": the reasons those did
    not run, one sentence each, without repeats}. A pool that runs dry stops the
    loop: what was found is kept and the rest is left for a top-up."""
    from . import gateway, signals
    key = signals.exa_key(cfg)
    todo = groups(leads)
    why: list = []
    out = {"asked": 0, "found": 0, "given": 0, "failed": 0, "why": why}
    if on_progress:
        on_progress(0, len(todo))
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        if gateway.is_pool(key) and gateway.exhausted():
            out["failed"] += len(todo) - i
            break
        rows = _lookup([e["company"] for e in chunk], key, why)
        if rows is None:
            out["failed"] += len(chunk)
        else:
            out["asked"] += len(chunk)
            for entry in chunk:
                row = next((r for r in rows if _match(r, entry)), None)
                if row is None:
                    continue
                out["found"] += 1
                out["given"] += sum(1 for lead in entry["leads"] if apply(lead, row))
        if on_progress:
            on_progress(min(i + BATCH, len(todo)), len(todo))
    out["why"] = list(dict.fromkeys(why))
    return out
