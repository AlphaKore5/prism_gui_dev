"""
Find buyers — the page
──────────────────────
Leads & Outreach starts from a filter ("who looks like a customer"). This page
starts from the product: describe what you sell, and Prism searches public
tenders, job posts and company news for organisations that look ready to buy,
and shows the proof for each one.

Three steps on one scrolling page, so nothing is a wizard the owner can get
lost in:

  1. Describe   — what you sell, a website and where you sell. One big box.
  2. Check      — what Prism understood: the kinds of buyer (tick the ones that
                  are right) and which sources to search. A free quick preview
                  first, then the full search.
  3. Cards      — each buyer with its evidence. Accept sends it to People;
                  Not a fit puts it away. Closed bids are counted, not shown.

A view only: it draws what it is handed and says what the owner asked by a
signal (buyers_controller.py answers). Nothing here searches, saves or sends.
"""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit,
                               QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import i18n
import theme
from addons.leads import result_rows as RR
from prospector import buyers as B
from widgets import controls as C

DOCK_MIN = 1100      # the body is at least this wide: the panel sits beside the list
PANEL_W = 700         # the docked panel's width
CHANNEL_LABEL = {B.LIST: "Companies like your customer", B.TENDER: "Public tender", B.HIRING: "Hiring", B.NEWS: "Company news", B.FUNDING: "Funding",
                 B.ASKING: "Asked online"}
CHANNEL_HELP = {
    B.LIST: "Companies that fit the size and place of your customer, then checked for a recent sign they are growing. "
            "Needs your own Exa key.",
    B.TENDER: "Open bids and quotation requests from public buyers. The strongest sign, and it expires: closed bids are dropped.",
    B.HIRING: "Companies hiring for the job that uses what you sell.",
    B.NEWS: "New plants and expansions: a reason to call, not a request.",
    B.FUNDING: "Companies that just raised money, so they are buying.",
    B.ASKING: "People who posted that they need it. Rare for niche B2B, so it is off unless you turn it on."}
_KIND_PILL = {B.DECLARED: ("They asked", "ok"), B.INFERRED: ("Likely fit", "info")}


def _plural(n: int, one: str, many: str) -> str:
    return i18n.t(one) if n == 1 else i18n.t(many).format(n=n)


def _short_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b")
    except ValueError:
        return iso


