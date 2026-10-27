"""Email inquiry automation — the working screen.

The three phases the customer described, in the order they happen and visibly
separated, because the difference between them is the difference between
software you leave running and software you supervise:

    READ      fetch every mailbox, sort, file the drawings, write the one
              register. Runs on its own. Nothing here can cost anybody money.

    ANSWER    price it, draft the covering mail, send it, read the reply,
              update the register. Prism prepares; a person presses Send.

    MAKE      the order is in — put the PO against the quotation, accept it,
              hand the drawing to BOQ and get the quantities out.

Only the first is automatic, and the tabs say so. Two of the steps move
money — a price going to a customer, and accepting a purchase order — and
those are the two places a human is required. Everything else runs unattended.

Several mailboxes, one register: the check walks the configured accounts one
at a time — never in parallel, because every account's rows land in the same
CSV and two writers racing on one order book is how a row is lost — and each
account carries its own read bookmark. One dead mail server skips to the next
account; one locked register stops the walk, because the same lock would
refuse every account after it and none of their bookmarks have moved.
Several MACHINES writing one register is deliberately not built — the office
PC that stays on does the writing, everyone else reads. docs/DEFERRED.md has
the trigger that would change that.
"""
from __future__ import annotations

import contextlib
import csv
import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QDate, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QDialog,
    QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QRadioButton, QSizePolicy, QStackedWidget, QStyle,
    QStyledItemDelegate, QTabBar,
    QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import email_config
import i18n
from widgets.loader import Loader
import theme
from dialogs.base import PrismDialog
from addons.inquiry import autoquote, documents
from addons.inquiry.setup import (
    InquirySetupDialog, accounts_of, active_accounts_of, is_ready, settings_of,
)
from widgets import controls as C
from workers import DraftWorker, InboxCheckWorker, POReadWorker, SendWorker
from addons.inquiry.pipeline_actions import PipelineActions, PipelineScreen

# What each sorted category is called on screen. The engine's keys are English
# identifiers; these are the words a customer reads.
CATEGORY_LABELS = {
    "inquiry": "Inquiry", "order": "Purchase order", "payment": "Payment",
    "promotion": "Promotion", "vendor": "Supplier", "internal": "Internal",
    "other": "Other", "unsorted": "Needs a look",
}

# The "Show:" date filter — shared by the register tab and the arrived-mail
# log. "week" and "older" split on the same boundary (today minus 6 days) so
# the two are exact complements of each other and nothing between them is
# silently dropped from either.
REGISTER_RANGES = [
    ("all", "All time"), ("today", "Today"), ("yesterday", "Yesterday"),
    ("week", "Last 7 days"), ("older", "Older than that"),
    ("custom", "Pick dates…"),
]


def _parse_iso(text: str) -> date | None:
    """A plain YYYY-MM-DD back into a date, or None for anything blank or
    unreadable — the worklist file's own dates, as opposed to the register's
    hand-typeable ones which go through register.parse_date() instead."""
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def _in_date_range(when: date | None, filter_key: str, today: date,
                   start: date | None = None, end: date | None = None) -> bool:
    """One rule, used everywhere a "Show:" filter reads a date — the
    register, and the arrived-mail log below it.

    An unreadable or missing date — a hand-typed register the owner edited,
    or an old worklist row from before a field existed — falls under "Older
    than that" rather than every bucket or none: it is shown somewhere,
    which a silent drop is not, and it is not claimed as today's when
    nobody can say that it is. "custom" is the owner's own from/to pair,
    both ends inclusive, which is how a person says "from the 1st to the
    15th".
    """
    if filter_key == "all":
        return True
    if filter_key == "custom":
        if when is None:
            return False
        if start is not None and end is not None and start > end:
            start, end = end, start
        return (start is None or when >= start) and (end is None or when <= end)
    if when is None:
        return filter_key == "older"
    if filter_key == "today":
        return when == today
    if filter_key == "yesterday":
        return when == today - timedelta(days=1)
    if filter_key == "week":
        return today - timedelta(days=6) <= when <= today
    if filter_key == "older":
        return when < today - timedelta(days=6)
    return True

SOURCE_LABELS = {
    "rule": "sorted here, by a rule",
    "learned": "sorted here, you taught it",
    "ai": "sorted by Prism's brain",
    "none": "not sorted",
}

ARRIVED_SENTENCE = (
    "Every mail Prism has read and how it sorted it. If one is in the "
    "wrong column, correct it here and Prism will remember that sender.")
# Shown once the log has ever grown past its working-file cap — see
# worklist.has_archive(). The cap moves the oldest rows to an archive file
# instead of deleting them, so this sentence must say so rather than let
# the tab look like it quietly lost mail.
ARRIVED_ARCHIVE_NOTE = (
    "Older mail beyond the most recent few thousand has moved to this "
    "inquiry folder's archive file — nothing is deleted.")

# ── colour ───────────────────────────────────────────────────────────────────
# A tinted background and a dark ink for each category and each status, so a
# hundred-row register can be read at arm's length: green is money coming in,
# amber wants you, grey can wait.
#
# The colour is never the only signal. Every cell that is tinted also carries
# the word, because roughly one man in twelve cannot tell the red from the
# green — and because a register printed on the office laser comes out grey.
#
# EVERY PAIR BELOW IS A theme.py TOKEN. It did not use to be: the three tables
# here carried sixteen hexes that matched nothing in the palette — three
# different "success greens", two ambers plus a third that was one digit off
# theme.WARN_INK, a blue and a red that duplicated the accent and error ramps
# without matching them, and the only purple in the application. Every one of
# them was invisible to the per-role accent rotation, which is a blunt string
# replace over eleven known hexes: in a manager's green profile the entire
# register stayed Prism blue and amber while the rest of the app moved, and the
# purple stayed purple in all eleven roles.
#
# The semantic tones (OK / WARN / ERR) sit outside the accent ramp on purpose
# and DO NOT rotate, which is exactly what this register needs: "Converted"
# has to stay green and "Not converted" has to stay red in every profile, or
# the one column the owner reads at a glance stops meaning anything. INFO is
# the accent's own mid step and does rotate, by design — it is used here only
# for "this is information", never for an outcome.
_OK = (theme.OK_BG, theme.OK_INK)              # money — won, confirmed
_WARN = (theme.WARN_BG, theme.WARN_INK)        # a person is needed here
_ERR = (theme.ERR_BG, theme.ERR_INK)           # lost
_INFO = (theme.INFO_BG, theme.INFO_INK)        # live, or informational
_NEUTRAL = (theme.NEUTRAL[200], theme.NEUTRAL[800])   # waiting, filed
_QUIET = (theme.NEUTRAL[100], theme.NEUTRAL[700])     # noise

CATEGORY_COLOURS = {
    "inquiry":   _OK,        # the reason they bought this
    "order":     _OK,        # money confirmed
    "payment":   _INFO,      # accounts, not sales
    # Amber is reserved for the one row that genuinely needs a human to look
    # at it. A supplier's mail is filed, not urgent.
    "vendor":    _NEUTRAL,   # someone selling TO them
    "promotion": _QUIET,     # noise
    "internal":  _QUIET,
    "other":     _QUIET,
    "unsorted":  _WARN,      # needs a human glance
}

# The sales pipeline: one colour per state, on every register tab, in the
# Excel copy and in its legend ([12][15][17], the owner's decision of 13 Oct
# 2026). Yet to quote is blue, quoted grey, no reply (chased) amber,
# negotiating orange, won green, lost red. Until then New, Accepted and
# Converted were one green, and Quoted and Following up two greys a person
# could not tell apart. "Accepted" is green with Converted: the customer has
# said yes, and the owner's own list groups it with the PO.
#
# The hexes live in theme.REGISTER_TONES (a light and a dark pair each).
# STATUS_COLOURS is the light set, which is what Prism paints today
# (theme.apply_palette pins light); status_colours() follows the palette.
STATUS_STATES = {
    "New":            "new",
    "Quoted":         "quoted",
    "Following up":   "no_reply",
    "Negotiating":    "negotiating",
    "Accepted":       "won",
    "Converted":      "won",
    "Not converted":  "lost",
}


def status_colours(dark: bool | None = None) -> dict:
    """{register status: (background, ink)} for the running palette, or for
    the light or dark one when `dark` is given."""
    tones = theme.register_tones(dark)
    return {status: tones[state] for status, state in STATUS_STATES.items()}


STATUS_COLOURS = status_colours(dark=False)

# What Prism made of a customer's reply, in the owner's words rather than the
# engine's identifiers.
INTENT_LABELS = {
    "accepted": "They accepted",
    "rejected": "They declined",
    "negotiating": "They want a better rate",
    "needs_info": "They asked a question",
    "unclear": "Prism can't tell — read it yourself",
}

INTENT_COLOURS = {
    # The three that decide a status wear that status's colour, so the
    # intent cell never disagrees with the row it sits on.
    "accepted":    STATUS_COLOURS["Accepted"],
    "rejected":    STATUS_COLOURS["Not converted"],
    "negotiating": STATUS_COLOURS["Negotiating"],
    "needs_info":  _INFO,     # they asked for information
    "unclear":     _NEUTRAL,
}


# Moved to addons/inquiry/quotation.py and re-exported, so that
# `UI.QuotationDialog` and friends keep resolving wherever they are
# already written. The import is one-way: nothing in quotation_dialog
# imports back from here.
from addons.inquiry.quotation import (        # noqa: E402,F401
    DRAWING_EXTENSIONS, QuotationDialog, _AttachmentsDialog, _CompareDialog,
    _POReviewDialog, _attachment_files, _default_body, _quantity_of,
    _warning_css, open_in_file_manager,
)


class _TableOrEmpty(QStackedWidget):
    """A table, or — while it has no rows — a centred empty state.

    All five tabs of this screen open empty and stay empty until a mail check
    runs, and an empty QTableWidget is a column header over several hundred
    pixels of blank white. That is the screen a customer meets the first time
    they open Email inquiry automation, and it says nothing about what will appear
    there or how to make it appear.

    Driven off the model's own signals rather than by editing the five places
    that fill these tables: `setRowCount()` emits rowsInserted / rowsRemoved,
    so the swap cannot fall out of step with the data the way a hand-placed
    call would.
    """

    def __init__(self, table, icon: str, title: str, body: str, parent=None):
        super().__init__(parent)
        self._table = table
        self.addWidget(table)
        self.empty = C.EmptyState(icon, title, body)
        self.addWidget(self.empty)
        model = table.model()
        for signal in (model.rowsInserted, model.rowsRemoved,
                       model.modelReset, model.layoutChanged):
            signal.connect(self._sync)
        self._sync()

    def _rows(self) -> int:
        return self._table.model().rowCount()

    def _sync(self, *_args):
        self.setCurrentIndex(0 if self._rows() else 1)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:          # noqa: N802 — Qt's name
        """The page on show, not the largest of the two. A QStackedWidget
        asks for its tallest page's minimum even while it is hidden, so the
        empty state's icon, title and sentence held the table open at their
        height with rows on screen and squeezed the Selected panel under it
        until its controls overlapped. A table keeps its header and two
        rows and scrolls the rest: at 1078x900 They answered needs that
        much for the reply, the verdict and the row's buttons."""
        if self.currentIndex() != 0:
            return super().minimumSizeHint()
        table = self._table
        floor = (table.horizontalHeader().sizeHint().height()
                 + 2 * table.verticalHeader().defaultSectionSize()
                 + 2 * table.frameWidth())
        return QSize(super().minimumSizeHint().width(), floor)


# ── the six tabs, in the order an inquiry lives ──────────────────────────────
# "To quote" first because "2 to quote" is the number the owner opens Prism
# for; the two "All …" tabs last because they are for looking things up, not
# for the day's work. The numbers in the labels are the reading order and
# are what the tests pin.
# Moved to inquiry_config.py and re-exported here, so everything that already
# imports them from this module keeps working. addons/inquiry/panel.py used
# to reach into this 4,000-line dialog at MODULE SCOPE for these three names
# -- the only widget->dialog import in the tree that was not a deferred "open
# this modal", and so a real load-order dependency.
from addons import names, registry      # noqa: E402
from inquiry_config import (            # noqa: E402,F401
    COUNTED_TABS, TAB_INDEX, TABS,
)

# The tables whose pick _refresh_register() carries over a reload
# (_reselect). They answered and Order came keep their own.
_RESELECT_TABS = ("to_quote", "waiting", "register")


# Every button the Selected-inquiry panel can show, in the words the owner
# reads. The key is what actions_for() returns; the variant is fixed per
# button because a button that is primary on one row and secondary on the
# next is a button nobody learns.
ROW_ACTIONS = [
    ("prepare", "Prepare a quotation", "primary"),
    ("remind", "Send a reminder", "primary"),
    ("win_back", "Write a reply to win them back", "primary"),
    ("record_po", "Record the PO by hand", "primary"),
    ("already_quoted", "Already quoted by phone", "secondary"),
    ("boq", "Count quantities from the drawing", "secondary"),
    ("phone", "They replied by phone…", "secondary"),
    ("lost", "Mark as lost", "secondary"),
    ("revise", "Send a revised quotation", "secondary"),
    ("edit", "Edit details", "tertiary"),
    ("folder", "Open this inquiry's folder", "tertiary"),
    ("attachments", "View attachments", "tertiary"),
    ("history", "See the whole story", "tertiary"),
    ("delete", "Delete this inquiry", "destructive"),
]


def actions_for(status: str, tab: str = "register",
                has_drawing: bool = False) -> list[str]:
    """Which buttons a register row gets, by where it is in its life.

    The seven-button row this replaces showed every action for every row,
    all the time — "Win this back" on an inquiry nobody had quoted yet,
    "Prepare a quotation" on one already converted. A person who has never
    used a CRM reads that as "which of these am I meant to press?", and the
    honest answer for any one row is two or three of them. So: at most
    three boxed buttons, the first of them the one the row is waiting for,
    plus the two quiet links every row gets.

    Pure — no Qt — so the table below can be tested as a table.
    """
    register = CB.get_register()
    status = (status or "").strip()
    if status in ("", register.NEW):
        keys = (["prepare", "boq", "already_quoted"] if has_drawing
                else ["prepare", "already_quoted"])
    elif status in (register.QUOTED, register.FOLLOWING_UP):
        keys = ["remind", "phone", "lost"]
    elif status == register.NEGOTIATING:
        keys = ["win_back", "revise", "phone"]
    elif status == register.ACCEPTED:
        keys = ["record_po", "phone", "lost"]
    elif status == register.CONVERTED:
        keys = ["boq"] if has_drawing else []
    elif status == register.NOT_CONVERTED:
        keys = ["win_back"]
    else:
        keys = []
    # Every row can be edited, opened, read back as its own story, and — the
    # owner asked for this on every row, not only new ones — deleted, with
    # the "block this sender?" question that follows. A newsletter that got
    # itself registered is the commonest reason, and it can be sitting at
    # any status.
    return keys + ["edit", "folder", "attachments", "history", "delete"]


class _RoomyTabBar(QTabBar):
    """A tab bar that gives every title a few pixels more than Qt thinks it
    needs. Measured with the real stylesheet, Qt's own sizeHint came out
    two pixels short of the semi-bold text the stylesheet paints — enough
    to shave the last letter. Asking for the slack here, rather than
    hunting the exact padding arithmetic, is what makes it impossible to
    regress when the font or the stylesheet moves."""

    # Keep a little more than the painted semi-bold title needs. The opaque
    # tab treatment adds a border, and the extra two pixels preserve the
    # no-truncation guarantee at the smallest supported window size.
    SLACK = 10

    def tabSizeHint(self, index: int):      # noqa: N802 — Qt's name
        hint = super().tabSizeHint(index)
        return QSize(hint.width() + self.SLACK, hint.height())


