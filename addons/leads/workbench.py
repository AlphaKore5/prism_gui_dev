"""
Leads & Outreach — the workbench widget
────────────────────────────────────────
The whole working surface as one embeddable QWidget, so it can be the full
in-window screen (addons/leads/panel.py) instead of living inside a modal. It
drives the tabbed cockpit (addons/leads/cockpit.py) — whose People tab is
Apollo's Find People (23-Sep-2026) — and every action: import, find, verify,
save, export, send — with the heavy work off the UI thread
(addons/leads/workers.py).

The People page is everyone Prism holds (addons/leads/pool.py: saved
contacts and every past run), filtered the moment a filter is clicked, split
into Total / Net New / Saved and paged 25 at a time — all free. The one
action that spends is Find new people, which says what it costs and asks
first. Import ▾ brings a sheet in as contacts or accounts
(addons/leads/import_wizard.py, contacts.py, imports.py) and never searches:
the import becomes a filter.

Who a list is for is set as lead FILTERS, Apollo / Sales Navigator style
(addons/leads/filter_panel.py): every facet includes and excludes, and an
exclusion is enforced on every person who comes back, not pasted into a query.
A set of filters can be saved and used again (addons/leads/saved_searches.py).

It PREPARES; a person presses Send, and only the value claims from the seller's
own file are ever made (prospector/reach.py). Sending goes one-per-person from
the owner's own account, through the same engine mailer the Email add-on uses.
"""
from __future__ import annotations

import csv
import datetime
import os
import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
from widgets.loader import Loader
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from prospector import gateway
from prospector.filters import MAX_FACET_VALUES, SearchSpec
from addons.leads import pool as P
from addons.leads import saved_searches
from addons.leads.filter_panel import (
    HELP_KEYS as _FILTER_HELP_KEYS, FilterPanel, reveal_in_scroll, static_suggest,
)
from addons.leads.credits_page import CreditPopover, CreditUsageDialog, UpgradeDialog
from addons.leads.workers import (CreditsCallWorker, CreditsWorker, LeadsEmailWorker,
                                  LeadsExportWorker, LeadsPhoneWorker, LeadsQualifyWorker,
                                  LeadsSendWorker, LeadsSessionLoadWorker,
                                  LeadsVerifyWorker, SourceWorker, outside_filters)
from addons.leads.cockpit import LeadsWorkspace

try:
    from prospector.run_poc import DEFAULT_OFFER
except Exception:                                       # noqa: BLE001
    DEFAULT_OFFER = "what your company sells"

# The owner's own ICP — the first client's buyers — as a STARTER search in
# Default view ▾ (_STARTERS). It used to be pre-filled in the rail; since the
# rail filters everyone Prism holds (pool.py), a pre-filled rail hid every
# held person outside that one vertical, so the page opens empty, as
# Apollo's does, and this is one pick away. Each line is one include chip.
_DEFAULT_INDUSTRIES = (
    "Automobile\nAuto Components\nTyre\nSteel Manufacturing\nDie Casting\n"
    "Aerospace & MRO\nDefense\nElectrical & Electronics\n"
    "Warehousing & Logistics\nMining")
_DEFAULT_ROLES = (
    "Head of Digital Transformation / Industry 4.0 / IIoT\n"
    "Automation Head / Smart Manufacturing\n"
    "Manufacturing Excellence / Operations / Production Head\n"
    "Business Excellence & Continuous Improvement\n"
    "Plant Head / Head of Manufacturing\n"
    "Supply Chain / Warehouse / Materials Head")


# The "?" walkthrough's keys this widget answers (addons/leads/tour.py) — Find
# new people and the run line; the filters and the cockpit answer for
# themselves. Search settings' rows are NOT walked one by one: they live in a
# window-modal dialog, and a walk that opened it would put the dialog over
# its own Next button. The toolbar's "Search settings" step says what is in
# there, and each row carries its own tooltip.
_HELP_KEYS = frozenset({"btn_find", "notice"})


# The Apollo half of the source switch, in two states. Apollo's own API Keys
# page says its search and match endpoints "aren't included in your Free plan
# and won't be accessible even with a master key" — so the tooltip says it
# before a run spends a thread finding out. Functions, not constants: the
# translation must be looked up when the tooltip is set, not at import.
def _apollo_tip() -> str:
    return i18n.t("Searching Apollo needs a PAID Apollo plan — the free plan "
                  "has no API access. Exa needs only its own key.")


def _apollo_blocked_text() -> str:
    """What the disabled switch says when Apollo refused without words of its
    own — normally it carries Apollo's actual 403 message instead."""
    return i18n.t("Apollo's API refused this key. Its people search is not in "
                  "the free Apollo plan; Exa is doing the finding.")


def _default_spec() -> SearchSpec:
    """The starter search: the owner's job titles and industries, anywhere."""
    return SearchSpec.from_dict({
        "job_titles": {"include": _DEFAULT_ROLES.split("\n")},
        "industries": {"include": _DEFAULT_INDUSTRIES.split("\n")},
    })


# Default view ▾'s starter searches: key → (name, the filters it loads).
_STARTERS = {
    "icp": ("Automation & digital leaders in manufacturing", _default_spec),
}


# Decision-maker levels broad enough to reach a real person at almost any
# company, whatever it makes — unlike _DEFAULT_ROLES, which names one
# specific vertical (digital-transformation / automation heads).
#
# Four, not five, not two. _queries() asks Exa once per (role, company)
# PAIR, so every extra seniority word here multiplies every batch's real
# query count: two names meant 100 real searches for one 50-company batch,
# which a live run (22-09-2026) showed was the wrong cut — filters.
# seniority_of() reads "Managing Director", "CEO", "Chairman" and
# "President" as c_suite, and "Founder"/"Co-Founder" as founder, NEVER as
# director or owner (its own docstring says so). Those are the titles an
# Indian SME's real decision-maker actually carries — a live 50-company
# batch came back with 2199 people and match_person() threw out 2162 of
# them as "outside your filters (seniority)" for exactly this reason, only
# the bare "Director"/"Owner" title text survived. c_suite and founder are
# back in; "head" stays out — "Head"/"HOD"/"Leader" catches middle-
# management noise ("Team Leader") a company-sheet search doesn't want.
# Four terms is 200 real searches for 50 companies, not the 250 the
# original five-term version cost.
_COMPANY_SEARCH_SENIORITY = ("owner", "founder", "c_suite", "director")
# One press of Find new people over an Account CSV import asks every company
# not searched yet, one Exa search each (the owner, 24-Sep-2026: "all at
# once") — up to this many, so a sheet of thousands still asks first in
# pieces a person can weigh. The confirmation names the exact count.
_COMPANIES_PER_PRESS = 500


def _company_search_spec(spec: SearchSpec) -> SearchSpec:
    """The base a company-only-sheet search asks with, unless the owner has
    customised Find people's job titles or seniority themselves.

    _default_spec()'s titles are ONE vertical: "Head of Digital
    Transformation", "Automation Head". A company sheet can be any industry
    at all, and asking Exa for exactly those titles at, say, a small
    Vadodara pharma-machinery manufacturer finds nobody — not because
    there is nobody there, but because that specific title is not a role a
    company that size has (proved live, 22-09-2026: the same companies,
    called through the real pipeline with just Owner/Director instead,
    returned real people with real LinkedIn profiles in seconds). Owner /
    Director reaches a real decision-maker almost anywhere, and the sheet
    already named the industry by naming the companies — asking Exa for it
    again on top would only narrow a search that is already as scoped as
    it can be.

    22-09-2026: originally gated on the WHOLE spec being byte-for-byte
    _default_spec() — any other field differing (a saved search touched
    earlier the same session, a restored run, anything) silently kept the
    stale automation-vertical titles with no sign anything had gone
    wrong. Gated on the one thing that actually matters instead: are the
    job titles still exactly the ones this sheet-search path must not use.
    Any OTHER seniority/job-title choice the owner made is respected.
    Industries is cleared regardless — with real companies named, it has
    no effect on the query Exa is sent (filters._queries' company branch
    never reads it) and only exists here as unused bookkeeping.

    23-09-2026: a company sheet is an Account CSV import now (Import ▾ ›
    Accounts) and nothing is searched until Find new people is pressed —
    this is what that search asks with, for the batch of the import's
    companies it covers (_search_spec)."""
    stale_titles = list(_DEFAULT_ROLES.split("\n"))
    out = spec.copy()
    out.industries.include = []
    if not out.job_titles.include or out.job_titles.include == stale_titles:
        out.job_titles.include = []
        if not out.seniority.include and not out.functions.include:
            out.seniority.include = list(_COMPANY_SEARCH_SENIORITY)
    return out


def _suggest(facet: str, text: str) -> list:
    """The filter panel's typeahead. Places come from prospector.places (every
    country, region, state and city it knows) ahead of the starter list, which
    stays the fallback when that lookup is missing or fails; every other facet
    offers its starter list."""
    base = static_suggest(facet, text)
    if facet not in ("locations", "company_hq"):
        return base
    try:
        from prospector import places                  # lazy: a big table
        found = list(places.suggest(text, limit=8) or [])
    except Exception:                                   # noqa: BLE001
        return base
    # Beside the places lookup, the starter list only adds names a WORD of
    # which starts with the text — "ger" is Germany, not Nigeria.
    fold = " ".join((text or "").split()).casefold()
    base = [s for s in base if f" {fold}" in f" {s.casefold()}"]
    out, seen = [], set()
    for value in found + base:
        if isinstance(value, str) and value.strip() and value.casefold() not in seen:
            seen.add(value.casefold())
            out.append(value)
    return out


def _when(iso: str) -> str:
    """A session timestamp as a person reads it: "11 Sep, 14:02"."""
    try:
        return datetime.datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def _kick(text: str) -> QLabel:
    """A rail section heading — the same voice as the cockpit's REFINE RESULTS."""
    lab = QLabel(text.upper())
    lab.setStyleSheet(
        f"color:{theme.NEUTRAL[600]};font-family:'{theme.FONT_HEADING}';"
        f"font-size:11px;letter-spacing:1px;font-weight:600;background:transparent;")
    return lab


def _field(text: str) -> QLabel:
    """A field label above an input in the rail."""
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[700]};font-size:12px;font-weight:600;"
                      f"background:transparent;")
    return lab


def _setting(text: str, control: QWidget) -> QWidget:
    """One run setting as a row — its name, and a compact control on the right —
    the way the refine rail's "Minimum fit" reads, so a narrow rail never has to
    split two spin boxes into slivers. The label is kept on the row (`.name`)
    because a setting can be renamed by what it now costs: "Source up to"
    becomes "Reveal up to" when the source charges per person."""
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.setSpacing(theme.SPACE_2)
    lab = QLabel(text)
    lab.setStyleSheet(f"color:{theme.NEUTRAL[800]};font-size:13px;font-weight:500;"
                      f"background:transparent;")
    h.addWidget(lab, 1)
    if isinstance(control, QSpinBox):
        control.setFixedWidth(104)
    h.addWidget(control)
    row.name = lab
    return row


def _segment(name: str) -> QFrame:
    """A segmented switch — a well with the chosen half lifted onto a card,
    its QHBoxLayout ready for the buttons. Scoped by object name on purpose:
    unscoped, the global style.qss would make each half a 34px-tall button and
    the pair would dwarf the rail it sits in."""
    seg = QFrame()
    seg.setObjectName(name)
    seg.setAttribute(Qt.WA_StyledBackground, True)
    seg.setStyleSheet(
        f"QFrame#{name}{{background:{theme.WELL};border:1px solid {theme.HAIRLINE};"
        f"border-radius:{theme.R_CONTROL}px;}}"
        f"QFrame#{name} QPushButton{{background:transparent;border:none;"
        f"color:{theme.NEUTRAL[600]};padding:5px 8px;min-height:22px;"
        f"font-size:13px;font-weight:600;border-radius:{theme.R_CHIP}px;}}"
        f"QFrame#{name} QPushButton:checked{{background:{theme.CARD};"
        f"color:{theme.TEXT};}}"
        f"QFrame#{name} QPushButton:disabled{{color:{theme.NEUTRAL[400]};}}")
    lay = QHBoxLayout(seg)
    lay.setContentsMargins(3, 3, 3, 3)
    lay.setSpacing(2)
    return seg


class _Line(QLabel):
    """A status / summary line that takes no vertical space until it has
    something to say — so an empty run leaves no grey band above the cockpit."""

    def __init__(self, level: str = "SUPPORT", on_change=None, ink: str = "",
                 weight: int = 0):
        super().__init__("")
        family, px, css_weight, default_ink = theme.TYPE.get(level, theme.T_BODY)
        self.setStyleSheet(
            f"font-family:'{family}';font-size:{px}px;"
            f"font-weight:{weight or css_weight};color:{ink or default_ink};"
            f"background:transparent;border:none;")
        self.setWordWrap(True)
        self.setVisible(False)
        self._on_change = on_change

    def setText(self, text: str):
        super().setText(text or "")
        self.setVisible(bool((text or "").strip()))
        if self._on_change is not None:
            self._on_change()


class _SearchSettings(PrismDialog):
    """Apollo's "Search settings", Prism's way: what every search on the
    People page runs with — which database, how far a search goes, how many
    it qualifies and verifies, what you sell, the keys, the claims file. The
    workbench owns every control in here (they are its attributes, read by
    the run exactly as before); this dialog is only where they live, built
    once and kept, so a setting survives closing it."""

    def __init__(self, parent=None):
        super().__init__(i18n.t("Search settings"),
                         i18n.t("What every search on the People page runs with"),
                         icon="sliders", parent=parent, scrollable=True)
        self.footer.set_primary(self.button(i18n.t("Done"), "primary",
                                            on_click=self.accept))
        self.resize(560, 680)


