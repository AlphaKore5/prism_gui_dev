"""A file Prism made, as a card: type icon, name, size, what you can do with it.

Used by the task result cards, the reader dialog and anywhere else a produced
file is named. One card is:

    [icon] name                    size · type      [Open] [Show in folder] [Save as…]
    Convert to  [CSV] [Excel] [PDF] [Word]
    (spreadsheets, reader only)  the first 20 rows x 8 columns

"Convert to" works from the spec Prism stored next to a file it built from the
AI's structured answer (core/filespec.py): local, instant, no AI call. A button
that cannot work stays visible and disabled with the reason as its tooltip, so
a missing file or a file with no stored data never reads as a broken button.
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QMessageBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

import core_bridge as CB
import i18n
import paths
import theme
from widgets import controls as C
from widgets.files_panel import size_label

PREVIEW_ROWS, PREVIEW_COLS = 20, 8
THUMB_W, THUMB_H = 320, 220
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

_SHEET_EXT = (".xlsx", ".csv", ".zip")
_TYPE_WORD = {".xlsx": "Excel", ".csv": "CSV", ".zip": "CSV (several sheets)",
              ".docx": "Word", ".pdf": "PDF", ".md": "Markdown", ".txt": "Text"}
_CONVERT = (("CSV", ".csv"), ("Excel", ".xlsx"), ("PDF", ".pdf"), ("Word", ".docx"))

WHY_MISSING = ("This file is no longer where Prism saved it (moved or deleted), "
               "so it cannot be opened or converted.")
WHY_NO_SPEC = ("Prism only has the finished file, not the data it was built "
               "from, so it cannot convert it exactly.")


def icon_for(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    return "sheet" if ext in _SHEET_EXT else "file-text"


def type_word(path: str) -> str:
    return _TYPE_WORD.get(os.path.splitext(path)[1].lower(), "File")


class SheetPreview(QTableWidget):
    """The first rows and columns of a spreadsheet, read-only."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setObjectName("sheetPreview")
        data = CB.filespec.preview(path, PREVIEW_ROWS, PREVIEW_COLS)
        self.data = data
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setAlternatingRowColors(True)
        self.verticalHeader().setVisible(False)
        cols, rows = data.get("columns", []), data.get("rows", [])
        self.setColumnCount(len(cols))
        self.setRowCount(len(rows))
        self.setHorizontalHeaderLabels(cols)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                self.setItem(r, c, item)
        self.resizeColumnsToContents()
        for c in range(self.columnCount()):
            self.setColumnWidth(c, min(self.columnWidth(c), 240))
        self.setMinimumHeight(140)
        self.setMaximumHeight(280)
        self.setStyleSheet(
            f"QTableWidget#sheetPreview {{ background: {theme.SURFACE};"
            f" border: 1px solid {theme.BORDER}; color: {theme.TEXT};"
            f" gridline-color: {theme.BORDER}; }}")

    def note(self) -> str:
        """"Showing the first 20 of 140 rows" or "" when it is all there."""
        d = self.data
        if not d:
            return ""
        parts = []
        if d.get("rows_total", 0) > len(d.get("rows", [])):
            parts.append(i18n.t("{n} of {total} rows").format(
                n=len(d["rows"]), total=d["rows_total"]))
        if d.get("cols_total", 0) > len(d.get("columns", [])):
            parts.append(i18n.t("{n} of {total} columns").format(
                n=len(d["columns"]), total=d["cols_total"]))
        return (i18n.t("Showing the first") + " " + ", ".join(parts)) if parts else ""


