"""One box to say what you want — reused by every add-on screen.

The target user is a business owner, not a software user. They should not
have to find a setting, understand a category, or know which box a file goes
in. So every add-on opens the same way the home screen does: one large
prompt, a Speak button, an Add file button, and their starred folders one
click away. Everything else on the screen is either automatic or folded
away behind "More options".

Anything technical that still has to exist (drawing path, units, layer
filters, recipient lists) lives in a collapsed section that a first-time
user never opens.
"""
from __future__ import annotations
import os

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QSizePolicy, QLabel,
    QFileDialog, QMenu, QFrame,
)

import favorites
import i18n
import theme
from widgets import icons
from widgets import controls as C
from widgets.files_panel import kind_label, size_label


def small_button(label: str, icon_name: str, tip: str = "") -> QPushButton:
    btn = QPushButton(label)
    btn.setObjectName("smallBtn")
    btn.setCursor(Qt.PointingHandCursor)
    icons.button_icon(btn, icon_name, 15, theme.TEXT)
    if tip:
        btn.setToolTip(tip)
    return btn


class AskPanel(QWidget):
    """A prompt box + Speak + Add file + Favourites, and a list of chips for
    whatever is attached."""

    speak_clicked = Signal()
    files_added = Signal(list)      # list of absolute paths
    file_removed = Signal(str)      # the absolute path taken back out

    def __init__(self, placeholder: str, parent=None, compact: bool = False):
        super().__init__(parent)
        self._paths: list[str] = []
        # Set by the owner so the file chooser starts where this person last picked.
        self.cfg: dict | None = None
        self.pick_kind = "attach"
        self.pick_filters = "All files (*)"

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.edit = C.PlainPasteTextEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFixedHeight(92)
        self.mic_btn = small_button("Speak", "mic", "Say it instead of typing")
        self.mic_btn.clicked.connect(self.speak_clicked.emit)
        add_btn = small_button("Add file", "paperclip",
                               "Attach a drawing, a list, a brochure — anything")
        add_btn.clicked.connect(self._pick_file)
        self.fav_btn = small_button("Favourites", "folder",
                                    "Your starred files and folders")
        self.fav_btn.clicked.connect(self._show_favourites)
        if compact:
            # The preview's shape: the box, with Speak and Add file beside it.
            top = QHBoxLayout()
            top.setSpacing(8)
            top.addWidget(self.edit, stretch=1)
            side = QVBoxLayout()
            side.setSpacing(4)
            side.addWidget(self.mic_btn)
            side.addWidget(add_btn)
            top.addLayout(side)
            root.addLayout(top)
        else:
            root.addWidget(self.edit)
            row = QHBoxLayout()
            row.addWidget(self.mic_btn)
            row.addWidget(add_btn)
            row.addWidget(self.fav_btn)
            row.addStretch(1)
            root.addLayout(row)

        # Attachments as real rows, not "📎 name   📎 name" in one label.
        # The emoji prefix was the last one left in the widget package: it
        # arrives pre-coloured and pre-weighted from the platform font vendor,
        # so it cannot match the 1.6px line icons beside it — and a run of
        # names in a single wrapped label is unreadable at four files and
        # offers nothing to click. Same controls.FileItem the context rail
        # uses, so an attachment reads identically wherever it appears.
        self.chips = QWidget(self)
        self._chip_layout = QVBoxLayout(self.chips)
        self._chip_layout.setContentsMargins(0, 0, 0, 0)
        self._chip_layout.setSpacing(theme.SPACE_1 + 2)
        self.chips.setVisible(False)
        self.chips.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        root.addWidget(self.chips)

    # ── text ────────────────────────────────────────────────────────────
    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def set_text(self, value: str):
        self.edit.setPlainText(value)

    def append_text(self, value: str):
        existing = self.text()
        self.edit.setPlainText((existing + " " + value).strip())

    def set_recording(self, on: bool):
        self.mic_btn.setText("Stop" if on else "Speak")

    # ── files ───────────────────────────────────────────────────────────
    def _pick_file(self):
        from widgets import file_pick
        paths = file_pick.open_files(self, "Attach files", self.pick_kind, self.pick_filters, self.cfg)
        if paths:
            self.add_paths(paths)

    def _show_favourites(self):
        items = favorites.load()
        menu = QMenu(self)
        if not items:
            act = menu.addAction("No favourites yet — star them on the home screen")
            act.setEnabled(False)
        else:
            for it in items:
                label = it.get("label") or os.path.basename(it["path"])
                act = menu.addAction(label)
                act.triggered.connect(
                    lambda _=False, p=it["path"]: self._add_favourite(p))
        menu.exec(self.fav_btn.mapToGlobal(self.fav_btn.rect().bottomLeft()))

    def _add_favourite(self, path: str):
        # A starred FOLDER is a shelf, not an attachment — open it so the
        # user picks the file they actually mean, rather than silently
        # attaching a whole directory.
        if os.path.isdir(path):
            picked, _ = QFileDialog.getOpenFileNames(
                self, i18n.t("Choose from this folder"), path)
            if picked:
                self.add_paths(picked)
        else:
            self.add_paths([path])

    def add_paths(self, paths: list[str], emit: bool = True):
        # Normalise to an absolute path before comparing and storing. On
        # Windows QFileDialog returns forward-slash paths while os/attach() use
        # backslashes, so a plain string compare let the SAME file in twice —
        # the duplicate chip. normcase folds slash + case for the compare; the
        # stored value stays a real absolute path.
        have = {os.path.normcase(p) for p in self._paths}
        fresh = []
        for p in paths:
            if not p:
                continue
            ap = os.path.abspath(os.path.expanduser(p))
            key = os.path.normcase(ap)
            if key in have:
                continue
            have.add(key)
            fresh.append(ap)
        if not fresh:
            return
        self._paths += fresh
        self._refresh_chips()
        # `emit=False` lets an owner add chips WITHOUT re-triggering its own
        # files_added handler. An owner that absorbs files (classify, then
        # add_paths the results) would otherwise re-enter through the signal
        # and classify — and count templates/images — a second time.
        if emit:
            self.files_added.emit(fresh)

    def paths(self) -> list[str]:
        return list(self._paths)

    def clear_files(self):
        self._paths = []
        self._refresh_chips()

    def remove_path(self, path: str):
        """Take one file back out. There was no way to do this at all — the
        only correction available for a mis-picked file was to close the
        dialog and start again.

        Emits `file_removed` so an owner keeping its own copy of the list
        (Gerber, STEP — each needs the plain path, not a chip) stays in
        sync. Without this the chip vanished but the owner's own list kept
        the file, so Generate ran it anyway — a mis-picked file could never
        actually be taken back out."""
        if path in self._paths:
            self._paths.remove(path)
            self._refresh_chips()
            self.file_removed.emit(path)

    def _refresh_chips(self):
        while self._chip_layout.count():
            item = self._chip_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self._paths:
            self.chips.setVisible(False)
            return
        for path in self._paths:
            att = {"name": os.path.basename(path), "path": path,
                   "kind": "folder" if os.path.isdir(path) else ""}
            drop = C.icon_button("x", i18n.t("Remove this file"),
                                 lambda _=False, p=path: self.remove_path(p))
            drop.setFixedSize(28, 28)
            bits = [b for b in (kind_label(att), size_label(path)) if b]
            row = C.FileItem(att["name"], " · ".join(bits),
                             "folder" if att["kind"] == "folder" else "file",
                             [drop])
            row.setToolTip(path)
            self._chip_layout.addWidget(row)
        self.chips.setVisible(True)


class MoreOptions(QFrame):
    """A section that stays shut until someone wants it.

    Everything a non-technical user must never be confronted with goes in
    here: file paths, units, layer filters, recipient editing. Hidden by
    default, one click to open, and the button says plainly that it is
    optional."""

    def __init__(self, label: str = "More options", parent=None, optional_suffix: bool = True):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.toggle = QPushButton(
            "  " + (i18n.t("{label}  (optional)").format(label=i18n.t(label))
                    if optional_suffix else i18n.t(label)))
        self.toggle.setObjectName("smallBtn")
        self.toggle.setCursor(Qt.PointingHandCursor)
        self.toggle.setCheckable(True)
        icons.button_icon(self.toggle, "chevron-right", 14, theme.NEUTRAL[600])
        self.toggle.clicked.connect(self._toggled)
        root.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(0, 4, 0, 0)
        self.body.setVisible(False)
        root.addWidget(self.body)

    def _toggled(self, checked: bool):
        self.body.setVisible(checked)
        icons.button_icon(self.toggle,
                          "chevron-down" if checked else "chevron-right",
                          14, theme.NEUTRAL[600])

    def add(self, widget):
        self.body_layout.addWidget(widget)

    def add_layout(self, layout):
        self.body_layout.addLayout(layout)
