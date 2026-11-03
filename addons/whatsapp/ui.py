"""Small pieces every WhatsApp screen needs, so each screen is about its own job.

  call()      run one platform call off the UI thread and say what went wrong in words
  Note        a line of status text that is quiet, good news or an error
  field()     a small caps label over a control, with an optional hint under it
  card()      a titled card with a body column
  discard()   take a widget out of its layout NOW (a deferred delete alone leaves it painting where it was)
  confirm()   a yes/no question with a safe default
  copy_text() put text on the clipboard and say so
"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QSizePolicy, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp.workers import PlatformWorker
from widgets import controls as C


def call(owner, route: str, data: dict = None, *, done=None, failed=None):
    """One platform call. `done(reply)` on success; `failed(message, detail)` on failure, which by default is shown
    through `owner.say(message, error=True)` when the owner has one. The worker is kept alive on the owner until it ends."""
    w = PlatformWorker(route, data)
    if done is not None:
        w.done.connect(done)
    if failed is not None:
        w.failed.connect(failed)
    elif hasattr(owner, "say"):
        w.failed.connect(lambda m, _d: owner.say(m, error=True))
    keep = owner.__dict__.setdefault("_calls", [])
    keep.append(w)
    finished = getattr(w, "finished", None)
    if finished is not None and hasattr(finished, "connect"):
        finished.connect(lambda w=w: keep.remove(w) if w in keep else None)
    w.start()
    return w


def note(text: str = "") -> "NoteLabel":
    return NoteLabel(text)


class NoteLabel(QLabel):
    """A line of status text: quiet by default, red for an error, green for good news. Hidden when empty."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.set("", "quiet")

    def set(self, text: str, tone: str = "quiet"):
        colour = {"error": theme.ERR_INK, "ok": theme.OK_INK, "warn": theme.WARN_INK}.get(tone, theme.NEUTRAL[600])
        self.setStyleSheet("color: %s; font-size: 13px;" % colour)
        self.setText(text)
        self.setVisible(bool(text))
        self.tone = tone

    def error(self, text: str):
        self.set(text, "error")

    def ok(self, text: str):
        self.set(text, "ok")

    def clear_note(self):
        self.set("", "quiet")


def field(label: str, content, hint: str = "") -> QWidget:
    box = QWidget()
    col = QVBoxLayout(box)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(4)
    col.addWidget(C.label(label.upper(), level="LABEL", colour=theme.NEUTRAL[500]))
    if isinstance(content, (QHBoxLayout, QVBoxLayout)):
        col.addLayout(content)
    else:
        col.addWidget(content)
    if hint:
        col.addWidget(C.label(hint, level="META", colour=theme.NEUTRAL[500], wrap=True))
    return box


def card(title: str, sub: str = "", width: int = 0) -> tuple:
    c = C.Card()
    if width:
        c.setFixedWidth(width)
    col = c.body((theme.SPACE_5,) * 4, theme.SPACE_3)
    if title:
        col.addWidget(C.label(title, level="CARD_TITLE"))
    if sub:
        col.addWidget(C.label(sub, level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
    return c, col


def see_through(widget: QWidget) -> QWidget:
    """Make a scroll area's content widget see-through WITHOUT touching what is inside it.

    `widget.setStyleSheet("background: transparent;")` looks harmless but a rule with no selector applies to the widget and
    every widget inside it, so every primary button in the area lost its black fill (and every card its tint) in the real
    window. Naming the rule after this one widget keeps it to this widget."""
    widget.setObjectName("waSeeThrough")
    widget.setStyleSheet("#waSeeThrough { background: transparent; }")
    return widget


def no_sideways(area):
    """A scroll area that only ever moves up and down.

    Switching the horizontal bar off hides it but does not stop the page sliding sideways: a trackpad swipe, a shift-wheel or a
    focus jump still moves it when something inside is a little wider than the window, and the left edge of the page is then cut off.
    Pinning the position to zero keeps the page where it belongs."""
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    bar = area.horizontalScrollBar()
    bar.valueChanged.connect(lambda value, b=bar: b.setValue(0) if value else None)
    return area


def let_text_wrap(root: QWidget) -> None:
    """Let every wrapping label under `root` be as narrow as the room it is given.

    A wrapping label reports a minimum width near its whole text on one line, so a few of them in a panel make the panel's content wider
    than the panel, and the page slides sideways. Marking the label's width as ignorable lets the layout hand it the width there is and
    the text wraps to it; its height still follows its width."""
    for lab in root.findChildren(QLabel):
        if lab.wordWrap():
            policy = lab.sizePolicy()
            policy.setHorizontalPolicy(QSizePolicy.Ignored)
            lab.setSizePolicy(policy)


class CenterFlow(C.FlowLayout):
    """Widgets in a row, centred, that step down a line when the row runs out of width instead of running out of the panel."""

    def _arrange(self, rect: QRect, *, dry_run: bool) -> int:
        left, top, right, bottom = self.getContentsMargins()
        inner = rect.adjusted(left, top, -right, -bottom)
        lines, line, used = [], [], 0
        for item in self._items:
            widget = item.widget()
            if widget is not None and not widget.isVisibleTo(widget.parentWidget()):
                continue
            hint = item.sizeHint()
            need = hint.width() + (self._h if line else 0)
            if line and used + need > inner.width():
                lines.append((line, used))
                line, used, need = [], 0, hint.width()
            line.append(item)
            used += need
        if line:
            lines.append((line, used))
        y = inner.y()
        for items, width in lines:
            tallest = max(i.sizeHint().height() for i in items)
            x = inner.x() + max(0, (inner.width() - width) // 2)
            for item in items:
                hint = item.sizeHint()
                if not dry_run:
                    item.setGeometry(QRect(x, y + (tallest - hint.height()) // 2, hint.width(), hint.height()))
                x += hint.width() + self._h
            y += tallest + self._v
        return (y - self._v if lines else y) - rect.y() + bottom


def centered_row(*widgets, h_space: int = theme.SPACE_1, v_space: int = theme.SPACE_1) -> QWidget:
    """These widgets side by side and centred, wrapping onto a second line on a narrow panel."""
    holder = QWidget()
    flow = CenterFlow(holder, h_space=h_space, v_space=v_space)
    for w in widgets:
        flow.addWidget(w)
    return holder


def discard(widget) -> None:
    if widget is not None:
        widget.setParent(None)
        widget.deleteLater()


def clear(layout) -> None:
    """Empty a layout, including layouts nested in it."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            discard(item.widget())
        elif item.layout() is not None:
            clear(item.layout())


def confirm(parent, title: str, question: str) -> bool:
    return QMessageBox.question(parent, title, question) == QMessageBox.Yes


def copy_text(parent, text: str, what: str = "") -> None:
    QGuiApplication.clipboard().setText(text)
    C.show_toast(parent, i18n.t("Copied"), what)
