"""
Prism Sales Automation — Apollo: the same filters, asked of a real database
──────────────────────────────────────────────────────────────────────────
Exa reads the open web and answers one sentence at a time; Apollo.io SELLS the
B2B contact database itself, and its people search takes the very facets Leads
& Outreach already holds — titles, seniority, person location, company HQ,
headcount, revenue. So the seller who brings an Apollo key gets their list from
Apollo's own index instead of from a prose query, with no second filter model:
`filters.SearchSpec` is still the only description of who the list is for.

What shapes every line below is Apollo's price list:

  · **Search is free.** `mixed_people/api_search` costs 0 credits, and it hands
    back no e-mail, no phone and an obfuscated last name — a catalogue card,
    not a contact.
  · **Revealing costs a credit**, one per person Apollo actually finds
    (`people/bulk_match`, ten at a time).

So the run spends nothing until the last possible moment. Everything that can
be decided from the free card is decided first — people earlier sessions
already pulled (`skip`, by Apollo id before anything else), the same person
twice in one run — and everything Apollo itself can narrow is pushed into the
SEARCH parameters, above all the location: Apollo has no exclusion parameter at
all, so "anywhere except India" is sent as the ~200 country names that are left
(`places.regions_outside`), and an Indian never reaches a credit in the first
place. Only what Apollo cannot express — an excluded job title, company or
keyword, and the bands it can only approximate — is enforced after the reveal
(`filters.match_person` / `filters.match_company`), and those people are
counted in `stats["filtered"]` so the owner can see what the credits bought.

And because that last kind of filtering happens AFTER the money is spent, the
run carries a `budget` — the credits it may spend, `target` by default, so the
rail's "Reveal up to 300" is 300 credits and not a hope. Without one, an
exclusion Apollo cannot express (nine "Sales Plant Heads" for every "Plant
Head") leaves the target as far off after each reveal as before it, and the
run would pay its way down the whole index chasing a number it can never
reach. Hitting the budget ends the run and is reported as `stats["short_by"]`,
next to the `stats["filtered"]` counts that say where the credits went.

BYO-key and stdlib-plus-requests: `requests` is imported lazily through
`_requests()` so a test can stand in for the whole network, and every failure
Apollo can return becomes an `ApolloError` written for the owner, not a stack
trace.
"""
from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from . import filters, identity, monid_run
from .models import Lead

BASE = "https://api.apollo.io/api/v1"
SEARCH = "/mixed_people/api_search"      # 0 credits, no e-mails
MATCH = "/people/match"                  # 1 credit when Apollo finds the person
BULK_MATCH = "/people/bulk_match"        # the same, ten people per call

# Apollo refuses any single value longer than this — seen live as
# "Value too long: '…' exceeds 200 characters" when prose reached the filters.
MAX_VALUE = 200
# "10,001+" has no upper bound; Apollo's ranges do, so the top band is written
# against a number no company reaches.
_TOP_HEADCOUNT = 1_000_000
_BATCH = 10                              # people per bulk_match call (Apollo's cap)
_APOLLO_PAGES = 500                      # 500 pages × 100 = the 50,000-record ceiling
_RETRIES = 2                             # 429 retries, then the run stops
_WAIT = 5                                # seconds when Apollo sends no Retry-After
_MAX_WAIT = 60

# Every message here is read by the owner, in a dialog, mid-run — so each one
# says what Apollo refused AND what to do about it.
NO_KEY = ("No Apollo API key. Paste one in Settings > Agents (Apollo > "
          "Settings > Integrations > API) to source from Apollo.")
BAD_KEY = "Apollo rejected the API key — check it in Settings > Agents."
# Apollo's own 403 reads "This API key is not authorized to access
# api/v1/…. Request an API key from your administrator that includes this
# endpoint in its configured scope." — i.e. the key is scoped, not a master key.
# A scoped Apollo key 403s on every endpoint it was not ticked for, one at a
# time — so name ALL THREE Prism calls here. Hearing about them one failed run
# apiece is three trips to Apollo's settings for what is really one decision.
SCOPED_KEY = ("Apollo would not let this key use {path}. Two things do that, "
              "and Apollo's own API Keys page says which: a FREE plan (these "
              "endpoints are not in it, and a master key does not help — every "
              "paid plan includes them), or a key scoped to other endpoints. "
              "For a scoped key, in Apollo under Settings > Integrations > API "
              "Keys, edit it (or make a new one) and either tick “Set as "
              "master key” or scope it to all three endpoints Prism calls: "
              "mixed_people/api_search (the search), people/bulk_match "
              "(revealing names and e-mails) and people/match (finding one "
              "address). On a free plan, switch “Search with” to Exa "
              "instead.")

