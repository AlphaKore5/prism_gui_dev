"""
Prism Prospector — find my buyers
─────────────────────────────────
The filters in Leads & Outreach answer "who looks like a customer". This answers
the other question: "who is acting like one, and what is the proof".

    describe what you sell          →  read_offer()     buyer types, in the buyer's words
    pick the buyer types + channels →  plan_queries()   searches, one per type per channel
    run them                        →  hunt()           evidence cards, scored, closed ones dropped

Four channels, because the first prototype (22-Nov-2026) showed which ones carry
real demand:

  tender   an open public bid for what you sell — the strongest signal there is,
           and the one that expires: a closing date is READ off the page, and a
           bid already closed is dropped, never shown as a lead.
  hiring   the company is hiring for the job that uses what you sell.
  news     a new plant, funding, an expansion — a reason to call, not a request.
  asking   someone posted that they need it. Rare for niche B2B; kept, never leaned on.

The rules this module keeps, because the whole value is that the list is honest:

  · No evidence, no card. A row with no address or no text is dropped.
  · Every card says WHICH kind it is: "declared" (the buyer asked, or invited
    bids) or "inferred" (we think so, from what they did).
  · A vendor's own page, a directory or a competitor is not a buyer. The model is
    asked to say so; without a model, the rules keep a known-bad host list.
  · Without a model nothing is invented: cards are scored by plain rules and say
    so (`scored_by == "rule"`).

Qt-free. The two outside calls are passed in: `search(query) -> rows | None` and
`ask(prompt, purpose, json_mode, temperature) -> text`. `make_search` and
`make_ask` build them from the user's config, pooled (licence server) or direct.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

LIST, TENDER, HIRING, NEWS, FUNDING, ASKING = "list", "tender", "hiring", "news", "funding", "asking"
CHANNELS = (LIST, TENDER, HIRING, NEWS, FUNDING, ASKING)
DECLARED, INFERRED = "declared", "inferred"
KIND_OF = {LIST: INFERRED, TENDER: DECLARED, ASKING: DECLARED, HIRING: INFERRED, NEWS: INFERRED, FUNDING: INFERRED}
# What a hunt searches unless the owner changes it. LIST comes first: companies that FIT the customer, found in a
# company index and gated on size and place before any signal is searched (22-Nov-2026: signal-first searches of
# the open web found news about companies that were never customers). News, funding, tenders and "asked online"
# are opt-in. Hiring as a web search was on by default for a few hours and found office managers at Regeneron: the list
# already looks for a recent sign (hires included) on each company that fits.
DEFAULT_CHANNELS = (LIST,)
LIST_COMPANIES = 12             # companies a full hunt reads past the size and place gate
LIST_PREVIEW = 6                # ... and a quick preview
LIST_SIGNALS = 10               # companies a full hunt looks for a recent signal on
LIST_SIGNALS_PREVIEW = 4

# Card status. "open" and "closed" are tender-only (a closing date was read).
OPEN, CLOSED, RECENT, OLD, UNKNOWN = "open", "closed", "recent", "old", "unknown"

NEW, ACCEPTED, SKIPPED, NOT_A_FIT = "new", "accepted", "skipped", "not_fit"
DECISIONS = (NEW, ACCEPTED, SKIPPED, NOT_A_FIT)

MAX_TYPES = 6
PREVIEW_ROWS = 5
FULL_ROWS = 8
SCORE_CAP = 48                  # cards the model is asked to read in one hunt: fewer, so a free key's minute is enough
WEAK_BELOW = 40                 # a card scoring under this is a weak match: counted, hidden until asked
SCORE_BATCH = 12                # cards to a model call: fewer calls, so fewer rate-limit waits
SCORE_PAUSE = 2.0               # seconds between model calls: a free Groq key allows only so many tokens a minute
CARD_TEXT = 260                 # characters of a page the model reads per card

# Hosts that are never a buyer: social feeds, directories, aggregators of
# company data. (Tender portals and job boards are NOT here — they are evidence.)
_NOT_BUYERS = ("exa.ai", "linkedin.com/company", "facebook.com", "youtube.com", "instagram.com",
               "crunchbase.com", "zoominfo.com", "indiamart.com", "justdial.com",
               "tradeindia.com", "glassdoor.com", "tofler.in", "zaubacorp.com",
               "quora.com", "wikipedia.org", "alibaba.com", "made-in-china.com")


class BuyersError(Exception):
    """A sentence for the owner, not a stack trace."""


# ── the shapes ────────────────────────────────────────────────────────────────

@dataclass
class BuyerType:
    key: str
    name: str
    why: str = ""
    who_decides: list = field(default_factory=list)
    needs: list = field(default_factory=list)        # what THEY call the problem
    hiring_roles: list = field(default_factory=list)
    triggers: list = field(default_factory=list)     # events that mean "buying soon"
    exclude: list = field(default_factory=list)
    enabled: bool = True


@dataclass
class Offer:
    text: str
    website: str = ""
    regions: str = ""
    competitors: str = ""          # kinds of organisation that SELL the same thing (read from the offer): never buyers
    channels: tuple = ()           # the sources that fit THIS seller, as read from the offer
    ideal: str = ""                # one line: who exactly buys it (size, country, kind of business), as read from the offer
    company_kinds: tuple = ()      # what the buying companies DO, as a company directory would say it: the list searches
    max_staff: int = 0             # the largest headcount that still fits; 0 = size does not matter / not known

    def domain(self) -> str:
        return host_of(self.website)


@dataclass
class Query:
    channel: str
    type_key: str
    text: str
    num: int = FULL_ROWS
    days: int = 0                  # 0 = no date window (tenders: the closing date decides)
    category: str = ""
    source: str = "exa"            # "exa", or one of monid_sources.SOURCES
    location: str = ""             # a city or state, for the sources that take one (Indeed)


@dataclass
class Hit:
    id: str
    channel: str
    kind: str
    who: str
    title: str
    snippet: str
    url: str
    source: str = ""
    published: str = ""
    closes: str = ""               # ISO date a tender closes; "" when none was read
    status: str = UNKNOWN
    fit: int = 0
    intent: int = 0
    why: str = ""
    buyer_type: str = ""           # BuyerType.key
    scored_by: str = "rule"        # "model" | "rule"
    decision: str = NEW
    reason: str = ""

    @property
    def score(self) -> int:
        return round(0.45 * self.fit + 0.55 * self.intent)

    @property
    def weak(self) -> bool:
        """A match too thin to lead with: scored under WEAK_BELOW. Closed bids are not "weak", they are closed."""
        return self.status != CLOSED and self.score < WEAK_BELOW

    @property
    def checked(self) -> bool:
        """The model read this card. A card scored only by plain rules is a guess about a page nobody read."""
        return self.scored_by == "model"


@dataclass
class HuntResult:
    hits: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)       # honest sentences for the owner

    def to_dict(self) -> dict:
        return {"hits": [asdict(h) for h in self.hits], "stats": dict(self.stats),
                "notes": list(self.notes)}


def hit_from_dict(d) -> "Hit | None":
    """Read one stored card back; None when it is not a card."""
    if not isinstance(d, dict) or not d.get("id") or not d.get("url"):
        return None
    known = {k: d[k] for k in Hit.__dataclass_fields__ if k in d}
    try:
        h = Hit(**known)
    except TypeError:
        return None
    h.decision = h.decision if h.decision in DECISIONS else NEW
    for key in ("fit", "intent"):
        try:
            setattr(h, key, max(0, min(100, int(getattr(h, key)))))
        except (TypeError, ValueError):
            setattr(h, key, 0)
    return h


# ── small helpers ─────────────────────────────────────────────────────────────

def host_of(url: str) -> str:
    try:
        raw = (url or "").strip()
        if raw and "//" not in raw:
            raw = "//" + raw
        return urlparse(raw).netloc.lower().replace("www.", "")
    except Exception:                                   # noqa: BLE001
        return ""


def _strings(value, limit: int = 6, width: int = 80) -> list:
    if isinstance(value, str):
        value = [value]
    out = []
    for item in value if isinstance(value, (list, tuple)) else []:
        s = " ".join(str(item or "").split())[:width]
        if s and s.casefold() not in {o.casefold() for o in out}:
            out.append(s)
    return out[:limit]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").casefold()).strip("-")[:40] or "type"


def hit_id(url: str) -> str:
    """Same page, same card — however the address was written."""
    u = (url or "").strip().lower()
    u = re.sub(r"^https?://(www\.)?", "", u).split("#")[0].rstrip("/")
    return hashlib.sha1(u.encode("utf-8")).hexdigest()[:14]


def parse_json(text: str):
    """The JSON a model wrapped in prose or code fences; None when there is none."""
    s = (text or "").strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s, flags=re.I)
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = s.find(opener), s.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(s[a:b + 1])
            except ValueError:
                continue
    return None


# ── closing dates ─────────────────────────────────────────────────────────────

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_DATES = (
    (re.compile(r"(?<!\d)(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})(?!\d)"), "dmy"),
    (re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[ \-]([A-Za-z]{3,9})\.?,?[ \-]+(\d{4})(?!\d)"), "dMy"),
    (re.compile(r"\b([A-Za-z]{3,9})\.? (\d{1,2})(?:st|nd|rd|th)?,? (\d{4})(?!\d)"), "Mdy"),
)
# A date is a CLOSING date when a word like these sits just before it. "Start",
# "published" and "opening" never count.
_CLOSER = re.compile(r"(clos(?:e|es|ed|ing)|end\b|due\b|last date|deadline|submit by|submission by|until)", re.I)
_NOT_CLOSER = re.compile(r"(start|publish|opening|issued|download start|begin)", re.I)


def _make_date(kind: str, a: str, b: str, c: str):
    try:
        if kind == "dmy":
            return date(int(c), int(b), int(a))
        if kind == "ymd":
            return date(int(a), int(b), int(c))
        if kind == "dMy":
            m = _MONTHS.get(b[:3].casefold())
            return date(int(c), m, int(a)) if m else None
        m = _MONTHS.get(a[:3].casefold())
        return date(int(c), m, int(b)) if m else None
    except (ValueError, TypeError):
        return None


def dates_in(text: str) -> list:
    """[(start, end, date)] of every full date in `text`, in reading order."""
    found = []
    for pattern, kind in _DATES:
        for m in pattern.finditer(text or ""):
            d = _make_date(kind, *m.groups())
            if d is not None and 2000 <= d.year <= 2100:
                found.append((m.start(), m.end(), d))
    found.sort()
    out, last_end = [], -1
    for s, e, d in found:                       # one date, one hit, even when two patterns saw it
        if s >= last_end:
            out.append((s, e, d))
            last_end = e
    return out


def closing_date(text: str):
    """The date a bid CLOSES, read off a tender page — the latest date that a
    closing word ("closing", "due", "end date", "last date") labels; None when
    the page names none. "Clarification due 24-11, submission due 01-12" is
    closing on 01-12."""
    text = text or ""
    best = None
    prev_end = 0
    for s, e, d in dates_in(text):
        label = text[max(prev_end, s - 48):s]
        prev_end = e
        if _CLOSER.search(label) and not _NOT_CLOSER.search(label[-24:]):
            best = d if best is None or d > best else best
    return best


# ── reading the offer ─────────────────────────────────────────────────────────

@dataclass
class Reading:
    """What the model made of an offer."""
    summary: str
    types: list
    competitors: list = field(default_factory=list)      # kinds of organisation that sell the same thing
    channels: tuple = ()                                  # the sources that fit this seller
    ideal: str = ""                                       # who exactly buys it: size, country, kind of business
    company_kinds: tuple = ()                             # what the buying companies do, for the company list
    max_staff: int = 0                                    # the largest headcount that fits; 0 = not known


def offer_prompt(offer: Offer) -> str:
    return (
        "You help a small business find the organisations that would BUY what it sells.\n"
        "A BUYER is an organisation that would USE the product or service for its own business. An organisation that "
        "SELLS the same or a similar thing (an agency, a software company, a reseller, a consultancy) is a "
        "COMPETITOR and never a buyer, even if it advertises, posts job ads or says it wants clients.\n"
        "Read what it sells, then name the kinds of buyer, in the buyer's own words.\n\n"
        f"WHAT IT SELLS:\n{offer.text.strip()[:2000]}\n"
        + (f"WEBSITE: {offer.website.strip()[:200]}\n" if offer.website.strip() else "")
        + (f"WHERE IT SELLS: {offer.regions.strip()[:200]}\n" if offer.regions.strip() else "")
        + "\nReply with JSON only, no prose:\n"
        '{"summary": "<one line: what is sold and to whom>",\n'
        ' "ideal_customer": "<one line: exactly who buys it: size of business, country, what they do, and what they do '
        'by hand today. Say what they are NOT, such as large enterprises, government bodies or consumer brands, when that '
        'is so>",\n'
        ' "company_kinds": ["<2-4 short descriptions of what the BUYING companies do, the way a company directory '
        'would write it, such as \'small industrial equipment manufacturer\'. Companies, not job titles, and never the '
        'seller\'s own kind of business>"],\n'
        ' "max_staff": <the largest headcount (a number) that still fits as a customer, or 0 when size does not matter>,\n'
        ' "competitors": ["<kinds of organisation that SELL the same or a similar thing: never buyers>"],\n'
        ' "channels": ["<which of list, tender, hiring, news, funding, asking fit THIS seller>"],\n'
        ' "buyer_types": [{"name": "<a kind of buyer, 2-5 words>",\n'
        '   "why": "<one line: why this kind of buyer needs it>",\n'
        '   "who_decides": ["<job titles>"],\n'
        '   "needs": ["<2-4 short phrases a buyer would type or write about THEIR OWN problem, such as \'follow up with leads '
        'faster\'. Never the seller\'s product name, and never \'supplier\' or \'vendor\' words>"],\n'
        '   "hiring_roles": ["<jobs a buyer hires for that mean they need this>"],\n'
        '   "triggers": ["<events that mean they are buying soon: new plant, funding, a tender>"],\n'
        '   "exclude": ["<kinds of company to skip: competitors, resellers>"]}]}\n'
        "channels: list (companies that match the customer, found in a company index) fits almost every seller of a "
        "B2B product; tender only when this seller's buyers buy through public tenders; hiring when the buyer hires for the "
        "job that uses the product; news for expansions; funding when fresh money means buying; asking only for "
        "products people discuss online. Pick the ones that fit, usually two or three.\n"
        f"Give 3 to {MAX_TYPES} buyer types. Prefer buyers a small seller can really win. "
        "Never invent customers or numbers."
    )


def read(offer: Offer, ask) -> Reading:
    """The model's reading of an offer: kinds of buyer, the kinds of organisation that SELL the same thing (never
    buyers) and the sources that fit. BuyersError, in plain words, when the model is unreachable or answers with
    nothing usable."""
    if not (offer.text or "").strip():
        raise BuyersError("Describe what you sell first.")
    try:
        raw = ask(offer_prompt(offer), "qualify", True, 0.3)
    except Exception as e:                              # noqa: BLE001
        raise BuyersError(f"Couldn't reach the model to read your offer: {e}") from e
    data = parse_json(raw)
    items = data.get("buyer_types") if isinstance(data, dict) else None
    types, seen = [], set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())[:60]
        if not name or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        types.append(BuyerType(
            key=_slug(name), name=name, why=" ".join(str(item.get("why") or "").split())[:200],
            who_decides=_strings(item.get("who_decides")), needs=_strings(item.get("needs"), 4, 100),
            hiring_roles=_strings(item.get("hiring_roles"), 4), triggers=_strings(item.get("triggers"), 4, 100),
            exclude=_strings(item.get("exclude"))))
    if not types:
        raise BuyersError("The model didn't name any buyer types. Describe what you sell in a "
                          "little more detail and try again.")
    d = data if isinstance(data, dict) else {}
    summary = " ".join(str(d.get("summary") or "").split())[:240]
    wanted = {str(c).strip().casefold() for c in (d.get("channels") if isinstance(d.get("channels"), list) else [])}
    channels = tuple(c for c in CHANNELS if c in wanted)
    ideal = " ".join(str(d.get("ideal_customer") or "").split())[:300]
    try:
        max_staff = max(0, min(int(d.get("max_staff") or 0), 1_000_000))
    except (TypeError, ValueError):
        max_staff = 0
    return Reading(summary, types[:MAX_TYPES], _strings(d.get("competitors"), 6, 120), channels, ideal,
                   tuple(_strings(d.get("company_kinds"), 4, 120)), max_staff)


def read_offer(offer: Offer, ask) -> tuple:
    """(summary, [BuyerType]) — read() without the competitors and the channels."""
    r = read(offer, ask)
    return r.summary, r.types


# ── the searches ──────────────────────────────────────────────────────────────

def _where(offer: Offer) -> str:
    return (offer.regions or "").strip()[:80] or "India"


def _location(offer: Offer) -> str:
    """The first place the owner named that is not just the country: "Gujarat, India" is "Gujarat"."""
    for part in re.split(r"[,/;]", offer.regions or ""):
        p = part.strip()
        if p and p.casefold() not in ("india", "bharat", "in"):
            return p[:60]
    return ""


def plan_queries(offer: Offer, types: list, channels, *, preview: bool = False, monid: bool = False) -> list:
    """One search per enabled buyer type per channel (two for "asked online" on Monid: Reddit and Hacker News).
    A preview is the cheap first look: the first two types, fewer rows, at most four searches.

    `monid` says Monid's sources are available. With it, hiring is Indeed jobs, news and funding are Google News,
    and "asked online" is Reddit and Hacker News: sources that return the company, the date and the text.
    Without it every channel is an Exa search, as before. Tenders are always Exa: Monid has no Indian tenders."""
    wanted = [c for c in CHANNELS if c in set(channels or ())]
    live = [t for t in types if t.enabled]
    if preview:
        live = live[:2]
    num = PREVIEW_ROWS if preview else FULL_ROWS
    where = _where(offer)
    loc = _location(offer)
    out = []
    if LIST in wanted:
        # No fallback to a buyer type's name: "Founder / Owner" as a company search finds nothing worth reading (22-Nov-2026).
        kinds = [k for k in (offer.company_kinds or ()) if str(k).strip()]
        for kind in kinds[:2 if preview else 4]:
            out.append(Query(LIST, "", f"{kind}", LIST_PREVIEW if preview else LIST_COMPANIES, 0, source="company"))
    for t in live:
        need = (t.needs or [t.name])[0]
        for ch in wanted:
            if ch == LIST:
                continue                                   # planned above, from the company kinds
            if ch == TENDER:
                text = (f"open tender or request for quotation inviting bids for {need}, "
                        f"{where}, bid submission closing date")
                out.append(Query(ch, t.key, text, num, 0))
            elif ch == HIRING:
                role = (t.hiring_roles or t.who_decides or [t.name])[0]
                if monid:
                    out.append(Query(ch, t.key, role, num, 30, source="indeed", location=loc))
                else:
                    out.append(Query(ch, t.key, f"job opening for {role} at a {t.name} in {where}", num, 120))
            elif ch == NEWS:
                trig = (t.triggers or ["expansion"])[0]
                if monid:
                    out.append(Query(ch, t.key, f"{t.name} {trig} {loc}".strip(), num, 0, source="gnews", location=loc))
                else:
                    out.append(Query(ch, t.key, f"{t.name} in {where} announces {trig}", num, 180))
            elif ch == FUNDING:
                if monid:
                    out.append(Query(ch, t.key, f"{t.name} raises funding {loc}".strip(), num, 0, source="gnews", location=loc))
                else:
                    out.append(Query(ch, t.key, f"{t.name} in {where} raises a funding round", num, 180))
            elif ch == ASKING:
                if monid:
                    out.append(Query(ch, t.key, f"how do I {need}", num, 0, source="reddit"))
                    out.append(Query(ch, t.key, need, num, 0, source="hn"))
                else:
                    # A buyer's own words about the problem. "Supplier" or "vendor" finds the SELLERS.
                    out.append(Query(ch, t.key, f"how do small businesses {need}? what tool do you use, {where}", num, 365))
    return out[:4] if preview and LIST not in wanted else out[:6] if preview else out


def estimate(offer: Offer, types: list, channels, *, preview: bool = False, monid: bool = False) -> dict:
    """What a hunt will ask for, before it runs: {"searches", "model_calls"}.
    The model reads at most SCORE_CAP cards, SCORE_BATCH to a call."""
    q = plan_queries(offer, types, channels, preview=preview, monid=monid)
    web = [x for x in q if x.channel != LIST]
    cards = min(SCORE_CAP, sum(x.num for x in web))
    # one more call checks the searches against what the owner wants, before any search is paid for
    calls = (-(-cards // SCORE_BATCH) + 1) if q else 0
    searches = len(q)
    if len(web) != len(q):                      # the company list: its searches, a signal lookup per company, two reads
        searches += LIST_SIGNALS_PREVIEW if preview else LIST_SIGNALS
        calls += 2
    return {"searches": searches, "model_calls": calls}


# ── the intent check ──────────────────────────────────────────────────────────

CHECK_NOTES = 6                 # dropped searches named to the owner, one sentence each


def check_prompt(offer: Offer, summary: str, types: dict, queries: list, learned: str = "") -> str:
    rows = [{"n": i, "source": q.channel, "buyer_type": types.get(q.type_key, q.type_key), "search": q.text}
            for i, q in enumerate(queries)]
    return (
        "A seller wants to find buyers on the web. Before any search is paid for, check each planned search: would the "
        "pages it returns show organisations that match the seller's customer AND have the need?\n\n"
        f"WHAT IS SOLD: {(summary or offer.text)[:400]}\n"
        f"THE CUSTOMER: {(offer.ideal or summary or offer.text)[:400]}\n"
        + (f"COMPETITORS (never buyers): {offer.competitors[:300]}\n" if offer.competitors else "")
        + (learned + "\n" if learned else "")
        + f"\nPLANNED SEARCHES:\n{json.dumps(rows, ensure_ascii=False)}\n\n"
        "Reply with JSON only:\n"
        '{"checks": [{"n": 0, "keep": true, "why": "<max 15 words>", "better": "<a sharper search sentence, or empty>"}]}\n'
        "Rules: keep=false when the pages it finds would mostly be organisations the customer line rules out (a large "
        "enterprise, a government body, a consumer brand, another country), or when the signal does not mean the need "
        "(a hire for a job that does not use what is sold; a funding round for a business of the wrong kind). "
        "tender searches only fit a customer that buys through public tenders. "
        "better: only when the search is right in aim but would find the wrong pages. Write it as a person with the "
        "problem would, naming the customer's size and place. Never use 'supplier' or 'vendor'. "
        "One entry per search, using its n."
    )


def check_queries(offer: Offer, summary: str, types: list, queries: list, ask, learned: str = "") -> tuple:
    """Ask the model whether each planned search would find the owner's customer, and drop or sharpen the ones that
    would not. Returns (queries, notes). Fails open: when the model can't be reached or answers nothing usable, every
    search runs as planned, and the owner is told it was not checked."""
    if not queries:
        return queries, []
    names = {t.key: t.name for t in types}
    try:
        raw = ask(check_prompt(offer, summary, names, queries, learned), "qualify", True, 0.1)
        data = parse_json(raw)
    except Exception as e:                              # noqa: BLE001
        return queries, [f"The searches could not be checked against what you want ({e}), so they ran as planned."]
    items = data.get("checks") if isinstance(data, dict) else data
    verdicts = {}
    for r in items if isinstance(items, list) else []:
        try:
            verdicts[int(r.get("n"))] = r
        except (AttributeError, TypeError, ValueError):
            continue
    if not verdicts:
        return queries, ["The searches could not be checked against what you want, so they ran as planned."]
    kept, notes = [], []
    for i, q in enumerate(queries):
        r = verdicts.get(i)
        if r is None or r.get("keep") is not False:
            better = " ".join(str(r.get("better") or "").split())[:200] if r else ""
            if better and q.source == "exa" and not re.search(r"supplier|vendor", better, re.I):
                q = replace(q, text=better)
            kept.append(q)
            continue
        if len(notes) < CHECK_NOTES:
            why = " ".join(str(r.get("why") or "").split())[:160].rstrip(".")
            notes.append(f"Skipped the {q.channel} search for {q.text if q.channel == LIST else names.get(q.type_key, q.type_key)}"
                         + (f": {why}." if why else "."))
    gone = len(queries) - len(kept)
    if gone > CHECK_NOTES:
        notes.append(f"{gone - CHECK_NOTES} more searches were skipped for the same reason.")
    return kept, notes


# ── turning rows into cards ───────────────────────────────────────────────────

def _row_text(row: dict) -> str:
    hi = row.get("highlights") or []
    text = " … ".join(str(h) for h in hi) if hi else ""
    return " ".join((text or str(row.get("text") or "")).split())


def _published(row: dict) -> str:
    return str(row.get("publishedDate") or row.get("published") or "")[:10]


def _age_days(iso: str, today: date):
    try:
        return (today - date.fromisoformat(iso)).days
    except ValueError:
        return None


def blocked(url: str, own_domain: str = "") -> bool:
    """An address that is never a buyer: a search engine's own listing, a social feed, a company directory, or the
    seller's own site. The one rule a new card and a card read back from an old hunt both go through, so a page we
    learn to ignore stays ignored in the hunts already saved."""
    low = (url or "").lower()
    if any(b in low for b in _NOT_BUYERS):
        return True
    host = host_of(url)
    return bool(own_domain and (host == own_domain or host.endswith("." + own_domain)))


def _squash(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").casefold()).strip()


def echoes_query(q_text: str, *parts: str) -> bool:
    """A page that merely repeats the sentence we searched for, give or take a small word. A search engine's own result
    page does this: Exa's library/places listing of WhatsApp agencies was titled "looking for a supplier vendor for run
    WhatsApp broadcast campaigns, recommendations please, India", our query with "or" missing. A real post, job or news
    story does not carry nine of our search words in our order within its first line or two.

    The test: the query's longer words (4+ letters, at least five of them) all appear, in the query's order, within the
    first 400 characters of a part."""
    words = [w for w in _squash(q_text).split() if len(w) >= 4]
    if len(words) < 5:
        return False
    for part in parts:
        lead = iter(_squash(part)[:400].split())
        if all(w in lead for w in words):                    # `in` on an iterator consumes it: an in-order match
            return True
    return False


def make_hit(row: dict, q: Query, today: date, *, own_domain: str = "") -> "Hit | None":
    """One search row as a card — or None when it cannot stand as evidence."""
    if not isinstance(row, dict):
        return None
    url = str(row.get("url") or "").strip()
    snippet = _row_text(row)
    title = " ".join(str(row.get("title") or "").split())[:200]
    if not url or not snippet:                          # a title alone is not evidence: no quote, no card
        return None
    host = host_of(url)
    # A tender page is judged by its closing date, and may well quote words from our query; the others may not echo it.
    if blocked(url, own_domain) or (q.channel != TENDER and echoes_query(q.text, title, snippet)):
        return None
    published = _published(row)
    closes, status = "", UNKNOWN
    if q.channel == TENDER:
        d = closing_date(" ".join((title, snippet, str(row.get("text") or ""))))
        if d is not None:
            closes = d.isoformat()
            status = OPEN if d >= today else CLOSED
    else:
        age = _age_days(published, today)
        status = UNKNOWN if age is None else (RECENT if age <= 200 else OLD)
    # Monid's rows say who (the company hiring) and where from ("Indeed", "r/smallbusiness"); an Exa row does not.
    who = " ".join(str(row.get("who") or "").split())[:120] or title or host
    source = " ".join(str(row.get("source_name") or "").split())[:60] or host
    return Hit(id=hit_id(url), channel=q.channel, kind=KIND_OF[q.channel], who=who,
               title=title, snippet=snippet[:600], url=url, source=source, published=published,
               closes=closes, status=status, buyer_type=q.type_key)


_RULE_INTENT = {LIST: 20, TENDER: 75, ASKING: 60, HIRING: 50, NEWS: 40, FUNDING: 45}


def rule_score(h: Hit) -> Hit:
    """Plain scoring for when no model is available. Deliberately modest: it
    knows the channel and the date, not whether the page is a real buyer."""
    intent = _RULE_INTENT[h.channel]
    if h.channel == TENDER and h.status == OPEN:
        intent = 85
    elif h.channel == TENDER and h.status == UNKNOWN:
        intent = 55
    if h.status == OLD:
        intent -= 20
    h.fit, h.intent, h.scored_by = 50, max(0, intent), "rule"
    h.why = {LIST: "A company that matches the kind of customer you sell to. No signal was read.",
             TENDER: "A public bid page that matched your search.",
             ASKING: "A post that matched what you sell.",
             HIRING: "Hiring for a job that uses what you sell.",
             NEWS: "A recent move that may need what you sell.",
             FUNDING: "Recently funded, so it may be buying."}[h.channel]
    return h


def score_prompt(offer_summary: str, types: dict, hits: list, competitors: str = "", skips: dict | None = None,
                 ideal: str = "", learned: str = "") -> str:
    skips = skips or {}
    rows = []
    for h in hits:
        row = {"id": h.id, "buyer_type": types.get(h.buyer_type, h.buyer_type), "channel": h.channel,
               "title": h.title, "text": h.snippet[:CARD_TEXT], "host": h.source, "date": h.published or h.closes}
        if skips.get(h.buyer_type):
            row["skip_kinds"] = skips[h.buyer_type][:5]
        rows.append(row)
    return (
        "A seller wants buyers. For each web page below, decide if the page shows an "
        "ORGANISATION that would BUY what is sold.\n\n"
        f"WHAT IS SOLD: {offer_summary[:300]}\n"
        + (f"THE CUSTOMER: {ideal[:300]}\n" if ideal else "")
        + (f"COMPETITORS (they SELL the same or a similar thing: NEVER buyers): {competitors[:400]}\n" if competitors else "")
        + (learned + "\n" if learned else "")
        + "\n"
        f"PAGES:\n{json.dumps(rows, ensure_ascii=False)}\n\n"
        "Reply with JSON only:\n"
        '{"results": [{"id": "<id>", "role": "buyer|vendor|directory|other",\n'
        '  "who": "<the organisation that would buy; its name>",\n'
        '  "fit": 0-100, "intent": 0-100, "why": "<max 20 words, using only what the page says>"}]}\n'
        "Rules: a BUYER would USE what is sold for its own business. role=vendor when the page is by, or about, an "
        "organisation that SELLS the same or a similar thing (an agency, a software company, a reseller, a consultancy), "
        "even when it says it wants clients, partners or suppliers, and always when it fits COMPETITORS or the row's "
        "skip_kinds; "
        + ("an organisation that THE CUSTOMER line rules out (too large, a government body, a consumer brand, another "
           "country) is role=other with fit 30 or lower, unless the page itself says it needs what is sold; " if ideal else "")
        + "directory for lists, guides and search listings; other when the page is not about an organisation "
        "that would buy what is sold (say so in why). intent 80+ only when the page itself says the organisation "
        "is asking for, or inviting bids for, what is sold. intent 40-70 for hiring or expansion that "
        "implies a need. A festival greeting, a thank-you or a generic company post is NOT a sign of need: intent 20 "
        "or lower. Anything else 30 or lower. Do not invent facts the page does not state."
    )


def model_score(hits: list, offer_summary: str, types: dict, ask, competitors: str = "", skips: dict | None = None,
                ideal: str = "", learned: str = "") -> tuple:
    """Score `hits` in place with the model. Returns (read, dropped, error): how
    many it scored, how many it ruled out as not-a-buyer, and a sentence when it
    failed (those cards keep their rule score)."""
    read = dropped = 0
    by_id = {h.id: h for h in hits}
    for i in range(0, len(hits), SCORE_BATCH):
        if i and SCORE_PAUSE:
            time.sleep(SCORE_PAUSE)
        batch = hits[i:i + SCORE_BATCH]
        try:
            raw = ask(score_prompt(offer_summary, types, batch, competitors, skips, ideal, learned), "qualify", True, 0.1)
        except Exception as e:                          # noqa: BLE001
            return read, dropped, f"The model could not score every card ({e}); the rest are scored by plain rules."
        data = parse_json(raw)
        results = data.get("results") if isinstance(data, dict) else data
        for r in results if isinstance(results, list) else []:
            h = by_id.get(str(r.get("id") if isinstance(r, dict) else ""))
            if h is None:
                continue
            role = str(r.get("role") or "").casefold()
            try:
                fit, intent = int(r.get("fit")), int(r.get("intent"))
            except (TypeError, ValueError):
                continue
            h.fit, h.intent = max(0, min(100, fit)), max(0, min(100, intent))
            h.why = " ".join(str(r.get("why") or "").split())[:200]
            who = " ".join(str(r.get("who") or "").split())[:120]
            if who:
                h.who = who
            h.scored_by = "model"
            read += 1
            if role != "buyer":                 # vendor, directory or "other": not an organisation that would buy
                h.decision, h.reason = NOT_A_FIT, role or "other"
                dropped += 1
    return read, dropped, ""


# ── the hunt ──────────────────────────────────────────────────────────────────

def hunt(offer: Offer, summary: str, types: list, channels, search, ask=None, *,
         preview: bool = False, today: "date | None" = None, on_progress=None,
         cancelled=None, monid: bool = False, lister=None, memory=None) -> HuntResult:
    """Run the searches and return the cards worth reading, best first.

    `search(query) -> list[dict] | None` — None is a failed search (counted and
    said, never read as "no buyers"). `ask` is optional: without it cards are
    scored by rule and say so. `lister` answers the company list (buyers_list); without it that source is skipped
    and said. `memory` is what the owner already judged (buyers_learn): those companies are not shown or read again,
    and their taste goes to the model."""
    today = today or date.today()
    queries = plan_queries(offer, types, channels, preview=preview, monid=monid)
    stale = LIST in set(channels or ()) and not any(q.channel == LIST for q in queries)
    planned = len(queries)
    res = HuntResult(stats={"searches": planned, "failed": 0, "rows": 0, "closed": 0,
                            "vendors": 0, "duplicates": 0, "skipped": 0})
    if stale:
        res.notes.append("Companies like your customer was skipped: your offer was read before Prism knew what your "
                         "buyers' companies do. Press Find my buyers to read it again, then run this.")
    if not queries:
        if not stale:
            res.notes.append("Nothing to search: pick at least one buyer type and one source.")
        return res
    from . import buyers_learn
    seen_before = buyers_learn.matcher(memory)
    learned = buyers_learn.lessons(memory)
    if ask is not None and (offer.ideal or "").strip():
        queries, check_notes = check_queries(offer, summary, types, queries, ask, learned)
        res.notes.extend(check_notes)
        res.stats["searches"], res.stats["skipped"] = len(queries), planned - len(queries)
        if not queries:
            res.notes.append("Every planned search was skipped, so nothing was searched. Change what you sell, "
                             "the kinds of buyer or the places to look, and try again.")
            return res
    if ask is not None and not (offer.ideal or "").strip():
        res.notes.append("The searches were not checked against your customer: your offer has no customer line yet. "
                         "Press Find my buyers to read it again.")
    list_qs = [q for q in queries if q.channel == LIST]
    queries = [q for q in queries if q.channel != LIST]
    own = offer.domain()
    cards, seen_id, seen_title = [], set(), set()
    for n, q in enumerate(queries, 1):
        if cancelled and cancelled():
            res.notes.append("Stopped before every search ran.")
            break
        if on_progress:
            on_progress(n, len(queries), q)
        rows = search(q)
        if rows is None:
            res.stats["failed"] += 1
            continue
        for row in rows:
            res.stats["rows"] += 1
            h = make_hit(row, q, today, own_domain=own)
            if h is None:
                continue
            judged = seen_before(h)
            if judged:                                   # the owner already decided this one
                res.stats["remembered_" + judged] = res.stats.get("remembered_" + judged, 0) + 1
                continue
            key = (h.source, re.sub(r"\W+", "", h.title.casefold()))
            if h.id in seen_id or key in seen_title:
                res.stats["duplicates"] += 1
                continue
            seen_id.add(h.id)
            seen_title.add(key)
            cards.append(h)
    for why in dict.fromkeys(getattr(search, "errors", None) or ()):     # a wallet or key problem, said once
        res.notes.append(why)
    if res.stats["failed"]:
        res.notes.append(f"{res.stats['failed']} of {len(queries)} searches failed, so this list may be "
                         "missing buyers. Nothing about them was assumed.")
    closed = [h for h in cards if h.status == CLOSED]
    res.stats["closed"] = len(closed)
    live = [h for h in cards if h.status != CLOSED]
    for h in live:
        rule_score(h)
    # The model reads the cards most likely to be real first, capped.
    live.sort(key=lambda h: (-h.intent, h.id))
    if ask is not None and live:
        names = {t.key: t.name for t in types}
        skips = {t.key: t.exclude for t in types}
        read, dropped, err = model_score(live[:SCORE_CAP], summary, names, ask, offer.competitors, skips, offer.ideal, learned)
        res.stats["model_read"], res.stats["vendors"] = read, dropped
        if err:
            res.notes.append(err)
        left = len(live[:SCORE_CAP]) - read
        if left > 0 and not err:
            res.notes.append(f"{left} cards the model did not answer for are scored by plain rules.")
        if len(live) > SCORE_CAP:
            res.notes.append(f"Only the {SCORE_CAP} most promising cards were read by the model.")
    elif live:
        res.notes.append("No model was available, so every card is scored by plain rules. Read the "
                         "evidence on each one before you act.")
    kept = [h for h in live if h.decision != NOT_A_FIT]
    if list_qs:
        kept += _company_list(offer, summary, list_qs, lister, ask, res, preview=preview, on_progress=on_progress,
                              cancelled=cancelled, taken={h.source for h in kept}, base=len(queries),
                              skip=seen_before, learned=learned)
    kept.sort(key=lambda h: (-h.score, h.id))
    out, inp = res.stats.get("remembered_rejected", 0), res.stats.get("remembered_accepted", 0)
    if out or inp:
        res.notes.append(f"Left out {out + inp} you already judged: {out} you put away, {inp} already in People.")
    # Closed bids ride along at the end, flagged, so the owner can see what was dropped and
    # why — they are hidden by default in the page, and never ranked above a live one.
    for h in closed:
        h.fit, h.intent, h.scored_by = 0, 0, "rule"
        h.why = "This bid has already closed."
    res.hits = kept + closed
    res.stats["kept"] = len(kept)
    return res


def _company_list(offer, summary, list_qs, lister, ask, res, *, preview, on_progress, cancelled, taken, base,
                  skip=None, learned="") -> list:
    """The "companies like your customer" source: its cards, with its counts and its honest sentences added to `res`."""
    if lister is None:
        res.notes.append("Companies like your customer needs your own Exa key. It is not available on credits yet, "
                         "so this source was skipped.")
        return []
    from . import buyers_list
    hits, stats, notes = buyers_list.list_first(
        offer, summary, list_qs, lister, ask, preview=preview, on_progress=on_progress, cancelled=cancelled,
        progress_base=base, progress_total=base + len(list_qs) + (LIST_SIGNALS_PREVIEW if preview else LIST_SIGNALS),
        skip=skip, learned=learned)
    res.stats["searches"] -= len(list_qs)            # counted already as planned; list_first counts what it really ran
    for k, v in stats.items():
        res.stats[k] = res.stats.get(k, 0) + v
    res.notes.extend(notes)
    return [h for h in hits if h.source not in taken]


def decide(hits: list, ids, decision: str, reason: str = "") -> int:
    """Set a decision on the cards whose id is in `ids`; how many changed."""
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision {decision!r}")
    ids, n = set(ids or ()), 0
    for h in hits:
        if h.id in ids and (h.decision != decision or h.reason != (reason or "")):
            h.decision, h.reason = decision, reason or ""
            n += 1
    return n


def to_lead(h: Hit):
    """An accepted card as a Lead the People list can hold. It is an
    ORGANISATION, not a person: name is empty, so "Find people" can fill it in
    later, and the evidence travels in `extra`."""
    from .models import Lead
    return Lead(name="", company=h.who or h.title, title="",
                extra={"profile_url": h.url,       # the identity key: one page, one lead
                       "source_url": h.url, "buyer_channel": h.channel, "buyer_kind": h.kind,
                       "buyer_why": h.why, "buyer_evidence": h.snippet[:400],
                       "buyer_closes": h.closes, "website": _own_site(h)})


def _own_site(h: Hit) -> str:
    """The buyer's OWN website, or "" so `verify.find_domains` looks it up. Only a "companies like your customer"
    card carries one: its source is the company's domain. Every other card's source is where the evidence was
    published (a job board, a newspaper, Reddit), and keying later paid lookups — phones, e-mails, people — on
    that domain would buy the publisher's contacts (PR #18 review, 25-Nov-2026)."""
    site = (h.source or "").strip().lower()
    if h.channel != LIST or "." not in site or " " in site or site.endswith("linkedin.com"):
        return ""
    return "https://" + site


