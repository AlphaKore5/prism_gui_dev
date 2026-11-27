"""WhatsApp plans, as AiSensy shows them (the owner, 27-Nov-2026: "build all of it like aisensy").

  PlanCompareDialog   every tier side by side — price (monthly, quarterly or yearly), limits and features — then the
                      add-ons bought on top of any plan, with "Ask for this" on each. The catalogue is prism-wa's own
                      (usage/plan → "catalogue"), so a price or a limit changes in one place on the server.
  UpgradePrompt       what a locked feature shows: why it was refused, which plan or add-on has it, and the way there.
  offer_upgrade()     called by ui.call for every plan refusal, so any screen that meets one gets the same prompt.

There is no payment here: "Ask" sends a request to Alphakore (plan/request on the licence server, listed in its
console), and the plan changes when the operator grants it.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QWidget

import i18n
import theme
from addons.whatsapp import ui
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons

CYCLES = (("monthly", "Monthly"), ("quarterly", "Quarterly"), ("yearly", "Yearly"))
PLAN_REASONS = ("plan_feature", "plan_limit")


def cycle_names() -> dict:
    """Literal i18n.t calls, so the extractor sees every word."""
    return {"monthly": i18n.t("Monthly"), "quarterly": i18n.t("Quarterly"), "yearly": i18n.t("Yearly")}


def rupees(n) -> str:
    """"Rs 1,500" — words, not the ₹ sign: the app's font has no ₹ (as analytics_page.rupees, Indian grouping)."""
    from addons.whatsapp.analytics_page import rupees as rs
    return rs(n)


def price_text(price, cycle: str = "monthly", discounts: dict = None) -> str:
    """"₹1,500 / month", "₹2,880 / month, billed yearly", "Free" or "Talk to us"."""
    if price is None:
        return i18n.t("Talk to us")
    if not price:
        return i18n.t("Free")
    off = int((discounts or {}).get(cycle) or 0)
    monthly = price * (100 - off) / 100.0
    if cycle == "monthly" or not off:
        return i18n.t("{p} / month").format(p=rupees(monthly))
    return i18n.t("{p} / month, billed {c}").format(p=rupees(monthly), c=cycle_names()[cycle].lower())


def limit_text(key: str, value) -> str:
    if value is None:
        return i18n.t("No limit")
    if value == 0:
        return "–"
    if key == "storage_mb":
        return ("%g GB" % (value / 1024)) if value >= 1024 else "%d MB" % value
    return "{:,}".format(int(value))


def needs_words(needs, catalogue: dict = None) -> str:
    """"Pro", "the Chatbot flows add-on", or "" — what unlocks a refused feature, in words."""
    needs = str(needs or "")
    if needs.startswith("addon:"):
        key = needs.split(":", 1)[1]
        label = next((a["label"] for a in (catalogue or {}).get("addons", []) if a.get("addon") == key), key.replace("_", " "))
        return i18n.t("the {a} add-on").format(a=label)
    if not needs:
        return ""
    tier = next((t for t in (catalogue or {}).get("tiers", []) if t.get("plan") == needs), None)
    return tier["label"] if tier else needs.title()


def lowest_plan_label(feature: str, catalogue: dict = None) -> str:
    """The name of the smallest plan in the catalogue that includes `feature` ("Pro"), or ""."""
    for t in (catalogue or {}).get("tiers") or []:
        if feature in (t.get("features") or []):
            return t.get("label") or ""
    return ""


def want_of(needs) -> dict:
    """The upgrade request a refusal's `needs` asks for: {"plan": "pro"} or {"addons": ["chatbot"]}."""
    needs = str(needs or "")
    if needs.startswith("addon:"):
        return {"addons": [needs.split(":", 1)[1]]}
    return {"plan": needs} if needs else {}