class _ClickLabel(QLabel):
    """A label that says it was pressed: the words next to a tick box tick it."""
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class _TypeRow(QWidget):
    """A kind of buyer: a tick box, and its name and reason in words that WRAP. A tick box's own text never
    wraps, and one long reason made the whole page wider than the window."""

    def __init__(self, buyer_type: B.BuyerType, detail: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.box = QCheckBox(self)
        self.box.setChecked(buyer_type.enabled)
        self.words = _ClickLabel(buyer_type.name + (" — " + buyer_type.why if buyer_type.why else ""))
        self.words.setWordWrap(True)
        self.words.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.words.clicked.connect(self.box.toggle)
        row.addWidget(self.box, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addWidget(self.words)
        # What used to be a hover window is a line of its own: who decides, what to look for, what to skip.
        self.detail = QLabel(detail, self)           # parented: see ResultRow.check
        self.detail.setWordWrap(True)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.detail.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:12px;")
        self.detail.setVisible(bool(detail))
        col.addWidget(self.detail)
        row.addLayout(col, 1)


def _card(object_name: str) -> QFrame:
    f = QFrame()
    f.setObjectName(object_name)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setStyleSheet(f"QFrame#{object_name}{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};"
                    f"border-radius:14px;}}")
    return f


class BuyersPage(QWidget):
    readRequested = Signal(object)                  # buyers.Offer: "Find my buyers"
    huntRequested = Signal(object, str, list, tuple, bool)   # offer, summary, types, channels, preview
    acceptRequested = Signal(list)                  # [buyers.Hit]
    decisionRequested = Signal(list, str, str)      # card ids, decision, reason
    openRequested = Signal(str)                     # a card's source address
    huntPicked = Signal(str)                        # the id of an earlier hunt, from the Hunts menu

    def __init__(self, parent=None):
        super().__init__(parent)
        self._summary = ""
        self._types: list = []
        self._hunt: dict | None = None
        self._busy = False
        self.type_boxes: dict = {}
        self.channel_boxes: dict = {}
        self._tab = "total"                     # Total | New | Accepted | Put away
        self._compact = False                   # the panel is docked beside the list: rows are short
        self._monid = False                     # Monid's sources (Indeed, Google News, Reddit, HN) are on
        self._ideal = ""                        # who exactly buys it, from the offer's reading
        self._company_kinds, self._max_staff = (), 0     # what the buying companies do, and the largest that fits
        self._competitors = ""                  # kinds of organisation that sell the same thing, from the offer's reading
        self._setup_hidden = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())
        self._body = QWidget()
        body = QHBoxLayout(self._body)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        self._body_lay = body
        outer.addWidget(self._body, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # the page is as wide as the window, never wider
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CARD};border:none;}}")
        host = QWidget()
        # Ignored: the scroll area may squeeze this to the width it has and never stretches it wider (it would
        # then be cut off on the left and run off the right when the panel docks beside it).
        host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._host = host
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        self._col.setSpacing(theme.SPACE_4)
        self._describe = self._build_describe()
        self._col.addWidget(self._describe)
        self._understood = self._build_understood()
        self._col.addWidget(self._understood)
        self._col.addWidget(self._build_results())
        self._col.addStretch(1)
        scroll.setWidget(host)
        body.addWidget(scroll, 1)
        # The buyer panel floats over the right of the page (the person drawer does the same when
        # the window is narrow): it is not in the layout, so it never makes the list narrower.
        from addons.leads.buyers_panel import BuyerPanel
        self.panel = BuyerPanel(self._body)
        self.panel.hide()
        self.panel.closeRequested.connect(self.close_panel)
        self.panel.acceptRequested.connect(lambda c: self.acceptRequested.emit([c]))
        self.panel.notFitRequested.connect(lambda c, why: self.decisionRequested.emit([c.id], B.NOT_A_FIT, why))
        self.panel.openRequested.connect(self.openRequested)
        self.panel.expandToggled.connect(lambda _on: self._place_panel())
        self.set_monid(False)                       # says how to turn Monid on, and syncs the buttons

    # ── the header: title, toolbar and tabs, as Find people has them ──────────
    def _build_header(self) -> QWidget:
        head = QWidget()
        head.setStyleSheet(f"background:{theme.CARD};")
        v = QVBoxLayout(head)
        v.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, 0)
        v.setSpacing(theme.SPACE_2)
        title = QHBoxLayout()
        title.addWidget(C.label(i18n.t("Find buyers"), level="SECTION", weight=400), 1)
        self.new_btn = C.button(i18n.t("New hunt"), on_click=self._new_hunt)
        title.addWidget(self.new_btn)
        v.addLayout(title)
        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_2)
        self.hunts_btn = C.button(i18n.t("Hunts"), on_click=None)
        self.hunts_menu = QMenu(self.hunts_btn)
        self.hunts_btn.setMenu(self.hunts_menu)
        self.setup_btn = C.button(i18n.t("Hide setup"), on_click=self._toggle_setup)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(i18n.t("Search buyers"))
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setMinimumWidth(120)
        self.search_edit.setMaximumWidth(260)
        self.search_edit.textChanged.connect(lambda _t: self._draw())
        self.filters_btn = C.button(i18n.t("Filters"))
        self.filters_menu = QMenu(self.filters_btn)
        self.show_weak = QAction(i18n.t("Show weak matches (score under {n})").format(n=B.WEAK_BELOW), self.filters_menu)
        self.show_closed = QAction(i18n.t("Show closed bids"), self.filters_menu)
        self.show_aside = QAction(i18n.t("Show ones I put away"), self.filters_menu)
        for a in (self.show_weak, self.show_closed, self.show_aside):
            a.setCheckable(True)
            a.toggled.connect(lambda _on: self._draw())
            self.filters_menu.addAction(a)
        self.filters_btn.setMenu(self.filters_menu)
        self.sort_btn = C.button(i18n.t("Best match"))
        self.sort_menu = QMenu(self.sort_btn)
        self._sort = "best"
        self.sort_actions: dict = {}
        group = QActionGroup(self.sort_menu)
        for key, words in (("best", "Best match"), ("closing", "Closing soonest"), ("newest", "Newest")):
            a = QAction(i18n.t(words), self.sort_menu)
            a.setCheckable(True)
            a.setChecked(key == "best")
            a.triggered.connect(lambda _c=False, k=key: self.set_sort(k))
            group.addAction(a)
            self.sort_menu.addAction(a)
            self.sort_actions[key] = a
        self.sort_btn.setMenu(self.sort_menu)
        bar.addWidget(self.hunts_btn)
        bar.addWidget(self.setup_btn)
        bar.addWidget(self.search_edit, 1)
        bar.addWidget(self.filters_btn)
        bar.addStretch(1)
        bar.addWidget(self.sort_btn)
        v.addLayout(bar)
        self.tabs = RR.ViewToggle([("total", i18n.t("Total")), ("new", i18n.t("New")),
                                   ("accepted", i18n.t("Accepted")), ("away", i18n.t("Put away"))], "total")
        self.tabs.changed.connect(self._tab_picked)
        row = QHBoxLayout()
        row.addWidget(self.tabs)
        row.addStretch(1)
        v.addLayout(row)
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{theme.HAIRLINE};border:none;")
        v.addWidget(rule)
        return head

    def set_sort(self, key: str) -> None:
        if key not in self.sort_actions:
            return
        self._sort = key
        self.sort_actions[key].setChecked(True)
        self.sort_btn.setText(self.sort_actions[key].text())
        self._draw()

    def _tab_picked(self, key: str) -> None:
        self._tab = key
        self._draw()

    def set_hunts(self, hunts: list) -> None:
        """[{"id", "label"}] newest first: what the Hunts menu offers."""
        self.hunts_menu.clear()
        self.hunt_actions = {}
        for h in hunts or []:
            a = self.hunts_menu.addAction(h["label"])
            a.triggered.connect(lambda _c=False, i=h["id"]: self.huntPicked.emit(i))
            self.hunt_actions[h["id"]] = a
        if not hunts:
            self.hunts_menu.addAction(i18n.t("No earlier searches yet")).setEnabled(False)
        self.hunts_btn.setEnabled(True)

    def _toggle_setup(self) -> None:
        self._setup_hidden = not self._setup_hidden
        self._sync_setup()

    def _new_hunt(self) -> None:
        """Back to the describe box: show the setup, clear the search box and tab, close the panel."""
        self._setup_hidden = False
        self.search_edit.clear()
        self.tabs.set_current("total")
        self._tab = "total"
        self._sync_setup()
        self.close_panel()
        self.offer_edit.setFocus()

    def _sync_setup(self) -> None:
        """The two setup cards and the words on the button that hides them."""
        self._describe.setVisible(not self._setup_hidden)
        self._understood.setVisible(bool(self._types) and not self._setup_hidden)
        self.setup_btn.setText(i18n.t("Show setup") if self._setup_hidden else i18n.t("Hide setup"))

    # ── 1. describe ───────────────────────────────────────────────────────────
    def _build_describe(self) -> QFrame:
        card = _card("buyersDescribe")
        v = QVBoxLayout(card)
        v.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        v.setSpacing(theme.SPACE_3)
        v.addWidget(C.label(i18n.t("Find the buyers who need what you sell"), level="SECTION", weight=400))
        v.addWidget(C.label(i18n.t("Describe it in plain words. Prism reads public tenders, job posts and "
                                   "company news and shows the proof for every buyer it finds."),
                            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.offer_edit = QPlainTextEdit()
        self.offer_edit.setPlaceholderText(i18n.t(
            "What you sell, who it is for, and what makes you worth choosing. For example: PCB "
            "prototypes and small batches for hardware startups, 2 to 8 layers, ready in 3 days."))
        self.offer_edit.setFixedHeight(110)
        self.offer_edit.textChanged.connect(self._sync)
        v.addWidget(self.offer_edit)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_3)
        self.site_edit = QLineEdit()
        self.site_edit.setPlaceholderText(i18n.t("Your website (optional)"))
        self.region_edit = QLineEdit()
        self.region_edit.setPlaceholderText(i18n.t("Where you sell, e.g. Gujarat, India"))
        row.addWidget(self.site_edit, 1)
        row.addWidget(self.region_edit, 1)
        v.addLayout(row)
        act = QHBoxLayout()
        act.setSpacing(theme.SPACE_3)
        self.find_btn = C.button(i18n.t("Find my buyers"), "primary", on_click=self._read)
        act.addWidget(self.find_btn)
        # One wrapping line, not three fixed-width chips: the describe card is what sets how narrow the page can be.
        act.addWidget(C.label(i18n.t("Reads public pages only  ·  Nothing is sent without your OK  ·  About 3 minutes"),
                              level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True), 1)
        v.addLayout(act)
        self.status = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        self.status.setVisible(False)
        v.addWidget(self.status)
        return card

    # ── 2. check ──────────────────────────────────────────────────────────────
    def _build_understood(self) -> QFrame:
        card = _card("buyersUnderstood")
        v = QVBoxLayout(card)
        v.setContentsMargins(theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4)
        v.setSpacing(theme.SPACE_3)
        v.addWidget(C.label(i18n.t("What Prism understood"), level="SECTION", weight=400))
        self.summary = C.label("", level="BODY", wrap=True)
        v.addWidget(self.summary)
        self.ideal_label = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        self.ideal_label.setVisible(False)
        v.addWidget(self.ideal_label)
        self.competitors_label = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        self.competitors_label.setVisible(False)
        v.addWidget(self.competitors_label)
        v.addWidget(C.label(i18n.t("Kinds of buyer. Untick the ones that are wrong."),
                            level="SUPPORT", colour=theme.NEUTRAL[600]))
        self._types_col = QVBoxLayout()
        self._types_col.setSpacing(4)
        v.addLayout(self._types_col)
        v.addWidget(C.label(i18n.t("Where to look"), level="SUPPORT", colour=theme.NEUTRAL[600]))
        srow = QHBoxLayout()
        srow.setSpacing(theme.SPACE_4)
        for ch in B.CHANNELS:
            box = QCheckBox(i18n.t(CHANNEL_LABEL[ch]))
            box.setChecked(ch in B.DEFAULT_CHANNELS)
            box.toggled.connect(self._sync)
            self.channel_boxes[ch] = box
            srow.addWidget(box)
        srow.addStretch(1)
        v.addLayout(srow)
        v.addWidget(C.label(" ".join(i18n.t(CHANNEL_HELP[c]) for c in B.CHANNELS), level="SUPPORT",
                            colour=theme.NEUTRAL[600], wrap=True))
        self.monid_note = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        v.addWidget(self.monid_note)
        self.estimate = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        v.addWidget(self.estimate)
        self.learned_label = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        self.learned_label.setVisible(False)
        v.addWidget(self.learned_label)
        act = QHBoxLayout()
        act.setSpacing(theme.SPACE_3)
        self.preview_btn = C.button(i18n.t("Quick preview"), "secondary", on_click=lambda: self._hunt_now(True))
        self.run_btn = C.button(i18n.t("Run the full search"), "primary", on_click=lambda: self._hunt_now(False))
        act.addWidget(self.preview_btn)
        act.addWidget(self.run_btn)
        act.addStretch(1)
        v.addLayout(act)
        card.setVisible(False)
        return card

    # ── 3. cards ──────────────────────────────────────────────────────────────
    def _build_results(self) -> QWidget:
        self._results = QWidget()
        v = QVBoxLayout(self._results)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(theme.SPACE_2)
        self.headline = C.label("", level="SECTION", weight=400, wrap=True)
        v.addWidget(self.headline)
        self.notes = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        v.addWidget(self.notes)
        self.list = RR.ResultList()
        v.addWidget(self.list)
        self.empty = C.label("", level="BODY", colour=theme.NEUTRAL[600], wrap=True)
        v.addWidget(self.empty)
        self._results.setVisible(False)
        return self._results

    # ── what the owner asked ──────────────────────────────────────────────────
    def offer(self) -> B.Offer:
        return B.Offer(text=self.offer_edit.toPlainText().strip(), website=self.site_edit.text().strip(),
                       regions=self.region_edit.text().strip(), competitors=self._competitors,
                       ideal=self._ideal, company_kinds=self._company_kinds, max_staff=self._max_staff)

    def types(self) -> list:
        """The buyer types, each carrying whether its box is ticked."""
        for t in self._types:
            box = self.type_boxes.get(t.key)
            if box is not None:
                t.enabled = box.isChecked()
        return list(self._types)

    def channels(self) -> tuple:
        return tuple(c for c in B.CHANNELS if self.channel_boxes[c].isChecked())

    def _read(self) -> None:
        offer = self.offer()
        if not offer.text:
            self.set_status(i18n.t("Describe what you sell first."))
            return
        self.readRequested.emit(offer)

    def _hunt_now(self, preview: bool) -> None:
        self.huntRequested.emit(self.offer(), self._summary, self.types(), self.channels(), preview)

    # ── what the controller hands in ──────────────────────────────────────────
    def set_offer(self, offer: B.Offer) -> None:
        self.offer_edit.setPlainText(offer.text)
        self.site_edit.setText(offer.website)
        self.region_edit.setText(offer.regions)

    def set_monid(self, on: bool) -> None:
        """Say whether Monid's sources are on, and what the owner gets or has to do for them."""
        self._monid = bool(on)
        self.monid_note.setText(
            i18n.t("Hiring uses Indeed jobs, news and funding use Google News, and Asked online uses Reddit and "
                   "Hacker News, through your Monid account.") if on else
            i18n.t("Hiring, news, funding and Asked online search the web with Exa. Add your Monid key "
                   "(MONID_API_KEY) to use Indeed jobs, Google News, Reddit and Hacker News instead."))
        self._sync()

    def set_status(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        self.set_status(text)
        self._sync()

    def set_learned(self, report: list) -> None:
        """What the owner's decisions say about each source (buyers_learn.report): how many it gave that were
        accepted and put away, how many accepted buyers replied, and which source is nearly all put away."""
        lines = []
        for r in report or ():
            line = i18n.t("{source}: {a} accepted, {p} put away").format(
                source=i18n.t(CHANNEL_LABEL[r["channel"]]), a=r["accepted"], p=r["put_away"])
            if r.get("saved"):
                line += i18n.t(", {r} of {s} replied").format(r=r.get("replied", 0), s=r["saved"])
            if r.get("advice"):
                line += i18n.t(". Nearly all were put away: consider turning it off.")
            lines.append(line)
        self.learned_label.setText(i18n.t("What your decisions say") + "\n" + "\n".join(lines) if lines else "")
        self.learned_label.setVisible(bool(lines))

    def set_types(self, summary: str, types: list, competitors: str = "", channels=None, ideal: str = "",
                  company_kinds=(), max_staff: int = 0) -> None:
        """Show what the model understood. `competitors` names who sells the same thing and `ideal` who the customer
        is, both said out loud so a wrong reading is seen before a search is paid for; `channels`, when given, are the
        sources that fit this seller."""
        self._summary, self._types = summary, list(types)
        self._ideal = (ideal or "").strip()
        self._company_kinds, self._max_staff = tuple(company_kinds or ()), int(max_staff or 0)
        self.ideal_label.setText(i18n.t("Your customer: {who}").format(who=self._ideal))
        self.ideal_label.setVisible(bool(self._ideal))
        self._competitors = (competitors or "").strip()
        self.competitors_label.setText(i18n.t("Not buyers, because they sell the same thing: {who}").format(who=self._competitors))
        self.competitors_label.setVisible(bool(self._competitors))
        if channels:
            for ch, box in self.channel_boxes.items():
                box.setChecked(ch in channels)
        self.summary.setText(summary or i18n.t("Here is how Prism read your offer."))
        while self._types_col.count():
            item = self._types_col.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.type_boxes = {}
        for t in self._types:
            detail = "  ·  ".join(x for x in (
                i18n.t("Decides: {who}").format(who=", ".join(t.who_decides)) if t.who_decides else "",
                i18n.t("Looks for: {what}").format(what=", ".join(t.needs)) if t.needs else "",
                i18n.t("Skips: {what}").format(what=", ".join(t.exclude)) if t.exclude else "") if x)
            row = _TypeRow(t, detail)
            row.box.toggled.connect(self._sync)
            self.type_boxes[t.key] = row.box
            self._types_col.addWidget(row)
        self._sync_setup()
        self._sync()

    def set_hunt(self, hunt: "dict | None") -> None:
        first_look = hunt is not None and self._hunt is None
        self._hunt = hunt
        if first_look and hunt.get("hits"):
            self._setup_hidden = True
            self._sync_setup()
        self._draw()

    def _sync(self, *_args) -> None:
        has_offer = bool(self.offer_edit.toPlainText().strip())
        self.find_btn.setEnabled(has_offer and not self._busy)
        ready = bool(self._types) and not self._busy
        picked = [t for t in self.types() if t.enabled]
        chans = tuple(c for c in B.CHANNELS if c in self.channel_boxes and self.channel_boxes[c].isChecked())
        can = ready and bool(picked) and bool(chans)
        self.preview_btn.setEnabled(can)
        self.run_btn.setEnabled(can)
        if picked and chans:
            full = B.estimate(self.offer(), picked, chans, monid=self._monid)
            quick = B.estimate(self.offer(), picked, chans, preview=True, monid=self._monid)
            self.estimate.setText(i18n.t("The full search makes about {s} web searches and {m} AI reads. "
                                         "The quick preview makes {q} searches.").format(
                s=full["searches"], m=full["model_calls"], q=quick["searches"]))
        else:
            self.estimate.setText(i18n.t("Pick at least one kind of buyer and one place to look."))

    # ── the cards ─────────────────────────────────────────────────────────────
    def _in_tab(self, h: B.Hit) -> bool:
        if self._tab == "new":
            return h.decision == B.NEW
        if self._tab == "accepted":
            return h.decision == B.ACCEPTED
        if self._tab == "away":
            return h.decision in (B.SKIPPED, B.NOT_A_FIT)
        return True

    def _matches(self, h: B.Hit, needle: str) -> bool:
        return not needle or needle in " ".join((h.who, h.title, h.why, h.snippet, h.source)).casefold()

    def _visible(self, hits: list) -> list:
        needle = self.search_edit.text().strip().casefold()
        out = []
        for h in hits:
            if not self._in_tab(h) or not self._matches(h, needle):
                continue
            if h.status == B.CLOSED and not self.show_closed.isChecked():
                continue
            if h.weak and h.decision == B.NEW and not self.show_weak.isChecked():
                continue
            # The Put away tab IS the ones put away; elsewhere they stay hidden unless asked for.
            if h.decision in (B.SKIPPED, B.NOT_A_FIT) and self._tab != "away" and not self.show_aside.isChecked():
                continue
            out.append(h)
        if self._sort == "closing":
            out.sort(key=lambda h: (h.closes == "", h.closes or "9999", -h.score))
        elif self._sort == "newest":
            out.sort(key=lambda h: (h.published == "", _neg(h.published), -h.score))
        else:
            out.sort(key=lambda h: (-h.score, h.id))
        return out

    def _counts(self, hits: list) -> dict:
        """What each tab would hold, so the labels say it before it is pressed."""
        return {"total": sum(1 for h in hits if h.status != B.CLOSED and not (h.weak and h.decision == B.NEW)
                             and h.decision not in (B.SKIPPED, B.NOT_A_FIT)),
                "new": sum(1 for h in hits if h.decision == B.NEW and h.status != B.CLOSED and not h.weak),
                "accepted": sum(1 for h in hits if h.decision == B.ACCEPTED),
                "away": sum(1 for h in hits if h.decision in (B.SKIPPED, B.NOT_A_FIT))}

    def _draw(self) -> None:
        hunt = self._hunt
        self.list.clear()
        self._results.setVisible(hunt is not None)
        if hunt is None:
            return
        hits = list(hunt.get("hits") or [])
        stats = hunt.get("stats") or {}
        shown = self._visible(hits)
        for key, words in (("total", "Total"), ("new", "New"), ("accepted", "Accepted"), ("away", "Put away")):
            self.tabs._buttons[key].setText(f"{i18n.t(words)}  {self._counts(hits)[key]}")
        live = [h for h in hits if h.status != B.CLOSED and h.decision == B.NEW and not h.weak]
        weak = sum(1 for h in hits if h.weak and h.decision == B.NEW)
        closed = sum(1 for h in hits if h.status == B.CLOSED)
        self.headline.setText(
            (i18n.t("Quick preview: ") if hunt.get("preview") else "")
            + _plural(len(live), "1 buyer worth a look", "{n} buyers worth a look")
            + (" · " + _plural(weak, "1 weak match hidden", "{n} weak matches hidden")
               if weak and not self.show_weak.isChecked() else "")
            + (" · " + _plural(closed, "1 closed bid hidden", "{n} closed bids hidden")
               if closed and not self.show_closed.isChecked() else ""))
        credits = stats.get("credits")
        bits = list(hunt.get("notes") or [])
        if credits:
            bits.append(_plural(int(credits), "This search used 1 credit.", "This search used {n} credits."))
        self.notes.setText("  ".join(bits))
        self.notes.setVisible(bool(bits))
        self.list.add_all([self._row(i, h, self._compact) for i, h in enumerate(shown)])
        self.list.setVisible(bool(shown))
        self.empty.setVisible(not shown)
        self.empty.setText(
            i18n.t("No buyers with proof turned up. That is a real answer: this niche may not "
                   "announce its needs in public. Try other kinds of buyer or another place to look.")
            if not hits else i18n.t("Nothing to show here. Try another tab, clear the search, or open "
                                    "Filters to see weak matches, closed bids or the ones you put away."))
        self._refresh_panel()

    def _row(self, idx: int, h: B.Hit, compact: bool = False) -> QWidget:
        # "They asked" is a claim about the buyer: only when the model read the page and agrees.
        if h.kind == B.DECLARED and h.checked and h.intent >= 60:
            pills = [(i18n.t(_KIND_PILL[B.DECLARED][0]), _KIND_PILL[B.DECLARED][1])]
        elif h.kind == B.DECLARED:
            pills = [(i18n.t("Possible"), "quiet")]
        else:
            pills = [(i18n.t(_KIND_PILL[B.INFERRED][0]), _KIND_PILL[B.INFERRED][1])]
        if not h.checked:
            pills.append((i18n.t("Not checked"), "warn"))
        if h.status == B.OPEN and h.closes:
            soon = False
            try:
                soon = (date.fromisoformat(h.closes) - date.today()).days <= 5
            except ValueError:
                pass
            pills.append((i18n.t("Closes {d}").format(d=_short_date(h.closes)), "warn" if soon else "ok"))
        elif h.status == B.CLOSED:
            pills.append((i18n.t("Closed"), "err"))
        elif h.status == B.OLD:
            pills.append((i18n.t("Old"), "warn"))
        elif h.status == B.RECENT:
            pills.append((i18n.t("Recent"), "quiet"))
        if h.decision == B.ACCEPTED:
            pills.append((i18n.t("Accepted"), "ok"))
        elif h.decision in (B.SKIPPED, B.NOT_A_FIT):
            pills.append((i18n.t("Put away"), "quiet"))
        else:
            pills.append((i18n.t("Score {n}").format(n=h.score),
                          "ok" if h.score >= 70 else "info" if h.score >= 50 else "quiet"))
        if compact:
            # Beside the panel the list is narrow: a name, a reason and ONE pill (where it stands, or its score).
            pills = pills[-1:]
        actions = []                       # "Open source" lives on the card: a row this wide cannot hold a third button
        if h.decision == B.NEW and not compact:
            actions.append((i18n.t("Accept"), True, lambda _=False, c=h: self.acceptRequested.emit([c])))
            actions.append((i18n.t("Not a fit"), False,
                            lambda _=False, c=h: self.decisionRequested.emit([c.id], B.NOT_A_FIT, "")))
        row = RR.ResultRow(RR.RowSpec(key=idx, name=h.who or h.title, company=i18n.t(CHANNEL_LABEL[h.channel]),
                                      subline=h.why or h.snippet, pills=pills, actions=actions,
                                      checkable=False))
        row.clicked.connect(lambda _i, c=h: self.open_card(c))
        return row

    def _type_name(self, h: B.Hit) -> str:
        return {t.key: t.name for t in self._types}.get(h.buyer_type, "")

    def open_card(self, h: B.Hit) -> None:
        """Click on a row: the buyer's panel slides over the right of the page, with the whole evidence.
        Not the browser: "Open the source page" is its own button on the panel."""
        self.panel.show_hit(h, self._type_name(h))
        self._place_panel()
        self.panel.show()
        self.panel.raise_()

    def close_panel(self) -> None:
        self.panel.hide()
        self.panel.show_hit(None)
        if self._body_lay.indexOf(self.panel) != -1:
            self._body_lay.removeWidget(self.panel)
        self._set_compact(False)

    def _refresh_panel(self) -> None:
        """A decision was made, or the list was redrawn: the open panel shows the card as it now stands."""
        h = self.panel.hit
        if h is not None and not self.panel.isHidden():
            self.panel.show_hit(h, self._type_name(h))

    def _place_panel(self) -> None:
        """Beside the list when the page is wide enough for both (nothing is covered); over it when it is
        not, or when the owner expands the panel. Never over the header: the toolbar stays reachable."""
        expanded = getattr(self.panel, "_expanded", False)
        dock = self._body.width() >= DOCK_MIN and not expanded
        self._set_compact(dock)
        docked_now = self._body_lay.indexOf(self.panel) != -1
        if dock:
            if not docked_now:
                self._body_lay.addWidget(self.panel)
            self.panel.setMinimumWidth(PANEL_W)
            self.panel.setMaximumWidth(PANEL_W)
        else:
            if docked_now:
                self._body_lay.removeWidget(self.panel)
            self.panel.setMinimumWidth(0)
            self.panel.setMaximumWidth(16777215)
            room = max(300, self._body.width())
            want = room if expanded else min(PANEL_W + 100, room)
            self.panel.setGeometry(self._body.width() - want, 0, want, self._body.height())
        self.panel.raise_()

    def _set_compact(self, on: bool) -> None:
        """Short rows while the panel is docked beside them; the full rows when it closes or floats."""
        if on != self._compact:
            self._compact = on
            self._draw()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.panel.isHidden():
            self._place_panel()


def _neg(text: str) -> str:
    """A sort key that puts the later date first: each character inverted."""
    return "".join(chr(0x10FFFF - ord(c)) for c in text)