BAD_PARAMS = ("Apollo refused the search filters — a value is one it does not "
              "accept, or is longer than 200 characters. Narrow the filters and "
              "run it again.")
RATE_LIMITED = ("Apollo is rate-limiting this key (about 600 search calls an "
                "hour). Wait a few minutes and run it again.")
UNREACHABLE = "Could not reach Apollo — check the internet connection and try again."
REFUSED = "Apollo answered {code} for {path}."


class ApolloError(Exception):
    """Something Apollo said no to, in words the owner can act on. `code` is
    the HTTP status when Apollo answered one (0 otherwise) and `error_code`
    Apollo's own name for the refusal ("API_INACCESSIBLE": a Free plan)."""

    def __init__(self, message: str = "", code: int = 0, error_code: str = "",
                 detail: str = ""):
        super().__init__(message)
        self.code = code
        self.error_code = error_code
        self.detail = detail                # Apollo's own sentence, when it sent one


class _Unreachable(ApolloError):
    """The call never landed (no network, a timeout). Mid-run this ends the
    sourcing with what it already has; on the very first call it is raised, so
    the owner is not shown an empty list and told nothing."""


# ── the call ──────────────────────────────────────────────────────────────────

def _requests():
    # Lazily, and through a seam a test can replace with a recorder.
    import requests
    return requests


def _pause(seconds: float) -> None:
    time.sleep(seconds)


def _retry_after(response) -> float:
    """The wait Apollo asked for, clamped — a header saying "one hour" must not
    hang the run."""
    headers = getattr(response, "headers", None) or {}
    try:
        value = float(str(headers.get("Retry-After") or "").strip())
    except (TypeError, ValueError):
        return _WAIT
    return min(max(value, 1.0), _MAX_WAIT)


def _message(code: int, path: str) -> str:
    if code == 401:
        return BAD_KEY
    if code == 403:
        return SCOPED_KEY.format(path=path)
    if code in (400, 422):
        return BAD_PARAMS
    return REFUSED.format(code=code, path=path)


def _post(path: str, body: dict, api_key: str, timeout: int = 30) -> dict:
    """One Apollo POST, as JSON, with the key in the `x-api-key` header. 429 is
    retried up to twice, honouring Retry-After; every other refusal raises an
    ApolloError the owner can read."""
    url = BASE + path
    headers = {"x-api-key": api_key, "Content-Type": "application/json",
               "Accept": "application/json"}
    attempt = 0
    while True:
        try:
            response = _requests().post(url, json=body, headers=headers, timeout=timeout)
        except Exception as exc:                        # noqa: BLE001
            raise _Unreachable(UNREACHABLE) from exc
        code = int(getattr(response, "status_code", 0) or 0)
        if code == 429:
            if attempt >= _RETRIES:
                raise ApolloError(RATE_LIMITED)
            attempt += 1
            _pause(_retry_after(response))
            continue
        if code in (200, 201):
            try:
                return response.json() or {}
            except Exception:                           # noqa: BLE001
                return {}
        raise ApolloError(_message(code, path), code, *_refusal_of(response))


def _refusal_of(response) -> tuple:
    """(error_code, error): Apollo's own name for a refusal ("API_INACCESSIBLE")
    and its sentence ("…not included in your Basic (Trial) plan…"), or ""s."""
    try:
        body = response.json()
    except Exception:                                   # noqa: BLE001
        return "", ""
    if not isinstance(body, dict):
        return "", ""
    return str(body.get("error_code") or ""), str(body.get("error") or "")


def api_key(cfg: dict | None = None) -> str:
    cfg = cfg or {}
    return (cfg.get("apollo_api_key") or os.environ.get("APOLLO_API_KEY") or "").strip()


# ── the filters, as Apollo takes them ─────────────────────────────────────────

def _as_spec(spec):
    return filters.SearchSpec.from_dict(spec) if isinstance(spec, dict) else spec


def _trim(value) -> str:
    """One value, fit for Apollo: spaces collapsed and never over 200 characters."""
    return " ".join(str(value or "").split())[:MAX_VALUE].strip()


def _clean(values) -> list:
    out = []
    for value in values:
        text = _trim(value)
        if text and text not in out:
            out.append(text)
    return out