class PlanCompareDialog(PrismDialog):
    """Every plan side by side, with the current one marked, and a way to ask for another."""

    def __init__(self, plan_reply: dict, parent=None):
        super().__init__(i18n.t("Compare plans"), i18n.t("What each plan includes. Messages are billed by Meta on every plan."),
                         icon="chart", parent=parent, scrollable=True)
        self.reply = dict(plan_reply or {})
        self.catalogue = dict(self.reply.get("catalogue") or {})
        self.current = self.reply.get("plan") or ""
        self.addons = set(self.reply.get("addons") or [])
        self.cycle = "monthly"
        self.asked: list = []

        chips = C.FilterChips([(k, cycle_names()[k] + (" · −%d%%" % (self.catalogue.get("billing_discount") or {}).get(k, 0)
                                                     if (self.catalogue.get("billing_discount") or {}).get(k) else ""))
                               for k, _ in CYCLES], "monthly")
        chips.changed.connect(self._set_cycle)
        self.chips = chips
        self.body.addWidget(chips)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(theme.SPACE_3)
        self.grid.setVerticalSpacing(theme.SPACE_2)
        host = QWidget()
        host.setLayout(self.grid)
        self.body.addWidget(host)

        self.body.addWidget(C.label(i18n.t("Add-ons, on top of any plan"), level="CARD_TITLE"))
        self.addon_rows = QGridLayout()
        self.addon_rows.setHorizontalSpacing(theme.SPACE_3)
        self.addon_rows.setVerticalSpacing(theme.SPACE_2)
        ahost = QWidget()
        ahost.setLayout(self.addon_rows)
        self.body.addWidget(ahost)
        self.note = ui.note()
        self.body.addWidget(self.note)
        self.body.addStretch(1)
        self.footer.set_primary(self.button(i18n.t("Done"), "primary", on_click=self.accept))
        self._fill()
        self.resize(1080, 760)

    # ── the table ────────────────────────────────────────────────────────────
    def _set_cycle(self, key: str):
        self.cycle = key if key in dict(CYCLES) else "monthly"
        self._fill()

    def _fill(self):
        ui.clear(self.grid)
        ui.clear(self.addon_rows)
        cat = self.catalogue
        tiers = cat.get("tiers") or []
        discounts = cat.get("billing_discount") or {}
        self.ask_buttons = {}
        order = [t.get("plan") for t in tiers]
        here = order.index(self.current) if self.current in order else -1
        for c, t in enumerate(tiers, start=1):
            mine = t.get("plan") == self.current
            head = C.label(t.get("label", ""), level="CARD_TITLE")
            self.grid.addWidget(head, 0, c)
            self.grid.addWidget(C.label(t.get("tagline", ""), level="META", colour=theme.NEUTRAL[600], wrap=True), 1, c)
            self.grid.addWidget(C.label(price_text(t.get("price"), self.cycle, discounts), level="SUPPORT", weight=700, wrap=True), 2, c)
            if mine:
                self.grid.addWidget(C.Pill(i18n.t("Your plan"), "accent"), 3, c, alignment=Qt.AlignLeft)
            elif c - 1 < here:
                pass                                        # a smaller plan than yours: nothing to ask for here
            else:
                b = C.button(i18n.t("Ask for {p}").format(p=t.get("label", "")) if t.get("price") is not None else i18n.t("Talk to us"),
                             "secondary", small=True, on_click=lambda _=False, p=t.get("plan"): self.ask({"plan": p}))
                self.ask_buttons[t.get("plan")] = b
                self.grid.addWidget(b, 3, c, alignment=Qt.AlignLeft)
        row = 4
        self.grid.addWidget(C.label(i18n.t("Limits"), level="SUPPORT", weight=700), row, 0)
        row += 1
        for lim in cat.get("limits") or []:
            self.grid.addWidget(C.label(lim.get("label", ""), level="SUPPORT"), row, 0)
            for c, t in enumerate(tiers, start=1):
                self.grid.addWidget(C.label(limit_text(lim["key"], (t.get("limits") or {}).get(lim["key"])), level="SUPPORT",
                                            colour=theme.NEUTRAL[800]), row, c)
            row += 1
        self.grid.addWidget(C.label(i18n.t("Features"), level="SUPPORT", weight=700), row, 0)
        row += 1
        for f in cat.get("features") or []:
            self.grid.addWidget(C.label(f.get("label", ""), level="SUPPORT", wrap=True), row, 0)
            for c, t in enumerate(tiers, start=1):
                yes = f["key"] in (t.get("features") or [])
                mark = QLabel()
                if yes:                                     # the app's own icon: a "✓" glyph draws as a box in its font
                    mark.setPixmap(icons.pixmap("check", 14, theme.OK))
                    mark.setAccessibleName(i18n.t("Included"))
                else:
                    mark.setText("–")
                    mark.setStyleSheet("color: %s;" % theme.NEUTRAL[400])
                    mark.setAccessibleName(i18n.t("Not included"))
                self.grid.addWidget(mark, row, c)
            row += 1
        self.grid.setColumnStretch(0, 2)
        for i, a in enumerate(cat.get("addons") or []):
            self.addon_rows.addWidget(C.label(a.get("label", ""), level="SUPPORT", weight=700), i, 0)
            per = i18n.t("{p} / seat / month") if a.get("addon") == "seat" else i18n.t("{p} / month")
            self.addon_rows.addWidget(C.label(per.format(p=rupees(a.get("price") or 0)), level="SUPPORT"), i, 1)
            if a.get("addon") in self.addons:
                self.addon_rows.addWidget(C.Pill(i18n.t("You have it"), "accent"), i, 2, alignment=Qt.AlignLeft)
            else:
                want = {"seats": 1} if a.get("addon") == "seat" else {"addons": [a.get("addon")]}
                self.addon_rows.addWidget(C.button(i18n.t("Ask for it"), "secondary", small=True,
                                                   on_click=lambda _=False, w=want: self.ask(w)), i, 2, alignment=Qt.AlignLeft)
        self.addon_rows.setColumnStretch(3, 1)

    # ── asking ───────────────────────────────────────────────────────────────
    def ask(self, want: dict):
        self.asked.append(dict(want))
        self.note.set(i18n.t("Sending your request…"))
        ui.call(self, "plan/request", {"want": want, "note": i18n.t("Asked from Compare plans")},
                done=self._asked, failed=lambda m, _d: self.note.error(m))

    def _asked(self, reply: dict):
        name = ((reply or {}).get("request") or {}).get("offer_name") or ""
        self.note.ok(i18n.t("Asked for {w}. Alphakore will be in touch to switch it on.").format(w=name) if (reply or {}).get("created", True)
                     else i18n.t("You have already asked for {w}. Alphakore will be in touch.").format(w=name))


