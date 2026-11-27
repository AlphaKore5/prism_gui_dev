"""AgentsPicker — one combo box per pipeline category, shared by the Settings
screen's Agents section and the first-run wizard so "which tool handles which
kind of step" has one implementation instead of two that can drift apart.

Deliberately owns no chrome (no Card, no kicker, no surrounding Section) —
each host wraps it in its own card or plain page. Only the form of combos is
this widget's job; how it's framed is the host's.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QWidget

import ai_server
import core_bridge as CB
import i18n
from widgets.agents_panel import STAGE_COPY
from widgets.controls import icon_label

SKIP = "— skip this category —"


class AgentsPicker(QWidget):
    picked_changed = Signal()

    def __init__(self, initial: dict | None = None, parent=None,
                 file_reader: str = ""):
        super().__init__(parent)
        self._combos: dict[str, QComboBox] = {}
        self._reader: QComboBox | None = None
        saved = dict(initial or {})
        current = saved
        # When tasks are worked in the browser, only those steps have a tool
        # to pick: pictures and video run on the Prism plan, so their saved
        # picks are carried through untouched instead of being offered.
        browser = ai_server.browser_work()
        if browser:
            current = CB.agents.server_effective(saved)
        offered = [c for c in CB.agents.PIPELINE_ORDER
                   if c in CB.agents.CATEGORIES
                   and (not browser or c in CB.default_work.CHOICES)]
        self._kept = ({k: v for k, v in saved.items() if k not in offered}
                      if browser else {})
        # Steps Prism always fills cannot be "skipped": it would not be true.
        filled = (("research", "brains", "content") + CB.default_work.FILLED
                  if browser else ())

        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(9)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        # Pipeline order, not dict order — these rows should read in the same
        # sequence the plan lists them in.
        if browser:
            self._reader = QComboBox()
            self._reader.addItems(list(CB.default_work.FILE_READERS))
            self._reader.setCurrentText(CB.default_work.file_reader(
                {"analysis_agent": file_reader}))
            self._reader.currentIndexChanged.connect(
                lambda _index=None: self.picked_changed.emit())
            self._reader.setToolTip(i18n.t(
                "Reads the files you attach, before the first step"))
            icon_name, title, _ = STAGE_COPY["analysis"]
            form.addRow(icon_label(icon_name, title), self._reader)

        for cat in offered:
            meta = CB.agents.CATEGORIES[cat]
            combo = QComboBox()
            combo.addItems(list(meta["agents"])
                           + ([] if cat in filled else [SKIP]))
            default = current.get(cat)
            combo.setCurrentText(
                default if default in meta["agents"]
                else meta["agents"][0] if cat in filled else SKIP)
            # Not .connect(self.picked_changed.emit) directly: PySide6 passes
            # currentIndexChanged's int through to the connected slot, and a
            # zero-arg Signal's bound emit() raises on an unexpected argument
            # rather than dropping it, the way a plain Python slot would.
            combo.currentIndexChanged.connect(
                lambda _index=None: self.picked_changed.emit())
            combo.setToolTip(meta.get("desc", ""))
            self._combos[cat] = combo
            # The plan calls this step "Build the slides"; every picker
            # should name the same thing the same way, with the same icon.
            icon_name, title, _ = STAGE_COPY.get(cat, ("grid", meta["label"], ""))
            form.addRow(icon_label(icon_name, title), combo)

    def visible_agents(self) -> dict:
        """The picks made on this form."""
        return {cat: combo.currentText() for cat, combo in self._combos.items()
                if combo.currentText() != SKIP}

    def current_agents(self) -> dict:
        """The picks to save: this form's, plus saved ones it does not show."""
        return {**self._kept, **self.visible_agents()}

    def current_file_reader(self) -> str:
        """The tool that reads attachments; "" where there is no such choice."""
        return self._reader.currentText() if self._reader is not None else ""

    def combos(self) -> list[QComboBox]:
        return list(self._combos.values())
