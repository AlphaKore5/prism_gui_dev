"""
Leads & Outreach — everyone Prism already has, filtered as you click
────────────────────────────────────────────────────────────────────
Apollo's Find People re-answers every filter change from its own database, so
the table moves the moment you tick something. Prism's people come from Exa —
a search costs credits — so the owner chose (23-Sep-2026) the Apollo feel
without the Apollo bill: filters are instant over the people Prism ALREADY
holds, and fetching new ones is a separate, explicit button.

The POOL is those people, one row per person however many ways they arrived:

  · saved contacts (contacts.py) — CSV imports, saves, exports, sequences;
  · everyone every past run found (sessions.py), with the newest qualified
    dossier when a run qualified them.

Two people are one when their identity keys touch (prospector.identity) —
the same rule a run uses to skip someone it already pulled. A saved contact's
fields win (the owner saved that record); among runs, the newest wins.

`filter_people` applies a SearchSpec the way Apollo does — AND across filters,
OR within one — using the SAME checks a search enforces (filters.match_person
and match_company), plus what only a local pool can check:

  · Job titles with "similar titles" on: match_person lets an include only
    steer an Exa query then; here it is a real filter — a title carrying the
    words of an include, or reading as the same seniority and function
    ("Plant Head" ~ "Head of Manufacturing").
  · Industry and Keywords INCLUDES, which a search could only steer: checked
    against what the person carries (their industry, their account's, their
    imported columns); a person carrying no match fails.
  · …except the people a SEARCH steered by those same values found. Those
    three includes only ever steered that search, which then took whoever
    came back — so a person it found passes them here too (Person.steered,
    from the run's own filters). Without that, pressing Find new people
    brought back 300 people and the page showed the dozen whose Exa row
    happened to name the industry: the "why only 37?" of 22-Sep-2026 again.
  · Contact CSV import — the person carries one of the chosen import ids.
  · Account CSV import — the person's company (by name, or by the domain of
    their e-mail / website) is one of the chosen imports' companies; that
    company's own record then answers the company-level filters (industry,
    headcount, HQ) the person row never carried.
  · The "Search people" box — name, title or company contains the text.
  · Apollo's filters over the owner's own records: Stage and Lists (the
    contact's — Person.stage / .lists, from contacts.py — or their saved
    account's, accounts.py), included or excluded, and Custom fields (the
    columns a sheet brought in, on the person or on their account). Someone
    not saved has no stage and is on no list: an include fails them, an
    exclude lets them through — Apollo's net new prospects behave the same.

Total / Net New / Saved (`split`) is Apollo's: Saved = saved contacts,
Net New = everyone else in the result. `pick` is Apollo's bulk selection
("Select number of people", "Max people per company").

Qt-free and stdlib-only beyond prospector; the widget and the workbench build a
pool off the UI thread and filter it in memory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from prospector import filters as F
from prospector.identity import keys_of, norm_company, norm_text
from prospector.models import Lead

from addons.leads import accounts as AC
from addons.leads.imports import company_keys, domain_of

PAGE_SIZE = 25                      # Apollo's page
SORTS = ("relevance", "name", "newest", "company")
# Dossier.status of a display-only row (Person.row): someone found whom the
# qualify pass never reached.
UNQUALIFIED = "not_qualified"
# Rows "Qualify & draft" can (re)run: never qualified, or a qualify pass that
# failed — no Groq key, a Groq error, a reply that wasn't JSON (models.py).
RETRYABLE = frozenset({UNQUALIFIED, "no_model", "qualify_error", "non_json"})


@dataclass
class Person:
    lead: Lead
    dossier: object = None          # the newest qualified Dossier, if any
    draft: object = None           # that dossier's draft, if one was written
    saved: bool = False
    imports: tuple = ()             # Contact CSV import ids
    first_seen: str = ""            # ISO: the earliest save / run that had them
    last_seen: str = ""
    sessions: tuple = ()            # ids of the runs they appear in
    account: dict = field(default_factory=dict)   # their Account CSV import company
    # What the searches that found them were steered by: {facet: frozenset
    # of casefolded include values} for the STEERED facets (_steering).
    steered: dict = field(default_factory=dict)
    stage: str = ""                 # the saved contact's stage; "" when not saved
    lists: tuple = ()               # the lists the saved contact is on
    # Every identity key any record of theirs carries — the handle a
    # selection holds them by across pages and rebuilds (a rebuild makes new
    # Person objects; the keys stay).
    keys: frozenset = frozenset()
    saved_account: object = None    # their accounts.Account, set by a filter pass
    _row: object = field(default=None, repr=False, compare=False)

    def row(self):
        """What a table shows for this person: their qualified Dossier, or —
        never qualified — a display-only one (status UNQUALIFIED), made once
        so a page and a selection that spans pages hand the same object on."""
        if self.dossier is not None:
            return self.dossier
        if self._row is None:
            from prospector.models import Dossier
            self._row = Dossier(lead=self.lead, verdict="", generated_at="",
                                status=UNQUALIFIED, score=int(self.fit))
        return self._row

    @property
    def fit(self) -> float:
        """The triage fit — what the table's FIT column shows."""
        return float(getattr(self.lead, "fit_score", 0) or 0)

    @property
    def score(self) -> float:
        """The qualified dossier's score, 0 when never qualified."""
        value = getattr(self.dossier, "score", None)
        return float(value) if isinstance(value, (int, float)) else 0.0

    @property
    def qualified(self) -> bool:
        return self.dossier is not None


