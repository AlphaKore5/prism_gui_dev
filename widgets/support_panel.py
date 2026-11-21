"""Help & support — local answers first, with a human route when needed.

────────────────────────────────────────────────────────────────────────────
Three tiers, in this order, and the order is the whole design
────────────────────────────────────────────────────────────────────────────
    1. the written answers   (`support_kb.py` — instant, free, always right)
    2. live diagnosis        (their own Groq key, only when they ask for it)
    3. our team              (an email that already contains everything we
                              would otherwise have to ask for)

The answer book is deliberately local: ordinary Help searches never send a
question to Groq, an AI tool, or an Alphakore server. A customer can then opt
into live diagnosis for an error or stalled task; it uses their saved Groq key,
the written guide and a scrubbed recent Prism log. Questions without a safe
answer still go to the team rather than being guessed at.

────────────────────────────────────────────────────────────────────────────
Why the gate is not a wall
────────────────────────────────────────────────────────────────────────────
A gate that traps someone is worse than no gate. Somebody whose problem is
genuinely not in the book must not be made to read six irrelevant answers to
earn the right to speak to a human. So it opens on the FIRST honest miss:
they read an answer and pressed "No, still stuck", or they typed a question
there was no answer for. One of either is enough.

────────────────────────────────────────────────────────────────────────────
Two columns, because a menu is not a conversation
────────────────────────────────────────────────────────────────────────────
The first version put everything in the thread: ten topic chips floating over
an empty screen, and a question box exiled to the bottom of it. Nothing about
the shape said "there are seventy-one answers in here", and the only way to
find out what a topic contained was to open it and lose your place.

So the screen is now split, and the split is the fix:

  · LEFT — the book. Search across every written answer, then the ten topics
    with the number of answers in each and the line that says what is on that
    shelf. It never scrolls away, so browsing costs nothing and going back
    costs nothing. This is where the topics live now; they are no longer
    posted into the thread.
  · RIGHT — the conversation. It opens on the questions the rest of the book
    points back at most, as pressable rows rather than behind a chip, and it
    keeps the three rules the first redesign earned:

      · **A menu is retired the moment the conversation moves past it.** The
        pick is already echoed as the customer's own bubble, so nothing is
        lost — and live buttons left in the scrollback are how a conversation
        forks. (The did-this-help row collapses itself for the same reason.)
      · **Questions stay full-width rows**, because they are whole sentences
        and a truncated question cannot be chosen.
      · **Prism's messages carry its mark.** Two voices in one column need
        telling apart faster than reading them.

This is a SCREEN, not a dialog — it keeps its conversation for the life of
the window, so following an answer's button to Settings and coming back
lands on the same thread. Start over is the one control that forgets.
"""
from __future__ import annotations

from collections import Counter

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import app_meta
import i18n
import support_kb as KB
import theme
from addons import registry
from widgets import controls as C
from widgets import icons
from widgets.markdown import render_markdown


# Live diagnosis is intentionally constrained. It receives the app's written
# guidance and a scrubbed recent log, never a blank canvas on which to invent
# controls or claim to have repaired a machine it cannot touch. It is entered
# only when the customer presses "Diagnose with AI" and uses their own Groq
# key; ordinary help remains local.
_SYSTEM = """\
You are Lumi, Prism's diagnostic assistant. You help a customer recover from a
failed or stalled Prism task, including render failures, malformed JSON,
browser/sign-in trouble and an agent that stopped halfway through.

RULES
1. Use only the Prism reference material, the scrubbed recent log, and the
   stated machine facts below. If they do not identify a safe next step, say
   so and direct the customer to Contact support. Never invent a button,
   setting, error cause or successful repair.
2. Explain the likely cause in plain English, then give at most six numbered
   steps. Start each step with an action word.
3. You cannot click, change, retry or repair anything yourself. Be clear
   about that; offer the customer a real action button where one is supplied.
4. Do not expose API keys, passwords, raw logs, stack traces, technical error
   codes, prompts, tokens, JSON, selectors, or browser-driver details.
5. If a reference answer has an Action key, append exactly this on a new last
   line: [ACTION: key]. Only use an action key actually shown in the material.
"""

# ── what the book actually contains ────────────────────────────────────────
# Read off support_kb rather than typed out here, so a question added there
# shows up here without anybody remembering to update a count.
_TOPIC_OF: dict[str, KB.Topic] = {
    q.qid: topic for topic in KB.TOPICS for q in topic.questions}
ANSWER_COUNT = len(KB.all_questions())
TOPIC_COUNT = len(KB.TOPICS)


def _most_pointed_at(limit: int) -> tuple[KB.Question, ...]:
    """The questions the rest of the book points back at, most first.

    The screen has to open on SOMETHING — ten topic names over an empty field
    told the customer nothing — and the one thing it must not do is invent a
    popularity figure it does not have. Nothing in Prism counts how often an
    answer is read.

    What the book does carry is `related`: every answer names the ones worth
    reading next, and those pointers were written one at a time by whoever
    wrote the answers. A question that eleven other answers hand you to is,
    by the book's own reckoning, the one people keep needing. Ties break on
    the order the file lists them in, so this is stable between runs.
    """
    pull: Counter[str] = Counter()
    for question in KB.all_questions():
        for other in question.related:
            pull[other] += 1
    order = {q.qid: i for i, q in enumerate(KB.all_questions())}
    ranked = sorted(pull, key=lambda qid: (-pull[qid], order.get(qid, 9999)))
    picked = [KB.question(qid) for qid in ranked[:limit]]
    return tuple(q for q in picked if q is not None)


def _matching(query: str) -> list[KB.Question]:
    """Every written answer this typed text could be about, best first.

    Deliberately NOT `KB.search`. That one is a decision — it returns nothing
    rather than a weak guess, because an empty result is what opens the route
    to a person. This is a browse filter on a list the customer can already
    see, so the honest behaviour is the opposite: narrow as they type, match
    on any part of any word, and let them judge. Both are wired up: this one
    filters the column, and pressing Ask still goes through `KB.search`.
    """
    words = [w for w in query.lower().split() if w]
    if not words:
        return []
    named, mentioned = [], []
    for question in KB.all_questions():
        topic = _TOPIC_OF.get(question.qid)
        heading = " ".join((question.text, " ".join(question.keywords),
                            topic.label if topic else "")).lower()
        body = " ".join((question.answer.what, " ".join(question.answer.steps),
                         question.answer.note)).lower()
        if all(word in heading for word in words):
            named.append(question)
        elif all(word in heading + " " + body for word in words):
            mentioned.append(question)
    return named + mentioned


def _chip(label: str, icon_name: str = "", tip: str = "") -> QPushButton:
    """One compact pressable — a small conversational move inside the thread.

    The capsule object name rather than a hand-rolled stylesheet: `#chipBtn`
    is the secondary variant in capsule form and already carries hover,
    pressed, focus and disabled states from style.qss.
    """
    btn = C.button(label, "secondary",
                   small=True)
    btn.setObjectName("chipBtn")
    if icon_name:
        icons.button_icon(btn, icon_name, 14, theme.ACCENT)
    if tip:
        btn.setToolTip(tip)
    return btn


# ── little shared pieces ───────────────────────────────────────────────────
def _wrap(widget: QWidget, mine: bool, glyph: str = "",
          full: bool = False) -> QWidget:
    """Put one message on its side of the transcript.

    Stretch rather than a fixed maximum width, so a bubble is ~75% of
    whatever the column happens to be. `glyph` puts Prism's mark beside its
    own messages — two voices in one column need telling apart at a glance.

    `full` is for the menus rather than the messages. A said thing is easier
    to read short, which is what the 75% is for; a list of questions to
    choose between is not a said thing, and holding it to 75% left a dead
    strip down the right of the screen and wrapped questions that would have
    fitted on one line.

    Minimum vertical policy, or a message can be squeezed shorter than its
    own text: these rows stack inside a scroll area that is routinely
    shorter than its content, so "short of room" is the normal case.
    """
    row = QWidget()
    row.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(theme.SPACE_2)
    if mine:
        box.addStretch(1)
        box.addWidget(widget, stretch=3)
    else:
        if glyph:
            mark = QLabel()
            import os
            import paths
            lumi_av = paths.resource("assets", "lumi", "lumi_avatar.png")
            if os.path.exists(lumi_av):
                from PySide6.QtGui import QPixmap
                pm = QPixmap(lumi_av).scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                mark.setPixmap(pm)
                mark.setFixedSize(28, 28)
            else:
                mark.setPixmap(icons.pixmap(glyph, 18, theme.ACCENT))
                mark.setFixedWidth(20)
            mark.setAlignment(Qt.AlignTop)
            mark.setStyleSheet("background: transparent; padding-top: 4px;")
            box.addWidget(mark, alignment=Qt.AlignTop)
        box.addWidget(widget, stretch=5)
        if not full:
            box.addStretch(1)
    return row