def _grade(n: int) -> str:
    """A 0-100 score as the verdict words the qualification card uses."""
    return "pass" if n >= 60 else "warn" if n >= 40 else "fail"


def _day_words(iso: str) -> str:
    try:
        d = date.fromisoformat((iso or "")[:10])
    except ValueError:
        return iso or ""
    return f"{d.day} {d.strftime('%b %Y')}"


def to_dossier(h: Hit, type_name: str = "", today: "date | None" = None):
    """A buyer card as the Dossier the person drawer already draws (addons/leads/evidence.py):
    the HOT / WARM / COLD verdict with its score, the one-line reason, a Qualification card of
    Fit, Need and Timing each with its evidence and source, and the page itself as the "why now".

    Nothing is added that the card does not hold. A card the model never read says so on every
    line instead of passing off a rule's guess as a finding."""
    from .models import COLD, HOT, WARM, Dimension, Dossier, Signal, SIG_FOUND
    today = today or date.today()
    verdict = HOT if h.score >= 70 else WARM if h.score >= 50 else COLD
    read = "Read by the model" if h.checked else "Not read by the model: scored by plain rules"
    unread = "Not read by the model, so not judged."
    dims = [
        Dimension("Fit", _grade(h.fit) if h.checked else "unknown",
                  (f"Scored {h.fit} / 100 for how well this organisation matches what you sell."
                   + (f" Kind of buyer: {type_name}." if type_name else "")) if h.checked else unread,
                  read),
        Dimension("Need", _grade(h.intent) if h.checked else "unknown",
                  h.why if h.checked and h.why else (unread if not h.checked else ""),
                  " · ".join(x for x in (h.source, _day_words(h.published or h.closes)) if x)),
    ]
    if h.channel == TENDER:
        if h.closes:
            gone = h.status == CLOSED
            try:
                soon = 0 <= (date.fromisoformat(h.closes) - today).days <= 5
            except ValueError:
                soon = False
            dims.append(Dimension("Timing", "fail" if gone else "warn" if soon else "pass",
                                  ("This bid closed on " if gone else "The bid closes on ") + _day_words(h.closes) + ".",
                                  h.source))
        else:
            dims.append(Dimension("Timing", "unknown", "No closing date was found on the page.", h.source))
    elif h.published:
        dims.append(Dimension("Timing", {RECENT: "pass", OLD: "warn"}.get(h.status, "unknown"),
                              f"Published {_day_words(h.published)}" + (
                                  ": this may be out of date." if h.status == OLD else "."), h.source))
    else:
        dims.append(Dimension("Timing", "unknown", "The page shows no date.", h.source))
    sig = Signal(title=h.title, snippet=h.snippet, url=h.url, published=h.published, source=h.source)
    return Dossier(lead=to_lead(h), verdict=verdict, score=h.score, dimensions=dims, signals=[sig],
                   summary=h.why if h.checked else "", generated_at="", status="ok",
                   confidence=1.0 if h.checked else 0.0, signal_status=SIG_FOUND)


