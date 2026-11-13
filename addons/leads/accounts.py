"""
Leads & Outreach — saved accounts (Apollo's companies you keep)
───────────────────────────────────────────────────────────────
Apollo keeps ACCOUNTS — companies — beside its contacts: an Account CSV import
creates them, a contacts import can "Assign/create account based on
Website/Email Domain in the CSV", and a person's panel shows the account they
work at, with its stage. Prism kept companies only on the account-import record
(imports.py, which still drives the Account CSV import filter and the paid
search's batches); this is the store the person panel — and the Companies page
after it — reads.

One file, accounts.json, in a folder the caller names. An account:

    name, domain, website, location, industry, headcount, revenue, phone,
    linkedin, description      what is known about the company
    custom                     the sheet's own columns, kept verbatim
    stage                      Apollo's account stages (STAGES), "Cold" to start
    saved_at, updated_at       first saved; last changed
    via                        "import", "contact", "save", "enrich"
    imports                    the Account CSV imports that brought it in
    lists                      the lists it was added to
    notes                      [{"at", "text"}], newest last — the company
                               profile's Notes
    tasks                      [{"id", "at", "text", "due", "done"}] — its Tasks
    history                    [{"at", "kind", "text"}], newest last — its
                               Activities (Apollo: "a log of all interactions
                               between your organization and the account"):
                               what Prism saw happen ("saved" — how, "stage",
                               "list", "edited", "enriched", "flagged") and
                               what the owner logged by hand (LOGGED)

One company, one account: the same web domain, or — where either side has no
domain — the same name once legal words are dropped (prospector.identity.
norm_company: "Acme Pvt. Ltd." is "Acme"). A free-mail domain (gmail.com …) is
nobody's company and never makes or matches an account.

Rules this module keeps (store.py): Qt-free and path-free; readers forgive,
writers refuse; atomic writes under one module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, fields
from datetime import datetime

from prospector.identity import norm_company

from addons.leads import store
from addons.leads.imports import domain_of

SCHEMA = 1
FILE = "accounts.json"
_KEY = "accounts"
_WHAT = "your saved accounts"
VIA = ("import", "contact", "save", "enrich")
# Apollo's default account stages, in its order (knowledge.apollo.io, "Contact
# and Account Stages Overview", read 23-Sep-2026). A stage an imported sheet
# names that is not one of these is kept as written (stage_named).
STAGES = ("Cold", "Current Client", "Active Opportunity", "Dead Opportunity",
          "Do Not Prospect")
DEFAULT_STAGE = "Cold"
# Mailboxes anyone can open: an address there says nothing about an employer.
FREE_MAIL = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.in",
    "ymail.com", "hotmail.com", "outlook.com", "live.com", "msn.com",
    "icloud.com", "me.com", "aol.com", "rediffmail.com", "protonmail.com",
    "proton.me", "zoho.com", "gmx.com", "mail.com", "yandex.com",
})
_TEXT_FIELDS = ("name", "domain", "website", "location", "industry", "headcount",
                "revenue", "phone", "linkedin", "description")
_NOTE_MAX = 20000                   # characters: a note, not a document
# What the owner can log by hand (Apollo's "Log activity"), in its menu's order.
LOGGED = ("call", "meeting", "email", "message", "other")
HISTORY_KINDS = ("saved", "stage", "list", "edited", "enriched", "flagged") + LOGGED
_HISTORY_MAX = 500                  # entries kept per account, newest
# What "Edit company info" may change (a blank value clears all but the name).
EDITABLE = ("name", "website", "location", "industry", "headcount", "revenue",
            "phone", "linkedin", "description")

_LOCK = threading.RLock()

StoreError = store.StoreError


@dataclass
class Account:
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
    stage: str = DEFAULT_STAGE
    saved_at: str = ""
    updated_at: str = ""
    via: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    lists: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    history: list = field(default_factory=list)

    def keys(self) -> set:
        return company_keys(self.name, self.domain or self.website)


_ACCOUNT_FIELDS = tuple(f.name for f in fields(Account))


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _text(value) -> str:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value = f"{value:g}"
    return " ".join(value.split()) if isinstance(value, str) else ""


def _strings(value) -> list:
    out = []
    for item in value if isinstance(value, list) else ():
        if isinstance(item, str) and item.strip() and item.strip() not in out:
            out.append(item.strip())
    return out


def _notes(value) -> list:
    out = []
    for item in value if isinstance(value, list) else ():
        if (isinstance(item, dict) and isinstance(item.get("text"), str)
                and item["text"].strip()):
            out.append({"at": item.get("at") if isinstance(item.get("at"), str) else "",
                        "text": item["text"][:_NOTE_MAX]})
    return out


def _tasks(value) -> list:
    out, seen = [], set()
    for item in value if isinstance(value, list) else ():
        if not (isinstance(item, dict) and isinstance(item.get("text"), str)
                and item["text"].strip()):
            continue
        task_id = item.get("id") if isinstance(item.get("id"), str) else ""
        n = len(out) + 1
        while not task_id or task_id in seen:      # a hand-edited file: any stable id
            task_id, n = f"t{n}", n + 1
        seen.add(task_id)
        out.append({"id": task_id,
                    "at": item.get("at") if isinstance(item.get("at"), str) else "",
                    "text": item["text"][:_NOTE_MAX],
                    "due": item.get("due") if isinstance(item.get("due"), str) else "",
                    "done": item.get("done") is True})
    return out


def _history(value) -> list:
    out = []
    for item in value if isinstance(value, list) else ():
        if (isinstance(item, dict) and item.get("kind") in HISTORY_KINDS
                and isinstance(item.get("text", ""), str)):
            out.append({"at": item.get("at") if isinstance(item.get("at"), str) else "",
                        "kind": item["kind"], "text": item.get("text", "")[:_NOTE_MAX]})
    return out[-_HISTORY_MAX:]


def _record(account: "Account", kind: str, text: str = "", at: str = "") -> None:
    """One more line in an account's Activities."""
    account.history.append({"at": at or _now(), "kind": kind, "text": str(text or "")})
    del account.history[:-_HISTORY_MAX]