# ── deliverability ────────────────────────────────────────────────────────────

# key → the label the table's STATUS column shows (cockpit.status_of).
EMAIL_STATUS_LABEL = {
    "mailed": "Mailed", "no_email": "No email", "verified": "Verified",
    "invalid": "Invalid", "catch_all": "Catch-all", "unknown": "Unknown",
    # The key stays "guessed" (saved searches name it); the words do not.
    # Nothing is guessed since 24-Sep-2026 — an address here came from a
    # sheet, Apollo or a finder and has no verdict yet: Apollo's "Unverified".
    "guessed": "Unverified",
}


def email_status_of(lead, draft=None) -> str:
    """The deliverability KEY for a person — one rule for the STATUS column
    and the "Email status" filter. Someone already sent to is "mailed";
    otherwise the free verify verdict, or "guessed" (shown "Unverified") for
    an address no verifier has ruled on yet."""
    if draft is not None and getattr(draft, "status", "") == "sent":
        return "mailed"
    if not (getattr(lead, "email", "") or "").strip():
        return "no_email"
    check = (getattr(lead, "extra", None) or {}).get("email_check") or ""
    return {"valid": "verified", "invalid": "invalid",
            "catch-all": "catch_all", "unknown": "unknown"}.get(check, "guessed")


# ── building ──────────────────────────────────────────────────────────────────

# The includes a search can only STEER — they shape the query, and whoever
# comes back is taken (source._enforces): industries, keywords, and job
# titles while "similar titles" is on.
STEERED = ("industries", "keywords", "job_titles")


def _fold(value) -> str:
    return " ".join(str(value or "").split()).casefold()


def _steering(params) -> dict:
    """{facet: frozenset of casefolded values} — what one run's search was
    steered by, read from the params its session saved (a legacy run's
    industries and roles included). {} for a run that searched nothing (a
    sheet run) or whose params can't be read."""
    if not isinstance(params, dict):
        return {}
    try:
        spec = F.SearchSpec.from_params(params)
    except Exception:                                   # noqa: BLE001
        return {}
    out = {}
    for facet in STEERED:
        if facet == "job_titles" and not spec.similar_titles:
            continue        # enforced by the search itself: match_person read them
        values = frozenset(v for v in (_fold(x) for x in getattr(spec, facet).include) if v)
        if values:
            out[facet] = values
    return out


def _add_steering(person, steer: dict) -> None:
    for facet, values in steer.items():
        person.steered[facet] = person.steered.get(facet, frozenset()) | values