# ── the outside calls ─────────────────────────────────────────────────────────

EXA_SEARCH_URL = "https://api.exa.ai/search"


def _exa_direct(api_key: str, q: Query, timeout: int = 40):
    import requests                                      # lazy, like the rest of the engine
    body = {"query": q.text, "type": "auto", "numResults": q.num,
            "contents": {"highlights": True, "text": {"maxCharacters": 1500}}}
    if q.days:
        now = datetime.now(timezone.utc)
        body["startPublishedDate"] = (now - timedelta(days=q.days)).strftime("%Y-%m-%dT00:00:00.000Z")
    if q.category:
        body["category"] = q.category
    try:
        resp = requests.post(EXA_SEARCH_URL, json=body, timeout=timeout,
                             headers={"x-api-key": api_key, "Authorization": f"Bearer {api_key}",
                                      "Content-Type": "application/json"})
        if resp.status_code != 200:
            return None
        rows = resp.json().get("results", [])
    except Exception:                                    # noqa: BLE001 — a failed search is a count, not a crash
        return None
    return rows if isinstance(rows, list) else None


def monid_ready(cfg: dict) -> bool:
    """Whether the Monid sources (Indeed, Google News, Reddit, Hacker News) are on for this config: the owner has a
    Monid key AND is on their own keys. On the credit pool the licence server will make these calls and does not yet,
    so the hunt stays on Exa there."""
    from . import gateway, monid_sources
    eff = gateway.effective_cfg(cfg or {})
    return (not gateway.is_pool(eff.get("exa_api_key"))) and monid_sources.available(eff)