class UpgradePrompt(PrismDialog):
    """A locked feature: what was refused, which plan or add-on has it, and the way there."""

    def __init__(self, message: str, needs, parent=None):
        super().__init__(i18n.t("Not on your plan"), "", icon="lock", parent=parent)
        self.needs = needs
        self.plan_reply: dict = {}
        self.body.addWidget(C.label(message, level="SUPPORT", wrap=True))
        what = needs_words(needs)
        self.where = C.label(i18n.t("It is part of {w}.").format(w=what) if what else "", level="SUPPORT", colour=theme.NEUTRAL[700], wrap=True)
        self.where.setVisible(bool(what))
        self.body.addWidget(self.where)
        self.note = ui.note()
        self.body.addWidget(self.note)
        self.compare_btn = self.button(i18n.t("Compare plans"), on_click=self._compare)
        self.footer.add_secondary(self.button(i18n.t("Close"), on_click=self.reject))
        self.footer.add_secondary(self.compare_btn)
        self.ask_btn = self.button(i18n.t("Ask for {w}").format(w=what) if what else i18n.t("Ask Alphakore"), "primary", on_click=self._ask)
        self.footer.set_primary(self.ask_btn)
        self.resize(520, 260)
        ui.call(self, "usage/plan", {}, done=self._got_plan, failed=lambda m, _d: None)

    def _got_plan(self, reply: dict):
        self.plan_reply = dict(reply or {})
        what = needs_words(self.needs, self.plan_reply.get("catalogue"))
        if what:
            self.where.setText(i18n.t("It is part of {w}.").format(w=what))
            self.ask_btn.setText(i18n.t("Ask for {w}").format(w=what))

    def _compare(self):
        dlg = PlanCompareDialog(self.plan_reply, parent=self.parentWidget())
        dlg.open()
        self.accept()

    def _ask(self):
        want = want_of(self.needs)
        if not want:
            self._compare()
            return
        self.ask_btn.setEnabled(False)
        self.note.set(i18n.t("Sending your request…"))
        ui.call(self, "plan/request", {"want": want, "note": i18n.t("Asked when a feature was locked")},
                done=lambda r: self.note.ok(i18n.t("Asked. Alphakore will be in touch to switch it on.")),
                failed=lambda m, _d: (self.ask_btn.setEnabled(True), self.note.error(m)))


_OPEN: list = []                    # one prompt at a time: a screen that meets the same wall twice shows it once


def offer_upgrade(owner, message: str, detail: dict) -> bool:
    """When a call was refused for the plan, show the upgrade prompt (non-blocking). True when it was shown."""
    if (detail or {}).get("reason") not in PLAN_REASONS:
        return False
    _OPEN[:] = [d for d in _OPEN if d.isVisible()]
    if _OPEN:
        return False
    parent = owner.window() if isinstance(owner, QWidget) else None
    dlg = UpgradePrompt(message, (detail or {}).get("needs"), parent=parent)
    _OPEN.append(dlg)
    dlg.open()
    return True
