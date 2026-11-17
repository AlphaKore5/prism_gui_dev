"""The run console — what Prism is doing right now, step by step.

Execution is the moment the whole product exists for: a browser is being
driven somewhere off-screen for tens of minutes and this panel is the only
window onto it. It used to be a heading, a sub-caption and a column of cards
that said "Working… 2s" — a screen that was half empty at the exact point the
user most wanted to be told something.

Two things changed.

**A run header.** Task, overall state, step counter, elapsed and progress, with
Stop beside them. None of that existed; every number in it was already known
somewhere else in the app (Home was even being handed the step counter) and
none of it reached the screen where the run is.

**The engine's own words.** The audit found that `automation.py` emits far more
than this panel drew. `stage_done` carries `blocked` — a human-readable reason
a step came back empty ("this tool has run out", "this is a sign-in wall",
"the site changed its markup") — plus `exhausted`, `count` and `snippet`.
`stage_failover` carries the real `reason` a tool was swapped out.
`stage_recovered` names the tool that gave up first. And three kinds —
`stage_skipped`, `retry`, `reel_scene` — were emitted and silently dropped,
`stage_skipped` having been added to the engine *specifically* so the GUI
would stop losing a step. All of it is rendered here now. Nothing on this
screen is invented; every line is a field the engine already produced.

Per-stage copy still matters: if a later stage fails, the user can take the
last good text and finish by hand.
"""
from __future__ import annotations
import os
import time
from html import escape as _escape
from PySide6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QRectF, QTimer, Signal,
)
from PySide6.QtGui import QPainter, QPen, QFontMetrics
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QScrollArea, QApplication, QGraphicsOpacityEffect, QSizePolicy,
)

import i18n
from widgets.loader import Loader
import ai_server
import paths
import theme
from widgets import icons
from widgets import controls as C
from widgets.agents_panel import STAGE_COPY
from widgets.controls import Card, StatusBadge
from widgets.markdown import render_markdown


def short_duration(seconds: float) -> str:
    """"12s" / "1m 40s" — short enough to sit inside a status badge."""
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"


def _short_url(url: str, limit: int = 58) -> str:
    """A link as readable text rather than as a button label.

    Every stage knows its URL and until now it only ever appeared as the word
    "Open in tool" — which is the one thing the address does not tell you.
    """
    text = (url or "").split("://", 1)[-1]
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


# States that mean "this stage is on the clock". Anything else freezes the
# figure rather than dropping it: how long a step took is worth keeping.
_LIVE_STATES = {"running", "streaming", "planning", "waiting", "retrying"}
# States a stage cannot come back from on its own.
_TERMINAL_STATES = {"completed", "failed", "cancelled", "skipped"}
# What "Next problem" jumps between. needs_review belongs here: a step that
# came back empty because the tool ran out of credit is exactly the thing the
# user has to go and look at, and it is not a crash.
_PROBLEM_STATES = {"failed", "needs_review"}


class _Elided(QLabel):
    """A label that shortens itself instead of clipping.

    Hindi and Gujarati run longer than English, so nothing on this screen gets
    a width that only fits the English string — the label keeps its full text
    for the tooltip and the accessible name, and elides whatever is on screen
    to whatever width the row actually got.
    """

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._full = i18n.t(text) if text else ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

    def setText(self, text: str):                  # noqa: N802 (Qt casing)
        # i18n patches QLabel.setText, and this override sits in front of it —
        # so the translation is asked for here, on the FULL string, rather than
        # on the shortened one that would match nothing in the catalogue.
        self._full = i18n.t(text or "")
        self.setToolTip(self._full)
        self.setAccessibleName(self._full)
        super().setText(self._full)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        if not self._full:
            return
        room = max(24, self.width())
        shown = QFontMetrics(self.font()).elidedText(
            self._full, Qt.ElideRight, room)
        if shown != super().text():
            super().setText(shown)


class TimelineDot(QWidget):
    """The medallion and the line beneath it, down the left of a run.

    This is what turns a stack of stage cards into a *sequence*: the resolved
    dots are behind you, the pulsing one is now, and the hollow ones are still
    to come.

    Everything it paints comes out of `theme.STATUS`, so the dot and the
    StatusBadge on the same row read the same row of the same table and cannot
    disagree about what the stage is doing — which they used to, "No response"
    having shipped as an amber badge over a red dot.

    The running dot moves. The old comment here promised a pulse and there was
    no timer in the file: the one cue that says "Prism is here now" was a
    static 45% accent ring on a near-white fill, the worst contrast in the
    system. Motion is a QTimer repaint and deliberately NOT a QGraphicsEffect —
    an effect-driven animation renders as nothing on a software rasteriser (see
    controls.effects_enabled), and the worst case for a repaint is that it
    holds still.
    """

    SIZE = 30
    MEDAL = 26                      # the disc; the rest is room for the pulse
    PULSE_MS = 170

    def __init__(self, icon_name: str, parent=None):
        super().__init__(parent)
        self._icon_name = icon_name
        self._state = "queued"
        self._last = False
        self._phase = 0.0
        self.setFixedWidth(self.SIZE)
        self.setMinimumHeight(self.SIZE)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.MinimumExpanding)
        self._timer = QTimer(self)
        self._timer.setInterval(self.PULSE_MS)
        self._timer.timeout.connect(self._tick)

    def set_state(self, state: str, last: bool = False):
        self._state = theme.status_key(state)
        self._last = last
        self._sync_timer()
        self.update()

    def state(self) -> str:
        return self._state

    # A timer behind a hidden widget is a repaint nobody sees and a wakeup the
    # machine pays for anyway — and it must stop the moment the stage leaves
    # the running state, or an idle app repaints for ever.
    def _sync_timer(self):
        _label, _ink, _bg, dot = theme.status(self._state)
        wants = dot in ("pulse", "spinner") and self.isVisible()
        if wants and not self._timer.isActive():
            self._timer.start()
        elif not wants and self._timer.isActive():
            self._timer.stop()

    def _tick(self):
        self._phase = (self._phase + 0.11) % 1.0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_timer()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        _label, ink, bg, kind = theme.status(self._state)
        pad = (self.SIZE - self.MEDAL) / 2
        box = QRectF(pad, pad, self.MEDAL, self.MEDAL)

        # Resolved states get a filled medallion with a white glyph; anything
        # still in flight or still to come keeps the stage's own icon on a
        # tint, so the sequence reads as "these are behind me, this is the job".
        if kind == "check":
            fill, glyph_ink, glyph = ink, theme.CARD, "check"
        elif kind == "cross":
            fill, glyph_ink, glyph = ink, theme.CARD, "x"
        elif kind == "solid":                       # needs review
            fill, glyph_ink, glyph = ink, theme.CARD, "alert"
        elif kind in ("square", "dash"):            # cancelled / skipped
            fill, glyph_ink, glyph = bg, ink, "minus"
        elif kind == "hollow":                      # queued / idle
            fill, glyph_ink, glyph = theme.CARD, theme.NEUTRAL[500], self._icon_name
        else:                                       # pulse / spinner / dashed
            fill, glyph_ink, glyph = bg, ink, self._icon_name

        # The expanding ring, drawn first so the disc sits on top of it.
        if kind == "pulse":
            grow = self._phase
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(ink, max(0.0, 0.45 * (1 - grow))), 1.6))
            spread = pad * grow * 2
            painter.drawEllipse(box.adjusted(-spread, -spread, spread, spread))

        painter.setBrush(theme.c(fill))
        if kind == "hollow":
            painter.setPen(QPen(theme.c(theme.NEUTRAL[300]), 1.4))
        elif kind == "dashed":                      # waiting
            pen = QPen(theme.c(ink, 0.8), 1.6, Qt.DashLine)
            pen.setDashPattern([2.4, 1.8])
            painter.setPen(pen)
        elif kind in ("pulse", "solid", "spinner"):
            painter.setPen(QPen(theme.c(ink, 0.5), 1.4))
        else:
            painter.setPen(Qt.NoPen)
        if kind == "square":                        # cancelled reads as a stop
            painter.drawRoundedRect(box, theme.R_CHIP, theme.R_CHIP)
        else:
            painter.drawEllipse(box)

        if kind == "spinner":                       # retrying
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(theme.c(ink), 1.8, Qt.SolidLine, Qt.RoundCap))
            start = int(-self._phase * 360 * 16) + 90 * 16
            painter.drawArc(box.adjusted(-1.5, -1.5, 1.5, 1.5), start, -110 * 16)

        pix = icons.pixmap(glyph, 14, glyph_ink)
        painter.drawPixmap(int((self.SIZE - 14) / 2),
                           int((self.SIZE - 14) / 2), pix)

        # The connector only reaches the next dot, so the last stage does not
        # trail a line into empty space.
        if not self._last and self.height() > self.SIZE:
            done = kind in ("check",)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.c(theme.OK, 0.45) if done
                             else theme.c(theme.NEUTRAL[200]))
            painter.drawRect(QRectF((self.SIZE - 2) / 2, self.SIZE, 2,
                                    self.height() - self.SIZE))


