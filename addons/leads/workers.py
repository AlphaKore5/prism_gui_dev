"""Off-thread workers for Leads & Outreach.

Per-addon workers, like addons/step/workers.py — the shared workers.py holds
only what more than one add-on needs. Each subclasses the shared
`workers._Worker` (which anchors a running QThread against GC, so a dialog can
close mid-run without a native crash), and imports the prospector engine lazily
inside run() so importing this module never drags the engine onto the UI thread.
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from workers import _Worker


def _run_cfg(cfg):
    """The config an engine run should use. Pooled (the default): the provider
    keys are the credit-pool sentinel and any key a customer still has saved is
    dropped, so nothing below can reach a provider directly and every paid
    lookup goes through Prism's licence server (prospector/gateway.py). The
    developer switch PRISM_LEADS_DIRECT=1 leaves it untouched."""
    from prospector import gateway
    return gateway.effective_cfg(cfg)


def _seen_index(sessions_dir: str, include_earlier: bool, removed_dir: str = ""):
    """Everyone a search must skip, as a SeenIndex — or None when nobody is:
    whoever an earlier session already pulled (unless the user asked to
    include earlier people), and whoever the owner took off the list
    (removed.py), always — "new searches never bring them back" does not
    bend to that switch. Built inside run(): both are disk reads."""
    from prospector.identity import SeenIndex
    keys: set = set()
    if sessions_dir and not include_earlier:
        from addons.leads import sessions
        keys |= set(sessions.seen_keys(sessions_dir) or ())
    if removed_dir:
        from addons.leads import removed
        keys |= removed.keys(removed.list_removed(removed_dir))
    return SeenIndex(keys) if keys else None


def outside_filters(filtered, top: int = 3) -> tuple:
    """(total, "380 location, 32 job title") from a source run's
    stats["filtered"] — how many people the filters turned away, and the `top`
    reasons, most first, in the words of prospector.filters.REASONS. Shared by
    the no-one-left message here and the workbench's run summary."""
    from prospector.filters import REASONS
    counts = {k: int(v) for k, v in (filtered or {}).items()
              if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0}
    top = sorted(counts.items(), key=lambda kv: (-kv[1], str(kv[0])))[:top]
    words = ", ".join(f"{n} {REASONS.get(k, str(k).replace('_', ' '))}" for k, n in top)
    return sum(counts.values()), words


def _nobody_left(skipped: int, filtered, source: str = "exa",
                 query_errors: int = 0, queries_used: int = 0) -> str:
    """Why a search ended with nobody, naming what the owner can change: the
    filters that turned people away, the Net-new switch, or the search width.
    The last line names the database that was asked, because "check your
    balance" is only actionable when it says whose.

    22-Sep-2026: that last line used to be the ONLY answer for a genuine
    zero-match search AND for a search where every call to the database
    itself failed (a bad or expired key, an empty balance, the service
    down) — prospector.source's own _exa_people distinguishes the two
    (`None` = the call failed, `[]` = it answered with nothing) and counts
    both in `stats`, but nothing downstream READ query_errors, so "check
    your balance" was a guess dressed as the only message, every time,
    whether the account was fine or not. Reported live three times the
    same evening on a sheet with well-known companies that should have
    been easy to find someone for — exactly the shape this was blind to."""
    total, words = outside_filters(filtered)
    # The switch by the name Search settings shows it under.
    switch = "“Only find people no earlier search found” in Search settings"
    already = (f" {skipped} more were already pulled in an earlier search — they "
               f"are on the People page already; turn off {switch} to fetch them "
               "again." if skipped else "")
    if total:
        return (f"Nobody who came back matched your filters — {total} were outside "
                f"them ({words}). Loosen a filter or widen the search.{already}")
    if skipped:
        return (f"Everyone this search found ({skipped}) was already pulled in an "
                f"earlier search — they are on the People page already. Widen the "
                f"filters, or turn off {switch}.")
    from prospector import gateway
    if gateway.pooled():
        # No key of the customer's to blame: either the credits ran out (the
        # server said so, and gateway remembered) or the provider could not be
        # reached — and a search that failed was never charged.
        if gateway.exhausted():
            return ("You've run out of credits, so the search stopped. Ask "
                    "Alphakore to top up and search again.")
        if queries_used and query_errors >= queries_used:
            return (f"Every one of the {queries_used} searches failed to reach "
                    "the data provider — you haven't been charged. Try again in "
                    "a moment; if it keeps happening, contact Alphakore.")
        note = (f" ({query_errors} of {queries_used} searches failed — those "
                "were not charged)" if query_errors else "")
        return f"No people came back — widen the filters.{note}"
    db = "Apollo" if source == "apollo" else "Exa"
    if queries_used and query_errors >= queries_used:
        # Not a guess: every single call to the database failed outright —
        # this is what a bad/expired key or an empty balance looks like,
        # told apart from a real zero-match search.
        return (f"Every one of the {queries_used} searches to {db} failed — "
                f"this points at your {db} API key or balance, not the "
                f"filters. Check it under Keys & claims before trying again.")
    note = (f" ({query_errors} of {queries_used} searches to {db} failed — "
            f"worth checking your {db} key or balance too)"
            if query_errors else "")
    if source == "apollo":
        return f"No people came back from Apollo — widen the filters, or check your Apollo plan.{note}"
    return f"No people came back — widen the filters, or check your Exa balance.{note}"