def _ask_places(facet) -> list:
    """The place names to ASK Apollo for. Apollo has no "not in" parameter, so
    an exclusion cannot be sent — it has to become the places that are LEFT
    (`places.regions_outside`, the whole world minus India when the filter says
    "anywhere except India"). The result is then checked against the excluded
    place's own names, because a name that slipped through would be paid for in
    credits, one Indian at a time."""
    if not facet.exclude:
        return _clean(facet.include)
    from . import places
    names = places.regions_outside(facet.exclude, facet.include)
    banned = set()
    for value in facet.exclude:
        banned.update(places.aliases_of(value))
        banned.add(" ".join(str(value).split()).casefold())
    return _clean(n for n in names if n.casefold() not in banned)


def _employee_ranges(bands) -> list:
    """The headcount bands as Apollo writes them: "1,10" … "10001,1000000"."""
    out = []
    for key in bands:
        low, high = filters.HEADCOUNT_RANGES.get(key, (None, None))
        if low is not None:
            out.append(f"{low},{_TOP_HEADCOUNT if high is None else high}")
    return out


def _revenue_span(bands) -> tuple:
    """(min, max) US dollars spanning every chosen revenue band; max is None for
    the top band. Apollo takes one span, not a set of bands, so two bands with a
    gap between them are asked for as the whole stretch — `match_company` puts
    the gap back after the reveal."""
    spans = [filters.REVENUE_RANGES[k] for k in bands if k in filters.REVENUE_RANGES]
    if not spans:
        return None, None
    low = min(lo for lo, _ in spans)
    high = None if any(hi is None for _, hi in spans) else max(hi for _, hi in spans)
    return low, high


def params_for(spec, industry: str = "") -> dict:
    """The Apollo search body for this spec (one industry at a time, since
    Apollo has no industry facet and the word belongs in `q_keywords`). Pure —
    no page, no key, no network.

    Sent: person_titles (the job titles, else the roles seniority × function
    spells out), include_similar_titles, person_seniorities (Apollo's own keys,
    which is why the panel uses them), person_locations and
    organization_locations (includes as given; with an exclusion, the places
    left over), organization_num_employees_ranges, revenue_range[min]/[max],
    q_keywords (the industry, the typed keywords, and — only when neither a
    title nor a seniority narrows the search — the chosen functions).

    NOT sent, because Apollo's search has no exclusion parameter: excluded job
    titles, companies and keywords. They are enforced after the reveal."""
    spec = _as_spec(spec)
    body: dict = {}

    titles = _clean(spec.job_titles.include or spec.role_terms())
    if titles:
        body["person_titles"] = titles
        body["include_similar_titles"] = bool(spec.similar_titles)
    seniorities = _clean(spec.seniority.include)
    if seniorities:
        body["person_seniorities"] = seniorities

    where = _ask_places(spec.locations)
    if where:
        body["person_locations"] = where
    hq = _ask_places(spec.company_hq)
    if hq:
        body["organization_locations"] = hq

    sizes = _employee_ranges(spec.headcount)
    if sizes:
        body["organization_num_employees_ranges"] = sizes
    low, high = _revenue_span(spec.revenue)
    if low is not None:
        body["revenue_range[min]"] = int(low)
        if high is not None:
            body["revenue_range[max]"] = int(high)

    words = [w for w in ([_trim(industry)] + _clean(spec.keywords.include)) if w]
    # Functions are read off the title, so they only add noise when a title or
    # a level already points the search; with neither, they ARE the search.
    if not spec.job_titles.include and not spec.seniority.include:
        words += [filters.label_of(filters.FUNCTIONS, k).split(" & ")[0]
                  for k in spec.functions.include]
    if words:
        body["q_keywords"] = _trim(" ".join(words))
    return body


# ── reading what Apollo sends back ────────────────────────────────────────────

def _text(value) -> str:
    return " ".join(str(value or "").split())


def _int(value):
    """A whole number, or None when the record holds none (Apollo writes
    revenue as a float and leaves unknown sizes null)."""
    try:
        if value is None or isinstance(value, bool):
            return None
        number = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 else None


