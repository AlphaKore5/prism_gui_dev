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


# item 73 (12 Nov 2026): "start the BOQ count from 0... so i can see how
# i am spending on each of the BOQ" -- the owner's own test runs from
# today (a pharma client, an ELV client, the locker, the trolley catalogue...)
# are real files History must keep showing, but they are not the baseline
# a going-forward "tokens per BOQ" figure should be measured against. One
# small marker file, never a second copy of the runs themselves: every
# run from before the marker's own timestamp stops counting toward
# counts_by_period(), while remaining exactly where it always was for
# History, follow-ups and everything else that reads list_boq_runs().
_RESET_MARKER = "_boq_counter_reset.json"


def reset_counter() -> None:
    """Zero the counter from this moment on. Callable again later (a
    small "Reset" action beside the counter itself, addons/boq/panel.py)
    -- not a one-off fix only reachable by editing a file by hand."""
    import time
    path = os.path.join(CB.config.RUNS_DIR, _RESET_MARKER)
    os.makedirs(CB.config.RUNS_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"reset_at": time.time()}, f)


def _counter_reset_at() -> float:
    path = os.path.join(CB.config.RUNS_DIR, _RESET_MARKER)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return float(json.load(f).get("reset_at") or 0.0)
    except (OSError, ValueError, TypeError):
        return 0.0


# item 70 (12 Nov 2026): "a small BOQ counter... how many were made in a
# day, a month, a year... and token utilization for each" -- read off the
# SAME run files list_boq_runs() already reads, bucketed by the run
# file's own mtime (the same timestamp when_label() already shows, so the
# counter and History's own dates never disagree). Deliberately not a
# new counter/log of its own, same reason list_boq_runs() itself gives.
def counts_by_period(now=None) -> dict:
    """{"day"/"month"/"year": {"boqs": N, "tokens": N}} -- each period
    nests the ones below it (this month's count includes today's), the
    ordinary meaning of "how many this month". `tokens` sums whatever
    OpenRouter usage a run's own "tokens" field carries (see dialog.py's
    _on_prism_agent_done) -- a run made entirely by a browser-driven
    agent (ChatGPT, Claude-in-a-tab, ...) has no token count to add and
    correctly counts as 0, never guessed from its text length. `now`:
    only ever passed by a test; real callers take the real clock."""
    import datetime
    now = now or datetime.datetime.now()
    reset_at = _counter_reset_at()
    out = {"day": {"boqs": 0, "tokens": 0}, "month": {"boqs": 0, "tokens": 0},
          "year": {"boqs": 0, "tokens": 0}}
    for run in list_boq_runs():
        try:
            mtime = os.path.getmtime(run["_path"])
        except OSError:
            continue
        if mtime < reset_at:
            continue
        made = datetime.datetime.fromtimestamp(mtime)
        tokens = (run.get("tokens") or {}).get("total_tokens") or 0
        if made.year != now.year:
            continue
        out["year"]["boqs"] += 1
        out["year"]["tokens"] += tokens
        if made.month != now.month:
            continue
        out["month"]["boqs"] += 1
        out["month"]["tokens"] += tokens
        if made.date() != now.date():
            continue
        out["day"]["boqs"] += 1
        out["day"]["tokens"] += tokens
    return out


def format_count(n: int) -> str:
    """1234 -> "1.2K", 1_250_000 -> "1.3M" -- so the counter stays "very
    little space" even once token counts run into the millions. Anything
    under 1,000 is shown exactly; nothing here is ever a guess, only a
    shorter way to write a real sum."""
    if n < 1000:
        return str(n)
    if n < 1_000_000:
        return f"{n / 1000:.1f}K"
    return f"{n / 1_000_000:.1f}M"


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
