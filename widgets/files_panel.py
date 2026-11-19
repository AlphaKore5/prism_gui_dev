"""Context rail: the files this task is being run against.

Two halves, and they are two different questions.

**Guesses.** Say "the brochure in my Documents folder" and the router resolves
it against the disk; the guess lands here as a card with the resolved path and
a Keep / Change pair — the CLI's confirm-before-attach prompt, turned into two
buttons.

**Attachments.** Everything kept, plus everything added by hand, as a real
contextual surface rather than a list of file names: a type glyph, the name
elided from the middle, the kind, the size on disk, and whether Prism will
only read part of it. Each row can be opened, previewed or taken back out.
A folder is one row that owns its files, because the engine attaches a folder
as its individual files and there was otherwise no single thing to remove.

Every field here is read from the attachment record or from the file system.
A file that cannot be stat'd shows no size rather than a guessed one.
"""
from __future__ import annotations
import os
from PySide6.QtCore import Signal, Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGraphicsOpacityEffect, QSizePolicy,
)

import i18n
import theme
from widgets import icons
from widgets import controls as C
from widgets.controls import kicker

# Item roles and what "Detach selected" should do with the highlighted row.
_PATH_ROLE = 1000
_MODE_ROLE = 1001
DETACH_FILE = "file"
DETACH_FOLDER = "folder"

# What a file is, in the words a person would use. See kind_label() below.


def _label(att: dict) -> str:
    """The row's text, saying so when only part of the file will be read.

    Prism inlines the first 12,000 characters of a file's text. For a 60-page
    tender that is roughly the first eight pages, and silently answering from
    an eighth of a document is a wrong deliverable rather than a degraded one.
    Truncation is reasonable; not mentioning it is not.
    """
    if att.get("truncated"):
        return f"{att['name']}   (first part only)"
    return att["name"]


def _tip(att: dict) -> str:
    if att.get("truncated"):
        return (f"{att['path']}\n\nThis file is long, so Prism is using its "
                f"first 12,000 characters — about 8 pages. The whole file is "
                f"still uploaded to any tool that accepts attachments.")
    return att["path"]


def kind_label(att: dict) -> str:
    """The engine's own classification of a file, in plain words.

    `core.files.attach` sets "image" / "pdf" / "text" / "folder"; anything it
    does not classify falls back to the extension, which is also a real fact
    about the file rather than a guess at one.

    The words live inside t() calls rather than in a module-level table
    because devtools/extract_strings.py reads the source and only scans tables
    whose name is in its COPY_TABLES set — a label that reaches the screen
    without reaching a translator is exactly what the catalogue prevents.
    """
    words = {
        "image": i18n.t("Image"), "pdf": i18n.t("PDF"),
        "text": i18n.t("Text"), "folder": i18n.t("Folder"),
        "doc": i18n.t("Document"), "sheet": i18n.t("Spreadsheet"),
        "code": i18n.t("Code"), "audio": i18n.t("Audio"),
        "video": i18n.t("Video"),
    }
    hit = words.get((att.get("kind") or "").lower())
    if hit:
        return hit
    ext = os.path.splitext(att.get("name") or att.get("path") or "")[1]
    return ext.lstrip(".").upper()