def stage_named(text) -> str:
    """One of STAGES matched without regard to case or spacing, else the text
    itself tidied, else ""."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for known in STAGES:
        if known.casefold() == cleaned.casefold():
            return known
    return cleaned[:60]


def company_domain(website_or_email) -> str:
    """The web domain a website or an e-mail address points at — "" for none,
    and "" for a free-mail provider, which is nobody's company."""
    host = domain_of(website_or_email)
    return "" if host in FREE_MAIL else host


def company_keys(name, website="") -> set:
    """{"d:<domain>", "n:<name>"} — what one company is known by."""
    out = set()
    domain = company_domain(website)
    if domain:
        out.add("d:" + domain)
    n = norm_company(name)
    if n:
        out.add("n:" + n)
    return out


def _account(item):
    """A stored row or an incoming company dict → Account, or None when it
    names no company at all."""
    if not isinstance(item, dict):
        return None
    values = {k: _text(item.get(k)) for k in _TEXT_FIELDS}
    if not values["domain"]:
        values["domain"] = company_domain(values["website"])
    else:
        values["domain"] = company_domain(values["domain"])
    if not (values["name"] or values["domain"]):
        return None
    custom = item.get("custom")
    custom = ({str(k).strip(): _text(v) for k, v in custom.items()
               if str(k).strip() and _text(v)} if isinstance(custom, dict) else {})
    return Account(
        **values, custom=custom,
        stage=stage_named(item.get("stage")) or DEFAULT_STAGE,
        saved_at=item.get("saved_at") if isinstance(item.get("saved_at"), str) else "",
        updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else "",
        via=[v for v in _strings(item.get("via")) if v in VIA],
        imports=_strings(item.get("imports")), lists=_strings(item.get("lists")),
        notes=_notes(item.get("notes")), tasks=_tasks(item.get("tasks")),
        history=_history(item.get("history")))


def _copy(value):
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return [dict(x) if isinstance(x, dict) else x for x in value]
    return value


def _row(account: Account) -> dict:
    return {name: _copy(getattr(account, name)) for name in _ACCOUNT_FIELDS}


def _read_accounts(items) -> list:
    return [a for a in (_account(item) for item in items) if a is not None]


# ── reading ───────────────────────────────────────────────────────────────────

