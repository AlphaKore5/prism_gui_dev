"""
Leads & Outreach — every company Prism knows, filtered as you click
────────────────────────────────────────────────────────────────────
Apollo's Companies page is Find People's twin (knowledge.apollo.io, "Search for
Companies", read 24-Oct-2026): the same Total · Net New · Saved split over
filters, a table you tick, and an action bar — Save, Find people, List, Export,
Edit — whose first word is the rule that makes everything else work: "save a
company to turn it into an account. This unlocks key actions like enrichment,
ownership, and timeline tracking."

Prism's answer is the People page's (pool.py): filters are instant and free
over the companies Prism ALREADY holds, and finding new ones is a separate,
explicit act. The POOL here is those companies, one row per company however
many ways it arrived:

  · saved accounts (accounts.py) — a sheet's companies, a saved person's
    employer, a company the owner saved from this page;
  · the employer of everyone in the People pool (pool.py) — a company Prism
    has a person at but nobody has saved is NET NEW, with the people attached.

Two records are one company by accounts.py's rule: the same web domain, or —
where either side has no domain — the same name once legal words are dropped
("Acme Pvt. Ltd." is "Acme"). A free-mail domain (gmail.com …) and a business
directory's (tradeindia.com …) are nobody's company.

`filter_companies` applies a SearchSpec the way Apollo does — AND across
filters, OR within one — using the SAME model the People page's company-level
filters use (prospector.filters.SearchSpec): Company (name or domain), Industry
and Keywords (words the company's own record carries — an industry or keyword
include a company says nothing about does not pass), Company headcount and
Annual revenue (a company whose size is not on record passes: unverified, not
wrong — filters.match_company's rule), Company HQ location, Stage and Lists
(the ACCOUNT's, as Apollo's "Stage > Account"), Account CSV import, and custom
fields on the account.

Qt-free and path-free: the page builds a pool off the UI thread and filters it
in memory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace

from prospector import filters as F
from prospector.identity import norm_company, norm_text

from addons.leads import accounts as AC
from addons.leads import pool as P

PAGE_SIZE = P.PAGE_SIZE
SORTS = ("relevance", "name", "newest", "people", "size")
# A company's web address is never one of these: a person is not reachable at a
# directory. (prospector/enrich.py keeps the long list for finding a homepage;
# this is the part that matters for telling two companies apart.)
_DIRECTORIES = frozenset({
    "dial4trade.com", "tradeindia.com", "indiamart.com", "exportersindia.com",
    "goldenpages.in", "thecompanycheck.com", "yelu.in", "indiainfo.net",
    "hoursfinder.com", "justdial.com", "sulekha.com", "alibaba.com",
    "linkedin.com", "facebook.com",
})


@dataclass
class Company:
    name: str = ""
    domain: str = ""
    website: str = ""
    location: str = ""
    industry: str = ""
    headcount: str = ""
    revenue: str = ""
    phone: str = ""
    linkedin: str = ""
    description: str = ""
    custom: dict = field(default_factory=dict)
    saved: bool = False             # an account (accounts.py)
    stage: str = ""                 # the account's stage; "" when not saved
    lists: tuple = ()
    imports: tuple = ()             # the Account CSV imports that brought it in
    first_seen: str = ""            # ISO: when it was saved / first seen
    last_seen: str = ""
    account: object = None          # the accounts.Account, when saved
    people: tuple = ()              # pool.Person who work there
    keys: frozenset = frozenset()   # every company key it is known by

    @property
    def people_count(self) -> int:
        return len(self.people)

    @property
    def saved_people(self) -> int:
        return sum(1 for p in self.people if p.saved)

    @property
    def employees(self) -> int | None:
        return number(self.headcount)

    def view(self) -> dict:
        """The company as a plain dict (what an account is saved from)."""
        return {"name": self.name, "domain": self.domain, "website": self.website,
                "location": self.location, "industry": self.industry,
                "headcount": self.headcount, "revenue": self.revenue,
                "phone": self.phone, "linkedin": self.linkedin,
                "description": self.description, "custom": dict(self.custom)}


# ── reading what a sheet or a lookup wrote ───────────────────────────────────

def number(value) -> int | None:
    """A company size from a cell — "500+", "51-200", "1,200" → the first
    number in it (the lower bound of a range), or None."""
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(value or ""))]
    return nums[0] if nums and nums[0] > 0 else None


_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|mn|mm|million|b|bn|billion)?\b", re.I)
_RUPEE = re.compile(r"₹|\brs\.?\b|\binr\b|\bcrore\b|\bcr\b|\blakh\b", re.I)
_SCALE = {"k": 1e3, "m": 1e6, "mn": 1e6, "mm": 1e6, "million": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9}


def revenue_usd(value) -> int | None:
    """Annual revenue in whole US dollars from a cell, or None. A lookup writes
    the plain dollar figure; a sheet may write "$5M" or "12.5 million". Rupees
    ("₹120 Cr") are NOT converted — an unknown size passes a revenue filter
    (unverified) rather than being wrongly placed in a band."""
    text = str(value or "")
    if not text.strip() or _RUPEE.search(text):
        return None
    m = _MONEY.search(text)
    if not m:
        return None
    n = float(m.group(1).replace(",", "")) * _SCALE.get((m.group(2) or "").lower(), 1)
    return int(n) if n > 0 else None


def real_domain(site) -> str:
    """The web domain a website points at — "" for none, for free mail and for
    a business directory."""
    d = AC.company_domain(site)
    return "" if d in _DIRECTORIES else d


# ── building ─────────────────────────────────────────────────────────────────

def _fold(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _from_account(account) -> Company:
    c = Company(name=account.name or account.domain, domain=account.domain,
                website=account.website, location=account.location,
                industry=account.industry, headcount=account.headcount,
                revenue=account.revenue, phone=account.phone,
                linkedin=account.linkedin, description=account.description,
                custom=dict(account.custom), saved=True, stage=account.stage,
                lists=tuple(account.lists), imports=tuple(account.imports),
                first_seen=account.saved_at, last_seen=account.updated_at or account.saved_at,
                account=account)
    c.keys = frozenset(account.keys())
    return c


def _company_of(person) -> dict:
    """The company a person works at, as company facts — {} when they name none."""
    lead = person.lead
    extra = getattr(lead, "extra", None) or {}
    name = " ".join(str(getattr(lead, "company", "") or "").split())
    site = str(extra.get("website") or "").strip()
    domain = real_domain(site) or real_domain(getattr(lead, "email", ""))
    if not (name or domain):
        return {}
    return {"name": name, "domain": domain, "website": site or domain,
            "industry": " ".join(str(getattr(lead, "industry", "") or
                                     extra.get("industry") or "").split()),
            "headcount": " ".join(str(extra.get("headcount") or "").split())}


class _Index:
    """Companies by the keys they are known by, with accounts.save's rule: the
    same domain, or the same name where either side has no domain."""

    def __init__(self):
        self.companies: list = []
        self._domain: dict = {}
        self._name: dict = {}

    def find(self, domain: str, name: str):
        if domain:
            hit = self._domain.get(domain)
            if hit is not None:
                return hit
        n = norm_company(name)
        hit = self._name.get(n) if n else None
        if hit is not None and (not domain or not hit.domain):
            return hit
        return None

    def add(self, company: Company) -> None:
        self.companies.append(company)
        self.index(company)

    def index(self, company: Company) -> None:
        if company.domain:
            self._domain.setdefault(company.domain, company)
        n = norm_company(company.name)
        if n:
            self._name.setdefault(n, company)


def build(accounts=(), people=()) -> list:
    """The pool from the saved accounts and everyone in the People pool.

    A saved account's own record wins; a company Prism only knows from a person
    is net new, its facts (website, industry, size) read off the people there —
    the first one that has them. Each company carries its people (pool.Person)."""
    index = _Index()
    for account in accounts or ():
        c = _from_account(account)
        # An account with a domain and one without may be the same company;
        # accounts.save refused to merge them, so the pool does not either.
        index.add(c)
    for person in people or ():
        facts = _company_of(person)
        if not facts:
            continue
        c = index.find(facts["domain"], facts["name"])
        if c is None:
            c = Company(name=facts["name"] or facts["domain"], domain=facts["domain"],
                        website=facts["website"], industry=facts["industry"],
                        headcount=facts["headcount"])
            index.add(c)
        else:
            for key in ("website", "industry", "headcount"):
                if facts[key] and not getattr(c, key):
                    setattr(c, key, facts[key])
            if facts["domain"] and not c.domain:
                c.domain = facts["domain"]
            if facts["name"] and not c.name:
                c.name = facts["name"]
            index.index(c)
        c.people = c.people + (person,)
        seen = getattr(person, "last_seen", "") or getattr(person, "first_seen", "")
        if seen:
            c.last_seen = max(c.last_seen, seen)
            c.first_seen = min(x for x in (c.first_seen, seen) if x)
    out = index.companies
    for c in out:
        c.keys = frozenset(AC.company_keys(c.name, c.domain or c.website))
        c.people = tuple(sorted(c.people, key=lambda p: (not p.saved, -p.fit,
                                                           norm_text(getattr(p.lead, "name", "")))))
    return out


def without(companies, removed_names=()) -> list:
    """The pool minus companies the owner deleted this session (their keys)."""
    gone = frozenset(removed_names or ())
    if not gone:
        return list(companies or ())
    return [c for c in companies or () if c.keys.isdisjoint(gone)]


# ── filtering ────────────────────────────────────────────────────────────────

def _texts(company: Company) -> list:
    return [company.name, company.industry, company.description,
            " ".join(map(str, company.custom.values()))]


def _facts(company: Company) -> dict:
    return {"headcount": company.employees, "revenue": revenue_usd(company.revenue),
            "hq": company.location, "description": company.description}


def _name_hit(company: Company, value: str) -> bool:
    """A Company filter value names this company: its name (legal words
    dropped) holds the value's, or it IS the company's web domain."""
    want = norm_company(value)
    if want and want in norm_company(company.name):
        return True
    dom = real_domain(value)
    return bool(dom and dom == company.domain)


class Matcher:
    """One filter pass over companies: everything that depends only on the spec
    is worked out once, then `test(company)` per company."""

    def __init__(self, spec, *, query: str = ""):
        self.spec = spec
        self.query = norm_text(query or "")
        self.records = {name: (P.folded(spec.facet(name).include),
                               P.folded(spec.facet(name).exclude))
                        for name in ("account_stages", "account_lists")
                        if spec.facet(name).active}
        self.imports = frozenset(spec.account_imports)
        self.custom = []
        for key, values in spec.custom_fields.items():
            scope, column = F.split_custom_key(key)
            if scope == "account":
                self.custom.append((column.casefold(), P.folded(values)))
        self.facts = bool(spec.headcount or spec.revenue or spec.company_hq.active
                          or spec.industries.exclude or spec.keywords.exclude)

    def test(self, c: Company) -> bool:
        spec = self.spec
        if self.query:
            hay = norm_text(" ".join((c.name, c.domain, c.industry, c.location)))
            if self.query not in hay:
                return False
        names = spec.companies
        if names.include and not any(_name_hit(c, v) for v in names.include):
            return False
        if any(_name_hit(c, v) for v in names.exclude):
            return False
        for facet, include, exclude in (
                ("industries", spec.industries.include, spec.industries.exclude),
                ("keywords", spec.keywords.include, spec.keywords.exclude)):
            texts = [t for t in (_texts(c) if facet == "keywords" else
                                 [c.industry, c.description]) if t]
            if include and (not texts or not any(
                    F._has_phrase(t, alt) for t in texts
                    for v in include for alt in F._alternatives(v))):
                return False
            # Match_company reads an exclude against a description only; a
            # company's own industry is on its record, so it counts here.
            if exclude and any(F._has_phrase(t, alt) for t in texts
                               for v in exclude for alt in F._alternatives(v)):
                return False
        if self.facts:
            shim = SimpleNamespace(title="", company=c.name)
            if F.match_company(spec, shim, _facts(c)):
                return False
        if self.imports and self.imports.isdisjoint(c.imports):
            return False
        have = {"account_stages": {_fold(c.stage)} if c.stage else set(),
                "account_lists": {_fold(x) for x in c.lists}}
        for name, (include, exclude) in self.records.items():
            if not P.names_pass(have[name], include, exclude):
                return False
        for column, values in self.custom:
            value = ""
            for key, v in c.custom.items():
                if str(key).strip().casefold() == column and str(v or "").strip():
                    value = _fold(v)
                    break
            if value not in values:
                return False
        return True


def filter_companies(companies, spec, *, query: str = "") -> list:
    m = Matcher(spec, query=query)
    return [c for c in companies or () if m.test(c)]


def split(companies) -> dict:
    """Apollo's three tabs: {"total", "net_new", "saved"}."""
    companies = list(companies or ())
    return {"total": companies,
            "net_new": [c for c in companies if not c.saved],
            "saved": [c for c in companies if c.saved]}