def size_label(path: str) -> str:
    """The file's size on disk, or nothing at all. Never an estimate."""
    try:
        size = float(os.path.getsize(path))
    except (OSError, TypeError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return ""


def _fade_in(widget: QWidget):
    if not C.effects_enabled():
        # A QGraphicsOpacityEffect that never paints costs you the widget, not
        # the animation: it starts at 0.0 and the card is then present,
        # correctly sized and permanently invisible. See controls.effects_enabled.
        return
    effect = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(effect)
    anim = QPropertyAnimation(effect, b"opacity", widget)
    anim.setDuration(200)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.setEasingCurve(QEasingCurve.OutQuart)
    anim.start(QPropertyAnimation.DeleteWhenStopped)
    widget._fade_anim = anim  # keep a reference alive


class MentionRow(QFrame):
    accepted = Signal(int)
    changed = Signal(int)

    def __init__(self, index: int, description: str, resolved: str, kind: str, parent=None):
        super().__init__(parent)
        self.index = index
        self.setObjectName("listRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.SPACE_3, theme.SPACE_3 - 1,
                                theme.SPACE_3, theme.SPACE_3 - 1)
        root.setSpacing(theme.SPACE_2 + 1)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2 + 1)
        head.addWidget(C.IconPad(
            "folder" if kind == "folder" else ("file" if kind == "file" else "help"),
            theme.ACCENT if resolved else theme.WARN, 28, theme.R_CONTROL, 14),
            alignment=Qt.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = QLabel(os.path.basename(resolved.rstrip("/")) if resolved
                      else i18n.t("Not found"))
        name.setStyleSheet(theme.type_css("SUPPORT", theme.TEXT))
        name.setWordWrap(True)
        text.addWidget(name)
        where = QLabel(
            i18n.t("in {folder}").format(
                folder=os.path.basename(os.path.dirname(resolved.rstrip('/'))))
            if resolved else i18n.t('for “{what}”').format(what=description))
        where.setObjectName("meta")
        where.setWordWrap(True)
        text.addWidget(where)
        head.addLayout(text, stretch=1)
        root.addLayout(head)

        self.setToolTip(i18n.t('"{what}"  →  {where}').format(
            what=description, where=resolved or i18n.t("(not found)")))

        actions = QHBoxLayout()
        actions.setSpacing(theme.SPACE_2 - 1)
        keep = C.button(i18n.t("Keep"), "primary", "check", small=True)
        keep.setEnabled(bool(resolved))
        keep.clicked.connect(lambda: self.accepted.emit(self.index))
        actions.addWidget(keep, stretch=1)

        change = C.button(i18n.t("Change"), "secondary", small=True)
        change.clicked.connect(lambda: self.changed.emit(self.index))
        actions.addWidget(change, stretch=1)
        root.addLayout(actions)

        _fade_in(self)


class FilesPanel(QWidget):
    mention_accepted = Signal(int)
    mention_change_requested = Signal(int)
    detach_requested = Signal(str)
    detach_folder_requested = Signal(str)   # the folder's own path
    detach_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._attached: list[dict] = []
        self._rows: list[tuple[str, str, str, str]] = []  # label, detail, target, mode
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_2 + 1)
        # No "Files you mentioned" heading here. The context rail draws it
        # itself, on the same line as the collapse chevron — having both
        # printed it put the title on screen twice.

        self.empty = QLabel(i18n.t(
            "Nothing attached yet. Name a file or folder in your task and "
            "Prism will look for it."))
        self.empty.setObjectName("emptyState")
        self.empty.setWordWrap(True)
        root.addWidget(self.empty)

        mentions_wrap = QWidget()
        self.mentions_box = QVBoxLayout(mentions_wrap)
        self.mentions_box.setContentsMargins(0, 0, 0, 0)
        self.mentions_box.setSpacing(theme.SPACE_2)
        root.addWidget(mentions_wrap)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.attached_label = kicker(i18n.t("Attached"), muted=True)
        head.addWidget(self.attached_label, stretch=1)
        self.attached_count = C.Pill("", "quiet")
        head.addWidget(self.attached_count)
        root.addLayout(head)

        rows_wrap = QWidget()
        self.rows_box = QVBoxLayout(rows_wrap)
        self.rows_box.setContentsMargins(0, 0, 0, 0)
        self.rows_box.setSpacing(theme.SPACE_1 + 2)
        root.addWidget(rows_wrap)

        self.detach_all_btn = C.button(i18n.t("Detach all"), "tertiary",
                                       "trash", small=True)
        self.detach_all_btn.setToolTip(
            i18n.t("Take every attached file back out."))
        self.detach_all_btn.clicked.connect(self.detach_all_requested.emit)
        root.addWidget(self.detach_all_btn)

        self._refresh_empty_state()

    # ── state ─────────────────────────────────────────────────────────────
    def _refresh_empty_state(self):
        has_mentions = self.mentions_box.count() > 0
        has_attached = bool(self._rows)
        self.empty.setVisible(not has_mentions and not has_attached)
        self.attached_label.setVisible(has_attached)
        self.attached_count.setVisible(has_attached)
        self.detach_all_btn.setVisible(has_attached)

    def clear_mentions(self):
        while self.mentions_box.count():
            item = self.mentions_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._refresh_empty_state()

    def add_mention(self, index: int, description: str, resolved: str, kind: str):
        row = MentionRow(index, description, resolved, kind)
        row.accepted.connect(self.mention_accepted.emit)
        row.changed.connect(self.mention_change_requested.emit)
        self.mentions_box.addWidget(row)
        self._refresh_empty_state()

    # ── the tray ──────────────────────────────────────────────────────────
    def set_attached(self, attachments: list[dict]):
        """Draw the tray: loose files as themselves, folders as one row with
        their files indented underneath.

        Grouping is presentation only — the engine still receives the flat
        list of files, because that is what it uploads. What it buys is a
        single row that means "this whole folder", which is the thing there
        was previously no way to take back out.
        """
        self._attached = list(attachments or [])
        self._rows = []
        while self.rows_box.count():
            item = self.rows_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        loose = [a for a in self._attached if not a.get("from_dir")]
        folders: dict[str, list[dict]] = {}
        for a in self._attached:
            if a.get("from_dir"):
                folders.setdefault(a["from_dir"], []).append(a)

        for a in loose:
            self._add_row(_label(a), a["path"], DETACH_FILE,
                          "folder" if a.get("kind") == "folder" else "file",
                          _tip(a), detail=self._detail(a))

        for folder, files in folders.items():
            count = len(files)
            self._add_row(
                os.path.basename(folder.rstrip(os.sep)) or folder,
                folder, DETACH_FOLDER, "folder", folder,
                detail=(i18n.t("Folder · {n} file") if count == 1
                        else i18n.t("Folder · {n} files")).format(n=count),
                lead=True)
            for a in files:
                self._add_row("     " + _label(a), a["path"], DETACH_FILE,
                              "file", _tip(a), detail=self._detail(a),
                              muted=True)
        self.attached_count.setText(
            (i18n.t("{n} file") if len(self._attached) == 1
             else i18n.t("{n} files")).format(n=len(self._attached)))
        self._refresh_empty_state()

    @staticmethod
    def _detail(att: dict) -> str:
        bits = [b for b in (kind_label(att), size_label(att.get("path"))) if b]
        if att.get("truncated"):
            bits.append(i18n.t("first part only"))
        return " · ".join(bits)

    def _add_row(self, label: str, target: str, mode: str, icon_name: str,
                 tip: str, *, detail: str = "", lead: bool = False,
                 muted: bool = False):
        drop = C.icon_button(
            "x",
            i18n.t("Remove this folder and everything in it")
            if mode == DETACH_FOLDER else i18n.t("Remove this file"),
            lambda: self._detach(target, mode))
        drop.setFixedSize(28, 28)
        row = C.FileItem(label.strip(), detail, icon_name, [drop])
        row.setToolTip(tip if mode != DETACH_FOLDER else
                       i18n.t("{path}\n\nRemoving this row removes every file "
                              "that came from the folder.").format(path=tip))
        row.activated.connect(lambda p=target: self._open(p))
        if muted:
            row.name.setStyleSheet(theme.type_css("SUPPORT", theme.NEUTRAL[600]))
        if lead:
            row.name.setStyleSheet(theme.type_css("SUPPORT", theme.TEXT)
                                   + " font-weight: 600;")
        row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.rows_box.addWidget(row)
        self._rows.append((label.strip(), detail, target, mode))

    def _detach(self, target: str, mode: str):
        if mode == DETACH_FOLDER:
            self.detach_folder_requested.emit(target)
        else:
            self.detach_requested.emit(target)

    @staticmethod
    def _open(path: str):
        """Show the attachment inside Prism's own viewer, so somebody can check
        they attached the right file without another program opening."""
        if path and os.path.exists(path):
            import paths
            paths.open_file(path)

    # ── read-back, for tests and for the window ───────────────────────────
    def attached_labels(self) -> list[str]:
        """The NAME of each tray row, in order.

        Replaces the old `attached_list.item(i).text()` walk: the tray is a
        column of controls.FileItem rows now rather than a QListWidget, and a
        row's name and its "PDF · 1.2 MB · first part only" line are two
        fields rather than one string."""
        return [label for label, _d, _t, _m in self._rows]

    def attached_details(self) -> list[str]:
        """The second line of each tray row, in the same order."""
        return [detail for _l, detail, _t, _m in self._rows]

    def attached_count_value(self) -> int:
        return len(self._rows)
