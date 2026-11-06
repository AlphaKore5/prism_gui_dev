"""The STEP workbench's own widgets — pure UI, no engine, no AI.

Everything here only draws what StepDialog hands it (models, a drawing sheet,
a measurement, files on disk) and says, by signal, what the person clicked.
The measuring, asking, planning and building stay in dialog.py, untouched.

Laid out to match preview/step-redesign/a2-workbench.html:
models · canvas with one action at a time · results in tabs.
"""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QColor, QDesktopServices, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
    QTextBrowser, QVBoxLayout, QWidget,
)

import i18n
import paths
import theme
from widgets import controls as C

_EDGE = "rgba(0, 0, 0, 0.10)"
_HAIR = "rgba(0, 0, 0, 0.07)"
MODEL_EXTS = (".step", ".stp")


def _discard(widget: QWidget):
    """Take a widget out of sight at once. deleteLater() alone leaves it
    painted until the event loop gets round to it, which showed as ghost rows
    when a list was rebuilt."""
    widget.hide()
    widget.setParent(None)
    widget.deleteLater()


def heading(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet(
        f"color: {theme.NEUTRAL[500]}; font-size: 11px; font-weight: 700;"
        " letter-spacing: 1px; background: transparent; border: none;")
    return label


def linkify(label: QLabel, colour: str) -> QLabel:
    """Links in a styled QLabel take the palette's link colour, not the
    stylesheet's text colour — set it explicitly or they read as plain
    underlined text."""
    pal = label.palette()
    pal.setColor(QPalette.Link, QColor(colour))
    pal.setColor(QPalette.LinkVisited, QColor(colour))
    label.setPalette(pal)
    label.setTextFormat(Qt.RichText)
    return label


class Link(QLabel):
    """A text link that is really a styled label: Qt's rich-text anchors take
    the application palette, which on this style comes out black."""

    clicked = Signal()

    def __init__(self, text: str, colour: str = "", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"color: {colour or theme.INFO}; text-decoration: underline;"
            " background: transparent; border: none; font-size: 12.5px;")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def chip(text: str, tone: str = "neutral") -> QLabel:
    bg, ink = {
        "ok": ("#f0fdf4", "#15803d"), "info": ("#f0f9ff", "#0369a1"),
        "warn": ("#fefce8", "#a16207"), "neutral": (theme.NEUTRAL[200],
                                                    theme.NEUTRAL[700]),
    }[tone]
    label = QLabel(text)
    label.setStyleSheet(
        f"background: {bg}; color: {ink}; border-radius: 5px; border: none;"
        " font-size: 10.5px; font-weight: 700; padding: 1px 6px;")
    label.setSizePolicy(label.sizePolicy().horizontalPolicy(),
                        label.sizePolicy().verticalPolicy())
    return label


class Card(QFrame):
    """A white panel with an upper-case title, like the mock's three columns."""

    def __init__(self, title: str = "", counter: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("wbCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#wbCard {{ background: #ffffff; border: 1px solid {_EDGE};"
            f" border-radius: {theme.R_CARD}px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.count = None
        if title:
            head = QFrame()
            head.setStyleSheet(f"border: none; border-bottom: 1px solid {_HAIR};")
            row = QHBoxLayout(head)
            row.setContentsMargins(16, 11, 16, 11)
            row.addWidget(heading(title))
            row.addStretch(1)
            if counter:
                self.count = chip("0")
                row.addWidget(self.count)
            self.lay.addWidget(head)

    def set_count(self, n: int):
        if self.count is not None:
            self.count.setText(str(n))


# ── models ───────────────────────────────────────────────────────────────

class _ModelRow(QFrame):
    clicked = Signal(str)
    removed = Signal(str)
    trashed = Signal(str)

    def __init__(self, item: dict, selected: bool, parent=None):
        super().__init__(parent)
        self.path = item["path"]
        self.setObjectName("wbModel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        edge = theme.ACCENT if selected else _EDGE
        width = "2px" if selected else "1px"
        self.setStyleSheet(
            f"#wbModel {{ background: #ffffff; border: {width} solid {edge};"
            " border-radius: 10px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 9, 8, 9)
        lay.setSpacing(10)
        thumb = QLabel("▣")
        thumb.setAlignment(Qt.AlignCenter)
        thumb.setFixedSize(42, 42)
        thumb.setStyleSheet(
            f"background: {theme.NEUTRAL[100]}; color: {theme.NEUTRAL[700]};"
            " border-radius: 8px; border: none; font-size: 16px;")
        lay.addWidget(thumb)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(item["name"])
        name.setToolTip(item["path"])
        name.setWordWrap(True)
        name.setStyleSheet("font-weight: 700; font-size: 13.5px; border: none;"
                           " background: transparent;")
        col.addWidget(name)
        s = QLabel(item["sub"])
        s.setWordWrap(True)
        s.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12px;"
                        " border: none; background: transparent;")
        col.addWidget(s)
        tag = QHBoxLayout()
        tag.addWidget(chip(item["status"], item["tone"]))
        tag.addStretch(1)
        col.addLayout(tag)
        lay.addLayout(col, stretch=1)
        x = C.icon_button("x", i18n.t("Remove this file"),
                          on_click=lambda: self.removed.emit(self.path))
        side = QVBoxLayout()
        side.setSpacing(0)
        side.addWidget(x, 0, Qt.AlignTop)
        if item.get("folder"):
            # Only a model Prism has made files for has anything to delete.
            bin_ = C.icon_button("trash", i18n.t(
                "Delete the files Prism made for this model"),
                on_click=lambda: self.trashed.emit(self.path))
            side.addWidget(bin_, 0, Qt.AlignTop)
        lay.addLayout(side)

    def mousePressEvent(self, event):
        self.clicked.emit(self.path)
        super().mousePressEvent(event)


class ModelList(QWidget):
    selected = Signal(str)
    removed = Signal(str)
    trashed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(10, 10, 10, 6)
        self.col.setSpacing(8)

    def set_items(self, items: list, current: str):
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                _discard(item.widget())
        for it in items:
            row = _ModelRow(it, it["path"] == current)
            row.clicked.connect(self.selected.emit)
            row.removed.connect(self.removed.emit)
            row.trashed.connect(self.trashed.emit)
            self.col.addWidget(row)


class _RunRow(QFrame):
    clicked = Signal(str)
    deleted = Signal(str)

    def __init__(self, item: dict, current: bool, parent=None):
        super().__init__(parent)
        self.path = item["path"]
        self.setObjectName("wbRun")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setCursor(Qt.PointingHandCursor)
        bg = theme.NEUTRAL[100] if current else "transparent"
        self.setStyleSheet(
            f"#wbRun {{ background: {bg}; border: none; border-radius: 8px; }}"
            "#wbRun:hover { background: " + theme.NEUTRAL[100] + "; }")
        self.setToolTip(item.get("tip", ""))
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)
        tone = {"Draft": "info", "Ask": "ok", "Edit": "warn"}.get(
            item["action"], "neutral")
        lay.addWidget(chip(item["action"], tone), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        text = QLabel(item["text"])
        text.setWordWrap(False)
        text.setStyleSheet("font-size: 12.5px; border: none; background: transparent;")
        text.setMaximumWidth(160)
        fm = text.fontMetrics()
        text.setText(fm.elidedText(item["text"], Qt.ElideRight, 158))
        col.addWidget(text)
        when = QLabel(item["when"])
        when.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 11.5px;"
                           " border: none; background: transparent;")
        col.addWidget(when)
        lay.addLayout(col, stretch=1)
        bin_ = C.icon_button("trash", i18n.t("Delete this chat from History"),
                             on_click=lambda: self.deleted.emit(self.path))
        bin_.setFixedSize(28, 28)
        lay.addWidget(bin_, 0, Qt.AlignVCenter)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.path)
        super().mousePressEvent(event)


class RunList(QWidget):
    """Every past STEP run on this machine. Click one and the workbench
    reopens it — the model, the question, the answer and its files."""

    chosen = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.col = QVBoxLayout(self)
        self.col.setContentsMargins(8, 4, 8, 4)
        self.col.setSpacing(2)

    def set_items(self, items: list, current: str = ""):
        while self.col.count():
            item = self.col.takeAt(0)
            if item.widget():
                _discard(item.widget())
        if not items:
            empty = QLabel(i18n.t("No runs yet."))
            empty.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12.5px;"
                                " padding: 6px 8px; border: none;")
            self.col.addWidget(empty)
            self.col.addStretch(1)
            return
        for it in items:
            row = _RunRow(it, it["path"] == current)
            row.clicked.connect(self.chosen.emit)
            row.deleted.connect(self.delete_requested.emit)
            self.col.addWidget(row)
        self.col.addStretch(1)


class DropZone(QFrame):
    browse = Signal()
    favourites = Signal()
    dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setObjectName("wbDrop")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#wbDrop {{ background: {theme.NEUTRAL[100]};"
            f" border: 1.5px dashed {theme.NEUTRAL[300]}; border-radius: 10px; }}"
            "QLabel { border: none; background: transparent; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 14, 12, 12)
        lay.setSpacing(4)
        t = QLabel(i18n.t("Drop .step / .stp files here"))
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12.5px;")
        lay.addWidget(t)
        row = QHBoxLayout()
        row.setAlignment(Qt.AlignCenter)
        b = Link(i18n.t("or browse"))
        b.clicked.connect(self.browse.emit)
        f = Link(i18n.t("Favourites"))
        f.clicked.connect(self.favourites.emit)
        row.addWidget(b)
        row.addSpacing(10)
        row.addWidget(f)
        lay.addLayout(row)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()


# ── the canvas ───────────────────────────────────────────────────────────

class _Sheet(QWidget):
    """Prism's drawing sheet on the mock's faint engineering grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix = QPixmap()

    def set_image(self, path: str) -> bool:
        pix = QPixmap(path)
        if pix.isNull():
            return False
        self._pix = pix
        self._path = path
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(i18n.t("Click to open the drawing in its own window"))
        self.update()
        return True

    def mousePressEvent(self, event):
        # A drawing is for looking at closely: open it in the machine's own
        # picture viewer, in another window.
        if event.button() == Qt.LeftButton and getattr(self, "_path", ""):
            paths.open_file(self._path)
        super().mousePressEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#fbfbfc"))
        pen = QPen(QColor(0, 0, 0, 14))
        p.setPen(pen)
        for x in range(0, self.width(), 24):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 24):
            p.drawLine(0, y, self.width(), y)
        if self._pix.isNull():
            return
        pad = 22
        box = QRectF(pad, pad, max(self.width() - 2 * pad, 20),
                     max(self.height() - 2 * pad, 20))
        scaled = self._pix.scaled(int(box.width()), int(box.height()),
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = box.x() + (box.width() - scaled.width()) / 2
        y = box.y() + (box.height() - scaled.height()) / 2
        p.fillRect(QRectF(x - 1, y - 1, scaled.width() + 2,
                          scaled.height() + 2), QColor("#ffffff"))
        p.drawPixmap(int(x), int(y), scaled)


class Canvas(QFrame):
    """Empty invitation · waiting · measuring · the drawing sheet · a note.
    A tag floats top-left; a toast floats at the bottom."""

    choose = Signal()
    dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setStyleSheet("border: none;")
        self.setMinimumHeight(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack)
        self.sheet = _Sheet()
        self.card = QLabel("")
        self.card.setAlignment(Qt.AlignCenter)
        self.card.setWordWrap(True)
        self.card.setTextFormat(Qt.RichText)
        self.card.setOpenExternalLinks(False)
        linkify(self.card, theme.INFO_INK)
        self.card.setStyleSheet(
            "background: #fbfbfc; border: none; padding: 20px;"
            f" color: {theme.NEUTRAL[700]}; font-size: 13px;")
        self.page = QWidget()
        pl = QVBoxLayout(self.page)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)
        pl.addStretch(1)
        pl.addWidget(self.card)
        self.choose_btn = C.button(i18n.t("Choose files…"), "primary",
                                   on_click=self.choose.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.choose_btn)
        row.addStretch(1)
        self.choose_host = QWidget()
        self.choose_host.setLayout(row)
        pl.addWidget(self.choose_host)
        pl.addStretch(1)
        self.page.setObjectName("wbPage")
        self.page.setStyleSheet("#wbPage { background: #fbfbfc; }")
        self.stack.addWidget(self.page)
        self.stack.addWidget(self.sheet)
        self.tag = chip("")
        self.tag.setParent(self)
        self.tag.hide()
        self.toast_box = QFrame(self)
        self.toast_box.setStyleSheet(
            f"background: {theme.TEXT}; border-radius: 10px; border: none;")
        trow = QHBoxLayout(self.toast_box)
        trow.setContentsMargins(14, 9, 14, 9)
        trow.setSpacing(14)
        self.toast_text = QLabel("")
        self.toast_text.setStyleSheet("color: white; background: transparent;"
                                      " border: none; font-size: 13px;")
        trow.addWidget(self.toast_text)
        self.toast_links = QHBoxLayout()
        self.toast_links.setSpacing(12)
        trow.addLayout(self.toast_links)
        self.toast_box.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.toast_box.hide)

    # states
    def show_empty(self):
        self.tag.hide()
        self.choose_host.show()
        self.card.setText(
            "<div style='font-size:26px; font-weight:700; color:%s'>%s</div>"
            "<p>%s</p><p style='color:%s'>%s</p>"
            "<p style='color:%s'>1 %s &nbsp;·&nbsp; 2 %s &nbsp;·&nbsp; 3 %s</p>"
            % (theme.TEXT, i18n.t("Attach a 3D model"),
               i18n.t(".step / .stp — several at once is fine. It is "
                      "measured on this machine; no AI ever sees the file."),
               theme.NEUTRAL[500],
               i18n.t("or drop them anywhere on this window"),
               theme.NEUTRAL[600], i18n.t("Attach"),
               i18n.t("Pick Draft · Ask · Edit"), i18n.t("Run")))
        self.stack.setCurrentWidget(self.page)

    def show_waiting(self, names: str):
        self.tag.hide()
        self.choose_host.hide()
        self.card.setText(
            "<div style='font-size:20px; font-weight:700; color:%s'>%s</div>"
            "<p>%s</p>" % (theme.TEXT, names,
                           i18n.t("Ready. Choose what to do below, then "
                                  "press the button at the bottom right.")))
        self.stack.setCurrentWidget(self.page)

    def show_measuring(self, name: str, lines: list):
        self.tag.hide()
        self.choose_host.hide()
        body = "".join(
            f"<div style='color:{theme.TEXT if i < len(lines) - 1 else theme.INFO_INK};'>"
            f"{'✓' if i < len(lines) - 1 else '◌'}&nbsp; {ln}</div>"
            for i, ln in enumerate(lines[-6:]))
        self.card.setText(
            "<div style='font-size:18px; font-weight:700; color:%s'>%s %s</div>"
            "<div style='text-align:left'><p>%s</p></div>"
            "<p style='color:%s'>%s</p>"
            % (theme.TEXT, i18n.t("Measuring"), name, body, theme.NEUTRAL[500],
               i18n.t("Stays on this machine.")))
        self.stack.setCurrentWidget(self.page)

    def show_note(self, title: str, text: str):
        self.tag.hide()
        self.choose_host.hide()
        self.card.setText("<div style='font-size:18px; font-weight:700;"
                          f" color:{theme.TEXT}'>{title}</div><p>{text}</p>")
        self.stack.setCurrentWidget(self.page)

    def show_sheet(self, path: str, tag: str) -> bool:
        if not self.sheet.set_image(path):
            return False
        self.stack.setCurrentWidget(self.sheet)
        self.tag.setText(tag)
        self.tag.adjustSize()
        self.tag.move(14, 12)
        self.tag.show()
        self.tag.raise_()
        return True

    # toast
    def toast(self, text: str, links: list, seconds: int = 9):
        while self.toast_links.count():
            item = self.toast_links.takeAt(0)
            if item.widget():
                _discard(item.widget())
        self.toast_text.setText(text)
        for label, fn in links:
            a = Link(label, "#7dd3fc")
            a.clicked.connect(fn)
            self.toast_links.addWidget(a)
        for w in self.toast_box.findChildren(QLabel):
            w.ensurePolished()
            w.adjustSize()
        self.toast_box.layout().activate()
        self.toast_box.resize(self.toast_box.sizeHint())
        self._place_toast()
        self.toast_box.show()
        self.toast_box.raise_()
        self._timer.start(seconds * 1000)

    def _place_toast(self):
        self.toast_box.move(max((self.width() - self.toast_box.width()) // 2, 8),
                            self.height() - self.toast_box.height() - 16)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.toast_box.isVisible():
            self._place_toast()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()
                 if u.isLocalFile()]
        if paths:
            self.dropped.emit(paths)
            event.acceptProposedAction()


# ── the right-hand panes ─────────────────────────────────────────────────

class _Rows(QScrollArea):
    """A scrolling stack of rows; subclasses fill self.col."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setStyleSheet("background: transparent;")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.col = QVBoxLayout(host)
        self.col.setContentsMargins(0, 0, 0, 0)
        self.col.setSpacing(0)
        self.col.addStretch(1)
        self.setWidget(host)

    def clear(self):
        while self.col.count() > 1:
            item = self.col.takeAt(0)
            if item.widget():
                _discard(item.widget())

    def add(self, widget: QWidget):
        self.col.insertWidget(self.col.count() - 1, widget)


def _section(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setStyleSheet(
        f"background: {theme.NEUTRAL[100]}; color: {theme.NEUTRAL[500]};"
        " font-size: 10.5px; font-weight: 700; letter-spacing: 1px;"
        " padding: 6px 16px; border: none;")
    return label


def _kv(key: str, value: str, tag: str = "") -> QWidget:
    row = QFrame()
    row.setStyleSheet(f"border: none; border-bottom: 1px solid {_HAIR};"
                      " background: transparent;")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(16, 7, 16, 7)
    k = QLabel(key)
    k.setStyleSheet("border: none; font-size: 13px;")
    lay.addWidget(k)
    lay.addStretch(1)
    if tag:
        lay.addWidget(chip(tag))
    v = QLabel(value)
    v.setWordWrap(True)
    v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    v.setStyleSheet("border: none; font-size: 13px; font-weight: 700;")
    v.setMaximumWidth(250)
    lay.addWidget(v)
    return row


class SpecPanel(_Rows):
    """What was measured, as the mock's key/value register."""

    def set_reports(self, reports: list, k_note: str = ""):
        self.clear()
        if not reports:
            return
        for rep in reports:
            if rep.get("_stub"):
                note = QLabel(i18n.t(
                    "The measurement was not kept with this run. Attach "
                    "{file} again to measure it; the sheet and files from "
                    "that run are still here.").replace("{file}", rep["file"]))
                note.setWordWrap(True)
                note.setStyleSheet(f"color: {theme.NEUTRAL[600]}; padding: 16px;"
                                   " font-size: 12.5px; border: none;")
                self.add(note)
                continue
            title = rep["file"] if len(reports) > 1 else i18n.t("Part")
            self.add(_section(f"{title} · {i18n.t('not measured by an AI')}"))
            ox, oy, oz = rep["overall_mm"]
            self.add(_kv(i18n.t("Mode"), rep["mode"]))
            self.add(_kv(i18n.t("Overall size"),
                         f"{ox:.1f} × {oy:.1f} × {oz:.1f} mm"))
            self.add(_kv(i18n.t("Parts"), str(len(rep["parts"]))))
            for part in rep["parts"]:
                self.add(_section(part["name"]))
                sx, sy, sz = part["size_mm"]
                self.add(_kv(i18n.t("Size"), f"{sx:.1f} × {sy:.1f} × {sz:.1f} mm"))
                if part.get("thickness_mm"):
                    self.add(_kv(i18n.t("Thickness / wall"),
                                 f"{part['thickness_mm']:g} mm"))
                self.add(_kv(i18n.t("Volume"), f"{part['volume_cm3']:.2f} cm³"))
                flat = part.get("flat")
                if flat:
                    fw = flat.get("w_mm") or flat.get("width_mm")
                    fh = flat.get("h_mm") or flat.get("height_mm")
                    if fw and fh:
                        self.add(_kv(i18n.t("Flat size"),
                                     f"{fw:.1f} × {fh:.1f} mm"))
                holes = part.get("holes") or []
                if holes:
                    self.add(_kv(i18n.t("Holes"), " · ".join(
                        f"Ø{h['dia_mm']:g} ×{h['count']}" for h in holes)))
            if rep.get("k_factor"):
                self.add(_section(i18n.t("Bend allowance")))
                self.add(_kv(i18n.t("K-factor"), f"{rep['k_factor']:g}", k_note))
            for w in rep.get("warnings") or []:
                note = QLabel("! " + w)
                note.setWordWrap(True)
                note.setStyleSheet("color: #a16207; padding: 6px 16px;"
                                   " font-size: 12px; border: none;")
                self.add(note)


class PlanPanel(QWidget):
    """Edit's plan, in the window: the steps, the review page it wrote, and —
    when there is something to build — a Build bar. Nothing is built until you
    press it. When ChatGPT found nothing Prism can apply by itself, this says
    so, says why, and says what to do next."""

    build_clicked = Signal()
    skip_clicked = Signal()
    refine_clicked = Signal()
    open_review = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.rows = _Rows()
        lay.addWidget(self.rows, stretch=1)
        self.bar = QFrame()
        self.bar.setObjectName("wbBar")
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bar.setStyleSheet(f"#wbBar {{ background: #fff7ed; border: none;"
                               f" border-top: 1px solid {_EDGE}; }}")
        bl = QVBoxLayout(self.bar)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setSpacing(8)
        self.bar_text = QLabel("")
        self.bar_text.setWordWrap(True)
        self.bar_text.setStyleSheet("border: none; font-size: 12.5px;"
                                    " background: transparent;")
        bl.addWidget(self.bar_text)
        self.build_btn = C.button(i18n.t("Build the modified model"), "primary",
                                  on_click=self.build_clicked.emit)
        bl.addWidget(self.build_btn)
        row = QHBoxLayout()
        self.skip_btn = C.button(i18n.t("Not now"), "secondary", small=True,
                                 on_click=self.skip_clicked.emit)
        self.review_btn = C.button(i18n.t("Open review page"), "secondary",
                                   small=True, on_click=self.open_review.emit)
        row.addWidget(self.skip_btn)
        row.addStretch(1)
        row.addWidget(self.review_btn)
        bl.addLayout(row)
        lay.addWidget(self.bar)
        self.bar.hide()

    # the steps -----------------------------------------------------------
    def set_plan(self, plan: dict | None, agent: str = ""):
        self.rows.clear()
        self.bar.hide()
        if not plan:
            empty = QLabel(i18n.t("No plan yet. Choose Edit, say the change, "
                                  "and press the button."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {theme.NEUTRAL[500]}; padding: 16px;")
            self.rows.add(empty)
            return
        if agent:
            # Which AI wrote this plan.
            who = QLabel(f"<span style='color:{theme.badge_color(agent)}'>●</span>"
                         f"&nbsp;{i18n.t('Planned by')} <b>{agent}</b>")
            who.setTextFormat(Qt.RichText)
            who.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 12px;"
                              " padding: 8px 14px 0 14px;")
            self.rows.add(who)
        changes = plan.get("changes", [])
        if not changes:
            self.rows.add(self._nothing())
        for ch in changes:
            what = (f"Ø{ch['dia_mm']:g} → Ø{ch['new_dia_mm']:g} on {ch['part']}"
                    if ch["op"] == "enlarge_hole"
                    else f"{i18n.t('Scale')} {ch['part']} × {ch['factor']:g}")
            self.rows.add(self._step("✓", what, ch.get("why", ""), True))
        for a in plan.get("advice", []):
            self.rows.add(self._step("•", i18n.t("For the designer"), a, False))

    def _nothing(self) -> QWidget:
        wrap = QFrame()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 12, 12, 4)
        card = QFrame()
        card.setObjectName("wbNothing")
        card.setAttribute(Qt.WA_StyledBackground, True)
        card.setStyleSheet("#wbNothing { background: #fefce8; border: 1px solid"
                           " #fde68a; border-radius: 10px; }")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(12, 10, 12, 10)
        cl.setSpacing(6)
        head = QLabel(i18n.t("Nothing to build yet"))
        head.setStyleSheet("font-weight: 700; font-size: 14px; border: none;"
                           " background: transparent;")
        cl.addWidget(head)
        body = QLabel(i18n.t(
            "The reviewing tool did not find a change Prism can apply by "
            "itself — it needs to know exactly which holes, and to what size "
            "(for example “enlarge the Ø10 holes to Ø10.5”), or a scale "
            "factor. Its reasons are below."))
        body.setWordWrap(True)
        body.setStyleSheet("font-size: 12.5px; border: none; background: transparent;")
        cl.addWidget(body)
        btn = C.button(i18n.t("Refine the request"), "secondary", small=True,
                       on_click=self.refine_clicked.emit)
        row = QHBoxLayout()
        row.addWidget(btn)
        row.addStretch(1)
        cl.addLayout(row)
        wl.addWidget(card)
        return wrap

    # the Build bar -----------------------------------------------------
    def ask_to_build(self, count: int, file: str):
        self.bar_text.setText(
            i18n.t("{n} change(s) ready for {file}. Prism builds a COPY and "
                   "re-measures it — the original is never touched.")
            .replace("{n}", str(count)).replace("{file}", file))
        self.build_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.build_btn.show()
        self.skip_btn.show()
        self.bar.show()

    def building(self):
        self.bar_text.setText(i18n.t("Building a copy and re-measuring it…"))
        self.build_btn.setEnabled(False)
        self.skip_btn.setEnabled(False)
        self.bar.show()

    def built(self, name: str):
        self.bar_text.setText(i18n.t("✓ Built {name}. It is in the Models list "
                                     "on the left — carry on from it there.")
                              .replace("{name}", name))
        self.build_btn.hide()
        self.skip_btn.hide()
        self.bar.show()

    def hide_bar(self):
        self.bar.hide()

    @staticmethod
    def _step(mark: str, title: str, sub: str, on: bool) -> QWidget:
        card = QFrame()
        card.setStyleSheet(
            f"background: #ffffff; border: 1px solid {_EDGE}; border-radius: 10px;"
            + ("" if on else " opacity: .6;"))
        lay = QHBoxLayout(card)
        lay.setContentsMargins(12, 10, 12, 10)
        m = QLabel(mark)
        m.setStyleSheet("border: none; font-weight: 800; color: #15803d;"
                        if on else "border: none; color: #71717a;")
        lay.addWidget(m, 0, Qt.AlignTop)
        col = QVBoxLayout()
        t = QLabel(title)
        t.setWordWrap(True)
        t.setStyleSheet("border: none; font-weight: 700; font-size: 13px;")
        col.addWidget(t)
        if sub:
            sl = QLabel(sub)
            sl.setWordWrap(True)
            sl.setStyleSheet(f"border: none; color: {theme.NEUTRAL[500]};"
                             " font-size: 12px;")
            col.addWidget(sl)
        lay.addLayout(col, stretch=1)
        wrap = QFrame()
        wl = QVBoxLayout(wrap)
        wl.setContentsMargins(12, 6, 12, 0)
        wl.addWidget(card)
        return wrap


_KIND = {".xlsx": ("XLSX", "#dcfce7", "#166534"), ".png": ("PNG", "#e0f2fe", "#075985"),
         ".txt": ("TXT", "#e5e5ea", "#3f3f46"), ".json": ("JSON", "#fef9c3", "#854d0e"),
         ".html": ("HTML", "#ede9fe", "#5b21b6"), ".step": ("STEP", "#ffedd5", "#9a3412"),
         ".stp": ("STEP", "#ffedd5", "#9a3412"), ".svg": ("SVG", "#e0f2fe", "#075985"),
         ".pdf": ("PDF", "#fee2e2", "#991b1b"), ".csv": ("CSV", "#dcfce7", "#166534")}


def describe(name: str) -> tuple[str, str]:
    """(group, one-line meaning) for a file Prism wrote, from its name."""
    n = name.lower()
    if "conversation" in n:
        return i18n.t("Ask / Edit"), i18n.t("kept so Ask and Edit can continue")
    if "change review" in n:
        return i18n.t("Edit"), i18n.t("the plan, as reviewed")
    if "modified" in n and n.endswith((".step", ".stp")):
        return i18n.t("Edit"), i18n.t("the new model — open in your CAD")
    if "after change" in n or "after" in n and "dimensions" in n:
        return i18n.t("Edit"), i18n.t("re-measured after the change, not predicted")
    if "dimensions" in n:
        return i18n.t("Measured"), i18n.t("every dimension, hole and bend")
    if "drawing sheet" in n:
        return i18n.t("Measured"), i18n.t("the dimensioned drawing sheet")
    return i18n.t("Other"), ""


class FilesPanel(QWidget):
    change_folder = Signal()
    open_folder = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        bar = QFrame()
        bar.setStyleSheet(f"background: {theme.NEUTRAL[100]}; border: none;"
                          f" border-bottom: 1px solid {_HAIR};")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 10, 12, 10)
        col = QVBoxLayout()
        col.setSpacing(0)
        k = QLabel(i18n.t("Saved in"))
        k.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 11.5px;"
                        " border: none; background: transparent;")
        col.addWidget(k)
        self.where = QLabel("")
        self.where.setWordWrap(True)
        self.where.setStyleSheet("font-weight: 700; font-size: 12.5px;"
                                 " border: none; background: transparent;")
        col.addWidget(self.where)
        row.addLayout(col, stretch=1)
        self.btn_open = C.button(i18n.t("Open folder"), "secondary", small=True,
                                 on_click=self.open_folder.emit)
        self.btn_change = C.button(i18n.t("Change…"), "secondary", small=True,
                                   on_click=self.change_folder.emit)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_change)
        lay.addWidget(bar)
        self.rows = _Rows()
        lay.addWidget(self.rows, stretch=1)

    def set_files(self, where: str, files: list, folder_known: bool):
        self.where.setText(where)
        self.btn_open.setEnabled(folder_known)
        self.rows.clear()
        if not files:
            empty = QLabel(i18n.t("Nothing made yet."))
            empty.setStyleSheet(f"color: {theme.NEUTRAL[500]}; padding: 16px;")
            self.rows.add(empty)
            return
        groups: dict[str, list] = {}
        order = ["Measured", "Ask / Edit", "Edit", "Other"]
        for path in files:
            g, sub = describe(os.path.basename(path))
            groups.setdefault(g, []).append((path, sub))
        for g in sorted(groups, key=lambda x: order.index(x) if x in order else 9):
            self.rows.add(_section(g))
            for path, sub in groups[g]:
                self.rows.add(self._row(path, sub))

    @staticmethod
    def _row(path: str, sub: str) -> QWidget:
        ext = os.path.splitext(path)[1].lower()
        label, bg, ink = _KIND.get(ext, ("FILE", "#e5e5ea", "#3f3f46"))
        row = QFrame()
        row.setStyleSheet(f"border: none; border-bottom: 1px solid {_HAIR};"
                          " background: transparent;")
        row.setCursor(Qt.PointingHandCursor)
        # Anywhere on the row opens the file; "Show" below reveals it in the
        # folder instead.
        row.mousePressEvent = lambda e, p=path: (
            paths.open_file(p) if e.button() == Qt.LeftButton else None)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(16, 8, 16, 8)
        lay.setSpacing(10)
        c = QLabel(label)
        c.setFixedWidth(44)
        c.setAlignment(Qt.AlignCenter)
        c.setStyleSheet(f"background: {bg}; color: {ink}; border-radius: 6px;"
                        " font-size: 10px; font-weight: 800; padding: 6px 0;"
                        " border: none;")
        lay.addWidget(c, 0, Qt.AlignTop)
        if ext in (".png", ".jpg", ".jpeg"):
            # The picture itself, not only its name — click it to open it big.
            pix = QPixmap(path)
            if not pix.isNull():
                thumb = QLabel()
                thumb.setPixmap(pix.scaled(64, 48, Qt.KeepAspectRatio,
                                           Qt.SmoothTransformation))
                thumb.setFixedSize(68, 52)
                thumb.setAlignment(Qt.AlignCenter)
                thumb.setStyleSheet(f"border: 1px solid {_EDGE};"
                                    " border-radius: 6px; background: white;")
                lay.addWidget(thumb, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        name = QLabel(os.path.basename(path))
        name.setToolTip(path)
        name.setWordWrap(True)
        name.setStyleSheet("font-size: 13px; font-weight: 700; border: none;")
        col.addWidget(name)
        if sub:
            s = QLabel(sub)
            s.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12px;"
                            " border: none;")
            col.addWidget(s)
        links = QHBoxLayout()
        links.setSpacing(14)
        for label, which in ((i18n.t("Open"), "o"), (i18n.t("Show"), "s")):
            lk = Link(label)
            lk.clicked.connect(
                lambda w=which, p=path: paths.open_file(
                    p if w == "o" else os.path.dirname(p)))
            links.addWidget(lk)
        links.addStretch(1)
        col.addLayout(links)
        lay.addLayout(col, stretch=1)
        return row


