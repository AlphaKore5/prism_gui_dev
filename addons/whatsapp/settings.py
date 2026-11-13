"""The Settings tab — everything about how the workspace is set up, in sections.

    Connection      is it reachable, and the WhatsApp numbers on this workspace (and how to connect one)
    Test message    your number's credentials and a plain test send, straight to Meta
    Team and inbox  who works the inbox, who sees what, auto-replies and working hours
    Quick replies   saved answers a teammate types with a slash
    Tags and attributes   the labels and details you keep about people
    Opt-in and opt-out    the words a customer sends to stop or start hearing from you
    Notifications   the pop-up and sound when a chat needs a person
    Stores          Shopify and WooCommerce orders turned into WhatsApp messages
    Developers      API keys for your own software

Inbox, Contacts and Campaigns need nothing configured here: they go through Prism's licence server, which already
knows which seat is calling. Each section is built the first time it is opened, so an unopened one costs nothing.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit,
                               QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget)

import core_bridge as CB
import i18n
import theme
from addons.whatsapp import demo, ui
from addons.whatsapp.workers import WhatsAppSendWorker
from widgets import controls as C

_COLUMN = 720


def _scrolled(build) -> tuple:
    """A section's own scroll area with a centred column; returns (outer widget, column layout)."""
    outer = QWidget()
    lay = QVBoxLayout(outer)
    lay.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.viewport().setAutoFillBackground(False)
    lay.addWidget(scroll)
    host = QWidget()
    ui.see_through(host)
    scroll.setWidget(host)
    page = QHBoxLayout(host)
    page.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
    col = QVBoxLayout()
    col.setSpacing(theme.SPACE_4)
    page.addStretch(1)
    page.addLayout(col, stretch=0)
    page.addStretch(1)
    return outer, col


