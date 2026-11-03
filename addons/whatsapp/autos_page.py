"""Automations → Automatic messages: a message that goes out because of a date, or a short series started by something that happens.

    On a date   a birthday or an anniversary every year, an appointment reminder the day before, a payment reminder a few days before it is due or after it is late —
                a template sent on, before or after a date held in a detail of the contact (a detail of the type Date)
    A drip      a series — hello today, a reminder in 2 days, an offer in 7 — started when someone gets a tag, opts in, or when you add them. It stops for anyone who
                replies, gets a tag you name, or opts out, so nobody is chased after they answered

Only approved templates are ever sent, only to people who have not opted out, and each person gets each message at most once. "Who it would reach" shows what a date
message would do over the next days before it is switched on. Nothing is sent until the message is saved AND switched on.
"""
from __future__ import annotations

import copy
from typing import Optional

from PySide6.QtCore import QTime, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit, QMenu, QScrollArea, QSpinBox, QStackedWidget, QTimeEdit, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import ui
from addons.whatsapp.chat import short_time
from addons.whatsapp.settings_team import ZONES
from addons.whatsapp.template_choice import TemplateChoice
from dialogs.base import PrismDialog
from widgets import controls as C

MAX_STEPS = 10
DEFAULT_TZ = "Asia/Kolkata"


def presets() -> list:
    """(key, kind, name, what it is, starting config) — the ways to begin. The owner still chooses the detail and the template."""
    return [("birthday", "date", i18n.t("Birthday message"), i18n.t("Every year, on the day."), {"match": "yearly", "offset_days": 0, "time": "10:00"}),
            ("anniversary", "date", i18n.t("Anniversary message"), i18n.t("Every year, on the day."), {"match": "yearly", "offset_days": 0, "time": "10:00"}),
            ("appointment", "date", i18n.t("Appointment reminder"), i18n.t("The day before, once."), {"match": "once", "offset_days": -1, "time": "09:00"}),
            ("payment_due", "date", i18n.t("Payment reminder"), i18n.t("Three days before it is due."), {"match": "once", "offset_days": -3, "time": "10:00"}),
            ("payment_late", "date", i18n.t("Payment overdue reminder"), i18n.t("Three days after it was due."), {"match": "once", "offset_days": 3, "time": "10:00"}),
            ("welcome", "drip", i18n.t("Welcome series"), i18n.t("For everyone who gets a tag; three messages over a week."),
             {"trigger": {"type": "tag", "tag": "new-lead"}, "steps": [{"delay_minutes": 0}, {"delay_minutes": 2 * 1440}, {"delay_minutes": 5 * 1440}], "stop": {"on_reply": True, "tags": []}}),
            ("followup", "drip", i18n.t("Follow-up after an enquiry"), i18n.t("You add the people; two messages."),
             {"trigger": {"type": "manual"}, "steps": [{"delay_minutes": 0}, {"delay_minutes": 3 * 1440}], "stop": {"on_reply": True, "tags": []}})]


def kind_words(kind: str) -> str:
    return {"date": i18n.t("On a date"), "drip": i18n.t("Drip")}.get(kind, kind)


def timing_words(cfg: dict) -> str:
    n = int(cfg.get("offset_days") or 0)
    return i18n.t("On the day") if n == 0 else i18n.t("{n} days before").format(n=-n) if n < 0 else i18n.t("{n} days after").format(n=n)


def delay_words(minutes: int) -> str:
    if not minutes:
        return i18n.t("Right away")
    for unit, per in ((i18n.t("days"), 1440), (i18n.t("hours"), 60)):
        if minutes % per == 0:
            return i18n.t("After {n} {u}").format(n=minutes // per, u=unit)
    return i18n.t("After {n} minutes").format(n=minutes)


def summary(a: dict) -> str:
    cfg = a.get("config") or {}
    if a.get("kind") == "date":
        return "%s · %s · %s" % (cfg.get("attribute") or "—", timing_words(cfg), i18n.t("every year") if cfg.get("match") == "yearly" else i18n.t("once"))
    t = (cfg.get("trigger") or {}).get("type")
    start = i18n.t("When someone gets “{t}”").format(t=cfg["trigger"].get("tag")) if t == "tag" else i18n.t("When someone opts in") if t == "opt_in" else i18n.t("People you add")
    return "%s · %s" % (start, i18n.t("{n} messages").format(n=len(cfg.get("steps") or [])))


class NewDetailDialog(PrismDialog):
    """Make a contact detail of the type Date (a birthday, an appointment) that a message can be based on."""

    def __init__(self, parent=None):
        super().__init__(i18n.t("New date detail"), i18n.t("A detail every contact can have, holding a date. You can fill it in on a contact, or import it."), icon="calendar", parent=parent)
        self.name = QLineEdit()
        self.name.setMinimumHeight(38)
        self.name.setMaxLength(40)
        self.name.setPlaceholderText(i18n.t("Birthday"))
        self.name.setAccessibleName(i18n.t("Detail name"))
        self.body.addWidget(ui.field(i18n.t("Name"), self.name, i18n.t("Letters, numbers and underscores; it starts with a letter.")))
        self.error = ui.note()
        self.body.addWidget(self.error)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Add it"), "primary", on_click=self._go))
        self.resize(440, 300)

    def key(self) -> str:
        return self.name.text().strip().replace(" ", "_")

    def _go(self):
        import re
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,39}$", self.key()):
            self.error.error(i18n.t("A name starts with a letter and uses letters, numbers and underscores."))
            return
        self.accept()