def _bubble(text: str, mine: bool = False, rich: bool = False) -> QWidget:
    frame = QFrame()
    frame.setObjectName("supportMine" if mine else "supportBot")
    if mine:
        frame.setStyleSheet(
            "QFrame#supportMine {"
            "  background: #0f172a;"
            "  border: 1px solid #1e293b;"
            "  border-radius: 18px;"
            "  border-bottom-right-radius: 4px;"
            "}"
        )
    else:
        frame.setStyleSheet(
            "QFrame#supportBot {"
            "  background: #ffffff;"
            "  border: 1px solid rgba(45, 212, 191, 0.28);"
            "  border-radius: 18px;"
            "  border-bottom-left-radius: 4px;"
            "}"
        )
    box = QVBoxLayout(frame)
    box.setContentsMargins(14, 10, 14, 10)
    body = C.label("", level="BODY", wrap=True,
                   colour="#ffffff" if mine else "#0f172a")
    body.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    if rich:
        body.setTextFormat(Qt.RichText)
        body.setText(render_markdown(text))
    else:
        body.setText(text)
    body.setTextInteractionFlags(Qt.TextSelectableByMouse)
    box.addWidget(body)
    return _wrap(frame, mine, glyph="" if mine else "prism")


class _Choice(QFrame):
    """One pressable row: a question in the thread, or a line in the browse
    column. Full width and left-aligned, because these are whole sentences —
    a row of chips would truncate them.

    A QFrame carrying real QLabels rather than a QPushButton with a newline
    in its text, and that is not a style preference. A push button's minimum
    height ignores embedded newlines entirely, so Qt is free to squash it to
    one line once the conversation grows taller than the viewport. Labels
    report a minimum height that includes their second line, so there is
    nothing for the layout to take.

    `flat` is the browse-column skin — no box of its own, because ten boxed
    rows inside one card reads as a list of cards rather than as a list. It
    keeps the hover tint and gains a current state, since that column has to
    show which shelf the thread is currently on.
    """

    clicked = Signal()

    # Everything between the frame's outer edge and the text column. BORDER is
    # the hairline the stylesheet draws: it is outside the contents rect, so
    # leaving it out overstated the text width by 2px — enough, at exactly the
    # wrong window width, to cost a blurb its last word.
    PAD, PAD_Y, GAP, ICON, BORDER, SLACK = 13, 10, 10, 16, 1, 2

    def __init__(self, label: str, icon_name: str = "chevron-right",
                 blurb: str = "", muted: bool = False, trail: str = "",
                 flat: bool = False, level: str = "BODY", parent=None):
        super().__init__(parent)
        self._flat = flat
        if flat:
            # Tighter, because these are index entries in a narrow column and
            # ten of them have to be readable at once — the whole point of the
            # column is that you can see the shape of the book without
            # scrolling it.
            self.PAD, self.PAD_Y = 9, 6
        self._current = False
        self.setObjectName("supportNavRow" if flat else "supportChoice")
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        # Reachable, and visibly so. A row you can only get to with a mouse is
        # not a control, and the focus ring is what the keyboard user reads as
        # "this is the one Enter will open".
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(label)
        # Height-for-width, declared. A word-wrapped QLabel knows how tall it
        # needs to be only once it knows how wide it is, and a layout will not
        # ask unless the size policy says to.
        policy = QSizePolicy(QSizePolicy.MinimumExpanding, QSizePolicy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self._skin()

        row = QHBoxLayout(self)
        row.setContentsMargins(self.PAD, self.PAD_Y, self.PAD, self.PAD_Y)
        row.setSpacing(self.GAP)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap(
            icon_name, self.ICON,
            theme.NEUTRAL[500] if muted else theme.ACCENT))
        glyph.setAlignment(Qt.AlignTop)
        glyph.setFixedWidth(self.ICON)
        glyph.setStyleSheet("background: transparent;")
        row.addWidget(glyph)

        self._stack = stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        self._lbl = C.label(
            label, level=level, wrap=True,
            colour=theme.NEUTRAL[500] if muted else theme.TEXT)
        stack.addWidget(self._lbl)
        if blurb:
            stack.addWidget(C.label(blurb, role="meta", wrap=True))
        row.addLayout(stack, stretch=1)

        # The count on a topic row. Real — it is how many answers are on that
        # shelf — and it is the thing that makes the column browsable rather
        # than a list of names.
        self._trail = 0
        if trail:
            tag = C.label(trail, role="meta")
            tag.setAlignment(Qt.AlignTop | Qt.AlignRight)
            self._trail = tag.sizeHint().width() + self.GAP
            row.addWidget(tag, alignment=Qt.AlignTop)

    # ── skin ──────────────────────────────────────────────────────────────
    def _skin(self):
        name = self.objectName()
        if self._flat:
            fill = theme.ACCENT_RAMP[100] if self._current else "transparent"
            edge = theme.ACCENT_RAMP[300] if self._current else "transparent"
            hover = theme.ACCENT_RAMP[100] if self._current else theme.WELL
            self.setStyleSheet(
                f"QFrame#{name} {{ background: {fill};"
                f"border: 1px solid {edge};"
                f"border-radius: {theme.R_CONTROL}px; }}"
                f"QFrame#{name}:hover {{ background: {hover};"
                f"border-color: {theme.ACCENT_RAMP[300]}; }}"
                f"QFrame#{name}:focus {{ border-color: {theme.ACCENT}; }}")
            return
        self.setStyleSheet(
            f"QFrame#{name} {{ background: rgba(255, 255, 255, 0.88);"
            f"border: 1px solid rgba(0, 0, 0, 0.08);"
            f"border-radius: {theme.R_CONTROL}px; }}"
            f"QFrame#{name}:hover {{ border-color: {theme.ACCENT};"
            f"background: rgba(255, 255, 255, 0.98); }}"
            f"QFrame#{name}:focus {{ border-color: {theme.ACCENT};"
            f"background: rgba(255, 255, 255, 0.98); }}")

    def set_current(self, current: bool):
        if current == self._current:
            return
        self._current = current
        self._skin()

    # ── geometry ──────────────────────────────────────────────────────────
    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        inner = max(1, width - (2 * self.PAD) - (2 * self.BORDER)
                    - self.ICON - self.GAP - self._trail)
        stack_h = self._stack.sizeHint().height()
        if hasattr(self, "_lbl") and self._lbl:
            lh = self._lbl.heightForWidth(inner)
            if lh > 0:
                stack_h = lh
        return max(44, stack_h + self.SLACK + (2 * self.PAD_Y) + (2 * self.BORDER))

    def resizeEvent(self, event):
        """Pin the height to what this width actually needs. A size POLICY
        was not enough: inside a scroll area Qt handed these rows 43px
        against a minimumSizeHint of 68 and overlapped the two lines. A hard
        setMinimumHeight is the one constraint a layout will not negotiate
        away, and the correct value is only knowable once the width is."""
        super().resizeEvent(event)
        self.setMinimumHeight(self.heightForWidth(self.width()))

    # ── input ─────────────────────────────────────────────────────────────
    def mouseReleaseEvent(self, event):
        # Only a press and release both inside it counts, so dragging away to
        # change your mind works the way it does on every other control.
        if (event.button() == Qt.LeftButton
                and self.rect().contains(event.position().toPoint())):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)


