"""The Inbox — every conversation, the live thread, and who you are talking to.

Three panes, the shape every messenger and support desk has converged on:

    chats  |  the thread + composer  |  the profile

The list has two views and a set of states. **Live** is what a team works from: chats whose 24-hour window is open, plus any a
person is wanted on or already has. **History** is the quiet ones — nobody can reply freely, but a template can start the chat
again. Within a view, the state tabs say who has what: needs a person, mine, unassigned, with the bot, with an agent, resolved —
each with its count. Filters narrow by anything known about the person (tags, attributes, source).

It stays current on its own (a quiet poll while the tab is on screen), tells you what you have not read (per seat, readstate.py),
alerts you when a chat needs a person, and treats a send as instant: the bubble is on screen the moment you press Enter and
settles to sent or to a red Retry. Every call runs on a worker; nothing blocks the window.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QListWidget, QListWidgetItem, QSplitter, QStackedWidget, QVBoxLayout, QWidget

import i18n
from widgets.loader import Skeleton
import theme
from addons.whatsapp import filter_model as FM
from addons.whatsapp import notify, readstate, ui
from addons.whatsapp.chat import CONVO_ROW_H, ConversationDelegate, avatar_colour, human_delta, window_left
from addons.whatsapp.inbox_actions import ConversationBar, QuickReplyButton
from addons.whatsapp.profile_panel import ProfilePanel
from addons.whatsapp.thread import Banner, Composer, MessageThread
from widgets import controls as C

POLL_MS = 15000                       # the quiet look-again (it also catches a message turning to "read"); live updates make it a safety net
LIVE_WAIT = 12                        # seconds the service holds a "has anything changed?" question open before answering "no"
LIVE_BACKOFF_MS = 5000                # after the live question fails, wait this long (growing) before asking again
_NARROW = 1120                       # below this the profile rail folds away


def _card(objname: str) -> QFrame:
    f = QFrame()
    f.setObjectName(objname)
    f.setAttribute(Qt.WA_StyledBackground, True)
    f.setStyleSheet(f"#{objname} {{ background: {theme.CARD}; border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CARD}px; }}")
    return f


def state_choices() -> list:
    """(key, label) of the state tabs. Literal i18n.t calls, so the extractor sees each word."""
    return [("", i18n.t("All chats")), ("requesting", i18n.t("Needs a person")), ("mine", i18n.t("Mine")), ("unassigned", i18n.t("Unassigned")),
            ("bot", i18n.t("With the bot")), ("intervened", i18n.t("With an agent")), ("closed", i18n.t("Resolved")), ("unread", i18n.t("Unread"))]


class InboxPage(QWidget):
    unreadChanged = Signal(int)
    statusChanged = Signal(str, bool)           # message, is_error
    orderRequested = Signal(dict)               # "New order" on the chat's person: open the Shop with them chosen
    formRequested = Signal(dict)                # "Send a form…" on the chat's person: open Forms with them chosen

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._rows: list = []
        self._counts: dict = {}
        self._current = None                    # the selected conversation row
        self._thread_stamp: dict = {}           # id -> last_active_at it was loaded at
        self._inflight = 0                      # sends still travelling
        self._loading = False
        self._view = "live"                     # live | history
        self._state = ""
        self._filter: dict = {}
        self._defs: dict = {}
        self._tag_names: list = []
        self._rail_pref = None                  # None = automatic, else user's choice
        self._first_load = True
        self._last_error = ""
        self._agents: list = []                 # the team
        self._me = ""                           # which of them is this seat
        self._bar_ok = True                     # False on a server without the team inbox: the bar stays away
        self._announced = None                  # what the last look saw, for alerts (None until the first)
        self._unread_total = 0
        self._request = 0
        self._active = False                    # the tab is on screen
        self._listening = False                 # a live question is open
        self._cursor = ""                       # what the service last said the newest change was
        self._live_failures = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        root.setSpacing(0)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(theme.SPACE_3)
        self.split.setStyleSheet("QSplitter::handle { background: transparent; }")
        root.addWidget(self.split)
        self.split.addWidget(self._build_list())
        self.split.addWidget(self._build_thread())
        self.profile = ProfilePanel(allow_delete=False)
        self.profile.changed.connect(lambda: self.refresh(silent=True))
        self.profile.sendTemplate.connect(self._send_template)
        self.profile.startOrder.connect(self.orderRequested)
        self.profile.sendForm.connect(self.formRequested)
        rail = _card("waRail")
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.profile)
        rail.setMinimumWidth(290)
        rail.setMaximumWidth(360)
        self._rail = rail
        self.split.addWidget(rail)
        self.split.setStretchFactor(0, 0)
        self.split.setStretchFactor(1, 1)
        self.split.setStretchFactor(2, 0)
        self.split.setSizes([360, 580, 320])

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(lambda: self.refresh(silent=True))
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(lambda: self.refresh(silent=True))
        find = QShortcut(QKeySequence("Ctrl+F"), self)
        find.setContext(Qt.WidgetWithChildrenShortcut)
        find.activated.connect(lambda: self.search.setFocus(Qt.ShortcutFocusReason))
        self._show_thread_page(False)

    # ── construction ─────────────────────────────────────────────────────────
    def _build_list(self) -> QWidget:
        card = _card("waList")
        card.setMinimumWidth(310)
        card.setMaximumWidth(460)
        col = QVBoxLayout(card)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_4, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_3)

        self.view_chips = C.FilterChips([("live", i18n.t("Live")), ("history", i18n.t("History"))], current="live")
        self.view_chips.changed.connect(self._on_view)
        self.view_chips.setMinimumWidth(190)
        col.addWidget(self.view_chips)

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.state_box = QComboBox()
        self.state_box.setMinimumHeight(34)
        self.state_box.setAccessibleName(i18n.t("Show chats that are"))
        self._fill_states()
        self.state_box.currentIndexChanged.connect(self._on_state)
        row.addWidget(self.state_box, stretch=1)
        self.filter_btn = C.button(i18n.t("Filters"), "secondary", icon_name="sliders", small=True, on_click=self._open_filter)
        row.addWidget(self.filter_btn)
        col.addLayout(row)

        self.search = C.SearchField(i18n.t("Search conversations"))
        self.search.changed.connect(lambda _t: self._on_search())
        col.addWidget(self.search)

        self.list_stack = QStackedWidget()
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setItemDelegate(ConversationDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setStyleSheet("QListWidget { background: transparent; border: none; outline: 0; }")
        self.list.currentItemChanged.connect(self._on_selected)
        self.list_stack.addWidget(self.list)
        self.list_empty = C.EmptyState("inbox", i18n.t("No conversations yet"), i18n.t("When someone messages your WhatsApp number, the chat appears here."))
        self.list_stack.addWidget(self.list_empty)
        self.list_loading = Skeleton(5)
        self.list_stack.addWidget(self.list_loading)
        col.addWidget(self.list_stack, stretch=1)

        self.list_status = C.label("", level="META", colour=theme.NEUTRAL[500])
        col.addWidget(self.list_status)
        return card

    def _fill_states(self):
        keep = self._state
        self.state_box.blockSignals(True)
        self.state_box.clear()
        for key, label in state_choices():
            n = self._counts.get(key if key else "all")
            self.state_box.addItem(("%s  (%d)" % (label, n)) if n is not None and key != "unread" else label, key)
        i = self.state_box.findData(keep)
        self.state_box.setCurrentIndex(max(i, 0))
        self.state_box.blockSignals(False)

    def _build_thread(self) -> QWidget:
        card = _card("waThread")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.thread_stack = QStackedWidget()
        outer.addWidget(self.thread_stack)

        self.thread_empty = C.EmptyState("message", i18n.t("Pick a conversation"), i18n.t("Choose someone on the left to read the chat and reply."))
        self.thread_stack.addWidget(self.thread_empty)

        live = QWidget()
        lc = QVBoxLayout(live)
        lc.setContentsMargins(0, 0, 0, 0)
        lc.setSpacing(0)

        head = QFrame()
        head.setObjectName("waThreadHead")
        head.setAttribute(Qt.WA_StyledBackground, True)
        head.setStyleSheet(f"#waThreadHead {{ border-bottom: 1px solid {theme.HAIRLINE}; }}")
        hr = QHBoxLayout(head)
        hr.setContentsMargins(theme.SPACE_5, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        hr.setSpacing(theme.SPACE_3)
        self.head_avatar_holder = QHBoxLayout()
        self.head_avatar_holder.setContentsMargins(0, 0, 0, 0)
        hr.addLayout(self.head_avatar_holder)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.head_name = C.label("", level="SECTION", weight=700)
        self.head_sub = C.label("", level="META", colour=theme.NEUTRAL[600])
        titles.addWidget(self.head_name)
        titles.addWidget(self.head_sub)
        hr.addLayout(titles, stretch=1)
        self.head_window = C.Pill("", "quiet")
        self.head_window.hide()
        hr.addWidget(self.head_window)
        self.template_btn = C.button(i18n.t("Send a template"), "secondary", small=True, on_click=lambda: self._send_template(self._contact_row()))
        self.template_btn.hide()
        hr.addWidget(self.template_btn)
        self.rail_btn = C.icon_button("user", i18n.t("Show or hide contact details"), on_click=self._toggle_rail)
        hr.addWidget(self.rail_btn)
        lc.addWidget(head)
        self.bar = ConversationBar()
        self.bar.changed.connect(self._team_changed)
        self.bar.problem.connect(lambda m: self.banner.show_note(m, "err"))
        lc.addWidget(self.bar)

        self.thread = MessageThread()
        self.thread.retryRequested.connect(self._retry)
        self.thread.retryMediaRequested.connect(self._retry_media)
        lc.addWidget(self.thread, stretch=1)

        foot = QWidget()
        fl = QVBoxLayout(foot)
        fl.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, theme.SPACE_4)
        fl.setSpacing(theme.SPACE_2)
        self.banner = Banner()
        fl.addWidget(self.banner)
        self.composer = Composer()
        self.composer.submitted.connect(self._send)
        self.composer.submittedMedia.connect(self._send_media)
        self.composer.attachRequested.connect(self._attach)
        self.quick = QuickReplyButton()
        self.quick.chosen.connect(self._insert_reply)
        self.composer.layout().insertWidget(0, self.quick)          # a saved reply, one click from the box
        fl.addWidget(self.composer)
        lc.addWidget(foot)
        self.thread_stack.addWidget(live)
        return card

    def _show_thread_page(self, live: bool):
        self.thread_stack.setCurrentIndex(1 if live else 0)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def activate(self):
        """The tab came on screen: load now, then keep current: a live question to the service (an answer the moment a chat changes), and the
        quiet look-again every few seconds as a safety net."""
        self._active = True
        self.refresh(silent=not self._first_load)
        self._timer.start()
        if self._first_load:
            self._first_load = False
            self._load_side_data()
        self._listen()

    def deactivate(self):
        self._active = False
        self._timer.stop()

    # ── live updates ─────────────────────────────────────────────────────────
    def _listen(self):
        """Ask the service "has anything changed since <cursor>?". It answers at once if so, or after LIVE_WAIT seconds if not; either way
        the next question follows. Never more than one is open."""
        if not self._active or self._listening:
            return
        self._listening = True
        ui.call(self, "inbox/changes", {"cursor": self._cursor, "wait": LIVE_WAIT, "_timeout": LIVE_WAIT + 18}, done=self._on_changes, failed=self._on_changes_failed)

    def _on_changes(self, reply: dict):
        self._listening = False
        self._live_failures = 0
        self._cursor = str(reply.get("cursor") or self._cursor)
        if not self._active:
            return
        if reply.get("changed"):
            self.refresh(silent=True)
            if self._current and not self._inflight:
                self._thread_stamp.pop(self._current.get("id"), None)
                self._load_thread(self._current.get("id"), silent=True)
        QTimer.singleShot(0, self._listen)

    def _on_changes_failed(self, _message: str, _detail: dict):
        """The service (or the network) did not answer: the quiet look-again keeps things current, and we try the live question again, later."""
        self._listening = False
        self._live_failures += 1
        if self._active:
            QTimer.singleShot(min(self._live_failures, 6) * LIVE_BACKOFF_MS, self._listen)

    def _load_side_data(self):
        ui.call(self, "inbox/agents/list", done=self._on_agents, failed=lambda m, _d: self._team_unavailable())
        ui.call(self, "tags/list", done=lambda r: setattr(self, "_tag_names", [t["name"] for t in r.get("tags") or []]), failed=lambda m, _d: None)
        ui.call(self, "attributes/list", done=lambda r: setattr(self, "_defs", {a["key"]: {"type": a.get("type"), "options": a.get("options")}
                                                                                for a in r.get("attributes") or []}), failed=lambda m, _d: None)
        self.quick.load()

    # ── the team: who has which chat ─────────────────────────────────────────
    def _on_agents(self, reply: dict):
        self._agents = list(reply.get("agents") or [])
        self._me = str(reply.get("me") or "")
        self._refresh_bar()

    def _team_unavailable(self):
        """A server without the team inbox: the bar stays away and the plain inbox carries on."""
        self._bar_ok = False
        self.bar.hide()

    def _refresh_bar(self):
        if not self._current or not self._bar_ok:
            self.bar.hide()
            return
        state = {"status": self._current.get("status") or "active", "assignee_id": self._current.get("assignee_id"),
                 "window_open": bool(self._current.get("window_open", True))}
        self.bar.show_for(self._current, state, self._agents, self._me)

    def _team_changed(self):
        self.refresh(silent=True)
        if self._current:
            self._load_thread(self._current.get("id"), silent=True)

    def _attach(self):
        from addons.whatsapp.media_lib import MediaLibraryDialog
        dlg = MediaLibraryDialog(parent=self)
        if dlg.exec() and dlg.asset:
            self.composer.set_attachment(dlg.asset)

    def _insert_reply(self, text: str, asset=None):
        if asset:                                   # a saved reply with a file: the file attaches, its words become the caption
            self.composer.set_attachment(asset)
        self.composer.edit.insertPlainText(text)
        self.composer.focus()

    # ── the list ─────────────────────────────────────────────────────────────
    def _params(self) -> dict:
        data = {"window": self._view, "limit": 100}
        if self._state and self._state != "unread":
            data["state"] = self._state
        text = self.search.text().strip()
        if text:
            data["search"] = text
        if self._filter and not FM.is_empty(self._filter):
            data["filter"] = self._filter
        return data

    def _unfiltered(self) -> bool:
        return not (self._state or self.search.text().strip() or (self._filter and not FM.is_empty(self._filter)))

    def refresh(self, silent: bool = False):
        self._request += 1
        rid = self._request
        if not silent:
            self.list_status.setText(i18n.t("Loading…"))
            if not self._rows:
                self.list_loading.setVisible(True)
                self.list_stack.setCurrentWidget(self.list_loading)
        ui.call(self, "inbox/threads", self._params(), done=lambda r, i=rid: self._on_list(i, r), failed=lambda m, _d, i=rid: self._on_list_failed(i, m))

    def _on_list_failed(self, rid: int, error: str):
        if rid != self._request:
            return
        self.list_loading.setVisible(False)
        self._last_error = error
        self.list_status.setText(i18n.t("Couldn't refresh — {e}").format(e=error))
        self.list_status.setStyleSheet(f"color: {theme.ERR_INK};")
        self.statusChanged.emit(error, True)
        if not self._rows:
            self.list_empty.set_text(i18n.t("Couldn't load your inbox"), error)
            self.list_stack.setCurrentIndex(1)

    def _on_list(self, rid: int, reply: dict):
        if rid != self._request:
            return
        self.list_loading.setVisible(False)
        self._last_error = ""
        rows = list(reply.get("conversations") or [])
        self._counts = dict(reply.get("counts") or {})
        self._rows = rows
        self.list_status.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        self.list_status.setText(i18n.t("Updated {t}").format(t=datetime.now().strftime("%I:%M %p").lstrip("0")))
        self.statusChanged.emit("", False)
        self._fill_states()
        self._draw()
        if self._view == "live" and self._unfiltered():
            unread_ids = {r["id"] for r in rows if readstate.is_unread(r)}
            self._unread_total = len(unread_ids)
            self.unreadChanged.emit(self._unread_total)
            fired = notify.events(self._announced, rows, unread_ids)
            self._announced = {"requesting": {r["id"] for r in rows if r.get("status") == "requesting"}, "unread": unread_ids}
            notify.announce(self, notify.prefs(self.cfg), fired)
        if self._current:
            fresh = next((r for r in self._rows if r.get("id") == self._current.get("id")), None)
            if fresh is not None:
                changed_state = (fresh.get("status"), fresh.get("assignee_id")) != (self._current.get("status"), self._current.get("assignee_id"))
                self._current = fresh
                if changed_state:
                    self._refresh_bar()
                if fresh.get("last_active_at") != self._thread_stamp.get(fresh.get("id")):
                    self._load_thread(fresh.get("id"), silent=True)

    def _visible_rows(self) -> list:
        if self._state == "unread":
            return [r for r in self._rows if readstate.is_unread(r)]
        return self._rows

    def _draw(self):
        rows = self._visible_rows()
        keep = (self._current or {}).get("id")
        self.list.blockSignals(True)
        self.list.clear()
        selected = -1
        for i, r in enumerate(rows):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, r)
            item.setSizeHint(QSize(0, CONVO_ROW_H))
            self.list.addItem(item)
            if r.get("id") == keep:
                selected = i
        if selected >= 0:
            self.list.setCurrentRow(selected)
        self.list.blockSignals(False)
        filtered = bool(self._state or self.search.text().strip() or (self._filter and not FM.is_empty(self._filter)))
        self.filter_btn.setText(i18n.t("Filters") + (" •" if self._filter and not FM.is_empty(self._filter) else ""))
        if rows:
            self.list_stack.setCurrentIndex(0)
        else:
            if filtered:
                self.list_empty.set_text(i18n.t("Nothing matches"), i18n.t("Try a different search or filter."))
            elif self._view == "history":
                self.list_empty.set_text(i18n.t("Nothing in History"), i18n.t("Chats that have been quiet for a day, with nobody on them, are kept here."))
            else:
                self.list_empty.set_text(i18n.t("No conversations yet"), i18n.t("When someone messages your WhatsApp number, the chat appears here."))
            self.list_stack.setCurrentIndex(1)

    def _on_view(self, value: str):
        self._view = value
        self._state = ""
        self._counts = {}
        self._fill_states()
        self.refresh()

    def _on_state(self, _i):
        self._state = self.state_box.currentData() or ""
        self.refresh()

    def _on_search(self):
        self._search_timer.start()

    def _open_filter(self):
        from addons.whatsapp.filter_builder import FilterDialog
        dlg = FilterDialog(self._filter, self._defs, self._tag_names, self)
        if dlg.exec():
            self._filter = dlg.filter()
            self.refresh()

    def _repaint_list(self):
        self.list.viewport().update()
        if self._view == "live" and self._unfiltered():
            self._unread_total = sum(1 for r in self._rows if readstate.is_unread(r))
            self.unreadChanged.emit(self._unread_total)

    # ── one conversation ─────────────────────────────────────────────────────
    def _on_selected(self, item, _previous=None):
        if item is None:
            return
        row = item.data(Qt.UserRole) or {}
        self._current = row
        self._show_thread_page(True)
        who = row.get("contact_name") or row.get("contact_phone") or i18n.t("Unknown")
        self._set_head(row, who)
        self.banner.hide()
        self.composer.set_active(True, i18n.t("Type a message"))
        self.thread.show_note(i18n.t("Loading…"))
        self.profile.load(row.get("contact_id"), self._contact_row())
        self.quick.contact_id = row.get("contact_id") or ""
        self._refresh_bar()
        self._load_thread(row.get("id"))
        self.composer.focus()

    def _contact_row(self) -> dict:
        row = self._current or {}
        return {"id": row.get("contact_id"), "name": row.get("contact_name"), "phone": row.get("contact_phone"), "opted_out": bool(row.get("opt_out")),
                "tags": list(row.get("tags") or []), "state": row.get("status"), "window_open": bool(row.get("window_open"))}

    def _set_head(self, row: dict, who: str):
        ui.clear(self.head_avatar_holder)
        self.head_avatar_holder.addWidget(C.Avatar(who, 40, avatar_colour(who, bool(row.get("opt_out")))))
        self.head_name.setText(who)
        phone = row.get("contact_phone") or ""
        self.head_sub.setText(phone if phone.startswith("*") else (("+" + phone.lstrip("+")) if phone else ""))

    def _load_thread(self, cid, silent: bool = False):
        ui.call(self, "inbox/thread", {"conversation_id": cid, "limit": 300}, done=lambda r, c=cid, s=silent: self._on_thread(c, r.get("messages") or [], s),
                failed=lambda m, _d, c=cid: self._on_thread_failed(c, m))

    def _on_thread_failed(self, cid, error: str):
        if self._current and self._current.get("id") == cid and not self.thread._bubbles:
            self.thread.show_note(i18n.t("Couldn't load this conversation.\n{e}").format(e=error), tone="error")

    def _on_thread(self, cid, messages: list, silent: bool):
        if not self._current or self._current.get("id") != cid:
            return
        if silent and self._inflight:
            return                              # a send is mid-flight; don't redraw under it
        self._thread_stamp[cid] = self._current.get("last_active_at")
        self.thread.set_messages(messages)
        readstate.mark_read(cid, self._current.get("last_active_at") or "")
        self._repaint_list()
        self._update_window(messages)

    def _update_window(self, messages: list):
        left = window_left(messages)
        row = self._current or {}
        opted = bool(row.get("opt_out"))
        if left is None:
            self.head_window.setText(i18n.t("Template only"))
            self.head_window.set_tone("quiet")
        elif left.total_seconds() > 0:
            self.head_window.setText(i18n.t("Reply window · {t} left").format(t=human_delta(left)))
            self.head_window.set_tone("ok")
        else:
            self.head_window.setText(i18n.t("Window closed"))
            self.head_window.set_tone("warn")
        self.head_window.show()
        open_now = left is not None and left.total_seconds() > 0
        self.template_btn.setVisible(not opted and not open_now)
        if opted:
            self.banner.show_note(i18n.t("This contact opted out. Replies are turned off — you can change that in the contact details."), "err")
            self.composer.set_active(False, i18n.t("Opted out — messaging is turned off"))
        elif not open_now:
            self.banner.show_note(i18n.t("It's been over 24 hours since they wrote, so WhatsApp only delivers an approved template. "
                                         "Use Send a template to start the chat again."), "warn")
            self.composer.set_active(False, i18n.t("Window closed — send a template to reach them"))
        else:
            self.banner.hide()
            self.composer.set_active(True, i18n.t("Type a message"))

    # ── sending ──────────────────────────────────────────────────────────────
    def _send(self, text: str, bubble=None):
        row = self._current
        if not row:
            return
        if bubble is None:
            bubble = self.thread.add_pending(text, sender=i18n.t("You"))
            bubble.msg["client_ref"] = uuid.uuid4().hex          # kept on the message, so a retry (even after a redraw) never sends twice
        else:
            bubble.set_status("sending")
        self._inflight += 1
        ui.call(self, "messages/send_text", {"conversation_id": row.get("id"), "text": text, "client_ref": bubble.msg.get("client_ref", "")},
                done=lambda _r, b=bubble, t=text, r=row: self._sent(b, t, r), failed=lambda m, _d, b=bubble: self._send_failed(b, m))

    def _send_media(self, asset: dict, caption: str, bubble=None):
        row = self._current
        if not row:
            return
        if bubble is None:
            bubble = self.thread.add_pending_media(asset, caption, sender=i18n.t("You"))
            bubble.msg["client_ref"] = uuid.uuid4().hex
        else:
            bubble.set_status("sending")
        self._inflight += 1
        ui.call(self, "messages/send_media", {"conversation_id": row.get("id"), "asset_id": asset.get("id"), "caption": caption,
                                              "client_ref": bubble.msg.get("client_ref", "")},
                done=lambda _r, b=bubble, a=asset, c=caption, r=row: self._sent(b, ("[%s] %s" % (a.get("kind") or "file", c)).strip(), r),
                failed=lambda m, _d, b=bubble: self._send_failed(b, m))

    def _retry_media(self, bubble):
        media = bubble.msg.get("media") or {}
        text = bubble.msg.get("text") or ""
        caption = re.sub(r"^\[[a-z]+\]\s*", "", text)
        self.banner.hide()
        self._send_media({"id": media.get("id"), "kind": media.get("kind"), "filename": media.get("filename"), "size": media.get("size")}, caption,
                         bubble=bubble)

    def _sent(self, bubble, text: str, row: dict):
        self._inflight = max(0, self._inflight - 1)
        bubble.set_status("sent")
        for r in self._rows:                                     # reflect it on the row at once; the next poll confirms it
            if r.get("id") == row.get("id"):
                r["last_text"], r["last_direction"] = text, "out"
                r["last_active_at"] = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
                readstate.mark_read(r["id"], r["last_active_at"])
        self._rows.sort(key=lambda r: r.get("last_active_at") or "", reverse=True)
        self._draw()
        QTimer.singleShot(1800, lambda: self._settle(row.get("id")))

    def _settle(self, cid):
        if self._current and self._current.get("id") == cid and not self._inflight:
            self.refresh(silent=True)
            self._thread_stamp.pop(cid, None)
            self._load_thread(cid, silent=True)

    def _send_failed(self, bubble, error: str):
        self._inflight = max(0, self._inflight - 1)
        bubble.set_status("failed")
        self.statusChanged.emit(error, True)
        self.banner.show_note(i18n.t("Couldn't send: {e}").format(e=error), "err")

    def _retry(self, text: str, bubble):
        self.banner.hide()
        self._send(text, bubble=bubble)

    def _send_template(self, contact: dict):
        from addons.whatsapp.send_template_dialog import SendTemplateDialog
        if not contact or not contact.get("id"):
            return
        if SendTemplateDialog(contact, self).exec():
            C.show_toast(self, i18n.t("Sent"), contact.get("name") or "")
            self.refresh(silent=True)
            if self._current:
                self._load_thread(self._current.get("id"), silent=True)
            self.profile.reload()

    # ── layout ───────────────────────────────────────────────────────────────
    def _toggle_rail(self):
        # isHidden(), not "not isVisible()": the latter is also true whenever the page itself is off screen,
        # which would turn "hide" into "show".
        self._rail_pref = self._rail.isHidden()
        self._rail.setVisible(self._rail_pref)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._rail_pref is None:
            self._rail.setVisible(self.width() >= _NARROW)