# ── the chat ─────────────────────────────────────────────────────────────

class _Markdown(QTextBrowser):
    """An AI answer rendered as Markdown, sized to its content so the chat
    scrolls as one page instead of a box inside a box."""

    # Sized at the app's own BODY level (15px, up from this box's old
    # hardcoded 13px) — this is the one place an AI answer IS the screen,
    # so it reads at the app's normal reading size, not a caption size.
    _CSS = ("body { line-height: 1.5; }"
            "p { margin: 0 0 10px 0; }"
            "p:last-child { margin-bottom: 0; }"
            "ul, ol { margin: 4px 0 10px 0; padding-left: 22px; }"
            "li { margin-bottom: 5px; }"
            "strong, b { font-weight: 700; }"
            "table { border-collapse: collapse; margin: 10px 0; }"
            "th, td { border: 1px solid #d1d1d6; padding: 6px 10px; }"
            "th { background-color: #f5f5f7; }"
            "h1 { font-size: 20px; } h2 { font-size: 18px; } h3 { font-size: 16px; }"
            "h1, h2, h3 { font-weight: 700; margin-top: 14px; margin-bottom: 6px; }"
            "h1:first-child, h2:first-child, h3:first-child { margin-top: 0; }"
            "hr { color: #e5e5ea; }")

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setOpenExternalLinks(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet("background: transparent; border: none;"
                           f" {theme.type_css('BODY')}")
        self.document().setDocumentMargin(2)
        self.document().setDefaultStyleSheet(self._CSS)
        self.setMarkdown(text)
        self._cap = 0
        self.fit()

    def set_cap(self, px: int):
        self._cap = px
        self.fit()

    def natural_height(self, width: int = 0) -> int:
        m = self.contentsMargins()
        # Padding from the app's style sheet is part of the box too.
        outer = width or self.width()
        width = (outer - m.left() - m.right()) if outer > 40 else 320
        self.document().setTextWidth(max(width, 120))
        return int(self.document().size().height()) + m.top() + m.bottom() + 8

    def fit(self, width: int = 0):
        if getattr(self, "_fitting", False):
            return
        self._fitting = True
        try:
            h = self.natural_height(width)
            h = min(h, self._cap) if self._cap else h
            if h != self.height() or self.minimumHeight() != h:
                self.setFixedHeight(h)
        finally:
            self._fitting = False

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # The width the widget has NOW, not the viewport's from before this
        # resize — measuring with the old one wrapped to fewer lines than the
        # text really takes and cut the last lines off.
        self.fit(event.size().width())
        QTimer.singleShot(0, self.fit)        # and once more when it has settled

    def showEvent(self, event):
        super().showEvent(event)
        # The style sheet's font size is applied once the widget is shown;
        # measure again then, or the text is taller than the box it was
        # measured for and its last lines are cut off.
        QTimer.singleShot(0, self.fit)


class _Turn(QFrame):
    """One run in the chat. Collapsed it is a single line you can scan — the
    number, what it was, what was asked, when; open it for the question, the
    answer, the sheet and what was built."""

    FOLD = 230

    def __init__(self, turn: dict, number: int, parent=None):
        super().__init__(parent)
        self.turn = turn
        self.number = number
        self.setObjectName("wbTurn")
        self.setAttribute(Qt.WA_StyledBackground, True)
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)

        # ── the line you scan ─────────────────────────────────────────
        self.head = QFrame()
        self.head.setObjectName("wbTurnHead")
        self.head.setAttribute(Qt.WA_StyledBackground, True)
        self.head.setCursor(Qt.PointingHandCursor)
        hl = QHBoxLayout(self.head)
        hl.setContentsMargins(10, 8, 10, 8)
        hl.setSpacing(8)
        tone = {"Draft": "info", "Ask": "ok", "Edit": "warn"}.get(
            turn["action"], "neutral")
        hl.addWidget(chip(f"{number} · {turn['action']}", tone), 0, Qt.AlignTop)
        if turn.get("agent") and turn["action"] in ("Ask", "Edit"):
            hl.addWidget(chip(turn["agent"], "neutral"), 0, Qt.AlignTop)
        text = turn["question"] or (
            i18n.t("Measured and drew the dimensioned sheet")
            if turn["action"] == "Draft" else turn["file"])
        self.summary = QLabel(text.replace("\n", " "))
        self.summary.setStyleSheet("font-size: 12.5px; border: none;"
                                   " background: transparent;")
        self.summary.setMinimumWidth(40)
        self.summary.setSizePolicy(self.summary.sizePolicy().horizontalPolicy(),
                                   self.summary.sizePolicy().verticalPolicy())
        self._full = text.replace("\n", " ")
        hl.addWidget(self.summary, 1)
        when = QLabel(turn["time"] or turn["when"])
        when.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 11.5px;"
                           " border: none; background: transparent;")
        hl.addWidget(when)
        self.arrow = QLabel("▸")
        self.arrow.setStyleSheet(f"color: {theme.NEUTRAL[500]}; border: none;"
                                 " background: transparent;")
        hl.addWidget(self.arrow)
        col.addWidget(self.head)
        self.head.mousePressEvent = lambda _e: self.set_open(not self._open)

        # ── the detail ────────────────────────────────────────────────
        self.body = QWidget()
        bl = QVBoxLayout(self.body)
        bl.setContentsMargins(10, 0, 10, 10)
        bl.setSpacing(8)
        if turn["file"]:
            frow = QHBoxLayout()
            frow.addWidget(chip(turn["file"] if len(turn["file"]) < 34
                                else turn["file"][:31] + "…",
                                "warn" if turn.get("edited") else "neutral"))
            full = QLabel(turn["when"])
            full.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 11.5px;"
                               " border: none; background: transparent;")
            frow.addWidget(full)
            frow.addStretch(1)
            bl.addLayout(frow)
        if turn["question"]:
            bl.addWidget(self._bubble(i18n.t("You"), turn["question"], mine=True))
        self.answer = None
        self.more = None
        if turn["answer"]:
            from addons.step import sessions as SES
            self.answer = _Markdown(SES.normalize_markdown(turn["answer"]))
            bl.addWidget(self._bubble(
                turn.get("agent") or i18n.t("Answer"), "", mine=False,
                body=self.answer, agent=turn.get("agent", "")))
            self.more = Link(i18n.t("Show more  ▾"))
            self.more.clicked.connect(self._toggle)
            self.more.hide()
            bl.addWidget(self.more, 0, Qt.AlignLeft)
        # The sheet, once, on the run that drew it — not repeated on every card.
        if turn["action"] == "Draft" and turn.get("sheet"):
            thumb = QLabel()
            pix = QPixmap(turn["sheet"])
            if not pix.isNull():
                thumb.setPixmap(pix.scaledToWidth(150, Qt.SmoothTransformation))
                thumb.setCursor(Qt.PointingHandCursor)
                thumb.setToolTip(i18n.t(
                    "Click to open the drawing in its own window"))
                thumb.setStyleSheet(f"border: 1px solid {_EDGE}; border-radius:"
                                    " 6px; background: white;")
                thumb.mousePressEvent = lambda _e, p=turn["sheet"]: \
                    paths.open_file(p)
                bl.addWidget(thumb, 0, Qt.AlignLeft)
        for f in turn.get("followups", []):
            bl.addWidget(self._bubble(i18n.t("You"), f.get("q", ""), mine=True))
            bl.addWidget(self._bubble(
                f.get("agent") or i18n.t("Answer"), "", mine=False,
                agent=f.get("agent", ""),
                body=_Markdown(__import__("addons.step.sessions", fromlist=["x"])
                               .normalize_markdown(f.get("a", "")))))
        for styled in turn.get("styled", []):
            bl.addWidget(self._built(styled, i18n.t("STYLED COPY"), "info"))
        for built in turn.get("built", []):
            bl.addWidget(self._built(built))
        col.addWidget(self.body)
        self._folded = False
        self._open = True
        self.set_open(False)

    def set_open(self, on: bool):
        self._open = on
        self.body.setVisible(on)
        self.arrow.setText("▾" if on else "▸")
        edge = theme.NEUTRAL[400] if on else _EDGE
        self.setStyleSheet(
            f"#wbTurn {{ background: #ffffff; border: 1px solid {edge};"
            " border-radius: 10px; }"
            f"#wbTurnHead {{ background: {theme.NEUTRAL[100] if on else '#ffffff'};"
            f" border: none; border-radius: 10px; }}")
        if on:
            QTimer.singleShot(0, self.settle)

    @staticmethod
    def _bubble(who: str, text: str, mine: bool, body: QWidget | None = None,
                agent: str = ""):
        box = QFrame()
        box.setObjectName("wbBubble")
        box.setAttribute(Qt.WA_StyledBackground, True)
        bg = theme.NEUTRAL[100] if not mine else "#eef2ff"
        box.setStyleSheet(f"#wbBubble {{ background: {bg}; border: none;"
                          " border-radius: 8px; }")
        lay = QVBoxLayout(box)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        if agent:
            # Which AI gave this answer: its name, with its own colour.
            label = QLabel(f"<span style='color:{theme.badge_color(agent)}'>●</span>"
                           f"&nbsp;{who.upper()}")
            label.setTextFormat(Qt.RichText)
        else:
            label = QLabel(who.upper())
        label.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 10.5px;"
                            " font-weight: 700; letter-spacing: 1px;"
                            " border: none; background: transparent;")
        lay.addWidget(label)
        if body is not None:
            lay.addWidget(body)
        else:
            t = QLabel(text)
            t.setWordWrap(True)
            t.setTextInteractionFlags(Qt.TextSelectableByMouse)
            t.setStyleSheet(f"border: none; background: transparent;"
                            f" {theme.type_css('BODY')}")
            lay.addWidget(t)
        return box

    @staticmethod
    def _built(path: str, label: str = "", tone: str = "warn") -> QWidget:
        row = QFrame()
        row.setObjectName("wbBuilt")
        row.setAttribute(Qt.WA_StyledBackground, True)
        row.setStyleSheet("#wbBuilt { background: #ffedd5; border: none;"
                          " border-radius: 8px; }")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(10, 7, 10, 7)
        lay.setSpacing(10)
        lay.addWidget(chip(label or i18n.t("BUILT"), tone))
        name = QLabel(os.path.basename(path))
        name.setWordWrap(True)
        name.setToolTip(path)
        name.setStyleSheet("font-size: 12.5px; font-weight: 700; border: none;"
                           " background: transparent;")
        lay.addWidget(name, 1)
        for caption, target in ((i18n.t("Open"), path),
                                (i18n.t("Show"), os.path.dirname(path))):
            lk = Link(caption)
            lk.clicked.connect(lambda t=target: paths.open_file(t))
            lay.addWidget(lk)
        return row

    def _reelide(self):
        fm = self.summary.fontMetrics()
        self.summary.setText(fm.elidedText(
            self._full, Qt.ElideRight, max(self.summary.width() - 4, 40)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reelide()

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._reelide)

    def settle(self):
        """After the card is open and has a width: fold a long answer."""
        if self.answer is None or not self._open:
            return
        long = self.answer.natural_height() > self.FOLD + 60
        self.more.setVisible(long)
        if long and not self._folded:
            self._fold(True)

    def _fold(self, on: bool):
        self._folded = on
        self.answer.set_cap(self.FOLD if on else 0)
        self.more.setText(i18n.t("Show more  ▾") if on else i18n.t("Show less  ▴"))

    def _toggle(self):
        self._fold(not self._folded)


class ChatView(QWidget):
    """Every run on one part, organised to scan: a toolbar (count, expand
    all, latest), a rail of numbered dots to jump along, and below it the runs
    as one-line rows — grouped by day, the newest open, the rest folded."""

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        bar = QFrame()
        bar.setStyleSheet(f"border: none; border-bottom: 1px solid {_HAIR};")
        bl = QVBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-size: 13px; font-weight: 700; border: none;")
        top.addWidget(self.summary)
        top.addStretch(1)
        self.toolbar = top                      # the screen adds its buttons here
        self.expand_link = Link(i18n.t("Expand all"))
        self.expand_link.clicked.connect(self._toggle_all)
        top.addWidget(self.expand_link)
        latest = Link(i18n.t("Newest ↑"))
        latest.clicked.connect(self.scroll_latest)
        top.addWidget(latest)
        bl.addLayout(top)

        self.jump_host = QWidget()
        self.jump = QHBoxLayout(self.jump_host)
        self.jump.setContentsMargins(0, 0, 0, 0)
        self.jump.setSpacing(5)
        self.jump_scroll = QScrollArea()
        self.jump_scroll.setWidgetResizable(True)
        self.jump_scroll.setFrameShape(QFrame.NoFrame)
        self.jump_scroll.setFixedHeight(30)
        self.jump_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.jump_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.jump_scroll.setStyleSheet("background: transparent;")
        self.jump_scroll.setWidget(self.jump_host)
        bl.addWidget(self.jump_scroll)
        outer.addWidget(bar)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("background: transparent;")
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        self.col = QVBoxLayout(host)
        self.col.setContentsMargins(10, 8, 10, 10)
        self.col.setSpacing(6)
        self.col.addStretch(1)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll, stretch=1)
        self.cards: list[_Turn] = []
        self._extras: list[QWidget] = []

    def set_turns(self, turns: list):
        for w in self.cards + self._extras:
            _discard(w)
        self.cards, self._extras = [], []
        while self.jump.count():
            item = self.jump.takeAt(0)
            if item.widget():
                _discard(item.widget())
        day = ""
        # Newest first: what you just did is at the top, no scrolling to find it.
        for n, turn in reversed(list(enumerate(turns, 1))):
            if turn["day"] != day:
                day = turn["day"]
                label = QLabel(day.upper())
                label.setStyleSheet(
                    f"color: {theme.NEUTRAL[500]}; font-size: 10.5px;"
                    " font-weight: 700; letter-spacing: 1px; padding: 6px 2px 0 2px;"
                    " border: none; background: transparent;")
                self.col.insertWidget(self.col.count() - 1, label)
                self._extras.append(label)
            card = _Turn(turn, n)
            self.col.insertWidget(self.col.count() - 1, card)
            self.cards.append(card)          # newest first, like the screen
            tone = {"Draft": "#bae6fd", "Ask": "#bbf7d0", "Edit": "#fed7aa"}.get(
                turn["action"], theme.NEUTRAL[300])
            dot = QPushButton(str(n))
            dot.setCursor(Qt.PointingHandCursor)
            dot.setFixedSize(24, 24)
            dot.setToolTip(f"{turn['action']} · {turn['when']}"
                           + (f"\n{turn['question'][:80]}" if turn["question"] else ""))
            dot.setStyleSheet(
                f"QPushButton {{ background: {tone}; border: 1px solid {_EDGE};"
                " border-radius: 12px; font-size: 11px; font-weight: 700;"
                " padding: 0px; min-width: 24px; max-width: 24px; min-height: 24px;"
                " max-height: 24px; color: #09090b; }"
                f"QPushButton:hover {{ border-color: {theme.ACCENT}; }}")
            dot.clicked.connect(lambda _=False, i=n - 1: self.open_turn(i))
            self.jump.addWidget(dot)
        self.jump.addStretch(1)
        if self.cards:
            self.cards[0].set_open(True)             # the newest, open at the top
        self.summary.setText(
            i18n.t("{n} runs").replace("{n}", str(len(turns))) if turns else "")
        self.expand_link.setText(i18n.t("Expand all"))
        self.expand_link.setVisible(len(turns) > 1)
        QTimer.singleShot(0, self.scroll_latest)

    def _toggle_all(self):
        every = all(c._open for c in self.cards)
        for c in self.cards:
            c.set_open(not every)
        self.expand_link.setText(i18n.t("Collapse all") if not every
                                 else i18n.t("Expand all"))

    def open_turn(self, index: int):
        """Open run number index+1 (1 = the oldest) and bring it into view."""
        card = next((c for c in self.cards if c.number == index + 1), None)
        if card is not None:
            card.set_open(True)
            QTimer.singleShot(30, lambda: self.scroll.verticalScrollBar().setValue(
                max(card.y() - 8, 0)))

    def scroll_latest(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(0))