def build(contacts=(), runs=()) -> list:
    """The pool from saved contacts and past runs.

    `contacts` — contacts.Contact records. `runs` — (session_id, created_at,
    all_leads, dossiers[, drafts[, params]]) per run, in any order; `params`
    is what the run's session saved it was asked (its filters). A person's
    dossier is the one from their newest run that qualified them, and their
    draft the one written for that dossier."""
    people: list = []
    by_key: dict = {}

    def place(lead):
        keys = keys_of(lead)
        at = next((by_key[k] for k in keys if k in by_key), None)
        return keys, at

    def index(at, lead):
        keys = keys_of(lead)
        for key in keys:
            by_key.setdefault(key, at)
        people[at].keys = people[at].keys | frozenset(keys)

    for c in contacts or ():
        lead = getattr(c, "lead", None)
        if lead is None:
            continue
        keys, at = place(lead)
        if not keys:
            continue
        when = getattr(c, "saved_at", "") or ""
        lists = tuple(getattr(c, "lists", ()) or ())
        if at is None:
            people.append(Person(lead=lead, saved=True,
                                 imports=tuple(getattr(c, "imports", ()) or ()),
                                 first_seen=when, last_seen=when,
                                 stage=getattr(c, "stage", "") or "", lists=lists))
            at = len(people) - 1
        else:
            p = people[at]
            p.saved = True
            p.imports = tuple(dict.fromkeys(p.imports + tuple(getattr(c, "imports", ()) or ())))
            p.stage = p.stage or getattr(c, "stage", "") or ""
            p.lists = tuple(dict.fromkeys(p.lists + lists))
        index(at, lead)

    ordered = sorted(runs or (), key=lambda r: r[1] or "", reverse=True)
    for run in ordered:
        session_id, created_at, all_leads, dossiers = run[:4]
        drafts = run[4] if len(run) > 4 else ()
        steer = _steering(run[5] if len(run) > 5 else None)
        written = {id(getattr(dr, "dossier", None)): dr for dr in drafts or ()}
        qualified = {id(getattr(d, "lead", None)): d for d in dossiers or ()}
        leads = list(all_leads or ())
        # A dossier whose lead the run's list lacks still names a person.
        known = {id(x) for x in leads}
        leads += [d.lead for d in dossiers or ()
                  if getattr(d, "lead", None) is not None and id(d.lead) not in known]
        for lead in leads:
            keys, at = place(lead)
            if not keys:
                continue
            dossier = qualified.get(id(lead))
            draft = written.get(id(dossier)) if dossier is not None else None
            if at is None:
                people.append(Person(lead=lead, dossier=dossier, draft=draft,
                                     first_seen=created_at or "",
                                     last_seen=created_at or "",
                                     sessions=(session_id,)))
                at = len(people) - 1
            else:
                p = people[at]
                if p.dossier is None and dossier is not None:
                    p.dossier = dossier       # newest run first: keep the first
                    p.draft = draft
                if session_id not in p.sessions:
                    p.sessions = p.sessions + (session_id,)
                if created_at:
                    p.first_seen = min(x for x in (p.first_seen, created_at) if x)
                    p.last_seen = max(p.last_seen, created_at)
            if steer:
                _add_steering(people[at], steer)
            index(at, lead)
    return people


def without(people, removed_keys) -> list:
    """The pool minus everyone the owner took off the list (removed.py): a
    person sharing any identity key with a removed one — the rule that made
    them one person in build() — is left out of every tab."""
    removed_keys = frozenset(removed_keys or ())
    if not removed_keys:
        return list(people or ())
    return [p for p in people or () if p.keys.isdisjoint(removed_keys)]


# ── filtering ─────────────────────────────────────────────────────────────────

