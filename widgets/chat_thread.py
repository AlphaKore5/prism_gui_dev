"""The task page as a conversation: what a message looks like.

The run screen (widgets/output_panel.py) lays these between its step cards:

    UserBubble    what the person typed (and the files they sent with it)
    AnswerBubble  what Prism AI answered, as real Markdown (the same document
                  styling as the reader dialog), with Copy and Open as a page
    NoteLine      a plain line from Prism itself (a stop, an error)
    ChatComposer  the box at the bottom: type, attach, send

Nothing here knows about runs, the server or the History store; the panel and
the window own that. The composer only says what is wrong when it cannot send.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QTextBrowser, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QFont, QFontMetrics

import i18n
import theme
import viewer
from widgets import controls as C
from widgets import icons

MAX_BUBBLE = 640           # a message is a column, not the window's width


class _Auto(QTextBrowser):
    """A read-only browser that is exactly as tall as its text."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        viewer.route_links(self)
        self.document().documentLayout().documentSizeChanged.connect(
            lambda _s: self._fit())

    def _fit(self):
        width = max(1, self.viewport().width())
        if abs(self.document().textWidth() - width) > 1:
            self.document().setTextWidth(width)
        self.setFixedHeight(int(self.document().size().height()) + 12)
        self.verticalScrollBar().setValue(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def showEvent(self, event):
        super().showEvent(event)
        self._fit()


def _row(widget: QWidget, right: bool) -> QWidget:
    """A message aligned to one side, never wider than MAX_BUBBLE."""
    host = QWidget()
    host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    lay = QHBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, theme.SPACE_3)
    lay.setSpacing(0)
    widget.setMaximumWidth(MAX_BUBBLE)
    if right:
        lay.addStretch(1)
        lay.addWidget(widget)
    else:
        # The answer grows first, up to MAX_BUBBLE; the spacer takes the rest.
        # With the spacer at stretch 1 and the answer at 0, the spacer won
        # every spare pixel and an answer sat at its 420 px minimum.
        lay.addWidget(widget, 1)
        lay.addStretch(0)
    return host


class UserBubble(QFrame):
    def __init__(self, text: str, files: list | None = None, parent=None):
        super().__init__(parent)
        self.setObjectName("userBubble")
        self.setStyleSheet(
            f"#userBubble {{ background: {theme.INK}; border-radius: {theme.R_CARD}px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4,
                               theme.SPACE_3)
        col.setSpacing(theme.SPACE_1)
        self.text_label = QLabel(text)
        self.text_label.setWordWrap(True)
        self.text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.text_label.setStyleSheet(
            f"color: #ffffff; background: transparent; font-size: 14px;")
        # A word-wrapped label asks for a sliver; give it the width its text
        # needs, up to a column.
        font = QFont(self.text_label.font())
        font.setPixelSize(14)
        wide = QFontMetrics(font).horizontalAdvance(text or "") + 12
        self.text_label.setMinimumWidth(max(60, min(MAX_BUBBLE - 2 * theme.SPACE_4, wide)))
        col.addWidget(self.text_label)
        self.files = [os.path.basename(str(f)) or str(f) for f in (files or [])]
        if self.files:
            names = QLabel("\U0001F4CE " + ", ".join(self.files))
            names.setWordWrap(True)
            names.setStyleSheet(
                f"color: {theme.FAINT}; background: transparent; font-size: 12px;")
            col.addWidget(names)


class AnswerBubble(QFrame):
    """Prism AI's reply, rendered as Markdown. Copy keeps the raw text."""

    def __init__(self, text: str, by: str = "", title: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("answerBubble")
        self.setStyleSheet(
            f"#answerBubble {{ background: {theme.CARD}; border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.HAIRLINE}; }}")
        self._text = text or ""
        self._title = title or by or i18n.t("Answer")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.setMinimumWidth(420)
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4,
                               theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        if by:
            who = QLabel(by)
            who.setStyleSheet(theme.type_css("META", theme.MUTE)
                              + " background: transparent;")
            col.addWidget(who)
        self.reader = _Auto()
        self.reader.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none; color: {theme.TEXT}; }}")
        try:
            from dialogs.completion_dialog import _READER_CSS    # one look for every reader
            self.reader.document().setDefaultStyleSheet(_READER_CSS)
        except Exception:                                       # noqa: BLE001
            pass
        self.reader.document().setDocumentMargin(2)
        self.reader.document().setMarkdown(self._text)
        col.addWidget(self.reader)
        acts = QHBoxLayout()
        acts.setSpacing(theme.SPACE_2)
        self.copy_btn = C.button(i18n.t("Copy"), "secondary", "copy", small=True,
                                 on_click=self._copy)
        acts.addWidget(self.copy_btn)
        self.page_btn = C.button(i18n.t("Open as a page"), "secondary", "external",
                                 small=True, on_click=self._open_page)
        self.page_btn.setToolTip(i18n.t(
            "Read the whole answer in its own window, and save it as PDF, "
            "Word or text."))
        acts.addWidget(self.page_btn)
        acts.addStretch(1)
        col.addLayout(acts)

    def text(self) -> str:
        return self._text

    def _copy(self):
        QApplication.clipboard().setText(self._text)

    def _open_page(self):
        from dialogs.completion_dialog import StageResultDialog
        StageResultDialog("content", "", self._text, "", self.window()).exec()


