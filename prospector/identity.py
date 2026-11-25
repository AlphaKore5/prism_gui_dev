"""
Who a lead IS, across runs
──────────────────────────
A lead reaches Prism by two roads, and the same person arrives with different
fields on each:

  • a sheet — a real e-mail, maybe a profile link, never an id;
  • the ICP search — a profile link and a name/company, but no e-mail until
    enrich GUESSES one (and verify may later replace the guess with a found
    address).

So a person is not one key but a SET of keys, and two leads are the same person
when they share ANY of them:

    e:<email>             every address the lead carries (email + other_emails)
    u:<profile>           the profile link, normalised (linkedin.com/in/<slug>)
    a:<apollo id>         Apollo's own id for the person — the ONLY key its free
                          search row carries (no e-mail, a half-hidden surname),
                          so it is what lets a later run skip someone before it
                          spends a credit revealing them
    n:<name>|<company>    name + company, both normalised — the weakest key,
                          only formed when both halves are present

Pure and stdlib-only, so the sessions store, the sourcing loop and the sheet
path all ask "have we pulled this person before?" the same way.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

# Only true legal-form words. enrich._SUFFIX also strips "india", "industries"
# and "manufacturing", which would merge different companies — not reused here.
_LEGAL = frozenset({
    "pvt", "private", "ltd", "limited", "llp", "llc", "inc", "incorporated",
    "corp", "corporation", "co", "company", "plc", "gmbh", "ag", "bv", "sa",
})
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")
_LINKEDIN_IN = re.compile(r"^/in/([^/]+)", re.IGNORECASE)


def norm_email(value) -> str:
    """lower-cased, trimmed address, or "" if it is not an address at all."""
    v = (value if isinstance(value, str) else "").strip().lower()
    if v.startswith("mailto:"):
        v = v[len("mailto:"):]
    if "@" not in v or " " in v or v.startswith("@") or v.endswith("@"):
        return ""
    return v


def norm_text(value) -> str:
    """casefolded, punctuation → space, whitespace collapsed."""
    v = _PUNCT.sub(" ", (value if isinstance(value, str) else "").casefold())
    return _SPACE.sub(" ", v).strip()


def norm_company(value) -> str:
    """norm_text with trailing legal-form words removed ("Acme Pvt. Ltd." →
    "acme"), so "X Ltd" and "X Limited" are one company."""
    words = norm_text(value).split()
    while len(words) > 1 and words[-1] in _LEGAL:
        words.pop()
    return " ".join(words)


def norm_profile(url) -> str:
    """A profile link reduced to its identity: no scheme, no www or country
    subdomain, no query, fragment or trailing slash. LinkedIn member profiles
    become linkedin.com/in/<slug>; any other link becomes host+path. A bare host
    with no path identifies nobody and returns ""."""
    raw = (url if isinstance(url, str) else "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    try:
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+", "/", parts.path or "").rstrip("/")
    if not host or not path:
        return ""
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        m = _LINKEDIN_IN.match(path)
        if m:
            return f"linkedin.com/in/{m.group(1).lower()}"
        return f"linkedin.com{path.lower()}"
    return f"{host}{path.lower()}"


def is_linkedin(url) -> bool:
    """Whether a link is a LinkedIn page (linkedin.com or a country
    sub-domain of it)."""
    raw = (url if isinstance(url, str) else "").strip()
    if not raw:
        return False
    try:
        host = (urlsplit(raw if "://" in raw else "https://" + raw).hostname or "").lower()
    except ValueError:
        return False
    return host == "linkedin.com" or host.endswith(".linkedin.com")


def move_profile_link(lead) -> bool:
    """A link filed as LinkedIn that is not one — an Exa people-search page,
    which is what Exa returns now (24-Sep-2026: the exported LinkedIn column was
    full of exa.ai links) — moved to extra["profile_url"]. True when moved."""
    extra = getattr(lead, "extra", None)
    link = (extra or {}).get("linkedin")
    if not link or is_linkedin(link):
        return False
    extra.setdefault("profile_url", link)
    del extra["linkedin"]
    return True


def keys_of(lead) -> frozenset:
    """Every identity key this lead carries right now. Recompute after enrich
    or verify: both can change the e-mail."""
    keys = set()
    extra = getattr(lead, "extra", None) or {}
    addresses = [getattr(lead, "email", "")]
    others = extra.get("other_emails")
    if isinstance(others, (list, tuple)):
        addresses.extend(others)
    for addr in addresses:
        email = norm_email(addr)
        if email:
            keys.add("e:" + email)
    # A LinkedIn link, and the page a search result came from (an Exa
    # people-search page, profile_url) — the same "u:" key it always made, so
    # someone found before is still someone found before.
    for link in (extra.get("linkedin"), extra.get("profile_url")):
        profile = norm_profile(link)
        if profile:
            keys.add("u:" + profile)
    apollo_id = str(extra.get("apollo_id") or "").strip()
    if apollo_id:
        keys.add("a:" + apollo_id)
    name = norm_text(getattr(lead, "name", ""))
    company = norm_company(getattr(lead, "company", ""))
    # An Apollo preview row's name is half a name ("Rahul S."): as a key it would fold two real Rahuls at Acme into
    # one. Its Apollo id identifies it instead (a: above).
    if name and company and not extra.get("apollo_preview"):
        keys.add(f"n:{name}|{company}")
    return frozenset(keys)


class SeenIndex:
    """A set of identity keys with an any-key membership test:
    `lead in index` is True when the lead shares at least one key."""

    def __init__(self, keys=()):
        self._keys = set(k for k in keys if isinstance(k, str) and k)

    def __contains__(self, lead) -> bool:
        return not self._keys.isdisjoint(keys_of(lead))

    def __len__(self) -> int:
        return len(self._keys)

    def add(self, lead) -> None:
        self._keys.update(keys_of(lead))

    def update(self, keys) -> None:
        self._keys.update(k for k in keys if isinstance(k, str) and k)

    def keys(self) -> frozenset:
        return frozenset(self._keys)


def dedupe(leads) -> tuple:
    """(kept, dropped): the first occurrence of each person in order; later
    rows sharing any key with an earlier one are dropped. For a sheet whose
    tabs repeat people, or search results that return someone twice."""
    index, kept, dropped = SeenIndex(), [], []
    for lead in leads:
        if lead in index:
            dropped.append(lead)
        else:
            kept.append(lead)
        index.add(lead)
    return kept, dropped