def _domains_of(lead) -> set:
    extra = getattr(lead, "extra", None) or {}
    out = set()
    addresses = [getattr(lead, "email", "")] + list(extra.get("other_emails") or ())
    for addr in addresses:
        d = domain_of(addr) if isinstance(addr, str) and "@" in addr else ""
        if d:
            out.add(d)
    site = domain_of(extra.get("website", ""))
    if site:
        out.add(site)
    return out


def _account_for(lead, accounts) -> dict:
    """The Account CSV import company this person works at, or {} — by name
    first, then by the domain of their e-mail or website. `accounts` is
    [(names, domains, {name/domain: company dict})]."""
    name = norm_company(getattr(lead, "company", ""))
    domains = _domains_of(lead)
    for names, doms, by in accounts:
        if name and name in names:
            return by.get(name, {})
        hit = next((d for d in domains if d in doms), None)
        if hit:
            return by.get(hit, {})
    return {}


def resolve_accounts(companies_by_import: dict) -> dict:
    """{import id: (names, domains, lookup)} from imports.companies_of(…) —
    built once per filter change, not once per person."""
    out = {}
    for import_id, companies in (companies_by_import or {}).items():
        names, domains = company_keys(companies)
        by = {}
        for c in companies:
            n = norm_company(c.get("name", ""))
            if n:
                by.setdefault(n, c)
            d = c.get("domain") or domain_of(c.get("website", ""))
            if d:
                by.setdefault(d, c)
        out[import_id] = (names, domains, by)
    return out


def _similar_title(title: str, include) -> bool:
    """A title matches a job-title include "or similar": it carries the
    include's significant words, or it reads as the same seniority AND the
    same function (whichever of the two the include names)."""
    words = set(F._tokens(title))
    t_sen, t_fun = F.seniority_of(title), F.function_of(title)
    for value in include:
        for alt in F._alternatives(value):
            if F._carries(words, alt):
                return True
            sen, fun = F.seniority_of(alt), F.function_of(alt)
            if (sen or fun) and (not sen or sen & t_sen) and (not fun or fun & t_fun):
                return True
    return False


def _industry_text(person: Person) -> str:
    lead = person.lead
    extra = getattr(lead, "extra", None) or {}
    parts = [getattr(lead, "industry", "") or "", str(extra.get("industry") or ""),
             person.account.get("industry", "")]
    return " · ".join(p for p in parts if p)


def _keyword_texts(person: Person) -> list:
    lead = person.lead
    extra = getattr(lead, "extra", None) or {}
    custom = extra.get("custom") if isinstance(extra.get("custom"), dict) else {}
    acc_custom = person.account.get("custom") if isinstance(person.account.get("custom"), dict) else {}
    return [getattr(lead, "title", "") or "", getattr(lead, "company", "") or "",
            _industry_text(person), " ".join(map(str, custom.values())),
            " ".join(map(str, acc_custom.values()))]


def _headcount(value):
    """A company size from a sheet cell — "500+", "51-200", "1,200" → a number
    inside the range (its lower bound), or None."""
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", str(value or ""))]
    return nums[0] if nums else None


def _custom_value(person: Person, scope: str, column: str) -> str:
    """One custom field's value for a person, folded: a "contact" column from
    the person's own imported columns, an "account" column from their saved
    account's, else their Account CSV import company's. "" when they have none."""
    fold = column.casefold()
    if scope == "contact":
        extra = getattr(person.lead, "extra", None) or {}
        sources = [extra.get("custom")]
    else:
        acc = person.saved_account
        sources = [getattr(acc, "custom", None), person.account.get("custom")]
    for source in sources:
        if isinstance(source, dict):
            for key, value in source.items():
                if str(key).strip().casefold() == fold and str(value or "").strip():
                    return _fold(value)
    return ""


def _names_pass(have, include: frozenset, exclude: frozenset) -> bool:
    """Apollo's "is any of" / "is none of" over names someone carries: one of
    the includes (when there are any) and none of the excludes."""
    if include and include.isdisjoint(have):
        return False
    return exclude.isdisjoint(have)


def _folded(values) -> frozenset:
    return frozenset(v for v in (_fold(x) for x in values or ()) if v)