class StageCard(QWidget):
    """One step of the run: number, title, provider, state, duration, reason,
    and a body you can fold away."""

    # Raised whenever this stage's state changes, so the panel can keep the
    # header and the "next problem" control in step without polling.
    state_changed = Signal()
    # A Studio reel landed on this card and the user wants to fix its layout
    # by hand. Carries the mp4 path; the window opens the browser editor.
    edit_reel = Signal(str)
    # Arrow-key navigation between cards, handled by the panel: -1 / +1.
    move_focus = Signal(int)

    def __init__(self, stage: str, agent: str, index: int = 0, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.agent = agent or ""
        self._tried: list[str] = []      # tools that gave up on this stage
        self._handover = ""              # the engine's reason for the swap
        self._url = ""
        self._raw = ""   # raw text kept for copy, even when the body is rich
        self._collapsed = False
        self._state = "queued"
        self._detail = ""
        self._status_detail = ""
        self._note_echoes = False
        self._count = 0
        # How tall an open transcript may be. Raised by the panel when the run
        # timeline does not fill the viewport: the slack goes to showing more
        # of a real answer rather than to a bigger blank card.
        self._body_cap = 240
        self._last = False
        self.failed = False
        self.needs_review = False
        # Elapsed time, shown live. A spinner with no number reads as "this
        # might be stuck", and these customers are on modest laptops with no
        # way to tell a slow step from a hung one. The honest count is the
        # whole difference between waiting and worrying.
        self._started: float | None = None
        self._final: float | None = None
        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._paint_status)

        icon_name, title, blurb = STAGE_COPY.get(
            stage, ("grid", stage.title(), ""))
        self._title = title
        self._blurb = blurb

        # Focusable, so a nine-stage timeline is walkable without a mouse:
        # Tab reaches a card, Space folds it, Left/Right fold and unfold,
        # Up/Down step through the run.
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(title)

        shell = QHBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(theme.SPACE_3)
        # No alignment: the dot column must fill this row's full height so its
        # connector reaches the next stage. Top-aligning it collapsed the
        # widget to its own sizeHint — which for a bare QWidget is zero — and
        # nothing painted at all.
        self.dot = TimelineDot(icon_name)
        shell.addWidget(self.dot)

        card = Card()
        self.panel = card
        # The gap between stages lives inside this row rather than between
        # rows, so the dot column spans it and the connector stays unbroken.
        # With the spacing in the parent layout the line came out dashed.
        gapped = QVBoxLayout()
        gapped.setContentsMargins(0, 0, 0, theme.SPACE_3)
        gapped.addWidget(card)
        shell.addLayout(gapped, stretch=1)
        self.content = card.body(
            (theme.CARD_PAD - 4, theme.SPACE_3, theme.CARD_PAD - 4,
             theme.SPACE_3), spacing=theme.SPACE_1)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.number = QLabel(str(index) if index else "")
        self.number.setFixedWidth(18)
        self.number.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.number.setStyleSheet(
            theme.type_css("MONO", theme.NEUTRAL[500]) + " background: transparent;")
        head.addWidget(self.number)

        self.name = _Elided(title)
        self.name.setObjectName("h6")
        head.addWidget(self.name, stretch=1)

        # Provider. A tool's brand colour is allowed on 16-20px of badge and
        # nowhere larger — the app belongs to Prism.
        self._head = head
        self.tool_badge = C.ToolBadge(ai_server.display_agent(self.agent) or "?", 20, theme.R_CHIP)
        head.addWidget(self.tool_badge)
        self.tool_name = QLabel(ai_server.display_agent(self.agent))
        self.tool_name.setStyleSheet(
            theme.type_css("META", theme.NEUTRAL[700]) + " background: transparent;")
        head.addWidget(self.tool_name)

        # The one status implementation, driven by theme.STATUS. focusable is
        # off on every card: the card itself is the tab stop, and nine extra
        # stops between Back and Stop is worse for a keyboard user than none.
        self.status = StatusBadge("queued", "", focusable=False)
        head.addWidget(self.status)

        # A finished stage folds to its header and its one-line summary. On a
        # nine-stage run the alternative is a page of transcripts with the step
        # you actually want somewhere in the middle of it.
        self.chevron = QPushButton()
        self.chevron.setFlat(True)
        self.chevron.setCursor(Qt.PointingHandCursor)
        # Named, not guessed: this is the one icon-only control in the
        # timeline and it has to clear the 28px minimum target like everything
        # else. It was 20px, and only cleared it by accident of a stylesheet
        # min-height that happened to win.
        self.chevron.setFixedSize(C.MIN_TARGET, C.MIN_TARGET)
        self.chevron.setStyleSheet("border: none; background: transparent;")
        self.chevron.setToolTip(i18n.t("Show or hide this step's output"))
        icons.button_icon(self.chevron, "chevron-down", 13, theme.NEUTRAL[500])
        self.chevron.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed))
        head.addWidget(self.chevron)
        self.content.addLayout(head)

        # The explanation line. This is where the engine's own words land —
        # `blocked`, a failover `reason`, a skip reason, the snippet of what
        # came back — and it stays on screen when the card is folded, because
        # "why did this step do nothing" is the question a collapsed card is
        # least able to answer.
        self.note = QLabel(blurb)
        self.note.setWordWrap(True)
        self.note.setStyleSheet(
            theme.type_css("SUPPORT", theme.NEUTRAL[700]) + " background: transparent;")
        self.content.addWidget(self.note)

        # Duration · how many responses · the tools tried · the link, as text.
        self.facts = _Elided("")
        self.facts.setStyleSheet(
            theme.type_css("META") + " background: transparent;")
        self.facts.setVisible(False)
        self.content.addWidget(self.facts)

        self.body = QTextEdit(self)
        self.body.setObjectName("stageBody")
        self.body.setReadOnly(True)
        # Sized to its content, capped — a queued or waiting stage has nothing
        # to show, and a fixed box would park an empty rectangle on screen for
        # however long the tool takes to answer.
        self.body.document().documentLayout().documentSizeChanged.connect(
            self._autosize)
        self.body.setVisible(False)
        self.content.addWidget(self.body)

        # Actions hide with the body: while a stage is queued or waiting there
        # is nothing to copy and no tab to open, and a row of dead buttons
        # under an empty box reads as broken rather than pending.
        self.actions = QWidget(self)
        self.actions.setVisible(False)
        row = QHBoxLayout(self.actions)
        row.setContentsMargins(0, theme.SPACE_1, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.copy_btn = C.button(i18n.t("Copy output"), "secondary", "copy",
                                 small=True, on_click=self._copy)
        self.copy_btn.setEnabled(False)
        row.addWidget(self.copy_btn)
        self.open_btn = C.button(i18n.t("Open in tool"), "link", "external",
                                 on_click=self._open)
        self.open_btn.setVisible(False)
        row.addWidget(self.open_btn)
        # Only ever shown for a file result: it lands in ~/.prism/runs, which
        # Finder hides, so "here is the path" is not an answer on its own.
        self.reveal_btn = C.button(
            i18n.t("Show in folder"), "secondary", "folder", small=True,
            on_click=lambda: paths.reveal_result(self._url))
        self.reveal_btn.setVisible(False)
        row.addWidget(self.reveal_btn)
        # Studio reels only: the spec saved beside the video is a web page,
        # and fixing a misplaced text by hand beats re-prompting for it.
        self.edit_btn = C.button(i18n.t("Edit the layout"), "secondary",
                                 "pencil", small=True,
                                 on_click=lambda: self.edit_reel.emit(self._url))
        self.edit_btn.setToolTip(i18n.t(
            "Open this reel in your browser: drag anything into place, "
            "resize it, retype it or delete it, then render it again."))
        self.edit_btn.setVisible(False)
        row.addWidget(self.edit_btn)
        row.addStretch(1)
        self.content.addWidget(self.actions)

        self._paint_frame()
        self.set_state("queued")
        self.set_collapsed(False)

        # The entrance fade is GATED, and the else branch is empty on purpose.
        #
        # A widget carrying a QGraphicsEffect is painted through a separate
        # pipeline that renders nothing at all on software rasterisers, virtual
        # machines and remote desktop. A failed drop shadow costs a shadow; a
        # failed opacity effect costs the whole card, because the animation
        # starts at 0.0 — present, correctly sized, permanently invisible. That
        # was live: on such a machine a nine-stage run showed nine blank gaps
        # and read as the app having lost the work. Shadows were turned off for
        # exactly this reason and this fade slipped through behind them.
        if C.effects_enabled():
            effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(effect)
            self._fade_anim = QPropertyAnimation(effect, b"opacity", self)
            self._fade_anim.setDuration(220)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.OutQuart)
            self._fade_anim.start()

    # ── identity ────────────────────────────────────────────────────────────
    def set_index(self, index: int):
        self.number.setText(str(index) if index else "")

    def set_agent(self, agent: str, note_swap: bool = True):
        """Point this step at a different tool.

        Called on a failover. The card is REUSED rather than replaced: building
        a second StageCard here left the first one in the timeline for ever —
        nothing could update it, "Next problem" stopped counting it, and the
        elapsed clock started again from zero.
        """
        agent = agent or ""
        if not agent or agent == self.agent:
            return
        if self.agent:
            self._tried.append(self.agent)
            if note_swap:
                self.set_note(i18n.t(
                    "{failed} could not finish this step — Prism handed it to "
                    "{agent}.").format(failed=ai_server.display_agent(self.agent),
                            agent=ai_server.display_agent(agent)))
        self.agent = agent
        # Swapped rather than restyled: ToolBadge owns its own metrics, and
        # re-deriving them here is how a second, slightly-different badge gets
        # into the app.
        fresh = C.ToolBadge(ai_server.display_agent(agent), 20, theme.R_CHIP)
        old = self._head.replaceWidget(self.tool_badge, fresh)
        if old is not None:
            self.tool_badge.hide()   # before setParent(None): avoids ghost-window flash
            self.tool_badge.setParent(None)
            self.tool_badge.deleteLater()
        self.tool_badge = fresh
        self.tool_name.setText(ai_server.display_agent(agent))
        self._paint_facts()

    def set_note(self, text: str, echoes_body: bool = False):
        """The reason line — what this step is doing, or why it did nothing.

        `echoes_body` marks a note that is the head of the transcript below it
        (a result preview, an error, a blocked reason). Those hide while the
        card is open, because the body already says it in full, and come back
        when it folds — which is the whole point of them: a folded step still
        has to be able to answer "so what happened here".
        """
        self.note.setText(text or "")
        self._note_echoes = bool(echoes_body)
        self._sync_note()

    def _sync_note(self):
        self.note.setVisible(bool(self.note.text())
                             and not (self._note_echoes
                                      and self.body.isVisible()))

    # ── state ───────────────────────────────────────────────────────────────
    def set_state(self, state: str, detail: str = None, note: str = None,
                  note_echoes_body: bool = False):
        """One call for the badge, the dot, the frame and the clock, so the
        four can never disagree about what this stage is doing.

        `detail` is the extra word beside the state (the wait ceiling, say);
        the elapsed figure is appended automatically and frozen — not dropped —
        once the stage stops running.
        """
        key = theme.status_key(state)
        self._state = key
        if detail is not None:
            self._detail = detail
        if note is not None:
            self.set_note(note, note_echoes_body)

        if key in _LIVE_STATES:
            if self._started is None:
                self._started = time.monotonic()
            self._final = None
            self._ticker.start()
        else:
            self._ticker.stop()
            if self._started is not None and self._final is None:
                self._final = time.monotonic() - self._started

        self.failed = key == "failed"
        self.needs_review = key == "needs_review"
        self.dot.set_state(key, self._last)
        self._paint_status()
        self._paint_facts()
        self._paint_frame()

        # Collapse what is done, open what needs a human. Every CI timeline
        # worth copying does this, and it is the difference between a
        # nine-stage run you can read and one you have to scroll. Driven from
        # here rather than from set_done/set_error so that every path which can
        # finish a stage — including the ones that finish it by timing out —
        # folds the same way.
        if key in ("completed", "skipped", "cancelled"):
            self.set_collapsed(True)
        elif key in _PROBLEM_STATES:
            self.set_collapsed(False)
        self.state_changed.emit()

    def state(self) -> str:
        return self._state

    def is_problem(self) -> bool:
        return self._state in _PROBLEM_STATES

    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    def _elapsed(self) -> float | None:
        if self._final is not None:
            return self._final
        if self._started is not None and self._state in _LIVE_STATES:
            return time.monotonic() - self._started
        return None

    def _paint_status(self):
        parts = [p for p in (self._detail,) if p]
        span = self._elapsed()
        if span is not None and span >= 1:
            parts.append(short_duration(span))
        self._status_detail = " · ".join(parts)
        self.status.set_state(self._state, self._status_detail)
        self.setAccessibleName(f"{self.number.text()} {self._title}. "
                               f"{self.status.accessibleName()}".strip())

    def status_text(self) -> str:
        """What the status badge is saying, as one string — for tests and for
        anything that needs the state as words rather than as a widget."""
        label, _ink, _bg, _dot = theme.status(self._state)
        return f"{label} {self._status_detail}".strip()

    def _paint_facts(self):
        bits = []
        if len(self._tried) >= 1:
            # Which tools this step went through, and — the part that used to
            # live for fifteen seconds in the status bar and nowhere else —
            # the engine's own reason for the handover.
            hand = " → ".join(ai_server.display_agent(a) for a in self._tried + [self.agent])
            bits.append(f"{hand} ({self._handover})" if self._handover
                        else hand)
        span = self._elapsed()
        if span is not None and span >= 1:
            bits.append(short_duration(span))
        if self._count:
            bits.append(i18n.t("1 response") if self._count == 1
                        else i18n.t("{n} responses").format(n=self._count))
        if self._url and not paths.is_local_result(self._url):
            bits.append(_short_url(self._url))
        self.facts.setText(" · ".join(bits))
        self.facts.setVisible(bool(bits))

    def _paint_frame(self):
        """The card's own edge carries the state too. A failed step with a red
        hairline is findable in a column of nine; a focused one has to show
        where the keyboard is."""
        if self.hasFocus():
            edge = theme.ACCENT
        elif self._state == "failed":
            edge = theme.ERR_LINE
        elif self._state == "needs_review":
            edge = theme.WARN
        else:
            edge = theme.HAIRLINE
        self.panel.setStyleSheet(
            f"#card {{ background: {theme.CARD};"
            f" border-radius: {theme.R_CARD}px; border: 1px solid {edge}; }}")

    # ── folding and keyboard ────────────────────────────────────────────────
    def set_collapsed(self, collapsed: bool):
        """Fold the output away, keeping the header and the reason line.

        A failed stage opens itself — see set_state — but the user may still
        fold it by hand, which is why this does not special-case `failed`.
        """
        self._collapsed = bool(collapsed)
        icons.button_icon(
            self.chevron,
            "chevron-right" if self._collapsed else "chevron-down", 13,
            theme.NEUTRAL[500])
        self.chevron.setAccessibleName(
            i18n.t("Show this step's output") if self._collapsed
            else i18n.t("Hide this step's output"))
        self._autosize()

    def set_last(self, last: bool):
        self._last = last
        self.dot.set_state(self._state, last)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._paint_frame()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._paint_frame()

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.set_collapsed(not self._collapsed)
            return
        if key == Qt.Key_Right and self._collapsed:
            self.set_collapsed(False)
            return
        if key == Qt.Key_Left and not self._collapsed:
            self.set_collapsed(True)
            return
        if key in (Qt.Key_Down, Qt.Key_Up):
            self.move_focus.emit(1 if key == Qt.Key_Down else -1)
            return
        super().keyPressEvent(event)

    def _autosize(self):
        has_content = bool(self.body.toPlainText().strip())
        show = has_content and not self._collapsed
        self.body.setVisible(show)
        self.actions.setVisible(show)
        self.chevron.setVisible(has_content)
        if show:
            height = int(self.body.document().size().height()) + 22
            self.body.setFixedHeight(max(56, min(self._body_cap, height)))
        self._sync_note()

    def body_is_clipped(self) -> bool:
        """True when the transcript is taller than the room it was given —
        i.e. when handing this card more height would show more real text."""
        if self._collapsed or not self.body.isVisible():
            return False
        return int(self.body.document().size().height()) + 22 > self._body_cap

    def set_body_cap(self, cap: int):
        cap = max(240, int(cap))
        if cap != self._body_cap:
            self._body_cap = cap
            self._autosize()

    # ── results ─────────────────────────────────────────────────────────────
    def _set_url(self, url: str):
        self._url = url or ""
        self.open_btn.setVisible(bool(url))
        # A local agent's result is a file, not a tab. Say so on the button —
        # "Open in tool" over a rendered MP4 reads as a link to somewhere else,
        # and the user never learns the video is already on their machine.
        local = paths.is_local_result(self._url)
        self.reveal_btn.setVisible(local)
        self.edit_btn.setVisible(local and self._editable_reel(self._url))
        if local:
            video = self._url.lower().endswith((".mp4", ".mov", ".m4v", ".webm"))
            self.open_btn.setText(i18n.t("Play video") if video
                                  else i18n.t("Open file"))
            icons.button_icon(self.open_btn, "play" if video else "folder", 15,
                              theme.ACCENT_RAMP[700])
        elif url:
            self.open_btn.setText(i18n.t("Open in tool"))
            icons.button_icon(self.open_btn, "external", 15,
                              theme.ACCENT_RAMP[700])
        self._paint_facts()

    @staticmethod
    def _editable_reel(url: str) -> bool:
        """A video with a Studio spec saved beside it — reel_<stamp>.json
        next to reel_<stamp>.mp4, scenes carrying real HTML."""
        if not url.lower().endswith(".mp4"):
            return False
        try:
            import json as _json
            with open(url[:-4] + ".json", encoding="utf-8") as f:
                spec = _json.load(f)
            import core_bridge as CB
            return CB.get_reel_edit().is_studio_spec(spec)
        except Exception:                               # noqa: BLE001
            return False

    def set_waiting(self, seconds: int):
        if ai_server.active():
            self.set_state("waiting", i18n.t("up to {n}s").format(n=seconds),
                           note=i18n.t("Prism AI is working on this step."))
            return
        self.set_state("waiting", i18n.t("up to {n}s").format(n=seconds),
                       note=i18n.t("Waiting for {tool} to answer. Prism is "
                                   "watching the tab, not asking again.")
                       .format(tool=ai_server.display_agent(self.agent) or i18n.t("the tool")))

    def set_done(self, texts: list[str], url: str, timed_out: bool = False,
                 blocked: str = "", exhausted: bool = False, count: int = None,
                 snippet: str = "", files: list | None = None,
                 prism_note: str = "", missing: str = ""):
        """A stage came back. Four different endings live in here and the
        engine tells us which — it always did, and the difference used to be
        thrown away at the door.

        `files` are the documents/sheets/decks the engine harvested from this
        step and saved to Prism Artifacts — named on the card, so a step whose
        whole answer was a DOCX reads as "made a file", not as prose that
        happens to mention one.
        """
        self._set_url(url)
        self._count = int(count if count is not None else len(texts or []))
        note = ""
        if files:
            rows = []
            for f in files:
                name = _escape(str(f.get("name") or os.path.basename(
                    f.get("saved") or f.get("path") or "")) or i18n.t("file"))
                size = ""
                try:
                    size = f" · {int(f.get('size') or 0) / 1e6:.1f} MB"
                except (TypeError, ValueError):
                    pass
                rows.append(f"<b>{name}</b>{size}")
            note += (f"<p style='line-height:150%'>"
                     + _escape(i18n.t("Saved to Prism Artifacts")) + ": "
                     + ", ".join(rows) + "</p>")
            if prism_note:
                # "Prism saved the step's own text as a Word document" — the
                # tool answered in prose, so the file is Prism's, and the
                # person is told so rather than left to assume the tool made
                # it (core/contract.document_from_text).
                note += (f"<p style='color:{theme.NEUTRAL[600]};"
                         f"line-height:150%'>" + _escape(prism_note) + "</p>")
        if timed_out:
            # Our clock ran out, not the tool's: it is still generating in that
            # tab and will land the finished deck/doc/app there. Saying "done"
            # here would send the user away from the only place the real
            # result appears, so the link is the headline.
            note = (f"<p style='color:{theme.NEUTRAL[600]};line-height:150%'>"
                    + _escape(i18n.t(
                        "Prism stopped waiting, but the tool is still working "
                        "— open it to pick up the finished result."))
                    + "</p>")

        if texts and paths.is_local_result(url):
            # The whole result IS the file. Without this the card printed the
            # engine's one-line note and nothing else, so a finished render
            # looked like a step that had produced nothing. Copy gives the
            # path, since that is the only thing worth pasting anywhere.
            size = ""
            try:
                size = f" · {os.path.getsize(url) / 1e6:.1f} MB"
            except OSError:
                pass
            self._raw = url
            self.body.setHtml(
                f"<p style='line-height:150%'>"
                + _escape(i18n.t("Made on this machine")) + " — "
                f"<b>{_escape(os.path.basename(url))}</b>{size}<br>"
                f"<span style='color:{theme.NEUTRAL[600]}'>"
                f"{_escape(os.path.dirname(url))}</span></p>")
            self.copy_btn.setEnabled(True)
            self.set_state("completed",
                           note=f"{os.path.basename(url)}{size}",
                           note_echoes_body=True)
            return

        if texts:
            self._raw = "\n\n———\n\n".join(texts)
            if missing and not timed_out:
                # The step answered, but not with the thing it was for — an
                # image step that wrote about a picture, a document step that
                # pasted text. It used to read "completed", and the gap was
                # found only when the reel came out blank (core/contract.py).
                note = (f"<p style='color:{theme.NEUTRAL[700]};line-height:150%'>"
                        f"<b>{_escape(missing[:1].upper() + missing[1:])}.</b></p>"
                        + note)
            # render the AI's response as formatted markdown (it's a document),
            # but keep the raw text for copy so paste-elsewhere is verbatim
            self.body.setHtml(note + render_markdown(self._raw))
            self.copy_btn.setEnabled(True)
            # The engine hands over its own first-200-characters snippet; the
            # panel used to build a worse one of its own and then not show it.
            preview = (snippet or texts[0] or "").strip().replace("\n", " ")
            if len(preview) > 260:
                preview = preview[:259] + "…"
            if timed_out:
                self.set_state("needs_review", note=i18n.t(
                    "Prism stopped waiting, but the tool is still working — "
                    "open it to pick up the finished result."))
            elif missing:
                self.set_state("needs_review",
                               note=missing[:1].upper() + missing[1:])
            else:
                self.set_state("completed", note=preview or self._blurb,
                               note_echoes_body=bool(preview))
            return

        # Nothing came back. The engine has already asked the three questions
        # that matter — has this tool run out, is this a sign-in wall, did the
        # markup change — and `blocked` is its answer in plain words. It is the
        # best piece of copy in the whole run flow and nothing showed it.
        self._raw = ""
        if blocked:
            reason = blocked
        elif timed_out:
            reason = i18n.t("Prism stopped waiting, but the tool is still "
                            "working — open it to pick up the finished result.")
        elif url:
            reason = i18n.t("Prism couldn't read the response off the page. "
                            "Open the tool to grab the result by hand — the "
                            "run finished, only the scrape missed it.")
        else:
            reason = i18n.t("No response was captured for this step.")
        extra = ""
        if exhausted:
            extra = ("<p style='line-height:150%'>" + _escape(i18n.t(
                "Sign in to that tool, switch this step to another one in the "
                "plan, or come back when the free allowance resets.")) +
                "</p>")
        self.body.setHtml(
            f"<p style='color:{theme.NEUTRAL[700]};line-height:150%'>"
            f"{_escape(reason)}</p>{extra}")
        self.copy_btn.setEnabled(False)
        # The run carried on and a human should look at this step: that is
        # needs_review, not a crash and not a success.
        self.set_state("needs_review",
                       i18n.t("out of credit") if exhausted else None,
                       note=reason, note_echoes_body=True)

    def set_error(self, error: str, url: str = ""):
        self._raw = error
        # A failed step can still leave a live tab behind — the tool often
        # finishes on its own after Prism loses the thread. Offer it.
        self._set_url(url)
        tail = ("<p style='color:" + theme.NEUTRAL[600] + ";line-height:150%'>"
                + _escape(i18n.t("The tool's tab is still on the job — open it "
                                 "to see whether it finished without Prism."))
                + "</p>") if url else ""
        self.body.setHtml(
            f"<p style='color:{theme.ERR_INK};line-height:150%'>"
            f"{_escape(error)}</p>{tail}")
        self.copy_btn.setEnabled(True)
        self.set_state("failed", note=error,
                       note_echoes_body=True)

    def set_skipped(self, reason: str = ""):
        """The engine left this step out. It emits `stage_skipped` for exactly
        this — the comment where it is raised says it was added so the GUI
        would stop silently dropping a step — and the GUI dropped it anyway."""
        self.set_state("skipped", note=reason or i18n.t(
            "Prism left this step out of the run."))

    def set_cancelled(self, note: str = ""):
        self.set_state("cancelled", note=note or i18n.t(
            "Stopped before this step finished."))

    def set_retrying(self, reason: str = ""):
        self.set_state("retrying", note=reason or i18n.t(
            "That reply could not be used — asking again."))

    @property
    def duration(self) -> float | None:
        """Seconds this stage took, or None if it never finished."""
        return self._final

    def _copy(self):
        QApplication.clipboard().setText(self._raw or self.body.toPlainText())
        self.copy_btn.setText(i18n.t("Copied"))
        QTimer.singleShot(
            1500, lambda: self.copy_btn.setText(i18n.t("Copy output")))

    def _open(self):
        if self._url:
            paths.open_result(self._url)


