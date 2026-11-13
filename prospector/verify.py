"""
Prism Sales Automation — verify: confirm (or scrap) the e-mail with Hunter
──────────────────────────────────────────────────────────────────────────
Enrich builds a PATTERN address (firstname.lastname@real-domain) and checks
only that the domain accepts mail — not that the mailbox exists. This stage,
when the seller has brought a Hunter.io key, closes that gap:

  1. Ask Hunter's Email Finder for the REAL address at the company domain — if
     Hunter knows the person, this fixes a wrong-pattern guess outright, and the
     finder already carries a verification status.
  2. If the finder draws a blank, VERIFY the pattern address we built — so even
     an unknown person's guessed address is confirmed or scrapped.

Two deliberate limits, both honest:
  · **BYO-key.** No Hunter key → this stage is skipped and nothing changes; the
    sheet keeps its free MX check.
  · **The qualified slice only.** Hunter's free tier is ~50 finder searches /
    100 verifications a month — nowhere near a 2,000-row list. So we spend it
    where a bad address costs a bounce and sender reputation: the hot/warm
    leads about to be emailed. An LLM cannot do this (it can't probe a mailbox);
    a dedicated verifier is the only honest way.
"""
from __future__ import annotations

import os
import re

from . import gateway
from .models import HOT, WARM

# The finders the licence server tries for a pooled lookup — the names it
# reports back, kept on a lead so the one that sold an address is not asked
# for it again.
_POOL_FINDERS = ("tomba", "hunter")

FINDER = "https://api.hunter.io/v2/email-finder"
VERIFIER = "https://api.hunter.io/v2/email-verifier"
ACCOUNT = "https://api.hunter.io/v2/account"       # free: the plan and what is left
DOMAIN_SEARCH = "https://api.hunter.io/v2/domain-search"

# Hunter status -> the Email-check value the leads/hotlist sheets colour-code on.
_MAP = {"valid": "valid", "invalid": "invalid", "accept_all": "catch-all",
        "webmail": "unknown", "disposable": "unknown", "unknown": "unknown"}

ZB_VALIDATE = "https://api.zerobounce.net/v2/validate"
# ZeroBounce status -> the Email-check value the sheets colour-code on.
_ZB_MAP = {"valid": "valid", "invalid": "invalid", "catch-all": "catch-all",
           "catchall": "catch-all", "unknown": "unknown", "spamtrap": "invalid",
           "abuse": "unknown", "do-not-mail": "unknown"}


