"""
Find my buyers — the company list (list first)
──────────────────────────────────────────────
Signal-first hunting searches the open web for events (news, funding, hires) and hopes the company that did it is a
customer. On 22-Nov-2026 that returned a chip startup, a clean-energy fund and an office manager at Regeneron for a
seller of outreach tools to small Indian B2B firms. Intent-data products work the other way round: write the ideal
customer down, build a list of companies that FIT, gate it on size and place, and only then look for a signal on
those companies. Fit is a gate, not a bonus; a signal on a company that does not fit never reaches the owner.

    1. company search   Exa's company index, one search per kind of company the buyers are ("small industrial
                        equipment manufacturer"), which returns a structured profile: name, headcount, HQ, description.
    2. the gate         plain rules, no model: a headcount over the seller's maximum, or an HQ in another country,
                        drops the company. An unknown size or place is kept and not guessed.
    3. the fit read     the model reads each description against THE CUSTOMER and names competitors, who are dropped.
    4. the signals      for the companies that fit: a dated search on that company's own recent moves (hiring, new
                        office, expansion). A page that does not name the company is dropped.
    5. the intent read  the model reads the signals and scores the intent. A company that fits and has no signal
                        stays on the list, said plainly: "fits, nothing recent found".

Qt-free. The two outside calls are an object with `companies(text, where, n)` and `signals(name)`, so a test needs no
network. Exa company search needs the owner's own Exa key; the credit pool has no company-list call yet, so a pooled
hunt skips this source and says so.
"""
from __future__ import annotations

import re
from dataclasses import replace
from datetime import date, datetime

from . import buyers as B

EXA_SEARCH_URL = "https://api.exa.ai/search"
SIGNAL_FOCUS = ("hiring sales or business development staff, a new office or branch, expansion, a new product line, "
                "growth, a new client win")
POST_DAYS = 45                  # a post this recent counts as the company being active
GROWTH_MIN = 10.0               # a year's headcount growth, in percent, worth saying
PER_SEARCH = 3                  # a company search is asked for this many times the companies a hunt reads: the gate drops some
SIGNALS_KEPT = 3                # signal pages kept on a company
FIT_FLOOR = 40                  # a company the model rates under this does not get a signal search


# ── the outside calls ─────────────────────────────────────────────────────────

def _host(url) -> str:
    from .source import _host as host
    return host(url)


_GROWTH = re.compile(r"Yearly Growth:\s*([+-]?\d+(?:\.\d+)?)\s*%", re.I)
_POST = re.compile(r"^-\s*\[(\d{4}-\d{2}-\d{2})[^\]]*\]\s*(.+)$", re.M)
# A festival greeting or a thank-you is a post, not a sign the company is about to buy anything.
_GREETING = re.compile(r"\b(happy|wishes|wishing|greetings|congratulations|thank you|thanks|blessed|festival|"
                       r"diwali|navratri|ganesh|raksha|independence day|republic day|holi|eid|christmas|new year)\b", re.I)


def _facts_of(text: str) -> tuple:
    """(yearly headcount growth in percent or None, [(date, post text)] newest first) from the profile text Exa
    returns with a company: "- Yearly Growth: -14.3%" and the "## Social" bullets "- [2026-11-08] post...". """
    text = str(text or "")
    g = _GROWTH.search(text)
    social = text.split("## Social", 1)[1] if "## Social" in text else ""
    posts = [(d, " ".join(t.split())) for d, t in _POST.findall(social)]
    posts.sort(key=lambda x: x[0], reverse=True)
    return (float(g.group(1)) if g else None), posts[:20]


def profile_rows(rows) -> list:
    """Exa company-search rows read into plain profiles: {name, domain, url, headcount, hq, description, growth,
    posts}. A row with no company profile in it, or no description to quote, is skipped: with nothing to quote there
    is no card."""
    from .source import _headcount
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        host = _host(row.get("url"))
        for e in row.get("entities") or []:
            if not isinstance(e, dict) or e.get("type") not in (None, "", "company"):
                continue
            props = e.get("properties") or {}
            name = " ".join(str(props.get("name") or "").split())
            description = " ".join(str(props.get("description") or "").split())
            if not (name and description):
                continue
            work = props.get("workforce")
            hq = props.get("headquarters")
            if isinstance(hq, dict):
                hq = ", ".join(str(hq[k]).strip() for k in ("city", "country")
                               if isinstance(hq.get(k), str) and hq[k].strip()) or str(hq.get("address") or "").strip()
            growth, posts = _facts_of(row.get("text"))
            out.append({"name": name[:120], "domain": host, "url": str(row.get("url") or ""),
                        "headcount": _headcount(work.get("total") if isinstance(work, dict) else work),
                        "hq": hq if isinstance(hq, str) else "", "description": description[:600],
                        "growth": growth, "posts": posts})
            break
    return out


