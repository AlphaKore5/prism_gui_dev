"""Settings → Plan and usage.

The plan, each of its limits against what is in use, what this month's WhatsApp messages have cost so far, and the rate card behind that
estimate. The cost is Meta's, not ours: Meta bills by message category, and the service adds up the price Meta reports with each delivered
message at a rate card that starts from Meta's published India rates and that you can correct to what you were actually charged.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp import ui
from addons.whatsapp.analytics_page import category_name, count_text, rupees
from addons.whatsapp.settings import _COLUMN, _scrolled
from widgets import controls as C


def limit_names() -> dict:
    """Literal i18n.t calls, so the extractor sees every word."""
    return {"agents": i18n.t("Team members"), "tags": i18n.t("Tags"), "attributes": i18n.t("Custom attributes"), "segments": i18n.t("Saved segments"),
            "flows": i18n.t("Chatbot flows"), "webhooks": i18n.t("Webhooks"), "ai_messages": i18n.t("AI replies this month"),
            "storage_mb": i18n.t("Media storage"), "mps": i18n.t("Sending speed (messages a second)")}


def used_words(row: dict) -> str:
    """"3 of 10", "212 of 1,000" or "3 · no limit"; storage in MB or GB."""
    key, used, limit = row["key"], int(row.get("used") or 0), row.get("limit")
    if key == "mps":
        return i18n.t("up to {n}").format(n=count_text(limit)) if limit is not None else i18n.t("no limit")
    unit = ""
    if key == "storage_mb":
        def size(mb):
            return ("%.1f GB" % (mb / 1024)) if mb >= 1024 else "%d MB" % mb
        return (i18n.t("{a} of {b}").format(a=size(used), b=size(limit)) if limit is not None else i18n.t("{a} · no limit").format(a=size(used)))
    if limit is None:
        return i18n.t("{a}{u} · no limit").format(a=count_text(used), u=unit)
    return i18n.t("{a} of {b}").format(a=count_text(used), b=count_text(limit))


def fraction(row: dict) -> float:
    limit = row.get("limit")
    if not limit or row["key"] == "mps":
        return 0.0
    return min(1.0, int(row.get("used") or 0) / float(limit))


def addon_names() -> dict:
    """Literal i18n.t calls, so the extractor sees every word."""
    return {"chatbot": i18n.t("Chatbot flows"), "ai_agent": i18n.t("AI agent")}


def addons_words(reply: dict) -> str:
    """"Add-ons: Chatbot flows, AI agent · 2 extra seats", or "" when there are none."""
    names = addon_names()
    parts = [names.get(a, a) for a in (reply or {}).get("addons") or []]
    seats = int((reply or {}).get("extra_seats") or 0)
    if seats:
        parts.append(i18n.t("1 extra seat") if seats == 1 else i18n.t("{n} extra seats").format(n=seats))
    return i18n.t("Add-ons: {a}").format(a=", ".join(parts)) if parts else ""


class PlanSection(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer, col = _scrolled(None)
        QVBoxLayout(self).addWidget(outer)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self._spins: dict = {}

        card, pc = ui.card(i18n.t("Your plan"), "", width=_COLUMN)
        top = QHBoxLayout()
        self.plan_name = C.label("", level="CARD_TITLE")
        top.addWidget(self.plan_name, stretch=1)
        self.plan_next = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600])
        top.addWidget(self.plan_next)
        # Every plan side by side, and a way to ask for another (plan_compare; the owner, 27-Nov-2026).
        self.compare_btn = C.button(i18n.t("Compare plans"), "secondary", small=True, on_click=self._compare)
        self.compare_btn.setEnabled(False)                  # until the plan, with its catalogue, has arrived
        top.addWidget(self.compare_btn)
        pc.addLayout(top)
        self.plan_note = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        pc.addWidget(self.plan_note)
        self.addons_note = C.label("", level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True)
        pc.addWidget(self.addons_note)
        col.addWidget(card)

        card, uc = ui.card(i18n.t("What you use"), i18n.t("Each limit against what is in use now."), width=_COLUMN)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(theme.SPACE_4)
        self.grid.setVerticalSpacing(theme.SPACE_2)
        uc.addLayout(self.grid)
        col.addWidget(card)

        card, sc = ui.card(i18n.t("This month's WhatsApp spend"), i18n.t("An estimate from the price Meta reports on each delivered message. Meta's invoice is the real figure."),
                           width=_COLUMN)
        self.month_total = C.label("", level="CARD_TITLE")
        sc.addWidget(self.month_total)
        self.month_cols = QVBoxLayout()
        self.month_cols.setSpacing(2)
        sc.addLayout(self.month_cols)
        col.addWidget(card)

        card, rc = ui.card(i18n.t("Rate card"), i18n.t("Rupees per billable message, before GST. These start from Meta's published India rates. If your Meta invoice shows "
                                                      "something different, enter what you were charged and the estimates follow."), width=_COLUMN)
        form = QGridLayout()
        form.setHorizontalSpacing(theme.SPACE_4)
        form.setVerticalSpacing(theme.SPACE_2)
        for i, cat in enumerate(("MARKETING", "UTILITY", "AUTHENTICATION", "SERVICE")):
            form.addWidget(C.label(category_name(cat), level="SUPPORT", weight=700), i, 0)
            spin = QDoubleSpinBox()
            spin.setRange(0, 1000)
            spin.setDecimals(4)
            spin.setSingleStep(0.01)
            spin.setPrefix("Rs ")
            spin.setMinimumHeight(34)
            spin.setAccessibleName(i18n.t("Rate for {c}").format(c=category_name(cat)))
            self._spins[cat] = spin
            form.addWidget(spin, i, 1)
        form.setColumnStretch(2, 1)
        rc.addLayout(form)
        row = QHBoxLayout()
        self.rates_note = ui.note()
        row.addWidget(self.rates_note, stretch=1)
        self.reset_btn = C.button(i18n.t("Back to Meta's rates"), "tertiary", on_click=self._reset)
        row.addWidget(self.reset_btn)
        self.save_btn = C.button(i18n.t("Save rates"), "primary", on_click=self._save)
        row.addWidget(self.save_btn)
        rc.addLayout(row)
        col.addWidget(card)
        col.addStretch(1)
        self._defaults: dict = {}
        self._plan_reply: dict = {}

    def _compare(self):
        from addons.whatsapp.plan_compare import PlanCompareDialog
        self._compare_dlg = PlanCompareDialog(self._plan_reply, parent=self.window())
        self._compare_dlg.open()

    def say(self, message: str, error: bool = False):
        (self.rates_note.error if error else self.rates_note.ok)(message)

    def activate(self):
        ui.call(self, "usage/plan", {}, done=self._plan, failed=lambda m, _d: self.plan_note.setText(m))
        ui.call(self, "usage/rates", {}, done=self._rates, failed=lambda m, _d: self.rates_note.error(m))

    def deactivate(self):
        pass

    def _plan(self, reply: dict):
        self._plan_reply = dict(reply or {})
        self.compare_btn.setEnabled(bool((reply or {}).get("catalogue")))
        self.plan_name.setText(reply.get("label") or "")
        self.addons_note.setText(addons_words(reply))
        self.addons_note.setVisible(bool(self.addons_note.text()))
        nxt = reply.get("next_plan")
        self.plan_next.setText(i18n.t("The next plan up is {p}.").format(p=nxt.title()) if nxt else i18n.t("This is the top plan."))
        feats = reply.get("features") or []
        self.plan_note.setText(i18n.t("{n} features are part of it.").format(n=len(feats)))
        ui.clear(self.grid)
        names = limit_names()
        for i, row in enumerate(reply.get("limits") or []):
            self.grid.addWidget(C.label(names.get(row["key"], row["key"]), level="SUPPORT", weight=700), i, 0)
            bar = C.ProgressBar(fraction(row), hue=theme.WARN if fraction(row) >= 0.9 else None)
            bar.setMinimumWidth(180)
            self.grid.addWidget(bar, i, 1)
            lab = C.label(used_words(row), level="SUPPORT", colour=theme.NEUTRAL[700])
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(lab, i, 2)
        self.grid.setColumnStretch(1, 1)
        month = reply.get("month") or {}
        t = month.get("totals") or {}
        self.month_total.setText(i18n.t("{c} so far in {m}").format(c=rupees(t.get("cost")), m=month.get("label") or ""))
        ui.clear(self.month_cols)
        for c in month.get("by_category") or []:
            self.month_cols.addWidget(C.label(i18n.t("{cat}: {n} billed · {c}").format(cat=category_name(c["category"]), n=count_text(c["billable"]), c=rupees(c["cost"])),
                                              level="SUPPORT", colour=theme.NEUTRAL[700]))
        self.month_cols.addWidget(C.label(i18n.t("With 18% GST that is about {c}.").format(c=rupees(t.get("cost_with_gst"))), level="META", colour=theme.NEUTRAL[500]))

    def _rates(self, reply: dict):
        self._defaults = dict(reply.get("defaults") or {})
        for cat, spin in self._spins.items():
            spin.setValue(float((reply.get("rates") or {}).get(cat, 0)))

    def _reset(self):
        for cat, spin in self._spins.items():
            spin.setValue(float(self._defaults.get(cat, 0)))
        self._save()

    def _save(self):
        rates = {cat: spin.value() for cat, spin in self._spins.items()}
        self.save_btn.setEnabled(False)
        ui.call(self, "usage/rates_save", {"rates": rates}, done=self._saved, failed=lambda m, _d: (self.save_btn.setEnabled(True), self.rates_note.error(m)))

    def _saved(self, reply: dict):
        self.save_btn.setEnabled(True)
        self._rates(reply)
        self.rates_note.ok(i18n.t("Saved."))
        ui.call(self, "usage/plan", {}, done=self._plan, failed=lambda m, _d: None)