def make_search(cfg: dict):
    """The `search` callable for this config, or None when there is no way to search at all.

    A query is answered by its own source: Exa (a key, or the credit pool) for tenders and for the Exa fallbacks,
    Monid (monid_sources, the owner's own key) for Indeed, Google News, Reddit and Hacker News. A Monid problem that
    is the owner's to fix (the wallet is empty, the key was refused) is kept in `search.errors` for the hunt to say,
    and stops the Monid searches that were still to run, instead of asking forty times."""
    from . import gateway, monid_sources, signals
    exa_key = signals.exa_key(cfg)
    monid_key = "" if gateway.is_pool(exa_key) else monid_sources.api_key(cfg)
    if not (exa_key or monid_key):
        return None
    exa = None
    if exa_key:
        exa = (lambda q: gateway.hunt_rows(q.text, num_results=q.num, days=q.days)) if gateway.is_pool(exa_key) \
            else (lambda q: _exa_direct(exa_key, q))
    errors: list = []
    stopped = []

    def search(q):
        if q.source == "exa":
            return exa(q) if exa else None
        if not monid_key or stopped:
            return None
        try:
            return monid_sources.run(q.source, q.text, key=monid_key, location=q.location, days=q.days, num=q.num)
        except monid_sources.MonidError as e:
            errors.append(str(e))
            stopped.append(1)
            return None
    search.errors = errors
    return search


