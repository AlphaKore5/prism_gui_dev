"""The Contacts tab — everyone your number has talked to, as a working table.

Search, filter (the same builder Campaigns uses), sort, choose columns, select people and act on them: broadcast to them,
tag them, block them, export them, delete them. Add one person by hand, import a spreadsheet and look back at past imports.
The profile of whoever is selected sits on the right.

    toolbar   search · Filters · Saved segments · Columns · Add contact · Import · Actions
    table     50 a page; click a heading to sort; the first column selects
    profile   the shared ProfilePanel (details, attributes, tags, journey, consent)

What the table shows comes from prism-wa through the `contacts/list` platform route, filtered there: a filter that matches
a thousand people costs the same as one that matches three.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QMenu, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import i18n
import paths
import theme
from addons.whatsapp import filter_model as FM
from addons.whatsapp import ui
from addons.whatsapp.chat import short_time
from addons.whatsapp.profile_panel import ProfilePanel
from widgets import controls as C
from widgets.loader import Skeleton

PAGE = 50
# (key, heading, sortable server key or None) — the columns a team picks from. Attribute columns are added after these.
BUILT_IN = (("name", "Name", "name"), ("phone", "Mobile", "phone"), ("tags", "Tags", "tags"), ("source", "Source", "source"),
            ("window", "Window", None), ("state", "State", None), ("last_seen", "Last wrote", "last_seen"), ("created_at", "Added", "created"),
            ("first_msg_tag", "First message", None), ("email", "Email", None), ("company", "Company", None))
DEFAULT_COLUMNS = ("name", "phone", "tags", "source", "state", "last_seen")


def _heading(key: str) -> str:
    return {"name": i18n.t("Name"), "phone": i18n.t("Mobile"), "tags": i18n.t("Tags"), "source": i18n.t("Source"), "window": i18n.t("Window"),
            "state": i18n.t("State"), "last_seen": i18n.t("Last wrote"), "created_at": i18n.t("Added"),
            "first_msg_tag": i18n.t("First message"), "email": i18n.t("Email"), "company": i18n.t("Company")}.get(key, key)


def _state_words(state) -> str:
    return {"active": i18n.t("With the bot"), "requesting": i18n.t("Needs a person"), "intervened": i18n.t("With an agent"),
            "human_takeover": i18n.t("With an agent"), "closed": i18n.t("Resolved")}.get(state or "", "")


def cell_text(row: dict, key: str) -> str:
    if key == "tags":
        return ", ".join(row.get("tags") or [])
    if key == "window":
        return i18n.t("Open") if row.get("window_open") else i18n.t("Closed")
    if key == "state":
        return _state_words(row.get("state"))
    if key in ("last_seen", "created_at"):
        return short_time(row.get(key) or "") if row.get(key) else ""
    if key.startswith("attr:"):
        v = (row.get("attrs") or {}).get(key[5:])
        return "" if v is None else str(v)
    if key == "phone":
        p = row.get("phone") or ""
        return p if p.startswith("*") or not p else "+" + p
    return "" if row.get(key) is None else str(row.get(key))


def _card(objname: str) -> QFrame:
    f = QFrame()
    f.setObjectName(objname)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setStyleSheet(f"#{objname} {{ background: {theme.CARD}; border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CARD}px; }}")
    return f


class ContactsPage(QWidget):
    countChanged = Signal(int)
    broadcastRequested = Signal(dict)          # {"contact_ids": [...]} or {"filter": {...}} — open the campaign composer for them
    manageRequested = Signal(str)              # "tags" | "compliance" — open that Settings section
    orderRequested = Signal(dict)              # "New order" on a person: open the Shop with them chosen
    formRequested = Signal(dict)               # "Send a form…" on a person: open Forms with them chosen

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._rows: list = []
        self._total = 0
        self._offset = 0
        self._chip = "all"
        self._user_filter: dict = {}
        self._segment_name = ""
        self._sort, self._dir = "created", "desc"
        self._attr_keys: list = []
        self._defs: dict = {}
        self._tag_names: list = []
        self._columns: list = list(DEFAULT_COLUMNS)
        self._selected: set = set()
        self._all_matching = False
        self._current_id = None
        self._request = 0
        self._loaded = False
        self._sticky = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(theme.SPACE_3)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")
        root.addWidget(split)

        left = _card("waContacts")
        col = QVBoxLayout(left)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_4, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_3)
        col.addLayout(self._toolbar())
        self.summary = C.label("", level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True)
        self.summary_row = QWidget()
        sl = QHBoxLayout(self.summary_row)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.summary, stretch=1)
        sl.addWidget(C.button(i18n.t("Clear filter"), "tertiary", small=True, on_click=self._clear_filter))
        self.summary_row.hide()
        col.addWidget(self.summary_row)
        col.addWidget(self._bulk_bar())

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setFrameShape(QFrame.NoFrame)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)       # the cells are left-aligned; a centred heading sits off its column
        self.table.horizontalHeader().setSectionsClickable(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().sectionClicked.connect(self._on_header)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.currentCellChanged.connect(lambda r, _c, _pr, _pc: self._on_row(r))
        self.table.setAccessibleName(i18n.t("Contacts"))
        self.stack.addWidget(self.table)
        self.empty = C.EmptyState("user", i18n.t("No contacts yet"),
                                  i18n.t("People are added automatically the first time they message your number. You can also add one or import a file."))
        self.stack.addWidget(self.empty)
        self.loading = Skeleton(5)                  # the first page, while it comes (index 2: the table is 0 and the empty state 1)
        self.stack.addWidget(self.loading)
        col.addWidget(self.stack, stretch=1)

        foot = QHBoxLayout()
        self.status = C.label("", level="META", colour=theme.NEUTRAL[500])
        foot.addWidget(self.status, stretch=1)
        self.prev_btn = C.button(i18n.t("Previous"), "tertiary", small=True, on_click=lambda: self._page(-1))
        self.next_btn = C.button(i18n.t("Next"), "tertiary", small=True, on_click=lambda: self._page(1))
        foot.addWidget(self.prev_btn)
        foot.addWidget(self.next_btn)
        col.addLayout(foot)
        split.addWidget(left)

        right = _card("waContactDetail")
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.panel = ProfilePanel()
        self.panel.changed.connect(self._profile_changed)
        self.panel.deleted.connect(lambda _cid: self.refresh())
        self.panel.sendTemplate.connect(self._send_template)
        self.panel.startOrder.connect(self.orderRequested)
        self.panel.sendForm.connect(self.formRequested)
        right.setMinimumWidth(330)
        right.setMaximumWidth(460)
        rl.addWidget(self.panel)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([760, 380])

    # ── pieces ───────────────────────────────────────────────────────────────
    def _toolbar(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_2)
        self.search = C.SearchField(i18n.t("Search name, number, company or email"))
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self._search_now)
        self.search.changed.connect(lambda _t: (setattr(self, "_sticky", ""), self._debounce.start()))
        top.addWidget(self.search, stretch=1)
        self.filter_btn = C.button(i18n.t("Filters"), "secondary", icon_name="sliders", small=True, on_click=self._open_filter)
        top.addWidget(self.filter_btn)
        top.addWidget(C.button(i18n.t("Segments"), "secondary", small=True, on_click=self._open_segments))
        self.columns_btn = C.button(i18n.t("Columns"), "secondary", small=True, on_click=self._columns_menu)
        top.addWidget(self.columns_btn)
        box.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.chips = C.FilterChips([("all", i18n.t("All")), ("in", i18n.t("Opted in")), ("out", i18n.t("Opted out")), ("blocked", i18n.t("Blocked"))], current="all")
        self.chips.changed.connect(self._on_chip)
        self.chips.setMinimumWidth(380)                                  # or the four chips wrap into a column
        row.addWidget(self.chips)
        row.addStretch(1)
        row.addWidget(C.button(i18n.t("Add contact"), "secondary", icon_name="plus", small=True, on_click=self._add))
        row.addWidget(C.button(i18n.t("Import"), "secondary", icon_name="upload", small=True, on_click=self._import))
        row.addWidget(C.button(i18n.t("More"), "secondary", small=True, on_click=self._more_menu))
        box.addLayout(row)
        return box

    def _bulk_bar(self) -> QWidget:
        self.bulk = QFrame()
        self.bulk.setObjectName("waBulk")
        self.bulk.setAttribute(Qt.WA_StyledBackground, True)
        self.bulk.setStyleSheet(f"#waBulk {{ background: {theme.NEUTRAL[100]}; border-radius: {theme.R_CONTROL}px; }}")
        lay = QHBoxLayout(self.bulk)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self.bulk_text = C.label("", level="SUPPORT", weight=700)
        lay.addWidget(self.bulk_text)
        self.select_all_btn = C.button("", "tertiary", small=True, on_click=self._select_all_matching)
        lay.addWidget(self.select_all_btn)
        lay.addStretch(1)
        for text, fn in ((i18n.t("Broadcast"), self._broadcast), (i18n.t("Manage tags"), self._manage_tags), (i18n.t("Export"), self._export_selected),
                         (i18n.t("Block"), self._block), (i18n.t("Delete"), self._delete), (i18n.t("Clear"), self._clear_selection)):
            lay.addWidget(C.button(text, "secondary" if text != i18n.t("Delete") else "tertiary", small=True, on_click=fn))
        self.bulk.hide()
        return self.bulk

    # ── loading ──────────────────────────────────────────────────────────────
    def activate(self):
        self.refresh()
        if not self._loaded:
            ui.call(self, "tags/list", {}, done=lambda r: setattr(self, "_tag_names", [t["name"] for t in r.get("tags") or []]), failed=lambda _m, _d: None)

    def deactivate(self):
        pass

    def effective_filter(self) -> dict:
        parts = []
        if self._chip == "in":
            parts.append({"field": "opted_in", "op": "is", "value": True})
        elif self._chip == "out":
            parts.append({"field": "opted_out", "op": "is", "value": True})
        elif self._chip == "blocked":
            parts.append({"field": "blocked", "op": "is", "value": True})
        if self._user_filter and not FM.is_empty(self._user_filter):
            parts.append(self._user_filter)
        if not parts:
            return {"all": []}
        return parts[0] if len(parts) == 1 else {"all": parts}

    def refresh(self):
        self._request += 1
        rid = self._request
        if not self._sticky:
            self.status.setText(i18n.t("Loading…"))
            self.status.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
            if not self._rows:
                self.loading.setVisible(True)
                self.stack.setCurrentWidget(self.loading)
        ui.call(self, "contacts/list", {"filter": self.effective_filter(), "search": self.search.text().strip(), "sort": self._sort,
                                         "direction": self._dir, "limit": PAGE, "offset": self._offset},
                done=lambda r, i=rid: self._loaded_rows(i, r), failed=lambda m, _d, i=rid: self._failed(i, m))

    def _failed(self, rid: int, message: str):
        if rid != self._request:
            return
        self.loading.setVisible(False)
        self.status.setText(i18n.t("Couldn't load contacts — {e}").format(e=message))
        self.status.setStyleSheet(f"color: {theme.ERR_INK};")
        if not self._rows:
            self.empty.set_text(i18n.t("Couldn't load contacts"), message)
            self.stack.setCurrentIndex(1)

    def _loaded_rows(self, rid: int, reply: dict):
        if rid != self._request:
            return
        self.loading.setVisible(False)
        self._loaded = True
        self._rows = reply.get("contacts") or []
        self._total = int(reply.get("total") or 0)
        self._attr_keys = list(reply.get("attribute_keys") or [])
        self._defs = {k: self._defs.get(k) or {"type": "string"} for k in self._attr_keys}
        self.countChanged.emit(self._total)
        self._draw()
        ui.call(self, "attributes/list", {}, done=self._got_defs, failed=lambda _m, _d: None)

    def _got_defs(self, reply: dict):
        self._defs = {a["key"]: {"type": a.get("type") or "string", "options": a.get("options")} for a in reply.get("attributes") or []}

    # ── drawing ──────────────────────────────────────────────────────────────
    def _visible_columns(self) -> list:
        order = [k for k, _h, _s in BUILT_IN] + ["attr:" + a for a in self._attr_keys]
        return [k for k in order if k in self._columns]

    def _draw(self):
        cols = self._visible_columns()
        sortable = {k: s for k, _h, s in BUILT_IN}
        t = self.table
        t.blockSignals(True)
        t.setColumnCount(len(cols) + 1)
        t.setHorizontalHeaderItem(0, QTableWidgetItem(""))
        for i, key in enumerate(cols, start=1):
            head = QTableWidgetItem(_heading(key) if not key.startswith("attr:") else key[5:])
            if sortable.get(key) == self._sort:                          # the font has no arrow glyph, so the sort mark is an icon
                head.setIcon(QIcon(paths.resource("assets/caret-up.svg" if self._dir == "asc" else "assets/caret-down.svg")))
            t.setHorizontalHeaderItem(i, head)
        t.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            box = QTableWidgetItem()
            box.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            box.setCheckState(Qt.Checked if (self._all_matching or row["id"] in self._selected) else Qt.Unchecked)
            box.setData(Qt.UserRole, row["id"])
            t.setItem(r, 0, box)
            for c, key in enumerate(cols, start=1):
                item = QTableWidgetItem(cell_text(row, key))
                item.setData(Qt.UserRole, row["id"])
                if key == "name":
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                if row.get("opted_out") or row.get("blocked"):
                    item.setForeground(Qt.gray)
                t.setItem(r, c, item)
        t.setColumnWidth(0, 34)
        widths = {"name": 170, "phone": 130, "tags": 170, "source": 90, "window": 80, "state": 110, "last_seen": 100, "created_at": 100,
                  "first_msg_tag": 120, "email": 180, "company": 150}
        for i, key in enumerate(cols, start=1):
            t.setColumnWidth(i, widths.get(key, 110))
        t.blockSignals(False)
        sel = next((i for i, r in enumerate(self._rows) if r["id"] == self._current_id), -1)
        if sel >= 0:
            t.selectRow(sel)
        start = self._offset + 1 if self._rows else 0
        end = self._offset + len(self._rows)
        self.status.setText(self._sticky or (i18n.t("{a}–{b} of {n}").format(a=start, b=end, n=self._total) if self._rows else ""))
        self.status.setStyleSheet(f"color: {theme.ERR_INK if self._sticky else theme.NEUTRAL[500]};")
        self.prev_btn.setEnabled(self._offset > 0)
        self.next_btn.setEnabled(self._offset + PAGE < self._total)
        self.prev_btn.setVisible(self._total > PAGE)
        self.next_btn.setVisible(self._total > PAGE)
        self._refresh_chrome()
        if self._rows:
            self.stack.setCurrentIndex(0)
        else:
            filtered = bool(self.search.text().strip()) or self._chip != "all" or not FM.is_empty(self._user_filter)
            self.empty.set_text(i18n.t("No one matches") if filtered else i18n.t("No contacts yet"),
                                i18n.t("Try a different search or filter.") if filtered else
                                i18n.t("People are added automatically the first time they message your number. You can also add one or import a file."))
            self.stack.setCurrentIndex(1)
            self.panel.clear()

    def _refresh_chrome(self):
        desc = FM.describe(self._user_filter, self._defs) if not FM.is_empty(self._user_filter) else ""
        if self._segment_name and desc:
            desc = "%s: %s" % (self._segment_name, desc)
        self.summary.setText(desc)
        self.summary_row.setVisible(bool(desc))
        self.filter_btn.setText(i18n.t("Filters") + (" •" if desc else ""))
        n = self.selected_count()
        self.bulk.setVisible(n > 0)
        if n:
            self.bulk_text.setText(i18n.t("{n} selected").format(n=n) if n != 1 else i18n.t("1 selected"))
            page_all = bool(self._rows) and all(r["id"] in self._selected for r in self._rows)
            more = self._total > len(self._rows)
            self.select_all_btn.setVisible(page_all and more and not self._all_matching)
            self.select_all_btn.setText(i18n.t("Select all {n} that match").format(n=self._total))

    # ── selection ────────────────────────────────────────────────────────────
    def selected_count(self) -> int:
        return self._total if self._all_matching else len(self._selected)

    def target(self) -> dict:
        if self._all_matching:
            return {"filter": self.effective_filter()}
        return {"contact_ids": sorted(self._selected)}

    def _on_item_changed(self, item):
        if item.column() != 0:
            return
        cid = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            self._selected.add(cid)
        else:
            self._selected.discard(cid)
            self._all_matching = False
        self._refresh_chrome()

    def _select_all_matching(self):
        self._all_matching = True
        self._draw()

    def _clear_selection(self):
        self._selected.clear()
        self._all_matching = False
        self._draw()

    def _on_row(self, r: int):
        if 0 <= r < len(self._rows):
            row = self._rows[r]
            if row["id"] != self._current_id:
                self._current_id = row["id"]
                self.panel.load(row["id"], row)

    # ── filter, sort, page ───────────────────────────────────────────────────
    def _search_now(self):
        self._offset = 0
        self.refresh()

    def _on_chip(self, value: str):
        self._chip = value
        self._offset = 0
        self._selected.clear()
        self._all_matching = False
        self.refresh()

    def _on_header(self, i: int):
        cols = self._visible_columns()
        if i == 0 or i > len(cols):
            return
        key = {k: s for k, _h, s in BUILT_IN}.get(cols[i - 1])
        if not key:
            return
        self._dir = ("asc" if self._dir == "desc" else "desc") if self._sort == key else "asc"
        self._sort = key
        self._offset = 0
        self.refresh()

    def _page(self, step: int):
        self._offset = max(0, self._offset + step * PAGE)
        self.refresh()

    def _open_filter(self):
        from addons.whatsapp.filter_builder import FilterDialog
        dlg = FilterDialog(self._user_filter, self._defs, self._tag_names, self)
        if dlg.exec():
            self._user_filter = dlg.filter()
            self._segment_name = ""
            self._offset = 0
            self._selected.clear()
            self._all_matching = False
            self.refresh()

    def _open_segments(self):
        from addons.whatsapp.filter_builder import SegmentsDialog
        dlg = SegmentsDialog(self._defs, self)
        if dlg.exec() and dlg.chosen:
            self._user_filter = dlg.chosen.get("filter") or {}
            self._segment_name = dlg.chosen.get("name") or ""
            self._offset = 0
            self.refresh()

    def _clear_filter(self):
        self._user_filter, self._segment_name, self._offset = {}, "", 0
        self.refresh()

    def _columns_menu(self):
        menu = QMenu(self)
        for key, _h, _s in BUILT_IN:
            if key == "name":
                continue
            act = menu.addAction(_heading(key))
            act.setCheckable(True)
            act.setChecked(key in self._columns)
            act.toggled.connect(lambda on, k=key: self._toggle_column(k, on))
        if self._attr_keys:
            menu.addSeparator()
            for a in self._attr_keys:
                act = menu.addAction(a)
                act.setCheckable(True)
                act.setChecked("attr:" + a in self._columns)
                act.toggled.connect(lambda on, k="attr:" + a: self._toggle_column(k, on))
        menu.exec(self.columns_btn.mapToGlobal(self.columns_btn.rect().bottomLeft()))

    def _toggle_column(self, key: str, on: bool):
        if on and key not in self._columns:
            self._columns.append(key)
        if not on and key in self._columns:
            self._columns.remove(key)
        self._draw()

    # ── actions ──────────────────────────────────────────────────────────────
    def _add(self):
        from addons.whatsapp.contact_dialogs import AddContactDialog
        dlg = AddContactDialog(self._tag_names, [dict(key=k, **(self._defs.get(k) or {})) for k in self._attr_keys], self)
        if dlg.exec():
            self._current_id = (dlg.created or {}).get("contact_id")
            self.refresh()

    def _import(self):
        from addons.whatsapp.import_dialog import ImportContactsDialog
        if ImportContactsDialog(self).exec():
            self.refresh()

    def _more_menu(self):
        menu = QMenu(self)
        menu.addAction(i18n.t("Export everyone"), self._export_all)
        menu.addAction(i18n.t("Import history"), self._import_history)
        menu.addSeparator()
        menu.addAction(i18n.t("Tags and attributes…"), lambda: self.manageRequested.emit("tags"))
        menu.addAction(i18n.t("Opt-in and opt-out words…"), lambda: self.manageRequested.emit("compliance"))
        btn = self.sender()
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()) if btn is not None else self.mapToGlobal(self.rect().center()))

    def _import_history(self):
        from addons.whatsapp.contact_dialogs import ImportHistoryDialog
        ImportHistoryDialog(self).exec()

    def _export_all(self):
        from addons.whatsapp.import_dialog import export_contacts
        export_contacts(self)

    def _export_selected(self):
        from addons.whatsapp.import_dialog import export_contacts
        export_contacts(self, target=self.target())

    def _broadcast(self):
        self.broadcastRequested.emit(self.target())

    def _manage_tags(self):
        from addons.whatsapp.contact_dialogs import ManageTagsDialog
        dlg = ManageTagsDialog(self.target(), self.selected_count(), self._tag_names, self)
        if dlg.exec():
            ui.call(self, "tags/list", {}, done=lambda r: setattr(self, "_tag_names", [t["name"] for t in r.get("tags") or []]), failed=lambda _m, _d: None)
            self.refresh()
            self.panel.reload()

    def _block(self):
        if not ui.confirm(self, i18n.t("Block these people?"), i18n.t("Blocked people are never messaged, by anyone, until you unblock them.")):
            return
        ui.call(self, "contacts/block", dict(self.target(), blocked=True), done=lambda _r: (self._clear_selection(), self.refresh()),
                failed=lambda m, _d: self._save_failed(m))

    def _delete(self):
        n = self.selected_count()
        if not ui.confirm(self, i18n.t("Delete contacts"),
                          (i18n.t("Delete {n} people? Their chats, details and consent history are removed for good.") if n != 1
                           else i18n.t("Delete 1 person? Their chats, details and consent history are removed for good.")).format(n=n)):
            return
        ui.call(self, "contacts/delete", self.target(), done=lambda _r: (self._clear_selection(), self.panel.clear(), self.refresh()),
                failed=lambda m, _d: self._save_failed(m))

    def _send_template(self, contact: dict):
        from addons.whatsapp.send_template_dialog import SendTemplateDialog
        if SendTemplateDialog(contact, self).exec():
            C.show_toast(self, i18n.t("Sent"), contact.get("name") or "")
            self.panel.reload()

    def _profile_changed(self):
        self.refresh()

    def _save_failed(self, error: str):
        self._sticky = i18n.t("Couldn't save that change — {e}").format(e=error)
        self.status.setText(self._sticky)
        self.status.setStyleSheet(f"color: {theme.ERR_INK};")
        self.refresh()
