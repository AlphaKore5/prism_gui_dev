"""
Find buyers — the buyer panel
─────────────────────────────
Click a card and this slides over the right of the page, drawn like the person
drawer on People (person.py) so the two read as one product: a round initial,
the organisation and where it came from, a state pill, the actions, then two
columns — information and record details on the left, tabs on the right.

The right-hand "Buyer" tab is the SAME qualification the person drawer draws
(evidence.py): the verdict with its score, the reason, Fit / Need / Timing each
with its evidence and source, and the page itself as the "why now". It gets there
by turning the card into a Dossier (buyers.to_dossier), so there is one drawing of
"here is why, with proof" and not two.

A view: it decides and saves nothing. Accept, Not a fit and Open source are signals
the page already answers (buyers_page.py).
"""
from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QBoxLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu,
                               QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QToolButton,
                               QVBoxLayout, QWidget)

import i18n
import theme
from addons.leads import evidence
from addons.leads.person import _LEFT_W, _WIDE, _clear, _label, _link, _pill, _sheet, _widget
from prospector import buyers as B
from prospector import buyers_learn as BL
from widgets import controls as C
from widgets import icons

CHANNEL = {B.LIST: "Company list", B.TENDER: "Public tender", B.HIRING: "Hiring", B.NEWS: "Company news", B.FUNDING: "Funding",
           B.ASKING: "Asked online"}
KIND = {B.DECLARED: "They asked or invited bids", B.INFERRED: "Likely fit, from what they did"}
TABS = (("buyer", "Buyer"), ("page", "The page"), ("fields", "All fields"))


def _day(iso: str, short: bool = False) -> str:
    """'1 Dec 2026' (or '1 Dec'), the way evidence.when() writes a date; the raw text when it is not one."""
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
    except ValueError:
        return iso or ""
    return f"{d.day} {d.strftime('%b')}" + ("" if short else f" {d.year}")


def _state(h: B.Hit) -> tuple:
    """(words, ink, tint) for the pill beside the name: where this card stands."""
    if h.decision == B.ACCEPTED:
        return i18n.t("Accepted"), theme.OK_INK, theme.OK_BG
    if h.decision in (B.SKIPPED, B.NOT_A_FIT):
        return i18n.t("Put away"), theme.NEUTRAL[700], theme.NEUTRAL[200]
    if h.status == B.CLOSED:
        return i18n.t("Closed"), theme.ERR_INK, theme.ERR_BG
    if h.status == B.OPEN and h.closes:
        try:
            soon = 0 <= (date.fromisoformat(h.closes) - date.today()).days <= 5
        except ValueError:
            soon = False
        return (i18n.t("Closes {d}").format(d=_day(h.closes, short=True)),
                theme.WARN_INK if soon else theme.OK_INK, theme.WARN_BG if soon else theme.OK_BG)
    return i18n.t("New"), theme.NEUTRAL[700], theme.NEUTRAL[200]