# Public names for what companies.py shares: Apollo's "is any of" / "is none of".
folded = _folded
names_pass = _names_pass


def _facts(person: Person):
    """What is known about the person's company, in match_company's shape —
    from their Account CSV import record, else their own row. None when
    nothing is known (match_company then passes size filters as unverified
    and fails a Company HQ filter as unknown — its own rules)."""
    extra = getattr(person.lead, "extra", None) or {}
    acc = person.account
    size = _headcount(acc.get("headcount") or extra.get("headcount"))
    hq = acc.get("location", "")
    if size is None and not hq:
        return None
    return {"headcount": size, "revenue": None, "hq": hq, "description": ""}


class Matcher:
    """One filter pass: everything that depends only on the spec, worked out
    once — the loosened copy of the spec, the chosen imports, the query —
    then `test(person)` per person. A pool of thousands re-filters on every
    click, so nothing per-spec may be redone per person."""

    def __init__(self, spec, *, accounts=None, query: str = "", today=None,
                 saved_accounts=None):
        self.spec = spec
        self.today = today
        self.query = norm_text(query or "")
        self.contact_imports = frozenset(spec.contact_imports)
        self.accounts = [accounts[i] for i in spec.account_imports
                         if i in (accounts or {})]
        # The owner's own records: (include, exclude) name sets per facet,
        # folded; custom fields as [(scope, column, values)].
        self.records = {name: (_folded(spec.facet(name).include),
                               _folded(spec.facet(name).exclude))
                        for name in F.RECORD_FACETS if spec.facet(name).active}
        self.custom = []
        for key, values in spec.custom_fields.items():
            scope, column = F.split_custom_key(key)
            if scope:
                self.custom.append((scope, column, _folded(values)))
        # A person's saved account is looked up only when a filter reads it.
        self.saved_index = (saved_accounts if isinstance(saved_accounts, AC.Index)
                            else AC.Index(saved_accounts or ()))
        self.needs_account = bool(
            {"account_stages", "account_lists"} & set(self.records)
            or any(scope == "account" for scope, _c, _v in self.custom))
        self.titles = list(spec.job_titles.include) if spec.similar_titles else []
        self.local = spec
        if self.titles:
            self.local = spec.copy()
            self.local.job_titles.include = []      # checked in test(), loosely
        self.industries = list(spec.industries.include)
        self.keywords = list(spec.keywords.include)
        # The same three, folded the way _steering folds a run's: a person a
        # search steered by any one of them found passes that facet here.
        self.steer = {"industries": frozenset(_fold(v) for v in self.industries),
                      "keywords": frozenset(_fold(v) for v in self.keywords),
                      "job_titles": frozenset(_fold(v) for v in self.titles)}
        self.company_facts = F.needs_company_facts(spec)
        self.statuses = frozenset(spec.email_status)

    def _steered(self, person: Person, facet: str) -> bool:
        """A search steered by one of this facet's includes found them."""
        return bool(person.steered.get(facet, frozenset()) & self.steer[facet])

    def test(self, person: Person) -> bool:
        spec, lead = self.spec, person.lead
        if self.contact_imports and not self.contact_imports.intersection(person.imports):
            return False
        if spec.qualified_only and not person.qualified:
            return False
        if spec.min_fit and person.fit < spec.min_fit:
            return False
        if self.statuses and email_status_of(lead, person.draft) not in self.statuses:
            return False
        if spec.account_imports:
            person.account = _account_for(lead, self.accounts)
            if not person.account:
                return False
        else:
            person.account = {}
        if self.query:
            # What the cockpit's own search always read: name, company,
            # title, e-mail and where they are.
            extra = getattr(lead, "extra", None) or {}
            hay = norm_text(" ".join(str(x or "") for x in (
                getattr(lead, "name", ""), getattr(lead, "title", ""),
                getattr(lead, "company", ""), getattr(lead, "email", ""),
                extra.get("location", ""))))
            if self.query not in hay:
                return False
        if self.titles and not self._steered(person, "job_titles") \
                and not _similar_title(getattr(lead, "title", "") or "", self.titles):
            return False
        if F.match_person(self.local, lead, None, self.today):
            return False
        for facet, include, texts in (
                ("industries", self.industries, lambda: [_industry_text(person)]),
                ("keywords", self.keywords, lambda: _keyword_texts(person))):
            if include and not self._steered(person, facet):
                got = [t for t in texts() if t]
                if not got or not any(F._has_phrase(t, alt) for t in got
                                      for v in include for alt in F._alternatives(v)):
                    return False
        if self.company_facts and F.match_company(spec, lead, _facts(person)):
            return False
        return self._records_pass(person)

    def _records_pass(self, person: Person) -> bool:
        """Stage, Lists and Custom fields — see the module docstring."""
        if self.needs_account:
            person.saved_account = self.saved_index.match(person.lead)
        acc = person.saved_account if self.needs_account else None
        have = {
            "contact_stages": {_fold(person.stage)} if person.stage else set(),
            "account_stages": {_fold(acc.stage)} if acc is not None and acc.stage else set(),
            "contact_lists": {_fold(x) for x in person.lists},
            "account_lists": {_fold(x) for x in getattr(acc, "lists", ()) or ()},
        }
        for name, (include, exclude) in self.records.items():
            if not _names_pass(have[name], include, exclude):
                return False
        for scope, column, values in self.custom:
            if _custom_value(person, scope, column) not in values:
                return False
        return True


