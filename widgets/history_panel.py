"""The History screen: every past run, re-rendered from its record."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout,
    QWidget,
)

import ai_server
import dashboard_data as DATA
import i18n
import theme
from widgets import controls as C
from widgets.panel_base import (
    _RunRow,
    ADDONS, _Elided, _kind_of, _plain_title, _state_of, bucket_for, _focusable_row, Page,
)


class _AbortedRow(QFrame):
    """A run of consecutive never-started records, folded into one line.

    Six identical "Untitled task / No tool recorded / Failed" rows is what
    made History look broken; on this machine there are eighty-six. Nothing is
    hidden — the count is stated, the "Never ran" filter chip lists them
    individually, and clicking here expands them in place.
    """

    expand = Signal()
    remove = Signal()

    def __init__(self, count: int, parent=None):
        super().__init__(parent)
        self.setObjectName("rowFlat")
        self.setAttribute(Qt.WA_StyledBackground, True)
        _focusable_row(self)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumHeight(C.MIN_TARGET + 22)

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_3)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.IconPad("archive", theme.NEUTRAL[600], 26,
                                theme.R_CHIP, 14))
        stack = QVBoxLayout()
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(1)
        stack.addWidget(_Elided(
            i18n.t("{n} runs that never started").format(n=count),
            "SUPPORT", theme.TEXT, weight=500))
        stack.addWidget(_Elided(
            i18n.t("No task text and no tool was recorded for any of them."),
            "META"))
        row.addLayout(stack, stretch=1)
        row.addWidget(C.button(i18n.t("Show them"), "tertiary",
                               icon_name="chevron-down",
                               on_click=self.expand.emit))
        # Clearing the whole fold without expanding it first: on real data
        # these are the overwhelming majority of records and all the same
        # Chrome failure, so "delete all of them" is the common wish.
        row.addWidget(C.icon_button("trash", i18n.t("Delete all of these"),
                                    self.remove.emit))

        self.setAccessibleName(i18n.t("{n} runs that never started").format(
            n=count))

    def mousePressEvent(self, event):
        child = self.childAt(event.position().toPoint())
        while child is not None and child is not self:
            if isinstance(child, QPushButton):
                return super().mousePressEvent(event)
            child = child.parentWidget()
        self.expand.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.expand.emit()
            return
        super().keyPressEvent(event)


class HistoryPanel(Page):
    """Every run, grouped by date, searchable and filterable by outcome.

    Reads the disk only when the screen is opened. MainWindow builds all
    eleven screens inside its own __init__, and this one used to open forty
    JSON files there — on a shared or synced workspace folder that is startup
    latency for a screen nobody has asked for yet.
    """

    TITLE = "History"
    BLURB = "Every past run, re-rendered out of its stored record."
    RELOAD_ON_SHOW = True               # always re-read runs when screen opens

    open_run = Signal(str)              # path of the run record
    runs_changed = Signal()             # runs were deleted; Home must re-read
    navigate = Signal(str)          # a key for MainWindow._handle_command

    LAZY = True
    LIMIT = 200
    COLLAPSE_AT = 3                 # fold this many consecutive aborts

    def __init__(self, cfg: dict = None, parent=None):
        self._runs = []
        self._expanded = set()
        self._chips = None
        self._chip_counts = None
        # Created here as well as in build(). This screen is LAZY, so
        # refresh() returns without building while it is off-screen -- and
        # the header's Clear all button exists from construction. A handler
        # that fires before the first build must find its state, not an
        # AttributeError.
        self._runs = []
        self._picked = set()
        self._bulk = None
        super().__init__(cfg, parent)

    def header_actions(self):
        return [C.button(i18n.t("Clear all"), "destructive", icon_name="trash",
                         on_click=self._clear_all),
                C.button(i18n.t("New task"), "primary", icon_name="plus",
                         on_click=lambda: self.navigate.emit("workbench"))]

    def build(self):
        self._runs = DATA.recent_runs(self.cfg, self.LIMIT) or []
        self._expanded = set()
        self._picked = set()            # paths of ticked rows
        self._chips = None
        self._chip_counts = None

        # One white card holding the search box and the count (the preview's
        # `.card.search`), not the bare toolbar strip.
        self._col.setSpacing(11)
        bar = C.Card()
        bar_row = QHBoxLayout()
        bar_row.setSpacing(theme.SPACE_3 - 1)
        bar.body((14, 8, 9, 8)).addLayout(bar_row)
        self._search = C.SearchField(
            i18n.t("Search a task, or a tool that ran it"))
        self._search.changed.connect(lambda _text: self._render())
        bar_row.addWidget(self._search, 1)
        self._count = C.label("", role="meta")
        self._count.setObjectName("monoMeta")
        bar_row.addWidget(self._count)
        self._col.addWidget(bar)

        self._chip_host = QWidget()
        self._chip_col = QVBoxLayout(self._chip_host)
        self._chip_col.setContentsMargins(0, 0, 0, 0)
        self._chip_col.setSpacing(0)
        self._col.addWidget(self._chip_host)

        self._bulk = C.Toolbar()
        self._bulk.setObjectName("selBar")      # the dark selection strip
        self._bulk_label = C.label("", role="meta")
        self._bulk.add(self._bulk_label, stretch=1)
        self._bulk.add(C.button(i18n.t("Delete selected"), "destructive",
                                icon_name="trash", small=True,
                                on_click=self._delete_picked))
        self._bulk.setVisible(False)
        self._col.addWidget(self._bulk)

        self._list = QWidget()
        self._list_col = QVBoxLayout(self._list)
        self._list_col.setContentsMargins(0, 0, 0, 0)
        self._list_col.setSpacing(0)
        self._col.addWidget(self._list, stretch=1)
        self._render()

    # -- filters ----------------------------------------------------------
    def _sync_chips(self, counts: dict):
        """Rebuilt only when the COUNTS change, never on a click — a chip row
        that deletes itself from inside its own clicked handler is a crash
        waiting for a slow machine."""
        if self._chips is not None and counts == self._chip_counts:
            return
        current = self._chips.current() if self._chips else "all"
        self._chip_counts = dict(counts)
        self._drop(self._chip_col)
        self._chips = C.FilterChips([
            ("all", i18n.t("All"), counts["all"]),
            ("completed", i18n.t("Completed"), counts["completed"]),
            ("failed", i18n.t("Failed"), counts["failed"]),
            ("cancelled", i18n.t("Never ran"), counts["cancelled"]),
        ], current)
        self._chips.changed.connect(lambda _value: self._render())
        self._chip_col.addWidget(self._chips)

    def _hits(self, run: dict, query: str) -> bool:
        parts = [(run.get("title") or "").lower()]
        in_browser = run.get("browser_tools") or []
        parts += [ai_server.display_agent(
            t, where="browser" if t in in_browser else "").lower()
            for t in (run.get("tools") or [])]
        kind = _kind_of(run.get("title", ""))
        if kind:
            parts.append(ADDONS[kind].lower())
        return any(query in part for part in parts)

    # -- render -----------------------------------------------------------
    def _render(self):
        self._drop(self._list_col)
        runs = self._runs
        counts = {"all": len(runs), "completed": 0, "failed": 0, "cancelled": 0}
        states = []
        for run in runs:
            state = _state_of(run)
            states.append(state)
            counts[state] += 1
        self._sync_chips(counts)

        want = self._chips.current() if self._chips else "all"
        query = (self._search.text() or "").strip().lower()
        rows = [(run, state) for run, state in zip(runs, states)
                if (want == "all" or state == want)
                and (not query or self._hits(run, query))]
        self._count.setText(i18n.t("{shown} of {total} runs").format(
            shown=len(rows), total=len(runs)))

        if not runs:
            self._list_col.addWidget(C.EmptyState(
                "inbox", i18n.t("No runs yet"),
                i18n.t("Every task you start is kept here — what you asked "
                       "for, which tools ran it, and what came back. Use "
                       "“New task” at the top of this screen to begin.")),
                stretch=1)
            return
        if not rows:
            self._list_col.addWidget(C.EmptyState(
                "search", i18n.t("Nothing matches that"),
                i18n.t("Try a different word, or show every run again.")),
                stretch=1)
            return

        groups: list[tuple[str, list]] = []
        for run, state in rows:
            bucket = bucket_for(run.get("when", ""), run.get("stamp", 0.0))
            if not groups or groups[-1][0] != bucket:
                groups.append((bucket, []))
            groups[-1][1].append((run, state))

        # When there are no completed or failed runs, the whole history is
        # "never started" — showing a single folded row for every group makes
        # the screen look completely empty, so the user thinks history is broken.
        # In this case skip the fold so each attempt is individually visible.
        has_real_runs = counts["completed"] > 0 or counts["failed"] > 0
        folding = want == "all" and not query and has_real_runs
        first_group = True
        for bucket, items in groups:
            head = C.SectionHeader(
                i18n.t(bucket),
                (i18n.t("1 run") if len(items) == 1
                 else i18n.t("{n} runs").format(n=len(items))).upper())
            head.subtitle.setProperty("mono", True)
            # The preview's day heading: 17px above (6 for the first, which
            # already sits 11px under the filters), 10px above its card.
            head.layout().setContentsMargins(4, 6 if first_group else 17,
                                             4, 10)
            first_group = False
            self._list_col.addWidget(head)
            card = C.Card()
            col = card.body((0, 0, 0, 0), spacing=0)

            # Real work first, in date order; the runs that never started
            # gathered into ONE row at the foot of the group.
            #
            # This used to fold each CONSECUTIVE stretch of aborts where it
            # sat, which on real data produced folds of 52, then 3, then 11
            # scattered between single real runs — and because a fold row
            # carries no date, the column read as though it had no order at
            # all. Aborted runs are also the overwhelming majority here (66 of
            # 82, every one the same Chrome failure), so leaving them inline
            # buried the fifteen runs that actually did something.
            #
            # Nothing is hidden: the count is stated, "Show them" expands the
            # group, and the "Never ran" chip lists them on their own.
            aborted = sum(1 for _r, s in items if s == "cancelled")
            fold_them = (folding and bucket not in self._expanded
                         and aborted >= self.COLLAPSE_AT)
            shown = ([(r, s) for r, s in items if s != "cancelled"]
                     if fold_them else items)

            first = True
            for run, state in shown:
                if not first:
                    col.addWidget(C.hairline())
                path = run.get("path", "")
                row = _RunRow(run, state, selectable=True, deletable=True)
                row.activated.connect(
                    lambda p=path: p and self.open_run.emit(p))
                if path in self._picked:
                    row.tick.setChecked(True)
                row.picked.connect(
                    lambda on, p=path: self._pick(p, on))
                row.removed.connect(
                    lambda r=run: self._delete([r]))
                col.addWidget(row)
                first = False
            if fold_them:
                if not first:
                    col.addWidget(C.hairline())
                fold = _AbortedRow(aborted)
                fold.expand.connect(lambda b=bucket: self._expand(b))
                folded = [r for r, st in items if st == "cancelled"]
                fold.remove.connect(lambda rs=folded: self._delete(rs))
                col.addWidget(fold)
            self._list_col.addWidget(card)
        self._list_col.addStretch(1)

    # -- deleting -----------------------------------------------------------
    def _pick(self, path: str, on: bool):
        """Remember a ticked row, and show the bar once anything is ticked."""
        if not path:
            return
        self._picked.add(path) if on else self._picked.discard(path)
        n = len(self._picked)
        if self._bulk is None:
            return                      # ticked before the first build
        self._bulk.setVisible(bool(n))
        self._bulk_label.setText(
            i18n.t("1 run selected") if n == 1
            else i18n.t("{n} runs selected").format(n=n))

    def _confirm_delete(self, n: int, everything: bool = False) -> bool:
        """Ask, with No as the default. A seam: a test stubs this rather
        than trying to press a button in a modal.

        The copy says what is KEPT, the way every other destructive message
        in this app does -- deleting a run removes the entry, not the work.
        """
        kept = i18n.t("The files those runs produced stay where they are, in "
                      "Prism Artifacts.")
        if everything:
            question = i18n.t("Clear the whole history — all {n} runs?"
                              ).format(n=n)
        else:
            question = (i18n.t("Delete this run?") if n == 1
                        else i18n.t("Delete these {n} runs?").format(n=n))
        return QMessageBox.question(
            self, i18n.t("History"),
            question + "\n\n" + i18n.t("This cannot be undone.")
            + " " + kept,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No) == QMessageBox.Yes

    def _delete(self, runs: list, everything: bool = False):
        """Remove some runs, then redraw -- but never from in here.

        The redraw destroys the very widget whose click handler is running.
        This screen already learned that once, three methods up: "a chip row
        that deletes itself from inside its own clicked handler is a crash
        waiting for a slow machine." So the work happens now and the rebuild
        is posted for the next turn of the event loop, the same way
        widgets/input_panel.py refreshes its recent list. Do not "simplify"
        this into a direct call.
        """
        paths = [r.get("path", "") for r in runs if r.get("path")]
        if not paths or not self._confirm_delete(len(paths), everything):
            return
        gone, refused = DATA.delete_runs(self.cfg, paths)
        for path in paths:
            self._picked.discard(path)
        if refused:
            QMessageBox.information(
                self, i18n.t("History"),
                i18n.t("{n} could not be removed. They may be open in "
                       "another program.").format(n=len(refused)))
        QTimer.singleShot(0, self._reload)

    def _delete_picked(self):
        by_path = {r.get("path", ""): r for r in self._runs}
        self._delete([by_path[p] for p in self._picked if p in by_path])

    def _clear_all(self):
        if not self._runs:
            return
        self._delete(list(self._runs), everything=True)

    def _reload(self):
        """Re-read the folder and rebuild. Home reads the same records for
        its activity list and its counters, so it is told to re-read too."""
        self._picked = set()
        self.refresh()
        self.runs_changed.emit()

    def _expand(self, bucket: str):
        self._expanded.add(bucket)
        self._render()


# ── the add-on front doors ──────────────────────────────────────────────────