def _plan_refusal(exc, apollo) -> str:
    """Apollo's 403 — a FREE plan (its search and match endpoints are not in
    one, and a master key does not help) or a key scoped to other endpoints —
    told apart from every other ApolloError by the message apollo itself writes
    for it. Matched on the halves around the endpoint it names, so the wording
    can be improved there without this going blind. "" = a different refusal."""
    text = str(exc)
    head, _sep, tail = apollo.SCOPED_KEY.partition("{path}")
    return text if head and text.startswith(head) and text.endswith(tail) else ""


def _filter_new(leads: list, skip):
    """(kept, skipped, duplicates): drop repeats within the run (first wins),
    then anyone `skip` already knows. Local on purpose — the workers only need
    prospector.identity, not an engine helper."""
    from prospector.identity import dedupe
    kept, dropped = dedupe(leads)
    if skip is None:
        return kept, 0, len(dropped)
    fresh = [lead for lead in kept if lead not in skip]
    return fresh, len(kept) - len(fresh), len(dropped)


# At most this many people from any one company in a run — source()'s own
# default, passed by name where a search over named companies relies on it.
_PER_COMPANY = 3


def _add_stats(into: dict, part: dict) -> None:
    """One group's search stats added into the run's: counts summed, the
    per-reason counts summed reason by reason, anything else kept from the
    first group that had it."""
    for key, value in (part or {}).items():
        if isinstance(value, bool):
            into.setdefault(key, value)
        elif isinstance(value, (int, float)):
            into[key] = into.get(key, 0) + value
        elif isinstance(value, dict):
            bucket = into.setdefault(key, {})
            for k, v in value.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    bucket[k] = bucket.get(k, 0) + v
        else:
            into.setdefault(key, value)