class LeadsWorkbench(QWidget):
    """The full Leads & Outreach surface as one widget — setup, cockpit and all
    the actions. Host it in a panel (full-window) or a dialog; it behaves the
    same, and needs only a cfg dict."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        # One kind of run now: a search. Importing a sheet is Import ▾, and an
        # old session saved as "sheet" still opens (sessions.MODES).
        self._mode = "icp"
        self._source = "exa"                # _build_inputs picks by the keys set
        self._claims_path = ""
        # Find People (addons/leads/pool.py): everyone Prism holds, and how the
        # page shows them. The pool is saved contacts + every run, one row per
        # person; the page is it filtered (the rail + Search people), split
        # (Total / Net New / Saved), sorted and paged, 25 at a time.
        self._contacts: list = []           # contacts.Contact, as last read
        self._runs: dict = {}               # session id → (id, when, leads, dossiers, drafts)
        self._people: list = []             # pool.build(contacts, runs)
        self._tab = "total"
        self._sort = "relevance"
        self._page = 0
        self._query = ""
        self._scope = ""                    # a session id: People shows only that run
        # What the result on screen IS (filters, tab, search box, scope): the
        # selection is cleared when it changes, kept across pages and sorts.
        self._result_sig = None
        self._accounts: dict = {}           # tuple of import ids → resolve_accounts(...)
        # The saved accounts (accounts.py), for the Stage / Lists / Custom
        # fields filters' account side — and an index of them, since the page
        # asks once per person on every filter change.
        from addons.leads import accounts as AC
        self._saved_accounts: list = []
        self._account_index = AC.Index()
        # The people taken off the list (removed.py): the records, and the
        # keys the pool and Send all / Export sheets leave out. _undo_ids is
        # the last Remove, while its notice (and Undo) is up.
        self._removed: list = []
        self._removed_keys = frozenset()
        self._undo_ids: list = []
        self._undo_text = ""
        self._pool_worker = None
        self._drafts = []
        self._draft_by = {}
        self._res = None
        self._worker = None
        self._send_worker = None
        self._export_worker = None
        self._verify_worker = None
        self._email_worker = None
        self._qualify_worker = None
        self._enrich_worker = None
        # The person panel's Enrichment picks, run one after another: each
        # step is a job, and a job refuses to start while another runs.
        self._enrich_queue: list = []
        # Apollo's own words when its API refused this plan or key scope, and
        # the key it refused (held in memory only — the config keeps a flag,
        # never a key). Empty = Apollo is on offer.
        self._apollo_blocked = ""
        self._blocked_key = ""
        self._announce_export = False
        self._opened_autosave = False
        # How many background jobs (prepare / verify / send / export) are running.
        # A count, not a flag: an export finishing must not re-enable Send while a
        # send started from the bulk bar is still going — two sends would mail the
        # same prospect twice.
        self._jobs = 0
        # The session on screen. Every finished run becomes one (sessions.py);
        # "" until then. _next_* hold the inputs of the run in flight.
        self._session_id = ""
        self._session_mode = "sheet"
        self._run_params: dict = {}
        self._next_mode, self._next_params = "sheet", {}
        self._load_worker = None
        self._restoring = ""
        # The saved search on the rail ("Use search" or "Save search"), and its
        # filters as saved: a finished run is recorded on it only while the
        # filters still say what it saved.
        self._active_search_id = ""
        self._active_search_filters = None

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(theme.SPACE_5, theme.SPACE_4,
                                      theme.SPACE_5, theme.SPACE_5)
        self._root.setSpacing(theme.SPACE_3)
        self._build_actions()
        self._build_inputs()
        self._build_results()
        self._refresh_prepare()
        self._refresh_imports()
        # The balance and the price list, read once the screen is up (and again
        # after every run and whenever the screen is shown) — never on the way in.
        QTimer.singleShot(0, self, self._refresh_credits)

    # ── batch actions (placed by the host) ────────────────────────────────────
    def _build_actions(self):
        """Export sheets and Send all act on the whole run, so they belong in the
        host's chrome — the page header, or a dialog footer — not in this layout.
        They are built here (their handlers and enabled state live here) and the
        host places them via action_buttons()."""
        self._export_btn = C.button(i18n.t("Export sheets"), "secondary",
                                    icon_name="file", on_click=self._export)
        self._export_btn.setEnabled(False)
        self._send_btn = C.button(i18n.t("Send all"), "primary",
                                  on_click=self._on_send)
        self._send_btn.setEnabled(False)
        # The credit pool's balance, beside the actions it pays for. Built
        # always (its handlers live here) and placed only when Leads runs on
        # the pool — see credits_button().
        self._credits_btn = C.button(i18n.t("Credits"), "tertiary",
                                     on_click=self._show_credits)
        self._credits_btn.setToolTip(i18n.t(
            "Your credits — every paid lookup Leads makes is charged to them. "
            "Click for the price list."))
        self._credits_worker = None
        self._credit_popover = None             # the "Team credit usage" card, built on first click
        self._credit_dlg = None                 # the Credit usage page, while open
        self._upgrade_dlg = None                # the Upgrade flow, while open
        self._credit_status: dict = {}          # the last balance / price list read
        self._credits_error = ""

    def action_buttons(self) -> list:
        return [self._export_btn, self._send_btn]

    def credits_button(self):
        """The balance pill, for the host's page header — None when Leads runs
        on the developer's own keys (PRISM_LEADS_DIRECT), where there is no
        pool to show."""
        return self._credits_btn if gateway.pooled() else None

    # ── credits: the pool every paid lookup is charged to ─────────────────────
    # Leads holds no provider key. Each lookup goes to Prism's licence server
    # (prospector/gateway.py), which charges the customer's credits and makes
    # the call. This screen's part: show the balance, say what an action will
    # cost BEFORE it runs (in credits, from the server's own price list), and
    # say so plainly when a run stops because the pool ran dry.
    @staticmethod
    def _pooled() -> bool:
        return gateway.pooled()

    @staticmethod
    def _cr(n: int) -> str:
        """"1 credit" / "1,240 credits"."""
        n = int(n)
        return i18n.t("1 credit") if n == 1 else i18n.t("{n} credits").format(n=f"{n:,}")

    def _refresh_credits(self) -> None:
        """Read the balance and the price list off the UI thread. One read at a
        time, and none at all on the developer's own keys."""
        if not self._pooled() or self._credits_worker is not None:
            return
        self._credits_worker = CreditsWorker()
        self._credits_worker.done.connect(self._on_credits)
        self._credits_worker.failed.connect(self._on_credits_failed)
        self._credits_worker.start()

    def _on_credits(self, status: dict) -> None:
        self._credits_worker = None
        self._credit_status = dict(status or {})
        self._credits_error = ""
        self._sync_credits()
        self._refresh_prepare()             # the cost under Find new people uses the price list

    def _on_credits_failed(self, why: str) -> None:
        self._credits_worker = None
        self._credits_error = why or i18n.t("Couldn't read your credits.")
        self._sync_credits()

    def _balance(self):
        """The credits left, as last read — None until the server has said."""
        if self._credit_status.get("balance") is not None:
            return int(self._credit_status["balance"])
        return gateway.known_balance()

    def _sync_credits(self) -> None:
        balance = self._balance()
        self._credits_btn.setText(self._cr(balance) if balance is not None
                                  else i18n.t("Credits"))
        # Running low reads at a glance: less than three searches' worth is red,
        # and the tooltip says what to do.
        low = balance is not None and balance < 3 * max(1, gateway.rate("people_search", 3))
        self._credits_btn.setStyleSheet(
            f"QPushButton{{color:{theme.ERR_INK};font-weight:600;}}" if low else "")
        tip = [self._credits_error] if self._credits_error else []
        if low:
            tip.append(i18n.t("You're nearly out of credits — click to ask for more.")
                       if balance > 0 else
                       i18n.t("You're out of credits — click to ask for more."))
        tip.append(i18n.t("Every paid lookup is charged to your credits. Click to see "
                          "how many are left, what they were spent on, and how to get more."))
        self._credits_btn.setToolTip("\n".join(tip))

    def _show_credits(self) -> None:
        """The pill's click: Apollo's small "Team credit usage" card — how much is
        used, how many are left, and Upgrade plan / View usage. One popover, kept
        and re-read each time, so clicking the pill never piles up widgets."""
        self._refresh_credits()
        pop = self._credit_popover
        if pop is None:
            pop = self._credit_popover = CreditPopover(self)
            pop.card.usageRequested.connect(self._open_credit_usage)
            pop.card.upgradeRequested.connect(self._open_upgrade)
        pop.card.set_loading()
        worker = CreditsCallWorker("usage")
        worker.done.connect(pop.show_usage)
        worker.failed.connect(pop.show_error)
        worker.start()
        pop.open_below(self._credits_btn)

    def _open_credit_usage(self) -> None:
        """View usage: the Credit usage page (Overview, Usage details, About
        credits). Opened with open(), like Search settings, so the screen stays alive."""
        dlg = self._credit_dlg = CreditUsageDialog(self._credit_status.get("rates") or {}, self)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.upgradeRequested.connect(self._open_upgrade)
        dlg.destroyed.connect(lambda *_: setattr(self, "_credit_dlg", None))
        dlg.open()

    def _open_upgrade(self) -> None:
        """Upgrade plan / Add more credits: Select plan, Add-ons, Payment, Review —
        which ends in a request to Alphakore, since nothing here takes a card."""
        dlg = self._upgrade_dlg = UpgradeDialog(self)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.destroyed.connect(lambda *_: setattr(self, "_upgrade_dlg", None))
        dlg.open()

    def _balance_line(self) -> str:
        balance = self._balance()
        return "" if balance is None else i18n.t("You have {c}.").format(c=self._cr(balance))

    def _pool_blocker(self, op: str) -> str:
        """Why a paid action cannot start right now, in words — or ''. Said
        before a worker spends a thread finding out."""
        if gateway.outdated():
            return i18n.t(gateway.OUTDATED_MESSAGE)
        if not gateway.ready(op):
            return i18n.t("That lookup isn't switched on yet — contact Alphakore "
                          "and we'll turn it on. You haven't been charged.")
        balance = self._balance()
        if balance is not None and balance <= 0:
            return i18n.t("You have no credits left. Ask Alphakore to top up and "
                          "it will run straight away.")
        return ""

    def _confirm_pool(self, title: str, lines: list) -> bool:
        """"This will cost about N credits — go?", with the balance under it.
        The owner approves every credit (23-Sep-2026); the wording changed with
        the pool, the rule did not."""
        balance_line = self._balance_line()
        if balance_line:
            lines = list(lines) + [balance_line]
        answer = QMessageBox.question(
            self, title, "\n\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _used_note(self) -> str:
        """"   ·   96 credits used" for the end of a run's line — and, when the
        pool ran dry, why the run stopped short."""
        if not self._pooled():
            return ""
        parts = []
        used = gateway.used()
        if used:
            parts.append(i18n.t("{c} used").format(c=self._cr(used)))
        if gateway.exhausted():
            parts.append(i18n.t("stopped: out of credits — ask Alphakore to top up"))
        return ("   ·   " + "   ·   ".join(parts)) if parts else ""

    # ── what a search runs with: the filters, Find new people, Search settings ─
    def _build_inputs(self):
        """Apollo's layout (23-Sep-2026):

          · the filters are the People rail's facets (FilterPanel) —
            _build_results mounts them under Total / Net New / Saved;
          · Find new people — the ONE action on the page that spends — sits
            under them, with what it will cost beside it (the owner's choice:
            filters are free and instant over the people Prism holds, fetching
            new ones is a button, never a side effect of a click);
          · everything else a search runs with — which database, how far it
            goes, how many to qualify and verify, what you sell, the keys, the
            claims file — is Search settings, a dialog the toolbar opens.

        There is no "Find people / Import a sheet" switch any more: a sheet is
        Import ▾ at the top of the page, and what it brought in is a filter."""
        self._filters = FilterPanel(suggest=_suggest)
        # Empty, as Apollo's page opens: every filter narrows everyone Prism
        # holds, so a pre-filled one would hide people nobody asked to hide.
        self._filters.set_spec(SearchSpec())
        self._filters.changed.connect(self._on_filters_changed)
        self._filters.saveRequested.connect(self._save_search)
        # The filters the owner pinned to the rail, as they left them.
        pinned = self.cfg.get("leads_pinned_filters")
        if isinstance(pinned, list):
            self._filters.set_pinned(pinned)
        self._filters.pinnedChanged.connect(
            lambda names: self._save_cfg("leads_pinned_filters", list(names)))

        # -- Find new people, at the foot of the rail ---------------------------
        self._find_panel = QWidget()
        fp = QVBoxLayout(self._find_panel)
        fp.setContentsMargins(0, 0, 0, 0)
        fp.setSpacing(theme.SPACE_1)
        # Both wired through a lambda: clicked(bool) would otherwise hand its
        # "checked" False to the first argument and turn the cheap run into
        # the expensive one.
        self._prepare = C.button(
            i18n.t("Find new people"), "primary", icon_name="search",
            on_click=lambda: self._on_prepare(leads_only=True, emails="later"))
        self._prepare.setToolTip(i18n.t(
            "Search for NEW people who match these filters — this spends "
            "searches (Exa) or credits (Apollo). No e-mail lookups and no Groq: "
            "tick rows afterwards and press Find e-mails when you want addresses."))
        fp.addWidget(self._prepare)
        self._find_meta = C.label("", level="META", wrap=True)
        fp.addWidget(self._find_meta)
        # The whole pipeline in one press — find, look up e-mails, qualify,
        # draft. Research with AI ▸ "Find new people and qualify them" presses
        # it; it never sits on the rail, which keeps ONE spending button there.
        self._prepare_all = C.button(
            i18n.t("Find and prepare"), "secondary", icon_name="mail",
            on_click=lambda: self._on_prepare(leads_only=False, emails="now"))
        self._prepare_all.setToolTip(i18n.t(
            "The whole pipeline in one run: find the people, look up their "
            "e-mails, qualify the top ones with Groq and draft a message each."))
        fp.addWidget(self._prepare_all)
        self._prepare_all.hide()

        # -- Search settings: a dialog, built once, opened from the toolbar -----
        self._settings_dlg = _SearchSettings(self)
        # Done (or its ✕) keeps the keys typed in it — see _save_keys.
        self._settings_dlg.finished.connect(lambda _result: self._save_keys())
        body = self._settings_dlg.body

        # The same filters, asked of two databases: Exa's web search (an Exa
        # call per industry) or Apollo's own people index (free to search,
        # about a credit per person revealed). Exa is the default and the
        # fallback: Apollo's search endpoints are not in its FREE plan, so an
        # owner who has only pasted a key would meet a 403, not a list.
        src = _segment("sourceSeg")
        self._src_apollo = QPushButton(i18n.t("Apollo"))
        self._src_exa = QPushButton(i18n.t("Exa"))
        for b, name in ((self._src_apollo, "apollo"), (self._src_exa, "exa")):
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, s=name: self._set_source(s))
            src.layout().addWidget(b, 1)
        # The rows are kept, not just their controls: the walkthrough points at
        # a whole setting — its name and its control — the way it is read.
        self._source_row = _setting(i18n.t("Search with"), src)
        body.addWidget(self._source_row)
        # On the credit pool Exa is the only database and nobody picks it — the
        # licence server holds the key — so the switch is built (the
        # walkthrough and the tests address it) but not shown.
        self._source_row.setVisible(not self._pooled())

        body.addWidget(_kick(i18n.t("Run settings")))
        self._target = QSpinBox()
        self._target.setRange(20, 2000)
        self._target.setValue(300)
        # Its name and tooltip belong to the source — _set_source writes both.
        self._target_row = _setting(i18n.t("Source up to"), self._target)
        body.addWidget(self._target_row)
        self._limit = QSpinBox()
        self._limit.setRange(1, 500)
        self._limit.setValue(25)
        self._limit.setToolTip(i18n.t("How many leads to qualify this run."))
        self._qualify_row = _setting(i18n.t("Qualify"), self._limit)
        body.addWidget(self._qualify_row)
        self._verify_limit = QSpinBox()
        self._verify_limit.setRange(0, 200)
        self._verify_limit.setValue(25)
        if self._pooled():
            self._verify_limit.setToolTip(i18n.t(
                "How many hot/warm addresses to find and check this run. Each "
                "one costs credits — 0 skips it."))
            self._verify_row = _setting(i18n.t("Verify"), self._verify_limit)
        else:
            self._verify_limit.setToolTip(i18n.t(
                "How many hot/warm addresses to check with Hunter. Its free tier is "
                "~50 credits a month, so keep this modest — 0 skips verification."))
            self._verify_row = _setting(i18n.t("Verify (Hunter)"), self._verify_limit)
        body.addWidget(self._verify_row)

        body.addWidget(_field(i18n.t("What you sell")))
        self._offer = QPlainTextEdit()
        self._offer.setPlainText(DEFAULT_OFFER)
        self._offer.setFixedHeight(96)
        self._offer.setToolTip(i18n.t("Every lead is qualified against this."))
        body.addWidget(self._offer)

        # Net new only: a SEARCH skips anyone an earlier session already
        # pulled, unless this is turned off to re-work an old list on purpose.
        self._skip_seen = QCheckBox(i18n.t("Only find people no earlier search found"))
        self._skip_seen.setChecked(True)
        self._skip_seen.setStyleSheet(
            f"QCheckBox{{border:none;background:transparent;color:{theme.NEUTRAL[800]};"
            f"font-size:13px;font-weight:600;}}")
        self._skip_seen.setToolTip(i18n.t(
            "People are matched by e-mail, LinkedIn link, or name and company. "
            "A search keeps looking until it has the number you asked for in "
            "new people."))
        body.addWidget(self._skip_seen)
        self._skip_meta = C.label(i18n.t("Anyone an earlier search found is skipped — "
                                         "they are on the People page already."),
                                  level="META", wrap=True)
        # Under the checkbox's text, not its box: the indicator and its gap.
        self._skip_meta.setContentsMargins(26, 0, 0, 0)
        body.addWidget(self._skip_meta)

        # Keys & claims are set once — folded away unless a key is missing.
        # "&&": a lone & in a button label is eaten as a keyboard mnemonic.
        self._keys_toggle = C.button(
            (i18n.t("Approved claims") if self._pooled()
             else i18n.t("Keys & claims").replace("&", "&&")), "link",
            icon_name="key", on_click=self._toggle_keys)
        body.addWidget(self._keys_toggle)
        self._keys_box = QWidget()
        kb = QVBoxLayout(self._keys_box)
        kb.setContentsMargins(0, 0, 0, 0)
        kb.setSpacing(theme.SPACE_1)
        self._byo_widgets = []       # the key rows: built, but not shown on the pool
        self._byo_widgets.append(_field(i18n.t("Exa API key · finds people and why-now signals")))
        kb.addWidget(self._byo_widgets[-1])
        self._exa = QLineEdit()
        self._exa.setText(self.cfg.get("exa_api_key") or "")
        self._exa.setEchoMode(QLineEdit.PasswordEchoOnEdit)   # never on screen at rest
        self._exa.setPlaceholderText(i18n.t("Needed to find people — saved once"))
        C.add_password_visibility(self._exa)
        kb.addWidget(self._exa)
        self._byo_widgets.append(self._exa)
        kb.addSpacing(theme.SPACE_1)
        self._byo_widgets.append(_field(i18n.t("Apollo API key · searches Apollo's own database")))
        kb.addWidget(self._byo_widgets[-1])
        self._apollo = QLineEdit()
        self._apollo.setText(self.cfg.get("apollo_api_key") or "")
        self._apollo.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self._apollo.setPlaceholderText(i18n.t(
            "Search Apollo's database and reveal verified emails — saved once"))
        C.add_password_visibility(self._apollo)
        kb.addWidget(self._apollo)
        self._byo_widgets.append(self._apollo)
        kb.addSpacing(theme.SPACE_2)
        self._claims = C.button(i18n.t("Approved claims file…"), "secondary",
                                icon_name="file", on_click=self._choose_claims)
        kb.addWidget(self._claims)
        self._claims_lbl = C.label(
            i18n.t("Optional — with none, the emails make no numeric claim."),
            level="META", wrap=True)
        kb.addWidget(self._claims_lbl)
        self._byo_widgets.append(C.label(i18n.t(
            "Verifier keys (Reoon, ZeroBounce, Hunter…) come from Settings > "
            "Agents — free tiers first, so most checks cost nothing."),
            level="META", wrap=True))
        kb.addWidget(self._byo_widgets[-1])
        for w in self._byo_widgets:
            w.setVisible(not self._pooled())
        body.addWidget(self._keys_box)
        body.addStretch(1)
        # A different Apollo key is a different Apollo plan, so typing one lifts
        # a block this key earned.
        self._apollo.textEdited.connect(self._on_apollo_key_typed)
        # Either key is enough to run a search, so either folds the box away.
        self._keys_box.setVisible(False if self._pooled() else not (
            self._key("exa_api_key") or self._key("apollo_api_key")))
        # Exa is the default even where an Apollo key is set: Apollo's people
        # search is not in its FREE plan (its API Keys page says so outright),
        # so offering it first sends most owners into a 403. A run that already
        # hit that wall is remembered, and Apollo is not offered at all.
        if self.cfg.get("apollo_api_blocked"):
            self._blocked_key = self._key("apollo_api_key")
            self._apollo_blocked = _apollo_blocked_text()
        self._set_source("exa")

    def _open_settings(self, keys: bool = False) -> None:
        """Search settings — the toolbar's button. `keys` unfolds the keys box
        first (a search that could not start for want of one). Window-modal
        but not blocking (open(), not exec()), so the page keeps drawing
        behind it and a test can look at it."""
        if keys:
            self._keys_box.setVisible(True)
        self._settings_dlg.open()

    def _key(self, name: str) -> str:
        return (self.cfg.get(name) or "").strip()

    # How many people a run may fetch, per source: Exa pages a web search and
    # nothing is charged per person, Apollo charges about a credit for each one
    # it reveals — so the same spin box is a budget under one and a ceiling
    # under the other, and has to say which.
    _TARGET_LABEL = {"apollo": "Reveal up to", "exa": "Source up to"}
    _TARGET_TIP = {
        "apollo": "Searching Apollo is free; revealing a person's name and "
                  "e-mail costs about one Apollo credit each — and a run "
                  "stops at this many, even when your filters leave it short.",
        "exa": "How many people to find before qualifying. Everyone outside "
               "your filters is left out and does not count.",
    }

    def _set_source(self, source: str):
        """Which database a Find-people run asks. Either can be picked with or
        without its key — Prepare says which one is missing rather than a dead
        button leaving the owner to guess. Apollo, once its API has refused
        this plan, cannot be picked at all: not by a click, and not by a
        session that was run on it before the refusal."""
        self._source = "apollo" if source == "apollo" else "exa"
        if self._source == "apollo" and (self._apollo_blocked or self._pooled()):
            self._source = "exa"            # on the pool, Exa is the only database
        self._src_apollo.setChecked(self._source == "apollo")
        self._src_exa.setChecked(self._source == "exa")
        self._sync_apollo()
        self._target_row.name.setText(i18n.t(self._TARGET_LABEL[self._source]))
        tip = i18n.t(self._TARGET_TIP[self._source])
        self._target_row.setToolTip(tip)
        self._target.setToolTip(tip)
        self._refresh_prepare()             # what Find new people now costs

    def _source_name(self) -> str:
        return i18n.t("Apollo") if self._source == "apollo" else i18n.t("Exa")

    def _sync_apollo(self):
        """The Apollo half of the switch: on offer with a tooltip saying what
        it needs, or off with Apollo's own refusal on it. Called wherever the
        switch is (re)armed — _set_running re-enables every control, and would
        otherwise hand back a button that only leads to another 403."""
        self._src_apollo.setToolTip(self._apollo_blocked or _apollo_tip())
        if self._apollo_blocked:
            self._src_apollo.setEnabled(False)

    def _on_apollo_key_typed(self, text: str):
        """A new Apollo key is a new Apollo plan, so it lifts the block the old
        key earned — the config forgets too, and the switch comes back."""
        if not self._apollo_blocked:
            return
        if (text or "").strip() and (text or "").strip() != self._blocked_key:
            self._apollo_blocked = self._blocked_key = ""
            self._save_cfg("apollo_api_blocked", False)
            self._src_apollo.setEnabled(not self._jobs)
            self._sync_apollo()

    def _on_source_blocked(self, why: str):
        """Apollo turned the run down on its PLAN or the key's scope. One
        refusal is enough: the rail goes back to Exa, the Apollo half is
        switched off carrying Apollo's own words, and the config remembers — a
        flag, never the key — so the next launch does not offer the same wall."""
        if self._job_done():
            self._set_running(False)
        self._apollo_blocked = why or _apollo_blocked_text()
        self._blocked_key = self._key("apollo_api_key")
        self._src_apollo.setEnabled(False)
        self._set_source("exa")
        self._save_cfg("apollo_api_blocked", True)
        self._status.setText(i18n.t(
            "Apollo refused this key — its people search needs a paid Apollo "
            "plan. Switched to Exa; hover Apollo for what it said."))

    def _toggle_keys(self):
        self._keys_box.setVisible(self._keys_box.isHidden())

    def _sync_notice(self):
        notice, summary = getattr(self, "_notice", None), getattr(self, "_summary", None)
        undo = getattr(self, "_undo_btn", None)
        if undo is not None:
            # Undo belongs to the Remove it follows: any later message retires it.
            undo.setVisible(bool(self._undo_ids) and self._status.text() == self._undo_text)
        if notice is not None and summary is not None:
            notice.setVisible(not (self._status.isHidden() and summary.isHidden()))

    def _search_spec(self):
        """(spec, companies, note, marks) for the paid search the rail's
        filters ask — or (None, [], why, {}) when they ask nobody.

        An Account CSV import is a list of COMPANIES: the search asks Exa for
        people at every company not searched yet, one search each, up to
        _COMPANIES_PER_PRESS (_account_batch), and with no job title or
        seniority of the owner's own it asks for the decision-makers
        (_company_search_spec). The spec's Current company facet holds the
        first MAX_FACET_VALUES; `companies` is all of them, which the worker
        asks in groups of that size. `marks` is how far each import will have
        been searched as the groups are asked (_on_companies_asked). A Contact
        CSV import is people already held: nothing to search for."""
        spec = self._filters.spec()
        companies, note, marks = [], "", {}
        if spec.account_imports:
            companies, marks, note = self._account_batch(spec.account_imports)
            if not companies:
                return None, [], i18n.t(
                    "The chosen account import holds no companies."), {}
            spec = _company_search_spec(spec)
            spec.companies.include = list(companies[:MAX_FACET_VALUES])
            spec.account_imports = []
        spec.contact_imports = []           # people already held — not a search term
        if not spec.is_searchable():
            return None, [], i18n.t(
                "Add a job title, seniority or function — a search needs someone "
                "to look for."), {}
        return spec, companies, note, marks

    def _account_batch(self, import_ids):
        """(companies, marks, note): every company of the chosen Account CSV
        imports not searched yet — up to _COMPANIES_PER_PRESS — each import
        walked on from where its last search stopped (imports.mark_searched —
        on disk, so a restart does not pay for the same companies twice), a
        company already searched in another of them skipped. `marks` is
        {"order": [(import id, searched up to)] — one per company, in order —
        "final": {import id: searched up to} once all of them are asked}: an
        import moves on as its companies really are asked
        (_on_companies_asked), never ahead of them. When every company has
        been searched, the batch starts again from the first, and the note
        says so — the confirmation before the search repeats it."""
        from addons.leads import imports as IM
        folder = self._imports_dir()
        records = [r for r in (IM.get(folder, i) for i in import_ids)
                   if r is not None and r["kind"] == "accounts"]
        total = sum(len(r["companies"]) for r in records)
        done = sum(r["searched"] for r in records)
        restart = bool(total) and done >= total

        def name_of(c) -> str:
            return (c.get("name") or c.get("domain") or "").strip()

        seen = set()
        if not restart:                     # what earlier batches already asked
            for r in records:
                seen.update(name_of(c).casefold() for c in r["companies"][:r["searched"]])
        companies, order, walked = [], [], 0
        final = {r["id"]: 0 for r in records} if restart else {}
        for r in records:
            start = 0 if restart else r["searched"]
            upto = start
            for i in range(start, len(r["companies"])):
                if len(companies) >= _COMPANIES_PER_PRESS:
                    break
                name = name_of(r["companies"][i])
                upto = i + 1
                if name and name.casefold() not in seen:
                    seen.add(name.casefold())
                    companies.append(name)
                    order.append((r["id"], upto))
            walked += upto - start
            if upto != start:
                final[r["id"]] = upto
        marks = {"order": order, "final": final} if companies else {}
        first = (0 if restart else done) + 1
        note = i18n.t("companies {a}–{b} of {n} from the import").format(
            a=first, b=first + walked - 1, n=total)
        if restart:
            note += " · " + i18n.t("every company was searched before — this starts "
                                   "again from the first")
        return companies, marks, note

    def _estimate(self, spec, companies=()) -> int:
        """How many Exa searches this search makes to start with."""
        return self._searches(spec, companies)[0]

    def _searches(self, spec, companies=()) -> tuple:
        """(first, more): the Exa searches a press makes to start with, and
        the most it may add when too few new people come back — worked out
        the way the search itself will do it (source.planned_searches), not
        guessed (24-Sep-2026: the box said "about 200" of a press that stopped
        at 60). Over an import's companies: one a company, nothing more."""
        try:
            from prospector import filters as F
            from prospector import source as S
            if companies:
                return sum(len(F.plan(part)) for part in F.company_chunks(spec, companies)), 0
            return S.planned_searches(spec)
        except Exception:                                   # noqa: BLE001
            return 0, 0

    def _refresh_prepare(self):
        """Find new people: armed when the filters ask for somebody, with what
        it will cost under it — the owner approves every credit (23-Sep-2026)."""
        spec, _companies, note, _marks = self._search_spec()
        ok = spec is not None
        # Never re-armed mid-run: the filters stay live while a search runs,
        # and an edit to them must not hand back a button a job is holding.
        self._prepare.setEnabled(ok and not self._jobs)
        self._prepare_all.setEnabled(ok and not self._jobs)
        if not ok:
            self._find_meta.setText(note)
            return
        if self._pooled():
            text = self._pool_search_meta(spec, _companies)
        elif self._source == "apollo":
            text = i18n.t("Searches Apollo — about a credit per person revealed")
        else:
            n, more = self._searches(spec, _companies)
            if not n:
                text = i18n.t("Searches Exa")
            elif _companies:
                text = (i18n.t("1 Exa search — one company") if n == 1 else
                        i18n.t("{n} Exa searches — one per company").format(n=n))
            elif more:
                text = i18n.t("About {n} Exa searches — up to {m} more if too few "
                              "come back").format(n=n, m=more)
            else:
                text = i18n.t("About {n} Exa searches").format(n=n)
        if note:
            text += " · " + note
        self._find_meta.setText(text)

    def _pool_search_meta(self, spec, companies) -> str:
        """The line under Find new people, in credits: "About 30 searches — 90
        credits". Each search costs what the server's price list says (3 until
        the owner sets it), and a search that finds nobody is not charged — so
        this is a ceiling, and the words say "up to"."""
        n, more = self._searches(spec, companies)
        if not n:
            return i18n.t("Searches for new people")
        price = gateway.rate("people_search", 3)
        if companies:
            return (i18n.t("1 search — up to {c}").format(c=self._cr(price)) if n == 1 else
                    i18n.t("{n} searches, one per company — up to {c}").format(
                        n=n, c=self._cr(n * price)))
        if more:
            return i18n.t("About {n} searches — up to {c}, and up to {m} more searches "
                          "if too few new people come back").format(
                              n=n, c=self._cr(n * price), m=more)
        return i18n.t("About {n} searches — up to {c}").format(n=n, c=self._cr(n * price))

    def _find_prepare_ready(self):
        """(ok, why) for Research with AI ▸ "Find new people and qualify
        them" — the whole pipeline, armed when Find new people is."""
        if self._jobs:
            return False, i18n.t("Wait for the current job to finish.")
        return self._prepare_all.isEnabled(), self._find_meta.text()

    # ── the guided walkthrough points at these ────────────────────────────────
    def help_targets(self) -> dict:
        """The parts the "?" tour can ring, by the key it asks for: the real
        widgets, never a copy — Find new people, and the run line once it has
        something to say. A part not on screen right now is left out, and
        the tour skips that step. The filters and the cockpit answer for
        themselves."""
        out = {"btn_find": self._prepare, "notice": self._notice}
        return {k: w for k, w in out.items() if w.isVisibleTo(self)}

    def help_reveal(self, key: str) -> None:
        """Make one part reachable: the People tab, and its rail unfolded and
        scrolled to. It starts no run, changes no filter and writes no config
        — an owner who walks the tour comes back to exactly the search they
        had.

        The lead filters' keys are answered here too, for the unfolding only:
        they sit in the People rail, which the filter panel can neither see
        nor bring back — with Hide filters on, every facet step was skipped."""
        if key not in _HELP_KEYS and key not in _FILTER_HELP_KEYS:
            return
        self._cockpit.help_reveal("tab_people")     # the rail is on the People tab
        if key == "notice":
            return                                  # over the tabs, not in the rail
        self._cockpit.leads.set_filters_shown(True)  # Hide filters folds it away
        widget = self.help_targets().get(key)
        if widget is not None:
            reveal_in_scroll(widget)

    # ── the tabbed cockpit ────────────────────────────────────────────────────
    def _build_results(self):
        # One slim notice line over the workspace: live progress on the left
        # ("Qualifying 3 of 25…"), the run summary on the right (hot/warm/cold,
        # drafted, why-now coverage). Takes no space until it has something.
        self._notice = QFrame()
        self._notice.setObjectName("leadsNotice")
        self._notice.setAttribute(Qt.WA_StyledBackground, True)
        self._notice.setStyleSheet(
            f"QFrame#leadsNotice{{background:{theme.CARD};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;}}")
        nl = QHBoxLayout(self._notice)
        nl.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        nl.setSpacing(theme.SPACE_4)
        # Something is running: the ring and its clock, beside the words.
        self._busy_ring = Loader("ring", compact=True)
        self._busy_ring.setVisible(False)
        nl.addWidget(self._busy_ring)
        self._status = _Line("SUPPORT", on_change=self._sync_notice,
                             ink=theme.TEXT, weight=600)
        self._summary = _Line("SUPPORT", on_change=self._sync_notice)
        self._summary.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        nl.addWidget(self._status, 1)
        # An opened session narrows People to its own people; this widens it.
        self._scope_btn = C.button(i18n.t("Show everyone"), "link",
                                   on_click=self.clear_scope)
        self._scope_btn.hide()
        nl.addWidget(self._scope_btn)
        # Right after a Remove: put them straight back.
        self._undo_btn = C.button(i18n.t("Undo"), "link", on_click=self._undo_remove)
        self._undo_btn.hide()
        nl.addWidget(self._undo_btn)
        nl.addWidget(self._summary, 1)
        self._notice.setVisible(False)
        self._root.addWidget(self._notice)
        # The workspace: People · Sessions · Lists · Saved searches · Sequences
        # · Analytics. People is Apollo's Find People: the filters are its
        # rail's facets, Find new people sits under them, and the page shows
        # the pool — every person Prism holds — filtered as you click.
        self._cockpit = LeadsWorkspace(leads_folder=self._autosave_dir(),
                                       sessions_folder=self._sessions_dir(),
                                       searches_folder=self._searches_dir())
        self._cockpit.openSessionRequested.connect(self.open_session)
        self._cockpit.useSavedSearchRequested.connect(self.use_saved_search)
        self._cockpit.deleteSavedSearchRequested.connect(self._delete_saved_search)
        self._cockpit.verifyRequested.connect(self._verify_selected)
        self._cockpit.emailsRequested.connect(self._find_emails)
        self._cockpit.phonesRequested.connect(self._find_phones)
        self._cockpit.saveListRequested.connect(self._save_list)
        self._cockpit.exportRequested.connect(self._export_selected)
        self._cockpit.sequenceRequested.connect(self._add_to_sequence)
        self._cockpit.qualifyRequested.connect(self._qualify_selected)
        self._cockpit.saveContactsRequested.connect(self._save_contacts)
        self._cockpit.stageRequested.connect(self._set_stage_selected)
        self._cockpit.removeRequested.connect(self._remove_selected)
        self._cockpit.removedRequested.connect(self._open_removed)
        self._cockpit.importRequested.connect(self._import)
        self._cockpit.tabChanged.connect(self._on_tab)
        self._cockpit.pageRequested.connect(self._on_page)
        self._cockpit.sortChanged.connect(self._on_sort)
        self._cockpit.queryChanged.connect(self._on_query)
        self._cockpit.settingsRequested.connect(lambda: self._open_settings())
        self._cockpit.saveSearchRequested.connect(self._save_search)
        self._cockpit.findPrepareRequested.connect(self._prepare_all.click)
        self._cockpit.starterPicked.connect(self.use_starter)
        self._cockpit.leads.set_find_prepare_ready(self._find_prepare_ready)
        self._cockpit.leads.set_starters(
            [(key, i18n.t(name)) for key, (name, _make) in _STARTERS.items()])
        self._cockpit.set_search_panel(self._filters)
        self._cockpit.set_find_panel(self._find_panel)
        # The person panel (Apollo's contact profile): what it shows comes from
        # here, and every act on it is carried out here, on the stores.
        leads = self._cockpit.leads
        leads.set_person_provider(self._person_view)
        pp = leads.person_panel
        pp.saveRequested.connect(self._panel_save)
        pp.stageRequested.connect(self._panel_stage)
        pp.accountStageRequested.connect(self._panel_account_stage)
        pp.accountSaveRequested.connect(self._panel_account_save)
        pp.noteRequested.connect(self._panel_note)
        pp.taskRequested.connect(self._panel_task)
        pp.taskDoneRequested.connect(self._panel_task_done)
        pp.logRequested.connect(self._panel_log)
        pp.editRequested.connect(self._panel_edit)
        pp.flagRequested.connect(self._panel_flag)
        pp.deleteRequested.connect(self._panel_delete)
        pp.listRequested.connect(lambda dos: self._save_list([dos]))
        pp.sequenceRequested.connect(lambda dos: self._add_to_sequence([dos]))
        pp.enrichRequested.connect(self._panel_enrich)
        frame = QFrame()
        frame.setObjectName("leadsFrame")
        frame.setAttribute(Qt.WA_StyledBackground, True)
        frame.setStyleSheet(f"QFrame#leadsFrame{{background:{theme.CARD};"
                            f"border:1px solid {theme.HAIRLINE};}}")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(1, 1, 1, 1)
        fl.setSpacing(0)
        fl.addWidget(self._cockpit)
        self._root.addWidget(frame, stretch=1)

    def refresh_lists(self) -> None:
        """Re-scan the saved-lists folder — the panel calls this when the screen
        is shown again, so a list saved elsewhere appears."""
        if getattr(self, "_cockpit", None) is not None:
            self._cockpit.refresh_lists()
        self._refresh_credits()             # a top-up since the screen was last shown

    # ── Find People: the pool, and the page over it ──────────────────────────
    def _contacts_dir(self) -> str:
        """This member's saved contacts (Apollo's Saved), beside their Leads
        sessions (see _sessions_dir). Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "contacts")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "contacts")

    def _imports_dir(self) -> str:
        """This member's CSV imports (the two CSV-import filters' values),
        beside their Leads sessions. Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "imports")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "imports")

    def _refresh_imports(self) -> None:
        """Hand the rail's two CSV-import facets the imports there are."""
        from addons.leads import imports as IM
        folder = self._imports_dir()
        self._filters.set_imports(IM.list_imports(folder, "contacts"),
                                  IM.list_imports(folder, "accounts"))
        self._accounts = {}

    def reload_pool(self) -> None:
        """Read every saved contact and every past run, off the UI thread, and
        put the page back over them (_on_pool_loaded)."""
        from addons.leads.workers import LeadsPoolWorker
        self._pool_worker = LeadsPoolWorker(self._contacts_dir(), self._sessions_dir(),
                                            self._accounts_dir(), self._removed_dir())
        self._pool_worker.accounts_read.connect(self._set_saved_accounts)
        self._pool_worker.removed_read.connect(self._set_removed)
        self._pool_worker.done.connect(self._on_pool_loaded)
        self._pool_worker.failed.connect(
            lambda msg: self._status.setText(
                i18n.t("Couldn't read everyone Prism has found: {err}").format(err=msg)))
        self._pool_worker.start()

    def _on_pool_loaded(self, contacts, runs):
        self._contacts = list(contacts or ())
        loaded = {r[0]: r for r in runs or ()}
        # The run on screen keeps ITS objects: the workers verify, enrich and
        # qualify those leads in place, and a copy read from disk would not
        # see it happen.
        if self._res is not None:
            loaded[self._session_id] = self._run_tuple()
        self._runs = loaded
        self._rebuild_pool()

    def _run_tuple(self):
        """The run on screen as a pool run: (id, when, leads, dossiers,
        drafts, params) — params so the pool knows what its search was
        steered by (pool._steering)."""
        created = ""
        current = self._runs.get(self._session_id)
        if current is not None:
            created = current[1]
        return (self._session_id, created or datetime.datetime.now().astimezone()
                .isoformat(timespec="seconds"),
                list(getattr(self._res, "all_leads", None) or []),
                list(self._res.dossiers or []), list(self._drafts),
                dict(self._run_params))

    def _rebuild_pool(self) -> None:
        self._pool_changed()
        self._refilter()

    def _pool_changed(self) -> None:
        """The pool from the contacts and runs in hand — and what the Stage,
        Lists and Custom fields filters can offer from it."""
        self._people = P.without(P.build(self._contacts, self._runs.values()),
                                 self._removed_keys)
        self._filters.set_record_options(P.record_options(self._people,
                                                          self._saved_accounts))

    def _set_saved_accounts(self, accounts) -> None:
        from addons.leads import accounts as AC
        self._saved_accounts = list(accounts or ())
        self._account_index = AC.Index(self._saved_accounts)

    def _reload_accounts(self) -> None:
        """Re-read the saved accounts after something here wrote them."""
        from addons.leads import accounts as AC
        self._set_saved_accounts(AC.list_accounts(self._accounts_dir()))

    def _accounts_for(self, spec) -> dict:
        """pool.resolve_accounts for the chosen Account CSV imports, cached
        per choice — a click re-filters the pool, it should not re-read the
        imports file every time."""
        key = tuple(sorted(spec.account_imports))
        if not key:
            return {}
        if key not in self._accounts:
            from addons.leads import imports as IM
            self._accounts[key] = P.resolve_accounts(
                IM.companies_of(self._imports_dir(), key))
        return self._accounts[key]

    def _refilter(self, keep_page: bool = False) -> None:
        """The page: the pool filtered (rail + Search people), split into
        Total / Net New / Saved, sorted, and the chosen page of 25 shown."""
        if not keep_page:
            self._page = 0
        spec = self._filters.spec()
        people = self._people
        if self._scope:
            people = [p for p in people if self._scope in p.sessions]
        matched = P.filter_people(people, spec, accounts=self._accounts_for(spec),
                                  query=self._query, saved_accounts=self._account_index)
        tabs = P.split(matched)
        counts = {k: len(v) for k, v in tabs.items()}
        rows = P.sort_people(tabs.get(self._tab, tabs["total"]), self._sort)
        info = P.page(rows, self._page)
        # A new search starts with nobody selected, as Apollo's does; another
        # page, another sort or the pool re-read keeps whoever was.
        import json
        signature = (json.dumps(spec.to_dict(), sort_keys=True), self._tab,
                     self._query, self._scope)
        if signature != self._result_sig:
            self._result_sig = signature
            self._cockpit.leads.clear_selection()
        self._page = info["page"]
        if not self._people:
            empty = None                    # the cockpit's own "No people yet"
        elif not rows:
            from addons.leads.cockpit import _NO_MATCH_BODY, _NO_MATCH_TITLE
            empty = (_NO_MATCH_TITLE, _NO_MATCH_BODY)
        else:
            empty = None
        self._cockpit.leads.set_empty_text()
        self._cockpit.set_people(info["rows"], info, counts, empty, universe=rows)
        self._cockpit.leads.set_filter_count(spec.active_count())

    def _on_filters_changed(self):
        self._refresh_prepare()
        self._refilter()

    def _on_tab(self, key: str):
        self._tab = key if key in ("total", "net_new", "saved") else "total"
        self._refilter()

    def _on_page(self, index: int):
        self._page = max(0, int(index))
        self._refilter(keep_page=True)

    def _on_sort(self, key: str):
        self._sort = key if key in P.SORTS else "relevance"
        self._refilter()

    def _on_query(self, text: str):
        self._query = (text or "").strip()
        self._refilter()

    def clear_scope(self) -> None:
        """Back to everyone, from one run's people (an opened session)."""
        self._scope_btn.hide()
        if self._scope:
            self._scope = ""
            self._status.setText("")
            self._refilter()

    # ── Apollo's "Save": people become contacts ──────────────────────────────
    def _keep_as_contacts(self, leads, via: str, list_name: str = "") -> bool:
        """Save these people as contacts — Apollo's rule that acting on
        someone (exporting them, sequencing them, finding their e-mail) saves
        them, and the one place such an action's result outlives a run that is
        not the one on screen. Their newest fields are written over the saved
        record; `list_name` is added to each (Add to list). True when the page
        was rebuilt. Never raises into the UI."""
        leads = [l for l in leads or () if l is not None]
        if not leads:
            return False
        try:
            from addons.leads import contacts as CT
            from prospector.identity import keys_of
            CT.save(self._contacts_dir(), leads, via=via, update=True,
                    list_name=list_name)
        except Exception as e:                              # noqa: BLE001
            self._status.setText(str(e) or i18n.t("Couldn't save these contacts."))
            return False
        # In memory, the SAME Lead objects become the contacts — not copies
        # read back from disk — so a row on screen stays the object the
        # workers verify and enrich in place, and the page stays consistent.
        # Someone already saved gets the new fields in memory too, as the
        # file just did (contacts.merge), or a filter would read the old ones.
        by_key: dict = {}
        for c in self._contacts:
            for key in keys_of(c.lead):
                by_key.setdefault(key, c)
        when = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
        for lead in leads:
            keys = keys_of(lead)
            if not keys:
                continue
            hit = next((by_key[k] for k in keys if k in by_key), None)
            if hit is None:
                hit = CT.Contact(lead=lead, saved_at=when, updated_at=when, via=[via])
                self._contacts.append(hit)
            elif hit.lead is not lead:
                CT.merge(hit.lead, lead)
            if list_name and list_name not in hit.lists:
                hit.lists.append(list_name)
            for key in keys:
                by_key.setdefault(key, hit)
        self._rebuild_pool_keep_page()
        return True

    def _advance_stage(self, leads, to: str, only_from) -> int:
        """contacts.advance_stage, mirrored on the contacts in memory. Never
        raises into the UI."""
        from addons.leads import contacts as CT
        from prospector.identity import keys_of
        try:
            moved = CT.advance_stage(self._contacts_dir(), leads, to, only_from)
        except Exception as e:                              # noqa: BLE001
            self._status.setText(str(e) or i18n.t("Couldn't update the stages."))
            return 0
        wanted = set()
        for lead in leads:
            wanted.update(keys_of(lead))
        for contact in self._contacts:
            if contact.stage in only_from and not wanted.isdisjoint(keys_of(contact.lead)):
                contact.stage = to
        return moved

    def _rebuild_pool_keep_page(self) -> None:
        self._pool_changed()
        self._refilter(keep_page=True)

    def _save_contacts(self, dossiers):
        """The action bar's Save."""
        leads = [getattr(d, "lead", None) for d in dossiers or ()]
        leads = [l for l in leads if l is not None]
        if not leads:
            return
        self._keep_as_contacts(leads, "save")
        self._status.setText(i18n.t("Saved {n} as contacts — they're under Saved now.")
                             .format(n=len(leads)))

    def _set_stage_selected(self, dossiers, stage: str):
        """Edit > Set stage: the selected people move to `stage` — saved as
        contacts first when they are not yet, since only a contact has a
        stage (Apollo's rule that acting on a prospect saves them)."""
        from addons.leads import contacts as CT
        from prospector.identity import keys_of
        leads = [getattr(d, "lead", None) for d in dossiers or ()]
        leads = [l for l in leads if l is not None]
        stage = CT.stage_named(stage)
        if not (leads and stage) or not self._keep_as_contacts(leads, "save"):
            return
        try:
            moved = CT.set_stage_many(self._contacts_dir(), leads, stage)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        wanted = set()
        for lead in leads:
            wanted.update(keys_of(lead))
        for contact in self._contacts:
            if not wanted.isdisjoint(keys_of(contact.lead)):
                contact.stage = stage
        self._rebuild_pool_keep_page()
        self._status.setText(
            i18n.t("Moved {n} to {stage}.").format(n=moved, stage=stage) if moved
            else i18n.t("Already at {stage}.").format(stage=stage))

    # ── Remove: people off the list (removed.py) ─────────────────────────────
    # The owner, 23-Sep-2026: ticking people and pressing Clear should take
    # them away. He chose "Remove from list": out of Total, Net New and Saved,
    # out of every new search, restorable — nothing is deleted.
    def _removed_dir(self) -> str:
        """This member's removed people, beside their contacts. Tests patch
        this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "removed")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "removed")

    def _set_removed(self, records) -> None:
        """The removed list in hand — what the pool leaves out, and the
        rail's "N removed"."""
        from addons.leads import removed as RM
        self._removed = list(records or ())
        self._removed_keys = RM.keys(self._removed)
        self._cockpit.leads.set_removed_count(len(self._removed))

    def _reload_removed(self) -> None:
        from addons.leads import removed as RM
        self._set_removed(RM.list_removed(self._removed_dir()))

    def _is_removed(self, lead) -> bool:
        from prospector.identity import keys_of
        return bool(self._removed_keys) and not keys_of(lead).isdisjoint(self._removed_keys)

    def _persons_for(self, rows) -> list:
        """The pool.Person behind each row — so a removal carries every key
        their records have, not only the row's own lead's. A row the pool no
        longer holds is taken by its lead."""
        by_row = {id(p.row()): p for p in self._people}
        out = []
        for row in rows or ():
            person = by_row.get(id(row)) or getattr(row, "lead", None)
            if person is not None:
                out.append(person)
        return out

    def _confirm_remove(self, n: int) -> bool:
        """"Take 25 people off the list?" — before anyone leaves the page.
        Tests patch this."""
        who = (i18n.t("this person") if n == 1
               else i18n.t("{n} people").format(n=f"{n:,}"))
        answer = QMessageBox.question(
            self, i18n.t("Remove from list"),
            i18n.t("Take {who} off the list? They leave People (Total, Net New "
                   "and Saved) and new searches won't bring them back. Nothing is "
                   "deleted: bring them back any time from Removed, under the tabs "
                   "at the top of the filters.").format(who=who),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _remove_selected(self, rows) -> None:
        """The action bar's Remove."""
        from addons.leads import removed as RM
        people = self._persons_for(rows)
        if not people or not self._confirm_remove(len(people)):
            return
        try:
            ids = RM.remove(self._removed_dir(), people)
        except RM.StoreError as e:
            self._status.setText(str(e))
            return
        self._reload_removed()
        leads = self._cockpit.leads
        leads.clear_selection()
        # The person open in the panel goes with them, rather than staying up
        # for someone the page no longer lists.
        shown = getattr(leads, "_drawer_person", None)
        shown_keys = getattr(shown, "keys", None) or frozenset()
        if shown_keys and not shown_keys.isdisjoint(self._removed_keys):
            leads._dismiss_drawer()
        self._rebuild_pool_keep_page()
        self._refresh_send()
        text = i18n.t("Removed {n} from the list.").format(n=len(people))
        self._undo_ids, self._undo_text = ids, text
        self._status.setText(text)
        self._sync_notice()

    def _undo_remove(self) -> None:
        """The notice's Undo: the last Remove, put back."""
        ids, self._undo_ids = list(self._undo_ids), []
        self._restore(ids)

    def _restore_dialog(self, records) -> list:
        """The Removed window: the ids ticked to come back, [] on Close.
        Tests patch this."""
        from PySide6.QtWidgets import QDialog
        from addons.leads.removed_dialog import RemovedDialog
        dlg = RemovedDialog(records, parent=self)
        return dlg.chosen_ids() if dlg.exec() == QDialog.Accepted else []

    def _open_removed(self) -> None:
        """The rail's "N removed · Restore"."""
        self._reload_removed()                  # as the file has it now
        ids = self._restore_dialog(self._removed)
        if ids:
            self._undo_ids = []
            self._restore(ids)

    def _restore(self, ids) -> None:
        from addons.leads import removed as RM
        if not ids:
            return
        try:
            n = RM.restore(self._removed_dir(), ids)
        except RM.StoreError as e:
            self._status.setText(str(e))
            return
        self._reload_removed()
        self._rebuild_pool_keep_page()
        self._refresh_send()
        self._status.setText(i18n.t("Put {n} back on the list.").format(n=n))

    def _refresh_send(self) -> None:
        """Send all as the list now stands — a removal can leave it nobody."""
        if not self._jobs:
            self._send_btn.setEnabled(bool(self._sendable(self._drafts)))

    # ── the person panel (Apollo's contact profile) ─────────────────────────
    def _person_view(self, dos, person=None):
        """Everything the panel shows about one person, from the stores: their
        saved contact as the file has it (notes, tasks, Activities), the
        account they work at, their Account CSV import company, who else
        Prism holds there, and the searches that found them."""
        from addons.leads import contacts as CT
        from addons.leads.person import PersonView
        lead = getattr(dos, "lead", None)
        if lead is None:
            return None
        if person is None:
            person = next((p for p in self._people if p.lead is lead), None)
        found_by = []
        for sid in (person.sessions if person is not None else ()):
            run = self._runs.get(sid)
            if run:
                found_by.append((run[1], self._search_words(run[5] if len(run) > 5 else {})))
        near = P.colleagues(self._people, person) if person is not None else []
        draft = person.draft if person is not None else None
        return PersonView(
            row=dos, draft=draft if draft is not None else self._draft_for(dos),
            person=person, contact=CT.get(self._contacts_dir(), lead),
            account=self._account_index.match(lead),
            company=dict(person.account) if person is not None and person.account else {},
            colleagues=near[:6], more_colleagues=max(0, len(near) - 6),
            found_by=found_by)

    @staticmethod
    def _search_words(params) -> str:
        """What a run asked, in a few words — "6 titles · Anywhere except India"."""
        if not isinstance(params, dict) or params.get("mode") == "sheet":
            return i18n.t("a sheet you loaded")
        try:
            return SearchSpec.from_params(params).summary()
        except Exception:                                   # noqa: BLE001
            return i18n.t("a search")

    def _panel_done(self, said: str = "", rebuild: bool = False) -> None:
        if rebuild:
            self._rebuild_pool_keep_page()
        if said:
            self._status.setText(said)
        self._cockpit.leads.refresh_person()

    def _ensure_contact(self, lead) -> bool:
        """Apollo's rule: acting on someone saves them first. False when the
        save failed (the status line says why)."""
        from addons.leads import contacts as CT
        if CT.find(self._contacts, lead) is not None:
            return True
        return self._keep_as_contacts([lead], "save")

    def _panel_save(self, lead) -> None:
        if self._keep_as_contacts([lead], "save"):
            self._panel_done(i18n.t("Saved {name} as a contact.").format(
                name=lead.name or i18n.t("them")))

    def _panel_stage(self, lead, stage: str) -> None:
        from addons.leads import contacts as CT
        stage = CT.stage_named(stage)
        if not stage or not self._ensure_contact(lead):
            return
        try:
            CT.set_stage(self._contacts_dir(), lead, stage)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        saved = CT.find(self._contacts, lead)
        if saved is not None:
            saved.stage = stage
        self._panel_done(i18n.t("Moved {name} to {stage}.").format(
            name=lead.name or i18n.t("them"), stage=stage), rebuild=True)

    def _panel_account_stage(self, account, stage: str) -> None:
        from addons.leads import accounts as AC
        try:
            AC.set_stage(self._accounts_dir(), account, stage)
        except AC.StoreError as e:
            self._status.setText(str(e))
            return
        self._reload_accounts()
        self._panel_done(i18n.t("Moved {company} to {stage}.").format(
            company=getattr(account, "name", "") or i18n.t("the account"),
            stage=AC.stage_named(stage)), rebuild=True)

    def _panel_account_save(self, lead) -> None:
        from addons.leads import accounts as AC
        company = AC.from_lead(lead, "domain") or AC.from_lead(lead, "name")
        if not company:
            return
        try:
            AC.save(self._accounts_dir(), [company], via="save")
        except AC.StoreError as e:
            self._status.setText(str(e))
            return
        self._reload_accounts()
        self._panel_done(i18n.t("Saved {company} as an account.").format(
            company=company.get("name") or company.get("domain")), rebuild=True)

    def _panel_note(self, lead, text: str) -> None:
        from addons.leads import contacts as CT
        if not self._ensure_contact(lead):
            return
        try:
            CT.add_note(self._contacts_dir(), lead, text)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        self._panel_done(i18n.t("Note kept."))

    def _panel_task(self, lead, text: str, due: str) -> None:
        from addons.leads import contacts as CT
        if not self._ensure_contact(lead):
            return
        try:
            CT.add_task(self._contacts_dir(), lead, text, due)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        self._panel_done(i18n.t("Task added."))

    def _panel_task_done(self, lead, task_id: str, done: bool) -> None:
        from addons.leads import contacts as CT
        try:
            CT.set_task_done(self._contacts_dir(), lead, task_id, done)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        self._panel_done()

    def _panel_log(self, lead, kind: str, text: str) -> None:
        from addons.leads import contacts as CT
        if not self._ensure_contact(lead):
            return
        try:
            CT.log(self._contacts_dir(), lead, kind, text)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        self._panel_done(i18n.t("Logged."))

    def _panel_edit(self, lead, changes: dict) -> None:
        """Edit contact info — the saved record and the person on the page."""
        from addons.leads import contacts as CT
        if not self._ensure_contact(lead):
            return
        try:
            done = CT.edit(self._contacts_dir(), lead, changes)
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        saved = CT.find(self._contacts, lead)
        if saved is not None and saved.lead is not lead:
            CT.merge(saved.lead, lead)
        self._panel_done(i18n.t("Saved the changes.") if done else "", rebuild=done)

    def _panel_flag(self, lead) -> None:
        """Flag as inaccurate: their details are wrong — kept in their
        Activities, and the stage becomes Apollo's Bad Data."""
        from addons.leads import contacts as CT
        if not self._ensure_contact(lead):
            return
        try:
            CT.log(self._contacts_dir(), lead, "flagged")
            CT.set_stage(self._contacts_dir(), lead, "Bad Data")
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        saved = CT.find(self._contacts, lead)
        if saved is not None:
            saved.stage = "Bad Data"
        self._panel_done(i18n.t("Flagged {name} as inaccurate — their stage is Bad Data.")
                         .format(name=lead.name or i18n.t("them")), rebuild=True)

    def _panel_delete(self, lead) -> None:
        """Delete contact: out of the contacts store — someone a search found
        stays on the page as net new, as Apollo's deleted contacts return."""
        from addons.leads import contacts as CT
        from prospector.identity import keys_of
        try:
            CT.remove(self._contacts_dir(), [lead])
        except CT.StoreError as e:
            self._status.setText(str(e))
            return
        gone = keys_of(lead)
        self._contacts = [c for c in self._contacts if gone.isdisjoint(keys_of(c.lead))]
        self._rebuild_pool_keep_page()
        self._status.setText(i18n.t("Deleted {name} from your contacts.").format(
            name=lead.name or i18n.t("them")))
        still = any(not gone.isdisjoint(p.keys) for p in self._people)
        if still:
            self._cockpit.leads.refresh_person()
        else:
            self._cockpit.leads._dismiss_drawer()

    def _panel_enrich(self, dos, fields) -> None:
        """Enrichment ▸ Enrich fields: each picked field in turn — an e-mail,
        a phone, the company, a qualify pass — every one asking before it spends."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the job that is running to finish, then try again."))
            return
        self._enrich_queue = [(dos, f) for f in ("email", "phone", "company", "qualify")
                              if f in (fields or ())]
        self._next_enrichment()

    def _next_enrichment(self) -> None:
        """Start the next picked enrichment; one that starts no job (declined,
        or nothing to do) hands on to the next at once."""
        while self._enrich_queue and not self._jobs:
            dos, what = self._enrich_queue.pop(0)
            if what == "email":
                self._find_emails([dos])
            elif what == "phone":
                self._find_phones([dos])
            elif what == "company":
                self._enrich_company(dos.lead)
            elif what == "qualify":
                self._qualify_selected([dos])

    def _enrich_company(self, lead) -> None:
        """Enrichment ▸ Company: one Exa lookup for the company a person works
        at — its website, size, revenue and HQ — into their saved account."""
        from addons.leads import accounts as AC
        from addons.leads.workers import LeadsAccountEnrichWorker
        if self._jobs:
            return
        account = self._account_index.match(lead)
        company = ({k: getattr(account, k) for k in ("name", "website", "domain",
                                                     "location", "industry", "headcount",
                                                     "revenue", "description")}
                   if account is not None
                   else AC.from_lead(lead, "domain") or AC.from_lead(lead, "name"))
        if not company or not LeadsAccountEnrichWorker.wants(company, "all"):
            self._status.setText(i18n.t("Nothing left to look up for this company."))
            return
        if self._pooled():
            blocked = self._pool_blocker("company")
            if blocked:
                self._status.setText(blocked)
                return
        elif not self._key("exa_api_key"):
            self._status.setText(i18n.t(
                "Looking the company up needs an Exa API key — add it under "
                "Search settings › Keys & claims."))
            return
        if not self._confirm_enrich(1):
            return
        self._set_running(True)
        self._status.setText(i18n.t("Looking up {name}…").format(
            name=company.get("name") or company.get("domain")))
        self._enrich_worker = LeadsAccountEnrichWorker([company], self.cfg, "all")
        self._enrich_worker.done.connect(self._on_company_enriched)
        self._enrich_worker.failed.connect(self._on_failed)
        self._job_started()
        self._enrich_worker.start()

    def _on_company_enriched(self, companies, filled: int) -> None:
        from addons.leads import accounts as AC
        idle = self._job_done()
        try:
            AC.save(self._accounts_dir(), list(companies or ()), via="enrich", update=True)
        except AC.StoreError as e:
            self._status.setText(str(e))
        else:
            self._status.setText(i18n.t("Filled in the company from Exa.") if filled
                                 else i18n.t("Exa had nothing more on this company."))
        self._reload_accounts()
        self._rebuild_pool_keep_page()
        if idle:
            self._set_running(False)

    # ── Import ▾ ──────────────────────────────────────────────────────────────
    def _import(self, kind: str):
        """Import ▾ — the wizard, then the stores. Nothing is searched: the
        import becomes a value of its CSV-import filter, and that filter is
        applied so the owner sees what came in (removing it is one click)."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then import."))
            return
        from PySide6.QtWidgets import QDialog
        from addons.leads.import_wizard import ImportWizard
        wizard = ImportWizard(kind, start_dir=self._autosave_dir(), parent=self,
                              lists=self._list_names())
        if wizard.exec() != QDialog.Accepted:
            return
        self._run_import(wizard.result())

    def _list_names(self) -> list:
        """The lists there are — the sheets in the Lists folder, and every list
        a saved contact was added to — for "Add to a list?"."""
        names = []
        try:
            for entry in sorted(os.listdir(self._autosave_dir())):
                stem, ext = os.path.splitext(entry)
                if ext.lower() in (".csv", ".xlsx") and stem not in names:
                    names.append(stem)
        except OSError:
            pass
        for contact in self._contacts:
            for name in getattr(contact, "lists", ()) or ():
                if name not in names:
                    names.append(name)
        return names

    @staticmethod
    def _stage_of(settings: dict):
        """A save's stage_of for an import's Stage setting: "csv" reads each
        row's own stage column, anything else is the stage for everyone."""
        stage = (settings or {}).get("stage") or "Cold"
        if stage == "csv":
            def from_row(item):
                if isinstance(item, dict):
                    return item.get("stage", "")
                return (getattr(item, "extra", None) or {}).get("stage", "")
            return from_row
        return lambda _item: stage

    def _run_import(self, result: dict):
        """Write one wizard's result: the import record (imports.py) and, for
        contacts, the people themselves (contacts.py, tagged with the import),
        their stage and list, and — "Auto-assign accounts?" — the companies
        they work at (accounts.py); for accounts, the companies as saved
        accounts too. Then show them: the new import's filter applied, the
        Total tab. What spends (Find e-mails, the accounts' enrichment) asks
        first, afterwards."""
        from addons.leads import accounts as AC
        from addons.leads import contacts as CT
        from addons.leads import imports as IM
        kind = result.get("kind")
        settings = result.get("settings") or {}
        list_name = settings.get("list_name", "") if settings.get("add_to_list") else ""
        if kind == "contacts":
            # Ranked on the way in, as a loaded sheet always was: the cheap,
            # local fit off the title and what you sell — no API, no credit —
            # so Relevance means something and the FIT column is not all 0.
            from prospector import triage
            unscored = [l for l in result.get("leads") or ()
                        if not getattr(l, "fit_score", 0)]
            if unscored:
                triage.rank(unscored, self._offer.toPlainText().strip() or DEFAULT_OFFER,
                            self._filters.spec().role_terms())
        try:
            if kind == "contacts":
                header = IM.create(
                    self._imports_dir(), name=result["name"], kind="contacts",
                    source=result.get("path", ""), sheet=result.get("sheet", ""),
                    mapping=result.get("mapping"), settings=result.get("settings"),
                    counts={"rows": result.get("rows", 0),
                            "skipped": result.get("skipped", 0)})
                leads = result.get("leads") or []
                got = CT.save(self._contacts_dir(), leads,
                              via="import", import_id=header["id"],
                              update=bool(settings.get("update_existing", True)),
                              stage_of=self._stage_of(settings), list_name=list_name)
                IM.update_counts(self._imports_dir(), header["id"], {
                    "rows": result.get("rows", 0), "skipped": result.get("skipped", 0),
                    "added": got["added"], "updated": got["updated"] + got["tagged"]})
                self._contacts = CT.list_contacts(self._contacts_dir())
                said = i18n.t("Imported {n} contacts from {file}").format(
                    n=got["added"] + got["updated"] + got["tagged"], file=result["name"])
                by = settings.get("assign_accounts", "none")
                if by in ("domain", "name"):
                    companies = [c for c in (AC.from_lead(l, by) for l in leads) if c]
                    if companies:
                        made = AC.save(self._accounts_dir(), companies, via="contact")
                        if made["added"]:
                            said += " · " + i18n.t("{n} new accounts").format(
                                n=made["added"])
                facet = "contact_imports"
            else:
                companies = result.get("companies") or []
                header = IM.create(
                    self._imports_dir(), name=result["name"], kind="accounts",
                    source=result.get("path", ""), sheet=result.get("sheet", ""),
                    mapping=result.get("mapping"), settings=settings,
                    counts={"rows": result.get("rows", 0),
                            "skipped": result.get("skipped", 0)},
                    companies=companies)
                got = AC.save(self._accounts_dir(), companies, via="import",
                              import_id=header["id"],
                              update=bool(settings.get("update_existing", True)),
                              stage_of=self._stage_of(settings), list_name=list_name)
                IM.update_counts(self._imports_dir(), header["id"], {
                    "rows": result.get("rows", 0), "skipped": result.get("skipped", 0),
                    "added": got["added"], "updated": got["updated"] + got["tagged"]})
                said = i18n.t("Imported {n} companies from {file} — press Find new "
                              "people to search for people at them.").format(
                    n=header.get("n_companies", 0), file=result["name"])
                facet = "account_imports"
        except (IM.StoreError, CT.StoreError, AC.StoreError, ValueError) as e:
            QMessageBox.warning(self, i18n.t("Import"), str(e))
            return
        if result.get("skipped"):
            said += " · " + i18n.t("{k} rows skipped").format(k=result["skipped"])
        if kind == "contacts":
            # Someone taken off the list and now imported again is wanted
            # after all: the owner picked this sheet row by row.
            from addons.leads import removed as RM
            back = RM.restore_leads(self._removed_dir(), result.get("leads") or [])
            if back:
                said += " · " + i18n.t("{n} back from Removed").format(n=back)
                self._reload_removed()
        # Show what came in, the way Apollo's import opens its people: that
        # import's filter and nothing else ("Hide Filters 1") — a job title
        # left on the rail would hide most of a sheet that never had one. The
        # pool first, so the one re-filter the spec change causes sees them.
        self._reload_accounts()
        self._pool_changed()
        self._refresh_imports()
        spec = SearchSpec()
        setattr(spec, facet, [header["id"]])
        self._tab = "total"
        self._cockpit.leads.set_tab("total")
        self._scope = ""
        self._cockpit.show_people_tab()
        self._filters.set_spec(spec)        # → _on_filters_changed → _refilter
        self._status.setText(said)
        if kind == "contacts":
            leads = result.get("leads") or []
            if list_name and leads:
                self._write_import_list(leads, list_name)
            if settings.get("find_emails"):
                # The SAVED contacts' own records, so the rows on screen are
                # the ones the lookup fills in.
                saved = [CT.find(self._contacts, l) for l in leads
                         if not (l.email or "").strip()]
                missing = [c.lead for c in saved if c is not None]
                if missing:
                    self._find_emails(self._placeholders(missing))
        else:
            if list_name and companies:
                self._write_account_list(companies, list_name)
            mode = ("all" if settings.get("enrich_all")
                    else "websites" if settings.get("find_websites") else "")
            if mode:
                self._enrich_accounts(header["id"], mode)

    # ── an accounts import's Intelligent enrichment ──────────────────────────
    def _accounts_dir(self) -> str:
        """This member's saved accounts, beside their contacts. Tests patch
        this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "accounts")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "accounts")

    def _confirm_enrich(self, n: int) -> bool:
        """"Look up N companies on Exa?" — every search is a credit the owner
        approves. Tests patch this."""
        if self._pooled():
            price = gateway.rate("company_lookup")
            return self._confirm_pool(i18n.t("Look the companies up"), [
                i18n.t("Look up {n} companies — up to {c} — for their website, "
                       "size, revenue and HQ?").format(n=n, c=self._cr(n * price))])
        answer = QMessageBox.question(
            self, i18n.t("Look the companies up"),
            i18n.t("Look up {n} companies on Exa — about {n} searches — for their "
                   "website, size, revenue and HQ?").format(n=n),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _enrich_accounts(self, import_id: str, mode: str) -> None:
        """Run an accounts import's enrichment: the import's companies to
        LeadsAccountEnrichWorker, after the owner approves the searches."""
        from addons.leads import imports as IM
        from addons.leads.workers import LeadsAccountEnrichWorker
        if self._jobs:
            return
        record = IM.get(self._imports_dir(), import_id)
        companies = list((record or {}).get("companies") or ())
        n = sum(1 for c in companies if LeadsAccountEnrichWorker.wants(c, mode))
        if not n:
            return
        if self._pooled():
            blocked = self._pool_blocker("company")
            if blocked:
                self._status.setText(blocked)
                return
        elif not self._key("exa_api_key"):
            self._status.setText(i18n.t(
                "Looking the companies up needs an Exa API key — add it under "
                "Search settings › Keys & claims."))
            return
        if not self._confirm_enrich(n):
            return
        self._set_running(True)
        self._status.setText(i18n.t("Looking up {n} companies…").format(n=n))
        self._enrich_worker = LeadsAccountEnrichWorker(companies, self.cfg, mode)
        self._enrich_worker.progress.connect(lambda i, total, name: self._status.setText(
            i18n.t("Looking up {i} of {n}: {name}").format(i=i, n=total, name=name)))
        self._enrich_worker.done.connect(
            lambda found, filled, i=import_id: self._on_accounts_enriched(i, found, filled))
        self._enrich_worker.failed.connect(self._on_failed)
        self._job_started()
        self._enrich_worker.start()

    def _on_accounts_enriched(self, import_id: str, companies, filled: int):
        """Write what the lookup found back to the import (the Account CSV
        import filter matches by the domains it learned) and to the saved
        accounts, and re-read the page."""
        from addons.leads import accounts as AC
        from addons.leads import imports as IM
        idle = self._job_done()
        try:
            IM.set_companies(self._imports_dir(), import_id, companies)
            AC.save(self._accounts_dir(), companies, via="enrich", update=True)
        except (IM.StoreError, AC.StoreError) as e:
            self._status.setText(str(e))
        else:
            self._status.setText(i18n.t("Filled in {n} companies from Exa.").format(
                n=filled))
        if idle:
            self._set_running(False)
        self._reload_accounts()
        self._pool_changed()
        self._refresh_imports()
        self._refilter(keep_page=True)

    def _write_account_list(self, companies, name: str) -> None:
        """"Add to a list?" for an accounts import: the companies as a sheet
        in the Lists folder."""
        safe = re.sub(r"[^\w .-]+", "", os.path.splitext(name.strip())[0]) or "list"
        path = os.path.join(self._autosave_dir(), f"{safe}.csv")
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["company", "website", "location", "industry", "employees",
                            "stage"])
                for c in companies:
                    w.writerow([c.get("name", ""), c.get("website", ""),
                                c.get("location", ""), c.get("industry", ""),
                                c.get("headcount", ""), c.get("stage", "")])
        except OSError as e:
            self._status.setText(i18n.t("Couldn't write the list {path}: {err}")
                                 .format(path=path, err=e))
            return
        self._cockpit.refresh_lists()

    def _placeholders(self, leads) -> list:
        """Leads as the display-only dossiers the bulk actions take."""
        from prospector.models import Dossier
        from addons.leads.cockpit import UNQUALIFIED
        return [Dossier(lead=l, verdict="", generated_at="", status=UNQUALIFIED,
                        score=int(getattr(l, "fit_score", 0) or 0)) for l in leads]

    def _write_import_list(self, leads, name: str) -> None:
        safe = re.sub(r"[^\w .-]+", "", os.path.splitext(name.strip())[0]) or "list"
        path = os.path.join(self._autosave_dir(), f"{safe}.csv")
        try:
            self._write_leads_csv(self._placeholders(leads), path)
        except OSError as e:
            self._status.setText(i18n.t("Couldn't write the list {path}: {err}")
                                 .format(path=path, err=e))
            return
        self._cockpit.refresh_lists()

    # ── file pickers ─────────────────────────────────────────────────────────
    def _choose_claims(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Approved value claims — one per line"), "",
            "Text (*.txt *.md);;All files (*.*)")
        if not path:
            return
        self._claims_path = path
        self._claims_lbl.setText(os.path.basename(path))

    # ── prepare ──────────────────────────────────────────────────────────────
    def _on_prepare(self, leads_only: bool = True, emails: str = "later"):
        """Find new people — the one action on the People page that spends.
        The defaults are Find new people's own: find the people, leave the
        e-mails and Groq for the actions on the rows that come back. Research
        with AI ▸ "Find new people and qualify them" passes leads_only=False,
        emails="now".

        It searches with the rail's filters, and says what that costs before
        it runs (the owner approves every credit — _confirm_search). An
        Account CSV import among them is searched MAX_FACET_VALUES companies
        at a time (_search_spec); the batch only counts as searched once the
        search actually starts. A sheet is never read here any more: that is
        Import ▾, and what it brought in is a filter."""
        if self._jobs:
            return
        from prospector import reach
        self._save_keys()
        missing = self._missing_key()
        if missing:
            self._status.setText(missing)
            self._open_settings(keys=True)
            return
        spec, companies, note, marks = self._search_spec()
        if spec is None:
            self._status.setText(note)
            return
        if not self._confirm_search(spec, companies, note):
            return
        filters = self._filters.spec()
        # An import's companies count as searched as each group of them is
        # asked (_on_companies_asked) — kept on disk, so the next press (or
        # the next launch) asks only the companies never asked.
        self._search_marks = marks
        claims = reach.load_claims(self._claims_path)
        offer = self._offer.toPlainText().strip() or DEFAULT_OFFER
        include_earlier = not self._skip_seen.isChecked()
        legacy = spec.legacy_params()
        # What this run was asked — saved with its session (no keys, no cfg).
        # The filters travel as the RAIL's (a reopened run puts the account
        # import back, not 50 company chips); the legacy industries / roles /
        # location beside them keep a session label and an older build reading.
        self._next_mode = "icp_leads_only" if leads_only else "icp"
        self._next_params = {
            "mode": self._next_mode, **legacy, "filters": filters.to_dict(),
            "source": self._source, "target": self._target.value(), "offer": offer,
            "limit": self._limit.value(), "verify_limit": self._verify_limit.value(),
            "claims_path": self._claims_path, "include_earlier": include_earlier,
        }
        self._set_running(True)
        self._status.setText(i18n.t("Finding people (no e-mails, no Groq)…")
                             if leads_only else i18n.t("Finding people…"))
        self._worker = SourceWorker(
            legacy["industries"], legacy["roles"], offer, self.cfg,
            location=legacy["location"],
            target=self._target.value(), limit=self._limit.value(),
            verify_limit=self._verify_limit.value(),
            sender=self._sender(), claims=claims,
            exclude_domains=self._seller_domains(), leads_only=leads_only,
            sessions_dir=self._sessions_dir(), include_earlier=include_earlier,
            spec=spec.to_dict(), source=self._source, emails=emails,
            removed_dir=self._removed_dir(), companies=list(companies))
        self._worker.companiesAsked.connect(self._on_companies_asked)
        self._worker.blocked.connect(self._on_source_blocked)
        self._worker.progress.connect(self._status.setText)
        self._worker.done.connect(self._on_prepared)
        self._worker.failed.connect(self._on_failed)
        self._job_started()
        self._worker.start()

    def _on_companies_asked(self, asked: int) -> None:
        """The worker has asked the first `asked` companies of this press:
        their imports move on that far — and, the whole press asked, to the
        end of what it walked (companies skipped as already searched too)."""
        marks = getattr(self, "_search_marks", None) or {}
        order = marks.get("order") or []
        if not order:
            return
        if asked >= len(order):
            upto = dict(marks.get("final") or {})
        else:
            upto = {}
            for import_id, at in order[:max(0, asked)]:
                upto[import_id] = max(upto.get(import_id, 0), at)
        from addons.leads import imports as IM
        try:
            for import_id, at in upto.items():
                IM.mark_searched(self._imports_dir(), import_id, at)
        except IM.StoreError as e:
            self._status.setText(str(e))
            return
        self._refresh_imports()

    def _confirm_search(self, spec, companies, note: str) -> bool:
        """"This will run about 200 Exa searches — go?" before a search
        spends anything (23-Sep-2026: the owner approves every credit). Says
        what it searches for when the owner did not say it himself — an
        account import with no title or seniority asks for the decision-
        makers. Tests patch this."""
        if self._pooled():
            return self._confirm_pool_search(spec, companies, note)
        if self._source == "apollo":
            cost = i18n.t("It searches Apollo — about one Apollo credit for each "
                          "person revealed, up to {n}.").format(n=self._target.value())
        else:
            n, more = self._searches(spec, companies)
            if companies and n == 1:
                cost = i18n.t("It will run 1 Exa search, asking the company for "
                              "everyone the search wants at once. It keeps up to 3 "
                              "people from it.")
            elif companies:
                cost = i18n.t("It will run {n} Exa searches: one for each company, "
                              "asking for everyone the search wants at once. It "
                              "keeps up to 3 people from each company.").format(n=n)
            elif more:
                cost = i18n.t("It will run about {n} Exa searches, and up to {m} "
                              "more only if too few new people come back.").format(
                                  n=n, m=more)
            else:
                cost = i18n.t("It will run about {n} Exa searches.").format(n=n)
        lines = [cost]
        if companies:
            lines.append(i18n.t("It looks at {what}.").format(what=note))
            own = self._filters.spec()
            if not own.job_titles.include and not own.seniority.include \
                    and not own.functions.include:
                lines.append(i18n.t(
                    "With no job title or seniority set, it asks for Owners, "
                    "Founders, Chiefs and Directors."))
        answer = QMessageBox.question(
            self, i18n.t("Find new people"), "\n\n".join(lines),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_pool_search(self, spec, companies, note: str) -> bool:
        """The credits version of _confirm_search. A search costs what the
        server's price list says and only a search that finds people is charged,
        so the figure is the most it can be — and it is exact about how many
        searches there are (source.planned_searches), not a guess."""
        n, more = self._searches(spec, companies)
        price = gateway.rate("people_search", 3)
        if companies and n == 1:
            cost = i18n.t("It will run 1 search, asking the company for everyone "
                          "the search wants at once — up to {c}. It keeps up to 3 "
                          "people from it.").format(c=self._cr(price))
        elif companies:
            cost = i18n.t("It will run {n} searches: one for each company, asking "
                          "for everyone the search wants at once — up to {c}. It "
                          "keeps up to 3 people from each company.").format(
                              n=n, c=self._cr(n * price))
        elif more:
            cost = i18n.t("It will run about {n} searches — up to {c} — and up to "
                          "{m} more only if too few new people come back.").format(
                              n=n, c=self._cr(n * price), m=more)
        else:
            cost = i18n.t("It will run about {n} searches — up to {c}.").format(
                n=n, c=self._cr(n * price))
        lines = [cost, i18n.t("A search that finds nobody is not charged.")]
        if companies:
            lines.append(i18n.t("It looks at {what}.").format(what=note))
            own = self._filters.spec()
            if not own.job_titles.include and not own.seniority.include \
                    and not own.functions.include:
                lines.append(i18n.t(
                    "With no job title or seniority set, it asks for Owners, "
                    "Founders, Chiefs and Directors."))
        balance = self._balance()
        if balance is not None and n * price > balance:
            lines.append(i18n.t("That is more than you have — the search stops "
                                "when your credits run out."))
        return self._confirm_pool(i18n.t("Find new people"), lines)

    def _save_keys(self) -> None:
        """Keep what Search settings › Keys & claims holds, in the config, so
        every run after picks it up — when Search settings closes and when a
        search starts. The owner, 24-Sep-2026: an expired Exa key replaced
        there was only kept once Find new people was pressed, so Done forgot
        it and Find e-mails and the company look-ups went on with the old one.
        Each key is written alone (_save_search_key): self.cfg can predate an
        account or a key saved elsewhere, and saving it whole would wipe them.

        On the credit pool there are no keys to keep — the hidden boxes hold
        whatever an older build saved, and writing it back would only keep a
        provider key on a customer's machine."""
        if self._pooled():
            return
        self._save_search_key("exa_api_key", self._exa.text().strip())
        self._save_search_key("apollo_api_key", self._apollo.text().strip())

    def _save_search_key(self, name: str, value: str):
        """Keep one search key in the config, and in this window's cfg."""
        if value != (self.cfg.get(name) or ""):
            self._save_cfg(name, value)
        self.cfg[name] = value

    def _save_cfg(self, name: str, value):
        """Write ONE setting to the config, and to this window's cfg. Only that
        one: the fresh config can hold an account or a key saved elsewhere since
        this screen opened, and saving self.cfg whole would write them back as
        they were when it opened."""
        try:
            fresh = CB.config.load()
            fresh[name] = value
            CB.config.save(fresh)
        except Exception:                                   # noqa: BLE001
            pass
        self.cfg[name] = value

    def _missing_key(self) -> str:
        """Why this search cannot start, naming the key the chosen source
        needs — said before a worker spends a thread finding out. On the
        credit pool there is no key to miss: the reason is no credits, or a
        lookup the server has not switched on."""
        if self._pooled():
            return self._pool_blocker("people")
        if self._source == "apollo" and not self._key("apollo_api_key"):
            return i18n.t("Searching Apollo needs an Apollo API key — add it "
                          "under Keys & claims, or search with Exa instead.")
        if self._source == "exa" and not self._key("exa_api_key"):
            return i18n.t("Searching with Exa needs an Exa API key — add it "
                          "under Keys & claims, or search with Apollo instead.")
        return ""

    def _seller_domains(self) -> list:
        """The seller's own site(s), pulled from the offer text and the claims
        file, so the why-now search never cites the seller's own pages."""
        text = self._offer.toPlainText()
        if self._claims_path:
            try:
                with open(self._claims_path, encoding="utf-8") as f:
                    text += " " + f.read()
            except Exception:                               # noqa: BLE001
                pass
        return sorted(set(re.findall(
            r"\b([a-z0-9][a-z0-9-]*\.(?:com|in|io|ai|co|net|org))\b",
            text.lower())))

    def _on_prepared(self, res, drafts):
        idle = self._job_done()
        # A finished run is a new session: kept on disk, reopenable, and the
        # people it pulled are skipped by the next run.
        try:
            from addons.leads import sessions
            self._session_id = sessions.new_id()
        except Exception:                                   # noqa: BLE001
            self._session_id = ""
        self._session_mode = self._next_mode
        self._run_params = dict(self._next_params)
        self._page = 0                      # a new search starts at its first page
        self._show_result(res, drafts)
        if idle:
            self._set_running(False)
        self._save_session()
        self._record_search_run(res)
        # The sheets ARE the deliverable — write them automatically to a known
        # folder the moment a run finishes (leads-only included, which needed no
        # Groq at all), so a run always produces a file instead of hiding it
        # behind a button the user must find.
        if res.dossiers or getattr(res, "all_leads", None):
            self._start_export(self._autosave_dir(), announce=False)

    def _show_result(self, res, drafts):
        """Make a run the CURRENT run — a finished one, or an opened session
        (which must NOT re-export or re-save): what Send all sends, Export
        sheets writes and Analytics counts, and — joined to the pool — people
        on the People page. The page shows the pool, not this run alone: what
        this run found is under Net New, filters and all."""
        self._res = res
        self._drafts = list(drafts or [])
        self._draft_by = {id(d.dossier): d for d in self._drafts}
        self._cockpit.set_run(res.dossiers, self._drafts)
        # Always in the pool — even a run whose session id could not be made
        # (it is on screen; its people must be too).
        self._runs[self._session_id] = self._run_tuple()
        self._rebuild_pool_keep_page()
        leads_only = not res.dossiers and bool(getattr(res, "all_leads", None))
        skipped = getattr(res, "skipped_seen", 0) or 0
        if leads_only:
            # What it found and what it did NOT spend — the whole point of the
            # cheap run, said where the owner reads the result. A list that HAS
            # addresses (an older run, or a sheet that came with them) must not
            # claim nothing was looked up.
            blank = not any((l.email or "").strip() for l in res.all_leads)
            text = (i18n.t("Found {n} people · sheet saved · no e-mail lookups, "
                           "no Groq.") if blank else
                    i18n.t("Found {n} people · sheet saved · no Groq used.")
                    ).format(n=len(res.all_leads))
            if skipped:
                text += "   ·   " + i18n.t("{n} already pulled, skipped").format(n=skipped)
            outside = self._outside_bit(res)
            if outside:
                text += "   ·   " + outside
            apollo = self._apollo_bit(res)
            if apollo:
                text += "   ·   " + apollo
            self._summary.setText(text + self._used_note())
        elif res.dossiers:
            self._summary.setText(self._run_summary(res, self._drafts))
            self._status.setText(i18n.t(
                "{n} ready to send — every lead below shows its outcome."
            ).format(n=len(self._sendable(self._drafts))))
        else:
            self._summary.setText("")
        self._export_btn.setEnabled(bool(res.dossiers or getattr(res, "all_leads", None)))
        self._send_btn.setEnabled(bool(self._sendable(self._drafts)))

    def _on_failed(self, msg):
        if self._job_done():
            self._set_running(False)
        self._save_session()                # a failed send can leave drafts half-sent
        self._status.setText("")
        QMessageBox.warning(self, i18n.t("Leads & Outreach"),
                            i18n.t("Something went wrong:\n\n{msg}").format(msg=msg))

    # ── bulk-bar actions on the checked leads ─────────────────────────────────
    def _verify_selected(self, dossiers):
        """Re-verify the checked leads' e-mails with the FREE verifier waterfall
        (no paid finder), off-thread, then re-render with the fresh statuses."""
        if not dossiers or self._jobs:
            return
        from prospector import verify
        if self._pooled():
            blocked = self._pool_blocker("verify")
            if blocked:
                self._status.setText(blocked)
                return
            if not self._confirm_verify(sum(1 for d in dossiers
                                            if (d.lead.email or "").strip())):
                return
        elif not verify.collect_keys(self.cfg):
            QMessageBox.information(
                self, i18n.t("Verify e-mails"),
                i18n.t("Add a verifier key in Settings > Agents (Reoon, "
                       "Verifalia, ZeroBounce, AbstractAPI or Kickbox) and "
                       "Prism can confirm addresses for free."))
            return
        self._set_running(True)
        self._acted = [d.lead for d in dossiers]
        self._status.setText(i18n.t("Verifying {n} selected…").format(n=len(dossiers)))
        self._verify_worker = LeadsVerifyWorker(dossiers, self.cfg)
        self._verify_worker.progress.connect(lambda i, n, l: self._status.setText(
            i18n.t("Verifying {i} of {n}: {who}").format(i=i, n=n, who=l.display())))
        self._verify_worker.done.connect(self._on_verified)
        self._verify_worker.failed.connect(self._on_failed)
        self._job_started()
        self._verify_worker.start()

    def _confirm_verify(self, n: int) -> bool:
        """On the pool a check costs a credit, so a batch past ten asks first.
        A check is charged only when a verifier actually answers. Tests patch
        this."""
        if n <= 10:
            return True
        price = gateway.rate("email_verify")
        return self._confirm_pool(i18n.t("Verify e-mails"), [
            i18n.t("Check {n} e-mail addresses — up to {c}.").format(
                n=n, c=self._cr(n * price)),
            i18n.t("An address is charged only when a verifier answers.")])

    def _on_verified(self):
        if self._job_done():
            self._set_running(False)
        self._save_session()                # verify changed each lead's e-mail status
        # Acting on someone saves them (Apollo) — and it is how a status
        # checked on someone OUTSIDE the run on screen is kept at all.
        if not self._keep_as_contacts(getattr(self, "_acted", []), "email"):
            self._rebuild_pool_keep_page()  # the rows show the new statuses
        self._status.setText(i18n.t("Verification done — statuses updated.")
                             + self._used_note())
        # Same deal as Find e-mails: the sheet already on disk is the
        # deliverable, so a status a verify pass just confirmed belongs in it
        # too, not only on screen.
        if self._res is not None and (self._res.dossiers
                                      or getattr(self._res, "all_leads", None)):
            self._start_export(self._autosave_dir(), announce=False)

    def _find_emails(self, dossiers):
        """"Find e-mails" — get the checked people an address and check it.

        A Find-people run brings back nobody's address on purpose: finding
        people costs only the searches, finding their addresses costs a lookup
        per company and a credit a head. So this is where that is spent, on the
        rows the owner picked (or on a sheet they exported and brought back)."""
        if not dossiers or self._jobs:
            return
        from addons.leads.cockpit import needs_email
        # A confirmed address has nothing left to find; asking again only
        # spends credits on an answer we already have.
        leads = [d.lead for d in dossiers if needs_email(d)]
        if not leads:
            self._status.setText(i18n.t(
                "Those leads already have a verified address."))
            return
        if self._pooled():
            blocked = self._pool_blocker("find_email")
            if blocked:
                self._status.setText(blocked)
                return
        if not self._confirm_emails(len(leads)):
            return
        self._set_running(True)
        self._acted = list(leads)
        self._status.setText(i18n.t("Finding e-mails for {n} selected…").format(
            n=len(leads)))
        # No verify_limit: the rail's Verify is a budget for a RUN, which picks
        # its own top slice. These rows were ticked by hand, so every one of
        # them is checked — a guessed address nobody confirmed is worse in the
        # sheet than no address at all.
        self._email_worker = LeadsEmailWorker(leads, self.cfg)
        self._email_worker.progress.connect(lambda i, n, l: self._status.setText(
            i18n.t("Finding e-mail domains…") if not i else
            i18n.t("Checking {i} of {n}: {who}").format(i=i, n=n, who=l.display())))
        self._finder_refusals = {}
        self._email_worker.refused.connect(self._on_finders_refused)
        self._email_worker.done.connect(self._on_emails_found)
        self._email_worker.failed.connect(self._on_failed)
        self._job_started()
        self._email_worker.start()

    def _confirm_emails(self, n: int) -> bool:
        """Each lead can cost a finder credit — Hunter's (our main finder),
        then Apollo's, only when one of them knows the person — and every
        ticked row is looked up, nothing is sampled, so a batch past ten asks
        first, and names whose credits. Nothing is guessed (24-Sep-2026). This
        question is the only cap on the spend. Tests patch this. On the credit
        pool it asks in credits (_confirm_pool_emails); the finders' own names
        are the developer switch's."""
        if n <= 10:
            return True
        if self._pooled():
            return self._confirm_pool_emails(n)
        # Named in the order verify._FINDERS asks them.
        hunter = self._key("hunter_api_key")
        apollo = self._key("apollo_api_key") and not self.cfg.get("apollo_api_blocked")
        who = (i18n.t("Hunter, then Apollo") if hunter and apollo
               else i18n.t("Hunter") if hunter else i18n.t("Apollo"))
        answer = QMessageBox.question(
            self, i18n.t("Find e-mails"),
            i18n.t("Find and check e-mails for {n} leads? Prism asks {who} for "
                   "each person's real address and checks what comes back with "
                   "the free verifiers. A credit is used only when a finder "
                   "knows the person. Nothing is guessed.").format(n=n, who=who))
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_pool_emails(self, n: int) -> bool:
        """The credits version of _confirm_emails: per lead, a company-website
        lookup where the lead has none, an address found (charged only when a
        finder knows the person) and a check of what came back. Nothing is
        guessed, so a lead nobody knows costs at most the website lookup."""
        find, check, site = (gateway.rate("email_find"), gateway.rate("email_verify"),
                             gateway.rate("domain_lookup"))
        return self._confirm_pool(i18n.t("Find e-mails"), [
            i18n.t("Find and check e-mails for {n} leads — up to {c}.").format(
                n=n, c=self._cr(n * (site + find + check))),
            i18n.t("Prism looks up each company's website, asks a finder for the "
                   "person's real address and checks what comes back. An address "
                   "is charged only when a finder knows the person. Nothing is "
                   "guessed.")])

    def _on_finders_refused(self, why) -> None:
        """{finder: why} from the e-mail worker, just before its result: the
        finders that turned the account away (verify.FinderRefused)."""
        self._finder_refusals = dict(why or {})

    def _on_emails_found(self, found: int, verified: int):
        """Fold the addresses in: the rows re-render with their new Status
        (Verified / Unverified / Catch-all / No email) and the session keeps them,
        so the next thing the owner does starts from what this cost. A finder
        that refused the account is named with the result — and when nothing
        was found, in a box the owner cannot miss (24-Sep-2026: Apollo's Free
        plan and Hunter's spent quota refused all 159 lookups in silence)."""
        idle = self._job_done()
        self._save_session()                # the addresses are the run's value now
        if not self._keep_as_contacts(getattr(self, "_acted", []), "email"):
            self._rebuild_pool_keep_page()  # the rows show the new statuses
        if idle:
            self._set_running(False)
        refusals = list((getattr(self, "_finder_refusals", None) or {}).values())
        self._finder_refusals = {}
        line = i18n.t("Found {n} new address(es) — {v} verified.").format(
            n=found, v=verified)
        self._status.setText("   ·   ".join([line] + refusals) + self._used_note())
        # The sheet already sitting in the autosave folder is the deliverable —
        # rewrite it with the addresses this run just found, the same way a
        # finished run writes it the first time, so the owner never has to
        # press Export sheets just to see what Find e-mails cost.
        if self._res is not None and (self._res.dossiers
                                      or getattr(self._res, "all_leads", None)):
            self._start_export(self._autosave_dir(), announce=False)
        if refusals and not found:
            QMessageBox.warning(self, i18n.t("Find e-mails"), "\n\n".join(
                [i18n.t("No e-mails were found. The finders turned Prism away:")]
                + refusals))

    def _find_phones(self, dossiers):
        """"Find phones" — the number each selected person's COMPANY publishes on
        its website or a directory, one lookup per company (prospector/phones.py).

        It is the company's number, published and not called: nothing checks that
        the line is live, whose it is, or whether it is on a do-not-call register,
        and Prism says so wherever it shows one. Nobody who already has a phone is
        looked up again, and (on the pool) a credit is used only for a number found."""
        if not dossiers or self._jobs:
            return
        from addons.leads.cockpit import needs_phone
        from prospector import phones
        leads = [d.lead for d in dossiers if needs_phone(d)]
        if not leads:
            self._status.setText(i18n.t(
                "Those leads already have a phone number, or name no company to look one up for."))
            return
        if self._pooled():
            blocked = self._pool_blocker("phones")
            if blocked:
                self._status.setText(blocked)
                return
        elif not self._key("exa_api_key"):
            self._status.setText(i18n.t(
                "Finding phone numbers needs an Exa API key — add it under "
                "Search settings › Keys & claims."))
            return
        companies = phones.companies_of(leads)
        if not self._confirm_phones(companies):
            return
        self._set_running(True)
        self._acted = list(leads)
        self._status.setText(i18n.t("Finding phone numbers for {n} companies…").format(
            n=companies))
        self._phone_worker = LeadsPhoneWorker(leads, self.cfg)
        self._phone_worker.progress.connect(lambda i, n: self._status.setText(
            i18n.t("Looked up {i} of {n} companies…").format(i=i, n=n)))
        self._phone_worker.done.connect(self._on_phones_found)
        self._phone_worker.failed.connect(self._on_failed)
        self._job_started()
        self._phone_worker.start()

    def _confirm_phones(self, companies: int) -> bool:
        """Every lookup asks first, in credits on the pool. It is priced per number
        FOUND, so the figure is a ceiling: what the company does not publish is
        given back. Tests patch this."""
        if self._pooled():
            price = gateway.rate("company_phone", 2)
            return self._confirm_pool(i18n.t("Find phones"), [
                i18n.t("Look up the phone number for {n} companies — up to {c}.").format(
                    n=companies, c=self._cr(companies * price)),
                i18n.t("Prism asks for the number each company publishes on its own "
                       "website or a business directory. A credit is used only for a "
                       "number found. It is the company's number, published — not a "
                       "direct dial, and not called or checked.")])
        answer = QMessageBox.question(
            self, i18n.t("Find phones"),
            i18n.t("Look up the published phone number of {n} companies with your Exa "
                   "key? It is the company's number, not a direct dial, and Prism has "
                   "not called it.").format(n=companies))
        return answer == QMessageBox.StandardButton.Yes

    def _on_phones_found(self, counts) -> None:
        """Fold the numbers in: each person at a company that published one now
        has it (the export, the drafts and the person panel read it), the session
        and the saved contacts keep it, and the line says what was — and was not —
        found, and that it is published, not verified."""
        idle = self._job_done()
        counts = counts if isinstance(counts, dict) else {}
        found, asked, given = (int(counts.get(k, 0)) for k in ("found", "asked", "given"))
        failed = int(counts.get("failed", 0))
        self._save_session()
        if not self._keep_as_contacts(getattr(self, "_acted", []), "phone"):
            self._rebuild_pool_keep_page()
        if idle:
            self._set_running(False)
        # Why a lookup did not run, in the provider's or the server's own sentence. The
        # pool's "out of credits" is already said by _used_note — not twice.
        stopped = gateway.exhausted()
        said = dict.fromkeys(str(w).strip() for w in (counts.get("why") or ()))
        reason = " ".join(i18n.t(w) for w in said if w and w != stopped)
        if failed and not asked:
            # Nothing was looked up at all. "Found 0 for 0 companies" reads as an answer
            # (26-Sep-2026: an Exa account with no credit left said exactly that).
            parts = [i18n.t("No phone numbers were looked up.")]
            if reason:
                parts.append(reason)
        else:
            parts = [i18n.t("Found {f} phone number(s) for {a} companies — published, "
                            "not verified.").format(f=found, a=asked)]
            if asked > found:
                parts.append(i18n.t("{n} publish none.").format(n=asked - found))
            if failed:
                parts.append(" ".join([i18n.t("{n} couldn't be looked up.").format(n=failed)]
                                      + ([reason] if reason else [])))
        self._status.setText("   ·   ".join(parts) + self._used_note())
        if given and self._res is not None and (self._res.dossiers
                                                or getattr(self._res, "all_leads", None)):
            self._start_export(self._autosave_dir(), announce=False)

    def _qualify_selected(self, dossiers):
        """Qualify & draft the checked people the run sourced but never
        qualified — a leads-sheet-only run's whole list, or everyone past a full
        run's Qualify count — right here, instead of re-importing a sheet."""
        if not dossiers or self._jobs:
            return
        from addons.leads.cockpit import RETRYABLE
        # Never qualified, or a pass that failed (no key, a Groq error) — a lead
        # already qualified is left as it is.
        leads = [d.lead for d in dossiers if getattr(d, "status", "") in RETRYABLE]
        if not leads:
            self._status.setText(i18n.t("Those leads are already qualified."))
            return
        # Without a Groq key every lead would come back "no model" after its
        # why-now search was already paid for — say so before spending anything.
        if self._pooled():
            blocked = self._pool_blocker("llm")
            if blocked:
                self._status.setText(blocked)
                return
        elif not (self.cfg.get("api_key") or "").strip():
            self._status.setText(i18n.t(
                "Qualifying needs your Groq key — add it in Settings, then try again."))
            return
        if not self._confirm_qualify(len(leads)):
            return
        if self._res is None:
            self._start_empty_run()
        from prospector import reach
        offer = self._offer.toPlainText().strip() or DEFAULT_OFFER
        # Score with the roles the run itself ranked by: a sheet run used none.
        roles = ([] if self._session_mode == "sheet"
                 else SearchSpec.from_params(self._run_params).role_terms())
        self._set_running(True)
        self._status.setText(i18n.t("Qualifying {n} selected…").format(n=len(leads)))
        self._qualify_worker = LeadsQualifyWorker(
            leads, offer, self.cfg, roles=roles,
            verify_limit=self._verify_limit.value(), sender=self._sender(),
            claims=reach.load_claims(self._claims_path),
            exclude_domains=self._seller_domains())
        self._qualify_worker.progress.connect(self._status.setText)
        self._qualify_worker.done.connect(self._on_qualified)
        self._qualify_worker.failed.connect(self._on_failed)
        self._job_started()
        self._qualify_worker.start()

    def _start_empty_run(self) -> None:
        """A run to hold what an action produces when none is on screen — the
        People page shows the pool, so Qualify can be pressed on imported
        contacts before any search ever ran. Its dossiers and drafts become a
        session like any run's (sessions.save brings a dossier's lead along)."""
        from prospector import engine
        try:
            from addons.leads import sessions
            self._session_id = sessions.new_id()
        except Exception:                                   # noqa: BLE001
            self._session_id = ""
        self._session_mode = "icp_leads_only"
        spec = self._filters.spec()
        self._run_params = {"mode": "icp_leads_only", **spec.legacy_params(),
                            "filters": spec.to_dict(), "source": self._source}
        self._res = engine.RunResult(dossiers=[], total_in_sheet=0, signal_source="",
                                     all_leads=[])
        self._drafts, self._draft_by = [], {}

    def _confirm_qualify(self, n: int) -> bool:
        """Each lead costs a why-now search and a Groq call, and a free Groq key
        paces them — so a batch past ten asks first. Tests patch this."""
        if n <= 10:
            return True
        if self._pooled():
            each = (gateway.rate("signals") + gateway.rate("ai_qualify")
                    + gateway.rate("ai_draft"))
            return self._confirm_pool(i18n.t("Qualify & draft"), [
                i18n.t("Qualify and draft {n} leads — up to {c}.").format(
                    n=n, c=self._cr(n * each)),
                i18n.t("Each lead is a why-now news search, a score and a draft.")])
        answer = QMessageBox.question(
            self, i18n.t("Qualify & draft"),
            i18n.t("Qualify and draft {n} leads now? Prism researches each one and "
                   "makes a Groq call per lead, so on a free Groq key this can "
                   "take several minutes.").format(n=n))
        return answer == QMessageBox.StandardButton.Yes

    def _on_qualified(self, res, drafts):
        """Fold the newly qualified people into the run on screen: their rows
        turn into real outcomes, their drafts join Send, and the session is
        saved with them.

        Only a pass that WORKED counts. A lead that came back "no model" or
        "qualify error" (no Groq key, a rate limit) is not stored as qualified —
        it keeps a row the button can retry — and a retry that works replaces
        the lead's earlier failed dossier, so nobody is listed twice."""
        from prospector.models import OK
        idle = self._job_done()
        came_back = list(res.dossiers or [])
        good = [d for d in came_back if getattr(d, "status", OK) == OK]
        failed = [d for d in came_back if getattr(d, "status", OK) != OK]
        good_ids = {id(d) for d in good}
        new_drafts = [dr for dr in (drafts or []) if id(dr.dossier) in good_ids]
        if self._res is not None:
            redone = {id(d.lead) for d in good}
            replaced = {id(d) for d in (self._res.dossiers or []) if id(d.lead) in redone}
            self._res.dossiers = [d for d in (self._res.dossiers or [])
                                  if id(d) not in replaced] + good
            kept = [dr for dr in self._drafts if id(dr.dossier) not in replaced]
            # A sheet-only run that now holds qualified leads is a full run.
            if good and self._session_mode == "icp_leads_only":
                self._session_mode = "icp"
                self._run_params = dict(self._run_params, mode="icp")
            self._show_result(self._res, kept + new_drafts)
            self._save_session()
        if idle:
            self._set_running(False)
        text = i18n.t("Qualified {n} — {d} drafted, {r} ready to send.").format(
            n=len(good), d=len(new_drafts), r=len(self._sendable(self._drafts)))
        if failed:
            why = (failed[0].note or "").strip() or i18n.t("the qualify pass failed")
            text += "  " + i18n.t(
                "{n} couldn't be qualified ({why}) — tick them and try again.").format(
                    n=len(failed), why=why.rstrip("."))
        self._status.setText(text + self._used_note())

    def _save_list(self, dossiers):
        """Write the checked leads to a named CSV in the Prism Leads folder — a
        reusable list, saved where every run's sheets already land."""
        if not dossiers:
            return
        name, ok = QInputDialog.getText(
            self, i18n.t("Save to list"), i18n.t("Name this list:"),
            text=i18n.t("My shortlist"))
        if not ok or not name.strip():
            return
        safe = re.sub(r"[^\w .-]+", "", name.strip()) or "list"
        path = os.path.join(self._autosave_dir(), f"{safe}.csv")
        try:
            n = self._write_leads_csv(dossiers, path)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Save to list"), i18n.t(
                "Couldn't write {path}: {err}. If it is open in Excel, close it "
                "and try again.").format(path=path, err=e))
            return
        self._cockpit.refresh_lists()      # show it on the Lists tab at once
        self._keep_as_contacts([d.lead for d in dossiers], "list", list_name=safe)
        QMessageBox.information(
            self, i18n.t("Save to list"),
            i18n.t("Saved {n} lead(s) to:\n{path}").format(n=n, path=path))

    def _export_selected(self, dossiers):
        """The cockpit's Export — the checked leads to a CSV wherever the user
        chooses. (The 'Export sheets' action still writes the full deliverable.)"""
        if not dossiers:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Export selected leads"),
            os.path.join(self._autosave_dir(), "selected leads.csv"),
            "CSV (*.csv)")
        if not path:
            return
        try:
            n = self._write_leads_csv(dossiers, path)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Export"), i18n.t(
                "Couldn't write {path}: {err}. If it is open in Excel, close it "
                "and try again.").format(path=path, err=e))
            return
        # Apollo: "When you export prospects, Apollo also saves them as contacts."
        self._keep_as_contacts([d.lead for d in dossiers], "export")
        QMessageBox.information(
            self, i18n.t("Export"),
            i18n.t("Exported {n} lead(s) to:\n{path}").format(n=n, path=path))

    def _draft_for(self, dos):
        """A row's draft: the current run's, else the one the People page
        holds for that person (their newest run that drafted for them)."""
        return (self._draft_by.get(id(dos))
                or self._cockpit.leads._draft_by.get(id(dos)))

    def _write_leads_csv(self, dossiers, path) -> int:
        from addons.leads.cockpit import status_of
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["name", "company", "title", "email", "fit", "status",
                        "verdict"])
            for d in dossiers:
                lead = d.lead
                w.writerow([lead.name, lead.company, lead.title, lead.email,
                            f"{getattr(lead, 'fit_score', 0) or 0:g}",
                            status_of(d, self._draft_for(d)), d.verdict])
        return len(dossiers)

    def _add_to_sequence(self, dossiers):
        """Enrol the checked leads. For now this sends the first touch (the
        reviewed draft) now; automatic follow-ups arrive with the Phase-2
        stop-on-reply engine. Only leads that were drafted can be enrolled."""
        if not dossiers or self._jobs:
            return
        drafts = [dr for dr in (self._draft_for(d) for d in dossiers) if dr is not None]
        if not drafts:
            QMessageBox.information(
                self, i18n.t("Add to sequence"),
                i18n.t("None of the selected leads has a drafted email yet — "
                       "qualify and draft them first (they must be hot/warm)."))
            return
        # Never resend: the suppression floor would mark a mailed lead 'skipped'
        # and it would stop reading as Mailed.
        drafts = self._pending(drafts)
        if not drafts:
            QMessageBox.information(self, i18n.t("Add to sequence"),
                                    i18n.t("Those leads were already mailed."))
            return
        if not CB.mailer.is_configured(self.cfg):
            self._need_account()
            return
        addr = (self.cfg.get("email") or {}).get("address", "")
        confirm = QMessageBox.question(
            self, i18n.t("Add to sequence"),
            i18n.t("Send the first touch to {n} selected lead(s) now, from "
                   "{addr}?\n\nAutomatic follow-ups arrive with the sequence "
                   "engine — for now this sends touch 1.").format(
                       n=len(drafts), addr=addr))
        if confirm == QMessageBox.StandardButton.Yes:
            self._run_send(drafts)

    def _run_summary(self, res, drafts) -> str:
        dos = res.dossiers
        c = lambda p: sum(1 for d in dos if p(d))
        bits = [i18n.t("Sourced {n}").format(n=res.total_in_sheet),
                i18n.t("qualified {n}").format(n=len(dos)),
                i18n.t("{h} hot / {w} warm / {c} cold").format(
                    h=c(lambda d: d.verdict == "hot"),
                    w=c(lambda d: d.verdict == "warm"),
                    c=c(lambda d: d.verdict == "cold")),
                i18n.t("{n} drafted").format(n=len(drafts))]
        skipped = getattr(res, "skipped_seen", 0) or 0
        if skipped:
            bits.append(i18n.t("{n} already pulled, skipped").format(n=skipped))
        outside = self._outside_bit(res)
        if outside:
            bits.append(outside)
        apollo = self._apollo_bit(res)
        if apollo:
            bits.append(apollo)
        no_email = c(lambda d: d.status == "ok" and not (d.lead.email or "").strip())
        if no_email:
            bits.append(i18n.t("{n} no-email").format(n=no_email))
        errs = c(lambda d: d.status != "ok")
        if errs:
            bits.append(i18n.t("{n} qualify-errors").format(n=errs))
        cov = i18n.t("why-now {a}/{b}").format(
            a=c(lambda d: d.signal_status == "found"), b=len(dos))
        sig_err = c(lambda d: d.signal_status == "source_error")
        if sig_err:
            cov += i18n.t(" ({n} source-errors)").format(n=sig_err)
        bits.append(cov)
        return "   ·   ".join(bits)

    @staticmethod
    def _apollo_bit(res) -> str:
        """"Apollo: 240 found · 25 revealed (about 25 credits)" — what the run
        cost, in the only unit Apollo bills in. Searching is free; a revealed
        person is a credit, so the owner can read the bill off the summary
        instead of the Apollo dashboard. "" for a run that was not Apollo's."""
        stats = getattr(res, "apollo_stats", None)
        if not isinstance(stats, dict):
            return ""
        found = int(stats.get("searched") or 0)
        revealed = int(stats.get("revealed") or 0)
        if not (found or revealed):
            return ""
        return i18n.t("Apollo: {n} found · {m} revealed (about {m} credits)").format(
            n=found, m=revealed)

    @staticmethod
    def _outside_bit(res) -> str:
        """"412 outside your filters (location)" — the people a search turned
        away, and the top reason — or "" when the filters left nobody out."""
        total, why = outside_filters(getattr(res, "filtered_out", None), top=1)
        if not total:
            return ""
        return i18n.t("{n} outside your filters ({why})").format(
            n=total, why=why.split(" ", 1)[-1])

    # ── send ─────────────────────────────────────────────────────────────────
    def _need_account(self):
        QMessageBox.information(
            self, i18n.t("Set up your sending account"),
            i18n.t("No sending account is set up yet. Open the Email spamming "
                   "screen > Change account, add your address and app "
                   "password, then come back and send."))

    def _on_send(self):
        """'Send all' — every drafted lead not already mailed, and not taken
        off the list."""
        pending = self._sendable(self._drafts)
        if not pending or self._jobs:
            return
        if not CB.mailer.is_configured(self.cfg):
            self._need_account()
            return
        addr = (self.cfg.get("email") or {}).get("address", "")
        confirm = QMessageBox.question(
            self, i18n.t("Send outreach"),
            i18n.t("Send {n} personalised email(s) — one to each lead — from "
                   "{addr}?\n\nEach person gets their own message, from your "
                   "own account.").format(n=len(pending), addr=addr))
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self._run_send(pending)

    def _run_send(self, drafts):
        """Shared sender for 'Send all' and 'Add to sequence' (selected).
        Apollo: "Adding prospects to a sequence saves them as contacts" — so
        everyone about to be written to is saved first, and _on_sent moves
        them on from Cold (Apollo's stage trigger)."""
        self._keep_as_contacts([dr.dossier.lead for dr in drafts], "sequence")
        self._set_running(True, sending=True)
        self._status.setText(i18n.t("Sending…"))
        self._send_worker = LeadsSendWorker(drafts, self.cfg)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_sent)
        self._send_worker.failed.connect(self._on_failed)
        self._job_started()
        self._send_worker.start()

    def _on_send_progress(self, i, total, _draft):
        self._status.setText(i18n.t("Sent {i} of {total}…").format(
            i=i, total=total))
        self._save_session()                # a crash mid-send keeps who was mailed

    def _on_sent(self, sent, failed):
        if self._job_done():
            self._set_running(False)
        # Apollo's stage trigger: "Approaching — you have sent the contact at
        # least one message". Only a contact still Cold moves; a stage the
        # owner set by hand stands.
        worker = self._send_worker
        sent_drafts = [dr for dr in getattr(worker, "drafts", None) or ()
                       if getattr(dr, "status", "") == "sent"]
        mailed = [dr.dossier.lead for dr in sent_drafts]
        if sent_drafts:
            # Each send, with its subject, in the contact's Activities.
            from addons.leads import contacts as CT
            try:
                CT.log_sent(self._contacts_dir(),
                            [(dr.dossier.lead, dr.subject) for dr in sent_drafts])
            except CT.StoreError as e:
                self._status.setText(str(e))
        moved = self._advance_stage(mailed, "Approaching", ("Cold",)) if mailed else 0
        if getattr(self, "_res", None) is not None:
            # A sent draft reads "Mailed" in Status — and under Email status.
            self._cockpit.set_run(self._res.dossiers, self._drafts)
        if moved or getattr(self, "_res", None) is not None:
            self._rebuild_pool_keep_page()      # …and a new stage under Stage
        self._save_session()
        self._status.setText(i18n.t("Sent {s}, failed {f}.").format(
            s=len(sent), f=len(failed)))
        QMessageBox.information(
            self, i18n.t("Leads & Outreach"),
            i18n.t("Sent {s} email(s). {f} failed.").format(
                s=len(sent), f=len(failed)))

    # ── shared ───────────────────────────────────────────────────────────────
    def _autosave_dir(self) -> str:
        """Where a run's sheets land without asking — a predictable folder the
        user can always find, created on first use."""
        import paths
        d = paths.user_folder("Documents", "Prism Leads")
        try:
            os.makedirs(d, exist_ok=True)
        except Exception:                                   # noqa: BLE001
            d = paths.real_home()
        return d

    def _export(self):
        """The 'Export sheets' action — choose where, and confirm loudly."""
        if self._jobs:
            return
        if not self._res or not (self._res.dossiers
                                 or getattr(self._res, "all_leads", None)):
            QMessageBox.information(self, i18n.t("Leads & Outreach"),
                                    i18n.t("Prepare a list first."))
            return
        folder = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose a folder for the sheets"))
        if not folder:
            return
        self._start_export(folder, announce=True)

    def _start_export(self, folder: str, announce: bool):
        """Write the two xlsx (live MX check per row → worker thread) plus the
        drafts CSV. `announce=False` is the automatic save after a run — quiet,
        opens the folder once; `announce=True` is the button — confirms loudly."""
        if not self._res or not (self._res.dossiers
                                 or getattr(self._res, "all_leads", None)):
            return
        self._announce_export = announce
        # The drafts CSV is quick — write it inline; the xlsx go to the worker.
        from prospector import reach
        # Whoever the owner took off the list is off the sheets too.
        def kept(lead):
            return not self._is_removed(lead)

        drafts = [d for d in self._drafts
                  if kept(getattr(getattr(d, "dossier", None), "lead", None))]
        try:
            reach.write_outreach(drafts, os.path.join(folder, "outreach.csv"))
        except Exception:                                   # noqa: BLE001
            pass
        self._set_running(True)
        self._status.setText(i18n.t("Verifying e-mails and writing the sheets…"))
        self._export_worker = LeadsExportWorker(
            [lead for lead in self._res.all_leads or () if kept(lead)],
            [d for d in self._res.dossiers or () if kept(getattr(d, "lead", None))],
            folder)
        self._export_worker.progress.connect(self._status.setText)
        self._export_worker.done.connect(self._on_exported)
        self._export_worker.failed.connect(self._on_failed)
        self._job_started()
        self._export_worker.start()

    def _on_exported(self, paths):
        if self._job_done():
            self._set_running(False)
        self.refresh_lists()                # the new sheets belong on Lists now
        folder = os.path.dirname(paths[0]) if paths else ""
        self._status.setText(
            i18n.t("Leads sheet + hot list saved to {f}").format(f=folder)
            if folder else i18n.t("Sheets written."))
        if folder and (self._announce_export or not self._opened_autosave):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self._opened_autosave = True
        if self._announce_export:
            QMessageBox.information(
                self, i18n.t("Leads & Outreach"),
                i18n.t("Wrote the leads sheet and the hot list (xlsx), plus "
                       "outreach.csv, to that folder."))

    def _sender(self) -> str:
        try:
            import identity
            return identity.describe() or ""
        except Exception:                                   # noqa: BLE001
            return ""

    def _set_running(self, running: bool, sending: bool = False):
        ring = getattr(self, "_busy_ring", None)
        if ring is not None:
            ring.setVisible(running)
        # The FILTERS stay usable: a running search took its filters when it
        # started, and browsing the people Prism holds costs nothing — Apollo
        # never locks its rail either.
        for w in (self._offer, self._claims, self._limit, self._verify_limit,
                  self._prepare, self._prepare_all, self._send_btn,
                  self._export_btn, self._target, self._exa, self._apollo,
                  self._src_apollo, self._src_exa, self._skip_seen):
            w.setEnabled(not running)
        # …except a source Apollo has already refused: re-enabling it here would
        # hand the owner a button that only leads to the same 403.
        if self._apollo_blocked:
            self._src_apollo.setEnabled(False)
        # The bulk bar's six ACTION buttons start sends and verifies too —
        # another background job while this one is still going. "Clear" and
        # "Select all" are not: pure local selection state, nothing they do
        # touches a running worker, and disabling the whole bar caught them
        # anyway — live report, 22-Sep-2026, a customer pressed "Clear"
        # mid-run and it did genuinely nothing (worse, it *looked* enabled
        # the whole time — QPushButton#bulkLink has no :disabled rule of
        # its own; see style fix above — so there was no way to tell a
        # disabled control from a broken one). Disabling only the buttons
        # that actually need it fixes both: the real bug (Clear was blocked
        # for no reason) and the visible one (it no longer needs to LOOK
        # disabled, because it just isn't).
        cockpit = getattr(self, "_cockpit", None)
        if cockpit is not None:
            for b in cockpit.leads._bulk_actions():
                if b in (cockpit.leads._b_contact, cockpit.leads._b_stage,
                         cockpit.leads._b_remove):
                    continue                # Save, Set stage, Remove: local writes
                b.setEnabled(not running)
            if not running:
                # Each button's real, selection-driven state — not just
                # unconditionally back on, which would offer "Qualify" with
                # nothing left to qualify.
                cockpit.leads._refresh_bulk()
        if not running:
            self._refresh_prepare()
            self._send_btn.setEnabled(bool(self._sendable(self._drafts)))
            # After the finishing job's own bookkeeping (the page rebuilt):
            # the open person as they now stand, then the next enrichment.
            QTimer.singleShot(0, self, self._after_job)
            self._export_btn.setEnabled(self._res is not None
                                        and bool(getattr(self._res, "dossiers", None)
                                                 or getattr(self._res, "all_leads", None)))

    def _after_job(self) -> None:
        if getattr(self, "_cockpit", None) is not None:
            self._cockpit.leads.refresh_person()
        if self._enrich_queue and not self._jobs:
            self._next_enrichment()

    # ── background jobs ───────────────────────────────────────────────────────
    def _job_started(self):
        if self._jobs == 0 and self._pooled():
            gateway.reset()             # a new run: its spend counts from zero
        self._jobs += 1

    def _job_done(self) -> bool:
        """One background job finished; True when none are left running."""
        self._jobs = max(0, self._jobs - 1)
        if self._jobs == 0:
            self._refresh_credits()     # what the run cost is now off the balance
        return self._jobs == 0

    @staticmethod
    def _pending(drafts) -> list:
        """Drafts not yet mailed — what Send may still send."""
        return [d for d in (drafts or []) if getattr(d, "status", "") != "sent"]

    def _sendable(self, drafts) -> list:
        """What Send all may send: drafts not yet mailed, to nobody the owner
        took off the list (Remove), and to someone Prism holds a real address
        for. A guessed one is set aside when a lead is read back (24-Sep-2026),
        and reach.send skips a draft with no address — so the count says the
        same."""
        out = []
        for d in self._pending(drafts):
            lead = getattr(getattr(d, "dossier", None), "lead", None)
            if lead is None or self._is_removed(lead):
                continue
            if not (getattr(lead, "email", "") or "").strip():
                continue
            out.append(d)
        return out

    # ── sessions: every run is kept, and no run repeats people ────────────────
    def _sessions_dir(self) -> str:
        """This member's Leads sessions: under their workspace folder, beside
        their run history (shared-drive aware, readable by a manager), falling
        back to ~/.prism when no workspace resolves. Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "sessions")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "sessions")

    def _save_session(self):
        """Write (or rewrite) the session on screen. Never raises into the UI —
        a failed save is said on the status line."""
        if self._res is None or not self._session_id:
            return
        try:
            from addons.leads import sessions
            sessions.save(
                self._sessions_dir(), self._session_id, mode=self._session_mode,
                params=self._run_params, all_leads=list(self._res.all_leads or []),
                dossiers=list(self._res.dossiers or []), drafts=list(self._drafts),
                total_in_sheet=self._res.total_in_sheet,
                signal_source=getattr(self._res, "signal_source", "") or "",
                skipped_seen=getattr(self._res, "skipped_seen", 0) or 0)
        except Exception as e:                              # noqa: BLE001
            self._status.setText(str(e) or i18n.t("Couldn't save this session."))
            return
        refresh = getattr(self._cockpit, "refresh_sessions", None)
        if refresh is not None:
            refresh(self._session_id)

    def restore_latest(self):
        """When the screen first opens: everyone Prism holds (the pool — every
        saved contact and every run), and the latest session as the current
        run (what Send all and Export sheets act on). Both read off the UI
        thread; the session is dropped if the user has already started
        something."""
        self.reload_pool()
        self._load_session("")

    def open_session(self, session_id: str):
        """Open a session picked on the Sessions tab."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then open the session."))
            return
        self._load_session(session_id)

    def _load_session(self, session_id: str):
        self._restoring = session_id or "latest"
        self._load_worker = LeadsSessionLoadWorker(self._sessions_dir(), session_id)
        self._load_worker.done.connect(self._on_session_loaded)
        self._load_worker.failed.connect(self._on_session_load_failed)
        self._load_worker.start()

    def _on_session_loaded(self, loaded):
        explicit = self._restoring not in ("", "latest")
        self._restoring = ""
        if loaded is None:
            return
        # Never clobber live work: a run in flight, or (for the automatic
        # restore) a run the user already finished while this was loading.
        if self._jobs or (not explicit and self._res is not None):
            return
        self._apply_session(loaded, scope=explicit)

    def _on_session_load_failed(self, msg):
        explicit = self._restoring not in ("", "latest")
        self._restoring = ""
        if explicit:
            QMessageBox.warning(self, i18n.t("Open session"), msg)
        else:
            self._status.setText(i18n.t(
                "Couldn't restore the last session: {err}").format(err=msg))

    def _apply_session(self, loaded: dict, scope: bool = False):
        """Make a saved session the current run, exactly as it was — no
        re-export, no re-save. `scope` (a session opened from the Sessions
        tab) narrows the People page to that run's people, with "Show
        everyone" on the run line to widen it again; the automatic restore
        at startup shows everyone."""
        from prospector import engine
        head = loaded.get("header") or {}
        params = loaded.get("params") or {}
        res = engine.RunResult(
            dossiers=list(loaded.get("dossiers") or []),
            total_in_sheet=int(loaded.get("total_in_sheet") or 0),
            signal_source=loaded.get("signal_source") or "",
            all_leads=list(loaded.get("all_leads") or []))
        res.skipped_seen = int(loaded.get("skipped_seen") or 0)
        self._session_id = head.get("id", "")
        self._session_mode = params.get("mode") or head.get("mode") or "sheet"
        self._run_params = dict(params)
        self._scope = self._session_id if scope else ""
        self._restore_inputs(params)
        self._show_result(res, loaded.get("drafts") or [])
        when = _when(head.get("created_at", ""))
        self._status.setText(
            i18n.t("Showing the people from the session of {when}.").format(when=when)
            if scope else i18n.t("Opened the session from {when}.").format(when=when))
        self._scope_btn.setVisible(bool(self._scope))
        if scope:
            self._cockpit.show_people_tab()
        refresh = getattr(self._cockpit, "refresh_sessions", None)
        if refresh is not None:
            refresh(self._session_id)

    def _restore_inputs(self, params: dict):
        """Put an opened session's search back in the rail, so a new search
        starts from what that run asked. A session saved before filters comes
        back as the filters it meant: "Global except india" is Location,
        excluding India. (An old "sheet" session carries no filters; the rail
        is left as it is.)"""
        # Always the source that run asked — a session saved before Prism could
        # ask Apollo carries none, and can only have been an Exa run. Leaving
        # the rail on its own default (Apollo, whenever that key is set) would
        # re-point a search the owner reopened to repeat at a database that
        # bills per person.
        self._set_source(params["source"]
                         if params.get("source") in ("apollo", "exa") else "exa")
        if (isinstance(params.get("filters"), dict)
                or any(params.get(k) for k in ("industries", "roles", "location"))):
            self._filters.set_spec(SearchSpec.from_params(params))
        for spin, key in ((self._target, "target"), (self._limit, "limit"),
                          (self._verify_limit, "verify_limit")):
            try:
                spin.setValue(int(params[key]))
            except (KeyError, TypeError, ValueError):
                pass
        if params.get("offer"):
            self._offer.setPlainText(str(params["offer"]))
        if params.get("claims_path"):
            self._claims_path = params["claims_path"]
            self._claims_lbl.setText(os.path.basename(self._claims_path))
        self._skip_seen.setChecked(not params.get("include_earlier", False))
        self._refresh_prepare()

    # ── saved searches: filters kept to run again ─────────────────────────────
    def _searches_dir(self) -> str:
        """This member's saved searches, beside their Leads sessions (see
        _sessions_dir). Tests patch this method."""
        try:
            import identity
            import workspace
            return workspace.member_dir(identity.current()["mid"], self.cfg,
                                        "leads", "searches")
        except Exception:                                   # noqa: BLE001
            import paths
            return paths.user_dir("leads", "searches")

    def _ask_search_name(self, suggested: str = ""):
        """(name, ok) from the owner. A seam, so a test never opens a dialog."""
        return QInputDialog.getText(self, i18n.t("Save search"),
                                    i18n.t("Name this search:"), text=suggested)

    def _confirm_delete(self, name: str) -> bool:
        """True when the owner confirms. A seam, so a test never opens a box."""
        return QMessageBox.question(
            self, i18n.t("Delete saved search"),
            i18n.t("Delete the saved search “{name}”? Sessions its runs saved "
                   "are kept.").format(name=name)) == QMessageBox.StandardButton.Yes

    def _run_settings(self) -> dict:
        return {"target": self._target.value(), "limit": self._limit.value(),
                "verify_limit": self._verify_limit.value(),
                "include_earlier": not self._skip_seen.isChecked(),
                "offer": self._offer.toPlainText().strip()}

    def _save_search(self):
        """The filter panel's Save search: name it, keep the filters and the run
        settings. Saving under the name of the search that is on the rail
        updates that search instead of refusing the name as taken."""
        folder = self._searches_dir()
        active = saved_searches.get(folder, self._active_search_id) \
            if self._active_search_id else None
        name, ok = self._ask_search_name(active["name"] if active else "")
        if not ok or not (name or "").strip():
            return
        spec = self._filters.spec()
        same = active is not None and " ".join(name.split()).casefold() \
            == active["name"].casefold()
        try:
            record = saved_searches.save(folder, name, spec.to_dict(),
                                         settings=self._run_settings(),
                                         search_id=active["id"] if same else None)
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        self._active_search_id = record["id"]
        self._active_search_filters = record["filters"]
        self._status.setText(i18n.t("Saved “{name}”.").format(name=record["name"]))
        self._cockpit.refresh_searches()

    def use_saved_search(self, search_id: str):
        """"Use search" on the Saved searches tab, or a pick from Default view
        ▾: its filters and settings go back in the rail — the People page
        filters at once, over everyone Prism holds — and Find new people is
        there to fetch more. Never run on its own."""
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then use the search."))
            return
        record = saved_searches.get(self._searches_dir(), search_id)
        if record is None:
            self._status.setText(i18n.t("That saved search is no longer there."))
            self._cockpit.refresh_searches()
            return
        self._filters.set_spec(record["filters"])
        settings = record.get("settings") or {}
        for spin, key in ((self._target, "target"), (self._limit, "limit"),
                          (self._verify_limit, "verify_limit")):
            if isinstance(settings.get(key), int):
                spin.setValue(settings[key])
        if (settings.get("offer") or "").strip():
            self._offer.setPlainText(settings["offer"])
        if isinstance(settings.get("include_earlier"), bool):
            self._skip_seen.setChecked(not settings["include_earlier"])
        self._cockpit._select(0)
        self._active_search_id = record["id"]
        self._active_search_filters = record["filters"]
        self._status.setText(i18n.t(
            "Loaded “{name}” — the people Prism holds are filtered by it; press "
            "Find new people to search for more.").format(name=record["name"]))

    def use_starter(self, key: str):
        """A starter search from Default view ▾: its filters in the rail, the
        page filtered by them at once — like a saved search, never run on
        its own."""
        if key not in _STARTERS:
            return
        if self._jobs:
            self._status.setText(i18n.t(
                "Wait for the current job to finish, then use the search."))
            return
        name, make = _STARTERS[key]
        self._filters.set_spec(make())
        self._active_search_id, self._active_search_filters = "", None
        self._cockpit._select(0)
        self._status.setText(i18n.t(
            "Loaded “{name}” — the people Prism holds are filtered by it; press "
            "Find new people to search for more.").format(name=i18n.t(name)))

    def _delete_saved_search(self, search_id: str):
        folder = self._searches_dir()
        record = saved_searches.get(folder, search_id)
        if record is None:
            self._cockpit.refresh_searches()
            return
        if not self._confirm_delete(record["name"]):
            return
        try:
            saved_searches.delete(folder, search_id)
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        if search_id == self._active_search_id:
            self._active_search_id, self._active_search_filters = "", None
        self._status.setText(i18n.t("Deleted “{name}”.").format(name=record["name"]))
        self._cockpit.refresh_searches()

    def _record_search_run(self, res):
        """A finished Find-people run of the saved search on the rail counts as
        one of its runs — but only while the filters are still the ones saved;
        a search edited after Use is a different search."""
        if (not self._active_search_id or self._session_mode == "sheet"
                or self._run_params.get("filters") != self._active_search_filters):
            return
        try:
            saved_searches.mark_run(
                self._searches_dir(), self._active_search_id, self._session_id,
                new_people=len(getattr(res, "all_leads", None) or []))
        except saved_searches.SavedSearchError as e:
            self._status.setText(str(e))
            return
        self._cockpit.refresh_searches()