def make_ask(cfg: dict, cancelled=None, on_wait=None):
    """The `ask` callable — `ask(prompt, purpose, json_mode, temperature)` — or
    None when no model is configured.

    On the owner's own Groq key the calls are paced under the key's rate limit, a refused call goes to the next model
    the engine knows (Groq counts a limit per model) and only then waits (prospector/ai_pace.py). `cancelled()` is
    asked while it waits; `on_wait(seconds, why)` says what it is waiting for. The budget is `ai_tokens_per_minute` in
    the config, or the AI_TOKENS_PER_MINUTE variable, when the owner's plan allows more."""
    from . import gateway
    key = (cfg or {}).get("api_key", "")
    if not key:
        return None
    if gateway.is_pool(key):
        return lambda prompt, purpose, json_mode=True, temperature=0.2: gateway.ask(
            prompt, purpose, json_mode=json_mode, temperature=temperature)

    import os
    from . import ai_pace
    import core_bridge as CB                             # lazy: wires the engine + submodule
    try:
        budget = int((cfg or {}).get("ai_tokens_per_minute") or os.environ.get("AI_TOKENS_PER_MINUTE") or ai_pace.PER_MINUTE)
    except (TypeError, ValueError):
        budget = ai_pace.PER_MINUTE

    def call(model, prompt, temperature, json_mode):
        return CB.router.groq_chat(key, model, prompt, temperature=temperature, json_mode=json_mode, retries=0)
    return ai_pace.paced(call, CB.router.model_chain((cfg or {}).get("model", "")), ai_pace.Pacer(budget),
                         cancelled=cancelled, on_wait=on_wait)