class ProspectorWorker(_Worker):
    """Qualify a sheet of leads and draft an email for each, off the UI thread.

    Groq is called once per lead to qualify and once per reachable lead to
    draft — minutes for a real list — so like the other engine workers this
    cannot run inline. `progress` carries a line per lead so the window has a
    live count instead of a frozen dialog. `limit=0` reads the sheet and ranks
    it and stops there: no Groq, no drafts — the cheap "load the sheet" half of
    the two Prepare buttons.

    A sheet is NEVER cut against earlier sessions. The owner picked this file,
    row by row; the commonest sheet there is now is one Prism itself exported
    from the run before, and a seen-index would hand that back empty. "Net new
    only" is about a SEARCH not re-finding people, and says so on the rail.
    """
    progress = Signal(str)
    done = Signal(object, list)      # RunResult, list[reach.Draft]
    failed = Signal(str)

    def __init__(self, path: str, offer: str, cfg: dict, *, sheet: str = None,
                 limit: int = 25, verify_limit: int = 25, focus: str = "",
                 sender: str = "", claims: list = None,
                 exclude_domains: list = None):
        super().__init__()
        self.path, self.offer, self.cfg = path, offer, _run_cfg(cfg)
        self.sheet, self.limit, self.focus = sheet, limit, focus
        self.verify_limit = verify_limit
        self.sender, self.claims = sender, claims or []
        self.exclude_domains = exclude_domains or []

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run(
                self.path, self.offer, self.cfg, sheet_name=self.sheet,
                limit=self.limit, focus=self.focus, provider=provider,
                skip=None, stats={},
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            if not res.dossiers:
                # limit=0 — the sheet is on screen, nothing was spent on it.
                self.done.emit(res, [])
                return
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit, cfg=self.cfg,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsSendWorker(_Worker):
    """Send the prepared outreach — one personalised message per lead — off the
    UI thread. SMTP blocks per message and a hot-list can be dozens of sends;
    `stop()` lets a person pull out part-way, and the reach layer refuses
    outright if no sending account is configured."""
    progress = Signal(int, int, object)     # i, total, reach.Draft
    done = Signal(list, list)               # sent emails, [(email, error), …]
    failed = Signal(str)

    def __init__(self, drafts: list, cfg: dict):
        super().__init__()
        self.drafts, self.cfg = drafts, cfg
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            from prospector import reach
            sent, failed = reach.send(
                self.drafts, self.cfg,
                on_progress=lambda i, n, d: self.progress.emit(i, n, d),
                should_stop=lambda: self._stop)
            self.done.emit(sent, failed)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsExportWorker(_Worker):
    """Write the two deliverable spreadsheets off the UI thread — the leads
    sheet does a live MX lookup per unique domain, which blocks, so it can no
    more run inline than a blast can."""
    progress = Signal(str)
    done = Signal(list)                     # [leads_path, hotlist_path]
    failed = Signal(str)

    def __init__(self, all_leads: list, dossiers: list, out_dir: str):
        super().__init__()
        self.all_leads, self.dossiers, self.out_dir = all_leads, dossiers, out_dir

    def run(self):
        try:
            import os
            from prospector import exports
            self.progress.emit("Verifying e-mails and writing the leads sheet…")
            leads_path = exports.leads_xlsx(
                self.all_leads, os.path.join(self.out_dir, "Prism leads.xlsx"))
            self.progress.emit("Writing the hot list…")
            hot_path = exports.hotlist_xlsx(
                self.dossiers, os.path.join(self.out_dir, "Prism hot list.xlsx"))
            self.done.emit([leads_path, hot_path])
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class CreditsWorker(_Worker):
    """Read the credit pool — the balance, the price list and which lookups
    Prism's licence server can make right now — off the UI thread, so the
    balance pill never holds the screen up on a slow connection. A failure is a
    quiet `failed`: the pill says it could not be read, and no run is blocked
    by it (a run asks the server itself and is told there)."""
    done = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            from prospector import gateway
            self.done.emit(gateway.status())
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(getattr(e, "message", "") or str(e))


class CreditsCallWorker(_Worker):
    """One call to the customer's own credit account — the usage read, the plans
    on offer, or a request for one (prospector.gateway.credit_usage /
    credit_offers / request_offer) — off the UI thread. `done` carries which
    call it was, so a screen can hand several to one slot; `failed` carries the
    server's own customer-facing sentence, or a plain one when it was not
    reached."""
    done = Signal(str, dict)
    failed = Signal(str, str)

    WHAT = ("usage", "offers", "request")

    def __init__(self, what: str, **params):
        super().__init__()
        if what not in self.WHAT:
            raise ValueError(what)
        self.what, self.params = what, params

    def run(self):
        try:
            from prospector import gateway
            call = {"usage": gateway.credit_usage, "offers": gateway.credit_offers,
                    "request": gateway.request_offer}[self.what]
            self.done.emit(self.what, call(**self.params))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(self.what, getattr(e, "message", "") or str(e))


class LeadsVerifyWorker(_Worker):
    """Re-verify the SELECTED leads' e-mails with the free-first verifier
    waterfall (verifiers only — never a paid finder), off the UI thread. Each
    live SMTP probe blocks, so a checked batch cannot run inline. Mutates
    lead.extra['email_check'] in place; the dialog re-renders when done."""
    progress = Signal(int, int, object)     # i, total, lead
    done = Signal()
    failed = Signal(str)

    def __init__(self, dossiers: list, cfg: dict):
        super().__init__()
        self.dossiers, self.cfg = dossiers, _run_cfg(cfg)

    def run(self):
        try:
            from prospector import verify
            keys = verify.collect_keys(self.cfg)
            from prospector import gateway
            targets = [d for d in self.dossiers if (d.lead.email or "").strip()]
            for i, d in enumerate(targets, 1):
                if gateway.exhausted():
                    break               # the credit pool ran dry: keep what was checked
                self.progress.emit(i, len(targets), d.lead)
                status = verify.verify_email(d.lead.email, keys)
                if status:
                    d.lead.extra = d.lead.extra or {}
                    d.lead.extra["email_check"] = status
            self.done.emit()
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsEmailWorker(_Worker):
    """Find the SELECTED leads' e-mail addresses, off the UI thread — the
    cockpit's "Find e-mails".

    A Find-people run deliberately brings back no addresses (finding people is
    free; finding their addresses costs a lookup and a credit each), so this is
    where that money is spent, on the people the owner ticked — or on the rows
    of a sheet they exported and brought back.

    First, ONE Exa lookup per company (verify.find_domains, not per lead) —
    the finders that follow ask by domain, not just a company's bare name,
    which finds far less (27-Sep-2026: this step existed but was never
    called). Then, `verify.find_and_verify` per lead: an address they came
    with (a sheet's, Apollo's) is checked with the free verifiers; anyone
    without one, or whose address the check could not confirm, is looked up
    by the FINDERS — Hunter (our main finder), then Apollo, each only where
    its key is set, each charging only when it knows the person — and what
    they find is checked too. Nothing is ever guessed (the owner, 24-Sep-2026:
    "hunter + apollo only to find mails"): someone neither finder knows keeps
    no address. A finder that turns the ACCOUNT away (a Free plan, a spent
    quota, a wrong key) is asked once, and `refused` says why before `done`.
    Not capped by the rail's Verify setting. That number is a budget for a
    RUN, which verifies whatever its top slice happens to be — this action is
    the owner naming people, row by row, and the workbench asks before a batch
    past ten."""
    progress = Signal(int, int, object)     # i, total, lead
    done = Signal(int, int)                 # addresses found, of them verified
    failed = Signal(str)
    refused = Signal(object)                # {finder: why} — verify.FinderRefused

    def __init__(self, leads: list, cfg: dict):
        super().__init__()
        self.leads, self.cfg = list(leads or []), _run_cfg(cfg)

    def run(self):
        try:
            from prospector import verify
            keys = verify.collect_keys(self.cfg)
            # Apollo's people/match is not in a free Apollo plan either, and the
            # workbench has already learnt that from a refused run — so don't
            # spend a lead's turn on a finder that answers 403.
            if self.cfg.get("apollo_api_blocked"):
                keys.pop("apollo_api_key", None)
            blank = [l for l in self.leads if not (l.email or "").strip()]
            # One Exa lookup per company (not per lead) before any finder is
            # asked, so Hunter/Apollo get a real domain instead of just a
            # company's bare name — silently skipped with no Exa key, same as
            # before this existed (27-Sep-2026: this was the missing step).
            self.progress.emit(0, len(self.leads), None)
            verify.find_domains(self.leads, self.cfg)
            # One Hunter Domain Search per company domain (not per lead) before
            # the per-person finder — the same credit, a cheaper way to buy it
            # when several leads share a company (02-Oct-2026).
            verify.find_emails_by_domain(self.leads, keys)
            refused: dict = {}
            for i, lead in enumerate(self.leads, 1):
                self.progress.emit(i, len(self.leads), lead)
                lead.extra = lead.extra or {}
                verify.find_and_verify(lead, keys, refused=refused)
            # "Found" is people who had NO address and have one now — the thing
            # this action was pressed for. Confirming one they already had is
            # counted as a verification, not as a find.
            found = sum(1 for l in blank if (l.email or "").strip())
            ok = sum(1 for l in self.leads
                     if (l.extra or {}).get("email_check") == "valid")
            if refused:
                self.refused.emit(dict(refused))
            self.done.emit(found, ok)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsPhoneWorker(_Worker):
    """Find the phone number each SELECTED lead's company publishes, off the UI
    thread — the cockpit's "Find phones" and the person panel's "Find their
    phone". One lookup per company, 15 to a call, only for leads with no phone
    yet (prospector/phones.py); the credits are charged per number found.

    Nothing here checks the number is live or whose it is: it is the number the
    company itself prints, with the page it came from. `done` carries the counts
    the workbench says out loud — {"asked", "found", "given", "failed"}."""
    progress = Signal(int, int)             # companies looked up so far, of how many
    done = Signal(object)                   # phones.find's counts
    failed = Signal(str)

    def __init__(self, leads: list, cfg: dict):
        super().__init__()
        self.leads, self.cfg = list(leads or []), _run_cfg(cfg)

    def run(self):
        try:
            from prospector import phones
            self.done.emit(phones.find(self.leads, self.cfg,
                                       on_progress=lambda i, n: self.progress.emit(i, n)))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsMobileWorker(_Worker):
    """Find each SELECTED person's own mobile number (Apollo, through the licence
    server), off the UI thread. Apollo answers in minutes, so this holds a thread
    that long: every lookup is started first and then all are read together
    (prospector/mobiles.py). Credits are charged per number found, once.

    `done` carries mobiles.find's counts — {"asked", "found", "given", "failed",
    "pending", "why"}."""
    progress = Signal(int, int)             # lookups finished so far, of how many
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, leads: list, cfg: dict):
        super().__init__()
        self.leads, self.cfg = list(leads or []), _run_cfg(cfg)

    def run(self):
        try:
            from prospector import mobiles
            self.done.emit(mobiles.find(self.leads, self.cfg,
                                        on_progress=lambda i, n: self.progress.emit(i, n)))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsQualifyWorker(_Worker):
    """Qualify and draft the leads the user ticked, off the UI thread — the
    cockpit's "Qualify & draft". A leads-sheet-only run, or everyone past a full
    run's Qualify count, leaves people sourced but never qualified; this spends
    the same expensive pass a run spends on its top slice (why-now signal, Groq
    dossier, the free verifier on hot/warm, the draft) on exactly those people,
    so nobody has to re-import a sheet to reach them. They already belong to the
    session on screen, so none is skipped as "already pulled"."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult for those leads, drafts
    failed = Signal(str)

    def __init__(self, leads: list, offer: str, cfg: dict, *, roles: list = None,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None):
        super().__init__()
        self.leads, self.offer, self.cfg = list(leads or []), offer, _run_cfg(cfg)
        self.roles, self.verify_limit, self.focus = roles or [], verify_limit, focus
        self.sender, self.claims = sender, claims or []
        self.exclude_domains = exclude_domains or []

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run_leads(
                self.leads, self.offer, self.cfg, limit=len(self.leads),
                focus=self.focus, provider=provider, roles=self.roles,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit, cfg=self.cfg,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsSessionLoadWorker(_Worker):
    """Read a saved Leads session off the UI thread — the latest one when the
    screen first opens, or the one picked on the Sessions tab. A 2,000-lead run
    is megabytes of JSON; parsing it inline would freeze the window. Emits the
    loaded session dict (see addons/leads/sessions.load), or None when there is
    no session yet."""
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, folder: str, session_id: str = ""):
        super().__init__()
        self.folder, self.session_id = folder, session_id

    def run(self):
        try:
            from addons.leads import sessions
            sid = self.session_id
            if not sid:
                head = sessions.latest(self.folder)
                if head is None:
                    self.done.emit(None)
                    return
                sid = head["id"]
            self.done.emit(sessions.load(self.folder, sid))
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsPoolWorker(_Worker):
    """Everyone Prism holds, read off the UI thread: the saved contacts and
    every past run — what the People page filters instantly (addons/leads/
    pool.build joins them). Emits (contacts, runs), each run a (session_id,
    created_at, all_leads, dossiers, drafts, params) tuple — params being what
    the run was asked, which the pool reads to know what its search was
    steered by. A run that cannot be read is left out, not the whole page: one
    damaged file must not hide everyone else. With `accounts_dir`, the saved
    accounts (accounts.py) come first, by accounts_read — the Stage, Lists and
    Custom fields filters read a person's account from them. With
    `removed_dir`, the people taken off the list (removed.py) come before
    `done` too, by removed_read — the pool leaves them out."""
    done = Signal(object, object)
    accounts_read = Signal(object)
    removed_read = Signal(object)
    failed = Signal(str)

    def __init__(self, contacts_dir: str, sessions_dir: str, accounts_dir: str = "",
                 removed_dir: str = ""):
        super().__init__()
        self.contacts_dir, self.sessions_dir = contacts_dir, sessions_dir
        self.accounts_dir, self.removed_dir = accounts_dir, removed_dir

    def run(self):
        try:
            from addons.leads import accounts, contacts, removed, sessions
            if self.accounts_dir:
                self.accounts_read.emit(accounts.list_accounts(self.accounts_dir))
            if self.removed_dir:
                self.removed_read.emit(removed.list_removed(self.removed_dir))
            saved = contacts.list_contacts(self.contacts_dir) if self.contacts_dir else []
            runs = []
            for head in sessions.list_sessions(self.sessions_dir) if self.sessions_dir else ():
                try:
                    got = sessions.load(self.sessions_dir, head["id"])
                except sessions.SessionStoreError:
                    continue
                runs.append((head["id"], got["header"].get("created_at", ""),
                             got["all_leads"], got["dossiers"], got["drafts"],
                             got["params"]))
            self.done.emit(saved, runs)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class LeadsAccountEnrichWorker(_Worker):
    """An accounts import's "Intelligent enrichment", off the UI thread: one
    Exa company lookup (prospector.source._exa_company — its website,
    headcount, revenue, HQ and a line about it) for each company that needs
    it. `mode` "websites" asks only for the companies with a name and no
    website (Apollo's "infer a website for rows with only account names");
    "all" asks for every company. Only what is MISSING is filled: the sheet's
    own values stand. A company Exa cannot confidently match is left as it
    was — a wrong website is worse than none. Emits progress(i, n, name)
    and done(companies, filled)."""
    progress = Signal(int, int, str)
    done = Signal(object, int)
    failed = Signal(str)

    def __init__(self, companies, cfg, mode: str = "websites"):
        super().__init__()
        self.companies = [dict(c) for c in companies or ()]
        self.cfg = _run_cfg(dict(cfg or {}))
        self.mode = mode if mode in ("websites", "all") else "websites"

    @staticmethod
    def wants(company: dict, mode: str) -> bool:
        """Whether this company is one `mode` looks up."""
        site = (company.get("website") or company.get("domain") or "").strip()
        if mode == "websites":
            return bool((company.get("name") or "").strip()) and not site
        return bool((company.get("name") or "").strip() or site)

    def run(self):
        try:
            from prospector import signals
            from prospector.source import _exa_company
            key = signals.exa_key(self.cfg)
            if not key:
                self.failed.emit("Looking companies up needs an Exa API key — add it "
                                 "under Search settings › Keys & claims.")
                return
            targets = [i for i, c in enumerate(self.companies) if self.wants(c, self.mode)]
            filled = 0
            for n, i in enumerate(targets, 1):
                company = self.companies[i]
                ask = company.get("name") or company.get("website") or company.get("domain")
                self.progress.emit(n, len(targets), str(ask or ""))
                facts = _exa_company(str(ask or ""), key)
                if not facts:
                    continue
                changed = False
                for field, value in (("domain", facts.get("domain")),
                                     ("website", facts.get("domain")),
                                     ("headcount", facts.get("headcount")),
                                     ("revenue", facts.get("revenue")),
                                     ("location", facts.get("hq")),
                                     ("description", (facts.get("description") or "")[:600])):
                    if value and not str(company.get(field) or "").strip():
                        company[field] = str(value)
                        changed = True
                filled += changed
            self.done.emit(self.companies, filled)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))


class SourceWorker(_Worker):
    """The full from-scratch pipeline off the UI thread: find people who match
    the lead FILTERS (every person checked against the filters before they take
    a slot), then qualify and draft — the hot and warm have their real
    addresses FOUND on the way (verify.verify_reachable: Hunter, our main
    finder, then Apollo).
    No address is ever guessed (24-Sep-2026).
    Emits the SAME (RunResult, drafts) as ProspectorWorker, so the dialog
    treats the sheet path and the search path identically.

    Two databases answer the same filters. `source="exa"` pages a web people
    search, free per person; `source="apollo"` asks Apollo's own index, free to
    search and about a credit for each person it reveals — so that path spends
    nothing on anyone the filters or an earlier session would drop, and the run
    carries its credit count back as `res.apollo_stats`.

    `emails="later"` finds the PEOPLE and stops: no domain lookups, no verifier,
    no finder — so a run costs only its searches, and the owner spends on
    addresses afterwards, for the rows they tick (or a sheet they export and
    bring back). `emails="now"` is the whole pipeline, as before.

    `spec` is the filter panel's SearchSpec dict. The industries / roles /
    location arguments are derived from it by the caller; with a spec they
    only matter to an engine that predates filters."""
    progress = Signal(str)
    done = Signal(object, list)             # RunResult, list[reach.Draft]
    failed = Signal(str)
    # Apollo refused the run on its PLAN or the key's scope (its own 403).
    # Separate from `failed` because the owner must not be able to spend
    # another run finding the same wall: the workbench switches back to Exa
    # and puts Apollo's reason on the switch it disables.
    blocked = Signal(str)
    # A search over `companies`: how many of them have been asked so far,
    # after each group — the workbench counts an import's companies as
    # searched only once they really were.
    companiesAsked = Signal(int)

    def __init__(self, industries: list, roles: list, offer: str, cfg: dict, *,
                 location: str = "India", target: int = 300, limit: int = 25,
                 verify_limit: int = 25, focus: str = "", sender: str = "",
                 claims: list = None, exclude_domains: list = None,
                 leads_only: bool = False, sessions_dir: str = "",
                 include_earlier: bool = False, spec: dict | None = None,
                 source: str = "exa", emails: str = "now", removed_dir: str = "",
                 companies: list | None = None):
        super().__init__()
        self.spec = spec
        # An Account CSV import searched whole (24-Sep-2026): every company
        # of it, more than the spec's Current company facet can hold. Asked
        # in groups of that size, one after another, in this one run.
        self.companies = [c for c in (companies or ()) if isinstance(c, str) and c.strip()]
        self.source = "apollo" if source == "apollo" else "exa"
        self.emails = "later" if emails == "later" else "now"
        self.industries, self.roles = industries, roles
        self.offer, self.cfg = offer, _run_cfg(cfg)
        self.location, self.target, self.limit = location, target, limit
        self.verify_limit = verify_limit
        self.focus, self.sender = focus, sender
        self.claims = claims or []
        self.exclude_domains = exclude_domains or []
        self.leads_only = leads_only
        self.sessions_dir, self.include_earlier = sessions_dir, include_earlier
        self.removed_dir = removed_dir      # the people taken off the list

    def _apollo_progress(self, stage, done, total, found):
        """Apollo's two phases, said in what each costs: paging its index is
        free, so that line counts pages and people; revealing is billed, so
        that line counts credits against the target."""
        if stage == "reveal":
            self.progress.emit(
                f"Revealing {done} of {total or self.target} (Apollo credits)")
        else:
            self.progress.emit(f"Searching Apollo — page {done} · {found} found")

    def _asked(self, part, asked: int) -> int:
        """After one group of an import's companies: how many are asked now,
        said to the workbench (companiesAsked)."""
        if not self.companies or part is None:
            return asked
        asked += len(part.companies.include)
        self.companiesAsked.emit(asked)
        return asked

    def run(self):
        try:
            from prospector import engine, reach, signals, verify
            from prospector.filters import SearchSpec, company_chunks
            spec = SearchSpec.from_dict(self.spec) if isinstance(self.spec, dict) else None
            # The roles triage and qualification read: the job titles, or the
            # seniority x function the filters ask for when there are none.
            roles = (spec.role_terms() if spec is not None else None) or self.roles
            skip = _seen_index(self.sessions_dir, self.include_earlier, self.removed_dir)
            stats: dict = {}
            apollo_run = self.source == "apollo"
            exa_key = signals.exa_key(self.cfg)
            # One search, or — over an import's companies — one per group.
            parts = (company_chunks(spec, self.companies)
                     if spec is not None and self.companies else [spec])
            leads, asked = [], 0
            if apollo_run:
                # Lazy, like every engine import here: the Exa path must not
                # pay for a module it never calls.
                from prospector import apollo
                key = apollo.api_key(self.cfg)
                if not key:
                    self.failed.emit("Searching Apollo needs an Apollo API key — "
                                     "add it under Keys & claims and try again.")
                    return
                self.progress.emit("Searching Apollo for people who match your filters…"
                                   if skip is None else
                                   "Searching Apollo — skipping anyone already pulled…")
                # An ApolloError (a bad key, a plan that cannot search, a rate
                # limit that outlasted its retries) is already written for the
                # owner; run()'s own handler emits it as the failure. The one
                # it does NOT emit as a failure is the plan/scope refusal:
                # that wall is there for every later run too, so it goes out
                # as `blocked` and the rail stops offering Apollo.
                for part in parts:
                    room = self.target - len(leads)     # Apollo bills each reveal
                    if room <= 0:
                        break
                    got: dict = {}
                    try:
                        leads += apollo.search_people(
                            part if part is not None else (self.spec or {}), key,
                            target=room, skip=skip, stats=got,
                            on_progress=self._apollo_progress)
                    except apollo.ApolloError as exc:
                        why = _plan_refusal(exc, apollo)
                        if not why:
                            raise
                        self.blocked.emit(why)
                        return
                    _add_stats(stats, got)
                    asked = self._asked(part, asked)
            else:
                # `as people_search`: self.source is the name of the database,
                # the module is the Exa people search itself.
                from prospector import source as people_search
                key = exa_key
                if not key:
                    self.failed.emit("Finding people needs an Exa API key — add it "
                                     "under Keys & claims and try again.")
                    return
                self.progress.emit("Finding people who match your filters…"
                                   if skip is None else
                                   "Finding new people — skipping anyone already pulled…")
                for part in parts:
                    got: dict = {}
                    if self.companies:
                        # One search a company, every one of them asked: the
                        # press was approved as exactly that, so the run's
                        # target does not cut a group short.
                        n = len(part.companies.include)
                        span = (f"companies {asked + 1}–{asked + n} of "
                                f"{len(self.companies)}")
                        leads += people_search.source(
                            self.industries, roles, key, location=self.location,
                            target=n * _PER_COMPANY, per_company=_PER_COMPANY,
                            skip=skip, stats=got, spec=part,
                            on_progress=lambda qi, total, _ind, found, span=span:
                                self.progress.emit(f"Searching {span} — {found} "
                                                   f"found ({qi}/{total} searches)"))
                    else:
                        # Only a spec'd run passes spec=, so an engine without
                        # filters still takes the call.
                        extra = {"spec": part} if part is not None else {}
                        leads += people_search.source(
                            self.industries, roles, key, location=self.location,
                            target=self.target, skip=skip, stats=got,
                            on_progress=lambda qi, n, ind, found: self.progress.emit(
                                f"Sourcing {ind} — {found} found ({qi}/{n} searches)"),
                            **extra)
                    _add_stats(stats, got)
                    asked = self._asked(part, asked)
            skipped, dups = stats.get("skipped_seen", 0), stats.get("duplicates", 0)
            filtered = dict(stats.get("filtered") or {})
            unverified = int(stats.get("company_unverified") or 0)
            if not leads:
                self.failed.emit(_nobody_left(
                    skipped, filtered, self.source,
                    query_errors=int(stats.get("query_errors") or 0),
                    queries_used=int(stats.get("queries_used") or 0)))
                return
            if self.emails == "later":
                # Finding PEOPLE is cheap — the searches are all it costs.
                # Finding their ADDRESSES is not: a domain lookup per company,
                # then a verifier or finder credit a head. So this run stops
                # here, and "Find e-mails" spends that on the rows the owner
                # ticks. (Apollo hands over the addresses it already revealed;
                # they are kept, nothing is guessed on top.)
                self.progress.emit(f"Found {len(leads)} new people — e-mails left "
                                   f"for later.")
            else:
                # Apollo hands over the addresses it holds; nobody else's is
                # made up — the hot and warm have theirs found after
                # qualifying (verify_reachable), anyone else by Find e-mails.
                self.progress.emit(f"Found {len(leads)} new people.")
            # The in-run dedupe once more before spending Groq (free).
            leads, late_skipped, late_dups = _filter_new(leads, skip)
            skipped += late_skipped
            dups += late_dups
            if not leads:
                self.failed.emit(_nobody_left(skipped, filtered, self.source))
                return
            if self.leads_only:
                # The cheap deliverable: a ranked leads sheet with NO Groq at all
                # (qualify + draft skipped) — so a rate-limited or exhausted Groq
                # key never blocks the list the user actually wants. With
                # emails="later" it is cheaper still: the searches, and nothing else.
                from prospector import triage
                ranked = triage.rank(leads, self.offer, roles)
                res = engine.RunResult(dossiers=[], total_in_sheet=len(ranked),
                                       signal_source="", all_leads=ranked)
                res.skipped_seen, res.duplicates = skipped, dups
                res.filtered_out, res.company_unverified = filtered, unverified
                if apollo_run:
                    res.apollo_stats = stats    # what the run cost, in credits
                self.done.emit(res, [])
                return
            provider = signals.make_provider(self.cfg, self.focus,
                                             exclude_domains=self.exclude_domains)
            res = engine.run_leads(
                leads, self.offer, self.cfg, limit=self.limit, focus=self.focus,
                provider=provider, roles=roles,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Qualifying {i} of {n}: {l.display()}"))
            res.skipped_seen = skipped
            res.duplicates = dups + (getattr(res, "duplicates", 0) or 0)
            res.filtered_out, res.company_unverified = filtered, unverified
            if apollo_run:
                res.apollo_stats = stats        # what the run cost, in credits
            vkeys = verify.collect_keys(self.cfg)
            if vkeys and self.verify_limit:
                self.progress.emit("Verifying the hot/warm emails…")
                verify.verify_reachable(
                    res.dossiers, vkeys, limit=self.verify_limit, cfg=self.cfg,
                    on_progress=lambda i, n, l: self.progress.emit(
                        f"Verifying {i} of {n}: {l.display()}"))
            drafts = reach.draft_batch(
                res.dossiers, self.offer, self.cfg, sender=self.sender,
                claims=self.claims,
                on_progress=lambda i, n, l: self.progress.emit(
                    f"Writing {i} of {n}: {l.display()}"))
            self.done.emit(res, drafts)
        except Exception as e:                          # noqa: BLE001
            self.failed.emit(str(e))