class ConnectionSection(QWidget):
    """Is it reachable, and which numbers are connected."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer, col = _scrolled(None)
        QVBoxLayout(self).addWidget(outer)
        self.layout().setContentsMargins(0, 0, 0, 0)

        card, cc = ui.card("", width=_COLUMN)
        head = QHBoxLayout()
        head.addWidget(C.label(i18n.t("Connection"), level="CARD_TITLE"), stretch=1)
        self.conn_pill = C.Pill(i18n.t("Checking…"), "quiet")
        head.addWidget(self.conn_pill)
        cc.addLayout(head)
        self.conn_text = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        cc.addWidget(self.conn_text)
        row = QHBoxLayout()
        row.addWidget(C.button(i18n.t("Check again"), "secondary", small=True, on_click=self.check))
        row.addStretch(1)
        cc.addLayout(row)
        col.addWidget(card)

        card, nc = ui.card(i18n.t("WhatsApp numbers"),
                           i18n.t("The numbers your customers message. Connecting one takes a few minutes in Meta's own window — "
                                  "you sign in to Facebook and choose the number."), width=_COLUMN)
        self._after_list = ""
        self.numbers_col = QVBoxLayout()
        self.numbers_col.setSpacing(theme.SPACE_2)
        nc.addLayout(self.numbers_col)
        self.numbers_note = ui.note()
        nc.addWidget(self.numbers_note)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.connect_btn = C.button(i18n.t("Connect a number"), "primary", icon_name="plus", on_click=self._connect)
        row.addWidget(self.connect_btn)
        self.connect_co_btn = C.button(i18n.t("Connect and keep using the phone app"), "secondary", on_click=lambda: self._connect(True))
        row.addWidget(self.connect_co_btn)
        row.addWidget(C.button(i18n.t("Refresh"), "secondary", on_click=self.load_numbers))
        row.addStretch(1)
        nc.addLayout(row)
        row = QHBoxLayout()                                             # its own line: three connect buttons and Refresh do not fit the column side by side
        self.attach_btn = C.button(i18n.t("Connect with an access token"), "secondary", on_click=lambda _checked=False: self._connect_with_token())
        row.addWidget(self.attach_btn)
        row.addStretch(1)
        nc.addLayout(row)
        self.limits_col = QVBoxLayout()
        self.limits_col.setSpacing(theme.SPACE_2)
        nc.addLayout(self.limits_col)
        self.co_col = QVBoxLayout()                                     # numbers also used in the WhatsApp Business app on the owner's phone
        self.co_col.setSpacing(theme.SPACE_2)
        nc.addLayout(self.co_col)
        self.limits_btn = C.button(i18n.t("Check limits with Meta"), "secondary", small=True, on_click=self._ask_meta)
        nc.addWidget(self.limits_btn, alignment=Qt.AlignLeft)
        self.link_row = QWidget()
        lr = QVBoxLayout(self.link_row)
        lr.setContentsMargins(0, 0, 0, 0)
        lr.setSpacing(4)
        lr.addWidget(C.label(i18n.t("If your browser didn't open, copy this link into it:"), level="META", colour=theme.NEUTRAL[600]))
        self.link_edit = QLineEdit()
        self.link_edit.setReadOnly(True)
        self.link_edit.setMinimumHeight(34)
        lr.addWidget(self.link_edit)
        self.link_row.hide()
        nc.addWidget(self.link_row)
        col.addWidget(card)
        col.addStretch(1)

    def say(self, text: str, error: bool = False):
        self.numbers_note.set(text, "error" if error else "quiet")

    # ── connection ───────────────────────────────────────────────────────────
    def activate(self):
        self.check()
        self.load_numbers()

    def check(self):
        self.conn_pill.setText(i18n.t("Checking…"))
        self.conn_pill.set_tone("quiet")
        self.conn_text.setText("")
        ui.call(self, "tags/list", {}, done=self._connected, failed=lambda m, _d: self._not_connected(m))

    def _connected(self, _tags):
        self.conn_pill.setText(i18n.t("Connected"))
        self.conn_pill.set_tone("ok")
        if demo.enabled():
            self.conn_pill.setText(i18n.t("Demo data"))
            self.conn_pill.set_tone("warn")
            self.conn_text.setText(i18n.t(
                "You're looking at sample conversations for design and testing — nothing here "
                "is real, and nothing you do is sent."))
        else:
            self.conn_text.setText(i18n.t(
                "Your inbox, contacts and campaigns are reaching Prism's licence server, "
                "and it can reach your WhatsApp data."))

    def _not_connected(self, error: str):
        self.conn_pill.setText(i18n.t("Not connected"))
        self.conn_pill.set_tone("err")
        self.conn_text.setText(error)

    # ── numbers ──────────────────────────────────────────────────────────────
    def load_numbers(self):
        ui.call(self, "numbers/list", done=self._numbers, failed=self._numbers_failed)
        ui.call(self, "numbers/limits", done=self._limits, failed=lambda _m, _d: None)
        ui.call(self, "coexistence/numbers", done=self._coexistence, failed=lambda _m, _d: None)

    def _coexistence(self, reply: dict):
        """Under the numbers: for a number that is also used in the WhatsApp Business app on the phone, how the copy of its contacts and chats is going."""
        ui.clear(self.co_col)
        for n in reply.get("numbers") or []:
            if not n.get("coexistence"):
                if n.get("status") == "connected":
                    row = QHBoxLayout()
                    row.setSpacing(theme.SPACE_2)
                    row.addWidget(C.label(i18n.t("{d} is also used in the WhatsApp Business app on my phone").format(d=n.get("display") or ""), level="META", colour=theme.NEUTRAL[600]), 1)
                    row.addWidget(C.button(i18n.t("Yes, it is"), "tertiary", small=True, on_click=lambda _=False, i=n["id"]: self._mark_coexistence(i)))
                    holder = QWidget()
                    holder.setLayout(row)
                    row.setContentsMargins(0, 0, 0, 0)
                    self.co_col.addWidget(holder)
                continue
            st = n.get("state") or {}
            facts = [i18n.t("Shared with the WhatsApp Business app on your phone")]
            if st.get("contacts"):
                facts.append(i18n.t("Contacts: {w}").format(w=(i18n.t("{n} copied").format(n=st["contacts_imported"]) if st.get("contacts_imported") else str(st["contacts"]))))
            if st.get("history"):
                facts.append(i18n.t("Past chats: {w}").format(w={"importing": i18n.t("copying ({p}%, {m} messages so far)").format(p=st.get("history_progress") or 0, m=st.get("history_messages") or 0),
                                                                    "done": i18n.t("copied ({m} messages)").format(m=st.get("history_messages") or 0),
                                                                    "declined": i18n.t("you chose not to share them")}.get(st["history"], str(st["history"]))))
            elif st.get("history_request"):
                facts.append(i18n.t("Past chats: {w}").format(w=st["history_request"]))
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_2)
            line = C.label("%s: %s" % (n.get("display") or "", "  ·  ".join(facts)), level="META", colour=theme.NEUTRAL[700], wrap=True)
            row.addWidget(line, 1)
            row.addWidget(C.button(i18n.t("Ask Meta again"), "tertiary", small=True, on_click=lambda _=False, i=n["id"]: self._sync_coexistence(i)))
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            self.co_col.addWidget(holder)

    def _sync_coexistence(self, number_id):
        ui.call(self, "coexistence/sync", {"number_id": number_id}, done=lambda r: (self.load_numbers(), self.say(i18n.t("Asked Meta for the phone's contacts and chats. Meta only allows this in the first 24 hours "
                                                                                                  "after connecting."))))

    def _mark_coexistence(self, number_id):
        ui.call(self, "coexistence/mark", {"number_id": number_id, "enabled": True}, done=lambda _r: self.load_numbers())

    def _ask_meta(self):
        self.limits_btn.setEnabled(False)
        self.say(i18n.t("Asking Meta…"))
        ui.call(self, "numbers/refresh", done=self._refreshed, failed=lambda m, _d: (self.limits_btn.setEnabled(True), self.say(m, error=True)))

    def _refreshed(self, reply: dict):
        self.limits_btn.setEnabled(True)
        self._limits(reply)
        problems = reply.get("problems") or []
        self.say(("; ".join("%s: %s" % (p.get("number") or "", p.get("message") or "") for p in problems[:2])) if problems else i18n.t("Up to date."), error=bool(problems))

    def _limits(self, reply: dict):
        """Under the numbers: how many people each may start a chat with in a day, the display-name review, and the speed."""
        ui.clear(self.limits_col)
        names = {"APPROVED": i18n.t("approved"), "PENDING_REVIEW": i18n.t("being reviewed"), "DECLINED": i18n.t("declined"), "NONE": i18n.t("not needed"),
                 "AVAILABLE_WITHOUT_REVIEW": i18n.t("approved")}
        for n in reply.get("numbers") or []:
            if not (n.get("tier") or n.get("name_status")):
                continue
            facts = []
            if n.get("unlimited"):
                facts.append(i18n.t("May start chats with any number of people a day"))
            elif n.get("daily_limit"):
                facts.append(i18n.t("May start chats with {n} people a day").format(n=format(int(n["daily_limit"]), ",")))
                if n.get("next_limit"):
                    facts.append(i18n.t("next step: {n}").format(n=format(int(n["next_limit"]), ",")))
            if n.get("name_status"):
                facts.append(i18n.t("Display name {s}").format(s=names.get(n["name_status"], str(n["name_status"]).replace("_", " ").lower())))
            if n.get("throughput"):
                facts.append(i18n.t("Speed {s}").format(s=str(n["throughput"]).lower()))
            self.limits_col.addWidget(C.label("%s: %s" % (n.get("display") or "", "  ·  ".join(facts)), level="META", colour=theme.NEUTRAL[700], wrap=True))

    def _numbers_failed(self, message: str, _detail: dict):
        ui.clear(self.numbers_col)
        self.say(message, error=True)

    def _numbers(self, reply: dict):
        self.say(self._after_list)                  # a line that belongs after the list is shown, such as "Connected" (the list otherwise starts clean)
        self._after_list = ""
        ui.clear(self.numbers_col)
        rows = list(reply.get("numbers") or [])
        if not rows:
            self.numbers_col.addWidget(C.label(i18n.t("No number is connected yet."), level="SUPPORT", colour=theme.NEUTRAL[700]))
        for n in rows:
            line = QFrame()
            line.setObjectName("waNumber")
            line.setAttribute(Qt.WA_StyledBackground, True)
            line.setStyleSheet(f"#waNumber {{ background: rgba(255,255,255,0.55); border: 1px solid {theme.HAIRLINE};"
                               f" border-radius: {theme.R_CONTROL}px; }}")
            rl = QHBoxLayout(line)
            rl.setContentsMargins(14, 10, 14, 10)
            rl.addWidget(C.label(str(n.get("display") or i18n.t("A WhatsApp number")), level="SUPPORT", weight=700), stretch=1)
            status = str(n.get("status") or "").upper()
            rl.addWidget(C.Pill({"CONNECTED": i18n.t("Connected")}.get(status, status.capitalize() or "—"), "ok" if status == "CONNECTED" else "quiet"))
            quality = str(n.get("quality") or "").upper()
            if quality:
                rl.addWidget(C.Pill({"GREEN": i18n.t("Quality: high"), "YELLOW": i18n.t("Quality: medium"), "RED": i18n.t("Quality: low")}.get(quality, quality.capitalize()),
                                    {"GREEN": "ok", "YELLOW": "warn", "RED": "err"}.get(quality, "quiet")))
            self.numbers_col.addWidget(line)

    def _connect_buttons(self, on: bool):
        for b in (self.connect_btn, self.connect_co_btn, self.attach_btn):
            b.setEnabled(on)

    def _connect(self, coexistence: bool = False):
        self._connect_buttons(False)
        ui.call(self, "onboarding/link", {"coexistence": True} if coexistence is True else {}, done=self._link, failed=self._link_failed)

    def _ask_for_token(self):
        """The three boxes, or None when cancelled. A method of its own so a test can answer for the window."""
        from PySide6.QtWidgets import QDialog
        from addons.whatsapp.attach_dialog import AttachDialog
        dialog = AttachDialog(self)
        return dialog.value() if dialog.exec() == QDialog.Accepted else None

    def _connect_with_token(self):
        values = self._ask_for_token()
        if values:
            self._attach(values)

    def _attach(self, values: dict):
        """Connect a number that is already live, from its ids and an access token. The token goes to the server and nowhere else."""
        self._connect_buttons(False)
        self.say(i18n.t("Connecting…"))
        ui.call(self, "onboarding/attach", values, done=self._attached, failed=self._link_failed)

    def _attached(self, reply: dict):
        self._connect_buttons(True)
        if reply.get("subscribed") and reply.get("registered"):
            self._after_list = i18n.t("Connected. Your number is in the list above.")
            self.say(self._after_list)
            self.load_numbers()
        else:
            self.say(i18n.t("The number was saved, but Meta did not finish setting it up. Press Connect with an access token to try again."), error=True)

    def _link_failed(self, message: str, _detail: dict):
        self._connect_buttons(True)
        self.say(message, error=True)

    def _link(self, reply: dict):
        self._connect_buttons(True)
        url = str(reply.get("url") or "")
        if not url.startswith(("http://", "https://")):
            self.say(i18n.t("The server did not give a link to open. Ask Alphakore to check the WhatsApp service address."), error=True)
            return
        self.link_edit.setText(url)
        self.link_row.show()
        if not demo.enabled():
            QDesktopServices.openUrl(QUrl(url))
        self.say(i18n.t("Finish connecting in the window that opened, then press Refresh."))


class TestSection(QWidget):
    """Your number's credentials and a plain test send, straight to Meta."""

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        wa = self.cfg.get("whatsapp") or {}
        outer, col = _scrolled(None)
        QVBoxLayout(self).addWidget(outer)
        self.layout().setContentsMargins(0, 0, 0, 0)

        card, cc = ui.card("", width=_COLUMN)
        head = QHBoxLayout()
        head.addWidget(C.label(i18n.t("Your WhatsApp number"), level="CARD_TITLE"), stretch=1)
        self.number_pill = C.Pill("", "quiet")
        head.addWidget(self.number_pill)
        cc.addLayout(head)
        cc.addWidget(C.label(
            i18n.t("Only the test message below uses these. They're kept on this "
                   "computer and sent to nobody but Meta."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self.pnid_edit = QLineEdit(wa.get("phone_number_id", ""))
        self.pnid_edit.setPlaceholderText(i18n.t("From Meta: WhatsApp, then API Setup"))
        self.pnid_edit.setMinimumHeight(38)
        cc.addWidget(ui.field(i18n.t("Phone number ID"), self.pnid_edit))
        self.token_edit = QLineEdit(wa.get("token", ""))
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setPlaceholderText(i18n.t("Access token"))
        self.token_edit.setMinimumHeight(38)
        cc.addWidget(ui.field(i18n.t("Access token"), self.token_edit))
        row = QHBoxLayout()
        self.save_status = QLabel("")
        row.addWidget(self.save_status, stretch=1)
        row.addWidget(C.button(i18n.t("Save"), "secondary", small=True, icon_name="check", on_click=self._save))
        cc.addLayout(row)
        col.addWidget(card)
        self._set_number_pill()

        card, cc = ui.card(i18n.t("Send a test message"),
                           i18n.t("Straight to Meta, outside the CRM — it isn't logged and isn't part of "
                                  "any conversation. A plain message only reaches someone who wrote to "
                                  "you in the last 24 hours."), width=_COLUMN)
        self.to_edit = QLineEdit(wa.get("last_to", ""))
        self.to_edit.setPlaceholderText(i18n.t("Full number with country code, e.g. 919812345678"))
        self.to_edit.setMinimumHeight(38)
        cc.addWidget(ui.field(i18n.t("To"), self.to_edit))
        self.body_edit = QPlainTextEdit()
        self.body_edit.setPlaceholderText(i18n.t("Your message"))
        self.body_edit.setFixedHeight(84)
        cc.addWidget(ui.field(i18n.t("Message"), self.body_edit))
        row = QHBoxLayout()
        self.send_status = QLabel("")
        self.send_status.setWordWrap(True)
        row.addWidget(self.send_status, stretch=1)
        self.template_btn = C.button(i18n.t("Send hello_world template"), "secondary", on_click=self._send_template)
        row.addWidget(self.template_btn)
        self.send_btn = C.button(i18n.t("Send test message"), "primary", on_click=self._send)
        row.addWidget(self.send_btn)
        cc.addLayout(row)
        self.log = QListWidget()
        self.log.setFrameShape(QFrame.NoFrame)
        self.log.setMaximumHeight(110)
        self.log.setStyleSheet("QListWidget { background: transparent; }")
        cc.addWidget(self.log)
        col.addWidget(card)
        col.addStretch(1)

    def activate(self):
        pass

    # ── credentials ──────────────────────────────────────────────────────────
    def _set_number_pill(self):
        ok = bool(self.pnid_edit.text().strip() and self.token_edit.text().strip())
        self.number_pill.setText(i18n.t("Set") if ok else i18n.t("Not set"))
        self.number_pill.set_tone("ok" if ok else "quiet")

    def _save(self):
        block = dict(self.cfg.get("whatsapp") or {})
        block["phone_number_id"] = self.pnid_edit.text().strip()
        block["token"] = self.token_edit.text().strip()
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception as e:                              # noqa: BLE001
            self.save_status.setStyleSheet(f"color: {theme.ERR_INK};")
            self.save_status.setText(i18n.t("Couldn't save: {e}").format(e=e))
            return
        self.save_status.setStyleSheet(f"color: {theme.OK_INK};")
        self.save_status.setText(i18n.t("Saved."))
        self._set_number_pill()

    # ── test send ────────────────────────────────────────────────────────────
    def _send(self):
        pnid = self.pnid_edit.text().strip()
        token = self.token_edit.text().strip()
        to = "".join(c for c in self.to_edit.text().strip() if c.isdigit())
        body = self.body_edit.toPlainText().strip()
        if not pnid or not token:
            self._say(i18n.t("Add your phone number ID and access token above first."), "err")
            return
        if not to or not body:
            self._say(i18n.t("Enter a recipient number and a message."), "err")
            return
        block = dict(self.cfg.get("whatsapp") or {})
        block["last_to"] = to
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception:                                   # noqa: BLE001
            pass
        self.send_btn.setEnabled(False)
        self._say(i18n.t("Sending…"), "muted")
        w = WhatsAppSendWorker(pnid, token, to, body)
        w.done.connect(lambda wamid, t=to: self._sent(t, wamid))
        w.failed.connect(lambda e, t=to: self._failed(t, e))
        self._send_worker = w
        w.start()

    def _send_template(self):
        pnid = self.pnid_edit.text().strip()
        token = self.token_edit.text().strip()
        to = "".join(c for c in self.to_edit.text().strip() if c.isdigit())
        if not pnid or not token:
            self._say(i18n.t("Add your phone number ID and access token above first."), "err")
            return
        if not to:
            self._say(i18n.t("Enter a recipient number."), "err")
            return
        block = dict(self.cfg.get("whatsapp") or {})
        block["last_to"] = to
        self.cfg["whatsapp"] = block
        try:
            CB.config.save(self.cfg)
        except Exception:                                   # noqa: BLE001
            pass
        self.send_btn.setEnabled(False)
        self.template_btn.setEnabled(False)
        self._say(i18n.t("Sending template…"), "muted")
        w = WhatsAppSendWorker(pnid, token, to, template="hello_world")
        w.done.connect(lambda wamid, t=to: (self.template_btn.setEnabled(True), self._sent(t, wamid)))
        w.failed.connect(lambda e, t=to: (self.template_btn.setEnabled(True), self._failed(t, e)))
        self._send_worker = w
        w.start()

    def _sent(self, to: str, wamid: str):
        self.send_btn.setEnabled(True)
        self._say(i18n.t("Sent."), "ok")
        self.log.insertItem(0, "%s  to %s  ok  %s" % (datetime.now().strftime("%I:%M %p").lstrip("0"), to, wamid))

    def _failed(self, to: str, error: str):
        self.send_btn.setEnabled(True)
        self._say(i18n.t("Failed: {e}").format(e=error), "err")
        self.log.insertItem(0, "%s  to %s  FAILED  %s" % (datetime.now().strftime("%I:%M %p").lstrip("0"), to, error))

    def _say(self, text: str, tone: str):
        colour = {"err": theme.ERR_INK, "ok": theme.OK_INK}.get(tone, theme.NEUTRAL[600])
        self.send_status.setStyleSheet(f"color: {colour};")
        self.send_status.setText(text)


def _sections() -> list:
    # (key, label) — literal i18n.t calls so the string extractor sees every name
    return [("connection", i18n.t("Connection")), ("test", i18n.t("Test message")), ("team", i18n.t("Team and inbox")),
            ("replies", i18n.t("Quick replies")), ("media", i18n.t("Media library")), ("tags", i18n.t("Tags and attributes")), ("compliance", i18n.t("Opt-in and opt-out")),
            ("notifications", i18n.t("Notifications")), ("profile", i18n.t("Business profile")), ("plan", i18n.t("Plan and usage")),
            ("acquire", i18n.t("Links and QR")), ("bluetick", i18n.t("Blue tick")),
            ("stores", i18n.t("Stores")), ("developers", i18n.t("Developers")),
            ("audit", i18n.t("Audit log")), ("sso", i18n.t("Single sign-on")), ("partner", i18n.t("Branding and resellers"))]


class SettingsPage(QWidget):
    @property
    def cfg(self) -> dict:
        return self._cfg

    @cfg.setter
    def cfg(self, value: dict):
        """The panel re-reads settings and hands them on; the Test section keeps its own copy to save from."""
        self._cfg = value if isinstance(value, dict) else {}
        for key in ("test", "notifications", "bluetick"):
            section = getattr(self, "_sections", {}).get(key)
            if section is not None:
                section.cfg = self._cfg

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self._sections: dict = {}
        self.cfg = cfg
        self._current = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        root.setSpacing(theme.SPACE_4)
        rail = QVBoxLayout()
        rail.setSpacing(2)
        self._buttons: dict = {}
        for key, label in _sections():
            b = QPushButton(label)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self._buttons[key] = b
            rail.addWidget(b)
        rail.addStretch(1)
        holder = QWidget()
        ui.see_through(holder)
        holder.setLayout(rail)
        rail_scroll = QScrollArea()
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail_scroll.viewport().setAutoFillBackground(False)
        rail_scroll.setWidget(holder)
        rail_scroll.setFixedWidth(206)
        root.addWidget(rail_scroll)
        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)
        self.show_section("connection")

    def _style(self, active: str):
        for key, b in self._buttons.items():
            if key == active:
                b.setStyleSheet(f"QPushButton {{ text-align: left; padding: 9px 12px; border: none; border-radius: {theme.R_CONTROL}px;"
                                f" background: {theme.NEUTRAL[100]}; color: {theme.TEXT}; font-weight: 700; font-size: 13px; }}")
            else:
                b.setStyleSheet(f"QPushButton {{ text-align: left; padding: 9px 12px; border: none; border-radius: {theme.R_CONTROL}px;"
                                f" background: transparent; color: {theme.NEUTRAL[700]}; font-size: 13px; }}"
                                f"QPushButton:hover {{ background: {theme.NEUTRAL[100]}; }}")

    def _section(self, key: str) -> QWidget:
        if key in self._sections:
            return self._sections[key]
        if key == "connection":
            w = ConnectionSection()
        elif key == "test":
            w = TestSection(self.cfg)
        elif key == "team":
            from addons.whatsapp.settings_team import TeamSection
            w = TeamSection()
        elif key == "replies":
            from addons.whatsapp.settings_team import QuickRepliesSection
            w = QuickRepliesSection()
        elif key == "media":
            from addons.whatsapp.settings_media import MediaSection
            w = MediaSection()
        elif key == "tags":
            from addons.whatsapp.settings_book import TagsAttributesSection
            w = TagsAttributesSection()
        elif key == "compliance":
            from addons.whatsapp.settings_book import ComplianceSection
            w = ComplianceSection()
        elif key == "notifications":
            from addons.whatsapp.settings_book import NotificationsSection
            w = NotificationsSection(self.cfg)
        elif key == "profile":
            from addons.whatsapp.settings_profile import ProfileSection
            w = ProfileSection()
        elif key == "plan":
            from addons.whatsapp.settings_plan import PlanSection
            w = PlanSection()
        elif key == "acquire":
            from addons.whatsapp.settings_acquire import AcquireSection
            w = AcquireSection()
        elif key == "bluetick":
            from addons.whatsapp.settings_profile import BlueTickSection
            w = BlueTickSection(self.cfg)
        elif key == "stores":
            from addons.whatsapp.settings_stores import StoresSection
            w = StoresSection()
        elif key == "audit":
            from addons.whatsapp.settings_audit import AuditSection
            w = AuditSection()
        elif key == "sso":
            from addons.whatsapp.settings_sso import SsoSection
            w = SsoSection()
        elif key == "partner":
            from addons.whatsapp.settings_partner import PartnerSection
            w = PartnerSection()
        else:
            from addons.whatsapp.settings_developers import DevelopersSection
            w = DevelopersSection()
        self._sections[key] = w
        self._stack.addWidget(w)
        return w

    def show_section(self, key: str):
        self._current = key
        self._style(key)
        w = self._section(key)
        self._stack.setCurrentWidget(w)
        w.activate()

    def activate(self):
        self.show_section(self._current or "connection")