def matches(person: Person, spec, *, accounts=None, query: str = "",
            today=None, saved_accounts=None) -> bool:
    """Whether one person passes the whole spec — see the module docstring.
    `accounts` is resolve_accounts(...) for spec.account_imports;
    `saved_accounts` the saved accounts (accounts.list_accounts, or an
    accounts.Index of them). For many people, build one Matcher instead
    (filter_people does)."""
    return Matcher(spec, accounts=accounts, query=query, today=today,
                   saved_accounts=saved_accounts).test(person)


def filter_people(people, spec, *, accounts=None, query: str = "", today=None,
                  saved_accounts=None) -> list:
    m = Matcher(spec, accounts=accounts, query=query, today=today,
                saved_accounts=saved_accounts)
    return [p for p in people or () if m.test(p)]


# ── what the owner's own records offer the filters ────────────────────────────

def record_options(people, saved_accounts=()) -> dict:
    """What Stage, Lists and Custom fields can offer, from the records there
    are: {"contact_stages", "account_stages", "contact_lists",
    "account_lists": [names], "custom": {"contact" | "account": {column:
    [values, most used first]}}}. Apollo's own stages come first in their
    order, then any other stage a sheet brought in."""
    from addons.leads import contacts as CT

    def ordered(defaults, seen):
        extra = sorted({s for s in seen if s and s not in defaults}, key=str.casefold)
        return list(defaults) + extra

    stages, lists = set(), {}
    custom = {"contact": {}, "account": {}}

    def count(scope, source):
        if not isinstance(source, dict):
            return
        for column, value in source.items():
            column, value = " ".join(str(column).split()), " ".join(str(value or "").split())
            if column and value:
                tally = custom[scope].setdefault(column, {})
                tally[value] = tally.get(value, 0) + 1

    for p in people or ():
        if p.saved:
            stages.add(p.stage)
            for name in p.lists:
                lists.setdefault(name.casefold(), name)
        count("contact", (getattr(p.lead, "extra", None) or {}).get("custom"))
    acc_stages, acc_lists = set(), {}
    for account in saved_accounts or ():
        acc_stages.add(account.stage)
        for name in account.lists:
            acc_lists.setdefault(name.casefold(), name)
        count("account", account.custom)
    return {
        "contact_stages": ordered(CT.STAGES, stages),
        "account_stages": ordered(AC.STAGES, acc_stages),
        "contact_lists": sorted(lists.values(), key=str.casefold),
        "account_lists": sorted(acc_lists.values(), key=str.casefold),
        "custom": {scope: {column: [v for v, _n in sorted(tally.items(),
                                                           key=lambda kv: (-kv[1], kv[0].casefold()))]
                           for column, tally in sorted(columns.items(),
                                                       key=lambda kv: kv[0].casefold())}
                   for scope, columns in custom.items()},
    }


