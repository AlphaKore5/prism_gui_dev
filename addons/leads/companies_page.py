"""
Leads & Outreach — the Companies page (Apollo's Companies)
──────────────────────────────────────────────────────────
Apollo's Companies page is Find People's twin (knowledge.apollo.io, "Search for
Companies", read 24-Oct-2026):

    Companies                                                 [Import ▾]
    [Hide filters] [Search companies]                         [Sort ▾]
    ┌ Total · Net New · Saved ┐ ┌ COMPANY … INDUSTRY … EMPLOYEES … STAGE … PEOPLE ┐
    │ the filter facets        │ │                                                │
    └──────────────────────────┘ │ ‹ [1] ›  1 – 25 of 312                         │
                                 └ the action bar, once rows are ticked ──────────┘

and a click on a company opens its account profile in place of the list, with a
way back (company_panel.py). Like the People page this is a VIEW: the
controller (companies_controller.py) owns the pool (companies.py), the filters,
the splits, the sorts and the pages, and hands one page here (`set_companies`);
every control says what the owner asked by a signal. The painted table is the
People page's own (cockpit._LeadTable, its header and delegates), so the two
pages look and behave alike — a tick column, a Bulk Selection caret, hover and
open-row grounds, resizable columns.

The action bar is Apollo's, minus what Prism has nothing real behind (Workflows,
Push to CRM, Prospect on LinkedIn): Save, Find people, Add to list, Export, and
under "More" Set stage, Look up details and Delete account.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QTableWidgetItem,
    QToolButton, QVBoxLayout, QWidget,
)

import i18n
import theme
from addons.leads import accounts as AC
from addons.leads import cockpit as K
from addons.leads import result_rows as RR
from addons.leads import companies as CO
from addons.leads.company_panel import CompanyPanel
from widgets import controls as C
from widgets import icons

_COLS = ("", "Company", "Industry", "Employees", "Stage", "People")
# Columns, by the People page's names: Company is its Lead, Industry its Focus,
# Employees its Fit (right-aligned), Stage its Status and People its Signal.
_C_TICK, _C_NAME, _C_INDUSTRY, _C_SIZE, _C_STAGE, _C_PEOPLE = range(len(_COLS))
_COL_WIDTH = {_C_TICK: 58, _C_NAME: 290, _C_SIZE: 100, _C_STAGE: 144, _C_PEOPLE: 124}
_COL_MIN = {_C_NAME: 150, _C_SIZE: 72, _C_STAGE: 104, _C_PEOPLE: 84}
_TABS = (("total", "Total"), ("net_new", "Net New"), ("saved", "Saved"))
_SORTS = (("relevance", "Relevance"), ("name", "Name A–Z"), ("newest", "Newest"),
          ("people", "Most people"), ("size", "Largest"))
_EMPTY_TITLE = "No companies yet"
_EMPTY_BODY = ("Import a sheet of companies with Import at the top right, or find people "
               "on the People page — the companies they work at show up here, and "
               "filters narrow them at once.")
_NO_MATCH_TITLE = "No company here matches these filters"
_NO_MATCH_BODY = ("Remove a filter on the left, or look under another tab.")
# A stage's pill: where a company stands with you.
_STAGE_TONE = {
    "Cold": (theme.INFO_INK, theme.INFO_BG),
    "Current Client": (theme.OK_INK, theme.OK_BG),
    "Active Opportunity": (theme.OK_INK, theme.OK_BG),
    "Dead Opportunity": (theme.NEUTRAL[700], theme.NEUTRAL[200]),
    "Do Not Prospect": (theme.ERR_INK, theme.ERR_BG),
}
_NET_NEW = "Net new"


class _SizeDelegate(K._CellDelegate):
    """The Employees column: the size as the record says it, right-aligned."""

    def cell(self, painter, rect, index, option):
        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return
        f = K._font(13)
        painter.setFont(f)
        painter.setPen(QColor(theme.NEUTRAL[800]))
        width = max(0, rect.width() - 2 * K._PAD)
        painter.drawText(QRect(rect.left() + K._PAD, rect.top(), width, rect.height()),
                         Qt.AlignRight | Qt.AlignVCenter,
                         QFontMetrics(f).elidedText(text, Qt.ElideLeft, width))


class _StageDelegate(K._CellDelegate):
    """The Stage column: an account's stage as a tinted pill; a company that is
    not an account yet says so in a quiet outline."""

    def cell(self, painter, rect, index, option):
        text = index.data(Qt.DisplayRole) or ""
        if not text:
            return
        f = K._font(11, QFont.DemiBold)
        fm = QFontMetrics(f)
        h = 22
        w = min(fm.horizontalAdvance(text) + 20, max(0, rect.width() - 2 * K._PAD))
        x, y = rect.left() + K._PAD, rect.top() + (rect.height() - h) // 2
        box = QRectF(x, y, w, h)
        painter.setRenderHint(QPainter.Antialiasing)
        if text == i18n.t(_NET_NEW):
            ink = theme.NEUTRAL[600]
            painter.setPen(QPen(QColor(theme.NEUTRAL[300]), 1))
            painter.setBrush(Qt.NoBrush)
            box = box.adjusted(0.5, 0.5, -0.5, -0.5)
        else:
            ink, bg = _STAGE_TONE.get(text, (theme.INFO_INK, theme.INFO_BG))
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(bg))
        painter.drawRoundedRect(box, box.height() / 2, box.height() / 2)
        painter.setFont(f)
        painter.setPen(theme.qcolor(ink))
        painter.drawText(QRect(x, y, w, h), Qt.AlignCenter,
                         fm.elidedText(text, Qt.ElideRight, max(0, w - 12)))


class _CompaniesBulkSelect(K._BulkSelect):
    """Apollo's Bulk Selection for companies: this page, all, or a number — the
    people-per-company limit has no meaning here."""

    def __init__(self, parent=None):
        super().__init__(parent)
        labels = self.findChildren(QLabel)
        if len(labels) >= 2:
            labels[0].setText(i18n.t("Select number of companies"))
            labels[1].hide()
        self.per_company.hide()
        self.number.setAccessibleName(i18n.t("Select number of companies"))


def _plural(n: int, one: str, many: str) -> str:
    return i18n.t(one) if n == 1 else i18n.t(many).format(n=f"{n:,}")


def _size_text(value) -> str:
    """A company's size as the table shows it: a bare number gets its thousands
    separators ("1200" is "1,200", "500+" stays "500+"); anything a sheet wrote
    in words ("51-200", "Large") is shown as written."""
    raw = " ".join(str(value or "").split())
    core = raw.replace(",", "")
    plus = core.endswith("+")
    core = core.rstrip("+")
    return f"{int(core):,}" + ("+" if plus else "") if core.isdigit() else raw


class CompaniesPage(QWidget):
    """The Companies tab. See the module docstring."""

    tabChanged = Signal(str)                # "total" | "net_new" | "saved"
    pageRequested = Signal(int)             # 0-based
    sortChanged = Signal(str)               # a _SORTS key
    queryChanged = Signal(str)              # the Search companies box
    importRequested = Signal(str)           # "accounts"
    openRequested = Signal(object)          # a Company opened from the table
    saveRequested = Signal(list)
    findPeopleRequested = Signal(list)
    listRequested = Signal(list)
    exportRequested = Signal(list)
    stageRequested = Signal(list, str)
    enrichRequested = Signal(list)
    deleteRequested = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []               # this page's companies
        self._universe: list = []           # everyone in the result, every page
        self._sel_keys: set = set()         # keys of everyone selected, across pages
        self._tab = "total"
        self._page_index = 0
        self._filter_count = 0
        self._col_pref = dict(_COL_WIDTH)
        self._fitting = False
        self._tab_counts = {key: 0 for key, _n in _TABS}
        self._open_company = None
        self._view = "list"                 # "list" (the rows, the default) or "table" (dense)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self._outer = QStackedWidget()
        outer.addWidget(self._outer)
        self._list_page = QWidget()
        lay = QVBoxLayout(self._list_page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._title_row())
        lay.addWidget(self._toolbar_row())
        self._split = K._Splitter(Qt.Horizontal)
        self._split.setHandleWidth(K._HANDLE_W)
        self._split.setChildrenCollapsible(False)
        self._split.addWidget(self._filter_rail())
        self._split.addWidget(self._center())
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([K._RAIL_W, 4 * K._RAIL_W])
        lay.addWidget(self._split, 1)
        self._outer.addWidget(self._list_page)
        # The profile replaces the list, Apollo's way: a page of its own with a
        # way back, and no rail (its facets have nothing to say about one company).
        self.panel = CompanyPanel()
        self.panel.backRequested.connect(self.close_profile)
        self._outer.addWidget(self.panel)
        self._show_empty(True)
        self._refresh_bulk()

    # ── construction ──────────────────────────────────────────────────────────
    def _title_row(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("companiesTitle")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(f"QFrame#companiesTitle{{background:{theme.CARD};border:none;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_3)
        title = QLabel(i18n.t("Companies"))
        title.setObjectName("companiesTitleText")
        title.setStyleSheet(theme.type_css("SECTION", theme.TEXT))
        lay.addWidget(title, 0, Qt.AlignVCenter)
        lay.addStretch(1)
        self._import_btn = self._menu_button(i18n.t("Import"), "companiesImportBtn")
        act = self._import_btn.menu().addAction(
            i18n.t("Accounts — companies from a CSV or Excel file…"))
        act.triggered.connect(lambda: self.importRequested.emit("accounts"))
        lay.addWidget(self._import_btn, 0, Qt.AlignVCenter)
        return bar

    @staticmethod
    def _menu_button(text: str, name: str) -> QToolButton:
        b = QToolButton()
        b.setObjectName(name)
        b.setText(text)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setToolButtonStyle(Qt.ToolButtonTextOnly)
        b.setCursor(Qt.PointingHandCursor)
        b.setMenu(QMenu(b))
        b.setStyleSheet(
            f"QToolButton#{name}{{background:{theme.CARD};color:{theme.NEUTRAL[800]};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 26px 5px 10px;min-height:20px;font-size:12px;"
            f"font-weight:600;}}"
            f"QToolButton#{name}:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}"
            f"QToolButton#{name}::menu-indicator{{image:url({K._asset('caret-down.svg')});"
            f"subcontrol-position:right center;subcontrol-origin:padding;"
            f"right:8px;width:12px;height:12px;}}")
        return b

    def _toolbar_row(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("companiesBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        bar.setStyleSheet(
            f"QFrame#companiesBar{{background:{theme.CARD};border:none;"
            f"border-bottom:1px solid {theme.HAIRLINE};}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self._filters_label = i18n.t("Hide filters")
        b = QPushButton(self._filters_label)
        b.setObjectName("companiesFiltersToggle")
        b.setCursor(Qt.PointingHandCursor)
        icons.button_icon(b, "list", 15, theme.NEUTRAL[700])
        b.setStyleSheet(
            f"QPushButton#companiesFiltersToggle{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[800]};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;padding:5px 12px 5px 10px;min-height:20px;"
            f"font-size:12px;font-weight:600;}}"
            f"QPushButton#companiesFiltersToggle:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}")
        b.clicked.connect(lambda: self.set_filters_shown(self._rail.isHidden()))
        self._filters_btn = b
        lay.addWidget(b)
        self._search = QLineEdit()
        self._search.setObjectName("companiesSearch")
        self._search.setPlaceholderText(i18n.t("Search companies"))
        self._search.setClearButtonEnabled(True)
        self._search.setMinimumWidth(150)
        self._search.setMaximumWidth(280)
        self._search.addAction(icons.icon("search", 15, theme.NEUTRAL[500]),
                               QLineEdit.LeadingPosition)
        # Debounced: every keystroke would otherwise re-filter the whole pool.
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(250)
        self._search_timer.timeout.connect(
            lambda: self.queryChanged.emit(self._search.text().strip()))
        self._search.textChanged.connect(lambda _t: self._search_timer.start())
        lay.addWidget(self._search)
        lay.addStretch(1)
        self._sort = QComboBox()
        self._sort.setObjectName("leadsSort")
        for key, label in _SORTS:
            self._sort.addItem(i18n.t(label), key)
        self._sort.setMinimumWidth(124)
        self._sort.setCursor(Qt.PointingHandCursor)
        self._sort.setToolTip(i18n.t("Sort"))
        self._sort.setStyleSheet(K._combo_sheet())
        self._sort.currentIndexChanged.connect(
            lambda _i: self.sortChanged.emit(self.sort_key()))
        self._view_toggle = RR.ViewToggle([("table", i18n.t("Table")), ("list", i18n.t("List"))], current=self._view)
        self._view_toggle.changed.connect(self._set_view)
        lay.addWidget(self._view_toggle)
        lay.addWidget(self._sort)
        return bar

    def _filter_rail(self) -> QWidget:
        """Apollo's left column: Total · Net New · Saved, then the filters (the
        controller mounts its FilterPanel — set_filter_panel). The rail scrolls
        on its own, so a short window never crushes a control."""
        self._rail = QScrollArea()
        self._rail.setObjectName("companiesRail")
        self._rail.setMinimumWidth(K._RAIL_MIN)
        self._rail.setMaximumWidth(K._RAIL_MAX)
        self._rail.setWidgetResizable(True)
        self._rail.setFrameShape(QFrame.NoFrame)
        self._rail.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rail.verticalScrollBar().setSingleStep(K._STEP)
        self._rail.setStyleSheet(
            f"QScrollArea#companiesRail{{background:{theme.CARD};border:none;}}")
        inner = QWidget()
        inner.setObjectName("companiesRailInner")
        inner.setAttribute(Qt.WA_StyledBackground, True)
        inner.setStyleSheet(f"QWidget#companiesRailInner{{background:{theme.CARD};}}")
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        lay.setSpacing(theme.SPACE_3)
        lay.addWidget(self._tabs_bar())
        self._filter_slot = QVBoxLayout()
        self._filter_slot.setContentsMargins(0, 0, 0, 0)
        self._filter_slot.setSpacing(0)
        lay.addLayout(self._filter_slot)
        lay.addStretch(1)
        note = QLabel(i18n.t("Saving a company makes it an account: a stage, lists, "
                             "notes, tasks and its activity."))
        note.setWordWrap(True)
        note.setStyleSheet(f"color:{theme.NEUTRAL[600]};font-size:11px;")
        lay.addWidget(note)
        self._rail.setWidget(inner)
        return self._rail

    def _tabs_bar(self) -> QWidget:
        seg = QFrame()
        seg.setObjectName("companyTabs")
        seg.setAttribute(Qt.WA_StyledBackground, True)
        seg.setStyleSheet(
            f"QFrame#companyTabs{{background:{theme.WELL};border:1px solid "
            f"{theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;}}"
            f"QFrame#companyTabs QPushButton{{background:transparent;border:none;"
            f"border-radius:{theme.R_CHIP}px;color:{theme.NEUTRAL[600]};"
            f"padding:5px 4px;font-size:12px;font-weight:600;text-align:center;}}"
            f"QFrame#companyTabs QPushButton:hover{{color:{theme.TEXT};}}"
            f"QFrame#companyTabs QPushButton:checked{{background:{theme.CARD};"
            f"color:{theme.TEXT};}}")
        lay = QHBoxLayout(seg)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._tab_btns: dict = {}
        for key, _name in _TABS:
            b = QPushButton()
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, k=key: self._pick_tab(k))
            lay.addWidget(b, 1)
            self._tab_btns[key] = b
        self._paint_tabs()
        return seg

    def _paint_tabs(self) -> None:
        for key, name in _TABS:
            b = self._tab_btns[key]
            b.setText(f"{i18n.t(name)}\n{self._tab_counts.get(key, 0):,}")
            b.setChecked(key == self._tab)

    def _pick_tab(self, key: str) -> None:
        self._tab = key
        self._paint_tabs()
        self.tabChanged.emit(key)

    def tab(self) -> str:
        return self._tab

    def set_tab(self, key: str) -> None:
        """Select a tab without emitting — the controller restoring one."""
        if key in self._tab_btns:
            self._tab = key
            self._paint_tabs()

    def set_counts(self, counts: dict) -> None:
        for key, _name in _TABS:
            self._tab_counts[key] = int((counts or {}).get(key, 0) or 0)
        self._paint_tabs()

    def set_filter_panel(self, widget: QWidget) -> None:
        """Mount the filter column (a FilterPanel of kind "company") under the tabs."""
        K._clear(self._filter_slot)
        self._filter_slot.addWidget(widget)

    def set_filters_shown(self, show: bool) -> None:
        rail = self._rail
        if show != rail.isHidden():
            return
        if show:
            rail.show()
            self._split.setSizes([K._RAIL_W, max(1, self._split.width() - K._RAIL_W)])
        else:
            rail.hide()
        self._filters_label = i18n.t("Hide filters") if show else i18n.t("Show filters")
        self._sync_filters_text()
        self._split.refresh()

    def set_filter_count(self, n: int) -> None:
        """How many filters are on — shown on Hide filters, Apollo's way."""
        self._filter_count = max(0, int(n or 0))
        self._sync_filters_text()

    def _sync_filters_text(self) -> None:
        self._filters_btn.setText(f"{self._filters_label}  {self._filter_count}"
                                  if self._filter_count else self._filters_label)

    def sort_key(self) -> str:
        return self._sort.currentData() or "relevance"

    def set_sort(self, key: str) -> None:
        i = self._sort.findData(key)
        if i >= 0 and i != self._sort.currentIndex():
            self._sort.blockSignals(True)
            self._sort.setCurrentIndex(i)
            self._sort.blockSignals(False)

    def query(self) -> str:
        return self._search.text().strip()

    # ── the results ───────────────────────────────────────────────────────────
    def _center(self) -> QWidget:
        wrap = QWidget()
        wrap.setMinimumWidth(K._TABLE_MIN)
        col = QVBoxLayout(wrap)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self._table = self._build_table()
        self._empty = C.EmptyState("building", i18n.t(_EMPTY_TITLE), i18n.t(_EMPTY_BODY))
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._table)         # 0 — the table
        self._view_stack.addWidget(self._empty)         # 1 — nothing to show
        self._view_stack.addWidget(self._build_rows())  # 2 — the rows
        col.addWidget(self._view_stack, 1)
        col.addWidget(self._pager_bar())
        self._bulk = self._bulk_bar()
        col.addWidget(self._bulk)
        return wrap

    def _build_table(self):
        t = K._LeadTable(0, len(_COLS))
        t.setObjectName("leadsTable")           # the People table's sheet and hover rules
        self._head = K._LeadHeader(t)
        t.setHorizontalHeader(self._head)
        t.setHorizontalHeaderLabels([i18n.t(c) for c in _COLS])
        t.horizontalHeaderItem(_C_TICK).setToolTip(i18n.t("Select all"))
        rows = t.verticalHeader()
        rows.setVisible(False)
        rows.setSectionResizeMode(QHeaderView.Fixed)
        rows.setDefaultSectionSize(K._ROW_H)
        t.setShowGrid(False)
        t.setAlternatingRowColors(False)
        t.setWordWrap(False)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        t.verticalScrollBar().setSingleStep(K._STEP)
        t.horizontalScrollBar().setSingleStep(K._STEP)
        t.setItemDelegateForColumn(_C_TICK, K._TickDelegate(t))
        t.setItemDelegateForColumn(_C_NAME, K._LeadDelegate(t))
        t.setItemDelegateForColumn(_C_INDUSTRY, K._FocusDelegate(t))
        t.setItemDelegateForColumn(_C_SIZE, _SizeDelegate(t))
        t.setItemDelegateForColumn(_C_STAGE, _StageDelegate(t))
        t.setItemDelegateForColumn(_C_PEOPLE, K._PillDelegate(t))
        head = self._head
        head.setStretchLastSection(False)
        head.setMinimumSectionSize(40)
        for c in range(len(_COLS)):
            head.setSectionResizeMode(c, QHeaderView.Interactive if c in _COL_MIN
                                      else QHeaderView.Fixed)
            if c in _COL_WIDTH:
                head.resizeSection(c, _COL_WIDTH[c])
        head.sectionResized.connect(self._on_section_resized)
        head.toggleAll.connect(self._toggle_all_visible)
        head.bulkMenuRequested.connect(self._open_bulk_select)
        self._bulk_select = _CompaniesBulkSelect(self)
        self._bulk_select.hide()
        self._bulk_select.pageRequested.connect(lambda: self._mark(self._rows, True))
        self._bulk_select.allRequested.connect(self._select_all)
        self._bulk_select.numberRequested.connect(lambda n, _per: self._select_number(n))
        self._bulk_select.clearRequested.connect(self.clear_selection)
        t.tickRequested.connect(self._tick_row)
        t.escapePressed.connect(self.close_profile)
        t.itemChanged.connect(self._on_item_changed)
        t.cellClicked.connect(self._on_cell_clicked)
        t.cellActivated.connect(self._on_cell_clicked)
        self._table_vp = t.viewport()
        self._table_vp.installEventFilter(self)
        t.setStyleSheet(
            f"QTableWidget#leadsTable{{background:{theme.CARD};border:none;"
            f"border-radius:0px;outline:0;}}"
            f"QTableWidget#leadsTable QHeaderView{{background:{theme.CARD};border:none;}}"
            f"QTableWidget#leadsTable QScrollBar:horizontal{{height:9px;"
            f"background:transparent;margin:0px;}}"
            f"QTableWidget#leadsTable QScrollBar::handle:horizontal{{"
            f"background:{theme.NEUTRAL[300]};border-radius:4px;min-width:30px;}}"
            f"QTableWidget#leadsTable QScrollBar::add-line:horizontal,"
            f"QTableWidget#leadsTable QScrollBar::sub-line:horizontal{{width:0px;}}")
        return t

    def eventFilter(self, obj, event):
        if (event.type() in (QEvent.Resize, QEvent.Show)
                and obj is getattr(self, "_table_vp", None)):
            self._fit_columns()
        return super().eventFilter(obj, event)

    # columns ------------------------------------------------------------------
    def _resize_col(self, col: int, width: int) -> None:
        self._fitting = True
        try:
            self._head.resizeSection(col, width)
        finally:
            self._fitting = False

    def _on_section_resized(self, col: int, _old: int, new: int) -> None:
        if self._fitting or col not in _COL_MIN:
            return
        if new < _COL_MIN[col]:
            new = _COL_MIN[col]
            self._resize_col(col, new)
        self._col_pref[col] = new
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Lay the columns into the table's width. Industry takes what the
        others leave, never less than the People page's Focus minimum; when
        the table narrows the others give way, Company first, each down to its
        minimum, and grow back once there is room."""
        t = self._table
        if not t.isVisible():
            return
        head = self._head
        room = t.viewport().width() - head.sectionSize(_C_TICK) - K._FOCUS_MIN
        width = {c: self._col_pref[c] for c in _COL_MIN}
        over = sum(width.values()) - room
        for c in (_C_NAME, _C_PEOPLE, _C_STAGE, _C_SIZE):
            give = max(0, min(over, width[c] - _COL_MIN[c]))
            width[c] -= give
            over -= give
        for c, w in width.items():
            if head.sectionSize(c) != w:
                self._resize_col(c, w)
        rest = t.viewport().width() - sum(head.sectionSize(c) for c in range(head.count())
                                          if c != _C_INDUSTRY)
        if head.sectionSize(_C_INDUSTRY) != max(K._FOCUS_MIN, rest):
            self._resize_col(_C_INDUSTRY, max(K._FOCUS_MIN, rest))

    # the pager ----------------------------------------------------------------
    def _pager_bar(self) -> QWidget:
        self._pager = QFrame()
        self._pager.setObjectName("companiesPager")
        self._pager.setAttribute(Qt.WA_StyledBackground, True)
        self._pager.setStyleSheet(
            f"QFrame#companiesPager{{background:{theme.CARD};border:none;"
            f"border-top:1px solid {theme.HAIRLINE};}}"
            f"QFrame#companiesPager QPushButton{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[800]};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;padding:5px 10px;min-height:20px;"
            f"min-width:12px;font-size:13px;font-weight:600;}}"
            f"QFrame#companiesPager QPushButton:disabled{{color:{theme.NEUTRAL[300]};"
            f"border-color:{theme.HAIRLINE};}}")
        lay = QHBoxLayout(self._pager)
        lay.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self._prev_btn = QPushButton("‹")
        self._prev_btn.setToolTip(i18n.t("Previous page"))
        self._next_btn = QPushButton("›")
        self._next_btn.setToolTip(i18n.t("Next page"))
        self._page_box = QComboBox()
        self._page_box.setObjectName("leadsSort")
        self._page_box.setStyleSheet(K._combo_sheet())
        self._page_box.setFixedWidth(72)
        for b in (self._prev_btn, self._next_btn):
            b.setCursor(Qt.PointingHandCursor)
        self._prev_btn.clicked.connect(lambda: self.pageRequested.emit(self._page_index - 1))
        self._next_btn.clicked.connect(lambda: self.pageRequested.emit(self._page_index + 1))
        self._page_box.activated.connect(lambda i: self.pageRequested.emit(i))
        self._range_lbl = QLabel("")
        self._range_lbl.setStyleSheet(f"color:{theme.TEXT};font-size:13px;font-weight:600;")
        lay.addWidget(self._prev_btn)
        lay.addWidget(self._page_box)
        lay.addWidget(self._next_btn)
        lay.addSpacing(theme.SPACE_2)
        lay.addWidget(self._range_lbl)
        lay.addStretch(1)
        self._pager.hide()
        return self._pager

    def set_page(self, info: dict) -> None:
        """Show which page is on screen — companies.page()'s dict."""
        info = info or {}
        pages = max(1, int(info.get("pages", 1) or 1))
        self._page_index = int(info.get("page", 0) or 0)
        total = int(info.get("total", 0) or 0)
        self._page_box.blockSignals(True)
        if self._page_box.count() != pages:
            self._page_box.clear()
            self._page_box.addItems([str(i + 1) for i in range(pages)])
        self._page_box.setCurrentIndex(min(self._page_index, pages - 1))
        self._page_box.blockSignals(False)
        self._prev_btn.setEnabled(self._page_index > 0)
        self._next_btn.setEnabled(self._page_index < pages - 1)
        self._range_lbl.setText(i18n.t("{a} - {b} of {n}").format(
            a=f"{info.get('start', 0):,}", b=f"{info.get('end', 0):,}", n=f"{total:,}"))
        self._pager.setVisible(total > 0)

    # the action bar -----------------------------------------------------------
    def _bulk_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("bulkBar")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#bulkBar{{background:{theme.CARD};border:none;"
            f"border-top:1px solid {theme.DIVIDER};}}"
            f"QFrame#bulkBar QLabel{{color:{theme.TEXT};font-size:13px;font-weight:600;"
            f"background:transparent;border:none;}}"
            f"QFrame#bulkBar QPushButton{{color:{theme.NEUTRAL[800]};background:{theme.CARD};"
            f"border:1px solid {theme.BORDER};border-radius:{theme.R_CONTROL}px;"
            f"padding:5px 14px;min-height:20px;font-family:'{theme.FONT_BODY}';"
            f"font-size:12px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton:hover{{background:{theme.WELL};"
            f"border-color:{theme.NEUTRAL[300]};}}"
            f"QFrame#bulkBar QPushButton:disabled{{color:{theme.NEUTRAL[400]};"
            f"border-color:{theme.HAIRLINE};background:{theme.CARD};}}"
            f"QFrame#bulkBar QPushButton#primary{{background:{theme.ACCENT};"
            f"border-color:{theme.ACCENT};color:#fff;}}"
            f"QFrame#bulkBar QPushButton#primary:hover{{background:{theme.ACCENT_RAMP[600]};"
            f"border-color:{theme.ACCENT_RAMP[600]};}}"
            f"QFrame#bulkBar QPushButton#bulkLink{{background:transparent;border:none;"
            f"color:{theme.ACCENT};padding:5px 6px;font-size:13px;font-weight:600;}}"
            f"QFrame#bulkBar QPushButton#bulkLink:hover{{color:{theme.ACCENT_RAMP[700]};"
            f"text-decoration:underline;}}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 10, theme.SPACE_4, 10)
        lay.setSpacing(theme.SPACE_2)
        self._sel_lbl = QLabel(i18n.t("0 selected"))
        lay.addWidget(self._sel_lbl)
        lay.addSpacing(theme.SPACE_2)
        self._sel_all = self._link(i18n.t("Select all"))
        self._sel_all.clicked.connect(self._select_all)
        lay.addWidget(self._sel_all)
        self._bulk_clear = self._link(i18n.t("Clear selection"))
        self._bulk_clear.clicked.connect(self.clear_selection)
        lay.addWidget(self._bulk_clear)
        lay.addStretch(1)
        self._b_save = QPushButton(i18n.t("Save"))
        self._b_save.setToolTip(i18n.t("Save the selected companies as accounts — they "
                                       "move from Net New to Saved."))
        self._b_find = QPushButton(i18n.t("Find people"))
        self._b_find.setObjectName("primary")
        self._b_find.setToolTip(i18n.t("Go to the People page, filtered to the people at "
                                       "the selected companies — and search for more."))
        self._b_list = QPushButton(i18n.t("Add to list"))
        self._b_export = QPushButton(i18n.t("Export"))
        self._b_more = QToolButton()
        self._b_more.setObjectName("companiesMoreBtn")
        self._b_more.setText(i18n.t("More"))
        self._b_more.setPopupMode(QToolButton.InstantPopup)
        self._b_more.setCursor(Qt.PointingHandCursor)
        self._b_more.setToolTip(i18n.t("More actions for the selected companies"))
        self._b_more.setStyleSheet(
            f"QToolButton#companiesMoreBtn{{background:{theme.CARD};"
            f"color:{theme.NEUTRAL[800]};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;padding:5px 24px 5px 14px;min-height:20px;"
            f"font-size:12px;font-weight:600;}}"
            f"QToolButton#companiesMoreBtn:hover{{background:{theme.WELL};}}"
            f"QToolButton#companiesMoreBtn:disabled{{color:{theme.NEUTRAL[400]};"
            f"border-color:{theme.HAIRLINE};}}"
            f"QToolButton#companiesMoreBtn::menu-indicator{{image:url("
            f"{K._asset('caret-down.svg')});subcontrol-position:right center;"
            f"subcontrol-origin:padding;right:8px;width:12px;height:12px;}}")
        more = QMenu(self._b_more)
        stage_menu = more.addMenu(i18n.t("Set stage"))
        for stage in AC.STAGES:
            act = stage_menu.addAction(stage)       # a stage is a record's value: as kept
            act.triggered.connect(lambda _=False, s=stage: self.stageRequested.emit(
                self.selected(), s))
        self._act_enrich = more.addAction(i18n.t("Look up website, size and HQ…"))
        self._act_enrich.triggered.connect(lambda: self.enrichRequested.emit(self.selected()))
        more.addSeparator()
        self._act_delete = more.addAction(i18n.t("Delete accounts…"))
        self._act_delete.triggered.connect(lambda: self.deleteRequested.emit(self.selected()))
        self._b_more.setMenu(more)
        self._b_save.clicked.connect(lambda: self.saveRequested.emit(self.selected()))
        self._b_find.clicked.connect(lambda: self.findPeopleRequested.emit(self.selected()))
        self._b_list.clicked.connect(lambda: self.listRequested.emit(self.selected()))
        self._b_export.clicked.connect(lambda: self.exportRequested.emit(self.selected()))
        for b in (self._b_save, self._b_list, self._b_export, self._b_more, self._b_find):
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        bar.hide()
        self._bulk_bar_w = bar
        return bar

    @staticmethod
    def _link(text: str) -> QPushButton:
        b = QPushButton(text)
        b.setObjectName("bulkLink")
        b.setCursor(Qt.PointingHandCursor)
        return b

    # ── data ──────────────────────────────────────────────────────────────────
    def set_companies(self, rows, page=None, counts=None, universe=None,
                      empty_text=None) -> None:
        """One page of the pool — companies.Company rows the controller has
        already filtered, split into Total / Net New / Saved, sorted and paged
        — shown in exactly that order. `universe` is everyone in the result on
        every page, in order: what Select all and Select number of companies
        choose from (the page alone when not given). Whoever was selected stays
        selected."""
        self._rows = list(rows or ())
        self._universe = list(universe) if universe is not None else list(self._rows)
        if empty_text:
            self._empty.set_text(*empty_text)
        else:
            self._empty.set_text(i18n.t(_EMPTY_TITLE), i18n.t(_EMPTY_BODY))
        self._show_empty(not self._rows)
        self._fill_table()
        if counts is not None:
            self.set_counts(counts)
        self.set_page(page or {})
        self._refresh_bulk()

    def _show_empty(self, empty: bool) -> None:
        self._view_stack.setCurrentIndex(1 if empty else (2 if self._view == "list" else 0))
        if empty:
            self._bulk_bar_w.hide()

    def _fill_table(self) -> None:
        t = self._table
        t.setSortingEnabled(False)
        t.setRowCount(0)
        t.blockSignals(True)
        for idx, c in enumerate(self._rows):
            row = t.rowCount()
            t.insertRow(row)
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            chk.setCheckState(Qt.Checked if self._is_sel(c) else Qt.Unchecked)
            chk.setData(Qt.UserRole, idx)
            t.setItem(row, _C_TICK, chk)
            name = QTableWidgetItem(c.name or i18n.t("(no name)"))
            second = c.domain or (c.website.split("://", 1)[-1].rstrip("/") if c.website else "")
            name.setData(K._COMPANY_ROLE, second)
            name.setToolTip(" — ".join(p for p in (c.name, second) if p))
            t.setItem(row, _C_NAME, name)
            focus = QTableWidgetItem(c.industry or "")
            focus.setData(K._WHERE_ROLE, c.location or "")
            focus.setToolTip(" — ".join(p for p in (c.industry, c.location) if p))
            t.setItem(row, _C_INDUSTRY, focus)
            t.setItem(row, _C_SIZE, QTableWidgetItem(_size_text(c.headcount)))
            t.setItem(row, _C_STAGE, QTableWidgetItem(c.stage if c.saved else i18n.t(_NET_NEW)))
            people = c.people_count
            t.setItem(row, _C_PEOPLE, QTableWidgetItem(
                "" if not people else _plural(people, "1 person", "{n} people")))
        t.blockSignals(False)
        self._fit_columns()
        self._fill_rows()

    # ── the rows (result_rows) ─────────────────────────────────────────────────
    def _build_rows(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        scroll.verticalScrollBar().setSingleStep(K._STEP)
        host = QWidget()
        hl = QVBoxLayout(host)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        hl.setSpacing(0)
        self._row_list = RR.ResultList()
        hl.addWidget(self._row_list)
        hl.addStretch(1)
        scroll.setWidget(host)
        self._rows_scroll = scroll
        self._row_checks = {}
        return scroll

    def _set_view(self, view: str) -> None:
        self._view = view
        self._view_toggle.set_current(view)
        if self._rows:
            self._view_stack.setCurrentIndex(2 if view == "list" else 0)

    def _fill_rows(self) -> None:
        self._row_list.clear()
        self._row_checks = {}
        self._row_list.add_all([self._row_for(i, c) for i, c in enumerate(self._rows)])

    def _row_for(self, idx: int, c) -> QWidget:
        """One company as a row: its name and web address, what it does and where, its stage and people, and what to do with it."""
        second = c.domain or (c.website.split("://", 1)[-1].rstrip("/") if c.website else "")
        subline = " · ".join(p for p in (c.industry, c.location,
                                         (_size_text(c.headcount) + " " + i18n.t("employees")) if c.headcount else "") if p)
        pills = [(c.stage or i18n.t("Saved"), "ok") if c.saved else (i18n.t(_NET_NEW), "quiet")]
        if c.people_count:
            pills.append((_plural(c.people_count, "1 person", "{n} people"), "info"))
        actions = [(i18n.t("Open"), True, lambda _=False, i=idx: self._open_row(i))]
        if not c.saved:
            actions.append((i18n.t("Save"), False, lambda _=False, co=c: self.saveRequested.emit([co])))
        row = RR.ResultRow(RR.RowSpec(
            key=idx, name=c.name or i18n.t("(no name)"), company=second, subline=subline, pills=pills, actions=actions,
            checked=self._is_sel(c), tooltip=" — ".join(p for p in (c.name, second) if p)))
        row.clicked.connect(self._open_row)
        row.toggled.connect(lambda i, on: self._mark([self._rows[i]], on) if 0 <= i < len(self._rows) else None)
        self._row_checks[idx] = row.check
        return row

    def _open_row(self, idx: int) -> None:
        if 0 <= idx < len(self._rows):
            self._open_company = self._rows[idx]
            self.openRequested.emit(self._rows[idx])

    # ── selection, across pages ───────────────────────────────────────────────
    def _is_sel(self, company) -> bool:
        keys = getattr(company, "keys", None)
        return bool(keys) and not keys.isdisjoint(self._sel_keys)

    def _mark(self, companies, on: bool) -> None:
        for c in companies or ():
            keys = getattr(c, "keys", None) or frozenset()
            if on:
                self._sel_keys |= keys
            else:
                self._sel_keys -= keys
        self._resync_ticks()

    def _resync_ticks(self) -> None:
        t = self._table
        t.blockSignals(True)
        for row in range(t.rowCount()):
            it = t.item(row, _C_TICK)
            if it is None:
                continue
            idx = it.data(Qt.UserRole)
            want = Qt.Checked if (idx is not None and 0 <= idx < len(self._rows)
                                  and self._is_sel(self._rows[idx])) else Qt.Unchecked
            if it.checkState() != want:
                it.setCheckState(want)
        t.blockSignals(False)
        for idx, box in getattr(self, "_row_checks", {}).items():
            if 0 <= idx < len(self._rows):
                want = self._is_sel(self._rows[idx])
                if box.isChecked() != want:
                    box.blockSignals(True)
                    box.setChecked(want)
                    box.blockSignals(False)
        self._refresh_bulk()

    def selected(self) -> list:
        """Everyone selected, on every page, in the result's order."""
        out = [c for c in self._universe if self._is_sel(c)]
        have = {id(c) for c in out}
        return out + [c for c in self._rows if self._is_sel(c) and id(c) not in have]

    def clear_selection(self) -> None:
        """Forget who is selected — the controller asks when the filters, the
        tab or the search box change what the result IS (Apollo starts a new
        search with nothing selected); a new page or a new sort keeps it."""
        self._sel_keys = set()
        self._resync_ticks()

    def _select_all(self) -> None:
        self._mark(self._universe, True)

    def _select_number(self, n: int) -> None:
        """Select number of companies: the first `n` of the result in its
        order. It replaces the selection, as Apollo's does."""
        self._sel_keys = set()
        self._mark(CO.pick(self._universe, n), True)

    def _tick_row(self, row: int) -> None:
        it = self._table.item(row, _C_TICK)
        if it is not None:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

    def _on_item_changed(self, item) -> None:
        if item.column() != _C_TICK:
            return
        idx = item.data(Qt.UserRole)
        if idx is None or not 0 <= idx < len(self._rows):
            return
        self._mark([self._rows[idx]], item.checkState() == Qt.Checked)

    def _toggle_all_visible(self) -> None:
        """The header checkbox: tick this page — or, when all of it is ticked
        already, clear it."""
        on = not (self._rows and all(self._is_sel(c) for c in self._rows))
        self._mark(self._rows, on)

    def _open_bulk_select(self) -> None:
        pop = self._bulk_select
        pop.set_counts(len(self._rows), len(self._universe), len(self.selected()))
        pop.adjustSize()
        at = self._head.mapToGlobal(self._head.caret_rect().bottomLeft())
        pop.move(at.x() - K._TICK_BOX // 2, at.y() + 2)
        pop.show()
        pop.raise_()

    def _refresh_bulk(self) -> None:
        picked = self.selected()
        n = len(picked)
        self._sel_lbl.setText(i18n.t("{n} selected").format(n=f"{n:,}"))
        shown = len(self._universe)
        self._sel_all.setText(i18n.t("Select all {n}").format(n=f"{shown:,}"))
        self._sel_all.setVisible(0 < n < shown)
        self._bulk_bar_w.setVisible(n > 0 and bool(self._rows))
        self._act_delete.setEnabled(any(c.saved for c in picked))
        self._act_enrich.setEnabled(any(CompaniesPage.needs_lookup(c) for c in picked))
        on_page = sum(1 for c in self._rows if self._is_sel(c))
        self._head.set_check_state(Qt.Unchecked if on_page == 0 else
                                   Qt.Checked if on_page == len(self._rows)
                                   else Qt.PartiallyChecked)

    @staticmethod
    def needs_lookup(company) -> bool:
        """Whether the Exa lookup has anything to fill in: it has a name or a
        domain to ask about, and lacks a website, size, revenue or HQ."""
        if not (company.name or company.domain):
            return False
        return not (company.website or company.domain) or not (
            company.headcount and company.revenue and company.location)

    # ── opening a company ─────────────────────────────────────────────────────
    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == _C_TICK:
            return
        it = self._table.item(row, _C_TICK)
        idx = it.data(Qt.UserRole) if it is not None else None
        if idx is not None and 0 <= idx < len(self._rows):
            self._open_company = self._rows[idx]
            self.openRequested.emit(self._rows[idx])

    def show_profile(self, view) -> None:
        """Replace the list with one company's profile (company_panel.CompanyView)."""
        self.panel.show_company(view)
        self._open_company = view.company if view is not None else None
        self._outer.setCurrentIndex(1)

    def close_profile(self) -> None:
        """Back to the list; no row stays highlighted to reopen the company."""
        self._open_company = None
        self.panel.show_company(None)
        self._outer.setCurrentIndex(0)
        self._table.blockSignals(True)
        self._table.setCurrentCell(-1, -1)
        self._table.clearSelection()
        self._table.blockSignals(False)

    def profile_open(self) -> bool:
        return self._outer.currentIndex() == 1

    def open_company(self):
        """The company whose profile is on screen, or None."""
        return self._open_company if self.profile_open() else None

    def set_empty_text(self, title: str = "", body: str = "") -> None:
        self._empty.set_text(title or i18n.t(_EMPTY_TITLE), body or i18n.t(_EMPTY_BODY))

