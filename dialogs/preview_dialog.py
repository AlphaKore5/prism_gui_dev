"""Open an Artifact inside Prism itself, not by handing it to the OS.

Artifacts used to open the same way every attachment chip in the app always
has — QDesktopServices.openUrl(), the system's own default app — see
widgets/files_panel.py's "Open" action and its docstring on why that is the
right call for an attachment a person is only checking. An Artifact is
different: it is the thing Prism itself made, in the window Prism itself
put it in, and the customer asked for it to stay that way rather than
bouncing out to whatever program the OS happens to have registered for a
.png today. `open_preview()` is the one entry point every row in
artifacts_panel.py calls instead.

Only a real remote URL — the "open the chat that made this" globe button —
keeps leaving the app; that one has nowhere to render TO inside Prism.

What actually renders in-app: images, plain-text/code, PDF, video, audio,
modern Word documents, Excel workbooks, PowerPoint decks, and a folder's own
contents (as a list, not a raw OS file-manager window). Office previews show
their readable content rather than pretending to be a full Office editor;
legacy/binary Office formats and archives retain an explicit "Open in the
default app" escape hatch.
"""
from __future__ import annotations

import html
import os
import re
import zipfile

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QSizePolicy, QSlider, QTabWidget,
    QTableWidget, QTableWidgetItem, QTextBrowser,
)

import i18n
import paths
import theme
from dialogs.base import PrismDialog
from widgets import controls as C

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".avi", ".mkv")
_AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")
_TEXT_EXTS = (".txt", ".md", ".json", ".py", ".js", ".ts", ".tsx", ".jsx",
             ".html", ".css", ".java", ".c", ".cpp", ".h", ".go", ".rb",
             ".php", ".sh", ".sql", ".csv", ".ipynb", ".yaml", ".yml")
_DOCUMENT_EXTS = (".docx",)
_SPREADSHEET_EXTS = (".xlsx",)
_PRESENTATION_EXTS = (".pptx",)


def _classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext == ".pdf":
        return "pdf"
    if ext in _DOCUMENT_EXTS:
        return "document"
    if ext in _SPREADSHEET_EXTS:
        return "spreadsheet"
    if ext in _PRESENTATION_EXTS:
        return "presentation"
    if ext in _TEXT_EXTS:
        return "text"
    return "other"


def _trigger_edit_reel(path: str, origin_widget=None) -> bool:
    """Find MainWindow and launch the reel layout editor."""
    from PySide6.QtWidgets import QApplication
    curr = origin_widget
    while curr is not None:
        if hasattr(curr, "_edit_reel_layout"):
            curr._edit_reel_layout(path)
            return True
        if hasattr(curr, "edit_reel"):
            curr.edit_reel.emit(path)
            return True
        curr = curr.parent()
    for w in QApplication.topLevelWidgets():
        if hasattr(w, "_edit_reel_layout"):
            w._edit_reel_layout(path)
            return True
        if hasattr(w, "artifacts_panel") and hasattr(w.artifacts_panel, "edit_reel"):
            w.artifacts_panel.edit_reel.emit(path)
            return True
    return False


def open_preview(path: str, parent=None, demo_mode: bool = False):
    """Show `path` inside Prism. A folder gets a navigable list of its own
    contents; a file gets the viewer matching its kind, or — for a kind
    nothing here can render — a small dialog offering to open it externally
    instead of doing that automatically.

    Video and audio fall back to the default-app dialog if Qt's optional
    multimedia module is unavailable. PDF uses pypdf's text extraction, so it
    stays readable even in the compact shipped build, which deliberately does
    not include QtPdf.
    """
    if os.path.isdir(path):
        FolderPreviewDialog(path, parent).exec()
        return
    kind = _classify(path)
    if kind in ("video", "audio") or demo_mode:
        # Only these need QtMultimedia, which the shipped build leaves out;
        # without it the file viewer says so and offers "Open in another app".
        try:
            PreviewDialog(path, kind, parent, demo_mode=demo_mode).exec()
            return
        except ImportError:
            pass
    from dialogs.file_viewer import FileViewer
    FileViewer(path, parent).exec()


# The dialog-header glyph registry (widgets/icons.py) only has "image",
# "video", "code" and "file" — not one for every kind this dialog renders.
_HEADER_ICON = {"image": "image", "video": "video", "audio": "video",
               "pdf": "file", "document": "file", "spreadsheet": "file",
               "presentation": "file", "text": "code"}