def hunter_key(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    return (cfg.get("hunter_api_key") or os.environ.get("HUNTER_API_KEY") or "").strip()


def zerobounce_key(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    return (cfg.get("zerobounce_api_key")
            or os.environ.get("ZEROBOUNCE_API_KEY") or "").strip()


def _name_parts(name: str):
    p = re.sub(r"[^A-Za-z ]", "", name or "").split()
    return (p[0], p[-1]) if len(p) >= 2 else ("", "")


def _domain_of(lead) -> str:
    return ((lead.extra or {}).get("company_domain")
            or (lead.email.split("@")[-1] if "@" in (lead.email or "") else ""))


# Second-level suffixes a registrable domain keeps a third label under.
_TWO_LEVEL = frozenset({
    "co.in", "net.in", "org.in", "firm.in", "gen.in", "ind.in", "ac.in", "gov.in",
    "co.uk", "org.uk", "ac.uk", "com.au", "net.au", "org.au", "co.jp", "com.sg",
    "com.my", "co.za", "com.br", "com.cn", "com.hk", "co.nz", "com.tr", "com.mx",
    "co.id", "com.sa", "com.eg", "co.ae", "com.ph", "com.vn", "co.kr", "com.bd",
    "com.pk", "com.np", "co.th"})


def _registrable(host: str) -> str:
    """A company's own domain from a website host: "new.abb.com" → "abb.com",
    "www.parleelizabeth.com" → "parleelizabeth.com", "acme.co.in" kept whole.
    A finder asked at a website's sub-domain knows nobody there."""
    host = (host or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = [p for p in host.split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    last_two = ".".join(parts[-2:])
    return ".".join(parts[-3:]) if last_two in _TWO_LEVEL else last_two


def _get(url: str, params: dict, timeout: int = 40) -> dict:
    import requests
    try:
        return requests.get(url, params=params, timeout=timeout).json() or {}
    except Exception:                                   # noqa: BLE001
        return {}


def _zb_validate(email: str, key: str) -> str:
    j = _get(ZB_VALIDATE, {"api_key": key, "email": email, "ip_address": ""})
    return _ZB_MAP.get((j.get("status") or "").lower().replace("_", "-"), "")


def _reoon_validate(email: str, key: str) -> str:
    j = _get("https://emailverifier.reoon.com/api/v1/verify",
             {"email": email, "key": key, "mode": "power"})
    s = (j.get("status") or "").lower()
    if j.get("is_disposable") or s in ("disposable", "spamtrap"):
        return "invalid"                         # throwaway/trap → never send
    if j.get("is_catch_all") or "catch" in s:    return "catch-all"
    if s in ("valid", "safe"):                   return "valid"
    if s in ("invalid", "disabled"):             return "invalid"
    return "unknown" if s else ""                # "" = out of credits / no answer


def _abstract_validate(email: str, key: str) -> str:
    j = _get("https://emailvalidation.abstractapi.com/v1/",
             {"api_key": key, "email": email})
    if (j.get("is_catchall_email") or {}).get("value"):
        return "catch-all"
    return {"DELIVERABLE": "valid", "UNDELIVERABLE": "invalid",
            "UNKNOWN": "unknown"}.get((j.get("deliverability") or "").upper(), "")


def _kickbox_validate(email: str, key: str) -> str:
    j = _get("https://api.kickbox.com/v2/verify", {"email": email, "apikey": key})
    return {"deliverable": "valid", "undeliverable": "invalid",
            "risky": "catch-all", "unknown": "unknown"}.get(
                (j.get("result") or "").lower(), "")


def _verifalia_validate(email: str, key: str) -> str:
    # `key` is a Verifalia browser-app credential pair "username:password".
    if ":" not in (key or ""):
        return ""
    import requests
    user, pw = key.split(":", 1)
    try:
        r = requests.post("https://api.verifalia.com/v2.4/email-validations",
                          params={"waitTime": 30000}, auth=(user, pw),
                          json={"entries": [{"inputData": email}]}, timeout=45)
        if r.status_code not in (200, 202):
            return ""
        data = ((r.json().get("entries") or {}).get("data") or [])
        c = (data[0].get("classification") or "").lower() if data else ""
        return {"deliverable": "valid", "undeliverable": "invalid",
                "risky": "catch-all", "unknown": "unknown"}.get(c, "")
    except Exception:                                   # noqa: BLE001
        return ""


# The free-first waterfall: providers with a recurring FREE tier, biggest first —
# and the DAILY-resetting Verifalia first of all, so its use-or-lose credits are
# spent before the monthly pools. Each is BYO-key (skipped without one) and
# fault-tolerant (a bad/empty reply → next). Paid keys act only as the fallback.
_VERIFIERS = [
    ("verifalia_api_key",   "Verifalia",   _verifalia_validate),# ~25/day free
    ("reoon_api_key",       "Reoon",       _reoon_validate),    # ~600/mo free
    ("zerobounce_api_key",  "ZeroBounce",  _zb_validate),       # 100/mo free
    ("abstractapi_api_key", "AbstractAPI", _abstract_validate), # 100/mo free
    ("kickbox_api_key",     "Kickbox",     _kickbox_validate),  # 50/mo free
]
def _tomba_find(lead, key: str):
    """Tomba email FINDER (name + domain -> the real address). `key` is the pair
    'X-Tomba-Key:X-Tomba-Secret'. Returns (email, verification_status)."""
    if ":" not in (key or ""):
        return "", ""
    tkey, tsecret = key.split(":", 1)
    first, last = _name_parts(lead.name)
    dom = _domain_of(lead)
    if not (first and last and dom):
        return "", ""
    import requests
    try:
        r = requests.get(f"https://api.tomba.io/v1/email-finder/{dom}",
                         params={"first_name": first, "last_name": last},
                         headers={"X-Tomba-Key": tkey, "X-Tomba-Secret": tsecret},
                         timeout=30)
        d = (r.json().get("data") or {})
        return (d.get("email") or ""), ((d.get("verification") or {}).get("status") or "")
    except Exception:                                   # noqa: BLE001
        return "", ""


class FinderRefused(Exception):
    """A finder turned the whole ACCOUNT away — a plan without API access, a
    used-up monthly quota, a key it does not know — not just this person. The
    message says which, in words the owner can act on. Anyone else asked would
    get the same answer, so find_and_verify stops asking that finder for the
    batch (`refused`) and the caller says why. 24-Sep-2026: Apollo's Free plan
    (no people/match) and Hunter's spent quota refused every lookup, both were
    swallowed as "not found", and 159 people were checked in silence."""


def _apollo_refusal(exc) -> str:
    if getattr(exc, "error_code", "") == "API_INACCESSIBLE":
        # Apollo names the plan: "…not included in your Basic (Trial) plan…" —
        # a trial of a paid plan is refused too (25-Sep-2026), so "Free" alone
        # would tell the owner who just started one that nothing changed.
        named = re.search(r"not included in your (.{1,40}?) plan", getattr(exc, "detail", "") or "")
        plan = f"your {named.group(1)} plan" if named else "your Apollo plan"
        return (f"Apollo: finding e-mails isn't in {plan}. Only paid Apollo plans "
                "include it.")
    if getattr(exc, "code", 0) == 401:
        return "Apollo: the API key was not accepted."
    return ("Apollo: this API key isn't allowed to find people. In Apollo's API "
            "settings, give it people/match.")


def _apollo_find(lead, key: str):
    """Apollo's people/match FINDER (the profile link or the Apollo id when the
    lead carries one, else name + domain -> the real address). One credit, and
    only when Apollo finds the person. Returns (email, verification_status);
    raises FinderRefused when Apollo refuses the key itself."""
    from .apollo import ApolloError, find_email     # lazily: apollo pulls in the filters
    try:
        return find_email(lead, key)
    except ApolloError as exc:                      # only 401 / 403 get this far
        raise FinderRefused(_apollo_refusal(exc)) from exc


def _hunter_reset(key: str) -> str:
    """"27 Sep": when Hunter's searches come back — its account call, which
    costs nothing — or ""."""
    import datetime
    import requests
    try:
        data = requests.get(ACCOUNT, params={"api_key": key}, timeout=15).json().get("data") or {}
        day = datetime.date.fromisoformat(str(data.get("reset_date") or "")[:10])
    except Exception:                                   # noqa: BLE001
        return ""
    return f"{day.day} {day:%b}"


def _hunter_refusal(code: int, body, key: str) -> str:
    """Why Hunter turned the ACCOUNT away, or "" for anything about this one
    person or this one moment. Its quota answer (429, "…the number of searches
    per billing period included in your plan") is told apart from its
    per-second rate limit, which is also a 429 and passes."""
    errors = body.get("errors") if isinstance(body, dict) else None
    details = " ".join(str(e.get("details") or "") for e in errors or ()
                       if isinstance(e, dict)).lower()
    if code == 401:
        return "Hunter: the API key was not accepted."
    if code in (403, 429) and ("billing period" in details or "your plan" in details):
        back = _hunter_reset(key)
        return ("Hunter: this month's searches are used up. "
                + (f"They come back on {back}." if back else "They come back next month."))
    return ""


def _hunter_find(lead, key: str):
    """Hunter Email FINDER only (name + the company's domain -> the real
    address; the company's NAME when no domain is known — Hunter finds the
    domain itself). NO verify call — so ALL of Hunter's monthly credits go to
    finding, and the free verifiers do the confirming. Returns (email,
    verification_status); raises FinderRefused when Hunter refuses the account
    (a key it does not know, this month's searches used up)."""
    first, last = _name_parts(lead.name)
    dom = _registrable(_domain_of(lead))
    company = (getattr(lead, "company", "") or "").strip()
    if not (first and last and (dom or company)):
        return "", ""
    params = {"first_name": first, "last_name": last, "api_key": key}
    if dom:
        params["domain"] = dom
    else:
        params["company"] = company
    import requests
    try:
        reply = requests.get(FINDER, params=params, timeout=30)
        body = reply.json()
    except Exception:                                   # noqa: BLE001
        return "", ""
    why = _hunter_refusal(getattr(reply, "status_code", 200), body, key)
    if why:
        raise FinderRefused(why)
    try:
        d = (body.get("data") or {})
        email = d.get("email") or ""
        if email and d.get("linkedin_url") and not (lead.extra or {}).get("linkedin"):
            lead.extra["linkedin"] = d["linkedin_url"]
        return email, ((d.get("verification") or {}).get("status") or "")
    except Exception:                                   # noqa: BLE001
        return "", ""


# The FINDERS — the only way Prism gets an address it was not handed (the
# owner, 24-Sep-2026: "hunter + apollo only to find mails"; addresses are never
# guessed). Hunter is our MAIN finder (the owner, 27-Sep-2026: "our main will
# always be hunter") — free plans keep working, and it is a FINDER ONLY, so
# every one of its monthly credits goes to finding, never spent confirming
# what it already found. Apollo is the fallback, for whoever Hunter missed —
# useful only with a paid Apollo plan (the free one refuses people/match
# outright, so it is asked once a batch and then left alone: see
# AFinderThatRefusesTheAccountIsAskedOnce). Both charge only when they know
# the person.
_FINDERS = [
    ("hunter_api_key",  "Hunter", _hunter_find),        # our main finder — monthly credits, FIND only
    ("apollo_api_key",  "Apollo", _apollo_find),        # fallback — 1 credit per person FOUND
]
# Every finder/verifier config key — collected from config/env by collect_keys.
VERIFIER_KEYS = [k for k, _, _ in _FINDERS] + [k for k, _, _ in _VERIFIERS]


def collect_keys(cfg: dict | None = None) -> dict:
    """{cfg_key: value} for every verifier/finder key present in config or env.
    Pooled (`gateway.effective_cfg`): ONE entry, the pool sentinel — the licence
    server holds every verifier and finder key, tries them free-first, and
    charges the customer per address checked or found. No key of the
    customer's is read (owner, 25-Sep-2026: pooled credits only)."""
    cfg = cfg or {}
    if cfg.get("leads_pool"):
        return {"pool": gateway.POOL_KEY}
    out = {}
    for k in VERIFIER_KEYS:
        v = (cfg.get(k) or os.environ.get(k.upper()) or "").strip()
        if v:
            out[k] = v
    return out


def find_domains(leads, cfg: dict | None = None) -> None:
    """The real website of every company among `leads` with nobody found and no
    domain yet — one Exa lookup per company (enrich.enrich), so the finders
    that follow ask Hunter/Apollo BY DOMAIN, not just a company's bare name.

    27-Sep-2026: this step never ran (enrich.enrich was built, tested, and
    never wired into a run), so every finder call went out with just a
    company's name — Hunter answered nothing for "company=Asian Paints" but
    found its CEO instantly for "domain=asianpaints.com", a company that size.
    Fixed here, called once per batch before the finder loop, instead of once
    per lead inside find_and_verify — enrich already dedupes by company, and a
    lead-by-lead call would ask Exa for the same company's site again for
    every person who works there.

    `cfg` is the run's OWN config — pooled (gateway.effective_cfg) or direct —
    so this reads exactly the key find_and_verify itself would use: the pool
    sentinel, the caller's own Exa key, or nothing, in which case this is a
    silent no-op and the finders fall back to a company's bare name, same as
    before this existed."""
    from . import enrich, signals
    key = signals.exa_key(cfg)
    if key:
        enrich.enrich(leads, key)


def _hunter_domain_search(domain: str, key: str, limit: int = 25) -> list:
    """Every named person Hunter already has on file for one domain — the
    direct-mode twin of the server's leads_providers.domain_search_hunter,
    kept in step by this comment and by test. A real database lookup
    (confirmed 02-Oct-2026: identical rows on a repeat call), not a search for
    anyone in particular — a cheap FIRST PASS before find_and_verify's
    per-person ask. [] on anything that is not a clean 200; Hunter's own
    "type": "generic" rows (info@, sales@) are never somebody's name, so only
    "personal" entries are kept."""
    import requests
    try:
        r = requests.get(DOMAIN_SEARCH, params={"domain": domain, "api_key": key, "limit": limit},
                         timeout=30)
    except Exception:                                   # noqa: BLE001
        return []
    if r.status_code != 200:
        return []
    try:
        data = r.json()
    except ValueError:
        return []
    rows = ((data.get("data") or {}).get("emails") or [])
    if not isinstance(rows, list):
        return []
    return [{"first_name": str(e.get("first_name") or ""), "last_name": str(e.get("last_name") or ""),
            "email": str(e.get("value") or "")}
           for e in rows if isinstance(e, dict) and e.get("type") == "personal"
           and e.get("first_name") and e.get("last_name") and e.get("value")]


def _domain_groups(leads) -> dict:
    """{registrable domain: [leads with no address yet and that domain already
    known]} — unlike the phone finder, Domain Search has no company-NAME
    fallback, so a lead with no domain yet (find_domains found none, or never
    ran) is simply left for find_and_verify's ordinary per-person ask."""
    out: dict = {}
    for l in leads or ():
        if (getattr(l, "email", "") or "").strip():
            continue
        first, last = _name_parts(getattr(l, "name", "") or "")
        dom = _registrable(_domain_of(l))
        if first and last and dom:
            out.setdefault(dom, []).append(l)
    return out


def find_emails_by_domain(leads, keys: dict | None = None) -> None:
    """One Hunter Domain Search per company domain — instead of one Email
    Finder ask per named person — for every lead with no address yet and a
    domain `find_domains` (or a sheet) already gave it. A company with several
    named leads is resolved in ONE call instead of one apiece; a lead this
    pass does not resolve still gets the ordinary find_and_verify pass right
    after, so coverage never drops, only the number of calls it took.

    Billed exactly like the per-person finder (email_find, pooled) — this
    changes what Hunter is asked, never what it costs: an efficiency gain for
    whoever holds the key, not a different product.

    02-Oct-2026, confirmed live: asianpaints.com and tatamotors.com each
    returned 10 real named people, identically on a repeat call — a real
    database lookup, not an agent's live guess (contrast prospector/phones.py's
    Fiber test the same day: 18 of 19 overlapping leads got a DIFFERENT number
    each run). Writes straight onto matching leads (email + email_source
    "hunter"), so find_and_verify's own "already sold by this finder" guard
    sees it and does not ask Hunter again for someone this pass already found.

    Pooled: one gateway.find_emails call per 50 people (gateway.is_pool(keys)).
    Direct: one Domain Search per domain with the caller's own Hunter key.
    No Hunter key, pooled or direct, is a silent no-op."""
    keys = keys or {}
    groups = _domain_groups(leads)
    if not groups:
        return
    if gateway.is_pool(keys):
        people, by_ref = [], {}
        for gi, (dom, group) in enumerate(groups.items()):
            for li, l in enumerate(group):
                ref = "p%d_%d" % (gi, li)
                first, last = _name_parts(l.name)
                people.append({"ref": ref, "first_name": first, "last_name": last, "domain": dom})
                by_ref[ref] = l
        for i in range(0, len(people), 50):
            rows = gateway.find_emails(people[i:i + 50])
            for row in rows or []:
                l = by_ref.get(row.get("ref"))
                email = str(row.get("email") or "")
                if l is not None and email:
                    l.email = email
                    l.extra["email_source"] = str(row.get("provider") or "hunter")
        return
    key = keys.get("hunter_api_key", "")
    if not key:
        return
    for dom, group in groups.items():
        listing = _hunter_domain_search(dom, key)
        if not listing:
            continue
        by_name = {(e["first_name"].casefold(), e["last_name"].casefold()): e["email"] for e in listing}
        for l in group:
            first, last = _name_parts(l.name)
            hit = by_name.get((first.casefold(), last.casefold()))
            if hit:
                l.email = hit
                l.extra["email_source"] = "hunter"


_STATUS_RANK = {"valid": 3, "invalid": 2, "catch-all": 1, "unknown": 0}


def verify_email(email: str, keys: dict | None = None) -> str:
    """Verify a plain address through the free-first verifier waterfall (no
    finding step) — for checking a ready-made list before a send. Returns
    valid / invalid / catch-all / unknown, or '' when no key is set or none
    answered. A verifier asks the mail server directly, so it catches the
    'live domain but the mailbox doesn't exist' guesses that hard-bounce (550).

    'valid' stops the waterfall — nothing more to learn, no point spending the
    next verifier's credit. Anything less sure (invalid / catch-all / unknown,
    or a blank reply because a key is out of credit) keeps going: a different
    verifier's probe can land where the last one couldn't decide, so the best
    answer any of them gave wins rather than the first one to say anything."""
    keys = keys or {}
    email = (email or "").strip()
    if not email:
        return ""
    if gateway.is_pool(keys):
        return gateway.check_email(email)       # the server runs the waterfall
    best = ""
    for cfg_key, _name, fn in _VERIFIERS:
        k = keys.get(cfg_key)
        if not k:
            continue
        s = fn(email, k)
        if s == "valid":
            return s
        if s and _STATUS_RANK.get(s, -1) > _STATUS_RANK.get(best, -1):
            best = s
    return best


def find_and_verify(lead, keys: dict | None = None, refused: dict | None = None) -> None:
    """FIND the person's real address, and CHECK it — never a guess (the
    owner, 24-Sep-2026: "the emails shouldn't be guessed any day — hunter +
    apollo only to find mails"):
      1) An address the lead already has came from somewhere real — their own
         sheet, Apollo, a finder (an old guess is set aside when it is read
         back: enrich.forget_guess). It is checked with the free verifiers
         (Verifalia → Reoon → ZeroBounce → AbstractAPI → Kickbox); 'valid' or
         'catch-all' is as sure as it gets and ends here.
      2) No address, or one the check could not confirm — the FINDERS, Apollo
         then Hunter, asked with the person's name and their company's domain,
         or its name when no domain is known. A credit only when one of them
         knows the person, and what comes back is checked too. The finder that
         SOLD us the address we hold (extra["email_source"]) is not asked again.
    Nobody found keeps no address — "No email", never a made-up one. BYO-key;
    a missing key is skipped, errors are ignored. `refused` ({finder name:
    why}), shared across a batch, collects the finders that turned the account
    away (FinderRefused) — they are not asked again, and the caller says why;
    a refusal never ends the run."""
    keys = keys or {}

    def _verify(addr: str) -> str:
        """Run the free verifier waterfall over one address and record the
        result — delegates to verify_email so every caller agrees on which
        verifier's answer wins when more than one responds."""
        status = verify_email(addr, keys)
        if status:
            lead.extra["email_check"] = status
        return status

    # 1) VERIFY the address we already have — FREE. A confirmed guess is done.
    email = (lead.email or "").strip()
    if email and _verify(email) == "valid":
        return
    # 2) Not confirmed (no address, or invalid/unknown) — FIND the real one (a
    #    finder credit), then verify what came back. 'catch-all' can't be
    #    confirmed either way, so we don't spend a credit chasing it.
    check = (lead.extra or {}).get("email_check", "")
    source = (lead.extra or {}).get("email_source", "")
    if (lead.name or "") and _domain_of(lead) and check not in ("valid", "catch-all") \
            and gateway.is_pool(keys):
        # Pooled: one finder lookup, made (and billed) by the licence server,
        # which asks Hunter and charges only when it knows the person. (Tomba
        # is out; "tomba" stays in _POOL_FINDERS only for old saved leads.)
        first, last = _name_parts(lead.name)
        if first and email and source in _POOL_FINDERS:
            return                  # that finder already sold us this address
        if first:
            found, _status, by = gateway.find_email(first, last, _domain_of(lead))
            if found and found.strip().lower() != email.lower():
                lead.email = found
                lead.extra["email_source"] = by or "pool"
                _verify(found)
        return                      # pooled means pooled: nobody found is "No email"
    somewhere = _domain_of(lead) or (getattr(lead, "company", "") or "").strip()
    if (lead.name or "") and somewhere and check not in ("valid", "catch-all"):
        for cfg_key, name, fn in _FINDERS:
            k = keys.get(cfg_key)
            if not k or (refused is not None and name in refused):
                continue
            # The finder that supplied the address we are holding has nothing
            # left to sell: asked again it looks the same person up and returns
            # the same address, for another credit.
            if email and source == name.lower():
                continue
            try:
                found, _status = fn(lead, k)
            except FinderRefused as why:
                if refused is not None:
                    refused[name] = str(why)
                continue
            if found and found.strip().lower() != email.lower():
                lead.email = found
                # Whoever supplied the address is who must not be asked for it
                # again — by this run's verify, or by a later one reopening the
                # session this lead is saved in.
                lead.extra["email_source"] = name.lower()
                _verify(found)          # confirm the freshly found address, free
                break


def verify_reachable(dossiers, keys: dict | None = None, limit: int = 25,
                     on_progress=None, cfg: dict | None = None) -> int:
    """FIND + VERIFY the hot/warm slice: the finders (Hunter, our main one,
    then Apollo) find the real address, then the FREE verifier waterfall
    (Verifalia → Reoon → ZeroBounce → AbstractAPI → Kickbox) confirms it. Runs
    only on the people about to be emailed, staying inside the free tiers.
    Sequential on purpose — free tiers are rate-limited and this list is
    short. With no keys it is skipped and the sheet keeps its free MX check.

    `cfg` (optional, the run's own config) looks up this slice's companies'
    real domains first (find_domains) — with no `cfg`, or no Exa key in it,
    this is skipped exactly as before, and the finders fall back to a
    company's bare name."""
    keys = keys or {}
    if not any(keys.values()):
        return 0
    targets = [d for d in dossiers if d.verdict in (HOT, WARM) and d.lead.name][:limit]
    find_domains([d.lead for d in targets], cfg)
    find_emails_by_domain([d.lead for d in targets], keys)
    refused: dict = {}              # a finder that refused the key is asked once a run
    for i, d in enumerate(targets, 1):
        if gateway.exhausted():
            return i - 1            # the pool ran dry: stop here, keep what was checked
        if on_progress:
            on_progress(i, len(targets), d.lead)
        find_and_verify(d.lead, keys, refused)
    return len(targets)