class FileCard(QFrame):
    """See the module docstring. `converted(path)` fires with the new file."""

    converted = Signal(str)

    def __init__(self, path: str, parent=None, preview: bool = False):
        super().__init__(parent)
        self.path = path
        self.setObjectName("fileCard")
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2)
        exists = os.path.isfile(path)
        name = os.path.basename(path)
        detail = " · ".join(p for p in (type_word(path), size_label(path)) if p)
        if not exists:
            detail = i18n.t("File not found")

        self.open_btn = C.button(i18n.t("Open"), "secondary", "external",
                                 small=True, on_click=lambda: paths.open_result(path))
        self.show_btn = C.button(i18n.t("Show in folder"), "secondary", "folder",
                                 small=True, on_click=lambda: paths.reveal_result(path))
        self.save_btn = C.button(i18n.t("Save as…"), "secondary", "download",
                                 small=True, on_click=self._save_as)
        self.buttons = (self.open_btn, self.show_btn, self.save_btn)
        for b in self.buttons:
            b.setEnabled(exists)
            if not exists:
                b.setToolTip(i18n.t(WHY_MISSING))
        self.row = C.FileItem(name, detail, icon_for(path),
                              list(self.buttons), flat=False)
        self.row.setToolTip(path)
        self.row.activated.connect(lambda: exists and paths.open_result(path))
        box.addWidget(self.row)

        self.thumb = self._thumbnail(path) if exists else None
        if self.thumb is not None:
            box.addWidget(self.thumb)

        self.convert_btns: dict[str, object] = {}
        if exists and CB.filespec.has_spec(path) or not exists:
            self._build_convert(box, exists)
        self.status = QLabel("")
        self.status.setObjectName("meta")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        box.addWidget(self.status)

        self.preview = None
        if (preview and exists
                and os.path.splitext(path)[1].lower() in (".xlsx", ".csv")):
            self.preview = SheetPreview(path)
            if self.preview.rowCount():
                box.addWidget(self.preview)
                note = self.preview.note()
                if note:
                    lab = QLabel(note)
                    lab.setObjectName("meta")
                    box.addWidget(lab)
            else:
                self.preview.deleteLater()
                self.preview = None

    @staticmethod
    def _thumbnail(path: str):
        """A small picture of an image file, or None when it is not an image
        or cannot be read (a corrupt file just keeps its plain card)."""
        if os.path.splitext(path)[1].lower() not in _IMAGE_EXT:
            return None
        pix = QPixmap(path)
        if pix.isNull():
            return None
        label = QLabel()
        label.setObjectName("fileThumb")
        label.setPixmap(pix.scaled(THUMB_W, THUMB_H, Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation))
        label.setAlignment(Qt.AlignLeft)
        label.setToolTip(os.path.basename(path))
        return label

    # ── convert ──────────────────────────────────────────────────────────────
    def _build_convert(self, box, exists: bool):
        own = os.path.splitext(self.path)[1].lower()
        ok = set(CB.filespec.convertible_to(self.path)) if exists else set()
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        lab = QLabel(i18n.t("Convert to"))
        lab.setObjectName("meta")
        row.addWidget(lab)
        for word, ext in _CONVERT:
            if ext == own:
                continue
            btn = C.button(word, "secondary", small=True,
                           on_click=lambda _=False, e=ext: self.convert(e))
            if not exists:
                btn.setEnabled(False)
                btn.setToolTip(i18n.t(WHY_MISSING))
            elif ext not in ok:
                btn.setEnabled(False)
                btn.setToolTip(i18n.t(
                    "This document has no table, so it cannot become a "
                    "spreadsheet.") if ext in (".csv", ".xlsx") and ok
                    else i18n.t(WHY_NO_SPEC))
            else:
                btn.setToolTip(i18n.t("Make a {fmt} copy on this computer. "
                                      "Nothing is sent anywhere.").format(fmt=word))
            self.convert_btns[ext] = btn
            row.addWidget(btn)
        row.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(row)
        row.setContentsMargins(theme.SPACE_3, 0, 0, 0)
        box.addWidget(wrap)

    def convert(self, ext: str) -> str:
        """Make the other format next to this file. Returns the new path, or
        "" with the reason on the card."""
        try:
            rec = CB.filespec.convert(self.path, ext)
        except (CB.filespec.FileSpecError, OSError) as e:
            self._say(str(e) or i18n.t("Prism could not convert that file."), bad=True)
            return ""
        self._say(i18n.t("Made {name}").format(name=rec["name"]))
        self.converted.emit(rec["path"])
        return rec["path"]

    # ── save as ──────────────────────────────────────────────────────────────
    def _save_as(self):
        ext = os.path.splitext(self.path)[1]
        dest, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save a copy"), os.path.basename(self.path),
            f"{type_word(self.path)} (*{ext})")
        if dest:
            self.save_to(dest)

    def save_to(self, dest: str) -> bool:
        ext = os.path.splitext(self.path)[1]
        if not os.path.splitext(dest)[1]:
            dest += ext
        try:
            shutil.copyfile(self.path, dest)
            if CB.filespec.has_spec(self.path):
                shutil.copyfile(CB.filespec.spec_path_for(self.path),
                                CB.filespec.spec_path_for(dest))
        except OSError as e:
            self._say(i18n.t("Prism could not save that copy ({why}).").format(
                why=e.strerror or e), bad=True)
            return False
        self._say(i18n.t("Saved {name}").format(name=os.path.basename(dest)))
        return True

    def _say(self, text: str, bad: bool = False):
        self.status.setText(text)
        self.status.setStyleSheet(
            f"color: {theme.ERR_INK if bad else theme.MUTE};"
            " background: transparent;")
        self.status.setVisible(True)


class FileCards(QWidget):
    """A column of FileCards for a list of paths; a converted file is added as
    its own card below, so the result of "Convert to" is visible at once."""

    def __init__(self, file_paths: list[str], parent=None, preview: bool = False):
        super().__init__(parent)
        self._preview = preview
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(theme.SPACE_2)
        self.cards: list[FileCard] = []
        for p in file_paths:
            self.add(p)

    def add(self, path: str) -> FileCard:
        for c in self.cards:
            if c.path == path:
                return c
        card = FileCard(path, self, preview=self._preview)
        card.converted.connect(self.add)
        self.box.addWidget(card)
        self.cards.append(card)
        return card