class PreviewDialog(PrismDialog):
    """One file, rendered in-app. `kind` picks the body; the chrome (title,
    close, an explicit escape hatch to the OS app) is the same for all four."""

    def __init__(self, path: str, kind: str, parent=None, demo_mode: bool = False):
        # demo_mode is the "Watch demo video" on Home: a prospect watching a
        # promo, not someone inspecting a file. It carries a plain title
        # instead of "prism-creator-promo_2026-08-16_05-15-18.mp4" and none
        # of the file-handling buttons (open in the default app, edit layout,
        # open chat) — just the player and Close.
        super().__init__(i18n.t("Prism demo") if demo_mode else os.path.basename(path),
                         icon=_HEADER_ICON.get(kind, "file"), parent=parent,
                         scrollable=(kind == "text"))
        self.demo_mode = demo_mode
        self.path = path
        self._player = None   # keeps QMediaPlayer/QAudioOutput alive
        self.resize(860, 640)
        self.setMinimumSize(480, 360)

        body = {
            "image": self._build_image,
            "video": self._build_video,
            "audio": self._build_audio,
            "pdf": self._build_pdf,
            "document": self._build_document,
            "spreadsheet": self._build_spreadsheet,
            "presentation": self._build_presentation,
            "text": self._build_text,
        }[kind]
        body()

        if not demo_mode:
            self.footer.add_utility(self.button(
                i18n.t("Open in default app"), on_click=self._open_externally))

        # Check if editable reel
        if kind == "video" and not demo_mode:
            try:
                from widgets.artifacts_panel import _editable_reel
                if _editable_reel(self.path):
                    self.footer.add_secondary(self.button(
                        i18n.t("Edit the layout"), "secondary",
                        on_click=self._edit_layout))
            except Exception:
                pass

        # Check if chat link exists
        try:
            from widgets.artifacts_panel import _chat_link
            chat_url = None if demo_mode else _chat_link(self.path)
            if chat_url:
                self.footer.add_secondary(self.button(
                    i18n.t("Open chat"), "secondary",
                    on_click=lambda: QDesktopServices.openUrl(QUrl(chat_url))))
        except Exception:
            pass

        self.footer.set_primary(self.button(
            i18n.t("Close"), "primary", on_click=self.accept))

    def _edit_layout(self):
        self.accept()
        _trigger_edit_reel(self.path, self)

    def _open_externally(self):
        paths.open_in_other_app(self.path)

    # -- image --------------------------------------------------------------
    def _build_image(self):
        pix = QPixmap(self.path)
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        if pix.isNull():
            label.setText(i18n.t("This image could not be read."))
        else:
            label.setPixmap(pix.scaled(
                800, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.body.addWidget(label, stretch=1)

    # -- text/code ------------------------------------------------------------
    def _build_text(self):
        edit = QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setStyleSheet(theme.type_css("MONO", theme.TEXT))
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                edit.setPlainText(f.read())
        except OSError as e:
            edit.setPlainText(f"({e})")
        self.body.addWidget(edit, stretch=1)

    # -- Office previews -----------------------------------------------------
    def _build_document(self):
        """Render the readable structure of a modern Word document.

        python-docx is already bundled because Prism writes DOCX fallbacks
        for agents. Reusing it gives headings, paragraphs and tables without
        pretending to be a full Word editor or sending the person elsewhere.
        """
        view = QTextBrowser()
        view.setOpenExternalLinks(False)
        view.setStyleSheet(theme.type_css("BODY", theme.TEXT))
        try:
            from docx import Document
            doc = Document(self.path)
            parts = []
            for paragraph in doc.paragraphs:
                text = html.escape(paragraph.text).replace("\n", "<br>")
                if not text:
                    continue
                style = (paragraph.style.name or "").lower()
                heading = re.search(r"heading\s*([1-6])", style)
                if heading:
                    parts.append(f"<h{heading.group(1)}>{text}</h{heading.group(1)}>")
                elif "list" in style:
                    parts.append(f"<p>• {text}</p>")
                else:
                    parts.append(f"<p>{text}</p>")
            for table in doc.tables:
                rows = []
                for row in table.rows:
                    cells = "".join(
                        f"<td>{html.escape(cell.text).replace(chr(10), '<br>')}</td>"
                        for cell in row.cells)
                    rows.append(f"<tr>{cells}</tr>")
                if rows:
                    parts.append("<table border='1' cellspacing='0' cellpadding='5'>"
                                 + "".join(rows) + "</table><br>")
            empty = html.escape(i18n.t("This document is empty."))
            view.setHtml("".join(parts) or f"<p>{empty}</p>")
        except Exception as e:                            # malformed DOCX
            view.setPlainText(i18n.t("This Word document could not be read.")
                              + f"\n\n{e}")
        self.body.addWidget(view, stretch=1)

    def _build_spreadsheet(self):
        """Show workbook sheets as bounded, read-only tables.

        The bound keeps a workbook with a million formatted rows responsive;
        the original remains one click away in the default spreadsheet app.
        """
        tabs = QTabWidget()
        book = None
        try:
            from openpyxl import load_workbook
            from openpyxl.utils import get_column_letter
            book = load_workbook(self.path, read_only=True, data_only=True)
            for sheet in book.worksheets[:12]:
                rows = list(sheet.iter_rows(max_row=300, max_col=40,
                                            values_only=True))
                cols = max((len(row) for row in rows), default=1)
                table = QTableWidget(len(rows), cols)
                table.setEditTriggers(QTableWidget.NoEditTriggers)
                table.setHorizontalHeaderLabels(
                    [get_column_letter(i + 1) for i in range(cols)])
                for r, row in enumerate(rows):
                    for c, value in enumerate(row):
                        if value is not None:
                            table.setItem(r, c, QTableWidgetItem(str(value)))
                tabs.addTab(table, sheet.title)
            if not book.worksheets:
                tabs.addTab(QLabel(i18n.t("This workbook is empty.")), "Sheet")
        except Exception as e:                            # corrupt or encrypted XLSX
            tabs.addTab(QLabel(i18n.t("This workbook could not be read.")
                               + f"\n\n{e}"), i18n.t("Preview"))
        finally:
            # A read-only workbook keeps its file open until closed. On
            # Windows that locks the .xlsx: Excel cannot save it, Prism cannot
            # overwrite or delete it, for as long as the preview exists.
            try:
                if book is not None:
                    book.close()
            except Exception:                             # noqa: BLE001
                pass
        self.body.addWidget(tabs, stretch=1)

    def _build_presentation(self):
        """Extract visible PPTX text slide-by-slide for an in-app preview."""
        tabs = QTabWidget()
        try:
            with zipfile.ZipFile(self.path) as deck:
                names = sorted(
                    (name for name in deck.namelist()
                     if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=lambda name: int(re.search(r"\d+", name).group()))
                for index, name in enumerate(names, 1):
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(deck.read(name))
                    words = [node.text for node in root.iter()
                             if node.tag.endswith("}t") and node.text]
                    page = QTextBrowser()
                    page.setStyleSheet(theme.type_css("BODY", theme.TEXT))
                    page.setPlainText("\n".join(words) or "(No text on this slide.)")
                    tabs.addTab(page, i18n.t("Slide {n}").format(n=index))
            if not tabs.count():
                tabs.addTab(QLabel(i18n.t("This presentation has no slides.")),
                            i18n.t("Preview"))
        except Exception as e:                            # malformed PPTX
            tabs.addTab(QLabel(i18n.t("This presentation could not be read.")
                               + f"\n\n{e}"), i18n.t("Preview"))
        self.body.addWidget(tabs, stretch=1)

    # -- pdf ------------------------------------------------------------------
    def _build_pdf(self):
        """Keep PDFs readable in builds that intentionally omit QtPdf.

        pypdf is already bundled for the engine; unlike QtPdf it does not
        pull a second native rendering stack into every installer. The reader
        gets the document's selectable text in Prism, and can still use the
        explicit default-app button for original visual fidelity.
        """
        view = QTextBrowser()
        view.setStyleSheet(theme.type_css("BODY", theme.TEXT))
        try:
            from pypdf import PdfReader
            reader = PdfReader(self.path)
            pages = [page.extract_text() or i18n.t("(No extractable text on this page.)")
                     for page in reader.pages]
            view.setPlainText("\n\n".join(pages) or i18n.t("This PDF is empty."))
        except Exception as e:
            view.setPlainText(i18n.t("This PDF could not be read.") + f"\n\n{e}")
        self.body.addWidget(view, stretch=1)

    # -- video ------------------------------------------------------------------
    def _build_video(self):
        from PySide6.QtMultimediaWidgets import QVideoWidget
        video = QVideoWidget()
        video.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body.addWidget(video, stretch=1)
        self._wire_player(video)

    # -- audio ------------------------------------------------------------------
    def _build_audio(self):
        label = QLabel(os.path.basename(self.path))
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        self.body.addWidget(label, stretch=1)
        self._wire_player(None)

    def _wire_player(self, video_widget):
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        player = QMediaPlayer(self)
        audio = QAudioOutput(self)
        player.setAudioOutput(audio)
        if video_widget is not None:
            player.setVideoOutput(video_widget)
        player.setSource(QUrl.fromLocalFile(self.path))
        self._player = (player, audio)   # kept alive for the dialog's life

        self.body.addLayout(self._transport_row(player))
        player.play()

    def _transport_row(self, player):
        row = QHBoxLayout()
        play_btn = self.button(i18n.t("Pause"), on_click=lambda: (
            player.pause() if player.isPlaying() else player.play()))

        def _sync(_state=None):
            play_btn.setText(i18n.t("Pause") if player.isPlaying()
                             else i18n.t("Play"))
        player.playbackStateChanged.connect(_sync)
        row.addWidget(play_btn)

        slider = QSlider(Qt.Horizontal)
        slider.setRange(0, 0)

        def _duration(ms):
            slider.setRange(0, ms)
        def _position(ms):
            if not slider.isSliderDown():
                slider.setValue(ms)
        player.durationChanged.connect(_duration)
        player.positionChanged.connect(_position)
        slider.sliderMoved.connect(player.setPosition)
        row.addWidget(slider, stretch=1)
        return row

    def reject(self):
        self._stop_playback()
        super().reject()

    def accept(self):
        self._stop_playback()
        super().accept()

    def _stop_playback(self):
        if self._player is not None:
            self._player[0].stop()


class UnsupportedPreviewDialog(PrismDialog):
    """A legacy/binary file kind Prism cannot preview — archives, .doc, .xls.
    Says so plainly rather than silently doing what the row used to do."""

    def __init__(self, path: str, parent=None):
        super().__init__(os.path.basename(path),
                         i18n.t("Prism can't show this file type inline yet."),
                         icon="file", parent=parent)
        self.path = path
        self.resize(440, 200)
        self.body.addWidget(QLabel(
            i18n.t("It will open in whatever app your computer already "
                   "uses for this kind of file.")))
        self.footer.add_secondary(self.button(
            i18n.t("Close"), on_click=self.reject))
        self.footer.set_primary(self.button(
            i18n.t("Open in default app"), "primary",
            on_click=self._open_externally))

    def _open_externally(self):
        paths.open_in_other_app(self.path)
        self.accept()


class FolderPreviewDialog(PrismDialog):
    """A task subfolder's contents, as a Prism list — same FileItem rows the
    Artifacts screen itself uses — rather than handing the whole folder to
    the OS file manager. Clicking a row opens that file/folder the same way,
    recursively, so a nested folder (Gerber's cleaned-copy output keeps its
    own previews/ subfolder) is just another row rather than a dead end."""

    edit_reel = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(os.path.basename(path), icon="folder",
                         parent=parent, scrollable=True)
        self.path = path
        self.resize(560, 640)
        self.setMinimumSize(420, 360)

        entries = sorted(
            (os.path.join(path, name) for name in os.listdir(path)
             if not name.endswith(".link.txt")
             and not (name.endswith(".json") and os.path.isfile(os.path.join(path, os.path.splitext(name)[0] + ".mp4")))),
            key=lambda p: (os.path.isfile(p), os.path.basename(p).lower()))
        if not entries:
            self.body.addWidget(C.EmptyState(
                "folder", i18n.t("Empty"), i18n.t("Nothing in this folder.")),
                stretch=1)
        for entry in entries:
            self.body.addWidget(self._row(entry))
        self.body.addStretch(1)

        self.footer.add_utility(self.button(
            i18n.t("Show in file manager"), on_click=self._open_externally))
        self.footer.set_primary(self.button(
            i18n.t("Close"), "primary", on_click=self.accept))

    def _row(self, path: str) -> C.FileItem:
        from widgets.files_panel import kind_label, size_label
        name = os.path.basename(path)
        if os.path.isdir(path):
            n = sum(len(f) for _r, _d, f in os.walk(path))
            detail = (i18n.t("1 file") if n == 1
                     else i18n.t("{n} files").format(n=n))
            icon = "folder"
            kind = ""
        else:
            classified = _classify(path)
            kind = classified if classified != "other" else ""
            detail = " · ".join(p for p in (
                kind_label({"kind": kind, "name": name}), size_label(path))
                if p)
            icon = {"image": "image", "video": "video", "audio": "video",
                   "text": "code"}.get(kind, "file")
        actions = [C.icon_button(
            "external", i18n.t("Open"),
            lambda _=False, p=path: open_preview(p, self))]
        if kind == "video":
            try:
                from widgets.artifacts_panel import _editable_reel
                if _editable_reel(path):
                    actions.append(C.icon_button(
                        "pencil", i18n.t("Edit the layout"),
                        lambda _=False, p=path: self._edit_child_layout(p)))
            except Exception:
                pass
        try:
            from widgets.artifacts_panel import _chat_link
            link = _chat_link(path)
            if link:
                actions.append(C.icon_button(
                    "globe", i18n.t("Open the chat that made this"),
                    lambda _=False, u=link: QDesktopServices.openUrl(QUrl(u))))
        except Exception:
            pass

        row = C.FileItem(name, detail, icon, actions)
        row.setToolTip(path)
        row.activated.connect(lambda p=path: open_preview(p, self))
        return row

    def _edit_child_layout(self, p: str):
        self.accept()
        _trigger_edit_reel(p, self)

    def _open_externally(self):
        paths.reveal_result(self.path)