def list_accounts(folder) -> list:
    """Every saved account, most recently saved first. Never raises: a
    missing, damaged or newer file lists nothing."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        accounts = _read_accounts(items)
    except Exception:                                   # noqa: BLE001
        return []
    accounts.sort(key=lambda a: a.saved_at, reverse=True)
    return accounts


class Index:
    """Saved accounts, looked up by person many times over: the People page
    asks once per person on every filter change, so each account's keys are
    worked out once here, not on every ask. `match` is match()'s rule."""

    def __init__(self, accounts=()):
        self.accounts = list(accounts or ())
        self._by_domain: dict = {}
        self._by_name: dict = {}
        for account in self.accounts:
            for key in account.keys():
                into = self._by_domain if key.startswith("d:") else self._by_name
                into.setdefault(key, account)

    def match(self, lead):
        if lead is None:
            return None
        extra = getattr(lead, "extra", None) or {}
        for source in (getattr(lead, "email", ""), extra.get("website", "")):
            domain = company_domain(source)
            if domain and "d:" + domain in self._by_domain:
                return self._by_domain["d:" + domain]
        name = norm_company(getattr(lead, "company", ""))
        return self._by_name.get("n:" + name) if name else None


def match(accounts, lead):
    """The saved account a person works at — by the domain of their e-mail or
    their company's website first, then by their company's name — or None.
    For many people, build one Index and ask it."""
    return Index(accounts).match(lead)


def from_lead(lead, by: str = "domain") -> dict | None:
    """The company a person works at, as a company dict to save — Apollo's
    contact-import "Assign/create account". `by` "domain" needs a website or
    a company e-mail domain (the name rides along); "name" needs only the
    company's name. None when the person gives nothing to go on."""
    extra = getattr(lead, "extra", None) or {}
    name = _text(getattr(lead, "company", ""))
    website = _text(extra.get("website", ""))
    domain = company_domain(website) or company_domain(getattr(lead, "email", ""))
    if by == "domain" and not domain:
        return None
    if by == "name" and not name:
        return None
    return {"name": name, "website": website or domain, "domain": domain,
            "industry": _text(getattr(lead, "industry", "")),
            "headcount": _text(extra.get("headcount", ""))}


# ── writing ───────────────────────────────────────────────────────────────────

def _merge(saved: Account, incoming: Account) -> bool:
    """Write incoming's non-empty fields over saved's — "Update the existing
    record with information from CSV"."""
    changed = False
    for name in _TEXT_FIELDS:
        value = getattr(incoming, name)
        if value and value != getattr(saved, name):
            setattr(saved, name, value)
            changed = True
    for key, value in incoming.custom.items():
        if value and saved.custom.get(key) != value:
            saved.custom[key] = value
            changed = True
    return changed


def save(folder, companies, *, via: str, import_id: str = "", update: bool = False,
         stage_of=None, list_name: str = "") -> dict:
    """Save companies as accounts; return {"added", "updated", "tagged"}.

    A company that is already an account (same domain, or same name where a
    domain is missing) gets `via` and `import_id` added; with `update` its
    non-empty fields are written over the saved ones — and a stage from
    `stage_of(company)` taken — too. A new account takes `stage_of(company)`
    or DEFAULT_STAGE. Raises StoreError when the file cannot be written."""
    if via not in VIA:
        raise ValueError(f"unknown via {via!r}")
    doing = "Couldn't save these accounts"
    added = updated = tagged = 0
    list_name = " ".join(str(list_name or "").split())
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        accounts = _read_accounts(items)
        by_key = {}
        for i, account in enumerate(accounts):
            for key in account.keys():
                by_key.setdefault(key, i)
        now = _now()
        for company in companies or ():
            incoming = _account(company)
            if incoming is None:
                continue
            keys = incoming.keys()
            stage = stage_named(stage_of(company)) if stage_of is not None else ""
            domain_keys = {k for k in keys if k.startswith("d:")}
            at = next((by_key[k] for k in domain_keys if k in by_key), None)
            if at is None:
                # By name only when one side has no domain: two companies with
                # different websites are two companies, whatever they are called.
                for k in keys - domain_keys:
                    hit = by_key.get(k)
                    if hit is not None and (not domain_keys or not accounts[hit].domain):
                        at = hit
                        break
            if at is None:
                incoming.stage = stage or DEFAULT_STAGE
                incoming.saved_at = incoming.updated_at = now
                incoming.via = [via]
                incoming.imports = [import_id] if import_id else []
                incoming.lists = [list_name] if list_name else []
                _record(incoming, "saved", via, now)
                if list_name:
                    _record(incoming, "list", list_name, now)
                accounts.append(incoming)
                at = len(accounts) - 1
                added += 1
            else:
                account = accounts[at]
                changed = update and _merge(account, incoming)
                if via not in account.via:
                    account.via.append(via)
                    changed = True
                if import_id and import_id not in account.imports:
                    account.imports.append(import_id)
                    changed = True
                if update and stage and stage != account.stage:
                    _record(account, "stage", f"{account.stage} → {stage}", now)
                    account.stage = stage
                    changed = True
                if list_name and list_name not in account.lists:
                    account.lists.append(list_name)
                    _record(account, "list", list_name, now)
                    changed = True
                if changed:
                    account.updated_at = now
                    if update:
                        updated += 1
                    else:
                        tagged += 1
            for key in accounts[at].keys() | keys:
                by_key.setdefault(key, at)
        store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                     [_row(a) for a in accounts])
    return {"added": added, "updated": updated, "tagged": tagged}