class _Steps(QFrame):
    """The numbered things to try."""

    def __init__(self, steps: tuple[str, ...], parent=None):
        super().__init__(parent)
        self.setObjectName("supportSteps")
        self.setStyleSheet(
            "QFrame#supportSteps {"
            "  background: #f0fdfa;"
            "  border: 1px solid #ccfbf1;"
            "  border-radius: 12px;"
            "}")
        box = QVBoxLayout(self)
        box.setContentsMargins(12, 10, 12, 10)
        box.setSpacing(8)
        box.addWidget(C.kicker(i18n.t("Try this")))
        for index, step in enumerate(steps, 1):
            row = QHBoxLayout()
            row.setSpacing(8)
            number = QLabel(str(index))
            number.setFixedSize(18, 18)
            number.setAlignment(Qt.AlignCenter)
            number.setStyleSheet(
                "background: #ccfbf1; color: #0f766e; font-size: 11px; font-weight: 700; border-radius: 9px;"
            )
            row.addWidget(number, alignment=Qt.AlignTop)
            body = C.label("", level="BODY", wrap=True, colour="#134e4a")
            body.setTextFormat(Qt.RichText)
            body.setText(render_markdown(step))
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(body, stretch=1)
            box.addLayout(row)


class _AnswerCard(QFrame):
    """One answer, presented cleanly with next action and verdict."""

    def __init__(self, question: KB.Question, locked: bool, on_verdict,
                 on_action, parent=None):
        super().__init__(parent)
        self.setObjectName("supportBot")
        self.setStyleSheet(
            "QFrame#supportBot {"
            "  background: #ffffff;"
            "  border: 1px solid rgba(45, 212, 191, 0.35);"
            "  border-radius: 18px;"
            "  border-bottom-left-radius: 4px;"
            "}")
        answer = question.answer
        box = QVBoxLayout(self)
        box.setContentsMargins(14, 12, 14, 12)
        box.setSpacing(10)

        topic = _TOPIC_OF.get(question.qid)
        if topic:
            box.addWidget(C.kicker(topic.label))

        if locked:
            tag = C.label(i18n.t("This part isn't in your licence — here's "
                                 "what it does anyway."), role="tagWarn",
                          wrap=True)
            box.addWidget(tag, alignment=Qt.AlignLeft)

        what = C.label("", level="BODY", wrap=True, colour="#0f172a")
        what.setTextFormat(Qt.RichText)
        what.setText(render_markdown(answer.what))
        what.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(what)

        if answer.steps:
            box.addWidget(_Steps(answer.steps))

        if answer.note:
            box.addWidget(C.label(answer.note, role="meta", wrap=True))

        if answer.action:
            action_btn = QPushButton(f"→  {i18n.t(answer.action_label or 'Take me there')}")
            action_btn.setCursor(Qt.PointingHandCursor)
            action_btn.setStyleSheet(
                "QPushButton {"
                "  background: #0f766e;"
                "  color: #ffffff;"
                "  font-weight: 600;"
                "  font-size: 12px;"
                "  border: none;"
                "  border-radius: 14px;"
                "  padding: 6px 14px;"
                "}"
                "QPushButton:hover {"
                "  background: #0d9488;"
                "}"
            )
            action_btn.clicked.connect(
                lambda _=False, key=answer.action: on_action(key))
            box.addWidget(action_btn, alignment=Qt.AlignLeft)

        box.addWidget(C.hairline())

        self._verdict = QWidget()
        row = QHBoxLayout(self._verdict)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        row.addWidget(C.label(i18n.t("Did that sort it?"), level="SUPPORT"))
        row.addStretch(1)
        for label, solved in ((i18n.t("Yes, thanks"), True),
                              (i18n.t("No, still stuck"), False)):
            btn = C.button(label, "secondary", small=True)
            btn.clicked.connect(
                lambda _=False, s=solved: self._answer(s, question.qid,
                                                       on_verdict))
            row.addWidget(btn)
        box.addWidget(self._verdict)

    def _answer(self, solved: bool, qid: str, on_verdict):
        """Replace the buttons with what was chosen — live buttons left in
        the scrollback are how the conversation forks."""
        layout = self._verdict.layout()
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        layout.addWidget(C.label(
            i18n.t("You said: that sorted it") if solved
            else i18n.t("You said: still stuck"), role="meta"))
        layout.addStretch(1)
        on_verdict(qid, solved)