class NoteLine(QLabel):
    def __init__(self, text: str, bad: bool = False, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(theme.type_css("SUPPORT", theme.ERR_INK if bad else theme.MUTE)
                           + " background: transparent;")


def user_row(text: str, files=None) -> tuple[QWidget, UserBubble]:
    bubble = UserBubble(text, files)
    return _row(bubble, True), bubble


def answer_row(text: str, by: str = "", title: str = "") -> tuple[QWidget, AnswerBubble]:
    bubble = AnswerBubble(text, by, title)
    return _row(bubble, False), bubble


class ChatComposer(QFrame):
    """Type, attach, send. `submitted(text, paths)` fires once per send.

    While Prism cannot take a message (a step is running, nothing to continue)
    `set_blocked(reason)` greys it out AND says why, in the box and on the
    button, so a dead control is never a mystery.
    """

    submitted = Signal(str, list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatComposer")
        self.setStyleSheet(
            f"#chatComposer {{ background: {theme.CARD}; border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.HAIRLINE}; }}")
        self._paths: list[str] = []
        self._reason = ""
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_3,
                               theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)

        self.chips_host = QWidget()
        self.chips = C.FlowLayout(self.chips_host, margin=0, h_space=6, v_space=6)
        self.chips_host.setVisible(False)
        col.addWidget(self.chips_host)

        self.edit = C.SubmitTextEdit()
        self.edit.setObjectName("chatInput")
        self.edit.setAcceptRichText(False)
        self.edit.setFixedHeight(64)
        self.edit.setFrameShape(QFrame.NoFrame)
        self.edit.setStyleSheet(
            f"QTextEdit {{ background: transparent; border: none; color: {theme.TEXT};"
            f" font-size: 14px; }}")
        self.edit.submitted.connect(self._send)
        self.edit.textChanged.connect(self._sync)
        col.addWidget(self.edit)

        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE_2)
        self.attach_btn = C.button(i18n.t("Attach"), "secondary", "paperclip",
                                   small=True, on_click=self._pick)
        self.attach_btn.setToolTip(i18n.t(
            "Add a picture, a PDF or a document to your next message."))
        bar.addWidget(self.attach_btn)
        self.hint = QLabel("")
        self.hint.setStyleSheet(theme.type_css("META", theme.MUTE)
                                + " background: transparent;")
        bar.addWidget(self.hint, 1)
        from widgets.home_panel import _SendButton           # Home's own send button
        self.send_btn = _SendButton()
        self.send_btn.clicked.connect(self._send)
        bar.addWidget(self.send_btn)
        col.addLayout(bar)
        self.set_blocked("")

    # -- state -------------------------------------------------------------
    def set_blocked(self, reason: str):
        """'' = ready. Otherwise the plain reason nothing can be sent now."""
        self._reason = reason or ""
        blocked = bool(self._reason)
        self.edit.setReadOnly(blocked)
        self.attach_btn.setEnabled(not blocked)
        self.edit.setPlaceholderText(
            self._reason if blocked else
            i18n.t("Write to Prism AI, ask for a change, or ask for a PDF or "
                   "Word copy…"))
        self.edit.setToolTip(self._reason)
        self.hint.setText(self._reason)
        if blocked:
            self.attach_btn.setToolTip(self._reason)
        self._sync()

    def blocked_reason(self) -> str:
        return self._reason

    def _sync(self):
        if self._reason:
            self.send_btn.setToolTip(self._reason)
        elif not self.edit.toPlainText().strip():
            self.send_btn.setToolTip(i18n.t("Type a message first."))
        else:
            self.send_btn.setToolTip(i18n.t("Send"))

    # -- files -------------------------------------------------------------
    def add_paths(self, paths: list):
        for p in paths:
            if p and p not in self._paths:
                self._paths.append(p)
        self._draw_chips()

    def paths(self) -> list[str]:
        return list(self._paths)

    def _pick(self):
        paths, _ = QFileDialog.getOpenFileNames(self, i18n.t("Attach file(s)"))
        if paths:
            self.add_paths(paths)

    def _draw_chips(self):
        while self.chips.count():
            item = self.chips.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for path in self._paths:
            chip = QFrame()
            chip.setObjectName("composerChip")
            chip.setStyleSheet(
                f"#composerChip {{ background: {theme.WELL}; border: 1px solid {theme.HAIRLINE};"
                f" border-radius: 8px; }}")
            row = QHBoxLayout(chip)
            row.setContentsMargins(8, 3, 6, 3)
            row.setSpacing(6)
            name = QLabel(os.path.basename(path))
            name.setStyleSheet("font-size: 12px; background: transparent;")
            row.addWidget(name)
            x = QPushButton("×")
            x.setFixedSize(18, 18)
            x.setCursor(Qt.PointingHandCursor)
            x.setToolTip(i18n.t("Remove"))
            x.setStyleSheet("border: none; background: transparent; color: #71717a;"
                            " font-size: 15px;")
            x.clicked.connect(lambda *_, p=path: self.remove_path(p))
            row.addWidget(x)
            self.chips.addWidget(chip)
        self.chips_host.setVisible(bool(self._paths))

    def remove_path(self, path: str):
        if path in self._paths:
            self._paths.remove(path)
            self._draw_chips()

    # -- send --------------------------------------------------------------
    def _send(self):
        if self._reason:
            return
        text = self.edit.toPlainText().strip()
        if not text:
            self.hint.setText(i18n.t("Type a message first."))
            return
        paths = list(self._paths)
        self.edit.clear()
        self._paths = []
        self._draw_chips()
        self.hint.setText("")
        self.submitted.emit(text, paths)

    def sizeHint(self) -> QSize:
        return super().sizeHint()