class BuyerPanel(QWidget):
    closeRequested = Signal()
    acceptRequested = Signal(object)            # the Hit
    notFitRequested = Signal(object, str)       # the Hit, and why (one of buyers_learn.REASONS' labels, or "")
    openRequested = Signal(str)
    expandToggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("personPanel")        # the person drawer's own stylesheet: one look
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_sheet() + f"QWidget#personPanel{{border-left:1px solid {theme.HAIRLINE};}}")
        self.hit: B.Hit | None = None
        self.type_name = ""
        self._tab = "buyer"
        self._expanded = False
        self._wide = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._header())
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background:{theme.HAIRLINE};border:none;")
        root.addWidget(rule)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().setSingleStep(20)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        body = QWidget()
        body.setStyleSheet(f"background:{theme.CARD};")
        cols = QWidget(body)
        outer = QVBoxLayout(body)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(cols, 1)
        self._body_lay = QBoxLayout(QBoxLayout.LeftToRight, cols)
        self._body_lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_4)
        self._body_lay.setSpacing(theme.SPACE_4)
        self._left = QWidget()
        self.left_lay = QVBoxLayout(self._left)
        self.left_lay.setContentsMargins(0, 0, 0, 0)
        self.left_lay.setSpacing(theme.SPACE_3)
        self._body_lay.addWidget(self._left, 0, Qt.AlignTop)
        self._body_lay.addWidget(self._right(), 1)
        scroll.setWidget(body)
        root.addWidget(scroll, 1)
        self._lay_out(False)
        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.closeRequested.emit)

    # ── the parts that never change ───────────────────────────────────────────
    def _header(self) -> QWidget:
        head = QWidget()
        col = QVBoxLayout(head)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_3)
        self._avatar = QLabel()
        self._avatar.setFixedSize(44, 44)
        self._avatar.setAlignment(Qt.AlignCenter)
        self._avatar.setStyleSheet(f"QLabel{{color:{theme.NEUTRAL[700]};background:{theme.NEUTRAL[200]};"
                                   f"border-radius:22px;font-weight:700;font-size:15px;}}")
        top.addWidget(self._avatar, 0, Qt.AlignTop)
        who = QVBoxLayout()
        who.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(theme.SPACE_1)
        self.name = _label("", "pName", wrap=True, select=True)
        name_row.addWidget(self.name, 0)
        self._source_btn = C.icon_button("external", i18n.t("Open the page this came from"),
                                         on_click=self._open)
        self._source_btn.setFixedSize(26, 26)
        name_row.addWidget(self._source_btn, 0, Qt.AlignVCenter)
        name_row.addStretch(1)
        self._state_pill = _pill("", theme.NEUTRAL[700], theme.NEUTRAL[200])
        name_row.addWidget(self._state_pill, 0, Qt.AlignVCenter)
        who.addLayout(name_row)
        self.role = _label("", "pRole", wrap=True, select=True)
        who.addWidget(self.role)
        self.reach = _label("", "pMuted", wrap=True, select=True)
        who.addWidget(self.reach)
        top.addLayout(who, 1)
        self._expand_btn = C.icon_button("maximize", i18n.t("Expand"), on_click=self._toggle_expand)
        top.addWidget(self._expand_btn, 0, Qt.AlignTop)
        top.addWidget(C.icon_button("x", i18n.t("Close"), on_click=self.closeRequested.emit), 0, Qt.AlignTop)
        col.addLayout(top)
        acts = QHBoxLayout()
        acts.setSpacing(theme.SPACE_2)
        self._copy_btn = C.icon_button("copy", i18n.t("Copy the link to the page"), on_click=self._copy)
        acts.addWidget(self._copy_btn)
        acts.addStretch(1)
        self.notfit_btn = C.button(i18n.t("Not a fit"))
        # One tap says why, and what the owner says is what the next hunt learns from.
        why_menu = QMenu(self.notfit_btn)
        for _key, label in BL.REASONS:
            why_menu.addAction(i18n.t(label)).triggered.connect(lambda _=False, w=label: self._not_fit(w))
        self.notfit_btn.setMenu(why_menu)
        self.accept_btn = C.button(i18n.t("Accept"), "primary", icon_name="send", on_click=self._accept)
        acts.addWidget(self.notfit_btn)
        acts.addWidget(self.accept_btn)
        self._more = QToolButton()
        self._more.setObjectName("pMore")
        self._more.setIcon(icons.icon("more-horizontal", 17, theme.NEUTRAL[700]))
        self._more.setIconSize(QSize(17, 17))
        self._more.setFixedSize(34, 34)
        self._more.setToolTip(i18n.t("More"))
        self._more.setPopupMode(QToolButton.InstantPopup)
        self._more.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self._more)
        self.act_open = menu.addAction(i18n.t("Open the source page"))
        self.act_open.triggered.connect(self._open)
        self.act_copy = menu.addAction(i18n.t("Copy the link"))
        self.act_copy.triggered.connect(self._copy)
        self._more.setMenu(menu)
        acts.addWidget(self._more)
        col.addLayout(acts)
        return head

    def _right(self) -> QWidget:
        right = QWidget()
        col = QVBoxLayout(right)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        strip_w = QWidget()
        strip_w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        strip = QHBoxLayout(strip_w)
        strip.setContentsMargins(0, 0, 0, 0)
        strip.setSpacing(0)
        self.tab_btns: dict = {}
        self._pages: dict = {}
        self._stack = QStackedWidget()
        for key, name in TABS:
            b = QPushButton(i18n.t(name))
            b.setObjectName("pTab")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.set_tab(k))
            strip.addWidget(b)
            self.tab_btns[key] = b
            page = QWidget()
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(theme.SPACE_3)
            self._pages[key] = lay
            self._stack.addWidget(page)
        strip.addStretch(1)
        col.addWidget(strip_w)
        col.addWidget(C.hairline())
        col.addWidget(self._stack, 0, Qt.AlignTop)
        col.addStretch(1)
        self.set_tab("buyer")
        return right

    # ── layout ────────────────────────────────────────────────────────────────
    def _lay_out(self, wide: bool) -> None:
        if wide == self._wide:
            return
        self._wide = wide
        self._body_lay.setDirection(QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom)
        if wide:
            self._left.setFixedWidth(_LEFT_W)
        else:
            self._left.setMinimumWidth(0)
            self._left.setMaximumWidth(16777215)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._lay_out(self.width() >= _WIDE)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self._expand_btn.setToolTip(i18n.t("Back to the list") if self._expanded else i18n.t("Expand"))
        self.expandToggled.emit(self._expanded)

    def set_tab(self, key: str) -> None:
        if key not in self.tab_btns:
            return
        self._tab = key
        for k, b in self.tab_btns.items():
            b.setChecked(k == key)
        self._stack.setCurrentIndex([k for k, _n in TABS].index(key))

    def tab(self) -> str:
        return self._tab

    # ── showing one buyer ─────────────────────────────────────────────────────
    def show_hit(self, h: "B.Hit | None", type_name: str = "") -> None:
        self.hit, self.type_name = h, type_name
        for lay in list(self._pages.values()) + [self.left_lay]:
            _clear(lay)
        if h is None:
            return
        from addons.leads.cockpit import _initials
        self._avatar.setText(_initials(h.who or h.title))
        self.name.setText(h.who or h.title or i18n.t("(no name)"))
        words, ink, bg = _state(h)
        self._state_pill.setText(words)
        self._state_pill.setStyleSheet(
            f"QLabel{{color:{ink};background:{bg};border-radius:{theme.R_CHIP}px;"
            f"padding:2px 8px;font-size:11px;font-weight:600;}}")
        self.role.setText(" · ".join((i18n.t(CHANNEL[h.channel]), i18n.t(KIND[h.kind]))))
        self.reach.setText(h.source or "")
        fresh = h.decision == B.NEW
        self.accept_btn.setVisible(fresh)
        self.notfit_btn.setVisible(fresh)
        self._source_btn.setVisible(bool(evidence.safe_url(h.url)))
        self._fill_left(h)
        self._fill_buyer(h)
        self._fill_page(h)
        self._fill_fields(h)

    def _icon(self, name: str) -> QLabel:
        lab = QLabel()
        lab.setPixmap(icons.pixmap(name, 15, theme.NEUTRAL[600]))
        lab.setFixedSize(18, 18)
        return lab

    def _fill_left(self, h: B.Hit) -> None:
        lay = self.left_lay
        box, col = _widget(i18n.t("Buyer information"))
        for icon_name, text in (("building", h.who or h.title), ("globe", h.source or h.url)):
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_2)
            row.addWidget(self._icon(icon_name), 0, Qt.AlignTop)
            row.addWidget(_label(text, select=True), 1)
            col.addLayout(row)
        if evidence.safe_url(h.url):
            self.open_link = _link(i18n.t("Open the page it came from"), self._open)
            col.addWidget(self.open_link)
        words = i18n.t("Found by searching " + {B.LIST: "company profiles", B.TENDER: "public tenders", B.HIRING: "job posts",
                                                  B.NEWS: "company news", B.FUNDING: "funding news",
                                                  B.ASKING: "online posts"}[h.channel])
        col.addWidget(_label(words, "pMuted"))
        lay.addWidget(box)

        box, col = _widget(i18n.t("Record details"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        rows = []
        if h.closes:
            rows.append((i18n.t("Bid closes"), _day(h.closes) + (" · " + i18n.t("closed") if h.status == B.CLOSED else "")))
        if h.published:
            rows.append((i18n.t("Published"), _day(h.published)))
        rows.append((i18n.t("Kind of buyer"), self.type_name or i18n.t("Not recorded")))
        rows.append((i18n.t("Read by"), i18n.t("The model") if h.checked else i18n.t("Plain rules only")))
        rows.append((i18n.t("Your decision"), {B.NEW: i18n.t("None yet"), B.ACCEPTED: i18n.t("Accepted"),
                                               B.SKIPPED: i18n.t("Put away"),
                                               B.NOT_A_FIT: i18n.t("Not a fit")}[h.decision]))
        for r, (k, v) in enumerate(rows):
            grid.addWidget(_label(k, "pKey", wrap=False), r, 0, Qt.AlignTop)
            grid.addWidget(_label(v, select=True), r, 1)
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        lay.addWidget(box)
        lay.addStretch(1)

    def _fill_buyer(self, h: B.Hit) -> None:
        """The tab the person drawer calls Prospect: the verdict, the reason and the proof."""
        lay = self._pages["buyer"]
        dos = B.to_dossier(h, self.type_name)
        for part in evidence.headline(dos) + evidence.detail(dos):
            lay.addWidget(part)
        if h.decision == B.NOT_A_FIT and h.reason:
            lay.addWidget(_label(i18n.t("Put away because: {why}").format(why=h.reason), "pMuted"))
        lay.addStretch(1)

    def _fill_page(self, h: B.Hit) -> None:
        lay = self._pages["page"]
        box, col = _widget(i18n.t("What the page says"))
        col.addWidget(_label(h.snippet or i18n.t("The page gave no text."), select=True))
        col.addWidget(_label(h.source or "", "pMuted"))
        lay.addWidget(box)
        lay.addStretch(1)

    def _fill_fields(self, h: B.Hit) -> None:
        lay = self._pages["fields"]
        box, col = _widget(i18n.t("All fields"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_3)
        grid.setVerticalSpacing(theme.SPACE_2)
        rows = [(i18n.t("Organisation"), h.who), (i18n.t("Title"), h.title), (i18n.t("Channel"), i18n.t(CHANNEL[h.channel])),
                (i18n.t("Kind"), i18n.t(KIND[h.kind])), (i18n.t("Source"), h.source), (i18n.t("Address"), h.url),
                (i18n.t("Published"), h.published), (i18n.t("Bid closes"), h.closes), (i18n.t("Status"), h.status),
                (i18n.t("Fit"), str(h.fit)), (i18n.t("Intent"), str(h.intent)), (i18n.t("Score"), str(h.score)),
                (i18n.t("Read by"), h.scored_by), (i18n.t("Decision"), h.decision), (i18n.t("Reason"), h.reason)]
        r = 0
        for k, v in rows:
            if not v:
                continue
            grid.addWidget(_label(k, "pKey", wrap=False), r, 0, Qt.AlignTop)
            grid.addWidget(_label(v, select=True), r, 1)
            r += 1
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        lay.addWidget(box)
        lay.addStretch(1)

    # ── what the owner pressed ────────────────────────────────────────────────
    def _accept(self) -> None:
        if self.hit is not None:
            self.acceptRequested.emit(self.hit)

    def _not_fit(self, reason: str = "") -> None:
        if self.hit is not None:
            self.notFitRequested.emit(self.hit, reason)

    def _open(self) -> None:
        if self.hit is not None:
            self.openRequested.emit(self.hit.url)

    def _copy(self) -> None:
        """Put the page's address on the clipboard. Tests patch this."""
        if self.hit is not None:
            QApplication.clipboard().setText(self.hit.url)