class EnrolDialog(PrismDialog):
    """Choose who to add to a drip: a saved segment, or everyone with some tags."""

    def __init__(self, segments: list, parent=None):
        super().__init__(i18n.t("Add people to this drip"), i18n.t("They start at the first message. Anyone already in it, or who has opted out, is left out."), icon="users", parent=parent)
        self.segment = QComboBox()
        self.segment.setMinimumHeight(38)
        self.segment.addItem(i18n.t("Choose a segment"), None)
        for s in segments:
            self.segment.addItem(s.get("name") or "", s.get("id"))
        self.segment.setAccessibleName(i18n.t("Segment"))
        self.body.addWidget(ui.field(i18n.t("A saved segment"), self.segment))
        self.tags = QLineEdit()
        self.tags.setMinimumHeight(38)
        self.tags.setAccessibleName(i18n.t("Tags"))
        self.tags.setPlaceholderText(i18n.t("hot lead, vip"))
        self.body.addWidget(ui.field(i18n.t("Or everyone with a tag"), self.tags, i18n.t("Separate tags with commas.")))
        self.error = ui.note()
        self.body.addWidget(self.error)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Add them"), "primary", on_click=self._go))
        self.resize(460, 340)

    def audience(self) -> dict:
        if self.segment.currentData():
            return {"segment_id": self.segment.currentData()}
        return {"tags": [t.strip() for t in self.tags.text().split(",") if t.strip()]}

    def _go(self):
        a = self.audience()
        if not a.get("segment_id") and not a.get("tags"):
            self.error.error(i18n.t("Choose a segment or write a tag."))
            return
        self.accept()


class _ListRow(QFrame):
    """A row of the list that can be clicked."""
    clicked = Signal()

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


# ── the two kinds of body ────────────────────────────────────────────────────

