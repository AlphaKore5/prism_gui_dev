"""A search result as one calm row — the look drafted in "Prism CRM: interface mockups" (3 Nov 2026).

Avatar, then "Name · Company" over one line of why this person or company is worth a look, then a few quiet pills and one to three buttons:
the first (black) is the thing to do. A hairline between rows, no grid, no column headings. People and Companies both draw their results with
this, so the two screens read as one product.

This file knows nothing about people or companies: a caller hands it text, pills and what each button does. (`RowSpec` below is that hand-over.)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

import theme

# A pill's two colours by what it says. "outline" is a state rather than a finding: no fill.
TONES = {
    "ok":    (theme.OK_INK, theme.OK_BG),
    "warn":  (theme.WARN_INK, theme.WARN_BG),
    "err":   (theme.ERR_INK, theme.ERR_BG),
    "info":  (theme.INFO_INK, theme.INFO_BG),
    "quiet": (theme.NEUTRAL[700], theme.NEUTRAL[200]),
}


@dataclass
class RowSpec:
    """Everything one row shows. `actions` are (label, is_primary, what to call)."""
    key: int
    name: str
    company: str = ""
    subline: str = ""
    pills: list = field(default_factory=list)          # (text, tone)
    actions: list = field(default_factory=list)        # (label, primary, callable)
    checked: bool = False
    tooltip: str = ""
    checkable: bool = True                             # False: no tick box (a list nobody bulk-acts on)


def initials(name: str) -> str:
    parts = [p for p in (name or "").replace(".", " ").split() if p[:1].isalpha()]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[1][0] if len(parts) > 1 else "")).upper()


def avatar(name: str, size: int = 34) -> QLabel:
    lab = QLabel(initials(name))
    lab.setFixedSize(size, size)
    lab.setAlignment(Qt.AlignCenter)
    lab.setStyleSheet(
        f"QLabel{{color:#ffffff;background:{theme.INK};"
        f"border-radius:{size // 2}px;font-weight:500;font-size:{max(11, size // 3)}px;}}")
    return lab


def pill(text: str, tone: str = "quiet") -> QLabel:
    """A pill. R_CHIP, not a huge radius: Qt drops a radius over half the height and draws square corners."""
    if tone != "outline":
        # The preview's `.st`: mono caps with a square before the word (the shared Pill; the words stay as given).
        from widgets import controls as C
        return C.Pill(text, {"ok": "st_ok", "warn": "st_warn", "err": "st_err"}.get(tone, "st_neutral"))
    lab = QLabel(text)
    f = lab.font()
    f.setCapitalization(QFont.AllUppercase)
    lab.setFont(f)
    lab.setStyleSheet(
        f"QLabel{{color:{theme.TEXT};background:transparent;border:1px solid {theme.BORDER};"
        f"border-radius:7px;padding:5px 9px;font-family:{theme.FONT_MONO_STACK};font-size:11px;font-weight:500;}}")
    lab.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lab


def button(text: str, primary: bool, on_click: Optional[Callable] = None) -> QPushButton:
    """A row's button: small (28px, the least a click target may be), black when it is the thing to do, outlined when it is not.
    The shared C.button has no small black variant on purpose; a row of results is where one is wanted."""
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    b.setFixedHeight(28)
    if primary:
        b.setStyleSheet(
            f"QPushButton{{background:{theme.ACCENT};color:#ffffff;border:1px solid {theme.ACCENT};border-radius:14px;"
            f"padding:0 14px;min-height:26px;max-height:26px;font-size:13px;font-weight:500;}}"
            f"QPushButton:hover{{background:{theme.ACCENT_2};}}")
    else:
        b.setStyleSheet(
            f"QPushButton{{background:{theme.WELL};color:{theme.INK};border:1px solid {theme.HAIRLINE};border-radius:14px;"
            f"padding:0 14px;min-height:26px;max-height:26px;font-size:13px;font-weight:500;}}"
            f"QPushButton:hover{{background:{theme.CARD};border-color:{theme.BORDER};}}")
    if on_click is not None:
        b.clicked.connect(on_click)
    return b


class _Elided(QLabel):
    """A label that ends in … instead of pushing its row wider, and gives its full text as a tooltip when it had to."""

    def __init__(self, text: str, css: str, parent=None):
        super().__init__(parent)
        self._full = text or ""
        self.setStyleSheet(css)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        # Not elided here: a child widget is 100px wide until a layout has placed it, so eliding now would cut every
        # long name to ~100px before the row had any say. resizeEvent elides once the real width is known.
        self.setText(self._full)

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):                                         # noqa: N802
        """The width of the WHOLE text, never of what is showing now. A label asked for the width of its
        elided text is given exactly that, shows the same elision, and is stuck short for good: a row built
        while the list was narrow kept a name like "Gujar…" after the list widened."""
        hint = super().sizeHint()
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._full) + 2 * self.margin() + 2, hint.height())

    def minimumSizeHint(self):                                  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())     # it can always shrink: that is what eliding is for

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _refit(self):
        width = self.width()
        if width <= 0:
            self.setText(self._full)
            return
        shown = QFontMetrics(self.font()).elidedText(self._full, Qt.ElideRight, width)
        self.setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class ResultRow(QFrame):
    """One result. Click anywhere that is not a button or the tick to open it."""

    clicked = Signal(int)
    toggled = Signal(int, bool)

    def __init__(self, spec: RowSpec, parent=None):
        super().__init__(parent)
        self.key = spec.key
        self.spec = spec
        self._last = False
        self._current = False
        self.setObjectName("resultRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        if spec.tooltip:
            self.setToolTip(spec.tooltip)
        self._style()

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_1, 10, theme.SPACE_1, 10)
        row.setSpacing(12)

        # Parented at once: setVisible(True) on a widget with no parent makes it a window of its own, and every row of
        # People and Companies flashed a 29x21 box on screen while it waited to be put in the row.
        self.check = QCheckBox(self)
        self.check.setChecked(spec.checked)
        self.check.setStyleSheet("QCheckBox{border:none;background:transparent;}")
        self.check.toggled.connect(lambda on: self.toggled.emit(self.key, on))
        self.check.setVisible(spec.checkable)
        row.addWidget(self.check, alignment=Qt.AlignVCenter)
        row.addWidget(avatar(spec.name), alignment=Qt.AlignVCenter)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(5)
        self.name = _Elided(spec.name, f"color:{theme.TEXT};font-size:14px;font-weight:500;background:transparent;")
        self.name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        head.addWidget(self.name)
        self.company = None
        if spec.company:
            self.company = _Elided("· " + spec.company, f"color:{theme.NEUTRAL[600]};font-size:14px;background:transparent;")
            head.addWidget(self.company, stretch=1)
        else:
            head.addStretch(1)
        text.addLayout(head)
        self.subline = None
        if spec.subline:
            self.subline = _Elided(spec.subline, f"color:{theme.NEUTRAL[600]};font-size:12px;background:transparent;")
            text.addWidget(self.subline)
        row.addLayout(text, stretch=1)

        self.pills = []
        for label, tone in spec.pills:
            p = pill(label, tone)
            self.pills.append(p)
            row.addWidget(p, alignment=Qt.AlignVCenter)

        self.buttons = []
        for label, primary, call in spec.actions:
            b = button(label, primary, call)
            self.buttons.append(b)
            row.addWidget(b, alignment=Qt.AlignVCenter)

    # -- look ----------------------------------------------------------------
    def _style(self):
        rule = "none" if self._last else f"1px solid {theme.HAIRLINE}"
        ground = "background:rgba(9, 9, 11, 0.06);" if self._current else "background:transparent;"
        self.setStyleSheet(
            f"QFrame#resultRow{{{ground}border:none;border-bottom:{rule};}}"
            f"QFrame#resultRow:hover{{background:{theme.WELL};}}")

    def set_last(self, last: bool):
        self._last = last
        self._style()

    def set_current(self, current: bool):
        """The row whose profile is open: a faint accent ground, as the table marks it."""
        self._current = current
        self._style()

    def set_checked(self, on: bool):
        self.check.blockSignals(True)
        self.check.setChecked(on)
        self.check.blockSignals(False)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mousePressEvent(event)


class ViewToggle(QFrame):
    """Two or more views side by side, one lit: the same small segmented control the People toolbar has. `changed` says which key was picked."""

    changed = Signal(str)

    def __init__(self, choices, current: str, parent=None):
        super().__init__(parent)
        self.setObjectName("viewSeg")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#viewSeg{{background:#EFEEEA;border:none;border-radius:16px;}}"
            f"QFrame#viewSeg QPushButton{{background:transparent;border:none;color:{theme.NEUTRAL[600]};padding:3px 14px;"
            f"min-height:22px;font-size:13px;font-weight:500;border-radius:14px;}}"
            f"QFrame#viewSeg QPushButton:hover{{color:{theme.TEXT};}}"
            f"QFrame#viewSeg QPushButton:checked{{background:{theme.CARD};color:{theme.INK};}}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self._buttons = {}
        for key, label in choices:
            b = QPushButton(label)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self._pick(k))
            self._buttons[key] = b
            lay.addWidget(b)
        self.set_current(current)

    def _pick(self, key: str):
        self.set_current(key)
        self.changed.emit(key)

    def set_current(self, key: str):
        for k, b in self._buttons.items():
            b.setChecked(k == key)


class ResultList(QFrame):
    """The card the rows sit in. Same small surface as the grid it replaces: clear(), add_all(), count()."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultList")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#resultList{{background:{theme.CARD};border:none;}}")
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(theme.SPACE_4, theme.SPACE_1, theme.SPACE_4, theme.SPACE_1)
        self._col.setSpacing(0)
        self._rows: list = []

    def clear(self):
        while self._col.count():
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                      # hidden first: a detached widget a queued show reaches opens as a window of its own
                w.setParent(None)
                w.deleteLater()
        self._rows = []

    def add_all(self, rows):
        rows = list(rows)
        for r in rows:
            self._col.addWidget(r)
            self._rows.append(r)
        for i, r in enumerate(rows):
            if hasattr(r, "set_last"):
                r.set_last(i == len(rows) - 1)

    def count(self) -> int:
        return len(self._rows)

    def rows(self) -> list:
        return list(self._rows)
