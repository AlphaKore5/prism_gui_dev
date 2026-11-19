"""Show any file INSIDE Prism, instead of handing it to whatever program the
operating system has registered for it.

One dialog for every produced or attached file: spreadsheets and CSV as a
sortable, filterable table, Word and Markdown and text as readable text, PDF
pages as pictures (zoom, page by page), images and DXF drawings as pictures,
and anything else as a small card with its name, size and type.

The file is read on a worker (`_ReadWorker`), so a big file never freezes the
window, and treated as data (see viewer_data.py): nothing in it is executed
and no HTML from it is rendered. "Open in another app" is the one deliberately
secondary button that leaves Prism; it goes through paths.open_in_other_app,
the only place in the product that launches the OS opener.

Never import this module from a widget at module scope (tests/test_layering);
use `viewer.open_file(path, parent)`.
"""
from __future__ import annotations

import os
import shutil

from PySide6.QtCore import (QAbstractTableModel, QModelIndex, QRegularExpression,
                            QSortFilterProxyModel, Qt, Signal)
from PySide6.QtGui import QImage, QPixmap, QTextCharFormat, QTextCursor, QFont
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QScrollArea, QTabWidget, QTableView, QTextBrowser, QTextEdit, QVBoxLayout,
    QWidget, QAbstractItemView,
)

import i18n
import paths
import theme
import viewer
import viewer_data as VD
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets.markdown import render_markdown
from workers import _Worker

_KIND_WORD = {
    "image": "Image", "pdf": "PDF", "docx": "Word document", "xlsx": "Excel workbook",
    "csv": "Table (CSV)", "markdown": "Markdown", "text": "Text", "dxf": "CAD drawing (DXF)",
    "pptx": "PowerPoint deck", "video": "Video", "audio": "Audio", "other": "File",
    "folder": "Folder",
}


def kind_word(kind: str) -> str:
    return i18n.t(_KIND_WORD.get(kind, "File"))


def size_text(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return ""


class _ReadWorker(_Worker):
    """Reads the file off the UI thread. Images are decoded here too."""

    done = Signal(object)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        data = VD.read(self._path)
        try:
            if not data["error"]:
                if data["kind"] == "image":
                    img = QImage(self._path)
                    if img.isNull():
                        data["error"] = i18n.t("This picture could not be read.")
                    else:
                        data["qimage"] = img
                elif data["kind"] == "dxf" and data.get("png"):
                    img = QImage.fromData(data["png"])
                    data["qimage"] = img
        except Exception as e:                            # noqa: BLE001
            data["error"] = VD.friendly_error(data["kind"], e)
        self.done.emit(data)


class _PageWorker(_Worker):
    """Draws one PDF page."""

    done = Signal(int, object)      # page index, QImage or None
    failed = Signal(str)

    def __init__(self, path: str, index: int, zoom: float, parent=None):
        super().__init__(parent)
        self._args = (path, index, zoom)

    def run(self):
        try:
            w, h, raw = VD.render_pdf_page(*self._args)
            img = QImage(raw, w, h, w * 4, QImage.Format_RGBA8888).copy()
            self.done.emit(self._args[1], img)
        except Exception as e:                            # noqa: BLE001
            self.failed.emit(VD.friendly_error("pdf", e))


# ── table model: lets 2,000 x 60 cells sort and filter without 120,000 items ──
def _number(text: str):
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


class _TableModel(QAbstractTableModel):
    def __init__(self, columns, rows, parent=None):
        super().__init__(parent)
        self.columns, self.rows = columns, rows

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        text = self.rows[index.row()][index.column()]
        if role == Qt.DisplayRole:
            return text
        if role == Qt.ToolTipRole:
            return text
        if role == Qt.UserRole:
            num = _number(text)
            return num if num is not None else text.lower()
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole:
            return self.columns[section] if orientation == Qt.Horizontal else section + 1
        return None


class _SheetView(QWidget):
    def __init__(self, sheet: dict, parent=None):
        super().__init__(parent)
        self.sheet = sheet
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2)
        self.model = _TableModel(sheet["columns"], sheet["rows"], self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.model)
        self.proxy.setSortRole(Qt.UserRole)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(-1, Qt.AscendingOrder)      # file order until a header is clicked
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.resizeColumnsToContents()
        for c in range(len(sheet["columns"])):
            self.table.setColumnWidth(c, min(max(self.table.columnWidth(c), 60), 260))
        box.addWidget(self.table, stretch=1)
        self.note = QLabel(self._note())
        self.note.setObjectName("meta")
        self.note.setWordWrap(True)
        box.addWidget(self.note)

    def _note(self) -> str:
        s = self.sheet
        shown = len(s["rows"])
        parts = []
        if s.get("truncated"):
            parts.append(i18n.t("Showing the first {n} rows. The file has more; "
                                "Save as… keeps the whole file.").format(n=f"{shown:,}"))
        else:
            parts.append(i18n.t("{n} rows.").format(n=f"{shown:,}"))
        if s.get("cols_cut"):
            parts.append(i18n.t("Only the first {n} columns are shown.").format(n=VD.MAX_COLS))
        return " ".join(parts)

    def set_filter(self, text: str):
        self.proxy.setFilterRegularExpression(
            QRegularExpression(QRegularExpression.escape(text),
                               QRegularExpression.CaseInsensitiveOption))
        if text:
            self.note.setText(i18n.t("{n} of {total} rows match").format(
                n=self.proxy.rowCount(), total=len(self.sheet["rows"])))
        else:
            self.note.setText(self._note())

    def as_text(self) -> str:
        head = "\t".join(self.sheet["columns"])
        return "\n".join([head] + ["\t".join(r) for r in self.sheet["rows"]])


