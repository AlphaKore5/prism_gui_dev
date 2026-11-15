"""The numbered step tabs and the "file added" card of the AlphaKore preview.

Two small pieces that every guided dialog shares (BOQ/BOM's four steps, the
HVAC tender-PDF steps). They draw nothing themselves: every colour comes from
theme.py and the shapes are QSS rules keyed on dynamic properties, so a screen
that uses them cannot drift from the rest of the app.

StepTabs is a progress strip, not a wizard engine. The dialog owns which page
is showing; it tells the strip with `set_current()`, and the strip tells it
when a finished step is clicked (`step_clicked`). A step that has not been
reached yet is never clickable, so the strip cannot skip past a gate.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

import theme
from widgets import controls as C


class _Tab(QFrame):
    clicked = Signal(int)

    def __init__(self, index: int, text: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("stepTab")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(8, 6, 14, 6)
        row.setSpacing(10)
        self.num = QLabel(str(index + 1))
        self.num.setObjectName("stepTabNum")
        self.num.setAlignment(Qt.AlignCenter)
        self.num.setFixedSize(26, 26)
        self.text = QLabel(text)
        self.text.setObjectName("stepTabText")
        row.addWidget(self.num)
        row.addWidget(self.text)
        row.addStretch(1)
        self.set_state("todo")

    def set_state(self, state: str):
        self.setProperty("state", state)
        for w in (self, self.num, self.text):
            w.setProperty("state", state)
            w.style().unpolish(w)
            w.style().polish(w)
        self.setCursor(Qt.PointingHandCursor if state == "done" else Qt.ArrowCursor)
        # What a screen reader says: the number and name alone do not say
        # where the person is.
        self.setAccessibleName(f"Step {self.index + 1}: {self.text.text()} ({state})")

    def mousePressEvent(self, event):
        if self.property("state") == "done":
            self.clicked.emit(self.index)
        super().mousePressEvent(event)


class StepTabs(QWidget):
    """A row of numbered steps. `set_current(i)` marks 0..i-1 done, i active,
    the rest still to come."""

    step_clicked = Signal(int)

    def __init__(self, names: list, parent=None):
        super().__init__(parent)
        self.setObjectName("stepTabs")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        self._tabs: list[_Tab] = []
        for i, name in enumerate(names):
            tab = _Tab(i, name)
            tab.clicked.connect(self.step_clicked)
            self._tabs.append(tab)
            row.addWidget(tab, stretch=1)
        self._current = 0
        self.set_current(0)

    @property
    def current(self) -> int:
        return self._current

    def states(self) -> list:
        return [t.property("state") for t in self._tabs]

    def set_current(self, index: int):
        self._current = max(0, min(index, len(self._tabs) - 1))
        for i, tab in enumerate(self._tabs):
            tab.set_state("done" if i < self._current
                          else "active" if i == self._current else "todo")
            tab.num.setText("✓" if i < self._current else str(i + 1))


class FileCard(QFrame):
    """The big card that says what the person has given Prism so far: an empty
    prompt ("Add your tender PDF") until a file lands, then a green "PDF added"
    card with the file's name and a button to change it.

    With `accept_drops=True` it is also a drop zone: a file dragged onto it is
    handed to `files_dropped` as local paths, nothing else. The owner decides
    what a dropped file means, normally the same thing as the button's own
    file chooser, so a drop can never do more than a click does."""

    files_dropped = Signal(list)

    def __init__(self, empty_title: str, empty_hint: str, added_title: str,
                 add_text: str, change_text: str, on_click=None, parent=None,
                 button_kind: str = "primary", accept_drops: bool = False):
        super().__init__(parent)
        self.setObjectName("fileCard")
        self.setAcceptDrops(accept_drops)
        self.setProperty("dragging", False)
        self._empty = (empty_title, empty_hint)
        self._added_title = added_title
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_5, theme.SPACE_4, theme.SPACE_5,
                               theme.SPACE_4)
        row.setSpacing(theme.SPACE_4)
        self.icon = QLabel()
        self.icon.setObjectName("fileCardIcon")
        self.icon.setFixedSize(46, 46)
        self.icon.setAlignment(Qt.AlignCenter)
        try:
            from widgets import icons
            self.icon.setPixmap(icons.pixmap("file", 20, theme.INK))
        except Exception:                                   # noqa: BLE001
            pass
        row.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("fileCardTitle")
        self.hint = QLabel("")
        self.hint.setObjectName("fileCardHint")
        self.hint.setWordWrap(True)
        col.addWidget(self.title)
        col.addWidget(self.hint)
        row.addLayout(col, stretch=1)
        self._add_text, self._change_text = add_text, change_text
        self.button = C.button(add_text, button_kind, on_click=on_click)
        row.addWidget(self.button)
        self.set_file("")

    def set_file(self, name: str):
        added = bool(name)
        self.setProperty("added", added)
        self.style().unpolish(self)
        self.style().polish(self)
        self.title.setText(self._added_title if added else self._empty[0])
        self.hint.setText(name if added else self._empty[1])
        self.button.setText(self._change_text if added else self._add_text)

    # ── drag and drop ────────────────────────────────────────────────────
    @staticmethod
    def _local_paths(event) -> list:
        md = event.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile()]

    def _set_dragging(self, on: bool):
        self.setProperty("dragging", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event):
        if self._local_paths(event):
            self._set_dragging(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._local_paths(event):
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._set_dragging(False)

    def dropEvent(self, event):
        self._set_dragging(False)
        paths = self._local_paths(event)
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)


class ChoiceCard(QFrame):
    """One of a few big "pick one" cards: an icon tile, a title, a sentence.
    Click it (or press Space/Enter when focused) and it emits `clicked`; the
    owner marks which one is picked with `set_selected`. A card that cannot be
    picked right now carries the reason in its tooltip."""

    clicked = Signal()

    def __init__(self, icon_name: str, title: str, hint: str, parent=None):
        super().__init__(parent)
        self.setObjectName("choiceCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("selected", False)
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        col.setSpacing(theme.SPACE_2)
        tile = QLabel()
        tile.setObjectName("choiceCardIcon")
        tile.setFixedSize(34, 34)
        tile.setAlignment(Qt.AlignCenter)
        try:
            from widgets import icons
            tile.setPixmap(icons.pixmap(icon_name, 16, theme.INK))
        except Exception:                                   # noqa: BLE001
            pass
        self.title = QLabel(title)
        self.title.setObjectName("choiceCardTitle")
        self.title.setWordWrap(True)
        self.hint = QLabel(hint)
        self.hint.setObjectName("choiceCardHint")
        self.hint.setWordWrap(True)
        col.addWidget(tile, alignment=Qt.AlignLeft)
        col.addWidget(self.title)
        col.addWidget(self.hint)
        col.addStretch(1)
        self.setAccessibleName(title)

    def selected(self) -> bool:
        return bool(self.property("selected"))

    def changeEvent(self, event):
        # Qt style sheets do not see an ancestor's :disabled, so say it as a property.
        if event.type() == QEvent.EnabledChange:
            off = not self.isEnabled()
            for w in (self, self.title, self.hint):
                w.setProperty("off", off)
                w.style().unpolish(w)
                w.style().polish(w)
        super().changeEvent(event)

    def set_selected(self, on: bool):
        self.setProperty("selected", bool(on))
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if self.isEnabled() and event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if self.isEnabled() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit()
        else:
            super().keyPressEvent(event)