class Composer(QFrame):
    """Where you carry on the conversation: a follow-up to the answer above,
    sent to whichever tool you pick, or "Build this" to turn it into a change.
    In the window, under the chat — it used to be a pop-up."""

    send = Signal(str, str)         # text, agent key
    build = Signal()

    def __init__(self, choices: list, parent=None):
        super().__init__(parent)
        self.setObjectName("wbComposer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"#wbComposer {{ background: #ffffff; border: none;"
                           f" border-top: 1px solid {_EDGE}; }}")
        from PySide6.QtWidgets import QComboBox, QPlainTextEdit
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(i18n.t(
            "Ask a follow-up question…"))
        self.edit.setFixedHeight(62)
        lay.addWidget(self.edit)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.agent = QComboBox()
        for key, label in choices:
            self.agent.addItem(label, key)
        row.addWidget(self.agent)
        row.addStretch(1)
        # One verb per situation. "Ask" always; "Make a change" only while the
        # person is changing the model (see set_mode).
        self.build_btn = C.button(i18n.t("Make a change"), "secondary", small=True,
                                  on_click=self.build.emit)
        self.build_btn.setToolTip(i18n.t(
            "Turn the answer above into an exact change plan, then build it."))
        self.build_btn.hide()
        row.addWidget(self.build_btn)
        self.send_btn = C.button(i18n.t("Ask"), "primary", small=True,
                                 on_click=self._send)
        row.addWidget(self.send_btn)
        lay.addLayout(row)
        self.note = QLabel("")
        self.note.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12px;"
                                " border: none;")
        self.note.setWordWrap(True)
        self.note.hide()
        lay.addWidget(self.note)

    def _send(self):
        text = self.edit.toPlainText().strip()
        if text:
            self.send.emit(text, self.agent.currentData() or "Claude Haiku 5.5")

    def set_busy(self, busy: bool, note: str = ""):
        for w in (self.edit, self.agent, self.build_btn, self.send_btn):
            w.setEnabled(not busy)
        self.note.setText(note)
        self.note.setVisible(busy and bool(note))

    def set_mode(self, changing: bool):
        """Ask: just "Ask". Changing the model: "Ask" for a question about the
        answer and "Make a change" to plan and build from it."""
        self.build_btn.setVisible(changing)
        self.edit.setPlaceholderText(i18n.t(
            "Ask a follow-up, or describe what to change and press Make a change…")
            if changing else i18n.t("Ask a follow-up question…"))

    def clear(self):
        self.edit.clear()

    def set_agent(self, key: str):
        i = self.agent.findData(key)
        if i >= 0:
            self.agent.setCurrentIndex(i)
