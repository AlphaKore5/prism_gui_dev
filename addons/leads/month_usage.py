"""This month's promise, as the customer reads it: "Emails 120/200, Numbers 40/100, resets 1 Dec",
with a percent bar for each.

The numbers come from the licence server's /v1/leads/status ("month"), through
prospector.gateway.month(); this module counts nothing itself and shows no money. It says nothing
at all when the server does not enforce a monthly limit.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

import i18n
import theme
from widgets import controls as C


def percent(used, limit) -> int:
    """Whole percent used, 0 to 100 (a limit of 0 reads as full)."""
    try:
        used, limit = int(used), int(limit)
    except (TypeError, ValueError):
        return 0
    if limit <= 0:
        return 100
    return max(0, min(100, round(100 * used / limit)))


def usage_line(month: dict | None) -> str:
    """"Emails 120/200, Numbers 40/100, resets 1 Dec" — or '' with nothing to say."""
    if not month:
        return ""
    return i18n.t("Emails {eu}/{el}, Numbers {nu}/{nl}, resets {d}").format(
        eu=int(month.get("emails_used") or 0), el=int(month.get("emails_limit") or 0),
        nu=int(month.get("numbers_used") or 0), nl=int(month.get("numbers_limit") or 0),
        d=month.get("resets_label") or "")


class MonthUsage(QWidget):
    """The line and its two bars. Hidden until there is a month to show."""

    def __init__(self, parent=None):
        super().__init__(parent)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        self.line = C.label("", level="META", wrap=True)
        col.addWidget(self.line)
        self.bars = {}
        self.percents = {}
        for key, name in (("emails", i18n.t("Emails")), ("numbers", i18n.t("Numbers"))):
            row = QHBoxLayout()
            row.setSpacing(theme.SPACE_2)
            title = C.label(name, level="META")
            title.setMinimumWidth(64)
            bar = C.ProgressBar(0.0)
            pct = C.label("0%", level="META")
            pct.setMinimumWidth(36)
            row.addWidget(title)
            row.addWidget(bar, 1)
            row.addWidget(pct)
            col.addLayout(row)
            self.bars[key], self.percents[key] = bar, pct
        self.setVisible(False)

    def set_month(self, month: dict | None) -> None:
        if not month or not month.get("guard", True):
            self.setVisible(False)
            return
        self.line.setText(usage_line(month))
        for key in ("emails", "numbers"):
            p = percent(month.get(key + "_used"), month.get(key + "_limit"))
            self.bars[key].set_fraction(p / 100)
            self.percents[key].setText("%d%%" % p)
        self.setVisible(True)
