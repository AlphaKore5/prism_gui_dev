"""The conversation itself: message bubbles, day separators, delivery ticks,
and the composer.

Two decisions worth knowing:

  · A bubble's WIDTH is computed from its text, not left to the layout. A
    word-wrapped QLabel inside a stretching layout takes the full column and
    leaves every short message ("Ok, thanks") as a wide pale bar. Measuring the
    wrapped text and fixing the label to that width gives bubbles that hug what
    was said — and fixing the width is also what makes the label's height
    follow it, so nothing clips.
  · A send is OPTIMISTIC. The bubble appears the instant Enter is pressed,
    marked "sending", and settles to sent or to a red "Failed · Retry" — the
    person never sits watching a button while a request travels to a server
    and on to n8n and Meta.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPlainTextEdit,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import media_lib, ui
from addons.whatsapp.chat import clock, day_label, parse_ts
from dialogs.base import PrismDialog
from widgets import controls as C
from widgets import icons

_MAX_TEXT = 4096                      # the licence server's bound on a reply
_GROUP_GAP = timedelta(minutes=3)
_PLACEHOLDER = re.compile(r"^\[(image|video|audio|document|sticker)\]\s*")       # the words stored for a message that is only a file
_TEMPLATE = re.compile(r"^\[template\]\s*(\S.*)$")                                   # the service stores a sent template as "[template] its_name"


def _font(px: int, weight: int = 400) -> QFont:
    f = QFont(theme.FONT_BODY)
    f.setPixelSize(px)
    f.setWeight(QFont.Weight(weight))
    return f


# Delivery state -> (icon, how many, colour, tooltip). Drawn as icons, not the
# ✓ characters: Barlow has no such glyph, and the fallback font's version came
# out as a broken box on the machine this was checked on. Anything the server
# has not said about is treated as plain "sent" — n8n logging the message means
# it was accepted, which is all one tick claims.
def _tick(status: str) -> tuple:
    """(icon, how many, colour, tooltip) for a delivery state. Literal i18n.t
    calls, for the string extractor."""
    return {
        "sending":   ("clock", 1, theme.NEUTRAL[500], i18n.t("Sending…")),
        "sent":      ("check", 1, theme.NEUTRAL[500], i18n.t("Sent")),
        "delivered": ("check", 2, theme.NEUTRAL[500], i18n.t("Delivered")),
        "read":      ("check", 2, theme.INFO_INK,     i18n.t("Read")),
    }.get(status or "sent") or ("check", 1, theme.NEUTRAL[500], i18n.t("Sent"))


class _Meta(QFrame):
    """The time + tick line under a bubble's text. Clickable only when the
    send failed — that click is the retry."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background: transparent;")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.time = QLabel()
        self.time.setFont(_font(11, 500))
        row.addWidget(self.time)
        self._tick_box = QWidget()
        self._ticks = QHBoxLayout(self._tick_box)
        self._ticks.setContentsMargins(0, 0, 0, 0)
        self._ticks.setSpacing(-7)              # overlap: two ticks read as one mark
        row.addWidget(self._tick_box)
        self._retry = False

    def _set_ticks(self, name: str, count: int, colour: str):
        while self._ticks.count():
            w = self._ticks.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for _ in range(count):
            lab = QLabel()
            lab.setPixmap(icons.pixmap(name, 14, colour))
            lab.setFixedSize(14, 14)
            self._ticks.addWidget(lab)
        self._tick_box.setVisible(count > 0)

    def show_state(self, stamp: str, outbound: bool, status: str):
        self._retry = False
        self.setCursor(Qt.ArrowCursor)
        self.setToolTip("")
        if status == "failed":
            self._retry = True
            self.setCursor(Qt.PointingHandCursor)
            self._set_ticks("check", 0, "")
            self.time.setText(i18n.t("Failed · Retry"))
            self.time.setStyleSheet(f"color: {theme.ERR_INK}; font-weight: 700;")
            self.setToolTip(i18n.t("It didn't send. Click to try again."))
            return
        self.time.setText(clock(stamp))
        if not outbound:
            self.time.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
            self._set_ticks("check", 0, "")
            return
        icon, count, colour, tip = _tick(status)
        self.time.setStyleSheet(f"color: {theme.NEUTRAL[500]};")
        self._set_ticks(icon, count, colour)
        self.setToolTip(tip)

    def mousePressEvent(self, event):
        if self._retry and event.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class _Picture(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class ImageViewer(PrismDialog):
    """A picture from a chat at a readable size, with a way to keep a copy."""

    def __init__(self, media: dict, data: bytes, parent=None):
        super().__init__(media.get("filename") or media_lib.kind_name("image"), media_lib.size_text(media.get("size")), icon="image",
                         parent=parent, closable=True)
        pm = media_lib.pixmap_from(data)
        view = QLabel()
        view.setAlignment(Qt.AlignCenter)
        if not pm.isNull():
            view.setPixmap(pm.scaled(860, 560, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.body.addWidget(view, stretch=1)
        self.footer.add_secondary(self.button(i18n.t("Save a copy"), on_click=lambda: media_lib.save_asset(
            self, media, lambda m: C.show_toast(self, i18n.t("Couldn't save"), m))))
        self.footer.set_primary(self.button(i18n.t("Close"), "primary", on_click=self.accept))


class MediaBlock(QFrame):
    """The file a message carries. A picture is shown in the bubble and opens large; anything else is a tile that opens in whatever
    program handles it. A customer's file the service has not finished fetching says so, and the next poll fills it in."""

    W = 264

    def __init__(self, media: dict, parent=None):
        super().__init__(parent)
        self.media = media
        self.setStyleSheet("background: transparent;")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 2)
        col.setSpacing(0)
        kind = media.get("kind") or "document"
        self.picture = None
        if not media.get("ready") or not media.get("id"):
            col.addWidget(self._tile(kind, media_lib.kind_name(kind), i18n.t("Fetching the file…"), opens=False))
        elif kind == "image" and int(media.get("size") or 0) <= 3 * 1024 * 1024:
            self.picture = _Picture()
            self.picture.setFixedSize(self.W, 150)
            self.picture.setAlignment(Qt.AlignCenter)
            self.picture.setCursor(Qt.PointingHandCursor)
            self.picture.setToolTip(i18n.t("Click to open"))
            self.picture.setStyleSheet(f"background: {theme.NEUTRAL[100]}; border-radius: 10px;")
            self.picture.setPixmap(media_lib.tile_icon("image").pixmap(88, 88))
            self.picture.clicked.connect(self._open_picture)
            col.addWidget(self.picture)
            media_lib.fetch(self, media["id"], self._picture_ready, failed=lambda _m, _d: None, max_bytes=3 * 1024 * 1024)
        else:
            sub = "%s · %s" % (media_lib.kind_name(kind), media_lib.size_text(media.get("size"))) if media.get("size") else media_lib.kind_name(kind)
            col.addWidget(self._tile(kind, media.get("filename") or media_lib.kind_name(kind), sub, opens=True))

    def _tile(self, kind: str, title: str, sub: str, opens: bool) -> QWidget:
        tile = QFrame()
        tile.setObjectName("waMediaTile")
        tile.setAttribute(Qt.WA_StyledBackground, True)
        tile.setStyleSheet("#waMediaTile { background: rgba(0,0,0,0.045); border-radius: 10px; }")
        col = QVBoxLayout(tile)
        col.setContentsMargins(10, 8, 8, 8)
        col.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        glyph = QLabel()
        glyph.setFixedSize(30, 30)
        glyph.setPixmap(icons.pixmap(media_lib.KIND_ICON.get(kind, "file"), 24, theme.NEUTRAL[700]))
        row.addWidget(glyph)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel()
        name.setFont(_font(13, 700))
        name.setText(QFontMetrics(name.font()).elidedText(title, Qt.ElideMiddle, self.W - 74))      # a long file name keeps its start and its ending
        name.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        name.setToolTip(title)
        text.addWidget(name)
        meta = QLabel(sub)
        meta.setFont(_font(11, 500))
        meta.setStyleSheet(f"color: {theme.NEUTRAL[600]}; background: transparent;")
        text.addWidget(meta)
        row.addLayout(text, stretch=1)
        col.addLayout(row)
        if opens:
            actions = QHBoxLayout()
            actions.setSpacing(6)
            actions.addStretch(1)
            actions.addWidget(C.button(i18n.t("Save a copy"), "tertiary", small=True, on_click=lambda: media_lib.save_asset(self, self.media, self._problem)))
            actions.addWidget(C.button(i18n.t("Open"), "secondary", small=True, on_click=lambda: media_lib.open_asset(self, self.media, self._problem)))
            col.addLayout(actions)
        return tile

    def _problem(self, message: str):
        C.show_toast(self, i18n.t("Couldn't open the file"), message)

    def _picture_ready(self, _meta, data):
        try:
            if not data or self.picture is None:
                return
            pm = media_lib.pixmap_from(data)
            if pm.isNull():
                return
            fit = pm.scaled(self.W, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.picture.setFixedSize(fit.width(), fit.height())
            self.picture.setPixmap(fit)
            self.picture.setStyleSheet("background: transparent; border-radius: 10px;")
        except RuntimeError:                                        # the bubble was redrawn while the picture was on its way
            return

    def _open_picture(self):
        media_lib.fetch(self, self.media["id"], self._show_picture, failed=lambda m, _d: self._problem(m))

    def _show_picture(self, meta, data):
        try:
            if data is None:
                return self._problem(i18n.t("That picture is too big to open from here."))
            ImageViewer({**self.media, **{k: v for k, v in (meta or {}).items() if v}}, data, self.window()).exec()
        except RuntimeError:
            return


class Bubble(QFrame):
    retry = Signal(object)                  # this bubble

    def __init__(self, msg: dict, tail: bool, caption: str = "", parent=None):
        super().__init__(parent)
        self.msg = msg
        self.outbound = msg.get("direction") == "out"
        self.setObjectName("waBubble")
        self.setAttribute(Qt.WA_StyledBackground, True)
        radius, small = 16, 4
        corners = {"tl": radius, "tr": radius, "bl": radius, "br": radius}
        if tail:
            corners["br" if self.outbound else "bl"] = small
        bg = "rgba(224, 244, 232, 0.97)" if self.outbound else "rgba(255, 255, 255, 0.97)"      # near-solid: the scenery behind must not show through the words
        border = "transparent" if self.outbound else theme.HAIRLINE
        self.setStyleSheet(
            f"#waBubble {{ background: {bg}; border: 1px solid {border};"
            f" border-top-left-radius: {corners['tl']}px;"
            f" border-top-right-radius: {corners['tr']}px;"
            f" border-bottom-left-radius: {corners['bl']}px;"
            f" border-bottom-right-radius: {corners['br']}px; }}")

        col = QVBoxLayout(self)
        col.setContentsMargins(12, 8, 12, 6)
        col.setSpacing(2)
        if caption:
            cap = QLabel(caption)
            cap.setFont(_font(11, 700))
            cap.setStyleSheet(f"color: {theme.OK_INK}; background: transparent;")
            col.addWidget(cap)
        media = msg.get("media") or None
        self.media_block = MediaBlock(media) if media and (media.get("id") or media.get("wa_id")) else None
        if self.media_block is not None:
            col.addWidget(self.media_block)
        text = msg.get("text") or ""
        if self.media_block is not None:
            text = _PLACEHOLDER.sub("", text)                    # a bare "[image]" is the file itself, not words
        template = _TEMPLATE.match(text)
        if template:                                             # say what it is, and show its name as a name, not as stored text
            kind = QLabel(i18n.t("Template message").upper())
            kind.setFont(_font(10, 700))
            kind.setStyleSheet(f"color: {theme.NEUTRAL[600]}; background: transparent;")
            col.addWidget(kind)
            text = template.group(1).strip().replace("_", " ")
            text = text[:1].upper() + text[1:]
        self.body = QLabel(text)
        if template:
            self.body.setToolTip(msg.get("text") or "")
        self.body.setFont(_font(14))
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        self.body.setVisible(bool(text) or self.media_block is None)
        col.addWidget(self.body)
        self.meta = _Meta()
        self.meta.clicked.connect(lambda: self.retry.emit(self))
        col.addWidget(self.meta, alignment=Qt.AlignRight)
        self.set_status(msg.get("status") or "")

    def set_status(self, status: str):
        self.msg["status"] = status
        self.meta.show_state(self.msg.get("created_at", ""), self.outbound, status)

    def fit(self, max_bubble: int):
        """Shrink-wrap the text: the widest line that fits, capped."""
        max_text = max(120, max_bubble - 26)
        text = self.body.text()
        fm = QFontMetrics(self.body.font())
        rect = fm.boundingRect(QRect(0, 0, max_text, 100000),
                               Qt.TextWordWrap | Qt.AlignLeft, text)
        meta_w = self.meta.sizeHint().width() + 4
        wide = max(min(max_text, rect.width() + 4), meta_w)
        if self.media_block is not None:
            self.media_block.setFixedWidth(min(MediaBlock.W, max_text))
            wide = max(wide, self.media_block.width())
        self.body.setFixedWidth(wide)


class _DayChip(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setFont(_font(11, 700))
        self.setStyleSheet(
            f"color: {theme.NEUTRAL[700]}; background: rgba(0, 0, 0, 0.06);"
            f" border-radius: 10px; padding: 3px 12px;")
        self.setAlignment(Qt.AlignCenter)


class MessageThread(QScrollArea):
    """A scrolling column of bubbles, pinned to the newest message."""

    retryRequested = Signal(str, object)    # text, the failed bubble
    retryMediaRequested = Signal(object)    # a failed bubble that carried a file

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        ui.no_sideways(self)
        self.viewport().setAutoFillBackground(False)
        self._host = QWidget()
        self._host.setStyleSheet("background: transparent;")
        self.setWidget(self._host)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(18, 14, 18, 14)
        self._col.setSpacing(0)
        self._bubbles: list[Bubble] = []
        self._signature = None
        # While the person is at the bottom the thread stays there as the content grows: a picture that finishes loading, a window
        # that was not laid out yet. Scrolling up lets go; scrolling back down picks it up again.
        self._sticky = True
        bar = self.verticalScrollBar()
        bar.rangeChanged.connect(self._on_range)
        bar.actionTriggered.connect(lambda _a: QTimer.singleShot(0, self._remember_sticky))
        # Messages typed here that the server has not confirmed. A FAILED one
        # must outlive a redraw: it is not in the server's thread, the composer
        # was already cleared, and dropping it would lose the person's words.
        self._pending_msgs: list[dict] = []

    # -- content ----------------------------------------------------------------
    def _clear(self):
        while self._col.count():
            item = self._col.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._bubbles = []

    def show_note(self, text: str, tone: str = "muted"):
        self._clear()
        self._signature = None
        colour = theme.ERR_INK if tone == "error" else theme.NEUTRAL[600]
        self._col.addStretch(1)
        lab = C.label(text, level="SUPPORT", colour=colour, wrap=True)
        lab.setAlignment(Qt.AlignCenter)
        self._col.addWidget(lab)
        self._col.addStretch(1)

    def set_messages(self, messages: list) -> bool:
        """Rebuild the thread. Returns False when nothing changed (so a poll
        that finds the same messages does not flicker or lose the scroll)."""
        sig = tuple((m.get("created_at"), m.get("text"), m.get("status"), (m.get("media") or {}).get("id"), (m.get("media") or {}).get("ready"))
                    for m in messages)
        if sig == self._signature:
            return False
        stick = self._at_bottom() or self._signature is None
        self._sticky = stick
        self._signature = sig
        self._clear()
        failed = [m for m in self._pending_msgs if m.get("status") == "failed"]
        self._pending_msgs = failed
        if not messages and not failed:
            self.show_note(i18n.t("No messages yet — say hello."))
            self._signature = sig
            return True

        prev_dt, prev_dir = None, None
        n = len(messages)
        for i, m in enumerate(messages):
            dt = parse_ts(m.get("created_at", ""))
            outbound = m.get("direction") == "out"
            new_day = dt is not None and (prev_dt is None or dt.date() != prev_dt.date())
            if new_day:
                self._add_row(_DayChip(day_label(dt)), Qt.AlignCenter, gap=14 if i else 0)
            grouped = (not new_day and prev_dt is not None and dt is not None
                       and prev_dir == outbound and dt - prev_dt <= _GROUP_GAP)
            nxt = messages[i + 1] if i + 1 < n else None
            nxt_dt = parse_ts(nxt.get("created_at", "")) if nxt else None
            tail = not (nxt is not None and nxt_dt is not None and dt is not None
                        and (nxt.get("direction") == "out") == outbound
                        and nxt_dt.date() == dt.date() and nxt_dt - dt <= _GROUP_GAP)
            caption = ""
            if outbound and not grouped:
                who = (m.get("sender") or "").strip()
                caption = i18n.t("Auto-reply") if who.lower() == "bot" else who
            bubble = Bubble(dict(m), tail=tail, caption=caption)
            bubble.retry.connect(self._on_retry)
            self._bubbles.append(bubble)
            self._add_row(bubble, Qt.AlignRight if outbound else Qt.AlignLeft,
                          gap=(3 if grouped else 12) if i else 0)
            prev_dt, prev_dir = dt, outbound
        for m in failed:                        # unsent messages stay at the bottom
            bubble = Bubble(m, tail=True)
            bubble.retry.connect(self._on_retry)
            self._bubbles.append(bubble)
            self._add_row(bubble, Qt.AlignRight, gap=12 if self._bubbles[:-1] else 0)
        self._col.addStretch(0)
        self._refit()
        if stick:
            QTimer.singleShot(0, self.scroll_to_bottom)
        return True

    def _add_row(self, widget: QWidget, align, gap: int = 0):
        if gap:
            self._col.addSpacing(gap)
        self._col.addWidget(widget, alignment=align)

    # -- optimistic sends ---------------------------------------------------------
    def add_pending(self, text: str, sender: str = "") -> Bubble:
        now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        # a placeholder replaced by the first real message must not linger
        if not self._bubbles:
            self._clear()
        msg = {"direction": "out", "sender": sender, "text": text,
               "created_at": now, "status": "sending"}
        self._pending_msgs.append(msg)
        bubble = Bubble(msg, tail=True)
        bubble.retry.connect(self._on_retry)
        self._bubbles.append(bubble)
        if self._col.count() and self._col.itemAt(self._col.count() - 1).spacerItem():
            self._col.takeAt(self._col.count() - 1)
        self._add_row(bubble, Qt.AlignRight, gap=12 if len(self._bubbles) > 1 else 0)
        self._sticky = True
        self._signature = None              # the next poll should redraw truthfully
        self._refit()
        QTimer.singleShot(0, self.scroll_to_bottom)
        return bubble

    def add_pending_media(self, asset: dict, caption: str, sender: str = "") -> Bubble:
        """A file typed into the chat, on screen at once like a text reply."""
        now = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
        if not self._bubbles:
            self._clear()
        kind = asset.get("kind") or "document"
        msg = {"direction": "out", "sender": sender, "text": ("[%s] %s" % (kind, caption)).strip(), "created_at": now, "status": "sending",
               "media": {"id": asset.get("id"), "wa_id": None, "mime_type": asset.get("mime"), "kind": kind, "filename": asset.get("filename"),
                         "size": asset.get("size"), "ready": True}}
        self._pending_msgs.append(msg)
        bubble = Bubble(msg, tail=True)
        bubble.retry.connect(self._on_retry)
        self._bubbles.append(bubble)
        if self._col.count() and self._col.itemAt(self._col.count() - 1).spacerItem():
            self._col.takeAt(self._col.count() - 1)
        self._add_row(bubble, Qt.AlignRight, gap=12 if len(self._bubbles) > 1 else 0)
        self._sticky = True
        self._signature = None
        self._refit()
        QTimer.singleShot(0, self.scroll_to_bottom)
        return bubble

    def _on_retry(self, bubble: Bubble):
        if (bubble.msg.get("media") or {}).get("id"):
            self.retryMediaRequested.emit(bubble)
            return
        self.retryRequested.emit(bubble.body.text(), bubble)

    # -- geometry -----------------------------------------------------------------
    def _refit(self):
        avail = self.viewport().width() - 36
        cap = max(220, min(int(avail * 0.72), 560))
        for b in self._bubbles:
            b.fit(cap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._refit()

    def _on_range(self, _low: int, _high: int):
        if self._sticky:
            QTimer.singleShot(0, self._pin)              # after the layout has settled, not in the middle of it

    def _pin(self):
        if self._sticky:
            self.scroll_to_bottom()
            self.viewport().update()

    def _remember_sticky(self):
        self._sticky = self._at_bottom()

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 24

    def scroll_to_bottom(self):
        bar = self.verticalScrollBar()
        bar.setValue(bar.maximum())


class _Entry(QPlainTextEdit):
    submitted = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                not (event.modifiers() & Qt.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


class Composer(QFrame):
    """The reply box: grows with the text (one line to five), Enter sends,
    Shift+Enter is a new line."""

    submitted = Signal(str)
    submittedMedia = Signal(dict, str)      # the file from the library, and the words under it
    attachRequested = Signal()

    MIN_H, MAX_H = 52, 140
    PAD = 8                                 # room above and below the words inside the box, so one line sits in the middle

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("waComposer")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#waComposer {{ background: rgba(255,255,255,0.94);"
            f" border: 1px solid {theme.BORDER}; border-radius: 22px; }}")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 4, 6, 4)
        row.setSpacing(theme.SPACE_2)
        self._asset = None
        self.attach_btn = C.icon_button("paperclip", i18n.t("Attach a picture, video, voice note or document"),
                                        on_click=self.attachRequested.emit, colour=theme.NEUTRAL[600])
        row.addWidget(self.attach_btn, alignment=Qt.AlignBottom)
        self.chip = QFrame()
        self.chip.setObjectName("waAttached")
        self.chip.setAttribute(Qt.WA_StyledBackground, True)
        self.chip.setStyleSheet(f"#waAttached {{ background: {theme.NEUTRAL[100]}; border-radius: 12px; }}")
        chip_row = QHBoxLayout(self.chip)
        chip_row.setContentsMargins(10, 2, 2, 2)
        chip_row.setSpacing(4)
        self.chip_name = QLabel("")
        self.chip_name.setFont(_font(12, 600))
        self.chip_name.setStyleSheet(f"color: {theme.TEXT}; background: transparent;")
        chip_row.addWidget(self.chip_name)
        chip_row.addWidget(C.icon_button("x", i18n.t("Remove the attachment"), on_click=self.clear_attachment, colour=theme.NEUTRAL[600]))
        self.chip.hide()
        row.addWidget(self.chip, alignment=Qt.AlignBottom)
        self.edit = _Entry()
        self.edit.setFrameShape(QFrame.NoFrame)
        self.edit.setFont(_font(14))
        self._placeholder = i18n.t("Type a message")
        self.edit.setPlaceholderText(self._placeholder)
        self.edit.setToolTip(i18n.t("Enter sends the message. Shift+Enter starts a new line."))
        self.edit.document().setDocumentMargin(self.PAD)
        self.edit.setStyleSheet("background: transparent; border: none;")
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)      # on only once the box is as tall as it gets (see _grow)
        self.edit.submitted.connect(self._submit)
        self.edit.textChanged.connect(self._grow)
        self.edit.installEventFilter(self)
        row.addWidget(self.edit, stretch=1)
        self.count = QLabel("")
        self.count.setFont(_font(11, 600))
        self.count.setStyleSheet(f"color: {theme.ERR_INK}; background: transparent;")
        self.count.hide()
        row.addWidget(self.count)
        self.send_btn = C.button(i18n.t("Send"), "primary", on_click=self._submit)
        row.addWidget(self.send_btn, alignment=Qt.AlignBottom)
        self._grow()

    def _wanted_height(self) -> int:
        """The height the words need at the width the box really has: what is typed, or the placeholder while it is empty, so a long
        one on a narrow window grows the box to show all of it instead of cutting its second line off."""
        words = int(self.edit.document().size().height())
        if not self.edit.toPlainText():
            width = max(60, self.edit.width() - 2 * self.PAD)       # the box's own width: its viewport is resized after this runs
            shown = self.edit.placeholderText()
            lines = QFontMetrics(self.edit.font()).boundingRect(QRect(0, 0, width, 10000), Qt.TextWordWrap, shown).height()
            words = max(words, lines + 2 * self.PAD)
        return words

    def eventFilter(self, obj, event):
        if obj is self.edit and event.type() == QEvent.Resize:
            self._grow()                                            # the box has just been given its real width
        return super().eventFilter(obj, event)

    def _grow(self):
        h = self._wanted_height() + 8                               # + the frame's own top and bottom margin
        self.setFixedHeight(max(self.MIN_H, min(self.MAX_H, h)))
        self.edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if h > self.MAX_H else Qt.ScrollBarAlwaysOff)
        n = len(self.edit.toPlainText())
        over = n > _MAX_TEXT
        self.count.setVisible(n > _MAX_TEXT - 300)
        self.count.setText(f"{n}/{_MAX_TEXT}")
        self.send_btn.setEnabled((bool(self.edit.toPlainText().strip()) or self._asset is not None) and not over
                                 and self.edit.isEnabled())

    def _submit(self):
        text = self.edit.toPlainText().strip()
        if len(text) > _MAX_TEXT or not self.edit.isEnabled():
            return
        if self._asset is not None:
            asset, self._asset = self._asset, None
            self.edit.clear()
            self._show_attachment()
            self.submittedMedia.emit(asset, text[:1024])
            return
        if not text:
            return
        self.edit.clear()
        self.submitted.emit(text)

    def set_attachment(self, asset) -> None:
        """Attach a library file to the next send; the words typed become its caption."""
        self._asset = dict(asset) if asset else None
        self._show_attachment()
        self.focus()

    def attachment(self):
        return self._asset

    def clear_attachment(self) -> None:
        self._asset = None
        self._show_attachment()

    def _show_attachment(self):
        a = self._asset
        self.chip.setVisible(a is not None)
        if a is not None:
            fm = QFontMetrics(self.chip_name.font())
            self.chip_name.setText(fm.elidedText(a.get("filename") or media_lib.kind_name(a.get("kind")), Qt.ElideMiddle, 200))
            self.chip_name.setToolTip("%s · %s" % (a.get("filename") or "", media_lib.size_text(a.get("size"))))
        self.edit.setPlaceholderText(i18n.t("Add a caption (optional)") if a is not None else self._placeholder)
        self._grow()

    def set_active(self, active: bool, placeholder: str = ""):
        self.edit.setEnabled(active)
        self.attach_btn.setEnabled(active)
        self.send_btn.setEnabled(active and (bool(self.edit.toPlainText().strip()) or self._asset is not None))
        if placeholder:
            self._placeholder = placeholder
            if self._asset is None:
                self.edit.setPlaceholderText(placeholder)

    def focus(self):
        self.edit.setFocus(Qt.OtherFocusReason)

    def restore(self, text: str):
        """Put text back after a failed send that the person chose not to retry."""
        self.edit.setPlainText(text)
        self.focus()


class Banner(QLabel):
    """A one-line notice above the composer — the 24-hour window, an opt-out."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)
        self.setFont(_font(12, 600))
        self.hide()

    def show_note(self, text: str, tone: str = "warn"):
        ink, bg = {"warn": (theme.WARN_INK, "rgba(202, 138, 4, 0.14)"),
                   "info": (theme.INFO_INK, "rgba(2, 132, 199, 0.12)"),
                   "err": (theme.ERR_INK, "rgba(220, 38, 38, 0.12)")}[tone]
        self.setStyleSheet(f"color: {ink}; background: {bg}; border-radius: 10px;"
                           f" padding: 8px 12px;")
        self.setText(text)
        self.show()