class _Tabs(QTabWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTabBar(_RoomyTabBar(self))


class _ReplyBox(QPlainTextEdit):
    """The customer's reply on They answered. Asks for `ask` pixels of
    height instead of QPlainTextEdit's stock 192, and scrolls past them."""

    ask = 0

    def sizeHint(self) -> QSize:                 # noqa: N802 — Qt's name
        hint = super().sizeHint()
        return QSize(hint.width(), self.ask) if self.ask else hint


class _StatusLine(QLabel):
    """The one-line message under the header. Hides itself when it has
    nothing to say, so an idle screen does not carry an empty band — and
    shows itself the moment it has, so "Checking demo@…" is never written
    into a label nobody can see."""

    def setText(self, text: str):          # noqa: N802 — Qt's name
        super().setText(text)
        self.setVisible(bool(text))


class _SelectedPanel(C.Card):
    """The card under every table: which row is picked, where it stands,
    and only the buttons that make sense for it.

    Buttons are built once and shown or hidden per row, never rebuilt — so
    `remind_btn`, `po_btn` and the rest stay stable objects the rest of the
    dialog (and the tests) can hold on to. The row of buttons is a
    FlowLayout: at any width the two quiet links wrap under the boxed
    buttons instead of being cut off at the edge, which is the failure the
    owner photographed.
    """

    def __init__(self, parent=None):
        super().__init__(stripe=True, parent=parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        col = self.body((theme.CARD_PAD, theme.SPACE_3,
                         theme.CARD_PAD, theme.SPACE_3), theme.SPACE_2)
        self.title = C.label("", level="CARD_TITLE", wrap=True)
        col.addWidget(self.title)
        self.info = C.label("", level="META", wrap=True)
        col.addWidget(self.info)
        # A slot a tab can put its own controls in — the reply text and the
        # "Prism thinks" row on the replies tab, the re-sort row on the mail
        # log. Hidden with the rest when nothing is selected.
        self.extra_host = QWidget()
        self.extra = QVBoxLayout(self.extra_host)
        self.extra.setContentsMargins(0, 0, 0, 0)
        self.extra.setSpacing(theme.SPACE_2)
        col.addWidget(self.extra_host)
        self._flow_host = QWidget()
        self.flow = C.FlowLayout(self._flow_host)
        col.addWidget(self._flow_host)
        self.buttons: dict[str, QPushButton] = {}
        self.clear()

    def add_action(self, key: str, text: str, variant: str = "secondary",
                   on_click=None) -> QPushButton:
        btn = C.button(i18n.t(text), variant, on_click=on_click)
        self.buttons[key] = btn
        self.flow.addWidget(btn)
        return btn

    def show_row(self, title: str, info: str, keys, extra: bool = False):
        self.title.setText(title)
        self.info.setText(info)
        self.info.setVisible(bool(info))
        keys = set(keys)
        for key, btn in self.buttons.items():
            btn.setVisible(key in keys)
        self._flow_host.setVisible(bool(keys))
        self.extra_host.setVisible(extra)

    def clear(self):
        self.show_row(i18n.t("Pick a row above."), "", ())


class _TabPage(QWidget):
    """One tab, always the same four parts top to bottom: a sentence saying
    what the list is and what to do; a toolbar (Show: range, search); the
    table, which is the ONLY thing that grows with the window; and the
    Selected-inquiry panel. Six tabs of the same shape is what lets somebody
    who learned one of them use the other five."""

    def __init__(self, sentence: str, table, icon: str, empty_title: str,
                 empty_body: str, *, ranges: bool = True, search: bool = True,
                 on_change=None, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, theme.SPACE_3, 0, 0)
        col.setSpacing(theme.ROW_GAP)

        self.sentence = C.label(i18n.t(sentence), level="SUPPORT", wrap=True)
        self.sentence.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        col.addWidget(self.sentence)

        self.toolbar = C.Toolbar()
        self.filter = None
        self.search = None
        self.date_from = None
        self.date_to = None
        if ranges:
            self.toolbar.add(QLabel(i18n.t("Show:")))
            self.filter = QComboBox()
            for value, label in REGISTER_RANGES:
                self.filter.addItem(i18n.t(label), value)
            self.filter.setMinimumHeight(C.MIN_TARGET)
            self.toolbar.add(self.filter)
            # The owner's own from/to pair — "from the 1st to the 15th" —
            # shown only once "Pick dates…" is chosen, so the four everyday
            # choices stay one click and the toolbar stays short.
            self._from_label = QLabel(i18n.t("from"))
            self.date_from = QDateEdit(QDate.currentDate().addDays(-30))
            self._to_label = QLabel(i18n.t("to"))
            self.date_to = QDateEdit(QDate.currentDate())
            for box in (self.date_from, self.date_to):
                box.setCalendarPopup(True)
                box.setDisplayFormat("dd-MM-yyyy")
                box.setMinimumHeight(C.MIN_TARGET)
                if on_change is not None:
                    box.dateChanged.connect(lambda *_: on_change())
            for widget in (self._from_label, self.date_from,
                           self._to_label, self.date_to):
                self.toolbar.add(widget)
                widget.setVisible(False)
            self.filter.currentIndexChanged.connect(self._range_picked)
            if on_change is not None:
                self.filter.currentIndexChanged.connect(lambda *_: on_change())
        if search:
            self.search = C.SearchField(
                i18n.t("Find a customer or inquiry number"))
            self.search.setMaximumWidth(320)
            # Room for the glyph, about eighteen characters ("Find a
            # customer…") and the clear button, from the font in use rather
            # than a pixel guess: with no floor a crowded toolbar squeezed
            # it to "Fin…" (13 Oct, real window at 1078 px).
            fm = self.search.fontMetrics()
            self.search.setMinimumWidth(fm.averageCharWidth() * 18
                                        + 2 * C.MIN_TARGET)
            if on_change is not None:
                self.search.changed.connect(lambda *_: on_change())
            self.toolbar.add(self.search)
        self.toolbar.add_stretch()
        col.addWidget(self.toolbar)

        self.table = table
        self.stack = _TableOrEmpty(table, icon, i18n.t(empty_title),
                                   i18n.t(empty_body))
        self.empty = self.stack.empty
        col.addWidget(self.stack, stretch=1)

        self.panel = _SelectedPanel()
        col.addWidget(self.panel)

    def add_tool(self, widget) -> QWidget:
        """A control on the right end of the toolbar."""
        return self.toolbar.add(widget)

    def add_tool_row(self):
        """Start the toolbar's second line; add_tool() fills it from the
        right, the same as the first."""
        self.toolbar.new_row()
        self.toolbar.add_stretch()

    def _range_picked(self, *_):
        custom = self.range_key() == "custom"
        for widget in (self._from_label, self.date_from,
                       self._to_label, self.date_to):
            widget.setVisible(custom)

    def range_key(self) -> str:
        return (self.filter.currentData() if self.filter is not None
                else "all") or "all"

    def range_bounds(self) -> tuple[date | None, date | None]:
        if self.date_from is None or self.range_key() != "custom":
            return None, None
        return (self.date_from.date().toPython(),
                self.date_to.date().toPython())

    def in_range(self, when: date | None, today: date | None = None) -> bool:
        start, end = self.range_bounds()
        return _in_date_range(when, self.range_key(), today or date.today(),
                              start, end)

    def search_text(self) -> str:
        return (self.search.text() if self.search is not None else "").strip()


def _dmy(iso, short: bool = False) -> str:
    """A worklist date the way the register and the owner write one:
    DD-MM-YYYY, or DD-MM when several sit in one cell. Takes the plain
    ISO string (YYYY-MM-DD) _arrived_entry()/_worklist_entry() save to
    disk, or a real date/datetime directly — _StoredMessage.date is one,
    needed as such by register.from_message(), and _ReadMailDialog reads
    it straight off a _StoredMessage the same way it reads a string off
    the worklist. Passing it back through _parse_iso() a second time
    would have tried to .strip() a datetime and crashed."""
    if isinstance(iso, (date, datetime)):
        when = iso
    else:
        when = _parse_iso(iso)
    if when is None:
        return iso if isinstance(iso, str) else ""
    return when.strftime("%d-%m" if short else "%d-%m-%Y")


def _rupees(value) -> str:
    """"42480.00" → "₹42,480.00"; blank stays blank. The register keeps bare
    digits so Excel reads the column as numbers; the screen is for people."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        quoting = CB.get_quoting()
        return "₹" + quoting.indian_currency(quoting.to_decimal(text))
    except Exception:               # noqa: BLE001 — an odd cell is shown as typed
        return text


def _matches(text: str, *values) -> bool:
    """Case-insensitive "is this typed text anywhere in the row"."""
    if not text:
        return True
    haystack = " ".join(str(v or "") for v in values).lower()
    return text.lower() in haystack


class _RegisterOnlyItem:
    """A row on the orders tab that has no mail behind it — the customer
    said yes (Status Accepted) and the PO is coming by hand, by phone, or
    on paper. Same shape as _StoredItem for everything the tab reads, with
    an empty message so the "read the PO off the mail" path politely finds
    nothing to read."""

    def __init__(self, row: dict):
        self.message_id = ""
        self.row = row
        self.folder = row.get("Folder", "")
        self.files: list = []
        self.intent = ""
        self.note = i18n.t("Said yes — waiting for the PO")
        self.message = _StoredMessage({"from_addr": row.get("Email", ""),
                                       "subject": ""})

    @property
    def inquiry_no(self) -> str:
        return (self.row or {}).get("Inquiry no", "")


class _PhoneReplyDialog(PrismDialog):
    """"They replied by phone…" — the same four answers Prism would read
    out of a mail, picked by hand. In GIDC most answers come by phone, and
    without this the register could only move when the customer wrote."""

    CHOICES = ("accepted", "negotiating", "needs_info", "rejected")

    def __init__(self, row: dict, parent=None):
        super().__init__(
            i18n.t("They replied by phone"),
            i18n.t("What did they say? The register moves the same way it "
                   "would for a reply by mail."),
            icon="mic", parent=parent, closable=False)
        who = row.get("Customer", "") or row.get("Email", "")
        self.body.addWidget(C.label(
            f"{row.get('Inquiry no', '')} · {who}", level="CARD_TITLE",
            wrap=True))
        self._radios: list[tuple[str, QRadioButton]] = []
        for key in self.CHOICES:
            radio = QRadioButton(i18n.t(INTENT_LABELS[key]))
            radio.setMinimumHeight(C.MIN_TARGET)
            self._radios.append((key, radio))
            self.body.addWidget(radio)
        self._radios[0][1].setChecked(True)
        self.body.addWidget(QLabel(i18n.t("A note, if you want one:")))
        self._note = QLineEdit()
        self._note.setPlaceholderText(i18n.t(
            "e.g. wants delivery in two weeks, will confirm Monday"))
        self.body.addWidget(self._note)
        self.body.addStretch(1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Update the register"), "primary",
                        icon_name="check", on_click=self.accept))

    def intent(self) -> str:
        for key, radio in self._radios:
            if radio.isChecked():
                return key
        return self.CHOICES[0]

    def note(self) -> str:
        return self._note.text().strip()


# One tone per event this feature can ever write — see core/history.py's
# writers (mailflow.py's _log_history, and every _log_sent/_mark_lost/
# _mark_already_quoted/_phone_reply/_po_accepted call in this file).
# Anything not listed (a future event, or one written in another language)
# reads as "neutral" rather than guessing.
_HISTORY_TONES = {
    "Enquiry received": "info",
    "Order received (no prior quotation)": "info",
    "Purchase order received": "info",
    "Quotation sent": "accent",
    "Revised quotation sent": "accent",
    "Reminder sent": "quiet",
    "Win-back mail sent": "accent",
    "Reply received": "neutral",
    "Reply received — by phone": "neutral",
    "Quoted outside Prism — recorded by hand": "quiet",
    "Order accepted — converted": "ok",
    "Marked lost": "err",
    "Marked lost — by phone": "err",
    "Register corrected": "warn",
}


class _HistoryDialog(PrismDialog):
    """The whole story for one inquiry, read back in order — the enquiry,
    every quotation and reminder sent, every reply, and how it closed, each
    as its own card instead of a wall of plain text. The record itself is
    history.txt in the inquiry's own folder (see core/history.py) — this
    window reads it back with entries(), it does not hold a second copy."""

    def __init__(self, row: dict, folder: str, parent=None):
        who = row.get("Customer", "") or row.get("Email", "")
        super().__init__(
            i18n.t("The whole story"),
            i18n.t("Everything that happened on {no}, in the order it "
                   "happened.").replace("{no}", row.get("Inquiry no", "")),
            icon="clock", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle(i18n.t("The whole story"))
        self.resize(720, 680)
        self.setMinimumSize(480, 360)
        self.body.addWidget(C.label(
            f"{row.get('Inquiry no', '')} · {who}", level="CARD_TITLE",
            wrap=True))
        events = CB.get_history().entries(folder)
        if not events:
            self.body.addWidget(C.label(i18n.t(
                "Nothing recorded here yet. This inquiry's story starts "
                "filling in from the next thing that happens to it — a "
                "quotation sent, a reply, a purchase order."),
                level="SUPPORT", wrap=True))
        for entry in events:
            self.body.addWidget(self._card(entry))
        self.body.addStretch(1)
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))

    @staticmethod
    def _card(entry: dict) -> QWidget:
        card = C.Card()
        col = card.body(margins=(16, 14, 16, 14), spacing=theme.SPACE_1)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        head.addWidget(C.Pill(i18n.t(entry["event"]) or entry["event"],
                              _HISTORY_TONES.get(entry["event"], "neutral")))
        # Already "DD-MM-YYYY HH:MM" — history.append() writes it in the
        # same day-month-year convention the rest of the screen uses, so
        # unlike a worklist date (_dmy()'s job) this needs no reformatting.
        when = QLabel(entry["when"])
        when.setObjectName("meta")
        head.addWidget(when)
        head.addStretch(1)
        col.addLayout(head)
        meta = " · ".join(p for p in (entry.get("who"), entry.get("subject"))
                          if p)
        if meta:
            meta_label = QLabel(meta)
            meta_label.setObjectName("meta")
            meta_label.setWordWrap(True)
            col.addWidget(meta_label)
        if entry.get("body"):
            body_label = QLabel(entry["body"])
            body_label.setWordWrap(True)
            body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            col.addWidget(body_label)
        return card


class _ReadMailDialog(PrismDialog):
    """One mail, read in full — the owner's own words were "there is only
    an option for subject, no body" and "I should be able to see the mail
    ... with Subject with Body, with image". Images are not here yet (an
    attachment is only ever a filename on file, see _StoredMessage); this
    is the subject, the body, and what was attached, in one window, opened
    the way every table on this screen now opens one — a double-click."""

    def __init__(self, message, parent=None):
        subject = (getattr(message, "subject", "") or "").strip() \
            or i18n.t("(no subject)")
        super().__init__(subject, "", icon="mail", parent=parent,
                         closable=False, scrollable=True)
        self.setWindowTitle(subject)
        self.resize(640, 560)
        self.setMinimumSize(420, 320)

        who = getattr(message, "from_name", "") or ""
        addr = getattr(message, "from_addr", "") or ""
        meta = f"{who} <{addr}>" if who and addr and who != addr else (who or addr)
        when = _dmy(getattr(message, "date", "") or "")
        line = " · ".join(p for p in (meta, when) if p)
        if line:
            self.body.addWidget(C.label(line, level="SUPPORT", wrap=True))

        card = C.Card()
        col = card.body(margins=(16, 14, 16, 14), spacing=theme.SPACE_2)
        text = QLabel((getattr(message, "body", "") or "").strip()
                      or i18n.t("(no body)"))
        text.setWordWrap(True)
        text.setTextInteractionFlags(Qt.TextSelectableByMouse)
        col.addWidget(text)
        self.body.addWidget(card)

        names = list(getattr(message, "attachment_names", None) or [])
        if names:
            self.body.addWidget(C.label(
                i18n.t("Attached: {names}").replace("{names}", ", ".join(names)),
                level="META", wrap=True))
        self.body.addStretch(1)
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))


class _ArrivedMailDialog(PrismDialog):
    """One mail from the All-mail log, read in full — opened on demand
    (double-click a row, or the "Open mail" button) and closed on demand,
    rather than a panel that is permanently open on screen the moment a
    row is picked. A real complaint: the always-open reading pane never
    went away, and people wanted to get their screen back."""

    def __init__(self, entry: dict, parent=None):
        who = entry.get("from_name") or entry.get("from_addr", "")
        category = entry.get("category", "")
        super().__init__(
            entry.get("subject", "") or i18n.t("(no subject)"),
            i18n.t("From {who} · Sorted as {what} · {when}")
            .replace("{who}", who)
            .replace("{what}", i18n.t(CATEGORY_LABELS.get(category, category)))
            .replace("{when}", _dmy(entry.get("date", ""))),
            icon="mail", parent=parent, closable=True, scrollable=True)
        self.resize(640, 520)
        self.setMinimumSize(420, 320)
        addr = entry.get("from_addr", "")
        if addr and addr != who:
            self.body.addWidget(C.label(addr, level="META"))
        # "body" not being a key at all, versus being there and empty, are
        # two different facts and must not read the same. A mail logged
        # before this tab started saving text has no key — nothing can
        # bring that back short of reading the mailbox again — while a
        # mail that genuinely says nothing has the key, just empty. Shown
        # as one line, the first one reads as "still broken" forever;
        # that was a real, reported confusion.
        if "body" not in entry:
            body_text = i18n.t(
                "(this mail was read before Prism started saving mail "
                "text — mail that arrives from now on will show it here)")
        else:
            body_text = entry.get("body", "") or i18n.t(
                "(no text in this mail)")
        body_label = QLabel(body_text)
        body_label.setWordWrap(True)
        body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.addWidget(body_label)
        names = entry.get("attachment_names") or []
        if names:
            self.body.addWidget(C.label(
                i18n.t("Attached: {names}").replace("{names}", ", ".join(names)),
                level="META", wrap=True))
        self.body.addStretch(1)
        self.footer.set_primary(
            self.button(i18n.t("Close"), "primary", on_click=self.accept))
class _TintedCellDelegate(QStyledItemDelegate):
    """Paints a cell's own background and text colour directly, instead of
    leaving it to the default delegate.

    #inquiryWorkspace's stylesheet styles QTableWidget#inquiryTable::item
    (padding and a border, on every one of the six tabs built by
    _make_table) — and the moment a stylesheet touches ::item at all, Qt
    stops consulting Qt.BackgroundRole/Qt.ForegroundRole on its own. A cell
    tinted with setBackground()/setForeground() then quietly paints plain
    white, nothing raised, no test catching it unless the test looks at an
    actual pixel. tests/test_paint_colours.py already found and fixed this
    exact failure for the Leads pills and the progress tracks; this is the
    same fix for this file's tables, by the same method register_table.py's
    StatusPillDelegate already uses — paint it yourself, so the stylesheet
    is never asked to.

    A cell that was never tinted (no Qt.BackgroundRole set) falls straight
    through to the normal, QSS-styled painting — unless it is picked: a
    picked row is painted here end to end, so it is one charcoal band and
    not charcoal tinted cells next to the stylesheet's 8% grey ones.
    """

    # A picked row is a charcoal fill, the palette's own Highlight family
    # (theme.apply_palette, the combo lists), never a tint: round 2's 14%
    # wash over the strong blue New tint left a picked row and an unpicked
    # New row a shade apart (13 Oct, seen in the real window). The text
    # takes the row's tint, so the status still shows on a picked row, and
    # a bar in that tint runs down the left edge.
    PICKED = {"light": (theme.NEUTRAL[800], "#fafafa"),
              "dark": ("#f4f4f5", theme.NEUTRAL[900])}

    @classmethod
    def picked_colours(cls, tint=None) -> tuple:
        """(fill, ink, bar) for a picked cell over `tint` (a QColor, or None
        for a cell that was never tinted)."""
        if tint is not None and tint.alphaF() >= 0.5:
            dark_tint = tint.lightnessF() < 0.5
        else:
            dark_tint = theme.is_dark_palette()
        fill, plain_ink = cls.PICKED["dark" if dark_tint else "light"]
        if tint is None or tint.alphaF() < 0.5:
            return QColor(fill), QColor(plain_ink), QColor(plain_ink)
        return QColor(fill), QColor(tint), QColor(tint)

    def paint(self, painter, option, index):
        bg = index.data(Qt.BackgroundRole)
        selected = bool(option.state & QStyle.State_Selected)
        if bg is None and not selected:
            super().paint(painter, option, index)
            return
        painter.save()
        fg = index.data(Qt.ForegroundRole)
        ink = fg.color() if fg is not None else QColor(theme.TEXT)
        if selected:
            tint = None
            if bg is not None:
                tint = bg.color() if hasattr(bg, "color") else QColor(bg)
            fill, ink, bar = self.picked_colours(tint)
            painter.fillRect(option.rect, fill)
            if index.column() == 0:
                width = max(3, option.fontMetrics.height() // 5)
                painter.fillRect(option.rect.adjusted(0, 0, -(option.rect.width() - width), 0),
                                 bar)
        else:
            painter.fillRect(option.rect, bg)
        text = str(index.data(Qt.DisplayRole) or "")
        if text:
            painter.setPen(ink)
            rect = option.rect.adjusted(10, 0, -10, 0)
            elided = option.fontMetrics.elidedText(text, Qt.ElideRight,
                                                   rect.width())
            painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, elided)
        painter.restore()


def paint(item: QTableWidgetItem, colours: dict, key: str) -> QTableWidgetItem:
    """Tint one cell from one of the tables above. Unknown keys stay plain.

    Goes through theme.qcolor(), not a bare QColor(pair[0]) — the OK/WARN/
    ERR/INFO tints are `rgba(...)` CSS strings, which QColor's own string
    constructor cannot parse: it returns silently-invalid and paints solid
    black with nothing raised (see tests/test_paint_colours.py, which caught
    exactly this for the Leads pills and progress tracks). Only _NEUTRAL and
    _QUIET happen to be plain hex, which is why that failure mode never
    showed up in a table painted only with those two.

    Returns the item so it reads as one line at the call site.
    """
    pair = colours.get((key or "").strip())
    if pair:
        item.setBackground(theme.qcolor(pair[0]))
        item.setForeground(theme.qcolor(pair[1]))
    return item


# ── the worklist: what keeps arrived mail, replies and purchase orders on
#    screen after the check that found them has long since moved its
#    bookmark past them ────────────────────────────────────────────────────
def _iso_date(when) -> str:
    """A plain YYYY-MM-DD out of whatever a message's date carries, so the
    worklist file — and its "Show:" filter — can compare dates as strings
    without needing the original object back."""
    if when is None:
        return date.today().isoformat()
    try:
        return when.date().isoformat() if hasattr(when, "date") else when.isoformat()
    except (TypeError, ValueError):
        return date.today().isoformat()


def _arrived_entry(message, verdict) -> dict:
    """What one arrived-mail row needs to redraw itself from disk — plus
    what "open the mail" needs to show it in full, the same two fields
    _worklist_entry() already keeps for a reply or an order. Every piece of
    mail Prism sorts gets this now, not only the ones that became a reply
    or a PO — previously this read "only a subject, no body" for anything
    landing in All mail, which was the owner's own words for the gap.
    `body` is capped the same way _worklist_entry() caps a reply's — long
    enough to read a real email, short enough that 5000 of them stay a
    reasonable file."""
    return {
        "message_id": message.message_id or "",
        "from_name": message.from_name,
        "from_addr": message.from_addr,
        "subject": message.subject,
        "body": (getattr(message, "body", "") or "")[:4000],
        "attachment_names": list(getattr(message, "attachment_names", None) or []),
        "date": _iso_date(message.date),
        # The reader's own clock, not the sender's — see register._clock's
        # own docstring: a 9am mail from a sender in a different timezone
        # must not read as "9am" here either, or the time means nothing.
        "time": CB.get_register().clock(message.date),
        "category": verdict.category,
        "reason": verdict.reason,
        "source": verdict.source,
    }


def _worklist_entry(item) -> dict:
    """What one reply or purchase-order Item needs to redraw itself, and to
    be acted on, after the live Message that a check built it from is gone —
    everything _show_reply() and _review_po() would otherwise have read off
    that Message, plus the paths to the files already saved on disk."""
    message = item.message
    return {
        "message_id": getattr(message, "message_id", "") or "",
        "inquiry_no": item.inquiry_no,
        "from_name": getattr(message, "from_name", ""),
        "from_addr": getattr(message, "from_addr", ""),
        "subject": getattr(message, "subject", ""),
        "body": (getattr(message, "body", "") or "")[:4000],
        "attachment_names": list(getattr(message, "attachment_names", None) or []),
        "date": _iso_date(getattr(message, "date", None)),
        "intent": item.intent,
        "note": item.note,
        "folder": item.folder,
        "files": list(item.files or []),
    }


class _StoredMessage:
    """Enough of core.inbox.Message to satisfy _show_reply(), _review_po(),
    _po_file(), register.from_message() and _ReadMailDialog for a reply,
    order or arrived-mail row read back from the worklist file, where the
    real Message from the check that found it no longer exists.

    `date` is rebuilt from the entry's own saved date + time (already the
    reader's local clock, not the sender's — see register._clock()) —
    naive on purpose, so register._clock() formats it back out unchanged
    instead of trying to convert an already-converted time a second time.
    A real datetime, not the plain ISO string _arrived_entry() saves to
    disk — register.from_message() calls .strftime() on it directly, the
    same as it would on a live Message's own `.date`. _dmy(), which
    _ReadMailDialog uses to show it, accepts either form."""

    def __init__(self, entry: dict):
        self.from_name = entry.get("from_name", "")
        self.from_addr = entry.get("from_addr", "")
        self.subject = entry.get("subject", "")
        self.body = entry.get("body", "")
        self.attachment_names = list(entry.get("attachment_names") or [])
        self.message_id = entry.get("message_id", "")
        when = _parse_iso(entry.get("date", ""))
        hh, _, mm = (entry.get("time") or "").partition(":")
        self.date = (datetime(when.year, when.month, when.day,
                              int(hh), int(mm))
                    if when and hh.isdigit() and mm.isdigit() else
                    datetime(when.year, when.month, when.day) if when else None)

    def snippet(self, limit: int = 1500) -> str:
        text = (self.body or "").strip()
        if len(text) > limit:
            text = text[:limit].rstrip() + " …"
        return f"Subject: {self.subject}\n\n{text}".strip()


class _StoredItem:
    """A reply or order Item, rebuilt from one worklist row rather than from
    a live check. Same shape as mailflow.Item for every attribute the
    working dialog reads — .row, .message, .folder, .files, .intent, .note,
    .inquiry_no, plus .message_id for resolving it — so nothing downstream
    has to know whether an item came from this check or from disk."""

    def __init__(self, entry: dict, row: dict | None):
        self.message_id = entry.get("message_id", "")
        self.row = row
        self._entry_inquiry_no = entry.get("inquiry_no", "")
        self.folder = entry.get("folder", "")
        self.files = list(entry.get("files") or [])
        self.intent = entry.get("intent", "")
        self.note = entry.get("note", "")
        self.message = _StoredMessage(entry)

    @property
    def inquiry_no(self) -> str:
        # The register's own copy when the row still exists there — the
        # freshest source, and the one every other status field comes from
        # — falling back to what was true at the moment this was persisted.
        return (self.row or {}).get("Inquiry no", "") or self._entry_inquiry_no


def open_in_file_manager(path: str) -> None:
    """Reveal a folder or file in Finder/Explorer.

    Worth having: the register and the inquiry folders are the product as far
    as the customer is concerned, and "where did it put it?" is the first
    question. A button beats a path they have to copy.
    """
    if not path or not os.path.exists(path):
        return
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif sys.platform.startswith("win"):
            os.startfile(path)             # noqa: S606  (Windows-only API)
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


class InquiryDialog(PipelineActions, PipelineScreen, QWidget):
    """The working screen — embedded in the main window's stack, not a
    popup. It used to be a modal PrismDialog opened with .exec(); the
    customer did not want a working window that blocks the rest of the app,
    so this is now a plain screen you navigate to and away from, the same
    way Home/Workbench/Settings/the launcher panel already work. `enter()`
    is what a fresh `.exec()` used to do (load the latest state, land on a
    tab, maybe check mail right away) — call it every time the screen is
    navigated to, not just once at construction. `on_leave()` is the light
    teardown for navigating away (stop the auto-check timer only); the full
    worker teardown in `closeEvent` below still exists as a last-resort
    safety net if this widget is ever actually closed/destroyed outright."""

    # Emitted to ask the main window to switch screens — "inquiry" for the
    # launcher panel this screen was opened from. Same convention as the
    # BOQ/Gerber/Email/History/Catalog/Settings panels' own `navigate`.
    navigate = Signal(str)
    # A customer's attachment, picked from an inquiry, asked to become a
    # real Prism attachment — the same thing attaching a file from the
    # sidebar's favourites already does (see main_window._attach_path,
    # wired to sidebar.favorite_chosen the same way this is wired to this
    # signal). Without this, using a customer's own drawing with any of
    # Prism's AI tools meant saving it by hand, then attaching it by hand
    # a second time — this does that in one click, so what's left is
    # typing the prompt.
    attach_to_prism = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        # This screen is data-dense.  It needs a deliberately more opaque
        # treatment than the dashboard cards so the wallpaper never competes
        # with a customer, date or quotation status.
        self.setObjectName("inquiryWorkspace")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # No subtitle: the sentence at the top of each tab says what THAT
        # list is for, which is the only sentence the owner needs, and the
        # header band's 20px are worth more as table rows.
        self.header = C.PageHeader(i18n.t("Email inquiry automation"), "")
        root.addWidget(self.header)

        self.body = QVBoxLayout()
        root.addLayout(self.body, stretch=1)

        self._closed = False
        self.cfg = dict(cfg)
        # The row the owner last picked, in ANY table — the one every
        # action button acts on. Meant to always be one of the dicts in
        # _register_rows, never a copy, so a change lands on the row
        # register.save() writes — but _refresh_register() reloads that list
        # with fresh dicts and only re-syncs the to_quote/waiting/register
        # tables (see _reselect()), not the replies/orders tabs. _focus_key
        # is the inquiry number behind whatever _focus_row was, so
        # _current_row() can re-anchor to the live dict instead of reporting
        # "nothing is selected" the moment the register underneath it turns
        # over.
        self._focus_row = None
        self._focus_key = ""
        self._to_quote_rows: list[dict] = []
        self._to_quote_count = 0          # the blue rows only, not the grey
        self._waiting_rows: list[dict] = []
        self._pages: dict[str, _TabPage] = {}
        self._worker = None
        self._send_worker = None
        self._draft_worker = None
        self._po_worker = None
        self._draft_row = None
        self._result = None
        self._sorted_mail = []
        self._register_rows = []
        # What the table actually shows once the date filter is applied — the
        # same dict objects as _register_rows, never copies, so a mutation
        # through _selected_row() (which reads this list) still lands on the
        # row register.save() will actually write.
        self._visible_rows = []
        self._replies = []
        self._orders = []
        self._po_row = None
        self._po_item = None
        self._followup_rows = []
        # The walk across the configured mailboxes: the accounts still to
        # check, how far along it is, and every account's result so far.
        self._queue = []
        self._queue_pos = 0
        self._partial = []
        # True only for the duration of a timer-driven check. Reset the moment
        # that check ends, so a later failure the owner DID ask for still gets
        # a dialog rather than disappearing into the status line.
        self._quiet = False

        self._build_header_actions()

        self.body.setContentsMargins(theme.PAGE_PAD, theme.SPACE_3,
                                     theme.PAGE_PAD, theme.SPACE_3)
        self.body.setSpacing(theme.SPACE_3)

        # The message bar: what Prism is doing right now, in one line, with
        # the busy bar beside it. Used to be a label squeezed into the header
        # action row, where "Writing it in your browser — this takes a minute
        # or two…" pushed "Check my mail now" off the right edge.
        bar = QWidget()
        bar.setObjectName("inquiryStatusBar")
        bar_row = QHBoxLayout(bar)
        bar_row.setContentsMargins(0, 0, 0, 0)
        bar_row.setSpacing(theme.SPACE_2)

        self.progress = Loader("ring", compact=True, parent=bar)
        self.progress.setObjectName("inquiryProgress")
        self.progress.setRange(0, 0)   # indeterminate until we know count
        self.progress.setAccessibleName(i18n.t("Mailbox check progress"))
        self.progress.setAccessibleDescription(i18n.t(
            "Shows that Prism is checking the configured inboxes."))
        self.progress.setVisible(False)
        bar_row.addWidget(self.progress)

        self.status = _StatusLine("")
        self.status.setObjectName("meta")
        self.status.setWordWrap(True)
        bar_row.addWidget(self.status)
        bar_row.addStretch(1)

        self.body.addWidget(bar)

        self.tabs = _Tabs()
        self.tabs.setObjectName("inquiryTabs")
        self.tabs.tabBar().setObjectName("inquiryTabBar")
        builders = {
            "to_quote": self._to_quote_tab, "waiting": self._followup_tab,
            "replies": self._replies_tab, "orders": self._orders_tab,
            "register": self._register_tab, "arrived": self._arrived_tab,
        }
        for key, label in TABS:
            page = builders[key]()
            self._pages[key] = page
            self.tabs.addTab(page, i18n.t(label))
        # Three things keep a title from ever being cut to "1 · What arriv…"
        # again: no equal-width splitting (each tab is as wide as its own
        # text), no eliding, and — the one that actually bit — the bar
        # MEASURING with the same font the stylesheet PAINTS with. QSS sets
        # QTabBar::tab to Barlow 13/600; the widget's own font was 14/400,
        # and a rect sized for regular text is too narrow for semi-bold.
        tab_bar = self.tabs.tabBar()
        tab_bar.setExpanding(False)
        tab_bar.setElideMode(Qt.ElideNone)
        tab_bar.setFont(theme.font("SUPPORT", 600))
        self.tabs.setUsesScrollButtons(True)
        self.tabs.currentChanged.connect(
            lambda index: self._sync_panel(TABS[index][0])
            if 0 <= index < len(TABS) else None)
        # The pipeline board, and the view switch around these tabs
        # (pipeline_actions.PipelineScreen). The tabs are not reparented
        # into anything new: they are page 1 of `views`.
        self._build_views()

        self.classic_footer = QWidget()
        self.classic_footer.setObjectName("inquiryClassicFooter")
        cfl = QVBoxLayout(self.classic_footer)
        cfl.setContentsMargins(0, 0, 0, 0)
        cfl.setSpacing(0)
        cfl.addWidget(C.hairline())
        footer_row = QHBoxLayout()
        # No room reserved for Ask-Lumi any more: it is a small button docked
        # to the window's right edge, clear of this row (14 Oct 2026).
        footer_row.setContentsMargins(theme.PAGE_PAD, theme.SPACE_3, theme.PAGE_PAD,
                                      theme.SPACE_3)
        footer_row.setSpacing(theme.SPACE_2)
        footer_row.addWidget(self.button(
            i18n.t("Open the folder"), "secondary", icon_name="folder",
            small=True,
            on_click=lambda: open_in_file_manager(self._root())))
        footer_row.addWidget(self.button(
            i18n.t("Open the register file"), "secondary", icon_name="file",
            small=True, on_click=self._open_register))
        footer_row.addStretch(1)
        # This screen is reached by drilling in from the launcher panel, not
        # from the sidebar directly — "Back" returns there. Was a plain
        # `reject()` when this was a modal; now it asks the main window to
        # switch screens, the same convention every other embedded panel's
        # `navigate` signal already uses.
        footer_row.addWidget(self.button(
            i18n.t("Back to Email inquiry automation"), "secondary",
            on_click=lambda: self.navigate.emit("inquiry")))
        cfl.addLayout(footer_row)
        root.addWidget(self.classic_footer)

        # Checking on a timer is what makes this "runs by itself" rather than
        # "a button somebody remembers". Started here rather than in the
        # constructor of the timer so a saved interval of 0 leaves it stopped.
        # Rejected sign-ins are counted PER ADDRESS: one mailbox's dead
        # password must not stop the others being read — see _note_failure.
        self._auth_failures: dict[str, int] = {}
        self._auto = QTimer(self)
        self._auto.timeout.connect(self._auto_check)
        self._apply_auto_interval()

        self.enter()

    def enter(self, tab: int = 0, auto_check: bool = False,
              view: str | None = None):
        """Show the latest state. Called every time the main window
        navigates to this screen — the replacement for what constructing a
        fresh dialog and calling .exec() used to do. `tab` lands on the tab
        the launcher's action line was about ("Quote them" → to_quote,
        "Read the answer" → replies, ...); `auto_check` is set only for the
        front door's "Check my mail now" — see InquiryPanel.check_requested.
        """
        self._refresh_register()
        # Draw the three worklist tabs from what is already on disk, before
        # any check has run this session — returning to this screen tomorrow
        # must show the same pending replies and orders it showed today,
        # not a blank screen waiting for a fresh check to repopulate them.
        self._render_arrived()
        self._render_replies()
        self._render_orders()
        self._tabs_quiet = True
        self.tabs.setCurrentIndex(max(0, min(int(tab or 0), len(TABS) - 1)))
        self._tabs_quiet = False
        # view="auto" (the main window's way in): the board, unless the
        # launcher asked for a tab only the client file or All mail holds.
        # No view (old callers): the classic tabs, exactly as before.
        if view == "auto":
            view = {"register": "client", "arrived": "mail"}.get(
                TABS[self.tabs.currentIndex()][0], "pipeline")
        self.show_view(view or "classic")
        self._apply_auto_interval()
        # Deferred so the screen paints before a "needs setup?" question can
        # pop over it. `_closed` guards it in the (now rare, since this
        # widget is never destroyed by ordinary navigation) case the app is
        # shutting down before Qt delivers this zero-delay callback.
        QTimer.singleShot(0, lambda: self._first_look(auto_check))

    def on_leave(self):
        """Called by the main window when the user navigates to a different
        screen. Only stops the timer — an in-flight check is left to finish
        in the background rather than force-terminated, so leaving this
        screen is instant rather than blocking on network I/O. The register
        it writes is re-read fresh by the launcher panel and by `enter()`
        regardless of which screen was active while it finished. Full worker
        teardown is `closeEvent`, below, for the rare case this widget is
        actually destroyed rather than merely navigated away from."""
        self._auto.stop()
        self.drawer.close_drawer()
        self._restore_sidebar()

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        if hasattr(self, "drawer"):
            self.drawer.place()
            self._fit_sidebar()

    def showEvent(self, event):                         # noqa: N802
        super().showEvent(event)
        if hasattr(self, "drawer"):
            QTimer.singleShot(0, self._fit_sidebar)

    def button(self, text: str, variant: str = "secondary",
              icon_name: str = "", on_click=None, tooltip: str = "",
              small: bool = False):
        """One button, on the four-variant scale — the same helper
        `PrismDialog.button()` gave every dialog, kept here verbatim now
        that this screen is no longer a PrismDialog, so none of the many
        `self.button(...)` call sites elsewhere in this class had to change."""
        btn = C.button(text, variant, icon_name, small=small, on_click=on_click)
        if tooltip:
            btn.setToolTip(tooltip)
            if not btn.accessibleName():
                btn.setAccessibleName(f"{text}. {tooltip}")
        if variant == "primary":
            btn.setDefault(True)
            btn.setAutoDefault(True)
        return btn

    def closeEvent(self, event):
        """Wind up every worker if this widget is ever actually closed or
        destroyed outright — ordinary navigation away from this screen goes
        through `on_leave()` above instead, which does not wait on anything,
        so this is a safety net rather than the normal path.

        A QThread destroyed while still running aborts the whole process — Qt
        calls qFatal() from ~QThread. Reel and BOQ have guarded this since they
        were written; this screen did not, and it has more workers than either:
        a mailbox check, a send, and a browser draft that runs for minutes.

        The timer is stopped first. Otherwise it can fire while the waits are
        running and start a fresh check on a widget that is closing.

        `QTimer.singleShot(0, ...)` in `enter()` posts a zero-delay callback
        that Qt does not deliver until the event loop next turns — which a
        caller that never spins the loop after closing (every test in
        tests/test_inquiry_ui.py, deliberately: see its own comments) never
        gives it the chance to do before moving on. Left unguarded, that
        callback survives the close and fires whenever ANYONE next drives the
        event loop — in a completely unrelated test, possibly dozens of
        modules later — and if this screen's config was not "ready" (a case a
        test exists specifically to cover), `_first_look` opens a genuinely
        modal, blocking `QMessageBox.question` with nothing in a headless
        test able to answer it: a hang, not a failure, in whatever test
        happened to call `processEvents()` next.

        `QCoreApplication.removePostedEvents(self)` looks like the fix and
        is not one: Qt's `QTimer.singleShot` free function runs the timer on
        an internal helper object it owns, not on `self`, so nothing posted
        against this widget is ever waiting to be removed. The `_closed`
        flag `_first_look` checks below is the actual guard.
        """
        self._closed = True
        self._auto.stop()
        # Stop the mailbox walk as well as the workers: a queue with accounts
        # left in it would otherwise start a fresh worker from the done-signal
        # of the one being waited on.
        self._queue = []
        for worker in (self._worker, self._send_worker, self._draft_worker,
                       self._po_worker):
            if worker is None:
                continue
            try:
                if not worker.isRunning():
                    continue
            except RuntimeError:
                continue        # already deleted; nothing to wait for
            stop = getattr(worker, "stop", None)
            if callable(stop):
                stop()
            # A browser draft sits in a Selenium poll that is seconds wide, so
            # a short wait would expire and terminate a thread that was about
            # to finish on its own.
            if not worker.wait(10_000):
                worker.terminate()
                worker.wait(1000)
        super().closeEvent(event)

    # ── chrome ────────────────────────────────────────────────────────────
    def _build_header_actions(self):
        """The controls that act on the whole screen, in the fixed band.

        `setProperty("class", "primary")` was the old way of asking for the
        solid accent button, and style.qss has never carried a single
        `[class=...]` selector — so the one button this screen exists for, and
        four others like it further down this file, all rendered as plain
        hairline boxes. They are real object names now, through
        `controls.button`, so a variant is picked by name rather than guessed.
        """
        # Three controls, no more: the status text that used to sit here
        # moved to the message bar under the header, because a long message
        # pushed the one primary button off the right edge.
        self.auto_box = QCheckBox(i18n.t("Check by itself"))
        self.auto_box.setMinimumHeight(C.MIN_TARGET)
        self.auto_box.setCursor(Qt.PointingHandCursor)
        self.auto_box.setToolTip(i18n.t(
            "Read the inbox on its own, every few minutes (set under Setup "
            "→ Your terms). Reading sends nothing."))
        self.auto_box.toggled.connect(self._auto_toggled)
        self.header.add_action(self.auto_box)

        setup = self.button(i18n.t("Setup"), "secondary", icon_name="sliders",
                            on_click=self.open_setup)
        self.header.add_action(setup)
        self.check_btn = self.button(i18n.t("Check my mail now"), "primary",
                                     icon_name="inbox",
                                     on_click=self.check_now)
        self.header.add_action(self.check_btn)
        # Hidden until a check is actually running — InboxCheckWorker has no
        # cooperative stop(), so a dead mail server used to leave the button
        # disabled and progress spinning with no way out short of closing the
        # whole dialog (which falls back to the same hard terminate() this
        # calls directly — see closeEvent).
        self.reset_btn = self.button(
            i18n.t("Reset"), "secondary", icon_name="x", small=True,
            on_click=self._reset_check,
            tooltip=i18n.t("Cancel a check that has stopped responding, so "
                           "you can try again."))
        self.reset_btn.setVisible(False)
        self.header.add_action(self.reset_btn)

    def _settings(self) -> dict:
        return settings_of(self.cfg)

    def _root(self) -> str:
        return self._settings().get("folder", "")

    def _paths(self):
        return CB.get_mailflow().Paths(self._root())

    # ── checking on its own ───────────────────────────────────────────────
    def _apply_auto_interval(self):
        """Start or stop the timer to match what is saved.

        Called on open and after every Setup, so changing the interval takes
        effect without reopening the screen.
        """
        minutes = int(self._settings().get("auto_minutes", 0) or 0)
        # Blocked so setting the checkbox from saved state does not re-enter
        # _auto_toggled and write the config back on the way past.
        self.auto_box.blockSignals(True)
        self.auto_box.setChecked(minutes > 0)
        self.auto_box.blockSignals(False)
        if minutes > 0 and is_ready(self.cfg):
            self._auto.start(minutes * 60_000)
        else:
            self._auto.stop()

    def _auto_toggled(self, on: bool):
        settings = self._settings()
        if on:
            # Turning it on without an interval saved has to mean something.
            # Ten minutes is the number in the engine's own docstring and is
            # far below any provider's idea of hammering an IMAP server.
            minutes = int(settings.get("auto_minutes", 0) or 0) or 10
        else:
            minutes = 0
        settings["auto_minutes"] = minutes
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        self._apply_auto_interval()
        self.status.setText(
            i18n.t("Checking every {n} minutes.").replace("{n}", str(minutes))
            if minutes else i18n.t("Automatic checking is off."))

    def _auto_check(self):
        """A timer tick. Silent about everything a person did not ask for.

        Skipped outright while a check is already running or while a
        quotation is open on top: fetching underneath an open Send dialog
        would refresh the register out from under the row being priced.
        """
        if self._worker is not None and self._worker.isRunning():
            return
        if not is_ready(self.cfg):
            return
        # Fetching underneath an open money dialog would refresh the register
        # out from under the row being priced — or accepted.
        if self.findChild(QuotationDialog) is not None:
            return
        if self.findChild(_POReviewDialog) is not None:
            return
        self.check_now(quiet=True)

    # ── tab 1: what arrived ───────────────────────────────────────────────
    # ── building the six tabs ─────────────────────────────────────────────
    @staticmethod
    def _make_table(headers: list[str], stretch, fit=(),
                    fixed: dict | None = None, multi: bool = False,
                    resizable: bool = False,
                    widths: dict | None = None) -> QTableWidget:
        """A plain grid, the same on every tab: the column(s) in `stretch`
        (one index, or several) share the slack, the ones named in `fit` size
        to their text — so a date is never "02-08-20…" and an inquiry number
        is never "INQ/…" — and `fixed` ({column: pixels}) holds a column whose
        text can be long and matters less ("5000 nos (monthly, ongoing)" used
        to size itself to its longest value and squeeze Customer to "Shreeji
        A…"; seen in the real window, 1 Oct 2026). Long text elides.

        `multi` turns on ctrl/shift-click multi-selection, for a tab that
        offers a delete-selected action rather than only the single-row kind.

        `resizable=True` is a different, incompatible layout from `stretch`/
        `fit`/`fixed`: those modes all lock a column's width against the
        user's own mouse — a real complaint, on a tab (All mail) wide enough
        and varied enough in content that a fixed "From" column was too wide
        for some rows and cut others off. `widths` only seeds a sane starting
        width per column index; the person still drags any border to
        whatever they actually want, and Qt remembers it for the rest of
        the session.
        """
        table = QTableWidget(0, len(headers))
        table.setObjectName("inquiryTable")
        table.setHorizontalHeaderLabels([i18n.t(h) for h in headers])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection if multi
                               else QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(True)
        table.setWordWrap(False)
        # Without this, every tint painted below (STATUS_COLOURS,
        # CATEGORY_COLOURS, INTENT_COLOURS — see _TintedCellDelegate for
        # why) is silently invisible under the app's real stylesheet.
        table.setItemDelegate(_TintedCellDelegate(table))
        head = table.horizontalHeader()
        if resizable:
            head.setSectionResizeMode(QHeaderView.Interactive)
            head.setStretchLastSection(True)
            for column, width in (widths or {}).items():
                table.setColumnWidth(column, width)
        else:
            for column in (stretch if isinstance(stretch, (tuple, list)) else (stretch,)):
                head.setSectionResizeMode(column, QHeaderView.Stretch)
            for column in fit:
                head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
            for column, width in (fixed or {}).items():
                head.setSectionResizeMode(column, QHeaderView.Interactive)
                head.resizeSection(column, width)
        return table

    def _add_row_actions(self, panel: _SelectedPanel) -> _SelectedPanel:
        """Every button a register row can have, built once for this panel.
        Which of them show is actions_for()'s decision, per row."""
        handlers = self._row_handlers()
        for key, text, variant in ROW_ACTIONS:
            panel.add_action(key, text, variant, handlers[key])
        return panel

    # ── tab 6: all mail ───────────────────────────────────────────────────
    def _arrived_tab(self) -> QWidget:
        # Resizable, not fixed — a real complaint: "From" was too wide on
        # some rows and cut the rest off on others, and there was no way
        # to trade width between columns. "Body" is new here too, a short
        # preview so "what is this about" rarely even needs the popup.
        self.arrived = self._make_table(
            ["From", "Subject", "Body", "Sorted as", "Why", "Date", "Time",
             "Flag"],
            stretch=2, resizable=True,
            widths={0: 150, 1: 190, 2: 260, 3: 100, 4: 190, 5: 90, 6: 60,
                    7: 90},
            multi=True)
        page = _TabPage(
            ARRIVED_SENTENCE,
            self.arrived, "inbox", "Nothing has come in yet",
            "Press Check my mail now. Everything that arrives is listed here "
            "and stays listed.", on_change=self._render_arrived)
        self.arrived_filter = page.filter
        # What the mail actually said, opened on its own — not a panel
        # permanently glued open the moment a row is picked. A real
        # complaint: the earlier version read the body straight into this
        # panel, and the panel then never went away. Double-click a row,
        # or press this button; the popup has its own Close.
        open_row = QHBoxLayout()
        open_row.addWidget(C.button(
            i18n.t("Open mail"), "secondary", icon_name="mail",
            on_click=self._open_arrived))
        open_row.addStretch(1)
        page.panel.extra.addLayout(open_row)
        self.arrived.cellDoubleClicked.connect(lambda *_: self._open_arrived())
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        row.addWidget(QLabel(i18n.t("This one is really a:")))
        self.recategorise = QComboBox()
        self.recategorise.setMinimumHeight(C.MIN_TARGET)
        for key, label in CATEGORY_LABELS.items():
            if key != "unsorted":
                self.recategorise.addItem(i18n.t(label), key)
        row.addWidget(self.recategorise)
        row.addWidget(C.button(i18n.t("Correct it — remember this sender"),
                               "primary", icon_name="check",
                               on_click=self._correct))
        row.addStretch(1)
        page.panel.extra.addLayout(row)
        # A flag, nothing more — no due date, no separate list, just a
        # quick way to not lose track of a mail without it needing to
        # become a full inquiry. The button's own text says which way it
        # goes, kept in sync with the selected row by _sync_panel().
        reminder_row = QHBoxLayout()
        self.reminder_btn = C.button(
            i18n.t("Mark as reminder"), "secondary", icon_name="pin",
            on_click=self._toggle_reminder)
        reminder_row.addWidget(self.reminder_btn)
        reminder_row.addStretch(1)
        page.panel.extra.addLayout(reminder_row)
        # One or many — ctrl/shift-click picks several, same button deletes
        # all of them. A real ask: this log can run to thousands of rows
        # (newsletters, bounces, everything that ever arrived) and clearing
        # them one at a time was never going to happen.
        delete_row = QHBoxLayout()
        # "Reset everything" sits apart from "Delete selected" on purpose —
        # one clears what's picked in this tab, the other wipes the whole
        # register and every mailbox's read bookmark at once. Different
        # enough in size that mixing them into one row invites a misclick.
        delete_row.addWidget(C.button(
            i18n.t("Reset everything"), "destructive", icon_name="trash",
            on_click=self._reset_everything))
        delete_row.addStretch(1)
        delete_row.addWidget(C.button(
            i18n.t("Delete selected"), "destructive", icon_name="trash",
            on_click=self._delete_arrived))
        page.panel.extra.addLayout(delete_row)
        self.arrived.currentCellChanged.connect(
            lambda *_: self._sync_panel("arrived"))
        # Double-click already opens _ArrivedMailDialog via the "Open mail"
        # wiring above — _open_mail("arrived") is still a real, tested path
        # (used when some OTHER tab's row traces back to an arrived-log
        # entry), just not also wired to this table's own double-click,
        # which would otherwise pop both dialogs at once.
        return page

    # ── tab 1: to quote ───────────────────────────────────────────────────
    def _to_quote_tab(self) -> QWidget:
        self.to_quote_table = self._make_table(
            ["Inquiry no", "Date", "Customer", "What they want", "Qty",
             "Status"], stretch=(2, 3), fit=(0, 1, 5), fixed={4: 120},
            multi=True)
        page = _TabPage(
            "These inquiries have no quotation yet. Pick one, then press "
            "Prepare a quotation. Ones already quoted stay below them in "
            "grey until the customer answers.",
            self.to_quote_table, "list", "Nothing to quote",
            "Every inquiry has a quotation. New ones appear here as soon as "
            "Prism reads them.", on_change=self._render_to_quote)
        self._add_row_actions(page.panel)
        self.to_quote_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("to_quote"))
        self.to_quote_table.itemSelectionChanged.connect(
            lambda: self._label_delete("to_quote"))
        self.to_quote_table.cellDoubleClicked.connect(
            lambda *_: self._open_mail("to_quote"))
        return page

    # ── tab 5: every inquiry ──────────────────────────────────────────────
    def _register_tab(self) -> QWidget:
        self.register_table = self._make_table(
            ["Inquiry no", "Date", "Customer", "What they want", "Status",
             "Value"], stretch=3, fit=(0, 1, 4, 5), multi=True)
        page = _TabPage(
            "Every inquiry Prism has written in the register, and where each "
            "one stands.",
            self.register_table, "list", "The register is empty",
            "Every inquiry Prism recognises is written here as one row — the "
            "number, the customer, and where it has got to.",
            on_change=self._render_register)
        self.register_filter = page.filter
        self.register_chips = C.FilterChips(
            [("all", i18n.t("All")), ("open", i18n.t("Open")),
             ("won", i18n.t("Won")), ("lost", i18n.t("Lost"))], current="all")
        self.register_chips.changed.connect(lambda *_: self._render_register())
        # The chips are a FlowLayout, which in a one-line toolbar was given
        # its narrowest width and stacked All/Open/Won/Lost one above the
        # other. Four chips always fit one line: ask for that line.
        chips = list(self.register_chips._buttons.values())
        self.register_chips.setMinimumWidth(
            sum(b.sizeHint().width() for b in chips)
            + (theme.SPACE_2 - 2) * (len(chips) - 1))
        page.add_tool(self.register_chips)
        # The two file buttons on a line of their own, so the search box
        # keeps its width.
        page.add_tool_row()
        # The one rare thing on this screen, kept out of the daily tabs.
        import_btn = C.button(i18n.t("Bring in an old list (CSV)…"),
                              "secondary", small=True,
                              on_click=self._import_csv_into_register)
        import_btn.setToolTip(i18n.t(
            "For a list of inquiries you already kept before using Prism — "
            "added alongside what is already here. Nothing already in the "
            "register is touched, changed or duplicated."))
        page.add_tool(import_btn)
        excel_btn = C.button(i18n.t("Save as Excel…"), "secondary", small=True,
                             on_click=self._export_register_xlsx)
        excel_btn.setToolTip(i18n.t(
            "A copy of the whole register as an Excel workbook: dates that "
            "read the same on every computer, phone numbers with their "
            "leading 0, and the status colours. The register itself is not "
            "changed."))
        page.add_tool(excel_btn)
        self._add_row_actions(page.panel)
        self.register_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("register"))
        self.register_table.itemSelectionChanged.connect(
            lambda: self._label_delete("register"))
        self.register_table.cellDoubleClicked.connect(
            lambda *_: self._open_mail("register"))
        return page

    # ── tab 3: they answered ──────────────────────────────────────────────
    def _replies_tab(self) -> QWidget:
        """Replies on quotations already out, and what Prism made of them.

        Nothing here applies itself. Prism reading "we will go ahead" and
        silently marking the row Accepted would be a machine changing a sales
        record on the strength of a sentence it might have misread — so it
        proposes, shows the words it read it from, and the owner presses the
        button.
        """
        self.replies_table = self._make_table(
            ["Inquiry no", "Customer", "Subject", "Prism thinks",
             "Register will say"], stretch=(1, 2), fit=(0,),
            fixed={3: 170, 4: 170}, multi=True)
        page = _TabPage(
            "The customer wrote back about a quotation. Read what they said, "
            "then tell Prism what it means.",
            self.replies_table, "mail", "No answers to read",
            "When a customer replies to a quotation, it is listed here with "
            "what Prism makes of it.", on_change=self._render_replies)

        panel = page.panel
        self.reply_sent_line = C.label("", level="META", wrap=True)
        panel.extra.addWidget(self.reply_sent_line)
        # What they wrote on the left, what Prism makes of it on the right,
        # side by side. Stacked, the two needed more height than the panel
        # gets at the app's default size: "Prism thinks" was drawn over the
        # text box, and once "Delete from this list" added a second line of
        # buttons the picker drew empty and the button as a black block
        # (13 Oct, real window at 1078x900).
        pair = QHBoxLayout()
        pair.setSpacing(theme.SPACE_3)
        wrote = QVBoxLayout()
        wrote.setSpacing(theme.SPACE_2)
        wrote.addWidget(C.label(i18n.t("What they wrote:"), level="LABEL"))
        self.reply_text = _ReplyBox()
        self.reply_text.setReadOnly(True)
        # Three to eight lines, from the font — never a fixed pixel height,
        # which is what squeezed the old tab into illegibility. It scrolls.
        line = self.reply_text.fontMetrics().lineSpacing()
        self.reply_text.setMinimumHeight(line * 3 + 2 * theme.SPACE_2)
        self.reply_text.setMaximumHeight(line * 8 + 2 * theme.SPACE_2)
        # It asks for as much height as the column beside it, no more: the
        # panel is laid out at its asked-for height, so a taller ask here
        # is what pushed everything over everything else.
        self.reply_text.ask = max(self.reply_text.minimumHeight(),
                                  2 * C.MIN_TARGET + theme.SPACE_2)
        wrote.addWidget(self.reply_text)
        pair.addLayout(wrote, stretch=1)
        verdict = QVBoxLayout()
        verdict.setSpacing(theme.SPACE_2)
        thinks = QLabel(i18n.t("Prism thinks:"))
        verdict.addWidget(thinks)
        self.intent_picker = QComboBox()
        self.intent_picker.setMinimumHeight(C.MIN_TARGET)
        for key, label in INTENT_LABELS.items():
            if key != "unclear":
                self.intent_picker.addItem(i18n.t(label), key)
        self.intent_picker.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        thinks.setBuddy(self.intent_picker)
        verdict.addWidget(self.intent_picker)
        self.apply_btn = C.button(i18n.t("Update the register"), "primary",
                                  icon_name="check", on_click=self._apply_reply)
        verdict.addWidget(self.apply_btn)
        verdict.addStretch(1)
        pair.addLayout(verdict)
        panel.extra.addLayout(pair)
        panel.add_action("win_back", "Write a reply to win them back",
                         "secondary", self._win_back)
        panel.add_action("folder", "Open this inquiry's folder", "tertiary",
                         self._open_inquiry_folder)
        panel.add_action("history", "See the whole story", "tertiary",
                         self._show_history)
        panel.add_action("delete", "Delete from this list", "destructive",
                         lambda: self._delete_from_list("replies"))
        self.replies_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("replies"))
        self.replies_table.itemSelectionChanged.connect(
            lambda: self._label_delete("replies"))
        self.replies_table.cellDoubleClicked.connect(
            lambda *_: self._open_mail("replies"))
        return page

    def _fill_replies(self, result):
        """Bank whatever this check found into the worklist file, then draw
        the tab from THAT — never straight from `result`, which only ever
        holds what this one check happened to see. See _render_replies()."""
        entries = [_worklist_entry(item)
                  for item in list(getattr(result, "replies", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "replies", entries)
        self._render_replies()

    def _render_replies(self):
        """Redraw from the worklist file, not from memory — a reply from
        two checks ago that nobody has applied yet is exactly as pending as
        one from thirty seconds ago, and both must still be here after the
        dialog is closed and reopened."""
        worklist = CB.get_worklist()
        register = CB.get_register()
        folder = self._root()
        data = worklist.load(folder) if folder else {"replies": []}
        items = [_StoredItem(entry, register.find(self._register_rows,
                                                   entry.get("inquiry_no", "")))
                for entry in worklist.pending(data, "replies")]
        page = self._pages.get("replies")
        text = page.search_text() if page else ""
        items = [item for item in items
                 if _matches(text, item.inquiry_no,
                             (item.row or {}).get("Customer", ""),
                             item.message.from_addr, item.message.subject)]
        self._replies = items
        self.replies_table.setRowCount(len(items))
        for index, item in enumerate(items):
            row = item.row or {}
            would = register.REPLY_STATUS.get(item.intent, "")
            cells = [row.get("Inquiry no", "") or item.inquiry_no,
                     row.get("Customer", "") or row.get("Email", "")
                     or item.message.from_addr,
                     item.message.subject,
                     i18n.t(INTENT_LABELS.get(item.intent, item.intent)),
                     would or i18n.t("nothing — needs your eye")]
            base = status_colours().get(would) if would else None
            for column, value in enumerate(cells):
                cell = QTableWidgetItem(str(value))
                if base:
                    cell.setBackground(theme.qcolor(base[0]))
                    cell.setForeground(theme.qcolor(base[1]))
                if column == 3:
                    paint(cell, INTENT_COLOURS, item.intent)
                elif column == 4 and would:
                    paint(cell, status_colours(), would)
                self.replies_table.setItem(index, column, cell)
        if items:
            self.replies_table.setCurrentCell(0, 0)
        self._show_reply()
        self._refresh_counts()
        self._render_board()

    def _selected_reply(self):
        index = self.replies_table.currentRow()
        rows = getattr(self, "_replies", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _show_reply(self):
        item = self._selected_reply()
        if item is None:
            self.reply_text.setPlainText("")
            return
        message = item.message
        self.reply_text.setPlainText(
            message.snippet(1200) if hasattr(message, "snippet")
            else getattr(message, "body", ""))
        # Preselect what Prism thought, so agreeing with it is one click and
        # disagreeing is two. An unclear reply leaves the box where it is
        # rather than nominating a guess the owner might accept by reflex.
        position = self.intent_picker.findData(item.intent)
        if position >= 0:
            self.intent_picker.setCurrentIndex(position)

    def _apply_reply(self, *, item=None, intent=None):
        item = item or self._selected_reply()
        if item is None:
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Pick a reply from the list first."))
            return
        # Two replies on the same inquiry can both be waiting here at once —
        # a customer who answers twice before either gets applied, or one
        # reopened by hand. worklist.pending() is oldest-first, so if this
        # one is not the last with this inquiry number, a newer answer is
        # still sitting below it — applying this one would silently
        # overwrite whatever that one decides, with nothing on screen to
        # say so afterwards.
        siblings = [r for r in self._replies if r.inquiry_no == item.inquiry_no]
        if len(siblings) > 1 and siblings[-1] is not item:
            proceed = QMessageBox.question(
                self, i18n.t("A newer reply is waiting"),
                i18n.t("This inquiry has a more recent reply still waiting "
                       "in this list. Applying this older one now will "
                       "overwrite whatever the newer one decides.\n\nApply "
                       "this one anyway?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if proceed != QMessageBox.Yes:
                return
        intent = intent or self.intent_picker.currentData()
        register = CB.get_register()
        # Work on the copy in the register we just loaded, not on the copy
        # carried by the worker's Item — saving writes self._register_rows,
        # and a change made to a detached dict would be written over.
        target = register.find(self._register_rows,
                               (item.row or {}).get("Inquiry no", ""))
        if target is None:
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("That inquiry is no longer in the register."))
            return
        register.mark_reply(target, intent)
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        # Resolved in the worklist file, not just popped from the table — a
        # re-check must never bring an already-applied reply back onto this
        # list, which popping the in-memory row alone would not have
        # prevented once the dialog closed and reopened.
        if item.message_id:
            CB.get_worklist().resolve(self._root(), "replies", item.message_id)
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} is now {status}.")
            .replace("{no}", target.get("Inquiry no", ""))
            .replace("{status}", target.get("Status", "")))
        self._render_replies()

    # ── tab 2: no answer yet ──────────────────────────────────────────────
    def _followup_tab(self) -> QWidget:
        self.followups = self._make_table(
            ["Quotation no", "Customer", "Quoted on", "Value", "Reminder",
             "Inquiry no"], stretch=1, fit=(0, 2, 3, 4, 5), multi=True)
        page = _TabPage(
            "Quotations you sent that the customer has not answered yet.",
            self.followups, "clock", "Every quotation has been answered",
            "When you send a quotation it waits here until the customer "
            "replies.", on_change=self._render_waiting)
        self.followups_empty = page.empty
        self._add_row_actions(page.panel)
        self.remind_btn = page.panel.buttons["remind"]
        self.followups.currentCellChanged.connect(
            lambda *_: self._sync_panel("waiting"))
        self.followups.itemSelectionChanged.connect(
            lambda: self._label_delete("waiting"))
        self.followups.cellDoubleClicked.connect(
            lambda *_: self._open_mail("waiting"))
        return page

    # ── tab 4: the order came ─────────────────────────────────────────────
    def _orders_tab(self) -> QWidget:
        """Purchase orders, against the quotations they answer.

        The second of the two places money moves, and the last stop of the
        whole workflow: Prism reads the PO into fields, puts it next to the
        quotation that was actually sent, and points at every difference — a
        rate quietly reduced between quote and PO is the classic dispute, and
        this check costs two seconds now or an argument in three weeks.
        Accepting is a button a person presses; nothing here accepts itself.
        """
        self.orders_table = self._make_table(
            ["Inquiry no", "Customer", "Subject", "What Prism noticed"],
            stretch=2, fit=(0, 1, 3), multi=True)
        page = _TabPage(
            "A purchase order arrived, or a customer said yes. Check it "
            "against your quotation, then record it.",
            self.orders_table, "archive", "No orders waiting",
            "A PO that arrives by mail is read here and checked against what "
            "you quoted.", on_change=self._render_orders)
        panel = page.panel
        self.po_btn = panel.add_action("po", "Read the PO and compare",
                                       "primary", self._review_po)
        panel.add_action("record_po", "Record the PO by hand", "primary",
                         self._record_po_by_hand)
        panel.add_action("phone", "They replied by phone…", "secondary",
                         self._phone_reply)
        panel.add_action("lost", "Mark as lost", "secondary", self._mark_lost)
        panel.add_action("remove_order", "Not an order — remove it",
                         "secondary", self._remove_order)
        panel.add_action("folder", "Open this inquiry's folder", "tertiary",
                         self._open_order_folder)
        panel.add_action("history", "See the whole story", "tertiary",
                         self._show_history)
        panel.add_action("delete", "Delete from this list", "destructive",
                         lambda: self._delete_from_list("orders"))
        self.orders_table.currentCellChanged.connect(
            lambda *_: self._sync_panel("orders"))
        self.orders_table.itemSelectionChanged.connect(
            lambda: self._label_delete("orders"))
        self.orders_table.cellDoubleClicked.connect(
            lambda *_: self._open_mail("orders"))
        return page

    def _fill_orders(self, result):
        """Bank whatever this check found into the worklist file, then draw
        the tab from THAT — see _fill_replies() for why."""
        entries = [_worklist_entry(item)
                  for item in list(getattr(result, "orders", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "orders", entries)
        self._render_orders()

    def _render_orders(self):
        """Redraw from the worklist file. This is the tab a friend's PO
        went missing from the moment the mailbox's bookmark moved past it —
        an unaccepted order three checks old is still an unaccepted order."""
        worklist = CB.get_worklist()
        register = CB.get_register()
        folder = self._root()
        data = worklist.load(folder) if folder else {"orders": []}
        items = [_StoredItem(entry, register.find(self._register_rows,
                                                   entry.get("inquiry_no", "")))
                for entry in worklist.pending(data, "orders")]
        # Plus every row the customer said yes on and no PO has landed for —
        # it is coming by hand, by phone or on paper, and "Record the PO by
        # hand" is how it gets in. Without these the tab only ever showed
        # POs that happened to arrive by mail.
        covered = {item.inquiry_no for item in items}
        for row in self._register_rows:
            if ((row.get("Status") or "").strip() == register.ACCEPTED
                    and row.get("Inquiry no", "") not in covered):
                items.append(_RegisterOnlyItem(row))
        page = self._pages.get("orders")
        text = page.search_text() if page else ""
        items = [item for item in items
                 if _matches(text, item.inquiry_no,
                             (item.row or {}).get("Customer", ""),
                             item.message.from_addr, item.message.subject)]
        self._orders = items
        self.orders_table.setRowCount(len(items))
        for index, item in enumerate(items):
            row = item.row or {}
            cells = [row.get("Inquiry no", "") or item.inquiry_no,
                     row.get("Customer", "") or row.get("Email", "")
                     or item.message.from_addr,
                     item.message.subject,
                     i18n.t(item.note) if item.note else ""]
            # Every row here is a yes: green, Converted's colour. That
            # includes one accepted by hand with no PO yet: its status is
            # Accepted, which the owner's list puts with the PO received
            # ([12][15][17]); amber now means "no reply". Its Note column and
            # its "Record the PO by hand" button still say what is missing.
            pair = status_colours()[register.CONVERTED]
            for column, value in enumerate(cells):
                cell = QTableWidgetItem(str(value))
                cell.setBackground(theme.qcolor(pair[0]))
                cell.setForeground(theme.qcolor(pair[1]))
                self.orders_table.setItem(index, column, cell)
        if items:
            self.orders_table.setCurrentCell(0, 0)
        self._refresh_counts()
        self._render_board()

    def _selected_order(self):
        index = self.orders_table.currentRow()
        rows = getattr(self, "_orders", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _open_order_folder(self):
        item = self._selected_order()
        if item is not None:
            open_in_file_manager(item.folder
                                 or (item.row or {}).get("Folder", "")
                                 or self._root())

    def _po_file(self, item) -> str:
        """The file most likely to be the order, out of what the check filed.

        The engine's own name heuristic picks the attachment ("PO 4471.pdf"
        is not a guess); the saved copy is matched back by name because
        save_attachments de-collides filenames rather than overwriting. Two
        unnamed PDFs is genuinely ambiguous and returns nothing — the mail
        body, or the typed-in form, is the honest fallback.
        """
        po = CB.get_po()
        readable = (".pdf", ".docx", ".docm", ".txt", ".csv")
        candidates = [f for f in (item.files or [])
                      if f.lower().endswith(readable) and os.path.exists(f)]
        if not candidates and item.folder and os.path.isdir(item.folder):
            candidates = [os.path.join(item.folder, name)
                          for name in sorted(os.listdir(item.folder))
                          if name.lower().endswith((".pdf", ".docx", ".docm"))
                          and not documents.is_ours(name)]
        wanted = po.find_attachment(item.message) if item.message else None
        if wanted:
            stem = os.path.splitext(wanted)[0].lower()
            for path in candidates:
                base = os.path.splitext(os.path.basename(path))[0].lower()
                # Saved as INQ-26-27-0005_PO 4471.pdf since attachments
                # carry their inquiry number; compare the sender's own part.
                base = re.sub(r"^[a-z]+-\d{2}-\d{2}-\d+_", "", base)
                if base == stem or base.startswith(stem) or stem.startswith(base):
                    return path
        return candidates[0] if len(candidates) == 1 else ""

    def _review_po(self, *, item=None):
        item = item or self._selected_order()
        if item is None:
            QMessageBox.information(
                self, i18n.t("Purchase order"),
                i18n.t("Pick an order from the list first."))
            return
        # Read again in _po_accepted() — the review dialog is modal, so the
        # selection cannot change underneath it, but the item itself (and
        # its message id, needed to resolve it in the worklist file) is not
        # otherwise threaded through _show_po()/_po_read().
        self._po_item = item
        register = CB.get_register()
        row = register.find(self._register_rows, item.inquiry_no) or item.row
        if not row:
            QMessageBox.information(
                self, i18n.t("Purchase order"),
                i18n.t("That inquiry is no longer in the register."))
            return

        settings = self._settings()
        po = CB.get_po()
        text, source, advice = "", "", ""
        path = self._po_file(item)
        if path:
            try:
                text = po.text_from(path)
                source = os.path.basename(path)
            except Exception as e:          # noqa: BLE001 — POError carries advice
                advice = str(e)
        elif getattr(item.message, "body", "").strip():
            # Occasionally the order is simply typed into the mail.
            text = item.message.body
            source = i18n.t("the email itself")
        else:
            advice = i18n.t(
                "No readable file came with this mail — type the fields from "
                "the printed order and everything else carries on as normal.")

        # The privacy switch means every AI call on mail content, and a PO is
        # mail content. With it on — or with no key — the reading is done by
        # the person instead, never silently ignored.
        if text and settings.get("local_only"):
            text = ""
            advice = i18n.t(
                "Keep everything on this computer is switched on, so the "
                "order is not sent out to be read. Type the fields from the "
                "printed order and everything else carries on as normal.")
        elif text and not self.cfg.get("api_key"):
            text = ""
            advice = i18n.t(
                "Reading a PO needs the free key Prism plans with, and there "
                "isn't one saved. Type the fields in, or add the key under "
                "Settings.")

        self._po_row = row
        if not text:
            self._show_po(None, row, advice=advice)
            return
        self.po_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.status.setText(i18n.t("Reading the purchase order…"))
        self._po_worker = POReadWorker(self.cfg, text, source)
        self._po_worker.done.connect(lambda order: self._po_read(order, row))
        self._po_worker.failed.connect(
            lambda message: self._po_read_failed(message, row))
        self._po_worker.start()

    def _po_read(self, order, row: dict):
        self.po_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        po = CB.get_po()
        quote = _read_sent_quotation(row)
        differences = po.compare(order, quote) if quote is not None else []
        advice = "" if quote is not None else i18n.t(
            "The quotation that was sent couldn't be read back from the "
            "inquiry's folder, so there is no line-by-line comparison — the "
            "copy in the folder is the record to check against.")
        self._show_po(order, row, advice=advice, differences=differences)

    def _po_read_failed(self, message: str, row: dict):
        """Extraction failed — a scan, a dead key, a rate limit. The POError
        text already says what to do, and the typed-in form is always the way
        through: an unreadable file must never block accepting a real order.
        (OCR for scanned POs is deliberately not built — docs/DEFERRED.md has
        the trigger.)"""
        self.po_btn.setEnabled(True)
        self.progress.setVisible(False)
        self.status.setText("")
        self._show_po(None, row, advice=message)

    def _show_po(self, order, row: dict, advice: str = "",
                 differences: list | None = None):
        dialog = _POReviewDialog(row, order, differences or [], advice, self)
        if dialog.exec() != QDialog.Accepted:
            return
        self._po_accepted(row, dialog.number(), dialog.value_text(),
                          dialog.date_text())

    def _po_accepted(self, row: dict, number: str, value_text: str,
                     po_date: str):
        register = CB.get_register()
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        register.mark_converted(target, number, register.money(value_text))
        if po_date:
            target["PO date"] = po_date
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        CB.get_history().append(
            target.get("Folder") or self._root(),
            i18n.t("Order accepted — converted"),
            body=i18n.t("PO {po}, dated {date} — ₹{value}.")
                .replace("{po}", number).replace("{date}", po_date or "—")
                .replace("{value}", target.get("Order value", "") or value_text))
        # Resolved in the worklist file — see _apply_reply() for why popping
        # the in-memory row is not enough on its own.
        item = getattr(self, "_po_item", None)
        if item is not None and item.message_id:
            CB.get_worklist().resolve(self._root(), "orders", item.message_id)
        self._refresh_register()
        self._render_orders()
        self.status.setText(
            i18n.t("{no} is converted — PO {po}, ₹{value}.")
            .replace("{no}", target.get("Inquiry no", ""))
            .replace("{po}", number)
            .replace("{value}", target.get("Order value", "") or value_text))
        self._after_po_accepted(target, number)

    # ── running a check ───────────────────────────────────────────────────
    def _is_the_open_screen(self) -> bool:
        """Is this panel the screen currently on show?

        Asked of the stack rather than through isVisible(). isVisible() is
        true only if EVERY ancestor is visible too, so it also answers "no"
        while the main window happens to be hidden — during the licence gate,
        for instance — and a question that should have been asked would be
        silently dropped. Which page a stack is showing is the thing actually
        being asked about here, and it does not depend on the window above it.

        No stack in the parent chain means this was built standalone (tests
        do that, ~30 times), and something nobody has put on screen must not
        open a modal.
        """
        node = self.parentWidget()
        while node is not None:
            if isinstance(node, QStackedWidget):
                return node.currentWidget() is self
            node = node.parentWidget()
        return False

    def _first_look(self, auto_check: bool = False):
        if self._closed:
            return
        # Only ask about setup on the screen the person is actually looking
        # at. MainWindow builds this panel at startup (main_window.py, next
        # to every other screen) and __init__ ends with self.enter(), which
        # arms the deferred callback below — so on every launch with no
        # mailbox configured, Prism opened a blocking "This needs your
        # mailbox set up first. Set it up now?" over the dashboard, before
        # the user had clicked anything or shown any interest in Email
        # automation. Reproduced by building MainWindow and turning the
        # event loop for 300ms: one modal, every time.
        #
        # It is the same callback that hangs the test suite. The panel is
        # constructed ~30 times across tests/test_inquiry_ui.py, each one
        # arming this; any instance not explicitly closed leaks its
        # singleShot into whichever later test next spins the event loop,
        # which then blocks on a modal no headless run can answer. closeEvent
        # documents `_closed` as the guard for that — it only works for the
        # instances a test remembers to close, and visibility covers the rest
        # for the same reason it is right in the product: a screen nobody is
        # looking at has no business opening a modal.
        #
        # The real path is unaffected. _open_inquiry_dialog() calls enter()
        # and then setCurrentIndex(INQUIRY_WORK) in the same slot, so by the
        # time this zero-delay callback is delivered the panel is the stack's
        # current page — which is exactly the moment the question is worth
        # asking.
        if not self._is_the_open_screen():
            return
        if not is_ready(self.cfg):
            answer = QMessageBox.question(
                self, i18n.t("Email inquiry automation"),
                i18n.t("This needs your mailbox set up first — it takes about "
                       "two minutes and only happens once.\n\nSet it up now?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                self.open_setup()
            return
        if auto_check:
            self.check_now()
            return
        self.status.setText(i18n.t("Ready. Press Check my mail now."))

    def open_setup(self):
        dialog = InquirySetupDialog(self.cfg, self)
        if dialog.exec() == QDialog.Accepted:
            self.cfg = dialog.cfg
            # A changed interval takes effect now rather than next time the
            # screen is opened — otherwise turning it on appears to do nothing.
            self._apply_auto_interval()
            self._refresh_register()
            self.status.setText(i18n.t("Saved. Press Check my mail now."))

    def check_now(self, quiet: bool = False):
        """Fetch and sort every mailbox. `quiet` is a timer tick rather than
        a button press.

        The only difference a quiet run makes is that failures land in the
        status line instead of a dialog. Somebody running a factory should not
        have a modal appear over their work every ten minutes because a mail
        server had a bad afternoon.

        The mailboxes are walked ONE AT A TIME, never in parallel: every
        account's rows land in the same register, and the engine's own rule —
        one check at a time, because two fetches racing on one bookmark
        registers the same inquiry twice — becomes "N fetches racing on one
        order book" the moment there are N accounts.
        """
        if not is_ready(self.cfg):
            if not quiet:
                self._first_look()
            return
        self._quiet = quiet
        if not quiet:
            # A person pressing the button is asserting the credentials are
            # right — every mailbox gets to try again, which is also how the
            # user gets going after fixing a password.
            self._auth_failures = {}

        accounts = active_accounts_of(self.cfg)
        if quiet:
            # A mailbox whose password keeps being refused is skipped by the
            # timer rather than hammered — the provider will throttle and then
            # lock the account, and the customer's report is "Prism locked me
            # out of my email". The others carry on being read.
            accounts = [a for a in accounts
                        if self._auth_failures.get(a["address"], 0)
                        < self.AUTH_FAILURES_BEFORE_STOP]
        if not accounts:
            return

        self._queue = accounts
        self._queue_pos = 0
        self._partial = []
        if len(accounts) == 1:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, len(accounts))
            self.progress.setValue(0)
        # The status line says which mailbox and position we are on; keeping
        # numbers out of the 8px motion bar makes the animation legible rather
        # than a row of flashing, segmented purple blocks.
        self.progress.setTextVisible(False)
        self._set_checking(True)
        self.progress.setVisible(True)
        self._check_account()

    def _set_checking(self, running: bool):
        self.check_btn.setEnabled(not running)
        self.reset_btn.setVisible(running)

    def _reset_check(self):
        """Give up on the check in progress and let the owner try again.

        Hard termination, not a cooperative stop — InboxCheckWorker has none
        to call, so this is the same fallback closeEvent() already reaches
        for when a worker will not finish on its own. It is the whole story
        here rather than a last resort, because the owner asked for it.
        """
        self._queue = []
        worker, self._worker = self._worker, None
        if worker is not None:
            try:
                if worker.isRunning():
                    worker.terminate()
                    worker.wait(1000)
            except RuntimeError:
                pass        # already deleted; nothing to wait for
        self._quiet = False
        self._set_checking(False)
        self.progress.setVisible(False)
        self.status.setText(i18n.t(
            "Check cancelled. Press Check my mail now to try again."))

    def _check_account(self):
        """Start the check for the account the walk is standing on."""
        account = self._queue[self._queue_pos]
        if len(self._queue) > 1:
            self.status.setText(
                i18n.t("Reading {who}… ({i} of {n})")
                .replace("{who}", account.get("address", ""))
                .replace("{i}", str(self._queue_pos + 1))
                .replace("{n}", str(len(self._queue))))
        else:
            self.status.setText(i18n.t("Reading your inbox…"))

        settings = self._settings()
        engine_cfg = dict(self.cfg)
        # The engine's inbox module reads cfg["inbox"]; the GUI keeps its
        # accounts under cfg["inquiry"] so this feature's settings travel
        # together and cannot be half-configured by the Email add-on.
        engine_cfg["inbox"] = {k: v for k, v in account.items()
                               if k != "state"}

        inbox = CB.get_inbox()
        triage = CB.get_triage()
        # Each mailbox reads its own bookmark; the sorter's knowledge is
        # shared — a sender is the same sender whichever address they wrote
        # to, and what account one's check learned is saved before account
        # two's check reads it.
        state = inbox.State.from_dict(account.get("state"))
        knowledge = triage.Knowledge.from_dict(settings.get("knowledge"))

        self._worker = InboxCheckWorker(
            engine_cfg, self._root(), state=state, knowledge=knowledge,
            local_only=bool(settings.get("local_only")),
            followup_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._worker.done.connect(self._account_checked)
        self._worker.failed.connect(self._account_failed)
        self._worker.progress.connect(self._on_check_progress)
        self._worker.start()

    def _on_check_progress(self, stage: str, done: int, total: int):
        """How far this mailbox's check has got: a real count once the mails
        are fetched, so the ring fills instead of spinning blind."""
        who = ""
        if len(self._queue) > 1:
            who = self._queue[self._queue_pos].get("address", "") + " — "
        if stage == "fetch":
            text = i18n.t("Reading your inbox…")
        elif stage == "sort":
            if total == 0:
                text = i18n.t("No new mail.")
            else:
                text = i18n.t("Sorting {n} new mails…").replace("{n}", str(total))
        else:
            text = i18n.t("Filing mail {i} of {n}…").replace(
                "{i}", str(done)).replace("{n}", str(total))
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done if stage == "file" else 0)
        self.status.setText(who + text)

    def _account_failed(self, message: str):
        """mailflow.check() promises never to raise; this is the seatbelt for
        the promise breaking. Treated exactly like a check that returned an
        error, so the walk carries on to the next mailbox."""
        mailflow = CB.get_mailflow()
        self._account_checked(mailflow.Result(error=message))

    def _account_checked(self, result):
        """One mailbox is done — bank it, then walk on or finish."""
        account = (self._queue[self._queue_pos]
                   if self._queue_pos < len(self._queue) else {})
        address = account.get("address", "")
        self._partial.append((address, result))

        if result.error and self._quiet \
                and CB.get_inbox().is_auth_failure(result.error):
            self._auth_failures[address] = \
                self._auth_failures.get(address, 0) + 1
        elif result.fetched or not result.error:
            # Got into the mailbox, so the credentials are good — clear any
            # run of rejections against this address.
            self._auth_failures.pop(address, None)

        # Persist this account's bookmark and what the sorter learned before
        # the next account runs — the learning chains through the config, and
        # a crash mid-walk must not cost the accounts already checked their
        # place. On a locked register the engine hands back the OLD state, so
        # saving it is exactly right: the same mail comes back next time.
        self._remember_account(address, result)

        register_locked = bool(result.error) and "Excel" in result.error
        self._queue_pos += 1
        if len(self._queue) > 1:
            self.progress.setRange(0, len(self._queue))
        else:
            self.progress.setRange(0, 0)
        self.progress.setValue(self._queue_pos)
        if register_locked:
            # The same locked file would refuse every account after this one,
            # and none of their bookmarks have moved — stopping loses nothing
            # and spares the owner N copies of the same sentence.
            self._finish_check()
            return
        if self._queue_pos < len(self._queue):
            self._check_account()
            return
        self._finish_check()

    def _finish_check(self):
        self._stamp_mailboxes(self._partial)
        merged = self._merge_results(self._partial)
        self._checked(merged, remember=False)
        self._maybe_stop_timer()

    def _merge_results(self, partial) -> object:
        """Every mailbox's result as one, in the shape _checked() renders.

        Errors are prefixed with the address that had them once there is more
        than one mailbox — "the mail server didn't answer" is only half a
        sentence when there are three servers it could mean.
        """
        mailflow = CB.get_mailflow()
        merged = mailflow.Result()
        counts: dict = {}
        errors = []
        for address, result in partial:
            merged.fetched += int(getattr(result, "fetched", 0) or 0)
            merged.sorted_mail.extend(result.sorted_mail)
            merged.new_inquiries.extend(result.new_inquiries)
            merged.replies.extend(result.replies)
            merged.orders.extend(result.orders)
            for key, value in (result.counts or {}).items():
                counts[key] = counts.get(key, 0) + value
            # The follow-up and SOP lists are computed over the WHOLE register
            # on every check, so the latest successful one is already complete
            # — extending would list the same quiet quotation once per mailbox.
            if not result.error:
                merged.followups = result.followups
                merged.sops = result.sops
            merged.state = result.state
            merged.knowledge = result.knowledge
            if result.error:
                errors.append(f"{address} — {result.error}"
                              if address and len(partial) > 1
                              else result.error)
        merged.counts = counts
        merged.error = "\n\n".join(errors)
        return merged

    def _stamp_mailboxes(self, partial):
        """Write which mailbox each new inquiry arrived at into the register.

        One more column — "Mailbox" — because with sales@, info@ and the
        owner's own address feeding one file, "who is this customer talking
        to" is the first question the sheet gets asked. Stamped only where
        the column is empty: a purchase order landing on a different address
        later must not rewrite where the inquiry originally arrived.

        Best-effort on purpose. The rows themselves were saved by the engine
        moments ago; if Excel took the file in the meantime the stamp waits —
        the register's own lock message has already told the owner what to do,
        and attribution is not worth a second error on top of it.
        """
        stamps: dict[str, str] = {}
        for address, result in partial:
            if not address:
                continue
            for item in list(result.new_inquiries) + list(result.orders):
                if item.inquiry_no:
                    stamps.setdefault(item.inquiry_no, address)
        if not stamps:
            return
        register = CB.get_register()
        try:
            rows = register.load(self._paths().register_csv)
            changed = False
            for row in rows:
                number = row.get("Inquiry no", "")
                if number in stamps and not (row.get("Mailbox") or "").strip():
                    row["Mailbox"] = stamps[number]
                    changed = True
            if changed:
                register.save(rows, self._paths().register_csv)
        except Exception:                   # noqa: BLE001
            pass

    def _maybe_stop_timer(self):
        """Give up the timer only when EVERY mailbox has settled into refusing
        its password — while one still answers, checking carries on and the
        status line names the ones being skipped."""
        locked = [address for address, count in self._auth_failures.items()
                  if count >= self.AUTH_FAILURES_BEFORE_STOP]
        if not locked:
            return
        addresses = ", ".join(locked)
        every = all(
            self._auth_failures.get(a.get("address", ""), 0)
            >= self.AUTH_FAILURES_BEFORE_STOP
            for a in active_accounts_of(self.cfg))
        if every:
            self._auto.stop()
            # Loud, unlike every other quiet-run failure: automatic checking
            # has stopped and will not restart on its own, so saying nothing
            # would leave the register silently going stale.
            self.status.setText(i18n.t(
                "Automatic checking is off — {who} kept refusing the "
                "password. Update it in Setup, then press Check now."
            ).replace("{who}", addresses or i18n.t("the mail server")))
        else:
            self.status.setText(i18n.t(
                "Skipping {who} — the password keeps being refused. Update "
                "it in Setup, then press Check now."
            ).replace("{who}", addresses))

    #: Consecutive rejected sign-ins before a mailbox is given up on. Three,
    #: because one can be a provider hiccup and two can be a password
    #: mid-rotation.
    AUTH_FAILURES_BEFORE_STOP = 3

    def _check_failed(self, message: str):
        self._set_checking(False)
        self.progress.setVisible(False)
        self.status.setText("")
        self._note_failure(message)
        self._explain(message)
        self._quiet = False

    def _note_failure(self, message: str):
        """Count a rejected sign-in against the first mailbox.

        The single-mailbox path — kept because tests and simple callers hand
        a result straight to _checked(); the account walk counts per address
        in _account_checked() instead, where it knows which mailbox it was.

        A network failure never counts: retrying is exactly what the timer is
        for. A rejected password does, because the provider will throttle and
        then lock the account, and the customer's report is "Prism locked me
        out of my email".
        """
        if not getattr(self, "_quiet", False):
            self._auth_failures = {}
            return
        if not CB.get_inbox().is_auth_failure(message):
            return                          # transport, not credentials
        accounts = active_accounts_of(self.cfg)
        address = accounts[0].get("address", "") if accounts else ""
        self._auth_failures[address] = self._auth_failures.get(address, 0) + 1
        self._maybe_stop_timer()

    def _explain(self, message: str):
        """Plain-English failure, through the same translator as the rest."""
        if getattr(self, "_quiet", False):
            self.status.setText(message.split("\n")[0])
            return
        try:
            from dialogs.problem_dialog import show_problem
            show_problem(self, message)
        except Exception:
            QMessageBox.warning(self, i18n.t("Email inquiry automation"), message)

    def _checked(self, result, remember: bool = True):
        """Render one result — a single mailbox's, or the whole walk's merge.

        `remember` is True on the direct path (one result, persist its
        bookmark here); the account walk passes False because it has already
        banked every account's bookmark as it went.
        """
        self._set_checking(False)
        self.progress.setVisible(False)
        self._result = result

        if result.error:
            self.status.setText("")
            if remember:
                self._note_failure(result.error)
            self._explain(result.error)
            # A locked register still leaves the bookmark alone, so the same
            # mail comes back next time. Nothing to save.
            if not result.fetched:
                self._quiet = False
                return
        elif remember:
            # Got in, so the credentials are good — clear any rejections.
            self._auth_failures = {}

        if remember:
            self._remember(result)
        self.status.setText(result.headline())
        self._fill_arrived(result)
        self._fill_replies(result)
        self._fill_orders(result)
        self._refresh_register()
        # Never move the tab out from under somebody on a timer tick. A screen
        # that rearranges itself every ten minutes while you are reading it is
        # the reason people switch automatic checking off.
        if not self._quiet:
            # A purchase order is money confirmed and waiting on an
            # acceptance, so it wins the opening tab; a reply on a live
            # quotation — somebody waiting on an answer — beats a new
            # inquiry, which will still be there this afternoon.
            self._tabs_quiet = True
            self.tabs.setCurrentIndex(
                TAB_INDEX["orders"] if result.orders else
                TAB_INDEX["replies"] if result.replies else
                TAB_INDEX["to_quote"])
            self._tabs_quiet = False
        self._quiet = False
        # Last, and only after the register has been written: a reminder must
        # never go out to somebody whose reply arrived in this same check and
        # has not been filed yet.
        self._chase_automatically()
        self._auto_quote(result)

    # ── quoting by code, without a person ────────────────────────────────
    def _auto_quote(self, result):
        """Quote and send every new inquiry this check brought in whose mail
        names rate-list codes with quantities -- only with the switch on,
        and one at a time. Anything the plan cannot settle stays in
        "To quote" with the reason on the row."""
        if not autoquote.enabled(self.cfg) or not getattr(result, "new_inquiries", None):
            return
        settings = self._settings()
        rate_path = settings.get("rate_list", "")
        if not rate_path or not os.path.exists(rate_path):
            return
        try:
            items = CB.get_quoting().load_rates(rate_path)
        except Exception as e:                              # noqa: BLE001
            self._explain(str(e))
            return
        register = CB.get_register()
        queue = []
        for item in result.new_inquiries:
            row = register.find(self._register_rows, item.inquiry_no)
            if row is None or (row.get("Quotation no") or "").strip():
                continue
            plan = autoquote.plan(row, items, getattr(item, "message", None))
            if plan.ok and row.get("Email"):
                queue.append((row, plan))
            else:
                note = autoquote.held_note(plan.reason or i18n.t("no email address to reply to"))
                if note not in (row.get("Notes") or ""):
                    row["Notes"] = ((row.get("Notes") or "") + " " + note).strip()
        if queue:
            self._auto_queue = queue
            self._auto_next()
        else:
            self._save_register_quietly()

    def _save_register_quietly(self):
        try:
            self._save_register()
        except Exception as e:                              # noqa: BLE001
            self._explain(str(e))

    def _save_register(self, rows: list | None = None):
        """Write the register this screen holds without erasing rows that
        reached the file after it was read — a mail check, a second Prism on
        a shared folder, a row typed in Excel. A plain save of the
        in-memory copy wiped them, and the next check reissued their
        numbers. See register.save_merged(). Raises what save() raises."""
        register = CB.get_register()
        rows = self._register_rows if rows is None else rows
        added = register.save_merged(rows, self._paths().register_csv,
                                     getattr(self, "_register_seen", None))
        if rows is self._register_rows:
            self._register_rows.extend(added)
        self._register_seen = register.row_keys(list(rows) + list(added))

    def _auto_next(self):
        if not getattr(self, "_auto_queue", None):
            self._save_register_quietly()
            self._refresh_register()
            return
        row, plan = self._auto_queue.pop(0)
        quoting = CB.get_quoting()
        settings = self._settings()
        quote = autoquote.build_quotation(self.cfg, row, self._register_rows, plan.lines,
                                          autoquote.numbers_in_use(self._root()))
        folder = row.get("Folder", "") or self._paths().root
        try:
            os.makedirs(folder, exist_ok=True)
            written, pdf = documents.quotation_files(quote, settings, folder)
            CB.config.save_artifact(pdf or written, quote.number, kind="quote",
                                    task=row.get("Inquiry no", "") or quote.number)
        except Exception as e:                              # noqa: BLE001
            self._explain(str(e))
            self._auto_next()
            return
        if not email_config.can_send(self.cfg):
            row["Notes"] = ((row.get("Notes") or "") + " " + autoquote.held_note(
                i18n.t("no sending account set up"))).strip()
            self._auto_next()
            return
        subject, body = autoquote.covering_mail(quote, settings)
        sender = email_config.default_sender(self.cfg)
        self._auto_worker = SendWorker(
            email_config.cfg_for_sender(self.cfg, sender),
            [{"email": row.get("Email", ""), "name": row.get("Contact person", "")}],
            subject, body,
            [documents.attachment_for(written, pdf)])
        register = CB.get_register()

        def _done(sent, failed, row=row, quote=quote, subject=subject, body=body):
            if failed:
                row["Notes"] = ((row.get("Notes") or "") + " " + autoquote.held_note(
                    i18n.t("send failed: {why}").format(why=failed[0][1]))).strip()
            else:
                register.mark_quoted(row, quote.number, quote.total)
                row["Notes"] = ((row.get("Notes") or "") + " " + i18n.t(
                    "quoted automatically by code")).strip()
                self._log_sent("quotation", row, subject, body=body)
            self._auto_next()

        def _failed(message, row=row):
            row["Notes"] = ((row.get("Notes") or "") + " " + autoquote.held_note(
                i18n.t("send failed: {why}").format(why=message))).strip()
            self._auto_next()

        self._auto_worker.done.connect(_done)
        self._auto_worker.failed.connect(_failed)
        status = i18n.t("Quoting {who} by code…").replace(
            "{who}", row.get("Email", ""))
        if not pdf:
            status = f"{status} {documents.pdf_fallback_note()}"
        self.status.setText(status)
        self._auto_worker.start()

    def _remember(self, result):
        """Persist the bookmark and anything the sorter learned — the direct
        single-result path; the walk banks each account itself."""
        accounts = active_accounts_of(self.cfg)
        address = accounts[0].get("address", "") if accounts else ""
        self._remember_account(address, result)

    def _remember_account(self, address: str, result):
        """Bank one mailbox's bookmark, and what the sorter learned, into the
        account list — mirroring the first account into the legacy keys so a
        config written here still opens in a Prism from before the list."""
        settings = self._settings()
        accounts = accounts_of(self.cfg)
        for account in accounts:
            if account.get("address", "") == address:
                account["state"] = result.state.to_dict()
                break
        settings["accounts"] = accounts
        first = accounts[0] if accounts else {}
        settings["account"] = {k: v for k, v in first.items() if k != "state"}
        settings["state"] = dict(first.get("state") or {})
        knowledge = settings.get("knowledge") or {}
        knowledge["learned"] = dict(result.knowledge.learned)
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)

    def _fill_arrived(self, result):
        """Bank whatever this check sorted into the worklist file, then
        draw the tab from THAT — see _fill_replies() for why: a table
        rebuilt straight from `result` shows only this check's mail, and
        goes blank the moment a later check (or a tab switch, which used to
        force a redraw from nothing) has nothing new to add."""
        entries = [_arrived_entry(message, verdict)
                  for message, verdict in
                  list(getattr(result, "sorted_mail", None) or [])]
        folder = self._root()
        if folder and entries:
            CB.get_worklist().append(folder, "arrived", entries)
        self._render_arrived()

    def _render_arrived(self):
        """Redraw from the worklist file's full log, filtered by the
        "Show:" range — not from memory, and not only "since the last
        check"."""
        worklist = CB.get_worklist()
        folder = self._root()
        data = worklist.load(folder) if folder else {"arrived": []}
        page = self._pages.get("arrived")
        if page is not None:
            sentence = i18n.t(ARRIVED_SENTENCE)
            if folder and worklist.has_archive(folder, "arrived"):
                sentence += " " + i18n.t(ARRIVED_ARCHIVE_NOTE)
            page.sentence.setText(sentence)
        today = date.today()
        text = page.search_text() if page else ""
        rows = [r for r in worklist.history(data, "arrived")
                if (page is None or page.in_range(
                    _parse_iso(r.get("date", "")), today))
                and _matches(text, r.get("from_name"), r.get("from_addr"),
                             r.get("subject"))]
        # Filling the table row by row fires currentCellChanged as it goes
        # — Qt moving "current" as rows appear — and that signal runs
        # _sync_panel("arrived"), which reads self._sorted_mail. Left
        # unblocked, it reads the OLD list against the NEW, half-filled
        # table mid-loop: an index mismatch inside a Qt signal handler,
        # not a plain Python exception, and exactly the kind of reentrancy
        # that crashes PySide rather than just raising. Blocked for the
        # rebuild, then synced once, cleanly, after _sorted_mail is the
        # list the table actually shows.
        self.arrived.blockSignals(True)
        try:
            self.arrived.setRowCount(len(rows))
            for index, entry in enumerate(rows):
                category = entry.get("category", "")
                # Tinted the same way every column, not only "Sorted as" —
                # a row's category should read at a glance down the whole
                # line, not just from one cell in it.
                who = entry.get("from_name") or entry.get("from_addr", "")
                self.arrived.setItem(index, 0, paint(
                    QTableWidgetItem(who), CATEGORY_COLOURS, category))
                self.arrived.setItem(index, 1, paint(
                    QTableWidgetItem(entry.get("subject", "")),
                    CATEGORY_COLOURS, category))
                # One line, not the whole mail — the popup (double-click,
                # or "Open mail") is still where the full body and any
                # attachments are read. Same "never saved" case as the
                # popup itself has to tell apart: no "body" key at all
                # means this entry predates body-saving, not that the
                # mail was empty.
                if "body" not in entry:
                    preview = i18n.t("(mail read before this was saved)")
                else:
                    preview = " ".join((entry.get("body") or "").split())[:160]
                self.arrived.setItem(index, 2, paint(
                    QTableWidgetItem(preview), CATEGORY_COLOURS, category))
                label = i18n.t(CATEGORY_LABELS.get(category, category))
                self.arrived.setItem(index, 3, paint(
                    QTableWidgetItem(label), CATEGORY_COLOURS, category))
                why = entry.get("reason") or i18n.t(
                    SOURCE_LABELS.get(entry.get("source", ""), ""))
                self.arrived.setItem(index, 4, paint(
                    QTableWidgetItem(why), CATEGORY_COLOURS, category))
                self.arrived.setItem(index, 5, paint(
                    QTableWidgetItem(_dmy(entry.get("date", ""))),
                    CATEGORY_COLOURS, category))
                self.arrived.setItem(index, 6, paint(
                    QTableWidgetItem(entry.get("time", "")),
                    CATEGORY_COLOURS, category))
                flag = QTableWidgetItem(
                    i18n.t("Reminder") if entry.get("reminder") else "")
                if entry.get("reminder"):
                    flag.setBackground(QColor(_WARN[0]))
                    flag.setForeground(QColor(_WARN[1]))
                self.arrived.setItem(index, 7, flag)
                self.arrived.item(index, 0).setData(
                    Qt.UserRole, entry.get("from_addr", ""))
        finally:
            self.arrived.blockSignals(False)
        self._sorted_mail = rows
        self._sync_panel("arrived")
        self._refresh_counts()

    def _correct(self):
        row = self.arrived.currentRow()
        if row < 0 or not getattr(self, "_sorted_mail", None):
            return
        entry = self._sorted_mail[row]
        address = entry.get("from_addr", "")
        category = self.recategorise.currentData()
        settings = self._settings()
        knowledge = settings.get("knowledge") or {}
        learned = dict(knowledge.get("learned") or {})
        learned[address] = category
        knowledge["learned"] = learned
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        # Update the log entry itself, not just what is on screen right
        # now — otherwise the very next tab switch redraws from disk and
        # the correction looks like it never took.
        reason = i18n.t("sorted here, you taught it")
        if entry.get("message_id"):
            CB.get_worklist().update(
                self._root(), "arrived", entry["message_id"],
                {"category": category, "reason": reason, "source": "learned"})
        entry["category"], entry["reason"] = category, reason
        self.arrived.setItem(row, 3, paint(QTableWidgetItem(
            i18n.t(CATEGORY_LABELS.get(category, category))),
            CATEGORY_COLOURS, category))
        self.arrived.setItem(row, 4, QTableWidgetItem(reason))
        # Teaching the sender's FUTURE mail is not the same as registering
        # THIS mail — a real complaint: correcting one to "inquiry" never
        # put it in To quote, it only meant the next one from the same
        # address would be. If this exact mail isn't already a row (it
        # may well be, if the sorter had already called it actionable),
        # it becomes one now, the same way a fresh check would have.
        registered = False
        if category == "inquiry":
            registered = self._register_arrived(entry)
        self.status.setText(
            (i18n.t("Remembered, and added to To quote. Mail from {who} "
                    "will be sorted that way from now on.") if registered
             else i18n.t("Remembered. Mail from {who} will be sorted that "
                         "way from now on.")).replace("{who}", address))

    def _register_arrived(self, entry: dict) -> bool:
        """Turn one All-mail entry into a real To-quote row, unless it
        already is one. Returns whether a row was actually added."""
        register = CB.get_register()
        stored = _StoredMessage(entry)
        if register.find_by_thread(self._register_rows, stored) is not None:
            return False
        row = register.from_message(stored, rows=self._register_rows)
        row["Folder"] = self._paths().folder_for(row["Inquiry no"])
        os.makedirs(row["Folder"], exist_ok=True)
        self._register_rows.append(row)
        try:
            register.save(self._register_rows, self._paths().register_csv)
        except Exception as e:
            self._explain(str(e))
            return False
        self._refresh_register()
        return True

    # ── the register ──────────────────────────────────────────────────────
    def _rows(self) -> list[dict]:
        if not self._root():
            return []
        register = CB.get_register()
        try:
            return register.load(self._paths().register_csv)
        except Exception:
            return []

    def _refresh_register(self):
        """Read the register off disk and redraw every table drawn from it.
        Anything that only changes what is SHOWN — a date filter, a search
        — calls the tab's own _render_*() instead; re-reading a CSV on a
        shared drive to change nothing but which rows are visible would
        make switching the filter cost what a real mail check costs."""
        register = CB.get_register()
        rows = self._rows()
        self._register_rows = rows
        self._register_seen = register.row_keys(rows)
        settings = self._settings()
        due = register.awaiting_followup(
            rows,
            after_days=int(settings.get("followup_days", 2) or 2),
            max_reminders=int(settings.get("max_reminders", 3) or 3))
        self._followup_rows = list(due)
        # Only a pick on these three tables is followed. They answered and
        # Order came pick their first row by themselves on every redraw;
        # following that pick put a row the owner never chose in To quote's
        # panel the moment its grey quoted rows could hold it (13 Oct, seen
        # in the real window: To quote opened on 0008).
        focus_no = ((self._focus_row or {}).get("Inquiry no", "")
                    if getattr(self, "_focus_tab", "") in _RESELECT_TABS
                    else "")
        self._render_register()
        self._render_to_quote()
        self._render_waiting()
        self._reselect(focus_no)
        self._render_board()

    def _reselect(self, inquiry_no: str):
        """After a save, land the owner back on the row they were on — in
        whichever tab it now lives — instead of clearing the panel and
        making them find it again."""
        if not inquiry_no:
            return
        current = TABS[self.tabs.currentIndex()][0]
        tables = {"to_quote": (self.to_quote_table, self._to_quote_rows),
                  "waiting": (self.followups, self._waiting_rows),
                  "register": (self.register_table, self._visible_rows)}
        for key in (current, "to_quote", "waiting", "register"):
            table, rows = tables.get(key, (None, []))
            if table is None:
                continue
            for index, row in enumerate(rows):
                if row.get("Inquiry no", "") == inquiry_no:
                    table.setCurrentCell(index, 0)
                    return

    def _register_date_matches(self, row: dict, filter_key: str,
                               today: date) -> bool:
        register = CB.get_register()
        return _in_date_range(register.parse_date(row.get("Date received", "")),
                              filter_key, today)

    def _filtered(self, key: str, rows: list[dict]) -> list[dict]:
        """A tab's Show: range and search box applied to register rows —
        in memory, never a disk read."""
        page = self._pages.get(key)
        if page is None:
            return list(rows)
        register = CB.get_register()
        today = date.today()
        text = page.search_text()
        def seen(r):
            # An inquiry the customer wrote on again is as fresh as that
            # reply: "To quote" filtered on the first mail's date hid today's
            # request behind a three-week-old date.
            first = register.parse_date(r.get("Date received", ""))
            if key != "to_quote":
                return first
            last = register.parse_date(r.get("Last contact", ""))
            return max((d for d in (first, last) if d), default=None)

        return [r for r in rows
                if page.in_range(seen(r), today)
                and _matches(text, r.get("Inquiry no"), r.get("Customer"),
                             r.get("Email"), r.get("Product asked"),
                             r.get("Quotation no"))]

    @staticmethod
    def _fill_cells(table: QTableWidget, values: list, status_column=None,
                    tint: tuple[dict, str] | None = None):
        """Append one row, tinted as a whole — every cell the same colour,
        not only the one that happens to print the word — so a long table
        still reads at arm's length rather than asking the owner to hunt for
        the one tinted cell in it. `status_column` reads the key straight
        off the row being drawn; `tint` is for a key that is not itself a
        printed column (the "waiting" tab never shows raw Status text)."""
        index = table.rowCount()
        table.setRowCount(index + 1)
        if tint is not None:
            colours, key = tint
            pair = colours.get((key or "").strip())
        elif status_column is not None:
            # One reading of the status for the screen and the Excel copy
            # (documents.status_key): blank is New, "quoted"/"Won" count.
            pair = status_colours().get(documents.status_key(values[status_column]))
        else:
            pair = None
        for column, value in enumerate(values):
            cell = QTableWidgetItem(str(value))
            if pair:
                cell.setBackground(theme.qcolor(pair[0]))
                cell.setForeground(theme.qcolor(pair[1]))
            table.setItem(index, column, cell)

    def _render_register(self):
        """Redraw the All-inquiries table from _register_rows and its
        filters, without touching the disk. _visible_rows becomes the
        table's actual row order — see its definition in __init__ for why
        _selected_row() must read that list and not _register_rows."""
        register = CB.get_register()
        chip = (self.register_chips.current()
                if hasattr(self, "register_chips") else "all") or "all"
        wanted = {"all": None, "open": set(register.OPEN_STATUSES),
                  "won": {register.CONVERTED},
                  "lost": {register.NOT_CONVERTED}}[chip]
        rows = [r for r in self._filtered("register", self._register_rows or [])
                if wanted is None
                or ((r.get("Status") or "").strip() or register.NEW) in wanted]
        self._visible_rows = rows
        self.register_table.setRowCount(0)
        for row in rows:
            when = row.get("Date received", "")
            clock = row.get("Time received", "")
            self._fill_cells(self.register_table, [
                row.get("Inquiry no", ""), f"{when} {clock}".strip(),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Product asked", ""), row.get("Status", ""),
                _rupees(row.get("Order value") or row.get("Quotation value"))],
                status_column=4)
        self._refresh_counts()

    def _render_to_quote(self):
        """The inquiries still to quote, blue, and under them in grey the
        ones already quoted and still unanswered ([15][17]): a quoted row
        stays where the owner last saw it instead of vanishing, and is in
        "No answer yet" as well. Only the blue ones are "to quote" in the
        tab's count. Once the customer answers, the row moves on."""
        register = CB.get_register()
        shown = self._filtered("to_quote", self._register_rows or [])
        status = lambda r: (r.get("Status") or "").strip() or register.NEW
        waiting = [r for r in shown if status(r) == register.NEW]
        quoted = [r for r in shown
                  if status(r) in (register.QUOTED, register.FOLLOWING_UP)]
        self._to_quote_rows = waiting + quoted
        self._to_quote_count = len(waiting)
        grey = status_colours()[register.QUOTED]
        self.to_quote_table.setRowCount(0)
        for row in self._to_quote_rows:
            self._fill_cells(self.to_quote_table, [
                row.get("Inquiry no", ""), row.get("Date received", ""),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Product asked", ""), row.get("Quantity", ""),
                status(row)],
                tint=({"to quote": status_colours()[register.NEW],
                       "quoted": grey},
                      "to quote" if status(row) == register.NEW else "quoted"))
        self._refresh_counts()

    def _render_waiting(self):
        """Every quotation still unanswered, with what has been done about
        it so far — from worklist/sent.json, so the column can say WHEN a
        reminder went, not just how many."""
        register = CB.get_register()
        rows = [r for r in self._filtered("waiting", self._register_rows or [])
                if (r.get("Status") or "").strip()
                in (register.QUOTED, register.FOLLOWING_UP)]
        self._waiting_rows = rows
        due_ids = {id(r) for r in self._followup_rows}
        settings = self._settings()
        max_reminders = int(settings.get("max_reminders", 3) or 3)
        folder = self._root()
        data = CB.get_worklist().load(folder) if folder else {}
        self.followups.setRowCount(0)
        for row in rows:
            sent_count = int((row.get("Reminders sent") or "0").strip() or 0)
            reminders = [e for e in CB.get_worklist().sent_for(
                data, row.get("Inquiry no", "")) if e.get("kind") == "reminder"]
            if sent_count >= max_reminders:
                chased = i18n.t("{n} sent — call them").replace(
                    "{n}", str(sent_count))
            elif id(row) in due_ids:
                chased = i18n.t("Due today")
            elif reminders:
                chased = i18n.t("Sent {dates}").replace(
                    "{dates}", ", ".join(_dmy(e.get("date", ""), short=True)
                                         for e in reminders))
            elif sent_count:
                chased = i18n.t("{n} sent").replace("{n}", str(sent_count))
            else:
                chased = i18n.t("Not yet due")
            self._fill_cells(self.followups, [
                row.get("Quotation no", "") or i18n.t("(no number)"),
                row.get("Customer", "") or row.get("Email", ""),
                row.get("Quotation date", ""),
                _rupees(row.get("Quotation value")), chased,
                row.get("Inquiry no", "")],
                tint=(status_colours(), documents.status_key(
                    row.get("Status", "") or register.QUOTED)))
            if id(row) in due_ids:
                paint(self.followups.item(self.followups.rowCount() - 1, 4),
                      {"due": _WARN}, "due")
        page = self._pages.get("waiting")
        if page is not None:
            n = len(self._followup_rows)
            page.sentence.setText(
                i18n.t("Quotations you sent that the customer has not "
                       "answered yet. None needs a reminder today.") if not n
                else i18n.t("Quotations you sent that the customer has not "
                            "answered yet. {n} need a reminder today.")
                .replace("{n}", str(n)))
        self._refresh_counts()

    def _refresh_counts(self):
        """The live number in each daily tab's title. Translate the label
        FIRST, then append the count — a string with a number in it is not
        in the catalogue and would never translate."""
        if not hasattr(self, "tabs") or len(self._pages) < len(TABS):
            return
        # Only the rows still to quote: the grey, already-quoted ones under
        # them are counted under "No answer yet".
        counts = {"to_quote": self._to_quote_count,
                  # Every quotation still unanswered — same rows the "No
                  # answer yet" table shows (_render_waiting()). This used
                  # to count _followup_rows instead: only the ones due a
                  # reminder TODAY, a narrower, different list — so the
                  # badge could read "(0)" with a row plainly sitting in
                  # the table right under it, "Not yet due".
                  "waiting": len(self._waiting_rows),
                  "replies": len(self._replies),
                  "orders": len(self._orders)}
        for index, (key, label) in enumerate(TABS):
            text = i18n.t(label)
            if key in COUNTED_TABS:
                text = f"{text} ({counts.get(key, 0)})"
            if self.tabs.tabText(index) != text:
                self.tabs.setTabText(index, text)

    # ── which row, and what it can have done to it ────────────────────────
    def _current_row(self) -> dict | None:
        """The picked register row, or None — silently. The twin of
        _selected_row() for signal handlers, which must never pop a
        message box.

        _focus_row can go stale — set from the replies or orders tab, then
        orphaned the moment _refresh_register() reloads _register_rows with
        fresh dicts, since that reload only re-syncs the to_quote/waiting/
        register tables (_reselect()). Re-anchoring by inquiry number, the
        one thing that survives a reload, is what stops "pick an inquiry
        from the list first" firing on a row that is plainly still
        selected on screen."""
        row = self._focus_row
        if row is not None and any(row is r for r in self._register_rows):
            return row
        if self._focus_key:
            register = CB.get_register()
            found = register.find(self._register_rows, self._focus_key)
            if found is not None:
                self._focus_row = found
                return found
        index = self.register_table.currentRow()
        rows = getattr(self, "_visible_rows", [])
        return rows[index] if 0 <= index < len(rows) else None

    def _selected_row(self) -> dict | None:
        row = self._current_row()
        if row is None:
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Pick an inquiry from the list first."))
        return row

    def _has_drawing(self, row: dict) -> bool:
        folder = row.get("Folder", "")
        try:
            return bool(folder) and os.path.isdir(folder) and any(
                name.lower().endswith(DRAWING_EXTENSIONS)
                and not documents.is_ours(name)
                for name in os.listdir(folder))
        except OSError:
            return False

    def _row_title(self, row: dict) -> str:
        parts = [row.get("Inquiry no", ""),
                 row.get("Customer", "") or row.get("Email", ""),
                 row.get("Product asked", "")]
        if row.get("Quantity"):
            parts.append(row["Quantity"])
        return " · ".join(p for p in parts if p)

    def _row_info(self, row: dict) -> str:
        register = CB.get_register()
        status = (row.get("Status") or "").strip() or register.NEW
        bits = [i18n.t(status)]
        if row.get("Date received"):
            bits.append(i18n.t("came {when}").replace(
                "{when}", row["Date received"]))
        folder = self._root()
        sent = []
        if folder:
            try:
                sent = CB.get_worklist().sent_for(
                    CB.get_worklist().load(folder), row.get("Inquiry no", ""))
            except Exception:           # noqa: BLE001 — a log, not the record
                sent = []
        if sent:
            words = {"quotation": i18n.t("quotation"),
                     "revised": i18n.t("revised quotation"),
                     "reminder": i18n.t("reminder"),
                     "winback": i18n.t("reply")}
            bits.append(i18n.t("Sent so far: {what}").replace("{what}", ", ".join(
                f"{words.get(e.get('kind'), e.get('kind', ''))} "
                f"{_dmy(e.get('date', ''), short=True)}" for e in sent)))
        else:
            bits.append(i18n.t("Sent so far: nothing yet"))
        return " · ".join(bits)

    def _sync_panel(self, key: str):
        """Redraw one tab's Selected-inquiry panel for whatever row is
        picked there. Runs from selection signals, so it never asks
        anything and never pops a box."""
        page = self._pages.get(key)
        if page is None:
            return
        panel = page.panel
        if key == "replies":
            item = self._selected_reply()
            self._show_reply()
            if item is None:
                panel.clear()
                return
            row = item.row or {}
            self._focus_row = row if row else None
            self._focus_key = row.get("Inquiry no", "") if row else ""
            self.reply_sent_line.setText(self._row_info(row) if row else "")
            title = (self._row_title(row) if row else
                     f"{item.inquiry_no} · {item.message.from_addr}")
            self._focus_tab = key
            panel.show_row(
                title, "",
                ["win_back", "folder", "history", "delete"] if row
                else ["delete"], extra=True)
            self._label_delete(key)
            return
        if key == "orders":
            item = self._selected_order()
            if item is None:
                panel.clear()
                return
            row = item.row or {}
            self._focus_row = row if row else None
            self._focus_key = row.get("Inquiry no", "") if row else ""
            self._focus_tab = key
            keys = (["po", "remove_order", "folder", "history", "delete"]
                    if getattr(item, "message_id", None) else
                    ["record_po", "phone", "lost", "folder", "history"])
            title = (self._row_title(row) if row else
                     f"{item.inquiry_no} · {item.message.from_addr}")
            panel.show_row(title, self._row_info(row) if row else "", keys)
            self._label_delete(key)
            return
        if key == "arrived":
            index = self.arrived.currentRow()
            rows = self._sorted_mail or []
            if not 0 <= index < len(rows):
                panel.clear()
                self.reminder_btn.setText(i18n.t("Mark as reminder"))
                self.reminder_btn.setEnabled(False)
                return
            entry = rows[index]
            self._focus_row = None
            self._focus_key = ""
            category = entry.get("category", "")
            panel.show_row(
                f"{entry.get('from_name') or entry.get('from_addr', '')} · "
                f"{entry.get('subject', '')}",
                i18n.t("Sorted as {what} · {when}")
                .replace("{what}", i18n.t(CATEGORY_LABELS.get(category, category)))
                .replace("{when}", _dmy(entry.get("date", ""))),
                (), extra=True)
            self.reminder_btn.setEnabled(True)
            self.reminder_btn.setText(
                i18n.t("Remove reminder") if entry.get("reminder")
                else i18n.t("Mark as reminder"))
            return
        table, rows = {"to_quote": (self.to_quote_table, self._to_quote_rows),
                       "waiting": (self.followups, self._waiting_rows),
                       "register": (self.register_table, self._visible_rows)
                       }[key]
        index = table.currentRow()
        row = rows[index] if 0 <= index < len(rows) else None
        self._focus_row = row
        self._focus_key = row.get("Inquiry no", "") if row else ""
        self._focus_tab = key
        if row is None:
            panel.clear()
            return
        keys = actions_for(row.get("Status", ""), key, self._has_drawing(row))
        panel.show_row(self._row_title(row), self._row_info(row), keys)
        self._label_delete(key)
        remind = panel.buttons.get("remind")
        if remind is not None and "remind" in keys:
            settings = self._settings()
            sent = int((row.get("Reminders sent") or "0").strip() or 0)
            stop = sent >= int(settings.get("max_reminders", 3) or 3)
            remind.setEnabled(not stop)
            remind.setToolTip(i18n.t("Three reminders have gone. Call them.")
                              if stop else "")

    def _open_register(self):
        if not self._root():
            return
        path = self._paths().register_csv
        if os.path.exists(path):
            open_in_file_manager(path)
        else:
            open_in_file_manager(self._root())

    def _open_inquiry_folder(self):
        row = self._selected_row()
        if row:
            open_in_file_manager(row.get("Folder", "") or self._root())

    def _show_history(self):
        """The enquiry, every quotation and reminder sent, every reply, and
        how it closed — read back in one window instead of a trip to the
        file manager for history.txt. See core/history.py."""
        row = self._selected_row()
        if not row:
            return
        _HistoryDialog(row, row.get("Folder", ""), self).exec()

    # ── tab 1-6: open the mail behind the selected row ──────────────────
    def _open_mail(self, key: str):
        """The mail itself, in full — every table's double-click, the way
        the owner asked for it: "if I double click ... so that I can open
        the mail". `key` is the tab that fired it (see TABS)."""
        if key == "arrived":
            index = self.arrived.currentRow()
            rows = self._sorted_mail or []
            if not 0 <= index < len(rows):
                return
            self._show_mail(_StoredMessage(rows[index]))
            return
        if key == "replies":
            item = self._selected_reply()
            if item is None:
                return
            self._show_mail(item.message)
            return
        if key == "orders":
            item = self._selected_order()
            if item is None:
                return
            if not getattr(item, "message_id", ""):
                # _RegisterOnlyItem: accepted by hand, no PO mail behind it.
                QMessageBox.information(
                    self, i18n.t("No mail on file"),
                    i18n.t("This order was accepted by hand — there is no "
                           "PO mail behind it to open."))
                return
            self._show_mail(item.message)
            return
        # to_quote, waiting, register — the row is the register's own, not
        # a message; find the mail it came from in the arrived log.
        row = self._current_row()
        if row is None:
            return
        entry = self._arrived_for(row)
        if entry is None:
            QMessageBox.information(
                self, i18n.t("No mail on file"),
                i18n.t("Prism can't find the original mail for this "
                       "inquiry — it may have been entered by hand, or be "
                       "older than what Prism has kept."))
            return
        self._show_mail(_StoredMessage(entry))

    def _arrived_for(self, row: dict) -> dict | None:
        """The arrived-log entry a register row was built from, found by
        the same thread identifiers add_thread() already keeps on every
        row — so "open the mail" works from the register and the daily
        tabs, not only from All mail itself."""
        ids = {i for i in (row.get("Thread") or "").split() if i}
        folder = self._root()
        if not ids or not folder:
            return None
        data = CB.get_worklist().load(folder)
        for entry in CB.get_worklist().history(data, "arrived"):
            if (entry.get("message_id") or "") in ids:
                return entry
        return None

    def _show_mail(self, message) -> None:
        _ReadMailDialog(message, self).exec()

    def _show_attachments(self):
        row = self._selected_row()
        if not row:
            return
        _AttachmentsDialog(
            row, lambda path: self.attach_to_prism.emit(path), self).exec()

    def _mark_lost(self):
        row = self._selected_row()
        if not row:
            return
        reason, ok = _ask_reason(self)
        if not ok:
            return
        register = CB.get_register()
        register.mark_lost(row, reason)
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        CB.get_history().append(row.get("Folder") or self._root(),
                                i18n.t("Marked lost"), body=reason)
        self._refresh_register()

    def _picked_register_rows(self) -> list[dict]:
        """Every register row picked in the tab the current row came from,
        top to bottom — or just the current row. Several only count when
        the current row is one of them, so a stale selection left on
        another tab can never be what gets deleted."""
        row = self._current_row()
        if row is None:
            return []
        source = {"to_quote": (self.to_quote_table, "_to_quote_rows"),
                  "waiting": (self.followups, "_waiting_rows"),
                  "register": (self.register_table, "_visible_rows"),
                  }.get(getattr(self, "_focus_tab", ""))
        if source is None:
            return [row]
        table, attr = source
        rows = getattr(self, attr, None) or []
        # The table's selection is the one source for both the Delete
        # button's label and what it deletes. Ctrl-clicking the current row
        # off leaves it current but not picked; the label already said
        # "Delete 2", so those two are what goes (review F8).
        picked = [rows[i] for i in self._selected_indexes(table)
                  if 0 <= i < len(rows)]
        return picked or [row]

    @staticmethod
    def _selected_indexes(table) -> list[int]:
        model = table.selectionModel()
        if model is None:
            return []
        return sorted({index.row() for index in model.selectedRows()})

    def _picked_items(self, key: str) -> list:
        """The picked mails on "They answered" or "Order came", or the
        current one when nothing is picked."""
        table, items = ((self.replies_table, getattr(self, "_replies", []))
                        if key == "replies" else
                        (self.orders_table, getattr(self, "_orders", [])))
        picked = [items[i] for i in self._selected_indexes(table)
                  if 0 <= i < len(items)]
        if picked:
            return picked
        current = (self._selected_reply() if key == "replies"
                   else self._selected_order())
        return [current] if current is not None else []

    def _label_delete(self, key: str):
        """"Delete this inquiry" for one row, "Delete 3 inquiries" for a
        multi-row pick — the button says what it will do before it does
        it."""
        page = self._pages.get(key) if hasattr(self, "_pages") else None
        button = page.panel.buttons.get("delete") if page else None
        table = {"to_quote": getattr(self, "to_quote_table", None),
                 "waiting": getattr(self, "followups", None),
                 "register": getattr(self, "register_table", None),
                 "replies": getattr(self, "replies_table", None),
                 "orders": getattr(self, "orders_table", None)}.get(key)
        if button is None or table is None:
            return
        count = len(self._selected_indexes(table))
        if key in ("replies", "orders"):
            text = (i18n.t("Delete {n} from this list").replace("{n}", str(count))
                    if count > 1 else i18n.t("Delete from this list"))
        else:
            text = (i18n.t("Delete {n} inquiries").replace("{n}", str(count))
                    if count > 1 else i18n.t("Delete this inquiry"))
        if button.text() != text:
            button.setText(text)

    def _delete_inquiry(self):
        """Take a row out of the register — and, since the usual reason is
        a newsletter or a supplier that got itself registered, offer to stop
        that sender ever being treated as an inquiry again. The inquiry's
        folder on disk is left alone: deleting a line from a book is not
        the same as shredding the file.

        Several rows picked (ctrl/shift-click) go together: one question,
        one "block these senders?", one write of the register."""
        picked = self._picked_register_rows()
        if len(picked) > 1:
            self._delete_inquiries(picked)
            return
        row = picked[0] if picked else None
        if not row:
            return
        no = row.get("Inquiry no", "")
        who = row.get("Customer", "") or row.get("Email", "")
        with self._timer_held():
            answer = QMessageBox.question(
                self, i18n.t("Delete this inquiry"),
                i18n.t("Delete {no} ({who}) from the register?\n\nIts folder, "
                       "with the mail and any drawings, stays on disk.")
                .replace("{no}", no).replace("{who}", who),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            address = (row.get("Email") or "").strip().lower()
            block = False
            if address:
                block = QMessageBox.question(
                    self, i18n.t("Block this sender?"),
                    i18n.t("Also stop treating mail from {who} as inquiries?\n\n"
                           "Prism will file anything from that address as "
                           "\"Other\" from now on and never register it.")
                    .replace("{who}", address),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes
        gone = self._drop_rows(row)
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        if block:
            self._learn_sender(address, "other")
        self._focus_row = None
        self._focus_key = ""
        self._refresh_register()
        if not gone:
            self.status.setText(self._nothing_deleted())
            if block:
                self.status.setText(self.status.text() + " " + i18n.t(
                    "Mail from {who} will be filed as Other.").replace("{who}", address))
            return
        self.status.setText(
            i18n.t("{no} deleted. Mail from {who} will be filed as Other.")
            .replace("{no}", no).replace("{who}", address) if block
            else i18n.t("{no} deleted.").replace("{no}", no))

    @contextlib.contextmanager
    def _timer_held(self):
        """Hold the automatic check while a confirmation is open. A modal
        question runs its own event loop, so the timer and a finished
        check's refresh were delivered inside it and replaced the rows the
        owner was being asked about (review F7)."""
        timer = getattr(self, "_auto", None)
        running = timer is not None and timer.isActive()
        interval = timer.interval() if running else 0
        if running:
            timer.stop()
        try:
            yield
        finally:
            if running and not timer.isActive():
                timer.start(interval)

    def _drop_rows(self, rows) -> int:
        """Remove picked rows from the register this screen holds. A row
        still on screen goes by identity; one a refresh has replaced since
        it was picked is found by its key (Inquiry no, else Email + Date +
        Product), so the delete is not a silent no-op that still says
        "deleted". Returns how many actually went."""
        register = CB.get_register()
        picked = rows if isinstance(rows, list) else [rows]
        present = {id(r) for r in self._register_rows}
        ids = {id(r) for r in picked}
        # By key only for picks that are no longer on screen, and one row
        # per pick: two hand-kept rows sharing a number must not both go
        # when the owner was asked about one.
        wanted: dict = {}
        for r in picked:
            if id(r) not in present:
                for key in register.row_keys([r]):
                    wanted[key] = wanted.get(key, 0) + 1
        kept, gone = [], 0
        for r in self._register_rows:
            key = next(iter(register.row_keys([r])), None)
            if id(r) in ids:
                gone += 1
            elif key is not None and wanted.get(key, 0) > 0:
                wanted[key] -= 1
                gone += 1
            else:
                kept.append(r)
        self._register_rows = kept
        return gone

    @staticmethod
    def _nothing_deleted() -> str:
        return i18n.t("Nothing was deleted: the register changed while you "
                      "were deciding, and those inquiries were already gone.")

    def _delete_inquiries(self, rows: list[dict]):
        """_delete_inquiry() for a multi-row pick."""
        listed = "\n".join(
            f"  {r.get('Inquiry no', '')}  "
            f"{r.get('Customer', '') or r.get('Email', '')}" for r in rows[:12])
        if len(rows) > 12:
            listed += "\n  " + i18n.t("and {n} more").replace(
                "{n}", str(len(rows) - 12))
        with self._timer_held():
            answer = QMessageBox.question(
                self, i18n.t("Delete these inquiries"),
                i18n.t("Delete these {n} inquiries from the register?")
                .replace("{n}", str(len(rows))) + "\n\n" + listed + "\n\n" +
                i18n.t("Their folders, with the mail and any drawings, stay on "
                       "disk."),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
            addresses = sorted({(r.get("Email") or "").strip().lower()
                                for r in rows} - {""})
            block = False
            if addresses:
                block = QMessageBox.question(
                    self, i18n.t("Block these senders?"),
                    i18n.t("Also stop treating mail from these addresses as "
                           "inquiries?") + "\n\n" + "\n".join(
                               f"  {a}" for a in addresses[:12]) + "\n\n" +
                    i18n.t("Prism will file anything from them as \"Other\" from "
                           "now on and never register it."),
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes
        gone = self._drop_rows(list(rows))
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        if block:
            self._learn_senders(addresses, "other")
        self._focus_row = None
        self._focus_key = ""
        self._refresh_register()
        # The count is what actually left the file, not what was picked.
        done = (i18n.t("{n} inquiries deleted.").replace("{n}", str(gone))
                if gone else self._nothing_deleted())
        if block:
            done += " " + i18n.t("Mail from those senders will be filed as "
                                 "Other.")
        self.status.setText(done)

    def _delete_from_list(self, key: str, *, items=None):
        """Delete on "They answered" and "Order came": the picked mails
        leave that list. The inquiries they belong to stay in the register
        exactly as they are — that is what the other tabs' Delete is for.
        A row on "Order came" that is there because it was accepted by
        hand has no mail behind it and cannot be taken off this way."""
        items = items if items is not None else self._picked_items(key)
        mails = [i for i in items if getattr(i, "message_id", "")]
        skipped = len(items) - len(mails)
        if not mails:
            if skipped:
                self.status.setText(i18n.t(
                    "That row is here because the customer said yes, not "
                    "because of a mail. Record the PO or mark it lost."))
            return
        tab = i18n.t("They answered") if key == "replies" else i18n.t("Order came")
        question = (i18n.t("Take this mail off \"{tab}\"?") if len(mails) == 1
                    else i18n.t("Take these {n} mails off \"{tab}\"?")
                    .replace("{n}", str(len(mails))))
        with self._timer_held():
            answer = QMessageBox.question(
                self, i18n.t("Delete from this list"),
                question.replace("{tab}", tab) + "\n\n" +
                i18n.t("The inquiries stay in the register, and nothing on "
                       "disk is touched."),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        folder = self._root()
        if folder:
            try:
                CB.get_worklist().resolve_many(
                    folder, "replies" if key == "replies" else "orders",
                    [i.message_id for i in mails])
            except OSError:
                # Windows: the list file held open by a virus scanner, a
                # sync client or a second Prism. Nothing was changed.
                self._explain(i18n.t(
                    "Prism couldn't update this list because another program "
                    "has its file open. Nothing was taken off. Try again in "
                    "a moment."))
                return
        if key == "replies":
            self._render_replies()
        else:
            self._render_orders()
        done = i18n.t("{n} taken off the list.").replace("{n}", str(len(mails)))
        if skipped:
            done += " " + i18n.t(
                "{n} accepted by hand stayed: they come from the register, "
                "not from a mail.").replace("{n}", str(skipped))
        self.status.setText(done)
    def _open_arrived(self):
        """The full mail, in its own closeable window — double-click a row,
        or press "Open mail"."""
        index = self.arrived.currentRow()
        rows = self._sorted_mail or []
        if not 0 <= index < len(rows):
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Pick a mail from the list first."))
            return
        _ArrivedMailDialog(rows[index], self).exec()

    def _toggle_reminder(self):
        """A flag, nothing more — no due date, no separate list. The
        point is not losing track of a mail that doesn't need to become
        a full inquiry, same as the register's own flags work."""
        index = self.arrived.currentRow()
        rows = self._sorted_mail or []
        if not 0 <= index < len(rows):
            return
        entry = rows[index]
        flagged = not entry.get("reminder")
        entry["reminder"] = flagged
        if entry.get("message_id"):
            CB.get_worklist().update(
                self._root(), "arrived", entry["message_id"],
                {"reminder": flagged})
        flag_item = QTableWidgetItem(i18n.t("Reminder") if flagged else "")
        if flagged:
            flag_item.setBackground(QColor(_WARN[0]))
            flag_item.setForeground(QColor(_WARN[1]))
        self.arrived.setItem(index, 7, flag_item)
        self.reminder_btn.setText(
            i18n.t("Remove reminder") if flagged
            else i18n.t("Mark as reminder"))
        self.status.setText(
            i18n.t("Marked as a reminder.") if flagged
            else i18n.t("Reminder removed."))

    def _delete_arrived(self):
        """Take one or more rows out of the All-mail log for good. Unlike
        _delete_inquiry(), there is no register row behind this and
        nothing on disk to leave alone — this log IS the record, so the
        entries themselves are what gets removed."""
        indices = sorted({i.row() for i in self.arrived.selectionModel()
                          .selectedRows()})
        rows = self._sorted_mail or []
        entries = [rows[i] for i in indices if 0 <= i < len(rows)]
        if not entries:
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Pick one or more mails from the list first."))
            return
        answer = QMessageBox.question(
            self, i18n.t("Delete these mails"),
            i18n.t("Delete {n} mail(s) from this log? This cannot be "
                   "undone.").replace("{n}", str(len(entries))),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        worklist = CB.get_worklist()
        folder = self._root()
        keys = [worklist.entry_key(e) for e in entries]
        if folder:
            worklist.remove(folder, "arrived", keys)
        self._render_arrived()
        self.status.setText(
            i18n.t("{n} mail(s) deleted.").replace("{n}", str(len(entries))))

    def _reset_everything(self):
        """A full "start over" for this mailbox — not a tab's rows, the
        whole thing. Clears the register and every worklist log, and
        rewinds each account's read bookmark to zero so the next check
        re-reads every mailbox from the start. Nothing on disk is deleted
        — same principle as _delete_inquiry(): a drawing, quotation or PO
        that was already saved into an inquiry's folder stays exactly
        where it is; only Prism's own bookkeeping of what it has seen is
        cleared."""
        folder = self._root()
        if not folder:
            return
        answer = QMessageBox.question(
            self, i18n.t("Reset everything"),
            i18n.t("This clears the whole register and every mail log, and "
                   "makes Prism re-read every mailbox from the start. "
                   "Nothing already saved to disk is deleted. This cannot "
                   "be undone. Continue?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        register = CB.get_register()
        worklist = CB.get_worklist()
        register.save([], self._paths().register_csv)
        for kind in worklist.KINDS:
            worklist.clear(folder, kind)
        state = CB.get_inbox().State()
        settings = self._settings()
        accounts = accounts_of(self.cfg)
        for account in accounts:
            account["state"] = state.to_dict()
        settings["accounts"] = accounts
        first = accounts[0] if accounts else {}
        settings["account"] = {k: v for k, v in first.items() if k != "state"}
        settings["state"] = dict(first.get("state") or {})
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)
        self._refresh_register()
        self._render_arrived()
        self._render_replies()
        self._render_orders()
        self.status.setText(i18n.t("Everything has been reset."))

    def _learn_sender(self, address: str, category: str):
        """Remember a sender's category — the same knowledge the sorter's
        rules read first, so that address never goes to an AI again."""
        self._learn_senders([address], category)

    def _learn_senders(self, addresses, category: str):
        """_learn_sender() for several addresses, saved once."""
        settings = self._settings()
        knowledge = settings.get("knowledge") or {}
        learned = dict(knowledge.get("learned") or {})
        for address in addresses:
            learned[address] = category
        knowledge["learned"] = learned
        settings["knowledge"] = knowledge
        self.cfg["inquiry"] = settings
        CB.config.save(self.cfg)

    def _phone_reply(self):
        """"They replied by phone…" — the register moves exactly as it would
        for a reply by mail, without one."""
        row = self._selected_row()
        if not row:
            return
        dialog = _PhoneReplyDialog(row, self)
        if dialog.exec() != QDialog.Accepted:
            return
        register = CB.get_register()
        intent, note = dialog.intent(), dialog.note()
        if intent == "rejected":
            detail = note or i18n.t("Declined by phone")
            register.mark_lost(row, detail)
            event = i18n.t("Marked lost — by phone")
        else:
            register.mark_reply(row, intent)
            if note:
                row["Notes"] = (row.get("Notes", "") + " " + note).strip()
            detail = note or i18n.t("Customer responded: {intent}").replace(
                "{intent}", intent)
            event = i18n.t("Reply received — by phone")
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        CB.get_history().append(row.get("Folder") or self._root(), event,
                                body=detail)
        self._refresh_register()
        self.status.setText(
            i18n.t("{no} is now {status}.")
            .replace("{no}", row.get("Inquiry no", ""))
            .replace("{status}", i18n.t(row.get("Status", ""))))

    def _record_po_by_hand(self):
        """The PO came on paper, or the customer said yes on the phone —
        the same review sheet, with nothing pre-filled."""
        row = self._selected_row()
        if not row:
            return
        self._po_row = row
        self._po_item = None
        self._show_po(None, row, advice=i18n.t(
            "Type the PO number, date and value from the printed order."))

    def _remove_order(self, *, item=None):
        """A mail Prism took for a purchase order and was not one."""
        item = item or self._selected_order()
        if item is None:
            return
        if item.message_id and self._root():
            CB.get_worklist().resolve(self._root(), "orders", item.message_id)
        self._render_orders()

    def _mark_already_quoted(self):
        """Log a quotation made outside Prism — a phone call, a counter
        sale, or one written before this inquiry ever reached this screen.
        Reuses the same "Quoted" status a real pricing run would set, so it
        gets the same colour and the same follow-up chasing — the only
        difference is that nothing was priced or sent through Prism itself."""
        row = self._selected_row()
        if not row:
            return
        quote_no, value, ok = _ask_already_quoted(self, row)
        if not ok:
            return
        register = CB.get_register()
        register.mark_quoted(row, quote_no, value)
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        CB.get_history().append(
            row.get("Folder") or self._root(),
            i18n.t("Quoted outside Prism — recorded by hand"),
            body=i18n.t("Quotation {no}, value ₹{value}.")
                .replace("{no}", quote_no).replace("{value}", str(value)))
        self._refresh_register()
        self.status.setText(i18n.t(
            "Marked as quoted. Prism will remind you if there is no reply."))

    def _export_register_xlsx(self):
        """[3] The register as an .xlsx, for the owner and for a client
        sheet. The CSV stays the book Prism reads; this is a copy."""
        if not self._root():
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Set up a mailbox and a folder first."))
            return
        suggested = Path(self._root()) / documents.safe_name(
            i18n.t("Inquiry register {date}").replace(
                "{date}", date.today().strftime("%d-%m-%Y")) + ".xlsx")
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save the register as Excel"), str(suggested),
            "Excel (*.xlsx)")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            written = documents.register_xlsx(self._rows(), path)
        except PermissionError:
            self._explain(i18n.t(
                "That file is open in another program. Close it in Excel "
                "and try again."))
            return
        except Exception as e:                          # noqa: BLE001
            self._explain(str(e))
            return
        self.status.setText(i18n.t("Saved {name}.").replace(
            "{name}", Path(written).name))

    def _import_csv_into_register(self):
        """Bring in a register the owner already kept before Prism, or one a
        colleague built up separately — appended, not swapped in, and
        nothing already here is touched. See register.merge_in() for how a
        row already present is recognised and skipped."""
        if not self._root():
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Set up a mailbox and a folder first."))
            return
        import paths
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose the CSV you already kept"),
            paths.picker_start_dir(), "CSV (*.csv)")
        if not path:
            return
        register = CB.get_register()
        try:
            incoming = register.load(path)
        except Exception as e:
            self._explain(str(e))
            return
        if not incoming:
            QMessageBox.information(
                self, i18n.t("Import"),
                i18n.t("That file has no rows in it."))
            return
        merged, added, skipped = register.merge_in(self._register_rows,
                                                    incoming)
        try:
            self._save_register(merged)
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()
        message = i18n.t("Added {n} row(s) to the register.").replace(
            "{n}", str(added))
        if skipped:
            message += " " + i18n.t(
                "{n} looked like ones already in the register, so they "
                "were left out.").replace("{n}", str(skipped))
        QMessageBox.information(self, i18n.t("Import"), message)

    # ── chasing a quiet quotation ─────────────────────────────────────────
    def _send_reminder(self):
        """One polite nudge, shown before it goes.

        Deliberately one at a time and never on the timer. A reminder is Prism
        writing to somebody else's customer in their name, and a loop that
        chases the whole list unattended is one bad afternoon away from
        mailing the same buyer three times.
        """
        row = self._current_row()
        if row is None:
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("Pick a quotation from the list first."))
            return
        address = row.get("Email", "")
        if not address:
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("This inquiry has no email address to write to."))
            return
        if not email_config.can_send(self.cfg):
            QMessageBox.information(
                self, i18n.t("Reminder"),
                i18n.t("Sending needs your outgoing account set up — open the "
                       "Email spamming add-on once and enter it."))
            return

        settings = self._settings()
        subject = (i18n.t("Reminder: our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        body = (i18n.t(
            "Dear Sir,\n\nWe sent you our quotation {no} on {when} and have "
            "not yet heard back. Please let us know if you need anything "
            "clarified, or if the requirement has changed.\n\n"
            "Regards,\n{signature}")
            .replace("{no}", row.get("Quotation no", ""))
            .replace("{when}", row.get("Quotation date", ""))
            .replace("{signature}", settings.get("signature", "")
                     or settings.get("company", "")))

        draft = _ReminderDialog(subject, body, address, self, cfg=self.cfg)
        if draft.exec() != QDialog.Accepted:
            return

        self.remind_btn.setEnabled(False)
        self.status.setText(i18n.t("Sending the reminder…"))
        self._send_worker = SendWorker(
            email_config.cfg_for_sender(self.cfg, draft.sender()),
            [{"email": address, "name": row.get("Contact person", "")}],
            draft.subject(), draft.message(), [])
        self._send_worker.done.connect(
            lambda sent, failed, s=draft.subject(), b=draft.message():
            self._reminder_sent(row, sent, failed, subject=s, body=b))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _reminder_sent(self, row: dict, sent: list, failed: list,
                       subject: str = "", body: str = ""):
        self.remind_btn.setEnabled(True)
        self.status.setText("")
        if failed:
            self._explain(failed[0][1])
            return
        register = CB.get_register()
        # Count it against the row in the loaded register, not the copy the
        # list is holding, so the increment survives the save.
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        register.note_reminder(target)
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        self._log_sent("reminder", row, subject or
                       self._reminder_words(row)[0], body=body)
        self._refresh_register()
        self.status.setText(
            i18n.t("Reminder sent to {who}.").replace(
                "{who}", row.get("Email", "")))

    _SENT_EVENTS = {
        "quotation": "Quotation sent",
        "revised": "Revised quotation sent",
        "reminder": "Reminder sent",
        "winback": "Win-back mail sent",
    }

    def _log_sent(self, kind: str, row: dict, subject: str, body: str = ""):
        """Write one line to worklist/sent.json — the readable history the
        "Sent so far" line and the reminder column are drawn from — and, with
        the actual mail text, one entry to this inquiry's own history.txt.
        The register's own "Reminders sent" count stays the engine's
        schedule; this is written in the same breath so the two cannot
        disagree. A failure here must never undo a send that already
        happened, so it is swallowed rather than raised."""
        folder = self._root()
        if folder:
            try:
                CB.get_worklist().log_sent(
                    folder, kind, to=row.get("Email", ""), subject=subject,
                    inquiry_no=row.get("Inquiry no", ""),
                    quotation_no=row.get("Quotation no", ""))
            except Exception:           # noqa: BLE001 — see docstring
                pass
        inquiry_folder = row.get("Folder") or folder
        if inquiry_folder and body:
            CB.get_history().append(
                inquiry_folder, i18n.t(self._SENT_EVENTS.get(kind, "Mail sent")),
                who=row.get("Email", ""), subject=subject, body=body)

    def _reminder_failed(self, message: str):
        self.remind_btn.setEnabled(True)
        self.status.setText("")
        self._explain(message)

    # ── chasing without being asked ───────────────────────────────────────
    def _chase_automatically(self):
        """Send the reminders that are due, one per check, unattended.

        Everything about this is deliberately conservative, because these are
        letters going out in somebody else's name to their own customers:

          · **One per check, never a batch.** Three reminders leaving in the
            same second, to three customers who talk to each other, reads as a
            machine. Spread over the day's checks, it reads as a person
            working through a list.
          · **The register is the schedule.** Who is due comes from Reminders
            sent and Last contact in the CSV — the same two columns the owner
            can see and edit. There is no second, hidden queue to get out of
            step with it.
          · **Counted only when the send succeeds**, or Prism gives up after
            three reminders that never left the building.
          · **Off unless they turned it on.**
        """
        settings = self._settings()
        if not settings.get("auto_followup"):
            return
        if self._send_worker is not None and self._send_worker.isRunning():
            return
        if not email_config.can_send(self.cfg):
            return
        due = [r for r in getattr(self, "_followup_rows", []) if r.get("Email")]
        if not due:
            return

        row = due[0]
        subject, body = self._reminder_words(row)
        self.status.setText(
            i18n.t("Sending a reminder to {who}…").replace(
                "{who}", row.get("Email", "")))
        # No draft screen to choose on, so the default account sends --
        # which is the whole point of there being a default.
        self._send_worker = SendWorker(
            email_config.cfg_for_sender(
                self.cfg, email_config.default_sender(self.cfg)),
            [{"email": row.get("Email", ""),
              "name": row.get("Contact person", "")}],
            subject, body, [])
        self._send_worker.done.connect(
            lambda sent, failed, s=subject:
            self._reminder_sent(row, sent, failed, subject=s))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _reminder_words(self, row: dict) -> tuple[str, str]:
        """Subject and body for the next reminder on this row.

        The attempt number changes the wording. Three identical nudges in six
        days is not persistence, it is a mail merge, and the customer can
        tell — so the first is a light touch and the third asks straight out
        whether to close the file.
        """
        settings = self._settings()
        try:
            sent = int(str(row.get("Reminders sent") or "0").strip() or 0)
        except ValueError:
            sent = 0
        attempt = sent + 1
        signature = settings.get("signature", "") or settings.get("company", "")
        subject = (i18n.t("Reminder: our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        openers = {
            1: i18n.t("We sent you our quotation {no} on {when}. Just making "
                      "sure it reached you."),
            2: i18n.t("Following up on our quotation {no} of {when}. If any "
                      "part of it does not suit, we are glad to revise it."),
            3: i18n.t("This is our last note about quotation {no} of {when}. "
                      "Would you like us to keep this enquiry open, or close "
                      "it for now? Either is perfectly all right."),
        }
        opener = openers.get(attempt, openers[3])
        body = (i18n.t("Dear Sir,\n\n{opener}\n\nRegards,\n{signature}")
                .replace("{opener}", opener
                         .replace("{no}", row.get("Quotation no", ""))
                         .replace("{when}", row.get("Quotation date", "")))
                .replace("{signature}", signature))
        return subject, body

    # ── winning back a customer who said no ───────────────────────────────
    def _win_back(self):
        """Draft a reply to a decline or a haggle, using the browser tools.

        This one email is worth the wait. It has to know what was quoted, what
        they objected to, and exactly how far this owner will move — and it is
        read out loud by somebody before it goes. That is a completely
        different job from labelling an inbox, and it goes to the best writer
        available rather than the fastest one.
        """
        row = self._selected_row()
        if not row:
            return
        settings = self._settings()
        status = (row.get("Status") or "").strip()
        register = CB.get_register()
        if status not in (register.NOT_CONVERTED, register.NEGOTIATING,
                          register.QUOTED, register.FOLLOWING_UP):
            QMessageBox.information(
                self, i18n.t("Win this back"),
                i18n.t("There is nothing to win back yet — this one has not "
                       "been quoted and turned down."))
            return

        drafting = CB.get_drafting()
        ready, why = drafting.available(self.cfg)
        if not ready:
            self._explain(why)
            return

        policy_path = settings.get("pricing_policy", "")
        policy_text, policy_files = drafting.load_policy(policy_path)
        if not policy_text and not policy_files:
            if QMessageBox.question(
                    self, i18n.t("Win this back"),
                    i18n.t("You have not given Prism your bargaining limits, "
                           "so it will not offer any discount at all — it will "
                           "argue on quality, delivery and service only.\n\n"
                           "Add the file under Setup → Files to let it "
                           "negotiate on price. Carry on without it?"),
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes) != QMessageBox.Yes:
                return

        prompt = drafting.negotiation_prompt(
            quotation_text=self._quotation_text(row),
            customer_reply=self._last_reply_text(row),
            policy_text=policy_text,
            customer_name=row.get("Customer", "") or row.get("Email", ""),
            product=row.get("Product asked", ""),
            signature=settings.get("signature", "") or settings.get("company", ""),
            language=self.cfg.get("output_language", "") or "")

        self._draft_row = row
        self.progress.setVisible(True)
        self.status.setText(i18n.t(
            "Writing it in your browser — this takes a minute or two. Chrome "
            "will open by itself; leave it alone until it finishes."))
        self._draft_worker = DraftWorker(self.cfg, prompt, purpose="negotiate",
                                         attachments=policy_files)
        self._draft_worker.progress.connect(self.status.setText)
        self._draft_worker.done.connect(self._drafted)
        self._draft_worker.failed.connect(self._draft_failed)
        self._draft_worker.start()

    def _quotation_text(self, row: dict) -> str:
        """What we actually sent them, read back off the disk.

        The quotation CSV written at send time is the only record of the
        figures as the customer saw them; rebuilding it from today's rate list
        could quote them something different from what they are holding.
        """
        folder = row.get("Folder", "")
        number = (row.get("Quotation no", "") or "").replace("/", "-")
        if folder and number:
            path = os.path.join(folder, f"{number}.csv")
            if os.path.exists(path):
                try:
                    with open(path, "r", encoding="utf-8-sig") as f:
                        return f.read()[:6000]
                except OSError:
                    pass
        return (i18n.t("Quotation {no} dated {when}, value Rs.{value}")
                .replace("{no}", row.get("Quotation no", ""))
                .replace("{when}", row.get("Quotation date", ""))
                .replace("{value}", row.get("Quotation value", "")))

    def _winback_body(self, row: dict, reply: str) -> str:
        """The letter, cleaned of anything the page scrape dragged along,
        with our quotation repeated underneath exactly as it was sent — the
        customer is deciding against a piece of paper, and this puts that
        paper back in front of them."""
        drafting = CB.get_drafting()
        clean = getattr(drafting, "clean_reply", lambda t: t)(reply or "")
        quotation = self._quotation_as_sent(row)
        if not quotation:
            return clean
        return (clean.rstrip() + "\n\n" + "-" * 40 + "\n"
                + i18n.t("Our quotation, as sent") + "\n" + quotation)

    def _quotation_as_sent(self, row: dict) -> str:
        """The quotation the customer is holding, as readable lines, from the
        CSV written when it went out. Empty when there is none on disk."""
        folder = row.get("Folder", "")
        number = (row.get("Quotation no", "") or "").replace("/", "-")
        if not folder or not number:
            return ""
        path = os.path.join(folder, f"{number}.csv")
        if not os.path.exists(path):
            return ""
        quoting = CB.get_quoting()
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except OSError:
            return ""
        head: dict[str, str] = {}
        items: list[str] = []
        totals: list[str] = []
        in_items = False
        for cells in rows:
            if not any(c.strip() for c in cells):
                continue
            if cells[0] == "Sr":
                in_items = True
                continue
            if not in_items and len(cells) >= 2:
                head[cells[0]] = cells[1]
                continue
            if in_items and cells[0].strip().isdigit() and len(cells) >= 7:
                try:
                    rate = quoting.indian_currency(quoting.to_decimal(cells[5]))
                    amount = quoting.indian_currency(quoting.to_decimal(cells[6]))
                except Exception:                           # noqa: BLE001
                    rate, amount = cells[5], cells[6]
                items.append(f"  {cells[0]}. {cells[1]} — {cells[3]} {cells[4]} "
                             f"x Rs.{rate} = Rs.{amount}")
            elif in_items and len(cells) >= 7 and cells[5].strip():
                try:
                    value = quoting.indian_currency(
                        quoting.to_decimal(cells[6].lstrip("-")))
                    value = ("-" if cells[6].startswith("-") else "") + value
                except Exception:                           # noqa: BLE001
                    value = cells[6]
                totals.append(f"{cells[5]}: Rs.{value}")
        if not items and not head:
            return ""
        lines = [f"Quotation {head.get('Quotation no', row.get('Quotation no', ''))}"
                 f" dated {head.get('Date', row.get('Quotation date', ''))}"]
        if head.get("Inquiry no"):
            lines[0] += f" (against your inquiry {head['Inquiry no']})"
        lines += items
        if totals:
            lines.append("  " + " · ".join(totals))
        return "\n".join(lines)

    def _last_reply_text(self, row: dict) -> str:
        """Their own words, from this check if we have them.

        Falls back to the reason recorded when the row was closed. Thin, but
        an honest "they said the rate was too high" beats inventing an
        objection for the tool to answer.
        """
        for item in getattr(self, "_replies", []):
            if (item.row or {}).get("Inquiry no") == row.get("Inquiry no"):
                message = item.message
                if hasattr(message, "snippet"):
                    return message.snippet(2000)
        reason = row.get("Reason if lost", "") or row.get("Notes", "")
        return reason or i18n.t("(they have not said why)")

    def _drafted(self, result):
        self.progress.setVisible(False)
        self.status.setText("")
        if result.error:
            self._explain(result.error)
            return
        if not result.ok:
            self._explain(i18n.t(
                "The AI tool did not answer. Its tab is still open in Chrome "
                "— the reply may have arrived after Prism stopped waiting."))
            return
        row = getattr(self, "_draft_row", None) or {}
        subject = (i18n.t("Regarding our quotation {no}")
                   .replace("{no}", row.get("Quotation no", "")))
        dialog = _ReminderDialog(subject, self._winback_body(row, result.text),
                                 row.get("Email", ""),
                                 self, note=i18n.t(
                                     "Written by {agent}. Read it before it "
                                     "goes — it is your name on it.")
                                 .replace("{agent}", result.agent),
                                 cfg=self.cfg)
        if dialog.exec() != QDialog.Accepted:
            return
        if not email_config.can_send(self.cfg):
            QMessageBox.information(
                self, i18n.t("Win this back"),
                i18n.t("Sending needs your outgoing account set up — open the "
                       "Email spamming add-on once and enter it."))
            return
        self._send_worker = SendWorker(
            email_config.cfg_for_sender(self.cfg, dialog.sender()),
            [{"email": row.get("Email", ""),
              "name": row.get("Contact person", "")}],
            dialog.subject(), dialog.message(), [])
        self._send_worker.done.connect(
            lambda sent, failed, s=dialog.subject(), b=dialog.message():
            self._winback_sent(row, sent, failed, subject=s, body=b))
        self._send_worker.failed.connect(self._reminder_failed)
        self._send_worker.start()

    def _winback_sent(self, row: dict, sent: list, failed: list,
                      subject: str = "", body: str = ""):
        if failed:
            self._explain(failed[0][1])
            return
        register = CB.get_register()
        target = register.find(self._register_rows,
                               row.get("Inquiry no", "")) or row
        # Reopened. A row we are actively arguing with is not a lost one, and
        # leaving it closed would drop it off every list Prism keeps.
        target["Status"] = register.NEGOTIATING
        target["Result"] = ""
        target["Last contact"] = date.today().strftime("%d-%m-%Y")
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        self._log_sent("winback", row, subject, body=body)
        self._refresh_register()
        self.status.setText(i18n.t("Sent. This inquiry is open again."))

    def _draft_failed(self, message: str):
        self.progress.setVisible(False)
        self.status.setText("")
        self._explain(message)

    # ── correcting the register by hand ───────────────────────────────────
    def _edit_row(self):
        """Let the owner fix what Prism got wrong, in Prism.

        They can always edit the CSV in Excel — it is their file. But an
        register that can only be corrected by closing the app, opening Excel
        and remembering to close it again is one they will stop correcting.
        """
        row = self._selected_row()
        if not row:
            return
        dialog = _EditRowDialog(row, self)
        if dialog.exec() != QDialog.Accepted:
            return
        row.update(dialog.changes())
        register = CB.get_register()
        try:
            self._save_register()
        except Exception as e:
            self._explain(str(e))
            return
        self._refresh_register()

    def _make_boq(self):
        """Hand this inquiry's drawings to the BOQ add-on.

        The join the customer asked for: the drawing already arrived with the
        inquiry and is already filed, so making the quantities out of it should
        not involve finding the file again.
        """
        row = self._selected_row()
        if not row:
            return
        folder = row.get("Folder", "")
        drawings = []
        if folder and os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                if (name.lower().endswith((".dwg", ".dxf", ".pdf"))
                        and not documents.is_ours(name)):
                    drawings.append(os.path.join(folder, name))
        if not drawings:
            QMessageBox.information(
                self, i18n.t("BOQ"),
                i18n.t("There is no drawing filed against this inquiry. BOQ "
                       "also works from a written specification — open it from "
                       "the sidebar and describe the job instead."))
            return
        # Hand the drawings to whoever measures drawings, by INTENT rather
        # than by import. This used to construct BoqDialog directly, which
        # meant Inquiry knew BOQ's module, its class, its constructor and --
        # the subtle one -- that an "attachment" is whatever
        # CB.get_files().attach() returns. That last is BOQ's own data
        # shaping, done here, in somebody else's file.
        #
        # Now Inquiry hands over plain paths. If nothing offers the intent
        # (not built, not installed) the handler is simply absent and this
        # returns, rather than opening something that cannot work.
        owner, handler = registry.offering(names.MEASURE_DRAWING)
        if owner is None:
            return
        registry.resolve(handler)(self, self.cfg, drawings)

    # ── preparing a quotation ─────────────────────────────────────────────
    def _prepare_quotation(self):
        row = self._selected_row()
        if not row:
            return
        settings = self._settings()
        quoting = CB.get_quoting()

        # Either source will do. A shop that sells from a catalogue has a rate
        # list; a shop that quotes made-to-drawing work has a cost sheet of
        # their own formulas; plenty have both and pick per job. Demanding the
        # rate list, as this once did, locked out the second kind entirely.
        rate_path = settings.get("rate_list", "")
        cost_path = settings.get("cost_sheet", "")
        items, cost_lines, problems = [], [], []

        if rate_path and os.path.exists(rate_path):
            try:
                items = quoting.load_rates(rate_path)
            except Exception as e:
                problems.append(str(e))
        if cost_path and os.path.exists(cost_path):
            try:
                cost_lines = quoting.load_cost_lines(cost_path)
            except Exception as e:
                problems.append(str(e))

        if not items and not cost_lines:
            self._explain("\n\n".join(problems) if problems else i18n.t(
                "Prism needs either your rate list or your cost sheet before "
                "it can price anything. Add one under Setup → Files."))
            return

        dialog = QuotationDialog(self.cfg, row, items, self,
                                 cost_lines=cost_lines)
        if dialog.exec() == QDialog.Accepted:
            self._refresh_register()


def _ask_reason(parent) -> tuple[str, bool]:
    """Why the inquiry was lost. Four choices, because a free-text box gets
    left empty and three months later the report says nothing."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(i18n.t("Not converted"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(i18n.t("Why did this one not convert?")))
    picker = QComboBox()
    for reason in ("Rate too high", "Delivery time", "No reply",
                   "Went to a competitor", "Customer's project dropped"):
        picker.addItem(i18n.t(reason), reason)
    picker.setEditable(True)
    layout.addWidget(picker)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    ok = dialog.exec() == QDialog.Accepted
    return picker.currentText().strip(), ok


def _ask_already_quoted(parent, row: dict) -> tuple[str, str, bool]:
    """Both fields optional — an owner who just wants the chase to stop
    should not be blocked on a quotation number they may never have
    written down."""
    dialog = QDialog(parent)
    dialog.setWindowTitle(i18n.t("Mark as already quoted"))
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(i18n.t(
        "For {who} — logs it as quoted, without opening the pricing "
        "screen.").replace(
        "{who}", row.get("Customer", "") or row.get("Email", ""))))
    form = QFormLayout()
    number = QLineEdit()
    number.setPlaceholderText(i18n.t("optional"))
    form.addRow(i18n.t("Quotation no:"), number)
    value = QLineEdit()
    value.setPlaceholderText(i18n.t("optional"))
    form.addRow(i18n.t("Value:"), value)
    layout.addLayout(form)
    buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    ok = dialog.exec() == QDialog.Accepted
    return number.text().strip(), value.text().strip(), ok


class _ReminderDialog(PrismDialog):
    """The reminder, shown before it goes. Editable, because the right words
    for a customer of fifteen years are not the right words for a new one."""

    def __init__(self, subject: str, body: str, address: str, parent=None,
                 note: str = "", cfg: dict | None = None):
        super().__init__(
            i18n.t("Send a reminder"),
            i18n.t("Prism wrote this. Edit anything before it goes."),
            icon="mail", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Send a reminder"))
        self.resize(620, 480)
        layout = self.body
        layout.setSpacing(theme.ROW_GAP)
        layout.addWidget(QLabel(
            i18n.t("To: {who}").replace("{who}", address)))
        # Which address it goes out from. A chaser for money and a chaser
        # for a quotation are often not the same mailbox, and this is the
        # last moment anybody can say so. Offered only when there is a
        # choice; with one sending account the screen is unchanged.
        self._senders = email_config.active_senders(cfg or {})
        self._from_box = QComboBox()
        for account in self._senders:
            self._from_box.addItem(
                i18n.t("From: {who}").replace(
                    "{who}", account.get("address", "")))
        if len(self._senders) > 1:
            layout.addWidget(self._from_box)
        if note:
            caption = QLabel(note)
            caption.setWordWrap(True)
            caption.setObjectName("meta")
            layout.addWidget(caption)
        self._subject = QLineEdit(subject)
        layout.addWidget(self._subject)
        self._body = C.PlainPasteTextEdit(body)
        layout.addWidget(self._body, stretch=1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Send it"), "primary", icon_name="mail",
                        on_click=self.accept))

    def sender(self) -> dict:
        """The account picked, or {} -- which `cfg_for_sender()` reads as
        "change nothing", so the no-choice case sends exactly what it did
        before this screen grew a chooser."""
        index = self._from_box.currentIndex()
        if 0 <= index < len(self._senders):
            return self._senders[index]
        return {}

    def subject(self) -> str:
        return self._subject.text().strip()

    def message(self) -> str:
        """The reminder text. Named `message`, not `body`, because
        PrismDialog puts the dialog's content layout on `self.body` and an
        instance attribute shadows a method of the same name — `draft.body()`
        would have tried to call a QVBoxLayout."""
        return self._body.toPlainText()


def _read_sent_quotation(row: dict):
    """The quotation actually sent, rebuilt from the CSV written at send time.

    That CSV is the only record of the figures as the customer saw them —
    rebuilding from today's rate list could compare their PO against a price
    they were never quoted. This mirrors quoting.write_csv column for column
    (a reader belongs beside that writer in the engine eventually; until the
    engine grows one, it lives here where its only caller is).

    The reconstruction is checked against the file's own Total row and
    refused on any mismatch: comparing a PO against a misparsed quotation
    would flag differences the customer never made, and a confidently wrong
    comparison is worse than saying there is none.
    """
    quoting = CB.get_quoting()
    register = CB.get_register()
    folder = row.get("Folder", "")
    number = (row.get("Quotation no", "") or "").strip()
    if not folder or not number:
        return None
    # The LATEST revision the customer holds (review R5): Rev n's CSV when
    # there is one, else the first copy. A PO matching Rev 1 checked against
    # Rev 0 flags every line as a price difference.
    latest = max(register.revision_of(row),
                 register.revision_on_disk(folder, number))
    path = ""
    for n in range(latest, -1, -1):
        candidate = os.path.join(folder, register.quote_file_name(number, n, "csv"))
        if os.path.exists(candidate):
            path = candidate
            break
    if not path:
        return None
    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            records = list(csv.reader(f))
    except OSError:
        return None

    head: dict = {}
    lines = []
    gst = None
    freight = Decimal(0)
    discount = Decimal(0)
    total = None
    section = "head"
    try:
        for record in records:
            cells = [c.strip() for c in record]
            if not any(cells):
                continue
            first = cells[0]
            if section == "head":
                if first == "Sr":
                    section = "lines"
                elif len(cells) >= 2:
                    head[first] = cells[1]
                continue
            if first:
                # A numbered line: Sr, Description, HSN, Qty, Unit, Rate,
                # Amount, Rate source — the order write_csv puts them in.
                lines.append(quoting.QuoteLine(
                    cells[1], quoting.to_decimal(cells[3]), cells[4],
                    quoting.to_decimal(cells[5]), cells[2],
                    basis=cells[7] if len(cells) > 7 else ""))
                continue
            label = cells[5] if len(cells) > 5 else ""
            value = cells[6] if len(cells) > 6 else ""
            if label.startswith("GST"):
                gst = quoting.to_decimal(label[4:].rstrip("%"))
            elif label.startswith("Discount"):
                discount = quoting.to_decimal(label[9:].rstrip("%"))
            elif label == "Freight":
                freight = quoting.to_decimal(value)
            elif label == "Total":
                total = quoting.to_decimal(value)
    except Exception:                       # noqa: BLE001 — hand-edited file
        return None

    if not lines or gst is None or total is None:
        return None
    quote = quoting.Quotation(
        number=head.get("Quotation no", ""),
        date=register.parse_date(head.get("Date", "")) or date.today(),
        customer=head.get("Customer", ""),
        inquiry_no=head.get("Inquiry no", ""),
        lines=lines,
        terms=quoting.Terms(gst_percent=gst, freight=freight,
                            discount_percent=discount))
    if quote.total != total:
        return None
    return quote




class _EditRowDialog(PrismDialog):
    """Correct one register row by hand.

    Only the fields a person can sensibly know better than Prism. The inquiry
    number, the quotation number and the dates are not here on purpose: those
    are the register's own bookkeeping, and letting them be retyped is how two
    rows end up sharing a number.
    """

    FIELDS = ("Customer", "Contact person", "Email", "Phone",
              "Product asked", "Quantity", "Notes")

    def __init__(self, row: dict, parent=None):
        super().__init__(
            i18n.t("Edit this row"),
            i18n.t("Only the fields a person knows better than Prism. The "
                   "numbers and dates are the register's own bookkeeping."),
            icon="pencil", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Edit inquiry {no}").replace(
            "{no}", row.get("Inquiry no", "")))
        self.resize(600, 480)
        self._edits = {}

        layout = self.body
        layout.setSpacing(theme.ROW_GAP)
        form = QFormLayout()
        for field in self.FIELDS:
            edit = QLineEdit(str(row.get(field, "") or ""))
            self._edits[field] = edit
            form.addRow(i18n.t(field) + ":", edit)

        self._status = QComboBox()
        register = CB.get_register()
        for status in register.STATUSES:
            self._status.addItem(i18n.t(status), status)
        current = self._status.findData((row.get("Status") or "").strip())
        if current >= 0:
            self._status.setCurrentIndex(current)
        form.addRow(i18n.t("Status") + ":", self._status)
        layout.addLayout(form)

        note = QLabel(i18n.t(
            "Changing the status here does not send anything — it only "
            "corrects the record."))
        note.setWordWrap(True)
        note.setObjectName("meta")
        layout.addWidget(note)

        layout.addStretch(1)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", icon_name="check",
                        on_click=self.accept))

    def changes(self) -> dict:
        out = {f: e.text().strip() for f, e in self._edits.items()}
        status = self._status.currentData()
        out["Status"] = status
        # Result is what the month-end summary counts, and a status set by
        # hand has to move it too — otherwise a row marked Converted here is
        # still counted as open, and the conversion figure quietly disagrees
        # with the list the owner is looking at.
        register = CB.get_register()
        if status in register.CLOSED_STATUSES:
            out["Result"] = status
        else:
            out["Result"] = ""
        return out




