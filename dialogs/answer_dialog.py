"""A running conversation with one AI about one question, shown full-size
and as real markdown.

The result box inside an add-on's own dialog is a few lines tall and plain
text — fine for "Measured", not for a paragraph of material advice someone
actually has to read, let alone a back-and-forth. This is that conversation
alone, nothing else mixed in (no measurements, no change plan): what was
asked, who answered, what a follow-up added — every turn stays on screen,
never overwritten, so the person can scroll back up and see exactly what
they asked and what they were told, the way a chat thread would. Any
add-on's plain-question step can use it — STEP is the first.

Follow-up is opt-in (`allow_followup=True`) and UI-only here: this dialog
never calls a model itself. It types a note, emits `followup_requested`,
and waits — the owner (the add-on's own dialog) does the actual asking and
reports back through `set_answer`/`set_busy`, exactly the way the owner
already knows how to reach whichever tool is answering. `model_choices`
(a list of `(value, label)` pairs) turns on a "Reply as" picker next to
the follow-up box, so a follow-up is not stuck with whichever tool
answered first — the owner reads the chosen value back off
`followup_requested`'s second argument.

Persistence is the same shape: this dialog holds no file path and does no
I/O. `prior_thread` seeds the conversation from whatever the owner already
has saved (so reopening it starts where it left off, not from empty), and
`on_change` is called with the full thread, as a plain list, every time a
turn is added — the owner writes that wherever it keeps that model's
conversation. Both are optional; leaving them out keeps this a one-shot,
unsaved popup exactly as before.

`allow_build=True` adds a "Build this" button beside Follow up — opt-in,
for an owner whose answer can turn into an actual file change (STEP's
Edit). Clicking it emits `build_requested` with nothing else to read: by
the time it fires, the owner already has the latest answer (every
`set_answer` call already told it so) and is the one deciding what "build
it" means. It does not close the popup — a person may want to build more
than once across a follow-up or two before they're done with it.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QApplication, QComboBox, QHBoxLayout, QLabel, QPlainTextEdit,
    QTextBrowser,
)

import i18n
import theme
import viewer
from dialogs.base import PrismDialog
from widgets.markdown import render_markdown


class AnswerDialog(PrismDialog):
    followup_requested = Signal(str, str)   # (typed text, chosen agent)
    build_requested = Signal()

    def __init__(self, title: str, subtitle: str, question: str,
                answer: str, agent: str, parent=None,
                allow_followup: bool = False, model_choices=None,
                prior_thread=None, on_change=None, allow_build: bool = False):
        super().__init__(title, subtitle, icon="chat", parent=parent)
        self._raw = answer
        self._agent = agent
        self._on_change = on_change
        self._thread: list[tuple[str, str]] = [
            (speaker, text) for speaker, text in (prior_thread or [])]
        self._thread += [(i18n.t("You asked"), question), (agent, answer)]
        self.resize(760, 640)
        self.setMinimumSize(480, 360)

        self.view = QTextBrowser()
        viewer.route_links(self.view)
        self.view.setStyleSheet(theme.type_css("BODY", theme.TEXT))
        self._render_thread()
        self.body.addWidget(self.view, stretch=1)

        self._busy_label = QLabel(i18n.t("Generating…"))
        self._busy_label.setStyleSheet(
            f"color: {theme.ACCENT_RAMP[700]}; font-weight: 600;")
        self._busy_label.setVisible(False)
        self.body.addWidget(self._busy_label)

        self.agent_combo = None
        self._followup_open = False
        self._followup_box = QPlainTextEdit()
        self._followup_box.setPlaceholderText(
            i18n.t("Ask a follow-up about this answer…"))
        self._followup_box.setFixedHeight(80)
        self._followup_box.setVisible(False)
        self.body.addWidget(self._followup_box)

        if model_choices:
            reply_row = QHBoxLayout()
            reply_row.addWidget(QLabel(i18n.t("Reply as:")))
            self.agent_combo = QComboBox()
            for value, label in model_choices:
                self.agent_combo.addItem(i18n.t(label), value)
            idx = self.agent_combo.findData(agent)
            self.agent_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.agent_combo.setVisible(False)
            reply_row.addWidget(self.agent_combo)
            reply_row.addStretch(1)
            self._reply_row = reply_row
            self.body.addLayout(reply_row)

        self.footer.add_secondary(self.button(
            i18n.t("Copy"), on_click=self._copy))
        self.followup_btn = None
        if allow_followup:
            self.followup_btn = self.button(
                i18n.t("Follow up"), on_click=self._on_followup_clicked)
            self.footer.add_secondary(self.followup_btn)
        self.build_btn = None
        if allow_build:
            self.build_btn = self.button(
                i18n.t("Build this"), on_click=self.build_requested.emit)
            self.footer.add_secondary(self.build_btn)
        self.footer.set_primary(self.button(
            i18n.t("Close"), "primary", on_click=self.accept))

    def _render_thread(self):
        parts = [f"**{speaker}**\n\n{text}" for speaker, text in self._thread]
        self.view.setHtml(render_markdown("\n\n---\n\n".join(parts)))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        if self._on_change is not None:
            self._on_change(list(self._thread))

    def _copy(self):
        QApplication.clipboard().setText(self._raw)

    def _on_followup_clicked(self):
        # Tracked explicitly rather than read off QWidget.isVisible(): that
        # reflects whether the whole WINDOW is mapped to the screen, not
        # just this one child's own setVisible() call — false for any
        # dialog built but not yet shown, which silently broke this exact
        # toggle under test (and would under any caller that builds the
        # dialog before .exec()/.show()).
        if not self._followup_open:
            self._followup_open = True
            self._followup_box.setVisible(True)
            if self.agent_combo is not None:
                self.agent_combo.setVisible(True)
            self.followup_btn.setText(i18n.t("Send"))
            self._followup_box.setFocus()
            return
        text = self._followup_box.toPlainText().strip()
        if not text:
            return
        agent = (self.agent_combo.currentData() if self.agent_combo
                is not None else self._agent)
        self._thread.append((i18n.t("You followed up"), text))
        self._render_thread()
        self._followup_box.clear()
        self._followup_box.setVisible(False)
        if self.agent_combo is not None:
            self.agent_combo.setVisible(False)
        self.followup_btn.setText(i18n.t("Follow up"))
        self._followup_open = False
        self.followup_requested.emit(text, agent)

    def set_answer(self, text: str, agent: str | None = None):
        """The owner's reply to a follow-up — added to the thread, never
        replacing what came before it."""
        self._raw = text
        self._agent = agent or self._agent
        self._thread.append((self._agent, text))
        self._render_thread()

    def set_busy(self, busy: bool):
        """Visible "Generating…" plus disabled input while the owner is
        off asking a model again — a follow-up used to give no sign
        anything was happening at all."""
        self._busy_label.setVisible(busy)
        self.view.setEnabled(not busy)
        self._followup_box.setEnabled(not busy)
        if self.agent_combo is not None:
            self.agent_combo.setEnabled(not busy)
        if self.followup_btn is not None:
            self.followup_btn.setEnabled(not busy)
        if self.build_btn is not None:
            self.build_btn.setEnabled(not busy)