class RunHeader(Card):
    """Task, overall state, step counter, elapsed, progress — and Stop.

    None of this existed. Every figure in it was already computed somewhere:
    `_push_active_run` builds "Step 3 of 7" and a progress fraction on every
    stage_start and posts them to *Home*, so the one screen that could not say
    how far along the run was, was the run screen.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        col = self.body((theme.CARD_PAD, theme.SPACE_3, theme.CARD_PAD,
                         theme.SPACE_3), spacing=theme.SPACE_2)

        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_3)
        left = QVBoxLayout()
        left.setSpacing(2)
        left.addWidget(C.kicker(i18n.t("RUNNING NOW")))
        self.task = _Elided(i18n.t("Untitled task"))
        self.task.setObjectName("h4")
        left.addWidget(self.task)
        top.addLayout(left, stretch=1)
        self.status = StatusBadge("idle", "", focusable=True)
        top.addWidget(self.status, alignment=Qt.AlignTop)
        col.addLayout(top)

        self.counts = QLabel("")
        self.counts.setStyleSheet(
            theme.type_css("META") + " background: transparent;")
        col.addWidget(self.counts)

        # One segment per step: finished ones filled, the live one moving.
        self.progress = Loader("stages", bare=True)
        self.progress.setVisible(True)
        col.addWidget(self.progress)

    def set_task(self, text: str):
        self.task.setText(text or i18n.t("Untitled task"))


class OutputPanel(QWidget):
    back_requested = Signal()
    stop_requested = Signal()
    skip_requested = Signal()
    fallback_requested = Signal()
    edit_reel = Signal(str)         # a card's Studio reel wants the editor

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cards: dict[str, StageCard] = {}
        self._order: list[str] = []
        self._live: str = ""
        self._run_started: float | None = None
        self._run_final: float | None = None
        self._running = False
        self._finished = False
        self._cancelled = False
        self._problem_at = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.SPACE_3)

        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.back_btn = C.button("", "tertiary",
                                 on_click=self.back_requested.emit)
        head.addWidget(self.back_btn)
        head.addStretch(1)

        # A failed step on a nine-stage run is somewhere in a long column, and
        # scrolling to find it is the wrong job to give somebody who has just
        # been told their work did not finish. Appears only when there is one.
        self.problem_btn = C.button(i18n.t("Next problem"), "secondary",
                                    "alert", small=True,
                                    on_click=self._next_problem)
        self.problem_btn.setVisible(False)
        head.addWidget(self.problem_btn)

        # One tool stuck generating — an image that never finishes, a site
        # whose page has changed — used to hold the whole run hostage: the
        # only ways out were waiting out the cap or stopping everything.
        # Skip gives up on THIS step only, keeps whatever it produced, and
        # the run carries on.
        self.skip_btn = C.button(i18n.t("Skip this step"), "secondary",
                                 "play", small=True, on_click=self._on_skip)
        self.skip_btn.setToolTip(i18n.t(
            "Give up on the step that's running — keep whatever it has "
            "produced so far — and move on to the next one. Use it when a "
            "tool is stuck generating."))
        head.addWidget(self.skip_btn)

        # The other way past a stuck tool. Skip gives the step up; this
        # hands it to the next tool in its category right now -- what the
        # failover pass would do by itself once the cap ran out, for the
        # person who can already see the tool has errored and does not want
        # to sit out ten minutes for Prism to notice.
        self.fallback_btn = C.button(i18n.t("Use fallback"), "secondary",
                                     "arrow-right", small=True,
                                     on_click=self._on_fallback)
        self.fallback_btn.setToolTip(i18n.t(
            "Stop waiting for this tool and hand the step to its fallback "
            "tool now. Use it when you can see the tool has errored and "
            "you don't want to wait for the timeout."))
        head.addWidget(self.fallback_btn)

        # A run is tens of minutes of browser automation. Without this the
        # only way out is force-quitting the app, which loses every step that
        # had already finished — the engine has supported stopping cleanly all
        # along, and nothing here was calling it.
        self.stop_btn = C.button(i18n.t("Stop the run"), "destructive", "stop",
                                 on_click=self._on_stop)
        self.stop_btn.setToolTip(i18n.t(
            "Finishes the step that's running, keeps everything already done, "
            "and stops there."))
        head.addWidget(self.stop_btn)
        root.addLayout(head)

        self.header = RunHeader()
        root.addWidget(self.header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.verticalScrollBar().valueChanged.connect(lambda _: scroll.viewport().update())
        inner = QWidget()
        self.cards_box = QVBoxLayout(inner)
        self.cards_box.setContentsMargins(0, 2, 0, 2)
        # Zero: each StageCard carries its own bottom gap so the timeline
        # connector runs unbroken between one dot and the next.
        self.cards_box.setSpacing(0)

        # An empty run screen centres its message in the whole height it is
        # given rather than top-anchoring a dashed label over a grey field.
        self.empty = C.EmptyState(
            "clock", i18n.t("Nothing has run yet"),
            i18n.t("Each step appears here as Prism reaches it, with what the "
                   "tool sent back and how long it took."))
        self.cards_box.addWidget(self.empty, stretch=1)
        # The tail exists only to stop the last card being inflated to fill the
        # viewport. It is switched off while the empty state is showing, so
        # that state gets the FULL height to centre itself in — the trailing
        # stretch over a small card is the exact line that produces a grey void.
        self.cards_box.addStretch(0)
        scroll.setWidget(inner)
        self.scroll = scroll
        root.addWidget(scroll, stretch=1)

        # One clock for the whole run, so the header's elapsed figure moves
        # even while no single stage is on the clock.
        self._run_ticker = QTimer(self)
        self._run_ticker.setInterval(1000)
        self._run_ticker.timeout.connect(self._refresh_header)

        self.set_finished(False)
        self._refresh_header()

    # ── panel chrome ────────────────────────────────────────────────────────
    def _on_skip(self):
        # Not latched like Stop: skipping two slow steps in a row is a
        # legitimate thing to do. The engine clears the flag per press.
        self.skip_requested.emit()

    def _on_fallback(self):
        # Not latched either: a second press during the retry means "not
        # that tool either" and moves to the next one.
        self.fallback_requested.emit()

    def _on_stop(self):
        # Latch immediately so a second click can't queue a second stop, and
        # so the label stops claiming an action that is already under way. The
        # engine finishes the current step before it winds up, which can take
        # a moment, and silence there reads as the button not having worked.
        self.stop_btn.setEnabled(False)
        self.stop_btn.setText(i18n.t("Stopping…"))
        self.stop_requested.emit()

    def set_running(self, running: bool):
        """Show Stop only while there is something to stop."""
        self._running = bool(running)
        self.stop_btn.setVisible(running)
        self.skip_btn.setVisible(running)
        # No websites to fall back to when AI runs through Prism's server.
        self.fallback_btn.setVisible(running and not ai_server.active())
        if running:
            self._finished = False
            self.stop_btn.setEnabled(True)
            self.stop_btn.setText(i18n.t("Stop the run"))
            icons.button_icon(self.stop_btn, "stop", 15, theme.ERR_INK)
            if self._run_started is None:
                self._run_started = time.monotonic()
            self._run_final = None
            self._run_ticker.start()
        else:
            self._run_ticker.stop()
            if self._run_started is not None and self._run_final is None:
                self._run_final = time.monotonic() - self._run_started
            # set_running(False) is only ever "the run is over" — it is called
            # from _on_run_done, from _on_run_failed and from set_finished. So
            # resolving stranded cards here rather than in set_finished covers
            # the failed-run path too, which calls set_running and nothing
            # else: without it a card sits on RUNNING with its clock going
            # after the run has already collapsed.
            self._resolve_unfinished()
        self._refresh_header()

    def _resolve_unfinished(self):
        """Nothing may still claim to be working once the run has stopped."""
        for key in self._order:
            card = self._cards[key]
            if card.is_terminal():
                continue
            if self._cancelled or card.state() in _LIVE_STATES:
                card.set_cancelled()
            else:
                card.set_skipped(i18n.t("The run ended before Prism reached "
                                        "this step."))

    def set_finished(self, finished: bool):
        """Once the run is done the plan behind this page is spent, and going
        back clears it — so the button has to say so. Mid-run (or after a
        failure, where the plan is still worth retrying) it stays a plain
        back link."""
        self._finished = bool(finished)
        if finished:
            self.set_running(False)
            self.back_btn.setText(i18n.t("Start something new"))
            icons.button_icon(self.back_btn, "plus", 15, theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip(i18n.t(
                "Clears these steps and the task, ready for the next one"))
            # Anything the run never reached is resolved rather than left
            # spinning: a card still saying QUEUED after the run has ended is
            # the same silence stage_skipped was invented to end.
            self._resolve_unfinished()
        else:
            self.back_btn.setText(i18n.t("Back to the steps"))
            icons.button_icon(self.back_btn, "chevron-left", 15,
                              theme.ACCENT_RAMP[700])
            self.back_btn.setToolTip(i18n.t(
                "Your steps are still there — nothing is lost"))
        self._refresh_header()

    def set_task(self, text: str):
        """The sentence the user typed, on the screen doing the work."""
        self.header.set_task((text or "").strip())

    def clear(self):
        for stage in list(self._cards):
            self._cards[stage].hide()   # before setParent(None): avoids ghost-window flash
            self._cards[stage].setParent(None)
            self._cards[stage].deleteLater()
        self._cards = {}
        self._order = []
        self._live = ""
        self._run_started = None
        self._run_final = None
        self._cancelled = False
        self._finished = False
        self.empty.setVisible(True)
        self._sync_tail()
        # A new run starts with no problems and no place in the cycle. Leaving
        # either behind would show "Next problem (2)" over an empty timeline.
        self._problem_at = -1
        self._sync_problems()
        self._refresh_header()

    def set_plan(self, steps, followup: bool = False,
                 prior_responses: dict = None, prior_links: dict = None,
                 prior_agents: dict = None):
        """Seed the timeline with every step the run is about to take.

        `steps` is what AgentsPanel.selected_agents() returns — {stage: tool} —
        or any ordered list of (stage, tool) pairs.

        When `followup` is True, existing completed cards are preserved so
        the person can continue seeing the already work done section.
        """
        if not followup:
            self.clear()
        else:
            # If workbench was clean (e.g. follow-up from History), populate
            # the completed cards from prior_responses so already work done is shown.
            if not self._cards and prior_responses:
                links = prior_links or {}
                agents = prior_agents or {}
                for stage, texts in prior_responses.items():
                    if not texts:
                        continue
                    agent = agents.get(stage) or ""
                    card = self._ensure_card(stage, agent)
                    card.set_done(texts, links.get(stage, ""))

        items = list(steps.items()) if isinstance(steps, dict) else list(steps)
        if followup:
            # For any existing card whose stage is being re-run in the follow-up,
            # archive the previous card so its completed deliverable stays visible
            # in the already-done section while the new follow-up card is queued.
            for stage, agent in items:
                if stage in self._cards and self._cards[stage].state() == "completed":
                    old_card = self._cards[stage]
                    old_key = f"{stage}_prior"
                    suffix = 1
                    while old_key in self._cards:
                        suffix += 1
                        old_key = f"{stage}_prior_{suffix}"
                    self._cards[old_key] = old_card
                    del self._cards[stage]
                    idx = self._order.index(stage)
                    self._order[idx] = old_key
                    old_card.set_note(i18n.t("Completed in earlier run"))

        for stage, agent in items:
            self._ensure_card(stage, agent)

        # Re-number all cards sequentially (1, 2, 3...)
        for i, key in enumerate(self._order):
            if key in self._cards:
                self._cards[key].number.setText(str(i + 1))
                self._cards[key].set_last(i == len(self._order) - 1)

        self._refresh_header()

    def _sync_tail(self):
        """Hand the leftover height to the empty state, or to the tail spacer.

        Exactly one of the two may hold it. With both stretching, the empty
        state centres itself in half the page and reads as top-anchored again.
        """
        tail = self.cards_box.count() - 1
        if tail >= 0:
            self.cards_box.setStretch(tail, 0 if self.empty.isVisible() else 1)

    def _ensure_card(self, stage: str, agent: str) -> StageCard:
        card = self._cards.get(stage)
        if card is not None:
            return card
        # If "artwork" comes in and "visual" was in the plan and is still queued,
        # reuse the "visual" card: it is the same deliverable (making images).
        if stage == "artwork" and "visual" in self._cards and self._cards["visual"]._state == "queued":
            card = self._cards.pop("visual")
            card.stage = "artwork"
            self._cards["artwork"] = card
            idx = self._order.index("visual")
            self._order[idx] = "artwork"
            return card
        self.empty.setVisible(False)
        card = StageCard(stage, agent, index=len(self._order) + 1)
        card.edit_reel.connect(self.edit_reel.emit)
        card.state_changed.connect(self._on_card_state)
        card.move_focus.connect(
            lambda step, key=stage: self._focus_neighbour(key, step))
        self._cards[stage] = card
        self._order.append(stage)
        # Before the trailing stretch, and before the empty state, so the
        # timeline always reads top-down.
        self.cards_box.insertWidget(len(self._order) - 1, card)
        # Un-tail the one before it, or the connector stops at the
        # second-to-last dot and the chain looks broken.
        for i, key in enumerate(self._order):
            self._cards[key].set_last(i == len(self._order) - 1)
        self._sync_tail()
        return card

    # ── engine events ───────────────────────────────────────────────────────
    def stage_started(self, stage: str, agent: str):
        card = self._ensure_card(stage, agent)
        # Reuse, never replace. A failover calls this a second time for the
        # same stage; building another card left the first one orphaned in the
        # timeline with a clock that had restarted from zero.
        card.set_agent(agent)
        self._live = stage
        if self._run_started is None:
            self._run_started = time.monotonic()
        card.set_state("running", "", note=card._blurb)
        self._refresh_header()

    def stage_waiting(self, stage: str, seconds: int):
        card = self._cards.get(stage)
        if card:
            card.set_waiting(seconds)
        self._refresh_header()

    def stage_done(self, stage: str, texts: list[str], url: str,
                   timed_out: bool = False, blocked: str = "",
                   exhausted: bool = False, count: int = None,
                   snippet: str = "", files: list | None = None,
                   prism_note: str = "", missing: str = ""):
        card = self._cards.get(stage)
        if card:
            card.set_done(texts, url, timed_out, blocked=blocked,
                          exhausted=exhausted, count=count, snippet=snippet,
                          files=files, prism_note=prism_note, missing=missing)
        if self._live == stage:
            self._live = ""
        self._refresh_header()

    def stage_error(self, stage: str, error: str, url: str = ""):
        card = self._cards.get(stage)
        if card:
            card.set_error(error, url)
        if self._live == stage:
            self._live = ""
        self._refresh_header()

    def stage_failover(self, stage: str, failed: str, agent: str,
                       reason: str = "", exhausted: bool = False):
        """A tool gave up and Prism is handing the step to another one.

        The engine says WHY in `reason` — "this tool has run out", "this is a
        sign-in wall", "the site changed its markup". The panel used to pick
        between two hardcoded phrases and put them in the status bar for
        fifteen seconds, which is the one place a customer who has walked away
        will never see them.
        """
        card = self._ensure_card(stage, failed or agent)
        why = reason or (i18n.t("it has hit its usage limit") if exhausted
                         else i18n.t("it couldn't finish"))
        # Kept on the card rather than announced and forgotten: the reason has
        # to still be there when the customer comes back to a finished run.
        card._handover = why
        card.set_agent(agent, note_swap=False)
        card.set_retrying(i18n.t("{failed} stopped: {why} — trying {agent}.")
                          .format(failed=failed or i18n.t("the tool"),
                                  why=why, agent=agent))
        self._live = stage
        self._refresh_header()

    def stage_recovered(self, stage: str, agent: str, failed: str = "",
                        texts: list[str] = None, url: str = ""):
        card = self._ensure_card(stage, agent)
        card.set_agent(agent, note_swap=False)
        card.set_done(texts or [], url, False)
        if failed:
            card.set_note(i18n.t("{agent} finished this step after {failed} "
                                 "could not.").format(agent=agent,
                                                      failed=failed))
        if self._live == stage:
            self._live = ""
        self._refresh_header()

    def stage_unrecovered(self, stage: str, failed: str = "",
                          reason: str = ""):
        card = self._cards.get(stage)
        if not card:
            return
        card.set_state("failed", note=i18n.t(
            "No other tool could finish this step either. {reason}")
            .format(reason=reason or "").strip())
        self._refresh_header()

    def stage_skipped(self, stage: str, agent: str = "", reason: str = ""):
        """`stage_skipped` exists in the engine solely so this panel would stop
        losing a step, and this panel lost it anyway — the event fell straight
        through the handler's if/elif chain."""
        card = self._ensure_card(stage, agent)
        card.set_skipped(reason)
        self._refresh_header()

    def stage_retry(self, stage: str, reason: str = ""):
        card = self._cards.get(stage)
        if card:
            card.set_retrying(
                i18n.t("Prism is asking again: {reason}.").format(reason=reason)
                if reason else "")
        self._refresh_header()

    def scene_progress(self, index: int, total: int):
        """`reel_scene` counts scenes inside a video render. It names no stage
        — it can only ever be the live one — so it lands on the live card."""
        card = self._cards.get(self._live)
        if card:
            card.set_state("running", i18n.t("scene {n} of {total}").format(
                n=index, total=total))

    def run_cancelled(self, stage: str = "", done: int = 0):
        """Stop was pressed. Emitted from three places in the engine and the
        panel marked nothing: the in-flight card kept saying "Working…" with
        its clock running for ever."""
        self._cancelled = True
        target = stage or self._live
        for key in self._order:
            card = self._cards[key]
            if card.is_terminal():
                continue
            if key == target or card.state() in _LIVE_STATES:
                card.set_cancelled()
            else:
                card.set_cancelled(i18n.t("The run was stopped before Prism "
                                          "reached this step."))
        self._live = ""
        self.set_running(False)
        self._refresh_header()

    def browser_lost(self, stage: str = "", error: str = "", done: int = 0):
        """Chrome went away. Not a failed step — a failed run — and the
        engine's `error` was never shown anywhere."""
        card = self._cards.get(stage or self._live)
        if card:
            card.set_error(error or i18n.t("The browser window was closed."))
        for key in self._order:
            other = self._cards[key]
            if other is card or other.is_terminal():
                continue
            other.set_cancelled(i18n.t("The browser closed before Prism "
                                       "reached this step."))
        self._live = ""
        self._refresh_header()

    # ── header ──────────────────────────────────────────────────────────────
    def _tallies(self) -> dict:
        out = {"total": len(self._order), "done": 0, "problem": 0,
               "skipped": 0, "finished": 0}
        for key in self._order:
            state = self._cards[key].state()
            if state == "completed":
                out["done"] += 1
            elif state in _PROBLEM_STATES:
                out["problem"] += 1
            elif state in ("skipped", "cancelled"):
                out["skipped"] += 1
            if state in _TERMINAL_STATES or state == "needs_review":
                out["finished"] += 1
        return out

    def _overall(self) -> tuple[str, str]:
        """(state, detail) for the run as a whole."""
        tally = self._tallies()
        if not tally["total"]:
            return "idle", ""
        if self._cancelled and not tally["problem"]:
            return "cancelled", ""
        if self._live and self._cards.get(self._live):
            card = self._cards[self._live]
            return card.state(), i18n.t("{tool} · {step}").format(
                tool=ai_server.display_agent(card.agent) or "?", step=card._title)
        if self._finished or tally["finished"] >= tally["total"]:
            if tally["problem"]:
                return ("failed" if any(
                    self._cards[k].state() == "failed" for k in self._order)
                    else "needs_review"), ""
            return "completed", ""
        if self._running:
            return "running", ""
        return "queued", ""

    def _run_elapsed(self) -> float | None:
        if self._run_final is not None:
            return self._run_final
        if self._run_started is not None:
            return time.monotonic() - self._run_started
        return None

    def _refresh_header(self):
        tally = self._tallies()
        total = tally["total"]
        state, detail = self._overall()

        span = self._run_elapsed()
        if span is not None and span >= 1:
            detail = f"{detail} · {short_duration(span)}" if detail \
                else short_duration(span)
        self.header.status.set_state(state, detail)

        position = tally["finished"]
        if self._live in self._cards:
            position = self._order.index(self._live) + 1
        elif total:
            position = min(total, max(1, position))
        bits = []
        if total:
            bits.append(i18n.t("Step {n} of {total}").format(
                n=position, total=total))
        if tally["done"]:
            bits.append(i18n.t("1 finished") if tally["done"] == 1
                        else i18n.t("{n} finished").format(n=tally["done"]))
        if tally["problem"]:
            bits.append(i18n.t("1 needs a look") if tally["problem"] == 1
                        else i18n.t("{n} need a look").format(
                            n=tally["problem"]))
        if tally["skipped"]:
            bits.append(i18n.t("1 not run") if tally["skipped"] == 1
                        else i18n.t("{n} not run").format(n=tally["skipped"]))
        if span is not None and span >= 1:
            bits.append(i18n.t("{t} elapsed").format(t=short_duration(span)))
        self.header.counts.setText(" · ".join(bits))
        self.header.counts.setVisible(bool(bits))
        self.header.progress.setRange(0, total)
        self.header.progress.setValue(tally["finished"])
        self.header.progress.set_active(state == "running")
        QTimer.singleShot(0, self._share_slack)

    def _on_card_state(self):
        self._sync_problems()
        self._refresh_header()

    # ── claiming the viewport ───────────────────────────────────────────────
    def _share_slack(self):
        """Hand whatever height the timeline did not use to an open transcript.

        A run screen whose steps do not fill the window used to end in a band
        of grey. The honest way to close it is to show more of a real answer —
        the transcript was capped at 230px and scrolled inside its own box —
        rather than to grow the padding.
        """
        # Only cards whose transcript is actually being cut off. Growing the
        # cap on a card whose text already fits buys nothing and would leave
        # this loop with slack it can never spend.
        open_cards = [self._cards[k] for k in self._order
                      if self._cards[k].body_is_clipped()]
        if not open_cards:
            return
        inner = self.scroll.widget()
        if inner is None:
            return
        slack = self.scroll.viewport().height() - inner.sizeHint().height()
        if slack <= 8:
            return
        share = int(slack / len(open_cards))
        for card in open_cards:
            card.set_body_cap(card._body_cap + share)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._share_slack)

    # ── problems ────────────────────────────────────────────────────────────
    def _problem_cards(self) -> list:
        """Steps that need a human, in the order they appear on screen.

        Failed AND needs-review: a step that came back empty because the tool
        ran out of credit is exactly what "jump to the problem" is for, and it
        used to be invisible to this control.
        """
        return [self._cards[k] for k in self._order
                if self._cards[k].is_problem()]

    def _sync_problems(self):
        problems = self._problem_cards()
        self.problem_btn.setVisible(bool(problems))
        self.problem_btn.setText(
            i18n.t("Next problem") if len(problems) < 2
            else i18n.t("Next problem ({n})").format(n=len(problems)))
        if problems:
            self.problem_btn.setToolTip(i18n.t("Jump to: {steps}").format(
                steps=", ".join(c._title for c in problems)))
        if self._problem_at >= len(problems):
            self._problem_at = -1

    def _next_problem(self):
        """Cycle the steps that need a human, opening and focusing each."""
        problems = self._problem_cards()
        if not problems:
            return
        self._problem_at = (self._problem_at + 1) % len(problems)
        card = problems[self._problem_at]
        card.set_collapsed(False)
        self.scroll.ensureWidgetVisible(card, 0, 40)
        card.setFocus(Qt.ShortcutFocusReason)

    def _focus_neighbour(self, stage: str, step: int):
        if stage not in self._order:
            return
        index = self._order.index(stage) + step
        if 0 <= index < len(self._order):
            card = self._cards[self._order[index]]
            card.setFocus(Qt.TabFocusReason)
            self.scroll.ensureWidgetVisible(card, 0, 40)

    # ── run record ──────────────────────────────────────────────────────────
    def stage_durations(self) -> dict:
        """{stage: seconds} for every stage that finished.

        Nothing keeps these yet. They are the half of "1m 40s, usually 2m"
        that has to be recorded before it can be compared — a run record
        currently stores what each stage produced and not how long it took.
        """
        return {name: card.duration for name, card in self._cards.items()
                if card.duration is not None}

    def run_elapsed(self) -> float | None:
        """Total wall-clock seconds for the run, or None if it never started."""
        return self._run_elapsed()
