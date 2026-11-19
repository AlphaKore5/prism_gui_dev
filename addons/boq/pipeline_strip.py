"""The road a BOQ takes, drawn as a row of steps (addons/boq/route.py says which).

Each step is a small tile: a state mark, its name, and who does it (this
computer, Prism AI, or you). Under the row, ONE line says what the chosen
step produced, whether it ran locally or used Prism AI, and why it failed or
was skipped when it did. A "Details" button opens that step's own screen.

The widget only displays. BoqDialog tells it what happened.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

import i18n
import theme
from widgets import controls as C
from addons.boq import route

_MARK = {route.WAITING: "○", route.RUNNING: "◔", route.DONE: "✓",
         route.NEEDS_YOU: "●", route.SKIPPED: "–", route.FAILED: "!"}
_COLOUR = {route.WAITING: theme.NEUTRAL[500], route.RUNNING: theme.INFO_INK,
           route.DONE: theme.OK_INK, route.NEEDS_YOU: theme.WARN_INK,
           route.SKIPPED: theme.NEUTRAL[500], route.FAILED: theme.ERR_INK}
_STATE_WORDS = {route.WAITING: "Waiting", route.RUNNING: "Working", route.DONE: "Done",
                route.NEEDS_YOU: "Needs you", route.SKIPPED: "Skipped",
                route.FAILED: "Did not work"}


class _Tile(QFrame):
    """One step as a small pill: a state mark and a short name. The state
    words (Done / Needs you...) live in the tooltip and in the line under the
    row, so the whole road fits on one thin line."""
    clicked = Signal(str)

    def __init__(self, stage: route.Stage, number: int, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("pipeTile")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_2, 0, theme.SPACE_2, 0)
        row.setSpacing(4)
        self.mark = QLabel("")
        self.name = QLabel(i18n.t(route.SHORT.get(stage.key, stage.label)))
        self.name.setToolTip(i18n.t(stage.label))
        row.addWidget(self.mark)
        row.addWidget(self.name)
        row.addStretch(1)
        self.setFixedHeight(28)
        self.set_state(route.WAITING, False)

    def set_state(self, state: str, selected: bool):
        self._state = state
        self.mark.setText(_MARK[state])
        self.mark.setStyleSheet(f"font-size: 12px; font-weight: 700; color: {_COLOUR[state]};"
                                " background: transparent;")
        self.name.setStyleSheet(
            f"font-size: 12px; background: transparent; font-weight: {600 if selected else 500};"
            f" color: {theme.INK if state in (route.NEEDS_YOU, route.RUNNING, route.FAILED) or selected else theme.NEUTRAL[600]};")
        border = theme.INK if selected else theme.HAIRLINE
        bg = theme.CANVAS if selected else theme.CARD
        self.setStyleSheet(
            f"#pipeTile {{ background: {bg}; border: 1px solid {border};"
            f" border-radius: 14px; }}")
        self.setToolTip(f"{i18n.t(_STATE_WORDS[state])}: {i18n.t(self.stage.label)}. "
                        f"{i18n.t(route.where_words(self.stage.where))}")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.stage.key)
        super().mousePressEvent(event)


class PipelineStrip(QWidget):
    detail_requested = Signal(str)       # the step key whose own screen to open

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stages: list[route.Stage] = []
        self._tiles: dict[str, _Tile] = {}
        self._state: dict[str, str] = {}
        self._line: dict[str, str] = {}
        self._selected = ""
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)
        self._row = QHBoxLayout()
        self._row.setSpacing(theme.SPACE_2)
        col.addLayout(self._row)
        line_row = QHBoxLayout()
        line_row.setSpacing(theme.SPACE_2)
        self.line = C.label("", level="SUPPORT", wrap=True)
        self.line.setMinimumHeight(18)
        line_row.addWidget(self.line, stretch=1)
        self.detail_btn = QPushButton(i18n.t("Open this step"))
        self.detail_btn.setObjectName("linkBtn")
        self.detail_btn.setCursor(Qt.PointingHandCursor)
        self.detail_btn.clicked.connect(lambda: self.detail_requested.emit(self._selected))
        self.detail_btn.setVisible(False)
        line_row.addWidget(self.detail_btn)
        col.addLayout(line_row)

    # ── what the screen can ask ─────────────────────────────────────────
    def keys(self) -> list[str]:
        return [s.key for s in self._stages]

    def state(self, key: str) -> str:
        return self._state.get(key, route.WAITING)

    def line_of(self, key: str) -> str:
        return self._line.get(key, "")

    def selected(self) -> str:
        return self._selected

    # ── what the dialog tells it ────────────────────────────────────────
    def set_route(self, stages: list[route.Stage]):
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                 # gone now, not at the next event-loop turn
                w.setParent(None)
                w.deleteLater()
        self._stages = list(stages)
        self._tiles = {}
        self._state = {s.key: route.WAITING for s in stages}
        self._line = {}
        for i, st in enumerate(stages, 1):
            t = _Tile(st, i)
            t.clicked.connect(self.select)
            self._tiles[st.key] = t
            self._row.addWidget(t, stretch=1)
        self._selected = stages[0].key if stages else ""
        self._refresh()

    def set_stage(self, key: str, state: str, line: str = ""):
        if key not in self._state:
            return
        self._state[key] = state
        self._line[key] = line
        if state in (route.RUNNING, route.NEEDS_YOU, route.FAILED):
            self._selected = key          # follow the step that wants attention
        self._refresh()

    def select(self, key: str):
        if key in self._state:
            self._selected = key
            self._refresh()

    def _refresh(self):
        for key, tile in self._tiles.items():
            tile.set_state(self._state[key], key == self._selected)
        st = next((s for s in self._stages if s.key == self._selected), None)
        if st is None:
            self.line.setText("")
            self.detail_btn.setVisible(False)
            return
        # A step's own description already says who does it; a result line does not.
        said = (f"{i18n.t(route.where_words(st.where))}: {self._line[st.key]}"
                if self._line.get(st.key) else i18n.t(st.detail))
        self.line.setText(said)
        self.detail_btn.setVisible(st.key in ("read", "scale", "layers", "measure", "tags", "drawing", "check", "write", "prices"))
