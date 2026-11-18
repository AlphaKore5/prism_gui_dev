"""Settings > Usage: what Prism's AI has cost this licence.

Everything on this page is drawn from one answer of the server's
GET /v1/ai/usage (balance, this cycle, today, by add-on, last 30 days, recent
calls). The answer is fetched on a worker thread (workers.UsageWorker); the page
itself never touches the network. An older server without the route answers 404:
the page then shows what this session heard and says so.

mc = milli-credits; people see credits = mc / 1000.
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

import ai_server
import i18n
import theme
from widgets import controls as C
from workers import UsageWorker


def credits(mc) -> str:
    """Milli-credits as the credits a person reads: 12,345 -> "12.35"."""
    mc = int(mc or 0)
    if mc == 0:
        return "0"
    if 0 < abs(mc) < 10:
        return "<0.01"
    return f"{mc / 1000:,.2f}".rstrip("0").rstrip(".")


def _nice(addon: str) -> str:
    return (addon or "core").replace("_", " ").replace("/", " ").title()


class DayBars(QWidget):
    """The last 30 days as bars, painted (no chart library)."""

    def __init__(self, days: list, parent=None):
        super().__init__(parent)
        self.days = list(days)
        self.setFixedHeight(96)
        self.setMinimumWidth(180)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        n = len(self.days)
        if not n:
            return
        top = max([int(d.get("used_mc") or 0) for d in self.days] + [1])
        gap = 3
        bar = max(2.0, (self.width() - gap * (n - 1)) / n)
        base = self.height() - 4
        p.setPen(Qt.NoPen)
        for i, d in enumerate(self.days):
            mc = int(d.get("used_mc") or 0)
            h = max(2.0, (base - 4) * mc / top) if mc else 2.0
            last = i == n - 1
            p.setBrush(theme.c(theme.BRAND_RED if last else theme.ACCENT,
                               1.0 if mc else 0.18))
            p.drawRoundedRect(QRectF(i * (bar + gap), base - h, bar, h), 2, 2)


class UsagePanel(QWidget):
    """Embedded in Settings. `refresh()` asks again; it is also what the
    Refresh button does."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = None
        self.data: dict | None = None
        self.session_only = False
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_4)
        bar = QHBoxLayout()
        self.status = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        bar.addWidget(self.status, stretch=1)
        self.refresh_btn = C.button(i18n.t("Refresh"), "secondary", small=True,
                                    on_click=self.refresh)
        bar.addWidget(self.refresh_btn)
        col.addLayout(bar)
        self.body = QVBoxLayout()
        self.body.setSpacing(theme.SPACE_4)
        col.addLayout(self.body)

    # ── loading ──────────────────────────────────────────────────────────
    def refresh(self):
        if self._worker is not None:
            return                              # one ask at a time
        if not ai_server.active():
            self.status.setText(i18n.t(
                "Usage is listed when AI runs through your Prism plan."))
            return
        ai_server.refresh_async(force=True)
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setToolTip(i18n.t("Loading your usage…"))
        self.status.setText(i18n.t("Loading your usage…"))
        w = UsageWorker()
        w.done.connect(self._loaded)
        w.failed.connect(self._failed)
        self._worker = w
        w.start()

    def _settle(self):
        self._worker = None
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setToolTip("")

    def _loaded(self, data):
        self._settle()
        self.session_only = False
        self.status.setText("")
        self.show_data(data)

    def _failed(self, error):
        self._settle()
        code = getattr(error, "code", "")
        if code == "NOT_SET_UP" or getattr(error, "status", 0) == 404:
            # An older server without /v1/ai/usage.
            self.session_only = True
            self.status.setText(i18n.t("Showing this session only"))
            self.show_data(ai_server.session_usage())
            return
        self.session_only = False
        self.status.setText(i18n.t("Couldn't load your usage: {why}").format(
            why=str(error) or i18n.t("Prism's server didn't answer.")))
        if self.data is None:
            self.show_data(None)

    # ── drawing ──────────────────────────────────────────────────────────
    def _clear(self):
        while self.body.count():
            item = self.body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def show_data(self, data):
        self._clear()
        self.data = data
        if not data:
            return
        events = data.get("events") or []
        if not events and not int((data.get("cycle") or {}).get("used_mc") or 0):
            self.body.addWidget(self._summary(data))
            self.empty = C.label(i18n.t("No AI calls yet"), level="BODY",
                                 colour=theme.NEUTRAL[600])
            self.empty.setObjectName("usageEmpty")
            self.body.addWidget(self.empty)
            return
        self.body.addWidget(self._summary(data))
        if data.get("by_addon"):
            self.body.addWidget(self._by_addon(data["by_addon"]))
        if data.get("by_day"):
            self.body.addWidget(self._chart(data["by_day"]))
        if events:
            self.body.addWidget(self._calls(events))

    def _card(self, title: str):
        card = C.Card("soft")
        col = card.body((theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD), theme.SPACE_2)
        col.addWidget(C.kicker(title))
        return card, col

    @staticmethod
    def _pair(name: str, value: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(C.label(name, level="SUPPORT", colour=theme.NEUTRAL[600]), stretch=1)
        row.addWidget(C.label(value, level="SUPPORT", colour=theme.TEXT))
        return row

    def _summary(self, d: dict) -> QWidget:
        card, col = self._card(i18n.t("Credits"))
        cyc = d.get("cycle") or {}
        used, allow = int(cyc.get("used_mc") or 0), cyc.get("allowance_mc")
        col.addLayout(self._pair(i18n.t("Credits left"), credits(d.get("balance_mc"))))
        col.addLayout(self._pair(
            i18n.t("Used this cycle"),
            (i18n.t("{used} of {total}").format(used=credits(used), total=credits(allow))
             if allow else credits(used))))
        if allow:
            col.addWidget(C.ProgressBar(min(1.0, used / int(allow))))
        if cyc.get("resets_at"):
            days = max(0, -(-(int(cyc["resets_at"]) - int(time.time())) // 86400))
            col.addLayout(self._pair(i18n.t("Resets in"),
                                     i18n.t("{n} days").format(n=days)))
        col.addLayout(self._pair(i18n.t("Used today"),
                                 credits((d.get("today") or {}).get("used_mc"))))
        return card

    def _by_addon(self, rows: list) -> QWidget:
        card, col = self._card(i18n.t("By add-on, last 30 days"))
        for r in rows:
            col.addLayout(self._pair(
                f"{_nice(r.get('addon', ''))}  ·  " + i18n.t("{n} calls").format(
                    n=int(r.get("calls") or 0)),
                credits(r.get("used_mc"))))
        return card

    def _chart(self, days: list) -> QWidget:
        card, col = self._card(i18n.t("Last 30 days"))
        self.chart = DayBars(days)
        col.addWidget(self.chart)
        col.addLayout(self._pair(days[0].get("day", ""), days[-1].get("day", "")))
        return card

    def _calls(self, events: list) -> QWidget:
        card, col = self._card(i18n.t("Recent calls"))
        for e in events:
            when = datetime.fromtimestamp(int(e.get("ts") or 0)).strftime("%d %b %H:%M")
            status = {"ok": "", "refunded": i18n.t("  ·  refunded"),
                      "failed": i18n.t("  ·  failed")}.get(e.get("status"), "")
            what = (f"{when}  ·  {_nice(e.get('addon', ''))} / {e.get('feature', '')}"
                    f"  ·  {e.get('model_label') or e.get('role', '')}{status}")
            col.addLayout(self._pair(what, credits(e.get("used_mc"))))
        return card