# ════════════════════════════════════════════════════════════════════════════
class SupportPanel(QWidget):
    """Lumi — Prism's local help bot, with an opt-in diagnosis route.

    Ordinary questions are answered immediately without a planning key or
    network connection. For an error or stalled task, the customer can opt
    into Groq-backed diagnosis using a scrubbed local log. If there is no safe
    answer, they reach a person instead of receiving a plausible-sounding one.
    """

    command_requested = Signal(str)

    STARTERS = 3

    def __init__(self, cfg: dict | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._stage = "triage"
        self._seen: list[str] = []
        self._unsolved: list[str] = []
        self._log: list[tuple[str, str]] = []
        self._live: list[QWidget] = []
        self._worker = None
        self._thinking: QWidget | None = None
        self._thinking_timer: QTimer | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._root = root

        self._restart = C.button(i18n.t("Start over"), "secondary", small=True,
                                 on_click=self._start_over)
        self._head = C.PageHeader(
            i18n.t("Lumi"),
            i18n.t("Prism help, answered locally. No question is sent anywhere."),
            [self._restart])
        root.addWidget(self._head)

        body = QVBoxLayout()
        body.setContentsMargins(theme.PAGE_PAD, theme.PAGE_PAD,
                                theme.PAGE_PAD, theme.PAGE_PAD)
        body.setSpacing(theme.CARD_GAP)
        body.addWidget(self._talk_column(), stretch=1)
        self._body = body
        root.addLayout(body, stretch=1)

        self._greet()

    def set_compact(self, compact: bool = True):
        """Use this panel inside the floating Lumi shell on Home.

        The shell supplies Lumi's title and close control; hiding the page
        header here gives the answer transcript its full popover height.
        """
        self._head.setVisible(not compact)
        if hasattr(self, "_foot"):
            self._foot.setVisible(not compact)
        if hasattr(self, "_talk_card"):
            self._talk_card.setStyleSheet("background: transparent; border: none;" if compact else "")
        if hasattr(self, "_scroll"):
            self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        margin = 0 if compact else theme.PAGE_PAD
        self._body.setContentsMargins(margin, margin, margin, margin)

    # ── the book: search, then the shelves ────────────────────────────────
    def _browse_column(self) -> QWidget:
        """Search over every written answer, then the ten topics with the
        number of answers on each. Fixed to the left of the conversation and
        never retired, so nothing has to be re-opened to be looked at twice.
        """
        holder = QWidget()
        holder.setFixedWidth(self.NAV_W)
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)

        self._search = C.SearchField(i18n.t("Search the written answers"))
        self._search.changed.connect(self._fill_nav)
        col.addWidget(self._search)

        card = C.Card()
        inner = card.body((theme.SPACE_3, theme.SPACE_3,
                           theme.SPACE_3, theme.SPACE_3), theme.SPACE_2)
        head = QHBoxLayout()
        head.setContentsMargins(theme.SPACE_1, 0, theme.SPACE_1, 0)
        head.setSpacing(theme.SPACE_2)
        self._nav_kicker = C.kicker(i18n.t("Browse by topic"))
        head.addWidget(self._nav_kicker, stretch=1)
        self._nav_count = C.meta(
            i18n.t("{n} answers").format(n=ANSWER_COUNT))
        head.addWidget(self._nav_count)
        inner.addLayout(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 0px; height: 0px; background: transparent; border: none; }"
            "QScrollBar:horizontal { width: 0px; height: 0px; background: transparent; border: none; }"
            "QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: transparent; border: none; }"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; background: transparent; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
        )
        listing = QWidget()
        listing.setStyleSheet("background: transparent;")
        listing.setMinimumSize(1, 1)
        self._nav_box = QVBoxLayout(listing)
        self._nav_box.setContentsMargins(0, 0, theme.SPACE_1, 0)
        self._nav_box.setSpacing(2)
        scroll.setWidget(listing)
        inner.addWidget(scroll, stretch=1)
        col.addWidget(card, stretch=1)
        return holder

    def _fill_nav(self, query: str = ""):
        """Redraw the column: the ten topics, or what a search matched."""
        while self._nav_box.count():
            item = self._nav_box.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()   # before setParent(None): avoids ghost-window flash
                widget.setParent(None)
                item.widget().deleteLater()
        self._nav_rows = {}
        query = (query or "").strip()

        if not query:
            self._nav_kicker.setText(i18n.t("Browse by topic").upper())
            topics = [topic for topic in KB.TOPICS
                      if topic.key in self.QUICK_TOPICS]
            self._nav_count.setText(
                i18n.t("{n} topics").format(n=len(topics)))
            for topic in topics:
                row = _Choice(topic.label, topic.icon, topic.blurb,
                              trail=str(len(topic.questions)), flat=True,
                              level="CARD_TITLE")
                row.clicked.connect(
                    lambda _=False, k=topic.key: self._pick_topic(k))
                self._nav_box.addWidget(row)
                self._nav_rows[topic.key] = row
            self._nav_box.addStretch(1)
            return

        hits = _matching(query)
        self._nav_kicker.setText(i18n.t("Matches").upper())
        self._nav_count.setText(i18n.t("{n} of {total}").format(
            n=len(hits), total=ANSWER_COUNT))
        if not hits:
            # Genuinely empty, so it centres in the height it has rather than
            # leaving a hole under a one-line apology.
            blank = C.EmptyState(
                "search", i18n.t("Nothing here matches that"),
                i18n.t("Try fewer words. Or ask it in your own words on the "
                       "right — if we have no written answer, the assistant "
                       "and our team open up straight away."))
            self._nav_box.addWidget(blank, stretch=1)
            return
        for question in hits:
            topic = _TOPIC_OF.get(question.qid)
            row = _Choice(question.text, topic.icon if topic else "help",
                          blurb=topic.label if topic else "", flat=True)
            row.clicked.connect(
                lambda _=False, qid=question.qid: self._show_answer(qid))
            self._nav_box.addWidget(row)
        self._nav_box.addStretch(1)

    def _pick_topic(self, key: str):
        for topic_key, row in self._nav_rows.items():
            row.set_current(topic_key == key)
        self._show_topic(key)

    # ── the conversation ──────────────────────────────────────────────────
    def _talk_column(self) -> QWidget:
        card = C.Card(radius=18)
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar:vertical { width: 0px; height: 0px; background: transparent; border: none; }"
            "QScrollBar:horizontal { width: 0px; height: 0px; background: transparent; border: none; }"
            "QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: transparent; border: none; }"
            "QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; border: none; background: transparent; }"
            "QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }"
        )
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        # A transcript is word-wrapped labels all the way down, and a wrapped
        # label's MINIMUM size is tall-and-narrow — its height when wrapped
        # at its widest single word. QVBoxLayout sums those minimums with no
        # width in hand, so the scroll area was handed a floor hundreds of
        # pixels past the real content. An explicit tiny minimum takes that
        # floor away; the area then sizes the column by height-for-width, the
        # same calculation that places the bubbles.
        inner.setMinimumSize(1, 1)
        self._thread_box = QVBoxLayout(inner)
        self._thread_box.setContentsMargins(0, 0, theme.SPACE_2, theme.SPACE_3)
        self._thread_box.setSpacing(theme.SPACE_3)
        self._thread_box.addStretch(1)
        scroll.setWidget(inner)
        self._scroll = scroll
        # A new message's layout settles over several passes — a word-wrapped
        # label reports its true height only once it knows its width — and
        # each pass grows the scroll range a little more. A single deferred
        # jump lands one pass short, with the newest message just below the
        # fold. So while a message is settling (_follow, armed by _say) the
        # bar rides the range's growth; afterwards it is the reader's.
        self._follow = False
        scroll.verticalScrollBar().rangeChanged.connect(
            lambda _lo, hi: self._follow
            and self._scroll.verticalScrollBar().setValue(hi))
        col.addWidget(scroll, stretch=1)

        col.addWidget(self._composer())
        col.addWidget(self._escalation())
        self._talk_card = card
        return card

    # ── chrome ────────────────────────────────────────────────────────────
    def _composer(self) -> QWidget:
        container = QFrame()
        container.setObjectName("supportComposer")
        container.setStyleSheet(
            "QFrame#supportComposer {"
            "  border-top: 1px solid rgba(0, 0, 0, 0.06);"
            "  padding-top: 4px;"
            "}")
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 4, 0, 4)
        c_layout.setSpacing(0)

        pill = QFrame()
        pill.setObjectName("supportComposerPill")
        pill.setFixedHeight(44)
        pill.setStyleSheet(
            "QFrame#supportComposerPill {"
            "  background: #ffffff;"
            "  border: 1.5px solid #2dd4bf;"
            "  border-radius: 22px;"
            "}"
            "QFrame#supportComposerPill QLabel {"
            "  background: transparent;"
            "  border: none;"
            "}"
        )
        row = QHBoxLayout(pill)
        row.setContentsMargins(14, 0, 5, 0)
        row.setSpacing(8)

        search_icon = QLabel()
        search_icon.setPixmap(icons.pixmap("search", 15, "#0d9488"))
        search_icon.setStyleSheet("background: transparent; border: none;")
        row.addWidget(search_icon)

        self._entry = QLineEdit()
        self._entry.setPlaceholderText(i18n.t("Ask Lumi anything about Prism..."))
        self._entry.setStyleSheet(
            "QLineEdit { border: none; background: transparent; font-size: 13px; color: #0f172a; padding: 0; }"
        )
        self._entry.setAccessibleName(i18n.t("Your question"))
        self._entry.returnPressed.connect(self._on_typed)
        row.addWidget(self._entry, stretch=1)

        self._send = QPushButton()
        self._send.setFixedSize(34, 34)
        self._send.setCursor(Qt.PointingHandCursor)
        icons.button_icon(self._send, "arrow-right", 16, "#0f766e")
        self._send.setStyleSheet(
            "QPushButton {"
            "  background: #ccfbf1;"
            "  border: none;"
            "  border-radius: 17px;"
            "}"
            "QPushButton:hover {"
            "  background: #5eead4;"
            "}"
            "QPushButton:disabled {"
            "  background: #f1f5f9;"
            "}"
        )
        self._send.clicked.connect(self._on_typed)
        row.addWidget(self._send)

        c_layout.addWidget(pill)
        return container

    def _escalation(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("supportFoot")
        bar.setStyleSheet(
            f"QFrame#supportFoot {{"
            f"border-top: 1px solid {theme.HAIRLINE}; }}")
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, theme.SPACE_3 - 1, 0, 0)
        row.setSpacing(theme.SPACE_2 + 1)
        self._foot_note = C.label(
            i18n.t("Need to speak to someone?"), role="meta", wrap=True)
        row.addWidget(self._foot_note, stretch=1)

        self._ai_btn = C.button(i18n.t("Diagnose with AI"), "secondary",
                                small=True, on_click=self._start_ai)
        icons.button_icon(self._ai_btn, "help", 14, theme.ACCENT)
        row.addWidget(self._ai_btn)

        self._meeting_btn = C.button(i18n.t("Book a meeting"), "secondary",
                                     small=True, on_click=self._book_meeting)
        icons.button_icon(self._meeting_btn, "clock", 14, theme.ACCENT)
        row.addWidget(self._meeting_btn)

        self._contact_btn = C.button(i18n.t("Contact support"), "secondary",
                                     small=True, on_click=self._open_contact)
        icons.button_icon(self._contact_btn, "mail", 14, theme.TEXT)
        row.addWidget(self._contact_btn)

        self._refresh_escalation()
        self._foot = bar
        return bar

    def _refresh_escalation(self):
        """Keep routing buttons in sync with conversation stage."""
        if hasattr(self, "_ai_btn"):
            self._ai_btn.setEnabled(self._stage != "ai")
        if hasattr(self, "_contact_btn"):
            self._contact_btn.setEnabled(True)

    def _sync_thread_height(self):
        if not hasattr(self, "_scroll") or not hasattr(self, "_thread_box"):
            return
        inner = self._scroll.widget()
        if not inner:
            return
        w = self._scroll.viewport().width()
        if w <= 0:
            w = self._scroll.width() - 20
        if w > 0 and self._thread_box.hasHeightForWidth():
            h = self._thread_box.heightForWidth(w)
            if h > 0:
                inner.setMinimumHeight(h)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._sync_thread_height()

    # ── the transcript ────────────────────────────────────────────────────
    def _say(self, widget: QWidget, scroll: bool = True):
        self._thread_box.insertWidget(self._thread_box.count() - 1, widget)
        self._sync_thread_height()
        if not scroll:
            return
        self._follow = True
        bar = self._scroll.verticalScrollBar()
        QTimer.singleShot(0, lambda: bar.setValue(bar.maximum()))
        QTimer.singleShot(50, self._sync_thread_height)
        QTimer.singleShot(100, lambda: bar.setValue(bar.maximum()))
        QTimer.singleShot(250, self._stop_following)

    def _stop_following(self):
        self._follow = False

    def _scroll_to_widget(self, widget: QWidget):
        """Scroll so that the beginning of the widget is comfortably in view."""
        def do_scroll():
            if not widget or not hasattr(self, "_scroll"):
                return
            self._scroll.ensureWidgetVisible(widget, 0, 0)
        QTimer.singleShot(20, do_scroll)
        QTimer.singleShot(80, do_scroll)
        QTimer.singleShot(200, do_scroll)

    def _bot(self, text: str, rich: bool = True):
        self._log.append(("prism", text))
        self._say(_bubble(text, mine=False, rich=rich))

    def _me(self, text: str):
        self._log.append(("you", text))
        self._say(_bubble(text, mine=True))

    def _retire_menus(self):
        """Take every still-pressable menu out of the thread.

        Called the moment the conversation moves past them. The customer's
        pick is already echoed as their own bubble, so nothing readable is
        lost — what goes is the wall of buttons that made the first version
        read as a form that kept growing, and the stale-click fork risk that
        comes with it. The browse column is not a menu in this sense: it is
        an index, it never posted anything into the thread, and it stays.
        """
        for group in self._live:
            self._thread_box.removeWidget(group)
            group.hide()   # before setParent(None): avoids ghost-window flash
            group.setParent(None)
            group.deleteLater()
        self._live = []
        self._sync_thread_height()

    def _options(self, buttons: list, scroll: bool = True, header: str = "",
                 note: str = ""):
        holder = QWidget()
        holder.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        box = QVBoxLayout(holder)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2 - 2)
        if header:
            box.addWidget(C.kicker(header))
            if note:
                box.addWidget(C.label(note, role="meta", wrap=True))
            box.addSpacing(2)
        for btn in buttons:
            # A chip keeps its own width; a question row is a sentence and
            # takes the column.
            if isinstance(btn, QPushButton):
                box.addWidget(btn, alignment=Qt.AlignLeft)
            else:
                box.addWidget(btn)
        row = _wrap(holder, mine=False, full=True)
        self._live.append(row)
        self._say(row, scroll=scroll)
        return holder

    # ── tier 1: the written answers ───────────────────────────────────────
    def _greet(self):
        self._say(_bubble(i18n.t(
            "Hi, I’m **Lumi**! ✨ Ask me any question about Prism.\n\n"
            "I can guide you through editing reels, extracting BOQs, finding leads, "
            "setting up WhatsApp, inspecting CAD/Gerber, or diagnosing any issue.\n\n"
            "Pick a topic below or type your question:"), mine=False, rich=True),
            scroll=False)
        self._show_starters(scroll=False)
        self._entry.setFocus()

    def _show_starters(self, scroll: bool = True):
        """Three most-common questions as pressable chips."""
        rows = []
        for question in _most_pointed_at(self.STARTERS):
            topic = _TOPIC_OF.get(question.qid)
            row = _Choice(question.text, "chevron-right",
                          blurb=topic.label if topic else "")
            row.clicked.connect(
                lambda _=False, qid=question.qid: self._show_answer(qid))
            rows.append(row)
        browse = _Choice(i18n.t("Browse all help topics"), "grid",
                         i18n.t("Licence, files, add-ons, privacy and errors"))
        browse.clicked.connect(self._show_all_topics)
        rows.append(browse)
        self._options(rows, scroll=scroll, header=i18n.t("Quick questions"))

    def _reset_to_triage(self):
        """Restore normal knowledge base triage mode and search placeholder."""
        self._stage = "triage"
        if hasattr(self, "_entry"):
            self._entry.setPlaceholderText(i18n.t("Ask Lumi anything about Prism..."))
        if hasattr(self, "_head") and hasattr(self._head, "set_subtitle"):
            self._head.set_subtitle(i18n.t(
                "Prism help, answered locally. No question is sent anywhere."))
        self._refresh_escalation()

    def _show_topic(self, key: str):
        topic = KB.topic(key)
        if not topic:
            return
        self._reset_to_triage()
        self._retire_menus()
        self._me(topic.label)
        self._bot(i18n.t("Which of these is it?"))
        buttons = []
        for question in topic.questions:
            btn = _Choice(question.text, "chevron-right")
            btn.clicked.connect(
                lambda _=False, q=question.qid: self._show_answer(q))
            buttons.append(btn)
        back = _chip(i18n.t("Back to the common questions"), "chevron-left")
        back.clicked.connect(lambda: self._back_to_start())
        self._options(buttons)
        self._options([back])

    def _show_all_topics(self):
        """Offer every shelf in the local book, without starting a chat."""
        self._reset_to_triage()
        self._retire_menus()
        self._me(i18n.t("Browse all help topics"))
        self._bot(i18n.t("Choose the area closest to your question:"))
        buttons = []
        for topic in KB.TOPICS:
            btn = _Choice(topic.label, topic.icon, topic.blurb,
                          trail=str(len(topic.questions)))
            btn.clicked.connect(
                lambda _=False, key=topic.key: self._show_topic(key))
            buttons.append(btn)
        self._options(buttons)

    def _back_to_start(self):
        self._reset_to_triage()
        self._retire_menus()
        self._show_starters()

    def _show_answer(self, qid: str, echo: bool = True):
        question = KB.question(qid)
        if not question:
            return
        self._reset_to_triage()
        self._retire_menus()
        if echo:
            self._me(question.text)
        if qid not in self._seen:
            self._seen.append(qid)
        self._log.append(("prism", KB.as_text(question)))

        locked = False
        if question.answer.feature:
            try:
                import licensing
                locked = not licensing.has(question.answer.feature)
            except Exception:               # noqa: BLE001
                locked = False              # never let a licence read hide help
        card = _AnswerCard(question, locked, self._verdict,
                           self._take_action)
        wrap = _wrap(card, mine=False, glyph="prism")
        self._say(wrap)
        self._scroll_to_widget(wrap)

    def _take_action(self, key: str):
        """An answer's button. Emits the sidebar command; the screen keeps
        its thread, so they can come back to the rest of the answer."""
        self.command_requested.emit(key)

    def _verdict(self, qid: str, solved: bool):
        if solved:
            self._bot(i18n.t("Good — glad that was all it was."))
            again = _chip(i18n.t("Ask about something else"), "help")
            again.clicked.connect(lambda: self._back_to_start())
            self._options([again])
            return

        self._unsolved.append(qid)
        nearby = [q for q in KB.related_to(qid) if q.qid not in self._seen]
        if nearby:
            self._bot(i18n.t("Sorry about that. Click any question below that matches what you need:"), rich=True)
            buttons = []
            for question in nearby:
                btn = _Choice(question.text, "chevron-right")
                btn.clicked.connect(
                    lambda _=False, q=question.qid: self._show_answer(q))
                buttons.append(btn)
            self._options(buttons)
        else:
            self._bot(i18n.t("Sorry about that. We didn't have a direct answer for this yet."))

        diag = _chip(i18n.t("Diagnose with AI"), "help")
        diag.clicked.connect(self._start_ai)
        supp = _chip(i18n.t("Contact Support"), "mail")
        supp.clicked.connect(self._open_contact)
        self._options([diag, supp], header=i18n.t("Or get more help"))

    @staticmethod
    def _is_greeting(text: str) -> bool:
        clean = (text or "").strip().lower()
        if not clean:
            return False
        chitchat = (
            "who are you", "who are you?", "what can you do", "what can you do?",
            "help", "help me", "wassup", "what's up", "whats up", "how are you",
            "how are you?", "how are you doing", "how's it going", "hows it going",
            "good morning", "good evening", "good afternoon"
        )
        if clean in chitchat:
            return True
        import re
        words = re.findall(r"\b\w+\b", clean)
        greetings = {
            "hello", "hi", "hey", "hiya", "howdy", "sup", "wassup", "whatsup",
            "yo", "greetings", "hola", "namaste", "morning", "afternoon", "evening"
        }
        if words and words[0] in greetings and len(words) <= 4:
            return True
        return False

    @staticmethod
    def _is_overview_request(text: str) -> bool:
        clean = (text or "").strip().lower()
        if clean in ("how to use", "how do i use", "how to start", "how do i start", "get started"):
            return True
        triggers = (
            "how do i use prism", "how to use prism", "how does prism work",
            "what is prism", "what does prism do", "what can prism do",
            "getting started", "start using prism", "tell me about prism",
            "prism overview", "what can you do", "guided tour", "take a tour",
            "explain prism", "walk me through prism"
        )
        return any(clean == t or clean.startswith(t + " ") or clean.startswith(t + "?") for t in triggers)

    # ── typing a question ─────────────────────────────────────────────────
    def _on_typed(self):
        text = self._entry.text().strip()
        if not text:
            return
        self._entry.clear()
        self._retire_menus()
        self._me(text)

        if self._is_greeting(text):
            self._stage = "triage"
            self._entry.setPlaceholderText(i18n.t("Ask Lumi anything about Prism..."))
            self._refresh_escalation()
            self._bot(i18n.t(
                "Hi there! 😊 I'm **Lumi**, your Prism copilot.\n\n"
                "I can guide you through editing reels, extracting BOQs, finding leads, "
                "configuring WhatsApp, inspecting CAD/Gerber designs, or diagnosing issues. "
                "What would you like help with?"
            ), rich=True)
            c1 = _chip(i18n.t("Edit or Create Reels"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("reel"))
            c2 = _chip(i18n.t("Extract BOQ / BOM"), "arrow-right")
            c2.clicked.connect(lambda: self.command_requested.emit("boq"))
            c3 = _chip(i18n.t("Manage Leads"), "arrow-right")
            c3.clicked.connect(lambda: self.command_requested.emit("leads"))
            c4 = _chip(i18n.t("WhatsApp Automation"), "message")
            c4.clicked.connect(lambda: self.command_requested.emit("whatsapp"))
            c5 = _chip(i18n.t("Diagnose an Issue"), "help")
            c5.clicked.connect(self._start_ai)
            self._options([c1, c2, c3, c4, c5], header=i18n.t("Quick actions"))
            return

        if self._is_overview_request(text):
            self._stage = "triage"
            self._entry.setPlaceholderText(i18n.t("Ask Lumi anything about Prism..."))
            self._refresh_escalation()
            self._bot(i18n.t(
                "**Welcome to Prism!** 🌟 Prism is an all-in-one AI & automation workstation for engineering and business operations.\n\n"
                "Here is what you can do:\n\n"
                "• 🎬 **Reel Creator**: Build and edit marketing videos, timelines, voiceovers, and captions.\n"
                "• 📊 **BOQ & BOM Extractor**: Analyze CAD/Gerber/DXF drawings, count components, and calculate cost estimates.\n"
                "• 👥 **Leads Workbench**: Source, enrich, and export verified B2B leads for client outreach.\n"
                "• 💬 **WhatsApp Automation**: Send personalized follow-ups, quotes, and customer messages safely.\n"
                "• 📐 **CAD & Gerber Viewers**: Inspect PCB copper layers, drill files, and interactive 3D STEP models.\n"
                "• ⚙️ **AI Planning & Tools**: Automate multi-step browser and file tasks using your Groq key."
            ), rich=True)
            t1 = _chip(i18n.t("Take Guided Tour"), "arrow-right")
            t1.clicked.connect(lambda: self.command_requested.emit("tour"))
            t2 = _chip(i18n.t("Open Reel Creator"), "arrow-right")
            t2.clicked.connect(lambda: self.command_requested.emit("reel"))
            t3 = _chip(i18n.t("Open BOQ Extractor"), "arrow-right")
            t3.clicked.connect(lambda: self.command_requested.emit("boq"))
            t4 = _chip(i18n.t("Open Leads"), "arrow-right")
            t4.clicked.connect(lambda: self.command_requested.emit("leads"))
            self._options([t1, t2, t3, t4], header=i18n.t("Quick start"))
            return

        if self._stage == "ai":
            hits = KB.search(text)
            if hits and not self._looks_like_failure(text):
                self._stage = "triage"
                self._entry.setPlaceholderText(i18n.t("Ask Lumi anything about Prism..."))
                self._refresh_escalation()
                self._show_answer(hits[0].qid, echo=False)
                return
            self._ask_ai(text)
            return

        raw_hits = KB.search(text)
        hits = [q for q in raw_hits if q.qid not in self._seen]
        if not hits and raw_hits:
            hits = [raw_hits[0]]
        if hits:
            # Show the direct answer for the best hit right away!
            top = hits[0]
            self._show_answer(top.qid, echo=False)

            # Offer a clean, compact option row below the answer
            if len(hits) > 1:
                buttons = []
                for question in hits[1:3]:
                    btn = _chip(question.text, "chevron-right")
                    btn.clicked.connect(
                        lambda _=False, q=question.qid: self._show_answer(q))
                    buttons.append(btn)
                none = _chip(i18n.t("None of these is what I meant"), "x")
                none.clicked.connect(lambda t=text: self._no_answer(t))
                buttons.append(none)
                self._options(buttons, header=i18n.t("Related topics"), scroll=False)
            else:
                none = _chip(i18n.t("None of these is what I meant"), "x")
                none.clicked.connect(lambda t=text: self._no_answer(t))
                self._options([none], scroll=False)
        else:
            self._no_answer(text)

    @staticmethod
    def _looks_like_failure(text: str) -> bool:
        words = (text or "").lower()
        signals = ("error", "fail", "failed", "stopped", "stuck", "crash",
                   "render", "json", "agent", "not working", "won't", "cannot",
                   "can't", "problem", "broken", "halfway")
        return any(signal in words for signal in signals)

    def _no_answer(self, text: str):
        self._unsolved.append(text)
        self._retire_menus()

        # Smart fallback based on Prism domain knowledge
        t_low = (text or "").lower()
        if any(w in t_low for w in ("artifact", "deliverable", "saved video", "past video", "output file")):
            self._bot(i18n.t(
                "You can view and manage all your generated files in **Artifacts**:\n\n"
                "• **View & Open**: Access videos, spreadsheets, and documents from the left sidebar.\n"
                "• **Edit Videos**: Click the **Pencil icon** ('Edit the layout') beside any Studio video to open the visual editor and modify text, scenes, and timings.\n"
                "• **Locate Files**: Click Folder to reveal the exact files on your computer."
            ), rich=True)
            c1 = _chip(i18n.t("Open Artifacts"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("artifacts"))
            c2 = _chip(i18n.t("Open Reel Creator"), "arrow-right")
            c2.clicked.connect(lambda: self.command_requested.emit("reel"))
            self._options([c1, c2])
            return

        if any(w in t_low for w in ("reel", "video", "timeline", "scene", "clip", "render", "audio")):
            self._bot(i18n.t(
                "You can create, edit, and render videos using the **Reel Creator** in Prism.\n\n"
                "• **Scenes & Script**: Edit scene text, timing, and visual elements.\n"
                "• **Media & Voiceover**: Choose background music and voiceover models.\n"
                "• **Produce Video**: Click **Make my reel** (or **Save & render** in the browser editor), then click **Show file** or view it under **Artifacts**."
            ), rich=True)
            c1 = _chip(i18n.t("Open Reel Creator"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("reel"))
            self._options([c1])
            return

        if any(w in t_low for w in ("boq", "bom", "bill of", "quantity", "estimate", "takeoff", "dxf", "dwg")):
            self._bot(i18n.t(
                "Prism features a dedicated **BOQ / BOM Extractor** for engineering drawings:\n\n"
                "• **Upload**: Import your DXF, DWG, PDF, or CAD drawings.\n"
                "• **Analyze**: Automatically detect layers, blocks, measurements, and counts.\n"
                "• **Export**: Export clean Excel or CSV bills of materials."
            ), rich=True)
            c1 = _chip(i18n.t("Open BOQ Extractor"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("boq"))
            self._options([c1])
            return

        if any(w in t_low for w in ("whatsapp", "chat", "bulk message", "message")):
            self._bot(i18n.t(
                "**WhatsApp Automation** helps you reach clients and follow up automatically:\n\n"
                "• **Connect**: Link your session securely in Settings.\n"
                "• **Campaigns**: Send personalized updates with attachments.\n"
                "• **Safety**: Built-in pacing ensures messaging complies with WhatsApp guidelines."
            ), rich=True)
            c1 = _chip(i18n.t("Open WhatsApp Setup"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("whatsapp"))
            self._options([c1])
            return

        if any(w in t_low for w in ("lead", "prospect", "outreach", "apollo", "contacts")):
            self._bot(i18n.t(
                "The **Leads Workbench** allows you to discover, filter, and export B2B leads:\n\n"
                "• Filter by industry, job title, location, or company size.\n"
                "• Export clean contact lists to CSV / spreadsheet."
            ), rich=True)
            c1 = _chip(i18n.t("Open Leads Workbench"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("leads"))
            self._options([c1])
            return

        if any(w in t_low for w in ("gerber", "step", "pcb", "3d", "cad")):
            self._bot(i18n.t(
                "Prism includes native hardware inspection tools:\n\n"
                "• **Gerber Viewer**: Inspect PCB copper layers, silkscreens, and drill paths.\n"
                "• **STEP 3D Viewer**: Rotate, measure, and analyze 3D CAD files locally."
            ), rich=True)
            c1 = _chip(i18n.t("Open Gerber Viewer"), "arrow-right")
            c1.clicked.connect(lambda: self.command_requested.emit("gerber"))
            c2 = _chip(i18n.t("Open STEP 3D Viewer"), "arrow-right")
            c2.clicked.connect(lambda: self.command_requested.emit("step"))
            self._options([c1, c2])
            return

        # General helpful fallback
        self._bot(i18n.t(
            "I couldn't find an exact local answer for that in the guide. "
            "You can run an AI diagnosis across your recent logs, or contact our support team."
        ), rich=True)
        diag = _chip(i18n.t("Diagnose with AI"), "help")
        diag.clicked.connect(self._start_ai)
        supp = _chip(i18n.t("Contact Support"), "mail")
        supp.clicked.connect(self._open_contact)
        self._options([diag, supp])

    # ── live diagnosis ─────────────────────────────────────────────────────
    def _start_ai(self):
        if not self.cfg.get("api_key"):
            self._bot(i18n.t(
                "AI diagnosis needs the Groq key Prism uses to plan work, and "
                "there isn't one saved on this computer. You can still use the "
                "local answers or contact our team."))
            go = _chip(i18n.t("Add the key in Settings"), "key")
            go.clicked.connect(lambda: self.command_requested.emit("key"))
            self._options([go])
            return
        self._stage = "ai"
        self._refresh_escalation()
        self._entry.setPlaceholderText(
            i18n.t("Describe the failed task or error…"))
        self._head.set_subtitle(i18n.t(
            "AI diagnosis uses your Groq key and a scrubbed recent log."))
        self._bot(i18n.t(
            "Tell me what stopped, what you expected, and what you already "
            "tried. I will check the local guide and recent Prism errors, then "
            "give you the safest next step."))
        self._entry.setFocus()

    def _ask_ai(self, text: str):
        if self._worker is not None:
            return
        self._start_thinking()
        self._entry.setEnabled(False)
        self._send.setEnabled(False)
        from workers import SupportWorker
        self._worker = SupportWorker(self.cfg, self._prompt(text), self)
        self._worker.done.connect(self._ai_answered)
        self._worker.failed.connect(self._ai_failed)
        self._worker.start()

    def _prompt(self, text: str) -> str:
        seen = tuple(self._seen)
        talk = "\n".join(
            f"{'CUSTOMER' if who == 'you' else 'PRISM'}: {said}"
            for who, said in self._log[-14:])
        return (
            f"{_SYSTEM}\n\n"
            f"─── PRISM REFERENCE MATERIAL ───\n"
            f"{KB.as_context(text, seen)}\n\n"
            f"─── THIS CUSTOMER'S SITUATION ───\n"
            f"{self._facts()}\n\n"
            f"─── THE CONVERSATION SO FAR ───\n{talk}\n\n"
            f"─── DIAGNOSE THIS ───\n{text}\n\n"
            f"Reply as Lumi, Prism's diagnostic assistant, following the rules above.")

    def _recent_log_summary(self) -> str:
        """Summarize recent log errors in plain English for the assistant.

        Reads the tail of the system log, scrubs sensitive tokens, and maps
        any crashes or errors through friendly.py so the assistant can give
        accurate diagnoses and actionable guidance without guessing.
        """
        try:
            import diagnostics
            import friendly
            raw_tail = diagnostics.tail(120)
            if not raw_tail or not raw_tail.strip():
                return "Recent system log events: (no errors recorded)"

            lines = raw_tail.splitlines()
            errors = []
            for line in reversed(lines):
                if any(tag in line for tag in ("ERROR", "CRASH", "Traceback", "Exception")):
                    scrubbed = diagnostics._scrub(line.strip())
                    if scrubbed and not any(scrubbed in e for e in errors):
                        errors.append(scrubbed)
                    if len(errors) >= 3:
                        break

            if not errors:
                return "Recent system log events: (no errors recorded)"

            summaries = []
            for err in errors:
                problem = friendly.explain(err, "run")
                # Do not send a raw log line to Groq. Even with credential
                # redaction it might contain a file name or task wording.
                # The locally produced diagnosis is enough to guide repair.
                summary_line = f"- Diagnosis: {problem.title} — {problem.what}"
                if problem.steps:
                    summary_line += f"\n  Steps: {'; '.join(problem.steps)}"
                if problem.action:
                    summary_line += f"\n  Action: {problem.action}"
                summaries.append(summary_line)

            return "Recent system log events:\n" + "\n".join(summaries)
        except Exception:
            return "Recent system log events: (logs unavailable)"

    def _facts(self) -> str:
        """What we know about this machine without asking them anything.

        Half of a support conversation is normally spent establishing these
        four facts. The assistant starts with them.
        """
        bits = [f"Prism version: {app_meta.VERSION}",
                f"Planning key saved: "
                f"{'yes' if self.cfg.get('api_key') else 'NO — not set up yet'}"]
        try:
            import sys
            bits.append(f"Computer: {sys.platform}")
        except Exception:                   # noqa: BLE001
            pass
        try:
            import licensing
            state = licensing.state()
            bits.append(f"Licence: {state.status}"
                        + (f", covers {', '.join(sorted(state.features))}"
                           if getattr(state, "features", None) else ""))
        except Exception:                   # noqa: BLE001
            pass
        if self._seen:
            titles = [KB.question(q).text for q in self._seen
                      if KB.question(q)]
            bits.append("Already read (do not repeat these): "
                        + "; ".join(titles))
        bits.append(self._recent_log_summary())
        return "\n".join(bits)

    def _start_thinking(self):
        """An animated "Thinking" bubble while the assistant works.

        The dots are appended to the already-translated base, so the
        animation costs one catalogue entry rather than four.
        """
        frame = QFrame()
        frame.setObjectName("supportBot")
        frame.setStyleSheet(
            f"QFrame#supportBot {{ background: {theme.CARD};"
            f"border: 1px solid {theme.HAIRLINE};"
            f"border-radius: {theme.R_CARD}px; }}")
        box = QVBoxLayout(frame)
        box.setContentsMargins(theme.SPACE_4 - 1, theme.SPACE_3,
                               theme.SPACE_4 - 1, theme.SPACE_3)
        label = C.label("", level="BODY", colour=theme.NEUTRAL[600])
        box.addWidget(label)
        base = i18n.t("Thinking")
        ticks = {"count": 0}

        def tick():
            label.setText(base + " ·" * (ticks["count"] % 4))
            ticks["count"] += 1
        tick()
        self._thinking = _wrap(frame, mine=False, glyph="prism")
        self._thinking_timer = QTimer(self)
        self._thinking_timer.timeout.connect(tick)
        self._thinking_timer.start(350)
        self._say(self._thinking)

    def _ai_answered(self, reply: str):
        self._clear_thinking()

        reply = reply or ""
        import re
        match = re.search(r"\[ACTION:\s*([a-zA-Z0-9_:-]+)\]", reply, re.IGNORECASE)
        action = None
        if match:
            action = match.group(1).strip()
            reply = reply[:match.start()].strip()

        self._bot(reply or i18n.t(
            "I didn't get an answer back that time. Try asking again, or use "
            "Contact the team."), rich=True)

        if not action:
            # Auto-infer action from answer content or customer query
            context_text = (reply + " " + (self._log[-2][1] if len(self._log) >= 2 else "")).lower()
            if any(w in context_text for w in ("reel", "studio", "timeline", "render")):
                action = "reel"
            elif any(w in context_text for w in ("chrome", "chromedriver", "browser")):
                action = "chrome"
            elif any(w in context_text for w in ("api key", "groq key", "planning key")):
                action = "key"
            elif any(w in context_text for w in ("lead", "outreach", "apollo")):
                action = "leads"
            elif any(w in context_text for w in ("gerber", "pcb")):
                action = "gerber"
            elif any(w in context_text for w in ("step", "3d model", "cad")):
                action = "step"
            elif any(w in context_text for w in ("whatsapp",)):
                action = "whatsapp"
            elif any(w in context_text for w in ("bom", "shortage")):
                action = "bom"
            elif any(w in context_text for w in ("boq", "dxf", "dwg")):
                action = "boq"
            elif any(w in context_text for w in ("email", "inquiry", "smtp")):
                action = "email"

        if action and (registry.is_off(action.lower())
                       or registry.is_absent(action.lower())):
            action = ""     # a switched-off add-on gets no "take me there"
        if action:
            clean_act = action.lower().replace("settings:", "")
            action_map = {
                "key": (i18n.t("Add API Key"), "key"),
                "agents": (i18n.t("Open Agent Settings"), "agents"),
                "chrome": (i18n.t("Open Chrome Settings"), "chrome"),
                "profile": (i18n.t("Open Profile Settings"), "profile"),
                "licence": (i18n.t("View Licence"), "licence"),
                "login": (i18n.t("Open Login Tabs"), "login"),
                "workbench": (i18n.t("Go to Workbench"), "workbench"),
                "runs": (i18n.t("View Past Runs"), "runs"),
                "artifacts": (i18n.t("Open Deliverables"), "artifacts"),
                "reel": (i18n.t("Open Reel Creator"), "reel"),
                "motion": (i18n.t("Open Motion Graphics"), "motion"),
                "whatsapp": (i18n.t("Open WhatsApp"), "whatsapp"),
                "leads": (i18n.t("Open Leads Workbench"), "leads"),
                "gerber": (i18n.t("Open Gerber Viewer"), "gerber"),
                "step": (i18n.t("Open STEP 3D Viewer"), "step"),
                "bom": (i18n.t("Open BOM Analyzer"), "bom"),
                "boq": (i18n.t("Open BOQ Extractor"), "boq"),
                "email": (i18n.t("Open Email Automation"), "email"),
                "guide": (i18n.t("Open Guide"), "guide"),
                "tour": (i18n.t("Take Guided Tour"), "tour"),
                "support": (i18n.t("Contact the team"), "support"),
            }
            label, emit_key = action_map.get(clean_act, (i18n.t("Take me there"), clean_act))
            chip = _chip(label, "arrow-right")
            chip.clicked.connect(lambda _=False, k=emit_key: self.command_requested.emit(k))
            self._options([chip])

    def _ai_failed(self, error: str):
        self._clear_thinking()
        # friendly.py already knows how to say every one of these — reusing it
        # means the assistant's failures read exactly like the app's do.
        import friendly
        problem = friendly.explain(error, "support")
        # Title included. Without it the message opens mid-sentence — the
        # headline is the half that says what kind of problem this is, and
        # the steps below make no sense arriving without it.
        text = f"{problem.title}\n\n{problem.what}"
        if problem.steps:
            text += "\n\n" + "\n".join(f"{i}. {s}"
                                       for i, s in enumerate(problem.steps, 1))
        self._bot(text)

    def _clear_thinking(self):
        self._entry.setEnabled(True)
        self._send.setEnabled(True)
        self._entry.setFocus()
        if self._thinking_timer is not None:
            self._thinking_timer.stop()
            self._thinking_timer = None
        if self._thinking is not None:
            self._thread_box.removeWidget(self._thinking)
            self._thinking.hide()   # before setParent(None): avoids ghost-window flash
            self._thinking.setParent(None)
            self._thinking.deleteLater()
            self._thinking = None
        if self._worker is not None:
            self._worker.deleteLater()
            self._worker = None

    def _transcript(self) -> str:
        """Format the conversation log as plain text for the contact sheet."""
        lines = []
        for who, text in getattr(self, "_log", []):
            speaker = i18n.t("Lumi") if who == "prism" else i18n.t("You")
            clean_text = str(text or "").strip()
            if clean_text:
                lines.append(f"{speaker}:\n{clean_text}\n")
        return "\n".join(lines).strip()

    # ── tier 3: a person ──────────────────────────────────────────────────
    def _open_contact(self):
        from dialogs.contact_dialog import ContactDialog
        sheet = ContactDialog(self._transcript(), self.window())
        sheet.exec()
        if sheet.sent:
            self._bot(i18n.t(
                "Sent to our team. We read every one of these and normally "
                "reply the same working day."))

    def _book_meeting(self):
        """Open the AlphaKore meeting booking link in the browser."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://alphakore.in/book"))

    # ── Home-card entry points ───────────────────────────────────────────
    def ask(self, question: str = ""):
        """Bring a Home-card question into the same local help flow."""
        if question.strip():
            self._entry.setText(question.strip())
            self._on_typed()
        else:
            self._entry.setFocus()

    def open_contact(self):
        self._open_contact()

    def book_meeting(self):
        self._book_meeting()

    # ── starting again ────────────────────────────────────────────────────
    def _start_over(self):
        """Forget the conversation and greet afresh."""
        if self._worker is not None:
            return
        while self._thread_box.count() > 1:      # keep the trailing stretch
            item = self._thread_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._live = []
        self._seen = []
        self._unsolved = []
        self._log = []
        self._thinking = None
        self._entry.setEnabled(True)
        self._send.setEnabled(True)
        self._entry.clear()
        self._reset_to_triage()
        self._greet()

    # ── shutting down ─────────────────────────────────────────────────────
    def shutdown(self):
        """Wind up the assistant's thread before the window goes.

        A running QThread destroyed with its owner takes the whole process
        with it — the customer would see Prism vanish while asking for help,
        which is a memorably bad way to end a support session. Called from
        the main window's own closeEvent, beside its other workers.
        """
        worker = getattr(self, "_worker", None)
        if worker is None:
            return
        try:
            if worker.isRunning() and not worker.wait(3000):
                worker.terminate()
                worker.wait(1000)
        except RuntimeError:
            pass                            # already deleted; nothing to wait