class Lister:
    """The owner's own Exa key, asked for company profiles and for a company's recent moves."""

    def __init__(self, api_key: str, timeout: int = 40):
        self.api_key, self.timeout = api_key, timeout

    def companies(self, text: str, where: str, n: int):
        """Profiles for one kind of company, or None when the search itself failed."""
        import requests                                           # lazy, like the rest of the engine
        try:
            r = requests.post(EXA_SEARCH_URL, timeout=self.timeout,
                              headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
                              json={"query": f"{text} in {where}", "category": "company", "type": "auto",
                                    "numResults": max(1, min(int(n), 25))})
            if r.status_code != 200:
                return None
            rows = r.json().get("results")
        except Exception:                                         # noqa: BLE001 — a failed search is a count, not a crash
            return None
        return profile_rows(rows) if isinstance(rows, list) else None

    def signals(self, name: str, exclude=()):
        """Dated signal pages (Signal objects) about one company, or None when the lookup failed."""
        from . import signals
        from .models import Lead
        provider = signals.ExaSignalProvider(self.api_key, num_results=5, exclude_domains=tuple(exclude))
        found = provider.fetch(Lead(company=name), focus=SIGNAL_FOCUS)
        return None if provider.errored else found


def make_lister(cfg: dict):
    """A Lister on the owner's own Exa key, or None: with no key, or on the credit pool, which has no company-list
    call yet."""
    from . import gateway, signals
    eff = gateway.effective_cfg(cfg or {})
    if gateway.is_pool(eff.get("exa_api_key")):
        return None
    key = signals.exa_key(eff)
    return Lister(key) if key else None


# ── the gate ──────────────────────────────────────────────────────────────────

def gate(profile: dict, offer: B.Offer) -> str:
    """"" when the company stays; "big" or "place" when plain rules drop it. Unknown is kept, never guessed."""
    from . import places
    cap = int(offer.max_staff or 0)
    if cap and profile.get("headcount") and profile["headcount"] > cap:
        return "big"
    want = places.countries_in(offer.regions or "India")
    have = places.countries_in(profile.get("hq") or "")
    if want and have and not (want & have):
        return "place"
    return ""


def profile_signals(p: dict, today: date) -> list:
    """Dated, quoted signs of life that came with the company profile, at no extra search: a recent post (a festival
    greeting does not count) and a year's headcount growth. Signal objects, like a news search returns."""
    from .models import Signal
    out = []
    for day, text in p.get("posts") or ():
        try:
            age = (today - datetime.strptime(day, "%Y-%m-%d").date()).days
        except ValueError:
            continue
        if 0 <= age <= POST_DAYS and not _GREETING.search(text):
            out.append(Signal(title="Posted on LinkedIn", snippet=text[:220], url=p.get("url") or "", published=day,
                              source="linkedin.com"))
        if len(out) == 2:
            break
    g = p.get("growth")
    if g is not None and g >= GROWTH_MIN:
        out.append(Signal(title=f"Headcount up {g:.0f}% in a year", snippet="", url=p.get("url") or "", published="",
                          source="company profile"))
    return out


def _mentions(company: str, *texts: str) -> bool:
    """The page names the company: its first word of three letters or more is in the title or the text."""
    words = [w for w in re.split(r"\W+", company.casefold()) if len(w) >= 3
             and w not in ("the", "and", "pvt", "ltd", "llp", "inc", "private", "limited")]
    if not words:
        return False
    blob = " ".join(texts).casefold()
    return words[0] in blob


def _hit(p: dict) -> B.Hit:
    url = p.get("url") or (("https://" + p["domain"]) if p.get("domain") else "")      # the page Exa found: a site or a LinkedIn page
    facts = []
    if p.get("headcount"):
        facts.append(f"{p['headcount']:,} staff on record")
    if p.get("hq"):
        facts.append(f"based in {p['hq']}")
    text = p["description"] + (f" ({'; '.join(facts)}.)" if facts else "")
    return B.Hit(id=B.hit_id(url), channel=B.LIST, kind=B.KIND_OF[B.LIST], who=p["name"], title=p["name"],
                 snippet=text[:600], url=url, source=p.get("domain") or B.host_of(url), status=B.UNKNOWN)


# ── the list ──────────────────────────────────────────────────────────────────