class DateBody(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        card, wc = ui.card(i18n.t("When"), i18n.t("Based on a date held in a detail of each contact."))
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.attribute = QComboBox()
        self.attribute.setMinimumHeight(38)
        self.attribute.setAccessibleName(i18n.t("Date detail"))
        self.attribute.activated.connect(lambda _i: self.editor.edited())
        row.addWidget(self.attribute, 1)
        self.new_detail_btn = C.button(i18n.t("New date detail"), "tertiary", icon_name="plus", on_click=self.new_detail)
        row.addWidget(self.new_detail_btn)
        wc.addWidget(ui.field(i18n.t("The date to go by"), row))
        trow = QHBoxLayout()
        trow.setSpacing(theme.SPACE_3)
        self.match = QComboBox()
        self.match.setMinimumHeight(38)
        self.match.addItem(i18n.t("Every year — a birthday, an anniversary"), "yearly")
        self.match.addItem(i18n.t("Once — an appointment, a due date"), "once")
        self.match.setAccessibleName(i18n.t("How often"))
        self.match.activated.connect(lambda _i: self.editor.edited())
        trow.addWidget(ui.field(i18n.t("It comes round"), self.match), 3)
        self.when = QComboBox()
        self.when.setMinimumHeight(38)
        self.when.addItem(i18n.t("On the day"), "on")
        self.when.addItem(i18n.t("Days before"), "before")
        self.when.addItem(i18n.t("Days after"), "after")
        self.when.setAccessibleName(i18n.t("Send"))
        self.when.activated.connect(self._when_changed)
        self.days = QSpinBox()
        self.days.setRange(1, 60)
        self.days.setValue(1)
        self.days.setMinimumHeight(38)
        self.days.setAccessibleName(i18n.t("Days"))
        self.days.valueChanged.connect(lambda _v: self.editor.edited())
        wrap = QHBoxLayout()
        wrap.addWidget(self.when, 2)
        wrap.addWidget(self.days, 1)
        trow.addWidget(ui.field(i18n.t("Send it"), wrap), 3)
        wc.addLayout(trow)
        srow = QHBoxLayout()
        srow.setSpacing(theme.SPACE_3)
        self.time = QTimeEdit(QTime(10, 0))
        self.time.setDisplayFormat("HH:mm")
        self.time.setMinimumHeight(38)
        self.time.setAccessibleName(i18n.t("Time of day"))
        self.time.timeChanged.connect(lambda _t: self.editor.edited())
        srow.addWidget(ui.field(i18n.t("At"), self.time), 1)
        self.zone = QComboBox()
        self.zone.setMinimumHeight(38)
        for z in ZONES:
            self.zone.addItem(z, z)
        self.zone.setAccessibleName(i18n.t("Time zone"))
        self.zone.activated.connect(lambda _i: self.editor.edited())
        srow.addWidget(ui.field(i18n.t("Time zone"), self.zone), 2)
        wc.addLayout(srow)
        self.tags = QLineEdit()
        self.tags.setMinimumHeight(38)
        self.tags.setAccessibleName(i18n.t("Only people with a tag"))
        self.tags.setPlaceholderText(i18n.t("Everyone — or e.g. vip, customer"))
        self.tags.textChanged.connect(lambda _t: self.editor.edited())
        wc.addWidget(ui.field(i18n.t("Only to people with one of these tags (optional)"), self.tags, i18n.t("Separate tags with commas.")))
        col.addWidget(card)

        card, mc = ui.card(i18n.t("The message"), i18n.t("An approved template. A message that is not a reply can only be a template."))
        self.template = TemplateChoice()
        self.template.changed.connect(self.editor.edited)
        mc.addWidget(self.template)
        col.addWidget(card)

        card, pc = ui.card(i18n.t("Who it would reach"), i18n.t("What this would do over the next seven days, from the dates you have now. Nothing is sent by looking."))
        row = QHBoxLayout()
        self.preview_btn = C.button(i18n.t("Show me"), "secondary", on_click=self.preview)
        row.addWidget(self.preview_btn)
        row.addStretch(1)
        pc.addLayout(row)
        self.preview_col = QVBoxLayout()
        self.preview_col.setSpacing(2)
        pc.addLayout(self.preview_col)
        col.addWidget(card)
        self._when_changed()

    # ── the date details ─────────────────────────────────────────────────────
    def set_attributes(self, attrs: list):
        keep = self.attribute.currentData()
        self.attribute.blockSignals(True)
        self.attribute.clear()
        dates = [a for a in attrs if a.get("type") == "date"]
        if not dates:
            self.attribute.addItem(i18n.t("No date details yet — add one"), None)
        for a in dates:
            self.attribute.addItem(a["key"], a["key"])
        self.attribute.setCurrentIndex(max(self.attribute.findData(keep), 0))
        self.attribute.blockSignals(False)

    def new_detail(self):
        dlg = NewDetailDialog(self.editor)
        if dlg.exec():
            key = dlg.key()
            ui.call(self.editor, "attributes/define", {"key": key, "type": "date"}, done=lambda r: self._made(key), failed=lambda m, _d: self.editor.say(m, error=True))

    def _made(self, key: str):
        self.editor.owner.date_attrs.append({"key": key, "type": "date"})
        self.set_attributes(self.editor.owner.date_attrs)
        self.attribute.setCurrentIndex(max(self.attribute.findData(key), 0))
        self.editor.say(i18n.t("Added the detail “{k}”. Fill it in on your contacts, or import it.").format(k=key))
        self.editor.edited()

    def _when_changed(self, *_):
        self.days.setVisible(self.when.currentData() != "on")
        self.editor.edited()

    # ── reading and showing ──────────────────────────────────────────────────
    def load(self, cfg: dict):
        self.attribute.setCurrentIndex(max(self.attribute.findData(cfg.get("attribute")), 0))
        self.match.setCurrentIndex(max(self.match.findData(cfg.get("match") or "yearly"), 0))
        n = int(cfg.get("offset_days") or 0)
        self.when.setCurrentIndex(self.when.findData("on" if n == 0 else "before" if n < 0 else "after"))
        self.days.setValue(abs(n) or 1)
        self.days.setVisible(n != 0)
        t = QTime.fromString(cfg.get("time") or "10:00", "HH:mm")
        self.time.setTime(t if t.isValid() else QTime(10, 0))
        self.zone.setCurrentIndex(max(self.zone.findData(cfg.get("tz") or DEFAULT_TZ), 0))
        self.tags.setText(", ".join(cfg.get("tags") or []))
        self.template.set_value(cfg.get("template") or {})

    def value(self) -> dict:
        way, n = self.when.currentData(), self.days.value()
        return {"attribute": self.attribute.currentData() or "", "match": self.match.currentData(), "offset_days": 0 if way == "on" else (-n if way == "before" else n),
                "time": self.time.time().toString("HH:mm"), "tz": self.zone.currentData(), "tags": [t.strip() for t in self.tags.text().split(",") if t.strip()],
                "template": self.template.value()}

    def preview(self):
        self.preview_btn.setEnabled(False)
        ui.call(self.editor, "autos/preview", {"config": self.value(), "days": 7}, done=self._previewed, failed=lambda m, _d: self._preview_failed(m))

    def _preview_failed(self, message: str):
        self.preview_btn.setEnabled(True)
        ui.clear(self.preview_col)
        self.preview_col.addWidget(C.label(message, level="SUPPORT", colour=theme.ERR_INK, wrap=True))

    def _previewed(self, reply: dict):
        self.preview_btn.setEnabled(True)
        ui.clear(self.preview_col)
        if not reply.get("total"):
            self.preview_col.addWidget(C.label(i18n.t("Nobody in the next seven days. Check the detail has dates on your contacts."), level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
            return
        for d in reply.get("days") or []:
            if d.get("count"):
                names = ", ".join(d.get("names") or []) + (" …" if d["count"] > len(d.get("names") or []) else "")
                self.preview_col.addWidget(C.label("%s — %s: %s" % (d["date"], i18n.t("{n} people").format(n=d["count"]), names), level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True))


class _StepRow(QFrame):
    """One message of a drip: how long after the one before, and the template."""

    def __init__(self, body: "DripBody", step: dict, number: int):
        super().__init__()
        self.body = body
        self.setObjectName("waDripStep")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#waDripStep {{ background: rgba(255,255,255,0.55); border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 10, 10, 10)
        col.setSpacing(theme.SPACE_1)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.title = C.label(i18n.t("Message {n}").format(n=number), level="SUPPORT", weight=700)
        head.addWidget(self.title, 1)
        head.addWidget(C.label(i18n.t("Wait"), level="META", colour=theme.NEUTRAL[600]))
        minutes = int(step.get("delay_minutes") or 0)
        unit, amount = ("d", minutes // 1440) if minutes and minutes % 1440 == 0 else ("h", minutes // 60) if minutes and minutes % 60 == 0 else ("m", minutes)
        self.amount = QSpinBox()
        self.amount.setRange(0, 100000)
        self.amount.setValue(amount)
        self.amount.setMinimumHeight(34)
        self.amount.setAccessibleName(i18n.t("Wait for"))
        self.unit = QComboBox()
        self.unit.setMinimumHeight(34)
        for k, label in (("m", i18n.t("minutes")), ("h", i18n.t("hours")), ("d", i18n.t("days"))):
            self.unit.addItem(label, k)
        self.unit.setCurrentIndex(self.unit.findData(unit))
        self.unit.setAccessibleName(i18n.t("Unit"))
        self.amount.valueChanged.connect(lambda _v: body.editor.edited())
        self.unit.activated.connect(lambda _i: body.editor.edited())
        head.addWidget(self.amount)
        head.addWidget(self.unit)
        self.remove_btn = C.icon_button("trash", i18n.t("Remove this message"), on_click=lambda: body.remove_step(self), colour=theme.NEUTRAL[600])
        head.addWidget(self.remove_btn)
        col.addLayout(head)
        self.hint = C.label("", level="META", colour=theme.NEUTRAL[500])
        col.addWidget(self.hint)
        self.template = TemplateChoice()
        self.template.set_templates(body.editor.owner.templates)
        self.template.set_value(step.get("template") or {})
        self.template.changed.connect(body.editor.edited)
        col.addWidget(self.template)

    def minutes(self) -> int:
        return self.amount.value() * {"m": 1, "h": 60, "d": 1440}[self.unit.currentData()]

    def value(self) -> dict:
        return {"delay_minutes": self.minutes(), "template": self.template.value()}


class DripBody(QWidget):
    def __init__(self, editor, parent=None):
        super().__init__(parent)
        self.editor = editor
        self.rows: list = []
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        card, sc = ui.card(i18n.t("Starts when"))
        self.trigger = QComboBox()
        self.trigger.setMinimumHeight(38)
        self.trigger.addItem(i18n.t("Someone gets a tag"), "tag")
        self.trigger.addItem(i18n.t("Someone opts in"), "opt_in")
        self.trigger.addItem(i18n.t("I add the people myself"), "manual")
        self.trigger.setAccessibleName(i18n.t("Starts when"))
        self.trigger.activated.connect(self._trigger_changed)
        sc.addWidget(self.trigger)
        self.tag = QLineEdit()
        self.tag.setMinimumHeight(38)
        self.tag.setAccessibleName(i18n.t("The tag"))
        self.tag.setPlaceholderText(i18n.t("new-lead"))
        self.tag.textChanged.connect(lambda _t: self.editor.edited())
        self.tag_box = ui.field(i18n.t("The tag"), self.tag, i18n.t("Only people who get it after you switch the drip on start it."))
        sc.addWidget(self.tag_box)
        self.existing = QCheckBox(i18n.t("Also start it for people who already have the tag"))
        self.existing.toggled.connect(lambda _on: self.editor.edited())
        sc.addWidget(self.existing)
        self.optin_note = C.label(i18n.t("People who opt in after you switch the drip on start it."), level="META", colour=theme.NEUTRAL[600], wrap=True)
        sc.addWidget(self.optin_note)
        arow = QHBoxLayout()
        self.enrol_btn = C.button(i18n.t("Add people now"), "secondary", icon_name="plus", on_click=self.enrol)
        arow.addWidget(self.enrol_btn)
        arow.addStretch(1)
        self.enrol_box = QWidget()
        self.enrol_box.setLayout(arow)
        sc.addWidget(self.enrol_box)
        col.addWidget(card)

        card, mc = ui.card(i18n.t("The messages"), i18n.t("Each one waits after the one before it. Only approved templates can be sent."))
        self.steps_col = QVBoxLayout()
        self.steps_col.setSpacing(theme.SPACE_2)
        mc.addLayout(self.steps_col)
        add = QHBoxLayout()
        self.add_btn = C.button(i18n.t("Add a message"), "tertiary", icon_name="plus", on_click=lambda: self.add_step({"delay_minutes": 1440}))
        add.addWidget(self.add_btn)
        add.addStretch(1)
        mc.addLayout(add)
        col.addWidget(card)

        card, pc = ui.card(i18n.t("Stop when"), i18n.t("So nobody is chased after they answered."))
        self.on_reply = QCheckBox(i18n.t("They reply"))
        self.on_reply.setChecked(True)
        self.on_reply.toggled.connect(lambda _on: self.editor.edited())
        pc.addWidget(self.on_reply)
        self.stop_tags = QLineEdit()
        self.stop_tags.setMinimumHeight(38)
        self.stop_tags.setAccessibleName(i18n.t("Stop on a tag"))
        self.stop_tags.setPlaceholderText(i18n.t("customer, do-not-disturb"))
        self.stop_tags.textChanged.connect(lambda _t: self.editor.edited())
        pc.addWidget(ui.field(i18n.t("They get one of these tags"), self.stop_tags, i18n.t("Separate tags with commas. Anyone who opts out always stops.")))
        col.addWidget(card)

        card, qc = ui.card(i18n.t("Quiet hours"), i18n.t("A message due outside these hours waits until they open."))
        self.quiet_on = QCheckBox(i18n.t("Only send between"))
        self.quiet_on.toggled.connect(self._quiet_changed)
        qc.addWidget(self.quiet_on)
        qrow = QHBoxLayout()
        self.quiet_from = QTimeEdit(QTime(9, 0))
        self.quiet_to = QTimeEdit(QTime(20, 0))
        for t, label in ((self.quiet_from, i18n.t("From")), (self.quiet_to, i18n.t("To"))):
            t.setDisplayFormat("HH:mm")
            t.setMinimumHeight(36)
            t.setAccessibleName(label)
            t.timeChanged.connect(lambda _t: self.editor.edited())
            qrow.addWidget(ui.field(label, t))
        qrow.addStretch(1)
        self.quiet_box = QWidget()
        self.quiet_box.setLayout(qrow)
        qc.addWidget(self.quiet_box)
        self.zone = QComboBox()
        self.zone.setMinimumHeight(36)
        for z in ZONES:
            self.zone.addItem(z, z)
        self.zone.setAccessibleName(i18n.t("Time zone"))
        self.zone.activated.connect(lambda _i: self.editor.edited())
        qc.addWidget(ui.field(i18n.t("Time zone"), self.zone))
        col.addWidget(card)
        self._quiet_changed()
        self._trigger_changed()

    def _trigger_changed(self, *_):
        kind = self.trigger.currentData()
        self.tag_box.setVisible(kind == "tag")
        self.existing.setVisible(kind == "tag")
        self.optin_note.setVisible(kind == "opt_in")
        self.enrol_box.setVisible(kind == "manual")
        self.editor.edited()

    def _quiet_changed(self, *_):
        self.quiet_box.setEnabled(self.quiet_on.isChecked())
        self.editor.edited()

    # ── steps ────────────────────────────────────────────────────────────────
    def add_step(self, step: dict):
        if len(self.rows) >= MAX_STEPS:
            return
        row = _StepRow(self, step, len(self.rows) + 1)
        self.rows.append(row)
        self.steps_col.addWidget(row)
        self._renumber()
        self.editor.edited()

    def remove_step(self, row: "_StepRow"):
        if len(self.rows) <= 1:
            return
        self.rows.remove(row)
        ui.discard(row)
        self._renumber()
        self.editor.edited()

    def _renumber(self):
        for i, r in enumerate(self.rows, start=1):
            r.title.setText(i18n.t("Message {n}").format(n=i))
            r.hint.setText(i18n.t("Sent when they start.") if i == 1 and not r.minutes() else
                           (delay_words(r.minutes()) + (" " + i18n.t("after they start") if i == 1 else " " + i18n.t("after the message before"))))
            r.remove_btn.setVisible(len(self.rows) > 1)
        self.add_btn.setVisible(len(self.rows) < MAX_STEPS)

    def set_templates(self, templates: list):
        for r in self.rows:
            r.template.set_templates(templates)

    def load(self, cfg: dict):
        for r in list(self.rows):
            self.rows.remove(r)
            ui.discard(r)
        t = cfg.get("trigger") or {"type": "manual"}
        self.trigger.setCurrentIndex(max(self.trigger.findData(t.get("type")), 0))
        self.tag.setText(t.get("tag") or "")
        self.existing.setChecked(bool(cfg.get("include_existing")))
        for s in cfg.get("steps") or [{"delay_minutes": 0}]:
            row = _StepRow(self, s, len(self.rows) + 1)
            self.rows.append(row)
            self.steps_col.addWidget(row)
        stop = cfg.get("stop") or {}
        self.on_reply.setChecked(bool(stop.get("on_reply", True)))
        self.stop_tags.setText(", ".join(stop.get("tags") or []))
        q = cfg.get("quiet")
        self.quiet_on.setChecked(bool(q))
        if q:
            self.quiet_from.setTime(QTime.fromString(q["from"], "HH:mm"))
            self.quiet_to.setTime(QTime.fromString(q["to"], "HH:mm"))
        self.zone.setCurrentIndex(max(self.zone.findData(cfg.get("tz") or DEFAULT_TZ), 0))
        self._trigger_changed()
        self._renumber()

    def value(self) -> dict:
        kind = self.trigger.currentData()
        out = {"trigger": {"type": kind, **({"tag": self.tag.text().strip()} if kind == "tag" else {})}, "steps": [r.value() for r in self.rows],
               "stop": {"on_reply": self.on_reply.isChecked(), "tags": [t.strip() for t in self.stop_tags.text().split(",") if t.strip()]}, "tz": self.zone.currentData(),
               "include_existing": self.existing.isChecked() and kind == "tag"}
        if self.quiet_on.isChecked():
            out["quiet"] = {"from": self.quiet_from.time().toString("HH:mm"), "to": self.quiet_to.time().toString("HH:mm")}
        return out

    def enrol(self):
        ui.call(self.editor, "segments/list", {}, done=self._pick_people, failed=lambda m, _d: self.editor.say(m, error=True))

    def _pick_people(self, reply: dict):
        dlg = EnrolDialog(list(reply.get("segments") or []), self.editor)
        if dlg.exec():
            self.editor.ensure_saved(lambda: ui.call(self.editor, "autos/enrol", {"auto_id": self.editor.auto["id"], "audience": dlg.audience()},
                                                     done=self._enrolled, failed=lambda m, _d: self.editor.say(m, error=True)))

    def _enrolled(self, reply: dict):
        self.editor.say(i18n.t("Added {n} people.").format(n=reply.get("enrolled", 0)) + ((" " + i18n.t("{n} left out (opted out or unreachable).").format(n=reply["left_out"])) if reply.get("left_out") else ""))
        self.editor.load_log()


# ── one automatic message ────────────────────────────────────────────────────

class AutoEditor(QWidget):
    def __init__(self, owner: "AutosSection", auto: dict, parent=None):
        super().__init__(parent)
        self.owner, self.auto = owner, auto
        self.dirty = not auto.get("id")
        self._after: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, theme.SPACE_3, 0)
        outer.setSpacing(theme.SPACE_3)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.name = QLineEdit(auto.get("name") or "")
        self.name.setMinimumHeight(38)
        self.name.setMaxLength(80)
        self.name.setAccessibleName(i18n.t("Name"))
        self.name.textChanged.connect(lambda _t: self.edited())
        head.addWidget(self.name, 1)
        self.kind_pill = C.Pill(kind_words(auto["kind"]), "neutral")
        head.addWidget(self.kind_pill)
        self.status = C.Pill("", "quiet")
        head.addWidget(self.status)
        head.addWidget(C.label(i18n.t("On"), level="META", colour=theme.NEUTRAL[600]))
        self.on = C.ToggleSwitch()
        self.on.setChecked(bool(auto.get("enabled")))
        self.on.toggled.connect(self._toggle)
        head.addWidget(self.on)
        self.save_btn = C.button(i18n.t("Save"), "primary", on_click=self.save)
        head.addWidget(self.save_btn)
        self.delete_btn = C.icon_button("trash", i18n.t("Delete this"), on_click=self._delete, colour=theme.ERR_INK)
        head.addWidget(self.delete_btn)
        outer.addLayout(head)
        self.note = ui.note()
        outer.addWidget(self.note)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        host = QWidget()
        ui.see_through(host)
        col = QVBoxLayout(host)
        col.setContentsMargins(0, 0, theme.SPACE_2, theme.SPACE_4)
        col.setSpacing(theme.SPACE_3)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self.body = DateBody(self) if auto["kind"] == "date" else DripBody(self)
        col.addWidget(self.body)
        card, lc = ui.card(i18n.t("What it has done"))
        self.stats = C.label("", level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True)
        lc.addWidget(self.stats)
        self.log_col = QVBoxLayout()
        self.log_col.setSpacing(2)
        lc.addLayout(self.log_col)
        col.addWidget(card)
        col.addStretch(1)

        if auto["kind"] == "date":
            self.body.set_attributes(owner.date_attrs)
            self.body.template.set_templates(owner.templates)
        else:
            self.body.set_templates(owner.templates)
        self.body.load(auto.get("config") or {})
        self.dirty = not auto.get("id")
        self._status()
        self.on.setEnabled(bool(auto.get("id")))
        self.delete_btn.setVisible(bool(auto.get("id")))
        if auto.get("id"):
            self.load_log()

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    def _status(self):
        if not self.auto.get("id"):
            self.status.setText(i18n.t("Not saved yet"))
            self.status.set_tone("quiet")
        elif self.auto.get("enabled"):
            self.status.setText(i18n.t("On"))
            self.status.set_tone("ok")
        else:
            self.status.setText(i18n.t("Off"))
            self.status.set_tone("warn")
        self.save_btn.setEnabled(self.dirty or not self.auto.get("id"))

    def edited(self):
        self.dirty = True
        self.save_btn.setEnabled(True)

    # ── saving ───────────────────────────────────────────────────────────────
    def value(self) -> dict:
        return {"name": self.name.text().strip(), "config": self.body.value()}

    def ensure_saved(self, then):
        if self.dirty or not self.auto.get("id"):
            self.save(then)
        else:
            then()

    def save(self, then=None):
        if then:
            self._after.append(then)
        v = self.value()
        if self.auto.get("id"):
            ui.call(self, "autos/update", {"auto_id": self.auto["id"], **v}, done=self._saved, failed=lambda m, _d: self._save_failed(m))
        else:
            ui.call(self, "autos/create", {"kind": self.auto["kind"], **v}, done=self._created, failed=lambda m, _d: self._save_failed(m))

    def _save_failed(self, message: str):
        self._after = []
        self.say(message, error=True)

    def _created(self, reply: dict):
        self.auto["id"] = reply["auto_id"]
        self.dirty = False
        self.say(i18n.t("Saved. Switch it on when you are ready."))
        self.owner.refresh_list()
        self.owner.open_auto(reply["auto_id"], after=self._after)
        self._after = []

    def _saved(self, reply: dict):
        self.dirty = False
        self.auto.update(reply.get("auto") or {})
        self.say(i18n.t("Saved."))
        self._status()
        self.owner.refresh_list()
        after, self._after = self._after, []
        for fn in after:
            fn()

    # ── on, off, delete ──────────────────────────────────────────────────────
    def _toggle(self, on: bool):
        def revert(message: str):
            self.on.blockSignals(True)
            self.on.setChecked(bool(self.auto.get("enabled")))
            self.on.blockSignals(False)
            self.say(message, error=True)
        self.ensure_saved(lambda: ui.call(self, "autos/set_enabled", {"auto_id": self.auto["id"], "enabled": on},
                                          done=lambda r: (self.auto.update(r.get("auto") or {"enabled": on}), self._status(),
                                                          self.say(i18n.t("Switched on. It will run at the time you chose.") if on else i18n.t("Switched off.")), self.owner.refresh_list(), self.load_log()),
                                          failed=lambda m, _d: revert(m)))

    def _delete(self):
        if ui.confirm(self, i18n.t("Delete"), i18n.t("Delete “{n}”? What it already sent stays sent. This can't be undone.").format(n=self.auto.get("name"))):
            ui.call(self, "autos/delete", {"auto_id": self.auto["id"]}, done=lambda r: self.owner.deleted())

    # ── what it did ──────────────────────────────────────────────────────────
    def load_log(self):
        ui.call(self, "autos/log", {"auto_id": self.auto["id"], "limit": 12}, done=self._logged, failed=lambda m, _d: None)

    def _logged(self, reply: dict):
        s = reply.get("stats") or {}
        parts = [i18n.t("{n} sent").format(n=s.get("sent", 0))]
        if s.get("skipped"):
            parts.append(i18n.t("{n} skipped").format(n=s["skipped"]))
        if s.get("failed"):
            parts.append(i18n.t("{n} failed").format(n=s["failed"]))
        if self.auto["kind"] == "drip":
            parts += [i18n.t("{n} still in it").format(n=s.get("active", 0)), i18n.t("{n} finished").format(n=s.get("done", 0)), i18n.t("{n} stopped").format(n=s.get("stopped", 0))]
        self.stats.setText("  ·  ".join(parts))
        ui.clear(self.log_col)
        for e in reply.get("log") or []:
            word = {"sent": i18n.t("sent"), "skipped": i18n.t("skipped"), "failed": i18n.t("failed")}.get(e.get("state"), e.get("state"))
            line = "%s — %s%s" % (e.get("name") or e.get("phone") or "", word, (" (%s)" % e["reason"]) if e.get("reason") else "")
            self.log_col.addWidget(C.label("%s    %s" % (line, short_time(e.get("at") or "")), level="META", colour=theme.ERR_INK if e.get("state") == "failed" else theme.NEUTRAL[600], wrap=True))
        for w in s.get("stopped_why") or []:
            self.log_col.addWidget(C.label(i18n.t("Stopped: {r} ({n})").format(r=w.get("reason") or "—", n=w.get("count")), level="META", colour=theme.NEUTRAL[500]))


# ── the section ──────────────────────────────────────────────────────────────

class AutosSection(QWidget):
    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self.autos: list = []
        self.templates: list = []
        self.date_attrs: list = []
        self.editor: Optional[AutoEditor] = None
        self._selected = ""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_4)
        left = QVBoxLayout()
        left.setSpacing(theme.SPACE_2)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("Automatic messages"), level="CARD_TITLE"), stretch=1)
        self.new_btn = C.button(i18n.t("New"), "primary", icon_name="plus", on_click=self._new_menu)
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
        self.state = C.EmptyState("calendar", i18n.t("Loading…"), "", i18n.t("Try again"))
        self.state.clicked.connect(self._state_action)
        self.stack.addWidget(self.state)
        self.editor_holder = QWidget()
        self.editor_lay = QVBoxLayout(self.editor_holder)
        self.editor_lay.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.editor_holder)
        root.addWidget(self.stack, 1)
        self._state_kind = "loading"

    def say(self, text: str, error: bool = False):
        self.note.set(text, "error" if error else "ok")

    def activate(self):
        ui.call(self, "templates/list", done=self._templates, failed=lambda m, _d: None)
        ui.call(self, "attributes/list", {}, done=self._attributes, failed=lambda m, _d: None)
        self.refresh_list(first=True)

    def deactivate(self):
        pass

    def _templates(self, reply: dict):
        self.templates = [t for t in reply.get("templates") or [] if str(t.get("status")).upper() == "APPROVED"]
        if self.editor is not None:
            if self.editor.auto["kind"] == "date":
                self.editor.body.template.set_templates(self.templates)
            else:
                self.editor.body.set_templates(self.templates)

    def _attributes(self, reply: dict):
        self.date_attrs = [a for a in reply.get("attributes") or [] if a.get("type") == "date"]
        if self.editor is not None and self.editor.auto["kind"] == "date":
            self.editor.body.set_attributes(self.date_attrs)

    def refresh_list(self, first: bool = False):
        ui.call(self, "autos/list", done=lambda r: self._listed(r, first), failed=lambda m, _d: self._failed(m))

    def _failed(self, message: str):
        if not self.autos:
            self._show_state("failed", message)
        self.say(message, error=True)

    def _listed(self, reply: dict, first: bool):
        self.autos = list(reply.get("autos") or [])
        ui.clear(self.list_col)
        for a in self.autos:
            self.list_col.addWidget(self._row(a))
        self.list_col.addStretch(1)
        if self.editor is None and not self.autos:
            self._show_state("none")
        elif self.editor is None and first and self.autos:
            self.open_auto(self.autos[0]["id"])

    def _row(self, a: dict) -> QWidget:
        sel = str(a["id"]) == self._selected
        row = _ListRow()
        row.setObjectName("waAutoRow")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(f"#waAutoRow {{ background: {'rgba(0,0,0,0.05)' if sel else 'rgba(255,255,255,0.55)'}; border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CONTROL}px; }}")
        col = QVBoxLayout(row)
        col.setContentsMargins(12, 10, 12, 10)
        col.setSpacing(4)
        top = QHBoxLayout()
        top.addWidget(C.label(a.get("name") or "", level="SUPPORT", weight=700, wrap=True), stretch=1)
        top.addWidget(C.Pill(i18n.t("On") if a.get("enabled") else i18n.t("Off"), "ok" if a.get("enabled") else "warn"))
        col.addLayout(top)
        col.addWidget(C.label("%s · %s" % (kind_words(a.get("kind")), summary(a)), level="META", colour=theme.NEUTRAL[600], wrap=True))
        bits = [i18n.t("{n} sent").format(n=a.get("sent", 0))]
        if a.get("kind") == "drip":
            bits.append(i18n.t("{n} in it now").format(n=a.get("active", 0)))
        col.addWidget(C.label("  ·  ".join(bits), level="META", colour=theme.NEUTRAL[500]))
        row.clicked.connect(lambda aid=a["id"]: self.open_auto(aid))
        return row

    def _show_state(self, kind: str, message: str = ""):
        title, body, action = {
            "loading": (i18n.t("Loading…"), "", None),
            "failed": (i18n.t("Couldn't load your automatic messages"), message, i18n.t("Try again")),
            "none": (i18n.t("Nothing automatic yet"), i18n.t("Send a birthday message, remind people of an appointment or a payment, or run a short series after someone enquires."), i18n.t("New")),
            "pick": (i18n.t("Choose one"), i18n.t("Pick one on the left to change it, or make a new one."), None),
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

    # ── opening and making ───────────────────────────────────────────────────
    def open_auto(self, auto_id: str, after: Optional[list] = None):
        self._selected = str(auto_id)
        ui.call(self, "autos/get", {"auto_id": auto_id}, done=lambda r: self._opened(r, after), failed=lambda m, _d: self.say(m, error=True))

    def _opened(self, reply: dict, after: Optional[list] = None):
        self._show(AutoEditor(self, dict(reply.get("auto") or {})))
        self.refresh_list()
        for fn in after or []:
            fn()

    def _show(self, editor: AutoEditor):
        if self.editor is not None:
            self.editor.hide()
            self.editor.setParent(None)
            self.editor.deleteLater()
        self.editor = editor
        self.editor_lay.addWidget(editor)
        self.stack.setCurrentIndex(1)

    def deleted(self):
        self.editor = None
        self._selected = ""
        self.say(i18n.t("Deleted."))
        self.refresh_list()
        self._show_state("pick")

    def _new_menu(self):
        menu = QMenu(self)
        dates = menu.addMenu(i18n.t("On a date"))
        drips = menu.addMenu(i18n.t("A drip"))
        for key, kind, name, hint, _cfg in presets():
            act = (dates if kind == "date" else drips).addAction(name)
            act.setToolTip(hint)
            act.triggered.connect(lambda _=False, k=key: self.start(k))
        dates.setToolTipsVisible(True)
        drips.setToolTipsVisible(True)
        menu.exec(self.new_btn.mapToGlobal(self.new_btn.rect().bottomLeft()))

    def start(self, key: str):
        """Begin a new one from a ready-made start. It exists only on screen until it is saved."""
        _k, kind, name, _hint, cfg = next(p for p in presets() if p[0] == key)
        cfg = copy.deepcopy(cfg)
        if kind == "date":
            cfg.setdefault("attribute", (self.date_attrs[0]["key"] if self.date_attrs else ""))
            cfg.setdefault("tz", DEFAULT_TZ)
            cfg.setdefault("template", {})
        else:
            for s in cfg["steps"]:
                s.setdefault("template", {})
        self._selected = ""
        self._show(AutoEditor(self, {"id": None, "kind": kind, "name": name, "enabled": False, "config": cfg}))
        self.editor.say(i18n.t("Choose the template to send, then save it."))
