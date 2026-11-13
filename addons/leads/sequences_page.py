"""The Sequences tab — section 3 of "Prism CRM: interface mockups" (3 Nov 2026), the old placeholder made into a real editor.

Pick a sequence, edit its touches (when, subject, text), save; see exactly what stops it; see who is in it and where they stand. The rules and the
reading of stored history are sequences.py's. Nothing on this page sends: later touches are drafted here and listed in Due today when they fall due.

`_confirm_delete` is the one question it asks; tests answer it without a window.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget)

import i18n
import theme
from addons.leads import result_rows as RR
from addons.leads import sequences as SQ
from addons.leads import store
from widgets import controls as C


class _StepEditor(QFrame):
    """One touch: the day it is due (after the first message), its subject and its text."""

    removeRequested = Signal(object)

    def __init__(self, index: int, step: SQ.Step, parent=None):
        super().__init__(parent)
        self.setObjectName("stepEditor")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#stepEditor{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};border-radius:{theme.R_CONTROL}px;}}")
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3, theme.SPACE_3)
        col.setSpacing(theme.SPACE_2)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_2)
        self.title = C.label(i18n.t("Touch {n}").format(n=index + 1), level="SUPPORT", weight=700)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(C.label(i18n.t("Due"), level="SUPPORT", colour=theme.NEUTRAL[600]))
        self.days = QSpinBox()
        self.days.setRange(0, 365)
        self.days.setValue(step.after_days)
        self.days.setSuffix(i18n.t(" days after the first message"))
        head.addWidget(self.days)
        self.remove_btn = C.button(i18n.t("Remove"), small=True, on_click=lambda: self.removeRequested.emit(self))
        head.addWidget(self.remove_btn)
        col.addLayout(head)
        self.subject = QLineEdit(step.subject)
        self.subject.setPlaceholderText(i18n.t("Subject"))
        col.addWidget(self.subject)
        self.body = QPlainTextEdit(step.body)
        self.body.setPlaceholderText(i18n.t("Text. {first_name}, {company} and {title} are filled in for each person."))
        self.body.setFixedHeight(92)
        col.addWidget(self.body)

    def renumber(self, index: int, only: bool) -> None:
        self.title.setText(i18n.t("Touch {n}").format(n=index + 1))
        self.remove_btn.setEnabled(not only)

    def value(self) -> SQ.Step:
        return SQ.Step(self.days.value(), self.subject.text(), self.body.toPlainText())


class SequencesPage(QWidget):
    openRequested = Signal(object)         # the lead, from a person's row
    changed = Signal()                     # a sequence was added, saved or deleted

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder = ""
        self._contacts: list = []
        self._today: Optional[date] = None
        self._seqs: list = []
        self._editors: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("seqHead")
        head.setStyleSheet(f"QFrame#seqHead{{background:{theme.CARD};border:none;border-bottom:1px solid {theme.HAIRLINE};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(C.label(i18n.t("Sequences"), level="SECTION", weight=700))
        self.summary = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        titles.addWidget(self.summary)
        hl.addLayout(titles, 1)
        self.picker = QComboBox()
        self.picker.setMinimumWidth(200)
        self.picker.activated.connect(lambda _i: self._show(self.picker.currentData()))
        hl.addWidget(self.picker)
        self.new_btn = C.button(i18n.t("New sequence"), "primary", on_click=self.new_sequence)
        hl.addWidget(self.new_btn)
        outer.addWidget(head)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        host = QWidget()
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        self._col.setSpacing(theme.SPACE_3)
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self.empty = C.EmptyState("send", i18n.t("No sequence yet"),
                                  i18n.t("A sequence is a short run of touches that stops when someone replies."),
                                  i18n.t("New sequence"))
        self.empty.clicked.connect(self.new_sequence)
        self._col.addWidget(self.empty)

        self.editor_card = QFrame()
        self.editor_card.setObjectName("seqEditor")
        self.editor_card.setAttribute(Qt.WA_StyledBackground, True)
        self.editor_card.setStyleSheet(
            f"QFrame#seqEditor{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}")
        ec = QVBoxLayout(self.editor_card)
        ec.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        ec.setSpacing(theme.SPACE_2)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(i18n.t("Name"))
        ec.addWidget(self.name_edit)
        self._steps_col = QVBoxLayout()
        self._steps_col.setSpacing(theme.SPACE_2)
        ec.addLayout(self._steps_col)
        row = QHBoxLayout()
        self.add_step_btn = C.button(i18n.t("Add a touch"), small=True, on_click=self.add_step)
        row.addWidget(self.add_step_btn)
        row.addStretch(1)
        self.delete_btn = C.button(i18n.t("Delete sequence"), small=True, on_click=self.delete_sequence)
        row.addWidget(self.delete_btn)
        self.save_btn = C.button(i18n.t("Save"), "primary", small=True, on_click=self.save)
        row.addWidget(self.save_btn)
        ec.addLayout(row)
        self.status = C.label("", level="SUPPORT", colour=theme.WARN_INK, wrap=True)
        self.status.hide()
        ec.addWidget(self.status)
        self._col.addWidget(self.editor_card)

        stops, sc = _card(i18n.t("Stops when"))
        for words, _stages in SQ.STOPS:
            sc.addWidget(C.label("•  " + i18n.t(words), level="SUPPORT"))
        sc.addWidget(C.label(i18n.t("Nothing here sends by itself. Prism drafts each later touch, lists it in Due today when it falls due, "
                                    "and you send it."), level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True))
        self._col.addWidget(stops)

        self.people = RR.ResultList()
        self._col.addWidget(self.people)
        self._col.addStretch(1)
        self.set_folder("")

    # -- data ----------------------------------------------------------------
    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def set_today(self, today: Optional[date]) -> None:
        self._today = today

    def set_contacts(self, contacts) -> None:
        self._contacts = list(contacts or ())
        self._draw_people()

    def sequences(self) -> list:
        return list(self._seqs)

    def current(self) -> Optional[SQ.Sequence]:
        seq_id = self.picker.currentData()
        return next((s for s in self._seqs if s.id == seq_id), None)

    def refresh(self, keep: str = "") -> None:
        self._seqs = SQ.list_sequences(self._folder) if self._folder else []
        keep = keep or (self.picker.currentData() or "")
        self.picker.blockSignals(True)
        self.picker.clear()
        for s in self._seqs:
            self.picker.addItem(s.name, s.id)
        self.picker.setCurrentIndex(max(0, self.picker.findData(keep)))
        self.picker.blockSignals(False)
        self.picker.setVisible(bool(self._seqs))
        self._show(self.picker.currentData())

    # -- showing one ---------------------------------------------------------
    def _show(self, seq_id) -> None:
        seq = next((s for s in self._seqs if s.id == seq_id), None)
        self.empty.setVisible(seq is None)
        self.editor_card.setVisible(seq is not None)
        self.status.hide()
        for ed in self._editors:
            ed.hide()
            ed.setParent(None)
            ed.deleteLater()
        self._editors = []
        if seq is not None:
            self.name_edit.setText(seq.name)
            for step in seq.steps:
                self._add_editor(step)
        self._draw_people()

    def _add_editor(self, step: SQ.Step) -> None:
        ed = _StepEditor(len(self._editors), step)
        ed.removeRequested.connect(self._remove_editor)
        self._editors.append(ed)
        self._steps_col.addWidget(ed)
        self._renumber()

    def _remove_editor(self, ed) -> None:
        if ed in self._editors and len(self._editors) > 1:
            self._editors.remove(ed)
            ed.hide()
            ed.setParent(None)
            ed.deleteLater()
            self._renumber()

    def _renumber(self) -> None:
        for i, ed in enumerate(self._editors):
            ed.renumber(i, len(self._editors) == 1)
        self.add_step_btn.setEnabled(len(self._editors) < SQ.MAX_STEPS)

    def add_step(self) -> None:
        last = self._editors[-1].days.value() if self._editors else 0
        self._add_editor(SQ.Step(last + 3, "", ""))

    # -- the people in it ----------------------------------------------------
    def _draw_people(self) -> None:
        seq = self.current()
        self.people.clear()
        rows = SQ.enrolments(self._contacts, seq, self._today) if seq is not None else []
        specs = []
        for i, e in enumerate(rows):
            lead = e.contact.lead
            if e.next_due is not None:
                subline = i18n.t("Touch {n} of {total} · {when}").format(
                    n=min(e.done + 1, e.total), total=e.total,
                    when=(i18n.t("late {n} days").format(n=e.late_days) if e.late_days else i18n.t("due {d}").format(d=e.next_due.strftime("%d %b"))))
            else:
                subline = i18n.t("{n} of {total} touches sent").format(n=e.done, total=e.total)
            tone = "warn" if e.is_due() else ("quiet" if e.status.startswith("Stopped") or e.status == "Finished" else "info")
            specs.append(RR.ResultRow(RR.RowSpec(
                key=i, name=lead.name or i18n.t("(no name)"), company=lead.company or "", subline=subline,
                pills=[(i18n.t(e.status.split(":")[0]) + (":" + e.status.split(":", 1)[1] if ":" in e.status else ""), tone)],
                actions=[(i18n.t("Open"), False, lambda _=False, l=lead: self.openRequested.emit(l))], checkable=False)))
        self.people.add_all(specs)
        self.people.setVisible(bool(specs))
        due = sum(1 for e in rows if e.is_due())
        if seq is None:
            self.summary.setText(i18n.t("Make a sequence to follow up without losing track."))
        elif rows:
            self.summary.setText(i18n.t("{n} in this sequence · {d} due. Nothing here sends by itself.").format(n=len(rows), d=due))
        else:
            self.summary.setText(i18n.t("Nobody is in this sequence yet. “Add to sequence” on People sends touch 1 and enrols them."))

    # -- actions -------------------------------------------------------------
    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def new_sequence(self) -> Optional[SQ.Sequence]:
        if not self._folder:
            return None
        try:
            seq = SQ.add(self._folder, i18n.t("3-touch email") if not self._seqs else i18n.t("New sequence"))
        except (SQ.SequenceError, store.StoreError) as e:
            self._say(str(e))
            return None
        self.refresh(keep=seq.id)
        self.changed.emit()
        return seq

    def save(self) -> bool:
        seq = self.current()
        if seq is None:
            return False
        try:
            SQ.update(self._folder, seq.id, self.name_edit.text(), [ed.value() for ed in self._editors])
        except (SQ.SequenceError, store.StoreError) as e:
            self._say(str(e))
            return False
        self.refresh(keep=seq.id)
        self.changed.emit()
        return True

    def _confirm_delete(self, name: str) -> bool:
        return QMessageBox.question(self, i18n.t("Delete sequence"),
                                    i18n.t("Delete “{name}”? People already in it stay saved.").format(name=name)) == QMessageBox.StandardButton.Yes

    def delete_sequence(self) -> bool:
        seq = self.current()
        if seq is None or not self._confirm_delete(seq.name):
            return False
        try:
            SQ.remove(self._folder, seq.id)
        except store.StoreError as e:
            self._say(str(e))
            return False
        self.refresh()
        self.changed.emit()
        return True


def _card(name: str) -> tuple:
    frame = QFrame()
    frame.setObjectName("seqCard")
    frame.setAttribute(Qt.WA_StyledBackground, True)
    frame.setStyleSheet(f"QFrame#seqCard{{background:{theme.CARD};border:1px solid {theme.HAIRLINE};border-radius:{theme.R_CARD}px;}}")
    col = QVBoxLayout(frame)
    col.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
    col.setSpacing(theme.SPACE_2)
    col.addWidget(C.label(name, level="SUPPORT", weight=700))
    return frame, col