def list_first(offer: B.Offer, summary: str, queries: list, lister, ask, *, preview: bool = False,
               today: "date | None" = None, on_progress=None, cancelled=None, progress_base: int = 0,
               progress_total: int = 0, skip=None, learned: str = "") -> tuple:
    """Run the company-list searches. Returns (hits, stats, notes): scored cards best first, counts for the hunt's
    stats, and honest sentences for the owner."""
    today = today or date.today()
    stats = {"list_found": 0, "list_big": 0, "list_place": 0, "list_signals": 0, "failed": 0, "searches": 0}
    notes: list = []
    where = (offer.regions or "").strip()[:80] or "India"
    own = offer.domain()
    cap = B.LIST_PREVIEW if preview else B.LIST_COMPANIES
    seen, kept = set(), []
    own_signals: dict = {}
    for n, q in enumerate(queries, 1):
        if cancelled and cancelled():
            notes.append("Stopped before every company search ran.")
            break
        if on_progress:
            on_progress(progress_base + n, progress_total or len(queries), q)
        stats["searches"] += 1
        rows = lister.companies(q.text, where, cap * PER_SEARCH)
        if rows is None:
            stats["failed"] += 1
            continue
        for p in rows:
            stats["list_found"] += 1
            # A company profile is not a search hit: a small firm's only page may be its LinkedIn page, so the
            # directory and social blocklist does not apply. The key is the page, never just the host.
            key = re.sub(r"^https?://(www\.)?|/+$", "", (p.get("url") or "").casefold()) or re.sub(r"\W+", "", p["name"].casefold())
            if key in seen or (own and B.host_of(p.get("url") or "").endswith(own)):
                continue
            seen.add(key)
            why = gate(p, offer)
            if why:
                stats["list_" + why] += 1
                continue
            judged = skip(_hit(p)) if skip else ""
            if judged:                                           # the owner already decided this company
                stats["remembered_" + judged] = stats.get("remembered_" + judged, 0) + 1
                continue
            kept.append(p)
            own_signals[B.hit_id(p.get("url") or "")] = profile_signals(p, today)
    if stats["failed"]:
        notes.append(f"{stats['failed']} of {len(queries)} company searches failed, so this list may be missing "
                     "companies.")
    kept = kept[:cap]
    hits = [_hit(p) for p in kept]
    if not hits:
        notes.append("The company search found no company that fits the size and place you named.")
        return [], stats, notes
    # the fit read: competitors and the wrong kind of company are dropped
    if ask is not None:
        read, dropped, err = B.model_score(hits, summary, {}, ask, offer.competitors, None, offer.ideal, learned)
        stats["vendors"] = dropped
        if err:
            notes.append(err)
    else:
        for h in hits:
            B.rule_score(h)
    live = [h for h in hits if h.decision != B.NOT_A_FIT]
    live.sort(key=lambda h: (-h.fit, h.id))
    # the signals: only on the companies that fit
    with_signal = 0
    ranked = [h for h in live if h.fit >= FIT_FLOOR or not h.checked][:B.LIST_SIGNALS_PREVIEW if preview else B.LIST_SIGNALS]
    shadows = {}
    for h in ranked:
        if cancelled and cancelled():
            break
        if on_progress:
            on_progress(progress_base + len(queries) + len(shadows) + 1, progress_total or len(queries), queries[-1])
        stats["searches"] += 1
        found = lister.signals(h.who, [offer.domain()] if offer.domain() else ())
        if found is None:
            stats["failed"] += 1
            found = []
        found = own_signals.get(h.id, []) + [s for s in found if _mentions(h.who, s.title, s.snippet)]
        found = found[:SIGNALS_KEPT + 2]
        if not found:
            continue
        with_signal += 1
        lines = [f"{(s.published or 'undated')}: {s.title}. {s.snippet}".strip() for s in found]
        dated = sorted(s.published for s in found if s.published)
        shadows[h.id] = replace(h, snippet=("Recent: " + " | ".join(lines) + " | About: " + h.snippet))
        h.snippet = (h.snippet + " Recent: " + " | ".join(f"{s.published or 'undated'}: {s.title}" for s in found))[:600]
        if dated:
            h.published, h.status = dated[-1], B.RECENT
    stats["list_signals"] = with_signal
    if shadows and ask is not None:
        # the intent read: the model scores what each company did, with the signal in front of it
        batch = list(shadows.values())
        B.model_score(batch, summary, {}, ask, offer.competitors, None, offer.ideal, learned)
        for s in batch:
            h = next(x for x in live if x.id == s.id)
            h.fit, h.intent, h.why, h.who, h.scored_by = s.fit, s.intent, s.why, s.who, s.scored_by
            h.decision, h.reason = s.decision, s.reason
    live = [h for h in live if h.decision != B.NOT_A_FIT]
    for h in live:
        if h.checked and h.id not in shadows and not h.why:
            h.why = "Fits the customer you described. No recent signal was found."
    notes.append(f"Companies like your customer: {stats['list_found']} found, {stats['list_big']} over the size you set, "
                 f"{stats['list_place']} in another country; {len(hits)} read, {with_signal} with a recent signal. "
                 "The rest fit but nothing recent was found.")
    live.sort(key=lambda h: (-h.score, h.id))
    return live, stats, notes
