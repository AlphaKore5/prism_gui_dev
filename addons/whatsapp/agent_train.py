"""Train: talk to the agent as a customer would, before any customer does.

This always talks to the DRAFT — what is on screen — not to the published copy. It uses a few of your test messages (not customer replies). Each answer says which of
your notes it used, which details it would have collected (nothing is saved while you are trying it), and what it would have called — an action that changes something
is not really run here, so a booking is never made by trying the agent out.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp import ui
from widgets import controls as C


class TrainPanel(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.messages: list = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("Try it"), level="CARD_TITLE"), stretch=1)
        top.addWidget(C.button(i18n.t("Start again"), "tertiary", on_click=self.reset))
        col.addLayout(top)
        self.banner = C.label("", level="META", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.banner)
        self.chat = QVBoxLayout()
        self.chat.setSpacing(theme.SPACE_1)
        col.addLayout(self.chat)
        col.addStretch(1)                       # the spare height goes here, not into the bubbles above it, which stay as tall as their words
        self.note = ui.note()
        col.addWidget(self.note)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setMinimumHeight(36)
        self.edit.setPlaceholderText(i18n.t("Ask it something a customer would"))
        self.edit.returnPressed.connect(self._send)
        row.addWidget(self.edit, 1)
        self.send = C.button(i18n.t("Ask"), "secondary", on_click=self._send)
        row.addWidget(self.send)
        col.addLayout(row)
        self.refresh_banner()

    def refresh_banner(self):
        a = self.editor.agent
        tests = len(self.editor.draft["settings"].get("test_numbers") or [])
        if a.get("status") == "published":
            head = i18n.t("You are talking to your draft. Customers meet version {v} until you publish.").format(v=a.get("published_version") or 1)
        elif a.get("status") == "paused":
            head = i18n.t("You are talking to your draft. The agent is paused, so customers get no AI answers.")
        else:
            head = i18n.t("You are talking to your draft. Customers meet nothing yet — publish when you are happy.")
        tail = i18n.t("{n} test numbers can chat with the draft on WhatsApp.").format(n=tests) if tests else i18n.t("Add test numbers in Settings to chat with the draft on a real phone.")
        self.banner.setText(head + " " + tail)

    def reset(self):
        self.messages = []
        ui.clear(self.chat)
        self.note.clear_note()

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "quiet")

    def _bubble(self, who: str, text: str, meta: str = ""):
        lab = C.label(text, level="SUPPORT", wrap=True, colour="#ffffff" if who == "customer" else theme.TEXT)
        lab.setStyleSheet(lab.styleSheet() + f" background: {theme.ACCENT if who == 'customer' else theme.NEUTRAL[100]}; border-radius: 12px; padding: 8px 12px;")
        lab.setMaximumWidth(360)
        row = QHBoxLayout()
        if who == "customer":
            row.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(lab)
        if meta:
            col.addWidget(C.label(meta, level="META", colour=theme.NEUTRAL[500], wrap=True))
        row.addLayout(col)
        if who != "customer":
            row.addStretch(1)
        box = QWidget()
        box.setLayout(row)
        self.chat.addWidget(box)

    def _send(self):
        text = self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.messages.append({"from": "customer", "text": text})
        self._bubble("customer", text)
        self.send.setEnabled(False)
        self.editor.ensure_saved(lambda: ui.call(self, "ai/test", {"agent_id": self.editor.agent["id"], "messages": self.messages}, done=self._answer, failed=self._failed))

    def _failed(self, message: str, _detail: dict):
        self.send.setEnabled(True)
        self.messages.pop()
        self.say(message, error=True)

    def _answer(self, reply: dict):
        self.send.setEnabled(True)
        a = reply.get("answer") or {}
        self.note.clear_note()
        meta = []
        if a.get("sources"):
            meta.append(i18n.t("Used: {s}").format(s=", ".join(a["sources"])))
        if a.get("collected"):
            meta.append(i18n.t("It would keep: {d}").format(d=", ".join("%s = %s" % (k, v) for k, v in a["collected"].items())))
        ran = a.get("ran_action")
        if ran:
            meta.append((i18n.t("It called “{n}”.") if ran.get("ran") else i18n.t("It would call “{n}” (not run here).")).format(n=ran.get("name")))
        if a.get("handoff"):
            meta.append(i18n.t("It would hand this chat to your team — {r}").format(r=a.get("reason") or i18n.t("it asked for a person")))
        self.messages.append({"from": "bot", "text": a.get("reply") or ""})
        self._bubble("bot", a.get("reply") or "…", "  ·  ".join(meta))
