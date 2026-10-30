"""BOQ-CHANGES-TODO.md item 30d's own History screen.

Every BOQ run is already saved by CB.config.save_run() (addons/boq/
dialog.py's _on_written/_on_followed_up) to a JSON file under
~/.prism/runs/ — one file per job, updated in place as follow-ups come
in, tagged "addon": "boq" so this module can find them without guessing
from the title text. This file is the "someone made 3 BOQs today, needs
to follow up on the first one this afternoon" screen: list those files
by date, let the person pick one, hand its saved state back to the
dialog to resume.

Deliberately NOT a new storage system — the folder-per-job and the
JSON-record-per-job both already existed (begin_run/continue_run/
save_run, core/config.py) before item 30 was ever asked for; this reads
them, it does not duplicate them.
"""
from __future__ import annotations

import glob
import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel,
)

import core_bridge as CB
import i18n
from widgets import controls as C


def list_boq_runs() -> list[dict]:
    """Every saved BOQ run, newest first. Each dict is the saved record
    (see dialog.py's own save_run() calls) plus "_path" (the JSON file
    it came from, so a caller can re-save to the same one) — a file that
    fails to parse is skipped, not a crash for the whole list."""
    out = []
    for path in glob.glob(os.path.join(CB.config.RUNS_DIR, "run_*.json")):
        try:
            with open(path, "r", encoding="utf-8") as f:
                record = json.load(f)
        except (OSError, ValueError):
            continue
        if record.get("addon") != "boq":
            continue
        record["_path"] = path
        out.append(record)
    out.sort(key=lambda r: os.path.getmtime(r["_path"]), reverse=True)
    return out


def when_label(path: str) -> str:
    """The run file's own modified time, in a short "Tue 29 Oct, 14:05"
    form -- used by this module's own list AND by dialog.py's
    _resume_from_history (via the record's "_path"), so the date shown
    when picking a job and the date shown after resuming it never
    disagree."""
    import datetime
    try:
        return datetime.datetime.fromtimestamp(
            os.path.getmtime(path)).strftime("%a %d %b, %H:%M")
    except OSError:
        return ""


class BoqHistoryDialog(QDialog):
    """Pick a past BOQ job by date and what it was. `chosen` holds the
    selected record (same shape list_boq_runs() returns) once the dialog
    is accepted — "" / None before that, the same way every other picker
    dialog in this add-on hands a result back (see
    InputMeasurementsDialog.measurements_text())."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("BOQ history"))
        self.resize(560, 420)
        self.chosen: dict | None = None
        self._runs = list_boq_runs()

        col = QVBoxLayout(self)
        col.addWidget(C.label(i18n.t(
            "Every BOQ you've made, newest first. Pick one to open it here "
            "and carry on with a follow-up — the earlier prompts and the "
            "document it produced come with it."), level="SUPPORT", wrap=True))

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _: self._accept())
        col.addWidget(self.list, stretch=1)
        self._fill()

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(C.button(i18n.t("Cancel"), "secondary", on_click=self.reject))
        self.open_btn = C.button(i18n.t("Open this BOQ"), "primary", on_click=self._accept)
        self.open_btn.setEnabled(False)
        btn_row.addWidget(self.open_btn)
        col.addLayout(btn_row)
        self.list.itemSelectionChanged.connect(
            lambda: self.open_btn.setEnabled(bool(self.list.selectedItems())))

    def _fill(self):
        self.list.clear()
        if not self._runs:
            item = QListWidgetItem(i18n.t("No BOQs made yet."))
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
            self.list.addItem(item)
            return
        for i, run in enumerate(self._runs):
            when = when_label(run["_path"])
            request = (run.get("request") or run.get("query") or "").strip()
            label = f"{when}  —  {request}" if request else when
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, i)
            self.list.addItem(item)

    def _accept(self):
        items = self.list.selectedItems()
        if not items:
            return
        i = items[0].data(Qt.UserRole)
        if i is None:
            return
        self.chosen = self._runs[i]
        self.accept()
