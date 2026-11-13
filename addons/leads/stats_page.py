"""The Stats tab — section 5 of "Prism CRM: interface mockups" (3 Nov 2026).

Four figures, the funnel, and why deals were lost, over the last 30 days, every one read from stored history by stats.py. A figure with no data
behind it reads "—", and a page with nothing at all says so rather than drawing zeros. It only draws what `set_data` is handed.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

import i18n
import theme
from addons.leads import deals as DL
from addons.leads import stats as ST
from widgets import controls as C


class _Bar(QWidget):
    """A thin bar filled to `fraction` of its width."""

    def __init__(self, fraction: float, parent=None):
        super().__init__(parent)
        self.fraction = max(0.0, min(1.0, fraction))
        self.setFixedHeight(8)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.NEUTRAL[200]))
        p.drawRoundedRect(self.rect(), 4, 4)
        if self.fraction > 0:
            p.setBrush(QColor(theme.ACCENT))
            width = max(8, int(self.width() * self.fraction))
            p.drawRoundedRect(0, 0, width, self.height(), 4, 4)


def _card(name: str = "") -> tuple:
    frame = QFrame()
    frame.setObjectName("statCard")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    frame.setStyleSheet(f"QFrame#statCard{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}")
    col = QVBoxLayout(frame)
    col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
    col.setSpacing(theme.SPACE_2)
    if name:
        col.addWidget(C.label(name, level="SUPPORT", weight=700))
    return frame, col


def _percent(value: Optional[float]) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


class StatsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("statsHead")
        head.setStyleSheet(f"QFrame#statsHead{{background:{theme.CARD};border:none;border-bottom:1px solid {theme.HAIRLINE};}}")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        hl.setSpacing(2)
        hl.addWidget(C.label(i18n.t("Stats"), level="SECTION", weight=700))
        self.summary = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        hl.addWidget(self.summary)
        outer.addWidget(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        host = QWidget()
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        self._col.setSpacing(theme.SPACE_3)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)
        self._contacts: list = []
        self._deals: list = []
        self._today: Optional[date] = None
        self.stats = ST.Stats()
        self.tiles: dict = {}
        self.set_data([], [])

    # -- data ----------------------------------------------------------------
    def set_today(self, today: Optional[date]) -> None:
        self._today = today

    def set_data(self, contacts, deals, today: Optional[date] = None) -> None:
        self._contacts, self._deals = list(contacts or ()), list(deals or ())
        self.stats = ST.compute(self._contacts, self._deals, today or self._today)
        self._draw()

    def refresh(self) -> None:
        self.set_data(self._contacts, self._deals)

    # -- drawing -------------------------------------------------------------
    def _clear(self) -> None:
        while self._col.count():
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                        # hidden first: a detached widget can open as a window of its own
                w.setParent(None)
                w.deleteLater()
        self.tiles = {}

    def _draw(self) -> None:
        s = self.stats
        self._clear()
        if s.is_empty():
            self.summary.setText(i18n.t("Nothing to count yet."))
            self._col.addWidget(C.EmptyState(
                "chart", i18n.t("No history yet"),
                i18n.t("Send a message, move someone's stage, or add a deal. These figures are counted from what Prism stored, never guessed.")))
            self._col.addStretch(1)
            return
        self.summary.setText(i18n.t("Last {n} days · all from your history").format(n=s.days))

        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_3)
        wait = "—" if s.median_reply_days is None else i18n.t("{n} days").format(n=f"{s.median_reply_days:g}")
        for key, name, value in (("reply_rate", i18n.t("Reply rate"), _percent(s.reply_rate)),
                                 ("median_reply", i18n.t("Median time to reply"), wait),
                                 ("pipeline", i18n.t("Open pipeline"), DL.inr(s.open_pipeline)),
                                 ("win_rate", i18n.t("Win rate"), _percent(s.win_rate))):
            tile, col = _card()
            col.addWidget(C.label(name, level="SUPPORT", colour=theme.NEUTRAL[600]))
            figure = C.label(value, level="SECTION", weight=700)
            col.addWidget(figure)
            self.tiles[key] = figure
            row.addWidget(tile, 1)
        holder = QWidget()
        holder.setLayout(row)
        row.setContentsMargins(0, 0, 0, 0)
        self._col.addWidget(holder)

        funnel, fcol = _card(i18n.t("Funnel"))
        top = max(s.contacted, s.replied, s.interested, s.deals, s.won, 1)     # deals need not come from people contacted here
        for name, n in ((i18n.t("Contacted"), s.contacted), (i18n.t("Replied"), s.replied),
                        (i18n.t("Interested"), s.interested), (i18n.t("Deal"), s.deals), (i18n.t("Won"), s.won)):
            line = QHBoxLayout()
            line.setSpacing(theme.SPACE_3)
            label = C.label(name, level="SUPPORT")
            label.setFixedWidth(90)
            line.addWidget(label)
            line.addWidget(_Bar(n / top), 1)
            count = C.label(str(n), level="SUPPORT", weight=600)
            count.setFixedWidth(40)
            count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            line.addWidget(count)
            fcol.addLayout(line)
        self._col.addWidget(funnel)

        lost, lcol = _card(i18n.t("Why deals were lost"))
        if s.lost_reasons:
            most = max(s.lost_reasons.values())
            for reason, n in sorted(s.lost_reasons.items(), key=lambda kv: (-kv[1], kv[0])):
                line = QHBoxLayout()
                line.setSpacing(theme.SPACE_3)
                label = C.label(reason, level="SUPPORT")
                label.setFixedWidth(120)
                line.addWidget(label)
                line.addWidget(_Bar(n / most), 1)
                count = C.label(str(n), level="SUPPORT", weight=600)
                count.setFixedWidth(40)
                count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                line.addWidget(count)
                lcol.addLayout(line)
        else:
            lcol.addWidget(C.label(i18n.t("No deal has been lost in this time."), level="SUPPORT", colour=theme.NEUTRAL[600]))
        self._col.addWidget(lost)
        self._col.addWidget(C.label(
            i18n.t("Reply rate by step needs the sequence engine: Prism records that a message went out, not which touch it was."),
            level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self._col.addStretch(1)