def set_stage(folder, account: Account, stage: str) -> bool:
    """Move a saved account to another stage. False when there is no such
    account or it is already there. Raises StoreError on a failed write."""
    stage = stage_named(stage)
    keys = account.keys() if isinstance(account, Account) else set()
    if not (stage and keys):
        return False
    doing = "Couldn't change this account's stage"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        accounts = _read_accounts(items)
        for saved in accounts:
            if saved.keys() & keys:
                if saved.stage == stage:
                    return False
                saved.updated_at = _now()
                _record(saved, "stage", f"{saved.stage} → {stage}", saved.updated_at)
                saved.stage = stage
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             [_row(a) for a in accounts])
                return True
    return False


# ── the profile's own writes (Apollo's account page) ─────────────────────────

def _keys_of(accounts) -> set:
    """Every key the given accounts (or company dicts) are known by."""
    out = set()
    for item in accounts or ():
        if isinstance(item, Account):
            out |= item.keys()
        elif isinstance(item, dict):
            made = _account(item)
            if made is not None:
                out |= made.keys()
    return out


def _change(folder, account, doing: str, change) -> bool:
    """Apply `change(saved) -> bool` to the saved account this is and write it;
    False when it is not saved (or nothing changed). Raises StoreError when the
    file cannot be written."""
    keys = _keys_of([account])
    if not keys:
        return False
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        accounts = _read_accounts(items)
        for saved in accounts:
            if saved.keys() & keys:
                if not change(saved):
                    return False
                saved.updated_at = _now()
                store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                             [_row(a) for a in accounts])
                return True
    return False


def get(folder, account) -> "Account | None":
    """The saved account as the file has it now, or None."""
    keys = _keys_of([account])
    if not keys:
        return None
    for saved in list_accounts(folder):
        if saved.keys() & keys:
            return saved
    return None


def add_note(folder, account, text: str) -> dict | None:
    """Keep a note on a saved account; the note ({"at", "text"}) or None when
    there is nothing to keep or no such account."""
    text = str(text or "").strip()[:_NOTE_MAX]
    if not text:
        return None
    note = {"at": _now(), "text": text}

    def change(saved):
        saved.notes.append(dict(note))
        return True
    return note if _change(folder, account, "Couldn't keep this note", change) else None


def add_task(folder, account, text: str, due: str = "") -> dict | None:
    """A to-do on a saved account ({"id", "at", "text", "due", "done"}), or
    None when there is nothing to keep or no such account. `due` is an ISO
    date ("2026-09-30") or ""."""
    text = str(text or "").strip()[:_NOTE_MAX]
    if not text:
        return None
    due = str(due or "").strip()[:10]
    task = {"id": "", "at": _now(), "text": text, "due": due, "done": False}

    def change(saved):
        taken = {t["id"] for t in saved.tasks}
        n = len(saved.tasks) + 1
        while f"t{n}" in taken:
            n += 1
        task["id"] = f"t{n}"
        saved.tasks.append(dict(task))
        return True
    return task if _change(folder, account, "Couldn't keep this task", change) else None