def sort_companies(companies, how: str = "relevance") -> list:
    """relevance — most of your people first, then saved, then newest; name —
    A–Z; newest — most recently saved or seen first; people — the most people
    first; size — the largest company first (unknown last)."""
    companies = list(companies or ())
    if how == "name":
        return sorted(companies, key=lambda c: norm_company(c.name) or "~")
    if how == "newest":
        return sorted(companies, key=lambda c: c.last_seen, reverse=True)
    if how == "people":
        return sorted(companies, key=lambda c: (-c.people_count, norm_company(c.name)))
    if how == "size":
        return sorted(companies, key=lambda c: (c.employees is None, -(c.employees or 0),
                                                norm_company(c.name)))
    return sorted(companies, key=lambda c: (c.people_count, c.saved, c.last_seen),
                  reverse=True)


def pick(companies, n: int = 0) -> list:
    """Apollo's bulk selection over a result, in its order ("Select number of
    companies lets you specify how many companies to select"): the first `n`
    (0: everyone)."""
    n = max(0, int(n or 0))
    companies = list(companies or ())
    return companies[:n] if n else companies


def page(companies, index: int, size: int = PAGE_SIZE) -> dict:
    return P.page(companies, index, size)


def record_options(saved_accounts=()) -> dict:
    """What Stage, Lists and Custom fields offer for companies — pool.
    record_options' account side."""
    return P.record_options((), saved_accounts)


# ── what the owner can take away ─────────────────────────────────────────────

def accounts_of(companies) -> list:
    """The company dicts to hand accounts.save for these companies."""
    return [c.view() for c in companies or ()]


def export_table(companies) -> tuple:
    """(header, rows) for a CSV of these companies — Apollo's "Export accounts
    to a CSV": the record's own fields, its stage and lists, and how many people
    Prism holds there, then the sheet's custom columns."""
    companies = list(companies or ())
    columns = []
    for c in companies:
        for key in c.custom:
            if key not in columns:
                columns.append(key)
    header = ["Company", "Website", "Domain", "Industry", "Location", "Employees",
              "Annual revenue", "Phone", "LinkedIn", "Stage", "Lists", "People held",
              "Saved contacts", "Description"] + columns
    rows = []
    for c in companies:
        rows.append([c.name, c.website, c.domain, c.industry, c.location, c.headcount,
                     c.revenue, c.phone, c.linkedin, c.stage, "; ".join(c.lists),
                     c.people_count, c.saved_people, c.description]
                    + [c.custom.get(k, "") for k in columns])
    return header, rows