class _PictureView(QScrollArea):
    """A picture with zoom. `source` is a QImage."""

    def __init__(self, image: QImage, parent=None):
        super().__init__(parent)
        self.image, self.zoom = image, 1.0
        self.label = QLabel()
        self.label.setAlignment(Qt.AlignCenter)
        self.setWidget(self.label)
        self.setWidgetResizable(False)
        self.setAlignment(Qt.AlignCenter)
        w = max(image.width(), 1)
        self.zoom = min(1.0, 820 / w)
        self._apply()

    def _apply(self):
        if self.image.isNull():
            return
        pix = QPixmap.fromImage(self.image).scaled(
            int(self.image.width() * self.zoom), int(self.image.height() * self.zoom),
            Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label.setPixmap(pix)
        self.label.resize(pix.size())

    def set_zoom(self, z: float):
        self.zoom = max(0.1, min(z, 6.0))
        self._apply()

    def set_image(self, image: QImage):
        self.image = image
        self._apply()


class FileViewer(PrismDialog):
    """See the module docstring."""

    def __init__(self, path: str, parent=None, kind: str = ""):
        self.path = path
        self.kind = kind or VD.classify(path)
        super().__init__(os.path.basename(path.rstrip("/\\")) or path,
                         " · ".join(p for p in (kind_word(self.kind),
                                                size_text(VD.size_of(path))) if p),
                         icon="file", parent=parent)
        self.resize(900, 680)
        self.setMinimumSize(520, 380)
        self.data: dict = {}
        self.content: QWidget | None = None
        self.search: QLineEdit | None = None
        self._page = 0
        self._pages = 0
        self._pdf_zoom = 1.0
        self._page_worker = None

        self.status = QLabel(i18n.t("Reading the file…"))
        self.status.setObjectName("meta")
        self.status.setAlignment(Qt.AlignCenter)
        self.body.addWidget(self.status, stretch=1)
        self.bar = QHBoxLayout()
        self.bar.setSpacing(theme.SPACE_2)
        self.body.insertLayout(0, self.bar)

        self.copy_btn = self.button(i18n.t("Copy"), "secondary", "copy", small=True,
                                    on_click=self._copy)
        self.save_btn = self.button(i18n.t("Save as…"), "secondary", "download",
                                    small=True, on_click=self._save_as)
        self.reveal_btn = self.button(i18n.t("Show in file manager"), "secondary",
                                      "folder", small=True,
                                      on_click=lambda: paths.reveal_result(self.path))
        self.other_btn = self.button(
            i18n.t("Open in another app"), "secondary", "external", small=True,
            on_click=lambda: paths.open_in_other_app(self.path),
            tooltip=i18n.t("Leaves Prism: your computer opens the file in whatever "
                           "program it uses for this kind of file."))
        for b in (self.copy_btn, self.save_btn, self.reveal_btn, self.other_btn):
            self.footer.add_utility(b)
        self.footer.set_primary(self.button(i18n.t("Close"), "primary",
                                            on_click=self.accept))
        self._set_enabled(False, i18n.t("Still reading the file."))

        self._worker = _ReadWorker(path, self)
        self._worker.done.connect(self._loaded)
        self._worker.start()

    # ── enabling, with the reason when off ───────────────────────────────────
    def _set_enabled(self, loaded: bool, why: str = ""):
        exists = os.path.isfile(self.path)
        gone = i18n.t("This file is no longer where Prism saved it.")
        for b, ok in ((self.save_btn, exists), (self.reveal_btn, os.path.exists(self.path)),
                      (self.other_btn, os.path.exists(self.path))):
            b.setEnabled(ok)
            if not ok:
                b.setToolTip(gone)
        if self.copy_btn.isEnabled() != loaded:
            self.copy_btn.setEnabled(loaded)
        self.copy_btn.setToolTip(
            "" if loaded else (why or i18n.t("There is nothing to copy from this file.")))

    # ── building the view once the worker is done ────────────────────────────
    def _loaded(self, data: dict):
        self.data = data
        self.status.setVisible(False)
        if data["error"]:
            self._info(data["error"], bad=True)
            self._set_enabled(False, i18n.t("There is nothing to copy: the file could not be read."))
            return
        kind = data["kind"]
        build = {"csv": self._build_tables, "xlsx": self._build_tables,
                 "text": self._build_text, "markdown": self._build_markdown,
                 "docx": self._build_docx, "pptx": self._build_pptx,
                 "pdf": self._build_pdf, "image": self._build_picture,
                 "dxf": self._build_picture}.get(kind)
        if build is None:
            self._build_card()
            return
        build(data)
        self._set_enabled(kind not in ("pdf", "image", "dxf"),
                          i18n.t("A picture or PDF page has no text to copy."))

    def _add(self, widget: QWidget):
        self.content = widget
        self.body.addWidget(widget, stretch=1)

    def _info(self, text: str, bad: bool = False):
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setAlignment(Qt.AlignCenter)
        lab.setStyleSheet(f"color: {theme.ERR_INK if bad else theme.TEXT};")
        self._add(lab)

    def _search_row(self, edit, placeholder: str, on_text=None):
        """A search box with Next / Previous that works on `edit`'s find()."""
        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setClearButtonEnabled(True)
        self.bar.addWidget(self.search, stretch=1)
        if on_text is None:
            nxt = self.button(i18n.t("Next"), "secondary", small=True,
                              on_click=lambda: self._find(edit, False))
            prv = self.button(i18n.t("Previous"), "secondary", small=True,
                              on_click=lambda: self._find(edit, True))
            self.bar.addWidget(prv)
            self.bar.addWidget(nxt)
            self.search.returnPressed.connect(lambda: self._find(edit, False))
            self.search.textChanged.connect(lambda _t: self._find(edit, False, restart=True))
        else:
            self.search.textChanged.connect(on_text)

    def _find(self, edit, backward: bool, restart: bool = False):
        text = self.search.text()
        if not text:
            return
        from PySide6.QtGui import QTextDocument
        flags = QTextDocument.FindBackward if backward else QTextDocument.FindFlag(0)
        if restart:
            cur = edit.textCursor()
            cur.setPosition(cur.selectionStart())
            edit.setTextCursor(cur)
        if not edit.find(text, flags):
            cur = edit.textCursor()
            cur.movePosition(QTextCursor.End if backward else QTextCursor.Start)
            edit.setTextCursor(cur)
            edit.find(text, flags)

    # tables
    def _build_tables(self, data):
        sheets = data["sheets"]
        if not sheets or all(not s["columns"] for s in sheets):
            self._info(i18n.t("This file has no rows to show."))
            return
        views = [_SheetView(s) for s in sheets]
        self._sheet_views = views
        if len(views) == 1:
            self._add(views[0])
        else:
            tabs = QTabWidget()
            for s, v in zip(sheets, views):
                tabs.addTab(v, s["name"])
            self._tabs = tabs
            self._add(tabs)
        self._search_row(None, i18n.t("Filter rows…"),
                         on_text=lambda t: [v.set_filter(t) for v in views])

    def _current_sheet(self):
        tabs = getattr(self, "_tabs", None)
        if tabs is not None and self.content is tabs:
            return tabs.currentWidget()
        return self._sheet_views[0]

    # text
    def _build_text(self, data):
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        edit.setStyleSheet(theme.type_css("MONO", theme.TEXT))
        edit.setPlainText(data["text"])
        self._add(edit)
        self._search_row(edit, i18n.t("Find in this file…"))
        if data.get("truncated"):
            self._cut_note()

    def _cut_note(self):
        lab = QLabel(i18n.t("Only the first 2 MB are shown. Save as… keeps the whole file."))
        lab.setObjectName("meta")
        self.body.addWidget(lab)

    def _build_markdown(self, data):
        view = QTextBrowser()
        view.setOpenLinks(False)
        view.setOpenExternalLinks(False)
        view.setStyleSheet(theme.type_css("BODY", theme.TEXT))
        view.setHtml(render_markdown(data["text"]))       # escapes everything
        view.anchorClicked.connect(lambda u: viewer.open_link(u.toString(), self))
        self._add(view)
        self._search_row(view, i18n.t("Find in this file…"))
        if data.get("truncated"):
            self._cut_note()

    # word
    def _build_docx(self, data):
        view = QTextEdit()
        view.setReadOnly(True)
        view.setAcceptRichText(False)
        cur = QTextCursor(view.document())
        base = view.font()
        for block in data["blocks"] or [("para", i18n.t("This document is empty."))]:
            fmt = QTextCharFormat()
            if block[0] == "heading":
                fmt.setFontWeight(QFont.Bold)
                fmt.setFontPointSize(base.pointSizeF() * max(1.0, 1.9 - 0.2 * block[1]))
                cur.insertText(block[2] + "\n", fmt)
            elif block[0] in ("para", "bullet"):
                cur.insertText(("•  " if block[0] == "bullet" else "") + block[1] + "\n", fmt)
            else:
                rows = block[1]
                table = cur.insertTable(len(rows), max(len(r) for r in rows))
                for r, row in enumerate(rows):
                    for c, text in enumerate(row):
                        table.cellAt(r, c).firstCursorPosition().insertText(text)
                cur.movePosition(QTextCursor.End)
                cur.insertText("\n")
        view.moveCursor(QTextCursor.Start)
        self._add(view)
        self._search_row(view, i18n.t("Find in this file…"))
        if data.get("truncated"):
            lab = QLabel(i18n.t("This document is long; only the first part is shown."))
            lab.setObjectName("meta")
            self.body.addWidget(lab)

    def _build_pptx(self, data):
        tabs = QTabWidget()
        for i, lines in enumerate(data["slides"], 1):
            page = QPlainTextEdit("\n".join(lines) or i18n.t("(No text on this slide.)"))
            page.setReadOnly(True)
            tabs.addTab(page, i18n.t("Slide {n}").format(n=i))
        if not tabs.count():
            self._info(i18n.t("This presentation has no slides."))
            return
        self._tabs_text = tabs
        self._add(tabs)

    # pdf
    def _build_pdf(self, data):
        self._pages = data["pages"]
        if not self._pages:
            self._info(i18n.t("This PDF has no pages."))
            return
        self.prev_btn = self.button(i18n.t("Previous page"), small=True,
                                    on_click=lambda: self._goto(self._page - 1))
        self.next_btn = self.button(i18n.t("Next page"), small=True,
                                    on_click=lambda: self._goto(self._page + 1))
        self.page_label = QLabel("")
        self.zoom_out = self.button("−", small=True, tooltip=i18n.t("Zoom out"),
                                    on_click=lambda: self._zoom_pdf(-0.25))
        self.zoom_in = self.button("+", small=True, tooltip=i18n.t("Zoom in"),
                                   on_click=lambda: self._zoom_pdf(0.25))
        for w in (self.prev_btn, self.page_label, self.next_btn):
            self.bar.addWidget(w)
        self.bar.addStretch(1)
        for w in (self.zoom_out, self.zoom_in):
            self.bar.addWidget(w)
        self._pdf_view = _PictureView(QImage())
        self._add(self._pdf_view)
        self._goto(0)

    def _goto(self, index: int):
        self._page = max(0, min(index, self._pages - 1))
        self.page_label.setText(i18n.t("Page {n} of {total}").format(
            n=self._page + 1, total=self._pages))
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < self._pages - 1)
        for b, off in ((self.prev_btn, self._page == 0), (self.next_btn,
                                                           self._page >= self._pages - 1)):
            b.setToolTip(i18n.t("This is the first page.") if b is self.prev_btn and off
                         else i18n.t("This is the last page.") if off else "")
        self._page_worker = _PageWorker(self.path, self._page, self._pdf_zoom, self)
        self._page_worker.done.connect(self._page_ready)
        self._page_worker.failed.connect(lambda m: self._info(m, bad=True))
        self._page_worker.start()

    def _page_ready(self, index: int, image):
        if index == self._page:
            self._pdf_view.zoom = 1.0
            self._pdf_view.set_image(image)

    def _zoom_pdf(self, step: float):
        self._pdf_zoom = max(0.5, min(3.0, self._pdf_zoom + step))
        self._goto(self._page)

    # pictures
    def _build_picture(self, data):
        img = data.get("qimage")
        if img is None or img.isNull():
            self._info(i18n.t("This picture could not be read."), bad=True)
            return
        view = _PictureView(img)
        self._pic_view = view
        for text, delta in (("−", 0.8), ("+", 1.25)):
            self.bar.addStretch(1) if text == "−" else None
            self.bar.addWidget(self.button(
                text, small=True, tooltip=i18n.t("Zoom out") if text == "−" else i18n.t("Zoom in"),
                on_click=lambda _=False, d=delta: view.set_zoom(view.zoom * d)))
        self._add(view)

    # anything else
    def _build_card(self):
        kind = self.data["kind"]
        word = kind_word(kind)
        lines = [self.data["name"], f"{word} · {size_text(self.data['size'])}"]
        if kind in ("video", "audio"):
            lines.append(i18n.t("Prism cannot play this kind of file inside its own "
                                "window yet."))
        else:
            lines.append(i18n.t("Prism does not know how to show this kind of file."))
        lines.append(i18n.t("Open in another app opens it in the program your "
                            "computer uses for this kind of file."))
        self._info("\n\n".join(lines))
        self._set_enabled(False, i18n.t("There is no text in this file to copy."))

    # ── actions ──────────────────────────────────────────────────────────────
    def text_for_copy(self) -> str:
        c = self.content
        if c is None:
            return ""
        if hasattr(self, "_sheet_views"):
            w = self._current_sheet()
            return w.as_text() if isinstance(w, _SheetView) else ""
        if isinstance(c, QTabWidget):
            c = c.currentWidget()
        return c.toPlainText() if hasattr(c, "toPlainText") else ""

    def _copy(self):
        QApplication.clipboard().setText(self.text_for_copy())

    def _save_as(self):
        ext = os.path.splitext(self.path)[1]
        if os.path.isdir(self.path):
            return
        dest, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save a copy"), os.path.basename(self.path),
            f"{kind_word(self.kind)} (*{ext})" if ext else "")
        if dest:
            self.save_to(dest)

    def save_to(self, dest: str) -> bool:
        if not os.path.splitext(dest)[1]:
            dest += os.path.splitext(self.path)[1]
        try:
            shutil.copyfile(self.path, dest)
        except OSError as e:
            self.status.setText(i18n.t("Prism could not save that copy ({why}).").format(
                why=e.strerror or e))
            self.status.setVisible(True)
            return False
        return True
