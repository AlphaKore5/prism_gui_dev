"""The chat profile — everything the team should know about one person, in one panel.

Who they are and whether you can write to them freely; the numbers (templates sent, messages exchanged, times they asked
for a person); their details and attributes; tags; the campaigns they got; and the Customer Journey, a timeline of what
has happened to them. It sits beside a chat in the Inbox and beside the table in Contacts.

It loads its own person (`load(contact_id)`) and saves its own edits through the platform, then says `changed` so the page
around it can refresh its list. Nothing else is shared with the page: it holds the one person it was asked for.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCompleter, QFrame, QHBoxLayout, QLineEdit, QScrollArea, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp import ui
from addons.whatsapp.chat import avatar_colour, short_time
from widgets import controls as C

JOURNEY_SHOWN = 8


def journey_words(e: dict) -> str:
    """One journey event as a sentence. A literal per case so each one is translatable."""
    kind, d, who = e.get("kind"), e.get("detail") or {}, e.get("who") or ""
    if kind == "created":
        return i18n.t("Added to your contacts") + ((" · " + str(d.get("source"))) if d.get("source") else "")
    if kind == "updated":
        return i18n.t("Details updated")
    if kind == "tag_added":
        return i18n.t("Tag added: {t}").format(t=", ".join(d.get("tags") or []))
    if kind == "tag_removed":
        return i18n.t("Tag removed: {t}").format(t=", ".join(d.get("tags") or []))
    if kind == "attribute_set":
        return i18n.t("{k} set to {v}").format(k=d.get("key"), v=d.get("value"))
    if kind == "blocked":
        return i18n.t("Blocked")
    if kind == "unblocked":
        return i18n.t("Unblocked")
    if kind == "opt_in":
        return i18n.t("Agreed to get messages")
    if kind == "opt_out":
        return i18n.t("Opted out of messages")
    if kind == "campaign_sent":
        return i18n.t("Got the campaign “{n}”").format(n=d.get("campaign"))
    if kind == "chat_requested":
        return i18n.t("Asked for a person")
    if kind == "chat_intervened":
        return i18n.t("A teammate took over the chat")
    if kind == "chat_transferred":
        return i18n.t("Chat given to another teammate")
    if kind == "chat_resolved":
        return i18n.t("Chat resolved")
    if kind == "chat_assigned":
        return i18n.t("Chat assigned to a teammate")
    if kind == "chat_reopened":
        return i18n.t("Chat reopened")
    if kind == "chat_note":
        return i18n.t("A note was added")
    return str(kind or "").replace("_", " ").capitalize()


class _Chip(QFrame):
    removed = Signal(str)

    def __init__(self, tag: str, parent=None):
        super().__init__(parent)
        self.setObjectName("waTag")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("#waTag { background: rgba(0,0,0,0.07); border-radius: 12px; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 3, 4, 3)
        row.setSpacing(2)
        row.addWidget(C.label(tag, level="SUPPORT", weight=600, colour=theme.NEUTRAL[800]))
        x = C.icon_button("x", i18n.t("Remove tag"), colour=theme.NEUTRAL[600])
        x.setFixedSize(20, 20)
        x.clicked.connect(lambda: self.removed.emit(tag))
        row.addWidget(x)


class ProfilePanel(QFrame):
    changed = Signal()
    deleted = Signal(object)
    sendTemplate = Signal(dict)
    startOrder = Signal(dict)              # "New order" for this person: the workbench opens the Shop with them chosen
    sendForm = Signal(dict)                # "Send a form…": the workbench opens Forms with them chosen

    def __init__(self, parent=None, *, allow_delete: bool = True):
        super().__init__(parent)
        self.setObjectName("waProfilePanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.allow_delete = allow_delete
        self._id = None
        self._c: dict | None = None
        self._journey: list = []
        self._more = False
        self._tags: list = []
        self._attr_defs: list = []
        self._error = ""
        self._loading = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        ui.no_sideways(scroll)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)
        self._host = ui.see_through(QWidget())
        scroll.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
        self._col.setSpacing(theme.SPACE_4)
        self._render()

    # ── public ───────────────────────────────────────────────────────────────
    def contact_id(self):
        return self._id

    def clear(self):
        self._id, self._c, self._journey, self._error, self._loading = None, None, [], "", False
        self._render()

    def load(self, contact_id, hint: dict | None = None):
        """Show this person. `hint` (a row we already have) is drawn at once while the full profile arrives."""
        self._id = contact_id
        self._more = False
        self._error = ""
        self._loading = True
        self._c = dict(hint) if hint else None
        self._journey = []
        self._render()
        ui.call(self, "contacts/get", {"contact_id": contact_id}, done=lambda r, cid=contact_id: self._got(cid, r),
                failed=lambda m, _d, cid=contact_id: self._failed(cid, m))
        ui.call(self, "contacts/journey", {"contact_id": contact_id, "limit": 60}, done=lambda r, cid=contact_id: self._got_journey(cid, r),
                failed=lambda _m, _d: None)
        if not self._tags:
            ui.call(self, "tags/list", {}, done=lambda r: setattr(self, "_tags", [t["name"] for t in r.get("tags") or []]), failed=lambda _m, _d: None)
        ui.call(self, "attributes/list", {}, done=lambda r: setattr(self, "_attr_defs", r.get("attributes") or []), failed=lambda _m, _d: None)

    def reload(self):
        if self._id:
            self.load(self._id, self._c)

    def say(self, message: str, error: bool = False):
        self._error = message if error else ""
        self._render()

    # ── loading ──────────────────────────────────────────────────────────────
    def _got(self, cid, reply: dict):
        if cid != self._id:
            return
        self._loading = False
        self._c = reply.get("contact") or self._c
        self._render()

    def _got_journey(self, cid, reply: dict):
        if cid != self._id:
            return
        self._journey = reply.get("journey") or []
        self._render()

    def _failed(self, cid, message: str):
        if cid != self._id:
            return
        self._loading = False
        self._error = message
        self._render()

    # ── drawing ──────────────────────────────────────────────────────────────
    def _render(self):
        ui.clear(self._col)
        c = self._c
        if not c:
            self._col.addStretch(1)
            text = i18n.t("Loading…") if self._loading else (self._error or i18n.t("Select someone to see their details."))
            msg = C.label(text, level="SUPPORT", colour=theme.ERR_INK if self._error else theme.NEUTRAL[600], wrap=True)
            msg.setAlignment(Qt.AlignCenter)
            self._col.addWidget(msg)
            self._col.addStretch(1)
            return
        self._col.addLayout(self._head(c))
        if self._error:
            self._col.addWidget(C.label(self._error, level="SUPPORT", colour=theme.ERR_INK, wrap=True))
        self._col.addWidget(self._facts(c))
        if c.get("counts"):
            self._col.addWidget(self._counts(c["counts"]))
        self._col.addWidget(self._attributes(c))
        self._col.addWidget(self._tags_block(c))
        if c.get("campaigns"):
            self._col.addWidget(self._campaigns(c["campaigns"]))
        self._col.addWidget(self._journey_block())
        self._col.addWidget(self._consent_block(c))
        self._col.addStretch(1)
        ui.let_text_wrap(self._host)

    def _title(self, text: str) -> QWidget:
        return C.label(text.upper(), level="LABEL", colour=theme.NEUTRAL[500])

    def _box(self, title: str) -> tuple:
        box = QWidget()
        col = QVBoxLayout(box)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        col.addWidget(C.hairline())
        col.addWidget(self._title(title))
        return box, col

    def _head(self, c: dict) -> QVBoxLayout:
        who = c.get("name") or c.get("phone") or i18n.t("Unknown")
        head = QVBoxLayout()
        head.setSpacing(theme.SPACE_2)
        head.addWidget(C.Avatar(who, 68, avatar_colour(who, bool(c.get("opted_out")))), alignment=Qt.AlignHCenter)
        name = C.label(who, level="SECTION", weight=700, wrap=True)
        name.setAlignment(Qt.AlignHCenter)
        head.addWidget(name)
        phone = c.get("phone") or ""
        if phone:
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_1)
            line.addStretch(1)
            line.addWidget(C.label(phone if phone.startswith("*") else "+" + phone.lstrip("+"), level="SUPPORT", colour=theme.NEUTRAL[600]))
            if not phone.startswith("*"):
                copy = C.icon_button("copy", i18n.t("Copy number"), colour=theme.NEUTRAL[600])
                copy.setFixedSize(24, 24)
                copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(phone))
                line.addWidget(copy)
            line.addStretch(1)
            head.addLayout(line)
        pills = [C.Pill(i18n.t("Opted out") if c.get("opted_out") else i18n.t("Opted in") if c.get("opted_in") else i18n.t("Not asked yet"),
                        "warn" if c.get("opted_out") else "ok" if c.get("opted_in") else "quiet")]
        if c.get("blocked"):
            pills.append(C.Pill(i18n.t("Blocked"), "err"))
        pills.append(C.Pill(i18n.t("Window open") if c.get("window_open") else i18n.t("Window closed"), "ok" if c.get("window_open") else "quiet"))
        state = {"active": i18n.t("With the bot"), "requesting": i18n.t("Needs a person"), "intervened": i18n.t("With an agent"),
                 "human_takeover": i18n.t("With an agent"), "closed": i18n.t("Resolved")}.get(c.get("state") or "")
        if state:
            pills.append(C.Pill(state, "info" if c.get("state") == "requesting" else "quiet"))
        head.addWidget(ui.centered_row(*pills))
        self.order_btn = C.button(i18n.t("New order"), "secondary", small=True, on_click=lambda: self.startOrder.emit(dict(self._c or {})))
        self.form_btn = C.button(i18n.t("Send a form…"), "secondary", small=True, on_click=lambda: self.sendForm.emit(dict(self._c or {})))
        head.addWidget(ui.centered_row(
            C.button(i18n.t("Edit"), "secondary", small=True, on_click=self._edit),
            C.button(i18n.t("Send a template"), "secondary", small=True, on_click=lambda: self.sendTemplate.emit(dict(self._c or {}))),
            self.order_btn, self.form_btn, h_space=theme.SPACE_2, v_space=theme.SPACE_2))
        return head

    def _facts(self, c: dict) -> QWidget:
        box, col = self._box(i18n.t("Details"))
        rows = [(i18n.t("Email"), c.get("email")), (i18n.t("Company"), c.get("company")), (i18n.t("Source"), c.get("source")),
                (i18n.t("First message"), c.get("first_msg_tag")),
                (i18n.t("Last wrote"), short_time(c.get("last_seen") or "") if c.get("last_seen") else i18n.t("Never")),
                (i18n.t("Added"), short_time(c.get("created_at") or ""))]
        for k, v in rows:
            if not v:
                continue
            line = QHBoxLayout()
            line.addWidget(C.label(k, level="SUPPORT", colour=theme.NEUTRAL[600]))
            val = C.label(str(v), level="SUPPORT", weight=600, wrap=True)
            val.setAlignment(Qt.AlignRight)
            line.addWidget(val, stretch=1)                      # the value takes the rest of the row, so it can wrap and is never squeezed out
            col.addLayout(line)
        return box

    def _counts(self, counts: dict) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        for label, key in ((i18n.t("Templates sent"), "template_messages"), (i18n.t("Chat messages"), "session_messages"),
                           (i18n.t("Asked for a person"), "unresolved_queries")):
            card = QFrame()
            card.setObjectName("waCount")
            card.setAttribute(Qt.WA_StyledBackground, True)
            card.setStyleSheet("#waCount { background: rgba(0,0,0,0.04); border-radius: 10px; }")
            col = QVBoxLayout(card)
            col.setContentsMargins(10, 8, 10, 8)
            col.setSpacing(0)
            num = C.label(str(counts.get(key, 0)), level="CARD_TITLE", weight=700)
            num.setAlignment(Qt.AlignHCenter)
            col.addWidget(num)
            cap = C.label(label, level="META", colour=theme.NEUTRAL[600], wrap=True)
            cap.setAlignment(Qt.AlignHCenter)
            col.addWidget(cap)
            row.addWidget(card, stretch=1)
        return box

    def _attributes(self, c: dict) -> QWidget:
        box, col = self._box(i18n.t("Attributes"))
        attrs = c.get("attrs") or {}
        if not attrs:
            col.addWidget(C.label(i18n.t("Nothing saved yet. Use Edit to add details such as their city."), level="META", colour=theme.NEUTRAL[600], wrap=True))
        for k, v in sorted(attrs.items()):
            line = QHBoxLayout()
            line.addWidget(C.label(k, level="SUPPORT", colour=theme.NEUTRAL[600]))
            val = C.label(str(v), level="SUPPORT", weight=600, wrap=True)
            val.setAlignment(Qt.AlignRight)
            line.addWidget(val, stretch=1)                      # the value takes the rest of the row, so it can wrap and is never squeezed out
            col.addLayout(line)
        return box

    def _tags_block(self, c: dict) -> QWidget:
        box, col = self._box(i18n.t("Tags"))
        tags = [t for t in (c.get("tags") or []) if isinstance(t, str) and t]
        if tags:
            holder = QWidget()
            flow = C.FlowLayout(holder, h_space=6, v_space=6)
            for t in tags:
                chip = _Chip(t)
                chip.removed.connect(self._remove_tag)
                flow.addWidget(chip)
            col.addWidget(holder)
        add = QLineEdit()
        add.setPlaceholderText(i18n.t("Add a tag and press Enter"))
        add.setMinimumHeight(34)
        comp = QCompleter([t for t in self._tags if t not in tags], add)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        add.setCompleter(comp)
        add.returnPressed.connect(lambda: self._add_tag(add))
        col.addWidget(add)
        return box

    def _campaigns(self, items: list) -> QWidget:
        box, col = self._box(i18n.t("Campaigns they got"))
        for it in items[:5]:
            line = QHBoxLayout()
            line.addWidget(C.label(it.get("name") or "", level="SUPPORT", weight=600), stretch=1)
            line.addWidget(C.label(short_time(str(it.get("at") or "")), level="META", colour=theme.NEUTRAL[600]))
            col.addLayout(line)
        return box

    def _journey_block(self) -> QWidget:
        box, col = self._box(i18n.t("Customer journey"))
        if not self._journey:
            col.addWidget(C.label(i18n.t("Nothing yet.") if not self._loading else i18n.t("Loading…"), level="META", colour=theme.NEUTRAL[600]))
            return box
        shown = self._journey if self._more else self._journey[:JOURNEY_SHOWN]
        for e in shown:
            line = QVBoxLayout()
            line.setSpacing(0)
            line.addWidget(C.label(journey_words(e), level="SUPPORT", wrap=True))
            by = ("%s · " % e["who"]) if e.get("who") else ""
            line.addWidget(C.label(by + short_time(str(e.get("at") or "")), level="META", colour=theme.NEUTRAL[500]))
            col.addLayout(line)
        if len(self._journey) > JOURNEY_SHOWN and not self._more:
            col.addWidget(C.button(i18n.t("Show all {n}").format(n=len(self._journey)), "tertiary", small=True, on_click=self._show_more), alignment=Qt.AlignLeft)
        return box

    def _consent_block(self, c: dict) -> QWidget:
        box, col = self._box(i18n.t("Messaging"))
        row = QHBoxLayout()
        row.addWidget(C.label(i18n.t("Opted out of messages"), level="BODY", weight=600, wrap=True), stretch=1)
        sw = C.ToggleSwitch()
        sw.setChecked(bool(c.get("opted_out")))
        sw.toggled.connect(self._toggle_opt)
        row.addWidget(sw)
        col.addLayout(row)
        col.addWidget(C.label(i18n.t("Opted-out contacts are skipped by every campaign and can't be written to first."), level="META", colour=theme.NEUTRAL[600], wrap=True))
        row2 = QHBoxLayout()
        row2.addWidget(C.label(i18n.t("Blocked"), level="BODY", weight=600, wrap=True), stretch=1)
        sw2 = C.ToggleSwitch()
        sw2.setChecked(bool(c.get("blocked")))
        sw2.toggled.connect(self._toggle_block)
        row2.addWidget(sw2)
        col.addLayout(row2)
        if self.allow_delete:
            col.addWidget(C.button(i18n.t("Delete this contact"), "tertiary", small=True, on_click=self._delete), alignment=Qt.AlignLeft)
        return box

    # ── edits ────────────────────────────────────────────────────────────────
    def _show_more(self):
        self._more = True
        self._render()

    def _edit(self):
        from addons.whatsapp.contact_dialogs import EditContactDialog
        if not self._c:
            return
        dlg = EditContactDialog(self._c, self._attr_defs, self)
        if dlg.exec():
            self.reload()
            self.changed.emit()

    def _set_tags(self, add=(), remove=()):
        if not self._id:
            return
        ui.call(self, "contacts/tags/set", {"contact_ids": [self._id], "add": list(add), "remove": list(remove)},
                done=lambda _r: (self.reload(), self.changed.emit()), failed=lambda m, _d: self.say(m, error=True))

    def _add_tag(self, edit: QLineEdit):
        tag = edit.text().strip()
        if tag and self._c and tag.lower() not in (t.lower() for t in self._c.get("tags") or []):
            self._set_tags(add=[tag])
        edit.clear()

    def _remove_tag(self, tag: str):
        self._set_tags(remove=[tag])

    def _toggle_opt(self, checked: bool):
        if not self._id:
            return
        if not checked and not ui.confirm(self, i18n.t("Start messaging again?"),
                                          i18n.t("Only do this if they have asked to hear from you again. Messaging someone who opted out can get your number restricted.")):
            self._render()
            return
        ui.call(self, "contacts/consent", {"contact_id": self._id, "action": "opt_out" if checked else "opt_in"},
                done=lambda _r: (self.reload(), self.changed.emit()), failed=lambda m, _d: (self.say(m, error=True)))

    def _toggle_block(self, checked: bool):
        if self._id:
            ui.call(self, "contacts/block", {"contact_ids": [self._id], "blocked": checked}, done=lambda _r: (self.reload(), self.changed.emit()),
                    failed=lambda m, _d: self.say(m, error=True))

    def _delete(self):
        if not (self._id and self._c):
            return
        if not ui.confirm(self, i18n.t("Delete this contact"),
                          i18n.t("Delete {n}? Their chats, details and consent history are removed for good.").format(n=self._c.get("name") or self._c.get("phone"))):
            return
        cid = self._id
        ui.call(self, "contacts/delete", {"contact_ids": [cid]}, done=lambda _r: (self.clear(), self.deleted.emit(cid), self.changed.emit()),
                failed=lambda m, _d: self.say(m, error=True))
