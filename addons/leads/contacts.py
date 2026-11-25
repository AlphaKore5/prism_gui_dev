"""
Leads & Outreach — saved contacts (Apollo's "Saved")
────────────────────────────────────────────────────
Apollo's Find People splits every result three ways — Total, Net New, Saved —
and Saved is a real store, not a filter: the people you import from a CSV,
save, export or put in a sequence become CONTACTS in your workspace, and "Net
New" is everyone a search turns up who is not one yet. (Apollo's own words:
"Adding prospects to a sequence saves them as contacts"; "When you export
prospects, Apollo also saves them as contacts in your account".) Prism had no
such store — sessions remember what a run pulled, lists are files you export —
so this is it.

One file, contacts.json, in a folder the caller names. A contact is a Lead,
written exactly as a session writes one (sessions.lead_to_row), plus how it
got here:

    saved_at    when it was first saved (kept on every later save)
    updated_at  when a save last changed it
    via         how, in the order it happened: "import", "save", "export",
                "sequence", "list", "email"
    imports     ids of the Contact CSV imports that brought it in — what the
                "Contact CSV import" filter reads (see imports.py)
    stage       where the person is with you — Apollo's contact stages
                (STAGES, knowledge.apollo.io "Contact and Account Stages
                Overview"): "Cold" until someone says otherwise; sending
                them a message moves Cold to "Approaching" (advance_stage)
    lists       the names of the lists they were added to
    notes       [{"at", "text"}], newest last — the person panel's Notes
    tasks       [{"id", "at", "text", "due", "done"}] — the panel's Tasks
    history     [{"at", "kind", "text"}], newest last — the panel's Activities
                (Apollo: "a log of all interactions between your organization
                and the contact"), what Prism saw happen: "saved" (how —
                a VIA), "stage" ("Cold → Approaching"), "list" (added to),
                "sent" (an e-mail's subject), "edited" (which fields),
                "flagged" (as inaccurate), and "call" / "meeting" / "email" /
                "message" / "other" — an activity the owner logged by hand
                (LOGGED), with what they wrote

One person, one contact: a lead whose identity keys (prospector.identity —
e-mail, profile link, Apollo id, name + company) touch a saved contact's is
THAT contact, tagged again rather than saved twice. Apollo's import setting
"If contacts already exist" is `update`: True writes the incoming non-empty
fields over the saved ones ("Update the existing record"); False leaves the
record as it is and only adds the tag.

Rules this module keeps — the ones sessions.py and saved_searches.py keep, via
store.py: Qt-free and path-free; readers forgive, writers refuse; writes are
atomic, every read-modify-write holds the module lock; a damaged file is set
aside, a newer one is never written over.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime

from prospector.identity import keys_of
from prospector.models import Lead

from addons.leads import store
from addons.leads.sessions import lead_from_row, lead_to_row

SCHEMA = 1
FILE = "contacts.json"
_KEY = "contacts"
_WHAT = "your saved contacts"
VIA = ("import", "save", "export", "sequence", "list", "email", "phone", "buyers")
# Apollo's default contact stages, in its order. A stage from an imported
# sheet that is not one of these is kept as written (see stage_named).
STAGES = ("Cold", "Approaching", "Replied", "Interested", "Not Interested",
          "Unresponsive", "Do Not Contact", "Bad Data", "Changed Job")
DEFAULT_STAGE = "Cold"
_NOTE_MAX = 20000                   # characters: a note, not a document
# What the owner can log by hand (Apollo's "Log activity"), in its menu's order.
LOGGED = ("call", "meeting", "email", "message", "other")
HISTORY_KINDS = ("saved", "stage", "list", "sent", "edited", "flagged") + LOGGED
_HISTORY_MAX = 500                  # entries kept per contact, newest

_LOCK = threading.RLock()

StoreError = store.StoreError


@dataclass
class Contact:
    lead: Lead
    saved_at: str = ""
    updated_at: str = ""
    via: list = field(default_factory=list)
    imports: list = field(default_factory=list)
    stage: str = DEFAULT_STAGE
    lists: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    tasks: list = field(default_factory=list)
    history: list = field(default_factory=list)


def stage_named(text) -> str:
    """A stage as written anywhere (a sheet's "stage" column, a hand edit):
    one of STAGES matched without regard to case or spacing, else the text
    itself tidied, else "" for nothing at all."""
    cleaned = " ".join(str(text or "").split())
    if not cleaned:
        return ""
    for known in STAGES:
        if known.casefold() == cleaned.casefold():
            return known
    return cleaned[:60]


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


def _record(contact, kind: str, text: str = "", at: str = "") -> None:
    """One more line in a contact's Activities."""
    contact.history.append({"at": at or _now(), "kind": kind, "text": str(text or "")})
    del contact.history[:-_HISTORY_MAX]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _commit(folder, doing: str, state, rows) -> None:
    """Every write here: the file, and get()'s kept copy dropped — a write
    inside the file clock's own resolution can leave its time unchanged."""
    store.commit(folder, FILE, _KEY, SCHEMA, doing, _WHAT, state, rows)
    _READ_CACHE.pop(folder, None)


def _strings(value) -> list:
    """A list of distinct non-empty strings, in order; anything else → []."""
    out = []
    for item in value if isinstance(value, list) else ():
        if isinstance(item, str) and item.strip() and item not in out:
            out.append(item.strip())
    return out


def _contact(item):
    """A stored row → Contact, or None for a row that holds no person."""
    if not isinstance(item, dict):
        return None
    lead = lead_from_row(item.get("lead"))
    if lead is None or not keys_of(lead):
        return None
    return Contact(
        lead=lead,
        saved_at=item.get("saved_at") if isinstance(item.get("saved_at"), str) else "",
        updated_at=item.get("updated_at") if isinstance(item.get("updated_at"), str) else "",
        via=[v for v in _strings(item.get("via")) if v in VIA],
        imports=_strings(item.get("imports")),
        stage=stage_named(item.get("stage")) or DEFAULT_STAGE,
        lists=_strings(item.get("lists")),
        notes=_notes(item.get("notes")),
        tasks=_tasks(item.get("tasks")),
        history=_history(item.get("history")))


def _row(contact: Contact) -> dict:
    return {"lead": lead_to_row(contact.lead), "saved_at": contact.saved_at,
            "updated_at": contact.updated_at, "via": list(contact.via),
            "imports": list(contact.imports), "stage": contact.stage,
            "lists": list(contact.lists), "notes": [dict(n) for n in contact.notes],
            "tasks": [dict(t) for t in contact.tasks],
            "history": [dict(h) for h in contact.history]}


def _read_contacts(items) -> list:
    return [c for c in (_contact(item) for item in items) if c is not None]


# ── reading ───────────────────────────────────────────────────────────────────

def list_contacts(folder) -> list:
    """Every saved contact, most recently saved first. Never raises: a missing,
    damaged or newer file lists nothing."""
    try:
        with _LOCK:
            _state, items, _reason = store.read(folder, FILE, _KEY, SCHEMA)
        contacts = _read_contacts(items)
    except Exception:                                   # noqa: BLE001
        return []
    contacts.sort(key=lambda c: c.saved_at, reverse=True)
    return contacts


def saved_keys(folder) -> frozenset:
    """Every identity key of every saved contact — what splits a result into
    Net New and Saved (see pool.py). Never raises."""
    keys = set()
    for contact in list_contacts(folder):
        keys.update(keys_of(contact.lead))
    return frozenset(keys)


# ── writing ───────────────────────────────────────────────────────────────────

def merge(saved: Lead, incoming: Lead) -> bool:
    """Write incoming's non-empty fields over saved's — Apollo's "Update the
    existing record". Returns whether anything changed. `extra` merges key by
    key; the fit/triage fields are left alone (they describe a run, not the
    person)."""
    changed = False
    for name in ("name", "title", "company", "email", "phone", "industry"):
        value = getattr(incoming, name, "") or ""
        if isinstance(value, str) and value.strip() and value != getattr(saved, name):
            setattr(saved, name, value)
            changed = True
    for key, value in (incoming.extra or {}).items():
        if key == "stage":
            continue                    # the contact's own field (Contact.stage)
        if value not in (None, "", [], {}) and saved.extra.get(key) != value:
            saved.extra[key] = value
            changed = True
    return changed


def save(folder, leads, *, via: str, import_id: str = "", update: bool = False,
         stage_of=None, list_name: str = "") -> dict:
    """Save people as contacts; return {"added": n, "updated": n, "tagged": n}.

    A lead that is already a contact (any shared identity key) gets `via` —
    and `import_id`, when given — added to its record; with `update` its
    non-empty fields are written over the saved ones too. A lead with no
    identity key at all (no e-mail, no profile, no name AND company) cannot
    be told apart from anyone and is skipped. Raises StoreError when the file
    cannot be written; nothing is then saved.

    `stage_of(lead)` -> a stage or "" — Apollo's "Use stage from CSV" / "set
    every contact to …": a new contact takes it (DEFAULT_STAGE when ""), a
    saved one only with `update`. The import's own "stage" column is read
    from the lead and never kept on the saved Lead itself. `list_name`, when
    given, is added to every one of them (Apollo's "Add to a list?")."""
    if via not in VIA:
        raise ValueError(f"unknown via {via!r}")
    doing = "Couldn't save these contacts"
    added = updated = tagged = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        by_key = {}
        for i, contact in enumerate(contacts):
            for key in keys_of(contact.lead):
                by_key.setdefault(key, i)
        now = _now()
        list_name = " ".join(str(list_name or "").split())
        for lead in leads or ():
            if lead is None:
                continue
            keys = keys_of(lead)
            if not keys:
                continue
            stage = stage_named(stage_of(lead)) if stage_of is not None else ""
            at = next((by_key[k] for k in keys if k in by_key), None)
            if at is None:
                contact = Contact(lead=_copy(lead), saved_at=now, updated_at=now,
                                  via=[via], imports=[import_id] if import_id else [],
                                  stage=stage or DEFAULT_STAGE,
                                  lists=[list_name] if list_name else [])
                _record(contact, "saved", via, now)
                if list_name:
                    _record(contact, "list", list_name, now)
                contacts.append(contact)
                at = len(contacts) - 1
                added += 1
            else:
                contact = contacts[at]
                changed = update and merge(contact.lead, lead)
                if via not in contact.via:
                    contact.via.append(via)
                    _record(contact, "saved", via, now)
                    changed = True
                if import_id and import_id not in contact.imports:
                    contact.imports.append(import_id)
                    changed = True
                if update and stage and stage != contact.stage:
                    _record(contact, "stage", f"{contact.stage} → {stage}", now)
                    contact.stage = stage
                    changed = True
                if list_name and list_name not in contact.lists:
                    contact.lists.append(list_name)
                    _record(contact, "list", list_name, now)
                    changed = True
                if changed:
                    contact.updated_at = now
                    if update:
                        updated += 1
                    else:
                        tagged += 1
            # The merged record may carry keys the incoming lead did not.
            for key in keys_of(contacts[at].lead) | keys:
                by_key.setdefault(key, at)
        _commit(folder, doing, state,
                     [_row(c) for c in contacts])
    return {"added": added, "updated": updated, "tagged": tagged}


def _copy(lead: Lead) -> Lead:
    """A contact holds its own copy: the run that found the person goes on
    mutating its Lead (verify, enrich), and the saved record must change only
    when it is saved again. The import's "stage" column is the CONTACT's
    (Contact.stage), not a fact about the person, so it is not kept here."""
    copy = lead_from_row(lead_to_row(lead))
    copy.extra.pop("stage", None)
    return copy


_READ_CACHE: dict = {}              # folder → ((mtime_ns, size), [Contact])


def get(folder, lead):
    """The saved Contact this lead is, as the file holds it now — the person
    panel's notes, tasks and Activities — or None. Never raises.

    The panel asks on every page rebuild while it is open (every filter
    click), so the parsed file is kept until the file itself changes; what
    comes back is for reading — edits go through this module's writers."""
    import os
    try:
        st = os.stat(os.path.join(folder, FILE))
        stamp = (st.st_mtime_ns, st.st_size)
    except (OSError, TypeError):
        return find(list_contacts(folder), lead)
    with _LOCK:
        hit = _READ_CACHE.get(folder)
        if hit is None or hit[0] != stamp:
            hit = (stamp, list_contacts(folder))
            _READ_CACHE.clear()             # one folder at a time is all it serves
            _READ_CACHE[folder] = hit
    return find(hit[1], lead)


def find(contacts, lead):
    """The Contact among `contacts` this lead is (any shared identity key), or
    None — in memory, for the person panel."""
    keys = keys_of(lead) if lead is not None else set()
    if not keys:
        return None
    for contact in contacts or ():
        if not keys.isdisjoint(keys_of(contact.lead)):
            return contact
    return None


def _change(folder, lead, doing: str, change) -> bool:
    """Apply `change(contact) -> bool` to the saved contact this lead is and
    write it; False when they are not a contact (or nothing changed). Raises
    StoreError when the file cannot be written."""
    keys = keys_of(lead) if lead is not None else set()
    if not keys:
        return False
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        for contact in contacts:
            if not keys.isdisjoint(keys_of(contact.lead)):
                if not change(contact):
                    return False
                contact.updated_at = _now()
                _commit(folder, doing, state,
                             [_row(c) for c in contacts])
                return True
    return False


def set_stage(folder, lead, stage: str) -> bool:
    """Move a saved contact to another stage (the person panel's Stage)."""
    stage = stage_named(stage)
    if not stage:
        return False

    def change(contact):
        if contact.stage == stage:
            return False
        _record(contact, "stage", f"{contact.stage} → {stage}")
        contact.stage = stage
        return True
    return _change(folder, lead, "Couldn't change this contact's stage", change)


def add_note(folder, lead, text: str) -> dict | None:
    """Keep a note on a saved contact; the note ({"at", "text"}) or None when
    there is nothing to keep or no such contact."""
    text = str(text or "").strip()[:_NOTE_MAX]
    if not text:
        return None
    note = {"at": _now(), "text": text}

    def change(contact):
        contact.notes.append(dict(note))
        return True
    return note if _change(folder, lead, "Couldn't keep this note", change) else None


EDITABLE = ("name", "title", "company", "email", "phone", "industry")
EDITABLE_EXTRA = ("location", "linkedin", "website")


def edit(folder, lead, changes: dict) -> bool:
    """Apollo's "… > Edit contact info": write the given fields over a saved
    contact — EDITABLE on the Lead, EDITABLE_EXTRA in its extra; a blank
    value clears an extra field. Returns whether anything changed. The live
    `lead` is updated too, so the page shows the edit at once."""
    changes = {k: " ".join(str(v or "").split()) for k, v in (changes or {}).items()
               if k in EDITABLE or k in EDITABLE_EXTRA}
    if not changes:
        return False

    def apply(target) -> list:
        changed = []
        for key, value in changes.items():
            if key in EDITABLE:
                if value and getattr(target, key, "") != value:
                    setattr(target, key, value)
                    changed.append(key)
            elif (target.extra.get(key) or "") != value:
                if value:
                    target.extra[key] = value
                else:
                    target.extra.pop(key, None)
                changed.append(key)
        if "email" in changed:
            # The owner typed it: that is where it came from, and the check run
            # on the address before says nothing about this one.
            target.extra["email_source"] = "you"
            target.extra.pop("email_check", None)
        return changed

    def change(contact):
        edited = apply(contact.lead)
        if edited:
            _record(contact, "edited", ", ".join(edited))
        return bool(edited)

    done = _change(folder, lead, "Couldn't save these changes", change)
    if done:
        apply(lead)
    return done


def add_task(folder, lead, text: str, due: str = "") -> dict | None:
    """A to-do on a saved contact ({"id", "at", "text", "due", "done"}), or
    None when there is nothing to keep or no such contact. `due` is an ISO
    date ("2026-09-30") or ""."""
    text = str(text or "").strip()[:_NOTE_MAX]
    if not text:
        return None
    due = str(due or "").strip()[:10]
    task = {"id": "", "at": _now(), "text": text, "due": due, "done": False}

    def change(contact):
        taken = {t["id"] for t in contact.tasks}
        n = len(contact.tasks) + 1
        while f"t{n}" in taken:
            n += 1
        task["id"] = f"t{n}"
        contact.tasks.append(dict(task))
        return True
    return task if _change(folder, lead, "Couldn't keep this task", change) else None


def set_task_done(folder, lead, task_id: str, done: bool = True) -> bool:
    """Tick a contact's task off (or back on)."""
    def change(contact):
        for task in contact.tasks:
            if task["id"] == task_id and task["done"] != bool(done):
                task["done"] = bool(done)
                return True
        return False
    return _change(folder, lead, "Couldn't update this task", change)


def advance_stage(folder, leads, to: str = "Approaching", only_from=("Cold",)) -> int:
    """Apollo's stage triggers, the ones Prism can see happen: a contact still
    in one of `only_from` moves to `to` — "Approaching" once they are sent a
    message. A stage the owner set by hand is left alone. Returns how many
    moved. Raises StoreError when the file cannot be written."""
    wanted = set()
    for lead in leads or ():
        if lead is not None:
            wanted.update(keys_of(lead))
    to = stage_named(to)
    if not (wanted and to):
        return 0
    doing = "Couldn't update these contacts' stage"
    moved = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        now = _now()
        for contact in contacts:
            if contact.stage in only_from and not wanted.isdisjoint(keys_of(contact.lead)):
                _record(contact, "stage", f"{contact.stage} → {to}", now)
                contact.stage = to
                contact.updated_at = now
                moved += 1
        if moved:
            _commit(folder, doing, state,
                         [_row(c) for c in contacts])
    return moved


def set_stage_many(folder, leads, stage: str) -> int:
    """Apollo's bulk "Edit > Set stage": every saved contact among `leads`
    moves to `stage`. Returns how many changed."""
    stage = stage_named(stage)
    wanted = set()
    for lead in leads or ():
        if lead is not None:
            wanted.update(keys_of(lead))
    if not (wanted and stage):
        return 0
    doing = "Couldn't set these contacts' stage"
    moved = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        now = _now()
        for contact in contacts:
            if contact.stage != stage and not wanted.isdisjoint(keys_of(contact.lead)):
                _record(contact, "stage", f"{contact.stage} → {stage}", now)
                contact.stage = stage
                contact.updated_at = now
                moved += 1
        if moved:
            _commit(folder, doing, state,
                         [_row(c) for c in contacts])
    return moved


def log(folder, lead, kind: str, text: str = "") -> dict | None:
    """Apollo's "Log activity": a call, a meeting, an e-mail or message sent
    outside Prism, or anything else, with what the owner wrote — or
    "flagged" (the data is wrong). The entry, or None when `kind` is not one
    of those or they are not a contact."""
    if kind not in LOGGED + ("flagged",):
        return None
    entry = {"at": _now(), "kind": kind, "text": str(text or "").strip()[:_NOTE_MAX]}

    def change(contact):
        _record(contact, kind, entry["text"], entry["at"])
        return True
    return entry if _change(folder, lead, "Couldn't log this activity", change) else None


def log_sent(folder, sent) -> int:
    """The e-mails Prism sent — [(lead, subject)] — each a line in its
    contact's Activities, in one write. Returns how many were logged."""
    by_key = {}
    for lead, subject in sent or ():
        for key in (keys_of(lead) if lead is not None else ()):
            by_key.setdefault(key, str(subject or ""))
    if not by_key:
        return 0
    doing = "Couldn't log these e-mails"
    logged = 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        now = _now()
        for contact in contacts:
            hit = next((by_key[k] for k in keys_of(contact.lead) if k in by_key), None)
            if hit is not None:
                _record(contact, "sent", hit, now)
                logged += 1
        if logged:
            _commit(folder, doing, state,
                         [_row(c) for c in contacts])
    return logged


def remove(folder, leads) -> int:
    """Delete the contacts these leads are (by any shared identity key);
    return how many were removed. Raises StoreError when the file cannot be
    written."""
    doing = "Couldn't remove these contacts"
    gone = set()
    for lead in leads or ():
        if lead is not None:
            gone.update(keys_of(lead))
    if not gone:
        return 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        kept = [c for c in contacts if keys_of(c.lead).isdisjoint(gone)]
        if len(kept) != len(contacts):
            _commit(folder, doing, state,
                         [_row(c) for c in kept])
    return len(contacts) - len(kept)


def untag_import(folder, import_id: str) -> int:
    """Forget one Contact CSV import on every contact that carries it — the
    import itself was deleted (imports.delete). A contact that came in ONLY
    through that import and was never saved any other way goes with it,
    matching Apollo's "delete the import and start over"; one saved again
    since (exported, sequenced, saved by hand) stays. Returns how many
    contacts were removed."""
    doing = "Couldn't remove that import's contacts"
    if not import_id:
        return 0
    with _LOCK:
        state, items = store.for_writing(folder, FILE, _KEY, SCHEMA, doing, _WHAT)
        contacts = _read_contacts(items)
        kept, removed, changed = [], 0, False
        for c in contacts:
            if import_id not in c.imports:
                kept.append(c)
                continue
            changed = True
            c.imports = [i for i in c.imports if i != import_id]
            if not c.imports and set(c.via) <= {"import"}:
                removed += 1
                continue
            kept.append(c)
        if changed:
            _commit(folder, doing, state,
                         [_row(c) for c in kept])
    return removed
