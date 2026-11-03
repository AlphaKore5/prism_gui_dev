"""Automations → Flows: the chatbot, drawn as steps.

A flow answers customers by itself: it says something, asks a question, waits for the reply, tags the contact, hands over to
your team. You choose what starts it (a keyword, a new customer's first message, a click on an ad...) and build the steps one
under another, each saying where it goes next. Nothing is ever lost or half-saved:

  · the draft saves itself a moment after every change;
  · the checks run on the server on every save and are listed beside the steps — a problem names its step and a click takes
    you there;
  · publishing is a separate act that refuses a flow with problems, so customers only ever meet a flow that passed;
  · "Try it" walks the flow as a pretend customer without sending anything;
  · every publish is kept, and an earlier one can be brought back.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import QDateTime, QTimer, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateTimeEdit, QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QSplitter, QStackedWidget, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import flow_model as M
from addons.whatsapp import ui
from addons.whatsapp.chat import short_time
from addons.whatsapp.flow_ai_dialog import AIFlowDialog
from addons.whatsapp.flow_canvas import FlowCanvas
from addons.whatsapp.flow_link_dialog import FlowLinkDialog
from addons.whatsapp.flow_results import FlowResults
from addons.whatsapp.flow_steps import StepCard
from dialogs.base import PrismDialog
from widgets import controls as C

SAVE_MS = 1200


def trigger_types() -> list:
    return [("keyword", i18n.t("A keyword is sent")), ("first_message", i18n.t("A new customer's first message")),
            ("default", i18n.t("Any message nothing else answers")), ("regex", i18n.t("A message that matches a pattern")),
            ("ad", i18n.t("A click on a click-to-WhatsApp ad")), ("button", i18n.t("A template button is pressed"))]


class TriggerDialog(PrismDialog):
    """What starts the flow."""

    def __init__(self, trigger: dict, parent=None):
        super().__init__(i18n.t("What starts this flow"), i18n.t("When a customer's message fits this, the flow begins."), icon="play", parent=parent)
        trigger = trigger or {}
        self.kind = QComboBox()
        self.kind.setMinimumHeight(38)
        for k, label in trigger_types():
            self.kind.addItem(label, k)
        self.kind.setCurrentIndex(max(self.kind.findData(trigger.get("type") or "keyword"), 0))
        self.body.addWidget(ui.field(i18n.t("It starts when"), self.kind))
        self.keywords = QLineEdit(", ".join(trigger.get("keywords") or []))
        self.keywords.setPlaceholderText(i18n.t("price, rate, quote"))
        self.keywords.setMinimumHeight(38)
        self.match = QComboBox()
        self.match.setMinimumHeight(38)
        for k, label in (("contains", i18n.t("the message contains one of them")), ("exact", i18n.t("the message is exactly one of them")),
                         ("starts_with", i18n.t("the message starts with one of them"))):
            self.match.addItem(label, k)
        self.match.setCurrentIndex(max(self.match.findData(trigger.get("match") or "contains"), 0))
        self.kw_box = QWidget()
        kl = QVBoxLayout(self.kw_box)
        kl.setContentsMargins(0, 0, 0, 0)
        kl.setSpacing(theme.SPACE_2)
        kl.addWidget(ui.field(i18n.t("Keywords"), self.keywords, i18n.t("Separate them with commas. Capital letters don't matter.")))
        kl.addWidget(ui.field(i18n.t("Match when"), self.match))
        self.body.addWidget(self.kw_box)
        self.pattern = QLineEdit(trigger.get("pattern") or "")
        self.pattern.setPlaceholderText(r"^\d{6}$")
        self.pattern.setMinimumHeight(38)
        self.pattern_box = ui.field(i18n.t("Pattern"), self.pattern, i18n.t("A regular expression, up to 100 characters."))
        self.body.addWidget(self.pattern_box)
        self.ads = QLineEdit(", ".join(trigger.get("ad_ids") or []))
        self.ads.setMinimumHeight(38)
        self.ads_box = ui.field(i18n.t("Ad ids"), self.ads, i18n.t("The ids of the ads, separated by commas. Several ads can start one flow."))
        self.body.addWidget(self.ads_box)
        self.payload = QLineEdit(trigger.get("payload") or "")
        self.payload.setMinimumHeight(38)
        self.payload_box = ui.field(i18n.t("Button payload"), self.payload, i18n.t("The payload you gave the template's button."))
        self.body.addWidget(self.payload_box)
        self.kind.activated.connect(lambda _i: self._show())
        self.keywords.textChanged.connect(lambda _t: self._show())
        self.link_btn = C.button(i18n.t("Get a link and QR code for this word"), "tertiary", "link", on_click=self._link)
        link_row = QHBoxLayout()
        link_row.addWidget(self.link_btn)
        link_row.addStretch(1)
        self.link_box = QWidget()
        self.link_box.setLayout(link_row)
        self.body.addWidget(self.link_box)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Use this"), "primary", on_click=self.accept))
        self.resize(520, 560)
        self._show()

    def _words(self) -> list:
        return [x.strip() for x in self.keywords.text().split(",") if x.strip()]

    def _link(self):
        FlowLinkDialog(self._words(), self).exec()

    def _show(self):
        k = self.kind.currentData()
        self.kw_box.setVisible(k == "keyword")
        self.pattern_box.setVisible(k == "regex")
        self.ads_box.setVisible(k == "ad")
        self.payload_box.setVisible(k == "button")
        self.link_box.setVisible(k == "keyword" and bool(self._words()))

    def value(self) -> dict:
        k = self.kind.currentData()
        split = lambda s: [x.strip() for x in s.split(",") if x.strip()]                         # noqa: E731
        if k == "keyword":
            return {"type": k, "match": self.match.currentData(), "keywords": split(self.keywords.text())}
        if k == "regex":
            return {"type": k, "pattern": self.pattern.text().strip()}
        if k == "ad":
            return {"type": k, "ad_ids": split(self.ads.text())}
        if k == "button":
            return {"type": k, "payload": self.payload.text().strip()}
        return {"type": k}


class LibraryDialog(PrismDialog):
    """Start from a ready-made flow: choose a topic, or search, and pick one."""

    def __init__(self, library: list, parent=None):
        super().__init__(i18n.t("Start from a ready-made flow"), i18n.t("Pick one and change the words to your own."), icon="list", parent=parent)
        self.key = None
        self.library = list(library or [])
        topics = sorted({i.get("topic") or "General" for i in self.library})
        self._topic, self._query = "", ""
        self.chips = C.FilterChips([("", i18n.t("All"))] + [(t, t) for t in topics], "")
        self.chips.setMinimumWidth(520)
        self.chips.changed.connect(self._set_topic)
        self.body.addWidget(self.chips)
        self.search = QLineEdit()
        self.search.setPlaceholderText(i18n.t("Search the ready-made flows"))
        self.search.setMinimumHeight(36)
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._set_query)
        self.body.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        self.items_col = QVBoxLayout(host)
        self.items_col.setSpacing(theme.SPACE_2)
        self.items_col.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(host)
        self.body.addWidget(scroll, 1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.resize(620, 700)
        self._render()

    def shown(self) -> list:
        q = self._query.strip().lower()
        return [i for i in self.library if (not self._topic or (i.get("topic") or "General") == self._topic)
                and (not q or q in (i.get("title", "") + " " + i.get("description", "")).lower())]

    def _set_topic(self, topic: str):
        self._topic = topic
        self._render()

    def _set_query(self, text: str):
        self._query = text
        self._render()

    def _render(self):
        ui.clear(self.items_col)
        items = self.shown()
        if not items:
            self.items_col.addWidget(C.label(i18n.t("Nothing matches. Try another topic or word."), level="SUPPORT", colour=theme.NEUTRAL[600]))
        for item in items:
            card = QFrame()
            card.setObjectName("waLib")
            card.setAttribute(Qt.WA_StyledBackground, True)
            card.setStyleSheet(f"#waLib {{ background: rgba(255,255,255,0.6); border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
            col = QVBoxLayout(card)
            col.setContentsMargins(14, 12, 14, 12)
            head = QHBoxLayout()
            head.addWidget(C.label(item.get("title", ""), level="SUPPORT", weight=700), 1)
            head.addWidget(C.Pill(item.get("topic") or "General", "neutral"))
            col.addLayout(head)
            col.addWidget(C.label(item.get("description", ""), level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True))
            col.addWidget(C.label(M.trigger_words(item.get("trigger")), level="META", colour=theme.NEUTRAL[600], wrap=True))
            row = QHBoxLayout()
            if item.get("needs_files"):
                tag = C.Pill(i18n.t("You add your own files"), "warn")
                tag.setToolTip(i18n.t("It sends a file. Choose one from your Media Library after you pick it — it cannot be published until you do."))
                row.addWidget(tag)
            if item.get("needs_edit"):
                tag = C.Pill(i18n.t("Change the details"), "warn")
                tag.setToolTip(i18n.t("It has an example address or place in it. Replace it with yours before you publish."))
                row.addWidget(tag)
            row.addStretch(1)
            row.addWidget(C.button(i18n.t("Use this one"), "secondary", on_click=lambda _=False, k=item["key"]: self._pick(k)))
            col.addLayout(row)
            self.items_col.addWidget(card)
        self.items_col.addStretch(1)

    def _pick(self, key: str):
        self.key = key
        self.accept()


class VersionsDialog(PrismDialog):
    def __init__(self, flow_id: str, current: int, parent=None):
        super().__init__(i18n.t("Earlier versions"), i18n.t("Bring one back and it becomes the live version. Customers already in the flow finish the version they started."),
                         icon="clock", parent=parent, scrollable=True)
        self.flow_id, self.choice = flow_id, None
        self.rows = QVBoxLayout()
        self.body.addLayout(self.rows)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.rows.addWidget(C.label(i18n.t("Loading…"), level="SUPPORT", colour=theme.NEUTRAL[600]))
        self.current = current
        self.resize(480, 480)
        ui.call(self, "flows/versions", {"flow_id": flow_id}, done=self._loaded, failed=lambda m, _d: self._text(m))

    def _text(self, text: str):
        ui.clear(self.rows)
        self.rows.addWidget(C.label(text, level="SUPPORT", colour=theme.ERR_INK, wrap=True))

    def _loaded(self, reply: dict):
        ui.clear(self.rows)
        versions = reply.get("versions") or []
        if not versions:
            self.rows.addWidget(C.label(i18n.t("It has never been published."), level="SUPPORT", colour=theme.NEUTRAL[600]))
        for v in versions:
            row = QHBoxLayout()
            live = v["version"] == self.current
            row.addWidget(C.label(i18n.t("Version {n}").format(n=v["version"]), level="SUPPORT", weight=700))
            row.addWidget(C.label(short_time(v.get("published_at") or ""), level="META", colour=theme.NEUTRAL[600]), stretch=1)
            if live:
                row.addWidget(C.Pill(i18n.t("Live"), "ok"))
            else:
                row.addWidget(C.button(i18n.t("Bring it back"), "secondary", on_click=lambda _=False, n=v["version"]: self._pick(n)))
            box = QWidget()
            box.setLayout(row)
            self.rows.addWidget(box)

    def _pick(self, version: int):
        self.choice = version
        self.accept()


class TryIt(QWidget):
    """Walk the flow as a pretend customer. Nothing is sent and nothing is saved."""

    def __init__(self, editor: "FlowEditor", parent=None):
        super().__init__(parent)
        self.editor = editor
        self.inputs: list = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("Try it"), level="CARD_TITLE"), stretch=1)
        self.pretend_btn = C.button(i18n.t("Pretend…"), "tertiary", on_click=self._toggle_pretend)
        top.addWidget(self.pretend_btn)
        top.addWidget(C.button(i18n.t("Start again"), "tertiary", on_click=self.reset))
        col.addLayout(top)
        col.addWidget(C.label(i18n.t("Write as a customer would. Nothing is sent."), level="META", colour=theme.NEUTRAL[600]))
        self.pretend = QFrame()
        self.pretend.setObjectName("waPretend")
        self.pretend.setAttribute(Qt.WA_StyledBackground, True)
        self.pretend.setStyleSheet(f"#waPretend {{ background: rgba(255,255,255,0.55); border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        pl = QVBoxLayout(self.pretend)
        pl.setContentsMargins(10, 8, 10, 8)
        pl.setSpacing(theme.SPACE_1)
        row = QHBoxLayout()
        self.use_clock = QCheckBox(i18n.t("Pretend it is"))
        self.use_clock.setToolTip(i18n.t("Try a flow that answers differently by the day, the date or the time — without waiting for that day."))
        self.clock = QDateTimeEdit(QDateTime.currentDateTime())
        self.clock.setCalendarPopup(True)
        self.clock.setDisplayFormat("ddd d MMM yyyy  HH:mm")
        self.clock.setMinimumHeight(32)
        self.clock.setAccessibleName(i18n.t("Pretend date and time"))
        self.clock.setEnabled(False)
        self.use_clock.toggled.connect(self.clock.setEnabled)
        row.addWidget(self.use_clock)
        row.addWidget(self.clock, 1)
        pl.addLayout(row)
        self.open_now = QCheckBox(i18n.t("Pretend you are open"))
        self.open_now.setChecked(True)
        self.open_now.setToolTip(i18n.t("What a “Whether you are open” condition sees. Your real hours are set in Settings."))
        pl.addWidget(self.open_now)
        self.holiday_note = C.label("", level="META", colour=theme.NEUTRAL[600], wrap=True)
        pl.addWidget(self.holiday_note)
        self.pretend.setVisible(False)
        col.addWidget(self.pretend)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        self.chat = QVBoxLayout(host)
        self.chat.setSpacing(theme.SPACE_1)
        self.chat.setContentsMargins(0, 0, 4, 0)
        self.scroll.setWidget(host)
        col.addWidget(self.scroll, 1)
        self.note = ui.note()
        col.addWidget(self.note)
        row = QHBoxLayout()
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(i18n.t("Type a message"))
        self.edit.setMinimumHeight(36)
        self.edit.returnPressed.connect(self._send)
        row.addWidget(self.edit, 1)
        row.addWidget(C.button(i18n.t("Send"), "secondary", on_click=self._send))
        col.addLayout(row)
        self.reset()

    def _toggle_pretend(self):
        on = not self.pretend.isVisible()
        self.pretend.setVisible(on)
        if on:
            n = len(self.editor.owner.holidays)
            self.holiday_note.setText(i18n.t("{n} holidays are set in Settings, Team and inbox.").format(n=n) if n else
                                      i18n.t("No holidays are set. Add them in Settings, Team and inbox, and a “Whether today is a holiday” condition can use them."))

    def options(self) -> dict:
        """What the pretend panel changes in the request: the clock (when switched on), whether you are open, and the holidays."""
        out = {"open_now": self.open_now.isChecked(), "holidays": [h.get("date") if isinstance(h, dict) else h for h in self.editor.owner.holidays]}
        if self.use_clock.isChecked():
            out["local"] = self.clock.dateTime().toString("yyyy-MM-ddTHH:mm:ss")
        return out

    def reset(self):
        self.inputs = []
        ui.clear(self.chat)
        self.chat.addStretch(1)
        self.note.clear_note()
        self.edit.setPlaceholderText(i18n.t("Type the first message a customer would send"))

    def _bubble(self, who: str, text: str):
        lab = C.label(text, level="SUPPORT", wrap=True, colour=theme.TEXT if who == "bot" else "#ffffff")
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lab.setMaximumWidth(280)
        bg = {"bot": theme.NEUTRAL[100], "customer": theme.ACCENT, "system": "transparent", "clock": "transparent"}.get(who, theme.NEUTRAL[100])
        if who in ("system", "clock"):
            lab.setStyleSheet("color: %s; font-size: 12px; font-style: italic;" % theme.NEUTRAL[500])
        else:
            lab.setStyleSheet(lab.styleSheet() + f" background: {bg}; border-radius: 12px; padding: 8px 12px;")
        row = QHBoxLayout()
        if who == "customer":
            row.addStretch(1)
        row.addWidget(lab)
        if who != "customer":
            row.addStretch(1)
        box = QWidget()
        box.setLayout(row)
        self.chat.insertWidget(self.chat.count() - 1, box)

    def _chips(self, titles: list):
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_1)
        for t in titles:
            row.addWidget(C.button(t, "secondary", small=True, on_click=lambda _=False, x=t: self._send(x)))
        row.addStretch(1)
        box = QWidget()
        box.setLayout(row)
        self.chat.insertWidget(self.chat.count() - 1, box)

    def _send(self, text=None):
        text = text if isinstance(text, str) else self.edit.text().strip()
        if not text:
            return
        self.edit.clear()
        self.inputs.append(text)
        self.run()

    def run(self):
        ui.call(self, "flows/test", {"graph": M.clean_for_save(self.editor.graph), "trigger": self.editor.trigger, "inputs": self.inputs,
                                     "name": i18n.t("Asha Patel"), **self.options()}, done=self._show, failed=lambda m, _d: self.note.error(m))

    def share_location(self):
        """The customer shares a map pin (a sample one) — what a "Ask for their location" step waits for."""
        self.inputs.append({"text": "", "location": {"latitude": 22.3072, "longitude": 73.1812, "name": i18n.t("Alkapuri, Vadodara"), "address": ""}})
        self.run()

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "quiet")

    def _show(self, reply: dict):
        ui.clear(self.chat)
        self.chat.addStretch(1)
        if reply.get("state") == "invalid":
            self.note.error(i18n.t("Fix the problems listed first, then try again."))
            self.editor.show_issues(reply.get("issues") or [])
            return
        self.note.clear_note()
        for item in reply.get("transcript") or []:
            who, kind = item.get("from"), item.get("kind")
            if who == "customer" and not item.get("text"):
                self._bubble("customer", i18n.t("Shared a location"))
            elif kind == "media":
                self._bubble("bot", i18n.t("[{kind}] {words}").format(kind=M.media_kind_name(item.get("media")), words=item.get("text") or ""))
            elif kind == "location":
                self._bubble("bot", i18n.t("Map pin: {name} {address} ({lat}, {lng})").format(name=item.get("name") or "", address=item.get("address") or "",
                                                                                              lat=item.get("latitude"), lng=item.get("longitude")))
            elif kind == "location_request":
                self._bubble("bot", item.get("text", ""))
                row = QHBoxLayout()
                row.addWidget(C.button(i18n.t("Share a location"), "secondary", small=True, on_click=self.share_location))
                row.addStretch(1)
                box = QWidget()
                box.setLayout(row)
                self.chat.insertWidget(self.chat.count() - 1, box)
            elif kind == "buttons":
                self._bubble("bot", item.get("text", ""))
                self._chips([o["title"] for o in item.get("options") or []])
            elif kind == "list":
                self._bubble("bot", item.get("text", ""))
                self._chips([r["title"] for r in item.get("rows") or []])
            elif kind == "template":
                self._bubble("bot", i18n.t("[template {n}]").format(n=item.get("name")))
            else:
                self._bubble(who, item.get("text", ""))
        if reply.get("error"):
            self.note.error(i18n.t("The flow stopped: {e}").format(e=reply["error"]))
        elif reply.get("state") == "done":
            self.note.set(i18n.t("The flow has finished."), "quiet")
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(self.scroll.verticalScrollBar().maximum()))


class _Context:
    """What the step cards ask the editor about the rest of the flow and the workspace."""

    def __init__(self, editor: "FlowEditor"):
        self.editor = editor

    def labels(self) -> dict:
        nodes = self.editor.graph.get("nodes") or {}
        return {nid: M.describe_step(nodes[nid]) for nid in M.order_of(self.editor.graph)}

    def entry(self):
        return self.editor.graph.get("entry")

    def templates(self):
        return self.editor.owner.templates

    def agents(self):
        return self.editor.owner.agents

    def forms(self):
        return self.editor.owner.forms

    def products(self):
        return self.editor.owner.products

    def flows(self):
        return [f for f in self.editor.owner.flows if f.get("id") != self.editor.flow.get("id")]


class FlowEditor(QWidget):
    """One flow: its name, what starts it, its steps, the checks beside them, and a way to try it."""
    deleted = Signal()
    changed = Signal()

    def __init__(self, owner: "FlowsSection", flow: dict, parent=None):
        super().__init__(parent)
        self.owner, self.flow = owner, flow
        self.graph = copy.deepcopy(flow.get("graph") or {})
        self.graph.setdefault("nodes", {})
        self.trigger = copy.deepcopy(flow.get("trigger") or {})
        self.version = int(flow.get("version") or 0)
        self.enabled = bool(flow.get("enabled"))
        self.cards: dict = {}
        self.issues: list = []
        self._saving = False
        self._again = False
        self._ctx = _Context(self)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SAVE_MS)
        self._timer.timeout.connect(self.save)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.name = QLineEdit(flow.get("name") or "")
        self.name.setMinimumHeight(38)
        self.name.setAccessibleName(i18n.t("Flow name"))
        self.name.textChanged.connect(lambda _t: self._edited())
        head.addWidget(self.name, 1)
        self.status = C.Pill("", "quiet")
        head.addWidget(self.status)
        head.addWidget(C.label(i18n.t("On"), level="META", colour=theme.NEUTRAL[600]))
        self.switch = C.ToggleSwitch()
        self.switch.setChecked(self.enabled)
        self.switch.toggled.connect(self._toggle)
        head.addWidget(self.switch)
        self.versions_btn = C.button(i18n.t("Versions"), "tertiary", on_click=self._versions)
        head.addWidget(self.versions_btn)
        head.addWidget(C.icon_button("trash", i18n.t("Delete this flow"), on_click=self._delete, colour=theme.ERR_INK))
        self.publish_btn = C.button(i18n.t("Publish"), "primary", on_click=self.publish)
        head.addWidget(self.publish_btn)
        root.addLayout(head)

        trig = QHBoxLayout()
        self.trigger_btn = C.button("", "secondary", on_click=self._trigger)
        trig.addWidget(C.label(i18n.t("Starts when"), level="SUPPORT", colour=theme.NEUTRAL[600]))
        trig.addWidget(self.trigger_btn)
        trig.addStretch(1)
        self.saved = C.label("", level="META", colour=theme.NEUTRAL[500])
        trig.addWidget(self.saved)
        self.mode = C.Tabs([i18n.t("Steps"), i18n.t("Canvas")], 0)
        self.mode.changed.connect(self._mode_changed)
        trig.addWidget(self.mode)
        root.addLayout(trig)
        self.note = ui.note()
        root.addWidget(self.note)

        split = QHBoxLayout()
        split.setSpacing(theme.SPACE_4)
        root.addLayout(split, 1)
        left = QVBoxLayout()
        left.setSpacing(theme.SPACE_2)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        self.steps_col = QVBoxLayout(host)
        self.steps_col.setSpacing(theme.SPACE_2)
        self.steps_col.setContentsMargins(0, 0, theme.SPACE_2, 0)
        self.scroll.setWidget(host)
        left.addWidget(self.scroll, 1)
        self.add_btn = C.button(i18n.t("Add a step"), "secondary", icon_name="plus", on_click=self._add_menu)
        add = QHBoxLayout()
        add.addWidget(self.add_btn)
        add.addStretch(1)
        left.addLayout(add)
        self.canvas = None
        self.canvas_card = None
        self.steps_page = QWidget()
        self.steps_page.setLayout(left)
        self.canvas_page = QWidget()
        self._build_canvas_page()
        self.left_stack = QStackedWidget()
        self.left_stack.addWidget(self.steps_page)
        self.left_stack.addWidget(self.canvas_page)
        split.addWidget(self.left_stack, 5)

        right = QVBoxLayout()
        right.setSpacing(theme.SPACE_3)
        self.problems = QVBoxLayout()
        self.problems.setSpacing(2)
        right.addLayout(self.problems)
        self.view = C.Tabs([i18n.t("Try it"), i18n.t("Results")], 0)
        self.view.changed.connect(self._view_changed)
        right.addWidget(self.view, 0, Qt.AlignLeft)
        self.console = TryIt(self)
        self.console.setMinimumWidth(320)
        self.results = FlowResults(flow.get("id", ""))
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.console)
        self.right_stack.addWidget(self.results)
        right.addWidget(self.right_stack, 1)
        side = QWidget()
        side.setLayout(right)
        side.setMinimumWidth(320)
        side.setMaximumWidth(400)
        split.addWidget(side, 3)

        self.render()
        self._status()
        self.show_issues(flow.get("issues") or [])

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    # ── showing ──────────────────────────────────────────────────────────────
    def _status(self):
        if self.version < 1:
            self.status.setText(i18n.t("Draft"))
            self.status.set_tone("quiet")
        elif self.enabled:
            self.status.setText(i18n.t("Live · v{n}").format(n=self.version))
            self.status.set_tone("ok")
        else:
            self.status.setText(i18n.t("Off · v{n}").format(n=self.version))
            self.status.set_tone("warn")
        self.trigger_btn.setText(M.trigger_words(self.trigger))

    def render(self):
        ui.clear(self.steps_col)
        self.cards = {}
        order = M.order_of(self.graph)
        if not order:
            self.steps_col.addWidget(C.label(i18n.t("No steps yet. Add the first thing the bot should do."), level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        for nid in order:
            card = StepCard(nid, self.graph["nodes"][nid], self._ctx)
            card.changed.connect(self._edited)
            card.shape.connect(self._reshape)
            card.renamed.connect(self._rename)
            card.removed.connect(self._remove)
            card.moved.connect(self._move)
            card.make_entry.connect(self._entry)
            self.cards[nid] = card
            self.steps_col.addWidget(card)
        self.steps_col.addStretch(1)
        self._paint_issues()

    def _reshape(self):
        for card in self.cards.values():
            card.refresh_targets()
        if self.canvas_shown():
            self.canvas.refresh()

    def show_issues(self, issues: list):
        self.issues = list(issues or [])
        ui.clear(self.problems)
        errors = [i for i in self.issues if i.get("severity") == "error"]
        warns = [i for i in self.issues if i.get("severity") != "error"]
        if self.graph.get("nodes") or self.trigger:
            if errors:
                self.problems.addWidget(C.label(i18n.t("{n} problems to fix before publishing").format(n=len(errors)), level="SUPPORT", weight=700, colour=theme.ERR_INK))
            elif warns:
                self.problems.addWidget(C.label(i18n.t("Ready to publish — with {n} things to look at").format(n=len(warns)), level="SUPPORT", weight=700, colour=theme.WARN_INK))
            else:
                self.problems.addWidget(C.label(i18n.t("No problems found"), level="SUPPORT", weight=700, colour=theme.OK_INK))
        for i in (errors + warns)[:8]:
            self.problems.addWidget(C.label("•  " + str(i.get("message", "")), level="META", wrap=True,
                                            colour=theme.ERR_INK if i.get("severity") == "error" else theme.WARN_INK))
        self._paint_issues()

    def _paint_issues(self):
        by = M.issues_by_node(self.issues)
        for nid, card in self.cards.items():
            card.set_issues(by.get(nid, []))
        if self.canvas is not None:
            self.canvas.set_issues(self.issues)

    # ── editing ──────────────────────────────────────────────────────────────
    def _edited(self):
        self.saved.setText(i18n.t("Unsaved changes…"))
        self._timer.start()
        if self.canvas_shown():
            for nid in list(self.cards):
                self.canvas.touch(nid)

    def _rename(self, old: str, new: str):
        try:
            M.rename_node(self.graph, old, new)
        except ValueError:
            self.render()
            return
        self.cards[new] = self.cards.pop(old)
        if self.canvas_shown():
            self.canvas.reload()
            self.canvas.set_issues(self.issues)
        self._reshape()
        self._edited()

    def _remove(self, nid: str):
        if ui.confirm(self, i18n.t("Delete step"), i18n.t("Delete the step “{n}”? Steps that led to it will end the flow instead.").format(n=nid)):
            M.remove_node(self.graph, nid)
            self._redraw()
            self._edited()

    def _move(self, nid: str, delta: int):
        M.move_node(self.graph, nid, delta)
        self.render()
        self._edited()

    def _redraw(self):
        """Show the steps again after one was added or removed, in whichever view is open."""
        if self.canvas_shown():
            self.canvas.reload()
            self.canvas.set_issues(self.issues)
            self.cards = {}
            self._open_card(self.canvas.current())
        else:
            self.render()

    def _entry(self, nid: str):
        self.graph["entry"] = nid
        self._reshape()
        self._edited()

    def _view_changed(self, index: int):
        self.right_stack.setCurrentIndex(index)
        if index == 1:
            self.results.load()

    def add_menu(self) -> QMenu:
        """The Add step menu: the twenty kinds of step in six groups, each with a line saying what it does."""
        menu = QMenu(self)
        names = {k: (n, h) for k, n, h in M.step_types()}
        for group, kinds in M.step_groups():
            sub = menu.addMenu(group)
            sub.setToolTipsVisible(True)
            for kind in kinds:
                act = sub.addAction(names[kind][0])
                act.setToolTip(names[kind][1])
                act.triggered.connect(lambda _=False, k=kind: self.add_step(k))
        return menu

    def _add_menu(self):
        self.add_menu().exec(self.add_btn.mapToGlobal(self.add_btn.rect().bottomLeft()))

    def add_step(self, kind: str):
        last = (M.order_of(self.graph) or [None])[-1]
        if self.canvas_shown():
            nid = M.add_node(self.graph, kind, after=self.canvas.current() or last)
            self._redraw()
            self.canvas.select(nid)
            self._edited()
            return
        nid = M.add_node(self.graph, kind, after=last)
        self.render()
        card = self.cards.get(nid)
        if card is not None:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(card))
        self._edited()

    def _trigger(self):
        dlg = TriggerDialog(self.trigger, self)
        if dlg.exec():
            self.trigger = dlg.value()
            self._status()
            self._edited()

    # ── the canvas ───────────────────────────────────────────────────────────
    def _build_canvas_page(self):
        col = QVBoxLayout(self.canvas_page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_1)
        self.canvas_add_btn = C.button(i18n.t("Add a step"), "secondary", icon_name="plus", on_click=lambda: self.add_menu().exec(
            self.canvas_add_btn.mapToGlobal(self.canvas_add_btn.rect().bottomLeft())))
        bar.addWidget(self.canvas_add_btn)
        self.zoom_out_btn = C.button(i18n.t("Smaller"), "tertiary", small=True, on_click=lambda: self.canvas and self.canvas.zoom(1 / 1.2))
        self.zoom_in_btn = C.button(i18n.t("Bigger"), "tertiary", small=True, on_click=lambda: self.canvas and self.canvas.zoom(1.2))
        self.fit_btn = C.button(i18n.t("Fit all"), "tertiary", small=True, on_click=lambda: self.canvas and self.canvas.fit())
        self.arrange_btn = C.button(i18n.t("Tidy up"), "tertiary", small=True, on_click=lambda: self.canvas and self.canvas.arrange())
        for b in (self.zoom_out_btn, self.zoom_in_btn, self.fit_btn, self.arrange_btn):
            bar.addWidget(b)
        bar.addStretch(1)
        col.addLayout(bar)
        col.addWidget(C.label(i18n.t("Drag a card to move it. Drag from a dot on its right edge to another card to join them; right-click a dot to cut the line."),
                              level="META", colour=theme.NEUTRAL[600], wrap=True))
        self.canvas_split = QSplitter(Qt.Vertical)
        self.canvas_split.setChildrenCollapsible(False)
        self.canvas_host = QVBoxLayout()
        holder = QWidget()
        holder.setLayout(self.canvas_host)
        self.canvas_split.addWidget(holder)
        self.card_scroll = QScrollArea()
        self.card_scroll.setWidgetResizable(True)
        self.card_scroll.setFrameShape(QFrame.NoFrame)
        self.card_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.card_scroll.viewport().setAutoFillBackground(False)
        card_host = QWidget()
        ui.see_through(card_host)
        self.card_col = QVBoxLayout(card_host)
        self.card_col.setContentsMargins(0, 0, theme.SPACE_2, 0)
        self.card_scroll.setWidget(card_host)
        self.canvas_split.addWidget(self.card_scroll)
        self.canvas_split.setStretchFactor(0, 3)
        self.canvas_split.setStretchFactor(1, 2)
        col.addWidget(self.canvas_split, 1)

    def canvas_shown(self) -> bool:
        return self.canvas is not None and self.left_stack.currentIndex() == 1

    def _mode_changed(self, index: int):
        if index == 1:
            if self.canvas is None:
                self.canvas = FlowCanvas(self.graph)
                self.canvas.selected.connect(self._open_card)
                self.canvas.edited.connect(self._canvas_edited)
                self.canvas_host.addWidget(self.canvas)
            self.left_stack.setCurrentIndex(1)
            self.canvas.reload()
            self.canvas.set_issues(self.issues)
            self.cards = {}
            self._open_card("")
            QTimer.singleShot(0, self.canvas.fit)
        else:
            self.left_stack.setCurrentIndex(0)
            self.render()

    def _canvas_edited(self):
        """A card was moved or two were joined or cut."""
        self._reshape()
        self._edited()
        for nid in list(self.cards):                                     # the open card's "Then" choices follow the line that was drawn
            self.cards[nid].refresh_targets()

    def _open_card(self, nid: str):
        """Show one step's card under the picture, so what it says can be changed there."""
        ui.clear(self.card_col)
        self.cards = {}
        node = (self.graph.get("nodes") or {}).get(nid)
        if node is None:
            self.card_col.addWidget(C.label(i18n.t("Click a step in the picture to change what it says."), level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
            self.card_col.addStretch(1)
            return
        card = StepCard(nid, node, self._ctx)
        card.changed.connect(self._edited)
        card.shape.connect(self._reshape)
        card.renamed.connect(self._rename)
        card.removed.connect(self._remove)
        card.make_entry.connect(self._entry)
        for b in card.findChildren(QWidget):
            if b.toolTip() in (i18n.t("Move up"), i18n.t("Move down")):          # the picture has no order to move a step within
                b.setVisible(False)
        self.cards[nid] = card
        card.set_issues(M.issues_by_node(self.issues).get(nid, []))
        self.card_col.addWidget(card)
        self.card_col.addStretch(1)

    # ── saving ───────────────────────────────────────────────────────────────
    def payload(self) -> dict:
        graph = M.clean_for_save(self.graph)
        graph["order"] = M.order_of(self.graph)
        return {"flow_id": self.flow["id"], "name": self.name.text().strip() or self.flow.get("name"), "trigger": self.trigger, "graph": graph}

    def save(self, then=None):
        if self._saving:
            self._again = True
            return
        self._timer.stop()
        self._saving = True
        ui.call(self, "flows/update", self.payload(), done=lambda r, t=then: self._saved(r, t), failed=lambda m, _d, t=then: self._save_failed(m))

    def _save_failed(self, message: str):
        self._saving = False
        self.saved.setText(i18n.t("Not saved"))
        self.say(message, error=True)

    def _saved(self, reply: dict, then=None):
        self._saving = False
        self.saved.setText(i18n.t("Saved"))
        self.flow["name"] = self.name.text().strip() or self.flow.get("name")
        self.owner.name_changed(self.flow["id"], self.flow["name"])
        self.show_issues(reply.get("issues") or [])
        if self._again:
            self._again = False
            self.save(then)
            return
        if then:
            then()

    def publish(self):
        def go():
            ui.call(self, "flows/publish", {"flow_id": self.flow["id"]}, done=self._published, failed=self._publish_failed)
        self.publish_btn.setEnabled(False)
        self.save(then=go)

    def _publish_failed(self, message: str, detail: dict):
        self.publish_btn.setEnabled(True)
        if detail.get("issues"):
            self.show_issues(detail["issues"])
        self.say(message, error=True)

    def _published(self, reply: dict):
        self.publish_btn.setEnabled(True)
        self.version = int(reply.get("version") or self.version + 1)
        self.flow["version"] = self.version
        self.say(i18n.t("Published as version {n}.").format(n=self.version) + ("" if self.enabled else " " + i18n.t("Switch it on to start answering customers.")))
        self._status()
        self.owner.refresh_list()

    def _toggle(self, on: bool):
        def revert(message: str):
            self.switch.blockSignals(True)
            self.switch.setChecked(self.enabled)
            self.switch.blockSignals(False)
            self.say(message, error=True)
        ui.call(self, "flows/set_enabled", {"flow_id": self.flow["id"], "enabled": on},
                done=lambda r: (setattr(self, "enabled", on), self._status(), self.say(i18n.t("The flow is on.") if on else i18n.t("The flow is off.")), self.owner.refresh_list()),
                failed=lambda m, _d: revert(m))

    def _versions(self):
        dlg = VersionsDialog(self.flow["id"], self.version, self)
        if dlg.exec() and dlg.choice:
            ui.call(self, "flows/rollback", {"flow_id": self.flow["id"], "version": dlg.choice},
                    done=lambda r: (self.say(i18n.t("Version {n} is live again.").format(n=dlg.choice)), self.owner.open_flow(self.flow["id"])))

    def _delete(self):
        if ui.confirm(self, i18n.t("Delete flow"), i18n.t("Delete “{n}” and everything in it? People in the middle of it stop. This can't be undone.").format(n=self.flow.get("name"))):
            ui.call(self, "flows/delete", {"flow_id": self.flow["id"]}, done=lambda r: self.deleted.emit())


class FlowsSection(QWidget):
    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self.templates: list = []
        self.agents: list = []
        self.forms: list = []                  # published forms a "Send a form" step can offer
        self.products: list = []               # the catalogue, for a "Show products" step
        self.flows: list = []
        self.holidays: list = []
        self.editor = None
        self._selected = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_4)
        left = QVBoxLayout()
        left.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("Your flows"), level="CARD_TITLE"), stretch=1)
        self.new_btn = C.button(i18n.t("New flow"), "primary", icon_name="plus", on_click=self._new_menu)
        top.addWidget(self.new_btn)
        left.addLayout(top)
        self.note = ui.note()
        left.addWidget(self.note)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        self.list_col = QVBoxLayout(host)
        self.list_col.setSpacing(theme.SPACE_2)
        self.list_col.setContentsMargins(0, 0, theme.SPACE_2, 0)
        scroll.setWidget(host)
        left.addWidget(scroll, 1)
        holder = QWidget()
        holder.setLayout(left)
        holder.setFixedWidth(300)
        root.addWidget(holder)

        self.stack = QStackedWidget()
        self.state = C.EmptyState("play", i18n.t("Loading…"), "", i18n.t("Try again"))
        self.state.clicked.connect(self._state_action)
        self.stack.addWidget(self.state)
        self.editor_holder = QWidget()
        self.editor_lay = QVBoxLayout(self.editor_holder)
        self.editor_lay.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.editor_holder)
        root.addWidget(self.stack, 1)
        self._state_kind = "loading"

    # ── data ─────────────────────────────────────────────────────────────────
    def activate(self):
        ui.call(self, "templates/list", done=lambda r: setattr(self, "templates", [t for t in r.get("templates") or [] if str(t.get("status")).upper() == "APPROVED"]),
                failed=lambda m, _d: None)
        ui.call(self, "ai/agents/list", done=lambda r: setattr(self, "agents", [a for a in r.get("agents") or []]), failed=lambda m, _d: None)
        ui.call(self, "forms/list", done=lambda r: setattr(self, "forms", [f for f in r.get("forms") or [] if f.get("status") == "published"]), failed=lambda m, _d: None)
        ui.call(self, "catalog/list", done=lambda r: setattr(self, "products", list(r.get("products") or [])), failed=lambda m, _d: None)
        ui.call(self, "inbox/settings/get", done=lambda r: setattr(self, "holidays", list((r.get("settings") or {}).get("holidays") or [])), failed=lambda m, _d: None)
        self.refresh_list(first=True)

    def deactivate(self):
        pass

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    def refresh_list(self, first: bool = False):
        ui.call(self, "flows/list", done=lambda r: self._listed(r, first), failed=lambda m, _d: self._failed(m))

    def _failed(self, message: str):
        if not self.flows:
            self._show_state("failed", message)
        self.say(message, error=True)

    def _listed(self, reply: dict, first: bool):
        self.flows = list(reply.get("flows") or [])
        self.say("")
        ui.clear(self.list_col)
        for f in self.flows:
            self.list_col.addWidget(self._row(f))
        self.list_col.addStretch(1)
        if self.editor is None and not self.flows:
            self._show_state("none")
        elif self.editor is None and first and self.flows:
            self.open_flow(self.flows[0]["id"])

    def _row(self, f: dict) -> QWidget:
        sel = str(f["id"]) == self._selected
        row = QFrame()
        row.setObjectName("waFlowRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(f"#waFlowRow {{ background: {'rgba(0,0,0,0.05)' if sel else 'rgba(255,255,255,0.55)'}; border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        col = QVBoxLayout(row)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(C.label(f.get("name") or "", level="SUPPORT", weight=700, wrap=True), stretch=1)
        v = int(f.get("version") or 0)
        word, tone = ((i18n.t("Draft"), "quiet") if v < 1 else (i18n.t("Live"), "ok") if f.get("enabled") else (i18n.t("Off"), "warn"))
        top.addWidget(C.Pill(word, tone))
        col.addLayout(top)
        col.addWidget(C.label(M.trigger_words(f.get("trigger")), level="META", colour=theme.NEUTRAL[600], wrap=True))
        if f.get("live"):
            col.addWidget(C.label(i18n.t("{n} customers in it now").format(n=f["live"]), level="META", colour=theme.NEUTRAL[600]))
        row.mousePressEvent = lambda e, fid=f["id"]: self.open_flow(fid)
        return row

    def name_changed(self, flow_id: str, name: str):
        for f in self.flows:
            if f["id"] == flow_id:
                f["name"] = name
        self.refresh_list()

    # ── showing ──────────────────────────────────────────────────────────────
    def _show_state(self, kind: str, message: str = ""):
        title, body, action = {
            "loading": (i18n.t("Loading…"), "", None),
            "failed": (i18n.t("Couldn't load your flows"), message, i18n.t("Try again")),
            "none": (i18n.t("No flows yet"), i18n.t("A flow answers customers by itself. Start from a ready-made one, or build your own."), i18n.t("New flow")),
            "pick": (i18n.t("Choose a flow"), i18n.t("Pick one on the left to change it, or make a new one."), None),
        }[kind]
        self.state.set_text(title, body)
        if self.state.action is not None:
            self.state.action.setText(action or "")
            self.state.action.setVisible(bool(action))
        self._state_kind = kind
        self.stack.setCurrentIndex(0)

    def _state_action(self):
        if self._state_kind == "failed":
            self.activate()
        elif self._state_kind == "none":
            self._new_menu()

    def open_flow(self, flow_id: str):
        self._selected = str(flow_id)
        ui.call(self, "flows/get", {"flow_id": flow_id}, done=self._opened, failed=lambda m, _d: self.say(m, error=True))

    def _opened(self, reply: dict):
        flow = dict(reply.get("flow") or {})
        flow["issues"] = reply.get("issues") or []
        if self.editor is not None:
            self.editor.hide()
            self.editor.setParent(None)
            self.editor.deleteLater()
        self.editor = FlowEditor(self, flow)
        self.editor.deleted.connect(self._deleted)
        self.editor_lay.addWidget(self.editor)
        self.stack.setCurrentIndex(1)
        self.refresh_list()                                          # repaint the list so the open flow stands out

    def _deleted(self):
        self.editor = None
        self._selected = ""
        self.say(i18n.t("Deleted."))
        self.refresh_list()
        self._show_state("pick")

    # ── creating ─────────────────────────────────────────────────────────────
    def _new_menu(self):
        menu = QMenu(self)
        menu.addAction(i18n.t("A blank flow")).triggered.connect(self._blank)
        menu.addAction(i18n.t("From a ready-made flow…")).triggered.connect(self._library)
        menu.addAction(i18n.t("Write it with AI…")).triggered.connect(self._write_with_ai)
        menu.exec(self.new_btn.mapToGlobal(self.new_btn.rect().bottomLeft()))

    def _blank(self):
        ui.call(self, "flows/create", {"name": i18n.t("New flow"), "trigger": {"type": "keyword", "match": "contains", "keywords": ["hello"]},
                                       "graph": {"entry": "welcome", "order": ["welcome"], "nodes": {"welcome": {"type": "send_text", "text": ""}}}},
                done=lambda r: self.open_flow(r["flow_id"]), failed=lambda m, _d: self.say(m, error=True))

    def _library(self):
        ui.call(self, "flows/library", done=self._choose, failed=lambda m, _d: self.say(m, error=True))

    def _write_with_ai(self):
        dlg = AIFlowDialog(parent=self)
        if dlg.exec() and dlg.result:
            ui.call(self, "flows/create", dlg.result, done=lambda r: self.open_flow(r["flow_id"]), failed=lambda m, _d: self.say(m, error=True))

    def _choose(self, reply: dict):
        dlg = LibraryDialog(reply.get("library") or [], self)
        if dlg.exec() and dlg.key:
            ui.call(self, "flows/from_library", {"key": dlg.key}, done=lambda r: self.open_flow(r["flow_id"]), failed=lambda m, _d: self.say(m, error=True))
