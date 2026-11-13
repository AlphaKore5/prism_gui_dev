"""The one loader. Every wait in Prism uses one of these looks, chosen by what
is being waited on (owner's choice, 2026-10-16):

  stages — a staged pipeline (measure → plan → build → check): a row of
           segments, finished ones filled, the current one sweeping. Reads as
           "step 3 of 5", never as stuck. STEP, Reel, Motion, BOQ, Gerber.
  ring   — anything else with or without a count: a ring, with the percentage
           in the middle once the total is known.
  orb    — waiting on an AI tool (a breathing dark orb in a turning ring).
  dots   — a button that started the work: see busy_button().
  skeleton — a list that is loading: see Skeleton.

`Loader` answers the QProgressBar calls the screens already make
(setVisible, setRange, setValue, maximum, setTextVisible), so a screen swaps
the widget and keeps its code. It adds a message line, an elapsed timer that
starts when it is shown, and an optional Stop button.

Nothing here touches the engine or another add-on; it is plain Qt.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QDialog, QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

import i18n
import theme

MODES = ("stages", "ring", "orb")
_MAX_SEGMENTS = 12


def elapsed_text(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 60}:{s % 60:02d}"


class Loader(QFrame):
    """A wait, with words. `mode` is one of MODES."""

    stop_requested = Signal()

    def __init__(self, mode: str = "stages", stages: list | None = None,
                 stoppable: bool = False, compact: bool = False,
                 bare: bool = False, parent=None):
        super().__init__(parent)
        self._compact = compact
        # bare: only the segments — for a header that already has its own
        # words and clock (the main run panel).
        self._bare = bare
        self._active = True
        self._mode = mode if mode in MODES else "stages"
        self._stages = list(stages or [])
        self._stage = 0
        self._lo, self._hi, self._value = 0, 0, 0
        self._message = ""
        self._since = 0.0
        self._phase = 0.0
        self.setObjectName("prismLoader")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAccessibleName(i18n.t("Progress"))

        self._tick = QTimer(self)
        self._tick.setInterval(33)
        self._tick.timeout.connect(self._advance)


        self.stop_btn = QPushButton(i18n.t("Stop"), self)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.setStyleSheet(
            f"QPushButton {{ background: #ffffff; border: 1px solid "
            f"{theme.NEUTRAL[300]}; border-radius: 7px; padding: 2px 10px;"
            " font-size: 12px; }")
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        self.stop_btn.setVisible(False)
        self._stoppable = stoppable
        QWidget.setVisible(self, False)

    # ── the QProgressBar surface the screens already call ─────────────────

    def setRange(self, lo: int, hi: int):
        self._lo, self._hi = int(lo), int(hi)
        self._value = max(self._lo, min(self._value, self._hi))
        self.update()

    def setValue(self, value: int):
        self._value = int(value)
        self.update()

    def maximum(self) -> int:
        return self._hi

    def minimum(self) -> int:
        return self._lo

    def value(self) -> int:
        return self._value

    def setTextVisible(self, _visible: bool):          # kept for callers
        pass

    def setVisible(self, visible: bool):
        was = self.isVisibleTo(self.parentWidget()) if self.parentWidget() else self.isVisible()
        super().setVisible(visible)
        if visible and not was:
            self._since = time.monotonic()
            self._phase = 0.0
            if self._active:
                self._tick.start()
        elif not visible:
            self._tick.stop()

    # ── what the screen can tell it ───────────────────────────────────────

    def set_message(self, text: str):
        self._message = str(text or "")
        self.update()

    def set_stages(self, names: list):
        self._stages = list(names or [])
        self._stage = 0
        self.update()

    def set_stage(self, index: int):
        self._stage = max(0, int(index))
        self.update()

    def set_stoppable(self, on: bool):
        self._stoppable = bool(on)
        self._layout_stop()

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def fraction(self) -> float | None:
        """0..1 when the total is known, else None (indeterminate)."""
        if self._hi <= self._lo:
            return None
        return max(0.0, min(1.0, (self._value - self._lo) / (self._hi - self._lo)))

    def elapsed(self) -> float:
        return time.monotonic() - self._since if self._since else 0.0

    # ── geometry ──────────────────────────────────────────────────────────

    def sizeHint(self) -> QSize:
        return QSize(90 if self._compact else 260, self._height())

    def minimumSizeHint(self) -> QSize:
        return QSize(90 if self._compact else 160, self._height())

    def set_active(self, active: bool):
        """Whether the current segment sweeps. A finished or idle run keeps
        its filled segments but stops moving (and stops the timer)."""
        self._active = bool(active)
        if self.isVisible():
            if self._active:
                self._tick.start()
            else:
                self._tick.stop()
        self.update()

    def _height(self) -> int:
        if self._bare:
            return 8
        if self._compact:
            return 30
        if self._mode == "stages":
            return 44 + (16 if self._stages else 0)
        return 52

    def _segments(self) -> int:
        if self._stages:
            return len(self._stages)
        if self._hi > self._lo and (self._hi - self._lo) <= _MAX_SEGMENTS:
            return self._hi - self._lo
        return 1

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_stop()

    def _layout_stop(self):
        self.stop_btn.setVisible(self._stoppable and self.isVisible())
        self.stop_btn.adjustSize()
        self.stop_btn.move(self.width() - self.stop_btn.width(), 0)

    def showEvent(self, event):
        super().showEvent(event)
        self._layout_stop()

    def _advance(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    # ── painting ──────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        ink = QColor(theme.BRAND_RED)
        track = QColor(theme.NEUTRAL[200])
        quiet = QColor(theme.NEUTRAL[500])
        text = QColor(theme.TEXT)
        fm = QFontMetrics(self.font())
        clock = elapsed_text(self.elapsed())
        right = self.width() - (self.stop_btn.width() + 8
                                if self._stoppable else 0)

        if self._bare:
            self._paint_segments(p, 1, ink, track)
        elif self._mode == "stages":
            self._paint_stages(p, fm, ink, track, quiet, text, clock, right)
        else:
            self._paint_side(p, fm, ink, track, quiet, text, clock, right)
        p.end()

    def _paint_stages(self, p, fm, ink, track, quiet, text, clock, right):
        w = self.width()
        # message left, clock right
        clock_w = fm.horizontalAdvance(clock)
        p.setPen(quiet)
        p.drawText(right - clock_w, 0, clock_w, 18, Qt.AlignRight | Qt.AlignVCenter, clock)
        p.setPen(text)
        msg = fm.elidedText(self._message, Qt.ElideRight, max(40, right - clock_w - 12))
        p.drawText(0, 0, right - clock_w - 8, 18, Qt.AlignLeft | Qt.AlignVCenter, msg)

        frac = self._paint_segments(p, 26, ink, track)
        if self._stages:
            self._paint_names(p, w, 26 + 10, text, quiet)

    def _paint_segments(self, p, y, ink, track):
        w = self.width()
        n = self._segments()
        gap = 5
        seg_w = (w - gap * (n - 1)) / n
        frac = self.fraction
        p.setPen(Qt.NoPen)
        for i in range(n):
            x = i * (seg_w + gap)
            rect = QRectF(x, y, seg_w, 5)
            p.setBrush(track)
            p.drawRoundedRect(rect, 2.5, 2.5)
            fill = self._segment_fill(i, n, frac)
            if fill > 0:
                p.setBrush(ink)
                p.drawRoundedRect(QRectF(x, y, seg_w * fill, 5), 2.5, 2.5)
            elif self._is_sweeping(i, n, frac):
                p.save()
                p.setClipRect(rect)
                span = seg_w * 0.45
                sx = x - span + (seg_w + span) * self._phase * 1.0
                p.setBrush(ink)
                p.drawRoundedRect(QRectF(sx, y, span, 5), 2.5, 2.5)
                p.restore()
        return frac

    def _paint_names(self, p, w, names_y, text, quiet):
        n = self._segments()
        gap = 5
        seg_w = (w - gap * (n - 1)) / n
        if True:
            for i, name in enumerate(self._stages):
                x = i * (seg_w + gap)
                bold = i == self._stage
                f = self.font()
                f.setBold(bold)
                p.setFont(f)
                p.setPen(text if i <= self._stage else quiet)
                label = QFontMetrics(f).elidedText(name, Qt.ElideRight, int(seg_w))
                p.drawText(QRectF(x, names_y, seg_w, 16), Qt.AlignLeft | Qt.AlignVCenter, label)
            p.setFont(self.font())

    def _segment_fill(self, i: int, n: int, frac) -> float:
        if self._stages:
            if i < self._stage:
                return 1.0
            if i == self._stage and frac is not None:
                return frac
            return 0.0
        if frac is None:
            return 0.0
        if n == 1:
            return frac
        done = self._value - self._lo
        return 1.0 if i < done else 0.0

    def _is_sweeping(self, i: int, n: int, frac) -> bool:
        if not self._active:
            return False
        if frac is not None and not self._stages and n > 1:
            return i == self._value - self._lo       # next segment is working
        if self._stages:
            return i == self._stage and frac is None
        return frac is None and i == 0

    def _paint_side(self, p, fm, ink, track, quiet, text, clock, right):
        """Ring or orb at the left, the words beside it."""
        if self._compact:
            self._paint_compact(p, ink, track, quiet, clock)
            return
        left = 52
        if self._mode == "ring":
            r = QRectF(4, 6, 40, 40)
            pen = QPen(track, 4.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r)
            pen = QPen(ink, 4.5)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            frac = self.fraction
            if frac is None:
                p.drawArc(r, int(-self._phase * 360 * 16), 100 * 16)
            else:
                p.drawArc(r, 90 * 16, int(-frac * 360 * 16))
                p.setPen(text)
                f = self.font()
                f.setBold(True)
                p.setFont(f)
                p.drawText(r, Qt.AlignCenter, f"{int(frac * 100)}%")
                p.setFont(self.font())
        if self._mode == "orb":
            self._paint_orb(p, ink)
        p.setPen(text)
        msg = fm.elidedText(self._message, Qt.ElideRight, max(40, right - left))
        p.drawText(left, 6, right - left, 20, Qt.AlignLeft | Qt.AlignVCenter, msg)
        p.setPen(quiet)
        frac = self.fraction
        total = self._hi - self._lo
        # A count means something when it is a count of things (43 of 75), not
        # when the range is just a percentage.
        sub = clock if frac is None or total == 100 \
            else i18n.t("{n} of {total}").replace("{n}", str(self._value - self._lo)) \
            .replace("{total}", str(total)) + " · " + clock
        p.drawText(left, 26, right - left, 18, Qt.AlignLeft | Qt.AlignVCenter, sub)


    def _paint_orb(self, p, ink):
        """A dark sphere that breathes, inside a slowly turning dashed ring —
        Prism thinking. Solid enough to read at a glance on a light card."""
        import math
        cx, cy = 24.0, 26.0
        breath = 0.86 + 0.14 * (0.5 + 0.5 * math.cos(self._phase * 2 * math.pi * 3))
        r = 14.0 * breath
        grad = QRadialGradient(cx - r * 0.3, cy - r * 0.4, r * 1.4)
        grad.setColorAt(0.0, QColor("#71717a"))
        grad.setColorAt(0.6, QColor(theme.NEUTRAL[800]))
        grad.setColorAt(1.0, QColor(theme.ACCENT))
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
        pen = QPen(QColor(theme.NEUTRAL[400]), 1.6)
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([2.0, 2.6])
        pen.setDashOffset(-self._phase * 60)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(cx - 21, cy - 21, 42, 42))

    def _paint_compact(self, p, ink, track, quiet, clock):
        """Just a small ring and the clock — for a status bar that already
        has its own sentence beside it."""
        r = QRectF(3, 3, 24, 24)
        pen = QPen(track, 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(r)
        pen = QPen(ink, 3.5)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        frac = self.fraction
        if frac is None:
            p.drawArc(r, int(-self._phase * 360 * 16), 100 * 16)
        else:
            p.drawArc(r, 90 * 16, int(-frac * 360 * 16))
        p.setPen(quiet)
        p.drawText(34, 0, self.width() - 34, 30, Qt.AlignLeft | Qt.AlignVCenter, clock)


# ── a button that started the work ────────────────────────────────────────

_busy_buttons: dict = {}


def busy_button(button: QPushButton, busy: bool, text: str = ""):
    """Put "Working ●●●" on the button that started the work, and put its own
    label back after. Pair every True with a False."""
    state = _busy_buttons.get(id(button))
    if busy:
        if state is None:
            timer = QTimer(button)
            timer.setInterval(350)
            state = {"label": button.text(), "step": 0, "timer": timer,
                     "text": text or i18n.t("Working")}
            _busy_buttons[id(button)] = state
            button.destroyed.connect(lambda *_: _busy_buttons.pop(id(button), None))

            def tick(b=button, s=state):
                s["step"] = (s["step"] + 1) % 4
                b.setText(s["text"] + " " + "●" * s["step"] + " " * (3 - s["step"]))
            timer.timeout.connect(tick)
            timer.start()
        state["text"] = text or state["text"]
        button.setText(state["text"] + " ●  ")
        button.setEnabled(False)
        return
    if state is not None:
        state["timer"].stop()
        button.setText(state["label"])
        _busy_buttons.pop(id(button), None)
    button.setEnabled(True)


# ── a list that is loading ────────────────────────────────────────────────

class Skeleton(QWidget):
    """Grey placeholder rows with a light moving across them, in place of a
    list that has not arrived yet. Hide it when the real rows do."""

    def __init__(self, rows: int = 4, parent=None):
        super().__init__(parent)
        self._rows = rows
        self._phase = 0.0
        self._tick = QTimer(self)
        self._tick.setInterval(40)
        self._tick.timeout.connect(self._advance)
        self.setMinimumHeight(rows * 46)
        QWidget.setVisible(self, False)

    def setVisible(self, visible: bool):
        super().setVisible(visible)
        if visible:
            self._tick.start()
        else:
            self._tick.stop()

    def _advance(self):
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        base = QColor(theme.NEUTRAL[200])
        light = QColor("#f1f1f4")
        w = self.width()
        glow_x = -w * 0.3 + (w * 1.6) * self._phase
        p.setPen(Qt.NoPen)

        def shade(x: float, width: float) -> QColor:
            mid = abs((x + width / 2) - glow_x) / (w * 0.35)
            t = max(0.0, 1.0 - mid)
            return QColor(int(base.red() + (light.red() - base.red()) * t),
                          int(base.green() + (light.green() - base.green()) * t),
                          int(base.blue() + (light.blue() - base.blue()) * t))

        for i in range(self._rows):
            y = 6 + i * 46
            p.setBrush(shade(0, 32))
            p.drawEllipse(QRectF(2, y, 32, 32))
            p.setBrush(shade(46, w * 0.6))
            p.drawRoundedRect(QRectF(46, y + 4, w * 0.62, 9), 4.5, 4.5)
            p.setBrush(shade(46, w * 0.4))
            p.drawRoundedRect(QRectF(46, y + 19, w * 0.4, 9), 4.5, 4.5)
        p.end()


# ── a small modal wait, for work with no screen of its own ────────────────

class LoadingDialog(QDialog):
    """A downloading / opening wait with the same ring as everywhere else.
    Answers the handful of QProgressDialog calls Prism's callers made
    (setLabelText, setMaximum, setValue, wasCanceled, canceled), so swapping
    it in changes no logic."""

    canceled = Signal()

    def __init__(self, title: str, message: str, cancellable: bool = True,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(False)
        self.setMinimumWidth(380)
        self._cancelled = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(12)
        self.loader = Loader("ring")
        self.loader.set_message(message)
        lay.addWidget(self.loader)
        row = QHBoxLayout()
        row.addStretch(1)
        self.cancel_btn = QPushButton(i18n.t("Cancel"))
        self.cancel_btn.setVisible(cancellable)
        self.cancel_btn.clicked.connect(self._cancel)
        row.addWidget(self.cancel_btn)
        lay.addLayout(row)

    def _cancel(self):
        self._cancelled = True
        self.canceled.emit()
        self.hide()

    def wasCanceled(self) -> bool:
        return self._cancelled

    def setLabelText(self, text: str):
        self.loader.set_message(text)

    def setMaximum(self, hi: int):
        self.loader.setRange(0, hi)

    def setValue(self, value: int):
        self.loader.setValue(value)

    def setAutoClose(self, _on: bool):              # kept for callers
        pass

    def setMinimumDuration(self, _ms: int):         # kept for callers
        pass

    def showEvent(self, event):
        super().showEvent(event)
        self.loader.setVisible(True)

    def hideEvent(self, event):
        self.loader.setVisible(False)
        super().hideEvent(event)