def set_task_done(folder, account, task_id: str, done: bool = True) -> bool:
    """Tick an account's task off (or back on)."""
    def change(saved):
        for task in saved.tasks:
            if task["id"] == task_id and task["done"] != bool(done):
                task["done"] = bool(done)
                return True
        return False
    return _change(folder, account, "Couldn't update this task", change)


def log(folder, account, kind: str, text: str = "") -> dict | None:
    """Apollo's "Log activity": a call, a meeting, an e-mail or message sent
    outside Prism, or anything else, with what the owner wrote — or "flagged"
    (the data is wrong). The entry, or None when `kind` is not one of those or
    the company is not an account."""
    if kind not in LOGGED + ("flagged",):
        return None
    entry = {"at": _now(), "kind": kind, "text": str(text or "").strip()[:_NOTE_MAX]}

    def change(saved):
        _record(saved, kind, entry["text"], entry["at"])
        return True
    return entry if _change(folder, account, "Couldn't log this activity", change) else None


def edit(folder, account, changes: dict) -> bool:
    """Apollo's "Actions > Edit company info": write the given fields (EDITABLE)
    over a saved account; a blank value clears every field but the name.
    Returns whether anything changed. The website's domain follows it."""
    changes = {k: " ".join(str(v or "").split()) for k, v in (changes or {}).items()
               if k in EDITABLE}
    if not changes:
        return False

    def change(saved):
        edited = []
        for key, value in changes.items():
            if key == "name" and not value:
                continue
            if getattr(saved, key) != value:
                setattr(saved, key, value)
                edited.append(key)
                if key == "website":
                    saved.domain = company_domain(value) or saved.domain
        if edited:
            _record(saved, "edited", ", ".join(edited))
        return bool(edited)
    return _change(folder, account, "Couldn't save these changes", change)


def set_stage_many(folder, accounts, stage: str) -> int:
    """Apollo's bulk "Edit > Set stage": every saved account among `accounts`
    moves to `stage`. Returns how many changed."""
    stage = stage_named(stage)
    wanted = _keys_of(accounts)
    if not (wanted and stage):
        return 0
    doing = "Couldn't set these accounts' stage"
    moved = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        saved = _read_accounts(items)
        now = _now()
        for account in saved:
            if account.stage != stage and account.keys() & wanted:
                _record(account, "stage", f"{account.stage} → {stage}", now)
                account.stage = stage
                account.updated_at = now
                moved += 1
        if moved:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(a) for a in saved])
    return moved


def add_to_list(folder, accounts, list_name: str) -> int:
    """Apollo's bulk "List": every saved account among `accounts` joins the
    named list. Returns how many were added."""
    list_name = " ".join(str(list_name or "").split())
    wanted = _keys_of(accounts)
    if not (wanted and list_name):
        return 0
    doing = "Couldn't add these accounts to the list"
    added = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        saved = _read_accounts(items)
        now = _now()
        for account in saved:
            if list_name not in account.lists and account.keys() & wanted:
                account.lists.append(list_name)
                _record(account, "list", list_name, now)
                account.updated_at = now
                added += 1
        if added:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(a) for a in saved])
    return added


def note_enriched(folder, accounts, what: str = "") -> int:
    """A company lookup filled in these accounts: one "enriched" line each,
    in one write. Returns how many were noted."""
    wanted = _keys_of(accounts)
    if not wanted:
        return 0
    doing = "Couldn't note the lookup"
    noted = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        saved = _read_accounts(items)
        now = _now()
        for account in saved:
            if account.keys() & wanted:
                _record(account, "enriched", what, now)
                noted += 1
        if noted:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(a) for a in saved])
    return noted


def remove(folder, accounts) -> int:
    """Apollo's "Actions > Delete account": the accounts these are (by any
    shared key) are deleted; return how many. Raises StoreError when the file
    cannot be written."""
    wanted = _keys_of(accounts)
    if not wanted:
        return 0
    doing = "Couldn't delete these accounts"
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        saved = _read_accounts(items)
        kept = [a for a in saved if not (a.keys() & wanted)]
        gone = len(saved) - len(kept)
        if gone:
            store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state,
                         [_row(a) for a in kept])
    return gone