def split(people) -> dict:
    """Apollo's three tabs: {"total", "net_new", "saved"}."""
    people = list(people or ())
    return {"total": people,
            "net_new": [p for p in people if not p.saved],
            "saved": [p for p in people if p.saved]}


def sort_people(people, how: str = "relevance") -> list:
    """relevance — best fit first (the triage fit the FIT column shows, then
    a qualified score), newest first among equals; name / company — A–Z;
    newest — most recently found or saved first."""
    people = list(people or ())
    if how == "name":
        return sorted(people, key=lambda p: norm_text(getattr(p.lead, "name", "")) or "~")
    if how == "company":
        return sorted(people, key=lambda p: (norm_company(getattr(p.lead, "company", "")) or "~",
                                             norm_text(getattr(p.lead, "name", ""))))
    if how == "newest":
        return sorted(people, key=lambda p: p.last_seen, reverse=True)
    return sorted(people, key=lambda p: (p.fit, p.score, p.last_seen), reverse=True)


def _company_of(person: Person) -> str:
    """Which company a person counts against for "Max people per company":
    their company's name once legal words are dropped, else the domain of
    their company's website or e-mail — "" when they give neither (a company
    of one)."""
    lead = person.lead
    name = norm_company(getattr(lead, "company", ""))
    if name:
        return "n:" + name
    extra = getattr(lead, "extra", None) or {}
    for source in (extra.get("website", ""), getattr(lead, "email", "")):
        domain = AC.company_domain(source)
        if domain:
            return "d:" + domain
    return ""


def colleagues(people, person, limit: int = 0) -> list:
    """Everyone else Prism holds at the same company as `person` (by name, or
    by domain where there is no name — _company_of's rule): saved contacts
    first, then the best fit. Apollo's "existing contacts at the company"
    beside new prospects there. `limit` 0 is all of them."""
    company = _company_of(person) if person is not None else ""
    if not company:
        return []
    mine = set(getattr(person, "keys", ()) or ())
    found = [p for p in people or () if p is not person
             and not (mine and mine & set(p.keys)) and _company_of(p) == company]
    found.sort(key=lambda p: (not p.saved, -p.fit, norm_text(getattr(p.lead, "name", ""))))
    return found[:limit] if limit else found


def pick(people, n: int = 0, per_company: int = 0) -> list:
    """Apollo's bulk selection over a result, in its order (knowledge.apollo.io
    "Search for People"): "Select number of people lets you specify how many
    people to select" — the first `n` (0: everyone) — and "Max people per
    company limits how many people Apollo selects from any single company"
    (0: no limit); a person passed over for their company's limit does not
    count towards `n`."""
    out, taken = [], {}
    n, per_company = max(0, int(n or 0)), max(0, int(per_company or 0))
    for person in people or ():
        if n and len(out) >= n:
            break
        if per_company:
            company = _company_of(person)
            if company:
                if taken.get(company, 0) >= per_company:
                    continue
                taken[company] = taken.get(company, 0) + 1
        out.append(person)
    return out


def page(people, index: int, size: int = PAGE_SIZE) -> dict:
    """One page: {"rows", "page" (0-based, clamped), "pages", "start", "end",
    "total"} — start/end 1-based for "1 - 25 of 312", 0 and 0 when empty."""
    people = list(people or ())
    total = len(people)
    pages = max(1, -(-total // size))
    index = min(max(0, int(index)), pages - 1)
    lo = index * size
    rows = people[lo:lo + size]
    return {"rows": rows, "page": index, "pages": pages,
            "start": lo + 1 if rows else 0, "end": lo + len(rows), "total": total}