def _host(url) -> str:
    text = _text(url)
    if not text:
        return ""
    if "://" not in text:
        text = "https://" + text
    try:
        host = (urlsplit(text).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _org(person) -> dict:
    org = person.get("organization")
    return org if isinstance(org, dict) else {}


def _full_name(person) -> str:
    parts = [_text(person.get("first_name")), _text(person.get("last_name"))]
    return " ".join(p for p in parts if p) or _text(person.get("name"))


def _email_of(person) -> str:
    """The address, or "" — Apollo answers a locked record with the placeholder
    `email_not_unlocked@domain.com`, which would be mailed to nobody."""
    email = _text(person.get("email")).lower()
    if "@" not in email or "not_unlocked" in email or email.startswith("email_not"):
        return ""
    return email


def _check_of(person) -> str:
    """The Email-check value the sheets colour on: Apollo's "verified" is the
    only status it stands behind, and everything else is a guess."""
    return "valid" if _text(person.get("email_status")).lower() == "verified" else "unknown"


def _since(person) -> str:
    """"YYYY-MM" the person started their current role, or "" — the live role
    first, the latest-starting one when Apollo marks none current."""
    history = person.get("employment_history")
    rows = [r for r in history if isinstance(r, dict)] if isinstance(history, list) else []
    live = [r for r in rows if r.get("current")]
    pick = max(live or rows, key=lambda r: _text(r.get("start_date")), default=None)
    start = _text(pick.get("start_date")) if pick else ""
    return start[:7] if len(start) >= 7 and start[4] == "-" else ""


def _where(person) -> str:
    """"City, State, Country" from whatever Apollo has — `match_person` reads
    this string against the location filter, so the country must be in it."""
    parts = [_text(person.get(k)) for k in ("city", "state", "country")]
    return ", ".join(p for p in parts if p)


def _lead_of(person, industry: str = "") -> Lead | None:
    """The Lead one revealed person makes, or None when the record names no one
    or no employer — a person with neither can be neither filtered nor mailed."""
    if not isinstance(person, dict):
        return None
    org = _org(person)
    name = _full_name(person)
    company = _text(org.get("name")) or _text(person.get("organization_name"))
    if not (name and company):
        return None
    email = _email_of(person)
    lead = Lead(name=name, title=_text(person.get("title")), company=company, email=email,
                industry=_text(org.get("industry")) or _text(industry))
    lead.extra["location"] = _where(person)
    lead.extra["linkedin"] = _text(person.get("linkedin_url"))
    lead.extra["apollo_id"] = _text(person.get("id"))
    if email:
        lead.extra["email_check"] = _check_of(person)
        # Who sold us this address. Apollo's own status is only "verified" for
        # some of them, and an unconfirmed one sends the verify waterfall to the
        # finders — where Apollo would charge a second credit to hand back this
        # very address. `find_email` reads this and declines.
        lead.extra["email_source"] = "apollo"
    domain = _text(org.get("primary_domain")) or _host(org.get("website_url"))
    if domain:
        lead.extra["company_domain"] = domain
    headcount = _int(org.get("estimated_num_employees"))
    if headcount is not None:
        lead.extra["headcount"] = headcount
    revenue = _int(org.get("annual_revenue"))
    if revenue is not None:
        lead.extra["revenue"] = revenue
    since = _since(person)
    if since:
        lead.extra["since"] = since
    return lead


def _facts_of(lead, person) -> dict:
    """The company lookup `filters.match_company` expects, built from the
    organization Apollo already sent — so the bands are checked without a
    second call to anybody."""
    org = _org(person)
    hq = ", ".join(p for p in (_text(org.get("city")), _text(org.get("country"))) if p)
    return {"headcount": lead.extra.get("headcount"),
            "revenue": lead.extra.get("revenue"),
            "hq": hq,
            "description": lead.industry}


# ── sourcing ──────────────────────────────────────────────────────────────────

def _counts(stats) -> dict:
    counts = stats if isinstance(stats, dict) else {}
    for key in ("search_calls", "reveal_calls", "searched", "revealed",
                "skipped_seen", "duplicates", "errors", "short_by"):
        counts[key] = int(counts.get(key) or 0)
    if not isinstance(counts.get("filtered"), dict):
        counts["filtered"] = {}
    return counts


def _card(person, industry: str) -> dict:
    """One free search row as the run holds it: enough to recognise the person
    and to ask for them by id, and nothing that costs anything.

    The name is kept only when Apollo hands back the WHOLE surname. Search
    obfuscates it ("Rahul S."), and a half name at a large employer is a
    bucket, not a person: used as an identity it would fold two real Rahuls at
    Acme into one and drop the second before anyone ever saw them."""
    org = _org(person)
    return {"id": _text(person.get("id")),
            "first": _text(person.get("first_name")),
            "name": "" if person.get("last_name_obfuscated") else _full_name(person),
            "company": _text(org.get("name")) or _text(person.get("organization_name")),
            "domain": _text(org.get("primary_domain")) or _host(org.get("website_url")),
            "linkedin": _text(person.get("linkedin_url")),
            "industry": industry,
            # What the free search shows and a preview row keeps (the Apollo way, 25-Nov-2026): the surname's
            # initial, the title, and whether Apollo holds an e-mail or a direct phone for them.
            "last_hint": _text(person.get("last_name_obfuscated")),
            "title": _text(person.get("title")),
            "has_email": bool(person.get("has_email")),
            "has_phone": bool(person.get("has_direct_phone")) and person.get("has_direct_phone") != "No"}


PREVIEW = "apollo_preview"      # lead.extra flag: a free search card, not revealed (no full name, no e-mail)


def is_preview(lead) -> bool:
    """A person Apollo's free search found and nobody has revealed yet: a first name and a surname's initial, no
    e-mail. Finding their e-mail or mobile would be asked with half a name, so those wait for Reveal."""
    return bool((getattr(lead, "extra", None) or {}).get(PREVIEW))


def _preview_of(card: dict) -> Lead:
    """A free search card as a row the owner can see and tick: "Ana R." at Acme, Head of Operations. It costs
    nothing; Reveal buys the full name and e-mail (reveal_leads)."""
    shown = " ".join(x for x in (card["first"], card["last_hint"]) if x) or card["first"]
    lead = Lead(name=card["name"] or shown, title=card["title"], company=card["company"],
                industry=card["industry"])
    lead.extra["apollo_id"] = card["id"]
    lead.extra["linkedin"] = card["linkedin"]
    if card["domain"]:
        lead.extra["company_domain"] = card["domain"]
    lead.extra["apollo_has_email"] = card["has_email"]
    lead.extra["apollo_has_phone"] = card["has_phone"]
    if not card["name"]:
        lead.extra[PREVIEW] = True                      # the surname came back whole: nothing left to reveal
    return lead


def _stub(card: dict) -> Lead:
    """The card as a Lead, only so `identity.keys_of` can say who it is: the
    Apollo id, the profile link, and — when the surname came through whole —
    the name/company pair. This is the lead that `skip` is asked about, before
    a credit is spent rather than after."""
    lead = Lead(name=card["name"], company=card["company"])
    lead.extra["apollo_id"] = card["id"]
    lead.extra["linkedin"] = card["linkedin"]
    return lead


def _details(card: dict) -> dict:
    """One entry in a bulk_match call. The last name is left OUT on purpose:
    search obfuscates it ("Rahul S."), and sending the half-name would tell
    Apollo to match somebody else."""
    detail = {}
    for key, value in (("id", card["id"]), ("linkedin_url", card["linkedin"]),
                       ("first_name", card["first"]), ("domain", card["domain"])):
        if value:
            detail[key] = value
    if card["company"] and not card["domain"]:
        detail["organization_name"] = card["company"]
    return detail


def search_people(spec, api_key, *, target=25, skip=None, stats=None, on_progress=None,
                  max_pages=20, per_page=100, budget=None, transport=None, reveal=True) -> list:
    """Up to `target` people from Apollo who pass the whole spec, for at most
    `budget` credits (the target itself unless a caller says otherwise).

    Free pages first: each included industry is searched in turn (breadth-first,
    so one industry cannot eat the target), and every card is checked against
    `skip` — anyone an earlier session already pulled, recognised by their
    Apollo id before anything else — and against the people already queued this
    run. Only what is left is REVEALED, ten at a time, and only as many as the
    target still needs, because a reveal is a credit. Each revealed person is
    then put through `filters.match_person` and `filters.match_company`: Apollo
    has no exclusion parameter, so an excluded title, company or keyword can
    only be enforced here, and those people are counted in `stats["filtered"]`.

    Those post-reveal drops bring the target no closer, so the run stops at
    `budget` credits whatever happens — the promise the rail makes ("Reveal up
    to N") kept literally — and comes back short rather than paying its way
    down the index for a target the filters will not let it fill.

    `skip` is anything answering `lead in skip` (a `SeenIndex`). `stats`, if a
    dict, gets search_calls, reveal_calls, searched (cards read), revealed
    (people Apollo found — the credits spent), filtered ({REASONS key: count}),
    skipped_seen, duplicates, errors and short_by. `on_progress(stage, done,
    total, found)` is called with stage "search" or "reveal".

    Raises ApolloError when Apollo refuses the key, the endpoint or the filters,
    and when it is still rate-limiting after the retries. A network failure once
    the run is under way ends it with what it has and counts stats["errors"].

    `transport(path, body) -> dict` replaces the call to api.apollo.io: with it no
    Apollo key is needed (`monid_transport`: the same two calls, asked of Apollo
    through the owner's Monid wallet — search still free, a reveal about $0.026)."""
    spec = _as_spec(spec)
    key = (api_key or "").strip()
    if not key and transport is None:
        raise ApolloError(NO_KEY)
    send = transport or (lambda path, body: _post(path, body, key))
    counts = _counts(stats)
    target = max(0, int(target or 0))
    # The credits this run may spend. `target` counts people who PASS, and a
    # person an exclusion Apollo cannot express turns away still cost a credit —
    # so the two are not the same number, and only this one is a bill.
    budget = target if budget is None else max(0, int(budget or 0))
    per_page = max(1, min(int(per_page or 100), 100))
    max_pages = max(1, int(max_pages or 1))

    industries = [i for i in spec.industries.include if _text(i)] or [""]
    searches = [{"industry": ind, "body": params_for(spec, ind), "page": 0, "done": False}
                for ind in industries]
    seen = identity.SeenIndex()          # everyone taken or queued in THIS run
    leads: list = []
    queue: list = []
    turn = 0

    def needed() -> int:
        return max(0, target - len(leads))

    def room() -> int:
        """Credits left in the budget — the hard stop, since a filtered person
        is paid for and still leaves `needed()` where it was."""
        return max(0, budget - counts["revealed"])

    def page() -> bool:
        """One free search page, round-robin across the industries. False when
        there is nothing left to ask for."""
        nonlocal turn
        live = [s for s in searches if not s["done"]]
        if not live or counts["search_calls"] >= max_pages:
            return False
        search = live[turn % len(live)]
        turn += 1
        search["page"] += 1
        counts["search_calls"] += 1
        try:
            data = send(SEARCH, dict(search["body"], page=search["page"],
                                     per_page=per_page))
        except _Unreachable:
            counts["errors"] += 1
            # Nothing to show yet: the owner must be told, not handed an empty
            # list. Mid-run, the list we already have is worth keeping.
            if not (leads or queue or counts["searched"]):
                raise
            for other in searches:
                other["done"] = True
            return False
        rows = data.get("people") if isinstance(data, dict) else None
        rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        for row in rows:
            counts["searched"] += 1
            card = _card(row, search["industry"])
            stub = _stub(card)
            if skip is not None and stub in skip:
                counts["skipped_seen"] += 1
                continue
            if stub in seen:
                counts["duplicates"] += 1
                continue
            seen.add(stub)
            queue.append(card)
        total = _int(data.get("total_entries")) or 0
        if (len(rows) < per_page or search["page"] >= _APOLLO_PAGES
                or (total and search["page"] * per_page >= total)):
            search["done"] = True
        if on_progress:
            on_progress("search", counts["search_calls"], max_pages, len(leads))
        return True

    def reveal_batch(batch: list) -> None:
        counts["reveal_calls"] += 1
        data = send(BULK_MATCH, {"details": [_details(c) for c in batch]})
        matches = data.get("matches") if isinstance(data, dict) else None
        matches = matches if isinstance(matches, list) else []
        for card, person in zip(batch, matches):
            if not isinstance(person, dict) or not person:
                continue                        # nobody found — and no credit
            counts["revealed"] += 1             # a credit, spent
            lead = _lead_of(person, card["industry"])
            if lead is None:
                continue
            reason = filters.match_person(spec, lead)
            if not reason:
                reason = filters.match_company(spec, lead, _facts_of(lead, person))
            if reason:
                counts["filtered"][reason] = counts["filtered"].get(reason, 0) + 1
                continue
            leads.append(lead)
            if len(leads) >= target:
                break

    if not reveal:
        # The Apollo way (the owner, 25-Nov-2026): search only. Up to `target` free cards come back as preview
        # rows; nobody is revealed and nothing is charged — the owner ticks who is worth a full name (reveal_leads).
        while len(queue) < target and page():
            pass
        counts["short_by"] = max(0, target - len(queue))
        return [_preview_of(c) for c in queue[:target]]

    while needed() and room():
        # Never queue more cards than the budget can still pay to reveal —
        # paging past that is free, but it is search calls (and minutes) spent
        # on people this run can no longer afford to look at.
        want = min(needed(), room())
        while len(queue) < want and page():
            pass
        if not queue:
            break
        batch = queue[:min(_BATCH, want)]
        del queue[:len(batch)]
        try:
            reveal_batch(batch)
        except _Unreachable:
            counts["errors"] += 1
            break
        if on_progress:
            # Against the budget, because that is the number being spent down.
            on_progress("reveal", counts["revealed"], budget, len(leads))
    counts["short_by"] = needed()
    return leads


def _details_of(lead) -> dict:
    """One bulk_match entry for a preview row: its Apollo id first (the surest match), then what else it holds.
    The surname's initial is never sent: Apollo would match somebody else."""
    x = lead.extra or {}
    detail = {"id": x.get("apollo_id") or "", "linkedin_url": x.get("linkedin") or "",
              "first_name": (lead.name or "").split(" ")[0], "domain": x.get("company_domain") or ""}
    detail = {k: v for k, v in detail.items() if v}
    if lead.company and "domain" not in detail:
        detail["organization_name"] = lead.company
    return detail


def reveal_leads(leads, api_key, *, transport=None, on_progress=None) -> dict:
    """Reveal the preview rows the owner ticked: each becomes the person Apollo knows — full name, e-mail when
    Apollo has one, LinkedIn, the company's website — in place, so the row the owner picked is the row that fills
    in. One credit (or the pool's price) for each person Apollo finds; a person it does not find costs nothing and
    stays a preview. {"asked", "found", "missing"}; `found` is what was charged.

    Raises ApolloError when the very first call is refused (a key, a plan, an empty wallet): nothing was bought,
    and the owner must be told why. Once some are revealed, a refusal ends the run keeping them."""
    key = (api_key or "").strip()
    if not key and transport is None:
        raise ApolloError(NO_KEY)
    send = transport or (lambda path, body: _post(path, body, key))
    todo = [l for l in leads if is_preview(l) and (l.extra or {}).get("apollo_id")]
    out = {"asked": len(todo), "found": 0, "missing": 0}
    for start in range(0, len(todo), _BATCH):
        batch = todo[start:start + _BATCH]
        try:
            data = send(BULK_MATCH, {"details": [_details_of(l) for l in batch]})
        except ApolloError:
            if out["found"]:
                out["stopped"] = True                   # keep what was bought; say the rest was not
                break
            raise
        matches = data.get("matches") if isinstance(data, dict) else None
        matches = matches if isinstance(matches, list) else []
        for lead, person in zip(batch, list(matches) + [None] * (len(batch) - len(matches))):
            full = _lead_of(person, lead.industry) if isinstance(person, dict) and person else None
            if full is None:
                out["missing"] += 1
                continue
            out["found"] += 1
            lead.name, lead.title = full.name, full.title or lead.title
            lead.company = full.company or lead.company
            if full.email:
                lead.email = full.email
            if full.industry and not lead.industry:
                lead.industry = full.industry
            lead.extra.update({k: v for k, v in full.extra.items() if v not in (None, "")})
            lead.extra.pop(PREVIEW, None)
        if on_progress:
            on_progress(min(start + _BATCH, len(todo)), len(todo))
    return out


# ── the verify waterfall's finder ─────────────────────────────────────────────

def find_email(lead, api_key, *, transport=None) -> tuple:
    """Apollo's `people/match` for ONE lead — the profile link or the Apollo id
    when the lead carries one (the surest match), else the name with the company
    domain or name. Returns (email, "valid" | "unknown"), and ("", "") when
    Apollo knows nobody, has no address, or refuses this one person. A refusal
    of the KEY itself — 401, or 403: a Free plan (people/match is not in it) or
    a key scoped to other endpoints — is raised instead: every other person
    would get the same answer, so verify stops asking Apollo for the batch and
    says why (verify.FinderRefused) rather than end the run.

    One credit, and only when Apollo finds the person — which is why verify
    calls it for the hot/warm slice alone."""
    key = (api_key or "").strip()
    if not key and transport is None:
        return "", ""
    send = transport or (lambda path, body: _post(path, body, key))
    extra = getattr(lead, "extra", None) or {}
    # Apollo already sold us this one. people/match, asked by the id the reveal
    # left behind, would find the same person and return the same address for a
    # second credit — so there is nothing to buy. An address enrich GUESSED from
    # a pattern carries no source, and is exactly what this finder is for.
    if extra.get("email_source") == "apollo" and _text(getattr(lead, "email", "")):
        return "", ""
    name = _text(getattr(lead, "name", ""))
    domain = _text(extra.get("company_domain"))
    company = _text(getattr(lead, "company", ""))
    body: dict = {}
    for slot, value in (("id", _text(extra.get("apollo_id"))),
                        ("linkedin_url", _text(extra.get("linkedin")))):
        if value:
            body[slot] = value
    if name:
        body["name"] = name
    if domain:
        body["domain"] = domain
    elif company:
        body["organization_name"] = company
    # An id or a profile link identifies the person on its own; a name does not
    # without somewhere to look for them.
    if not (body.get("id") or body.get("linkedin_url")
            or (name and (domain or company))):
        return "", ""
    try:
        data = send(MATCH, body)
    except ApolloError as exc:
        if exc.code in (401, 403) or transport is not None:
            raise                   # a key, or a Monid wallet, refused: every other person would be too
        return "", ""
    person = data.get("person") if isinstance(data, dict) else None
    if not isinstance(person, dict):
        return "", ""
    email = _email_of(person)
    if not email:
        return "", ""
    link = _text(person.get("linkedin_url"))
    if link and not extra.get("linkedin") and isinstance(getattr(lead, "extra", None), dict):
        lead.extra["linkedin"] = link
    return email, _check_of(person)


# ── the same two calls, through the owner's Monid wallet ──────────────────────

MONID_SEARCH_COST = 0.01        # Monid's ceiling on a search: it is listed at $0
MONID_MATCH_COST = 0.05         # ... and on a person match: listed at $0.026
_MONID_WORKERS = 4              # people revealed at once (Monid has no bulk match)


def _monid_query(body: dict) -> dict:
    """Apollo's JSON search body as Monid's query string takes it: a list is written `key[]`, which is
    how Apollo's own people-search parameters are named (`person_titles[]`, `revenue_range[min]` already
    carry theirs)."""
    query = {}
    for name, value in (body or {}).items():
        if isinstance(value, (list, tuple)):
            query[name if name.endswith("]") else name + "[]"] = list(value)
        elif value is not None:
            query[name] = value
    return query


def monid_transport(key: str, *, call=None):
    """`transport` for search_people, asked through Monid instead of api.apollo.io with an Apollo key.

    SEARCH is `apollo /mixed_people/api_search`, $0: the same cards, last name obfuscated, no e-mail.
    BULK_MATCH has no Monid twin, so it is one `apollo /people/match` per person (about $0.026 each,
    charged when Apollo attaches the name to a company) answered in the shape bulk_match has — one entry
    per person asked, {} for nobody — which is why `search_people` needs no other change. A key or wallet
    Monid refuses is an ApolloError in Monid's own words; a call that did not land is `_Unreachable`.

    Reveals are PAID, so a refusal part-way through them (the wallet ran dry) must not throw away the ones already
    bought (PR #18 review, 25-Nov-2026): the batch comes back with what was revealed, and every later call raises
    `_Unreachable` with Monid's words, which ends the run keeping its list."""
    call = call or monid_run.call
    dry: list = []                                      # Monid's refusal, once a reveal has met one

    def one(detail) -> dict:
        query = {k: v for k, v in (detail or {}).items() if v}
        if not query:
            return {}                                   # nothing identifies them: nobody to ask for
        try:
            run = call("apollo", "/people/match", key=key, query=query, max_cost=MONID_MATCH_COST)
        except monid_run.MonidError as exc:
            dry.append(str(exc))
            return {}
        out = run.get("output") if isinstance(run, dict) else None
        person = out.get("person") if isinstance(out, dict) else None
        return person if isinstance(person, dict) else {}

    def send(path: str, body: dict) -> dict:
        if dry:
            raise _Unreachable(dry[0])
        try:
            if path == SEARCH:
                run = call("apollo", "/mixed_people/api_search", key=key,
                           query=_monid_query(body), max_cost=MONID_SEARCH_COST)
                if run is None:
                    raise _Unreachable(UNREACHABLE)
                out = run.get("output")
                return out if isinstance(out, dict) else {}
            if path == BULK_MATCH:
                details = [d for d in (body.get("details") or []) if isinstance(d, dict)]
                with ThreadPoolExecutor(max_workers=_MONID_WORKERS) as pool:
                    matches = list(pool.map(one, details))
                if dry and not any(matches):
                    raise ApolloError(dry[0])           # nothing bought in this batch: say why, now
                return {"matches": matches}
            if path == MATCH:
                person = one(body)
                if dry and not person:
                    raise ApolloError(dry[0])
                return {"person": person}
        except monid_run.MonidError as exc:
            raise ApolloError(str(exc)) from exc
        raise ApolloError(REFUSED.format(code=0, path=path))

    return send


def pool_transport():
    """`transport` for search_people on the CREDIT POOL: the same two calls, made by the licence server
    through Prism's own Monid account (prospector.gateway.apollo_search / apollo_reveal). Search takes no
    credit; a reveal costs the server's `apollo_reveal` price per person Apollo finds. A refusal is
    `_Unreachable` in the server's own words: before anything was found the run says why, and once it has
    people, a pool that runs dry ends the run with the list it has instead of throwing it away."""
    from . import gateway

    def send(path: str, body: dict) -> dict:
        try:
            if path == SEARCH:
                return gateway.apollo_search(body)
            if path == BULK_MATCH:
                details = [d for d in (body.get("details") or []) if isinstance(d, dict)]
                return {"matches": gateway.apollo_reveal(details)}
        except gateway.GatewayError as exc:
            raise _Unreachable(exc.message) from exc
        raise ApolloError(REFUSED.format(code=0, path=path))
    return send
