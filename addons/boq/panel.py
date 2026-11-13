"""The BOQ and BOM front doors.

Two screens, one file: BOM is BOQ's dialog in a different mode, so the
two front doors differ only in their copy and their run prefix.
"""
from __future__ import annotations


from PySide6.QtWidgets import QHBoxLayout, QWidget

import i18n
import theme
from addons.boq import history
from widgets import controls as C
from widgets.panel_base import (
    AddonFrontDoor,
)


class BoqPanel(AddonFrontDoor):
    TITLE = "BOQ"
    BLURB = ("Quantities off a CAD drawing, or a written spec. Prism counts "
             "and measures — you price it.")
    ICON = "file"
    HEADLINE = "Attach a drawing or spec to begin"
    DETAIL = "DXF, PDF, or a written list of what's needed."
    ACTION = "Attach a file"
    KIND = "boq"

    STEPS = [
        ("paperclip", "Attach the drawing",
         "Upload a CAD drawing (DXF/PDF) or enter a written description."),
        ("chart", "Prism measures it",
         "Counts, lengths, and areas are calculated automatically."),
        ("file", "Attach a sample BOQ too",
         "Upload your past BOQ (Excel/Word) to match your company's format."),
        ("grid", "Price & export",
         "Generates itemized quantities and priced Excel sheets with live formulas."),
    ]

    PLACEHOLDERS = [
        ("BOQ for CCTV, cabling and fibre for this site",
         "Measures your CAD drawing and matches formatting to your past BOQs."),
        ("Materials to build one 36x24 jaw crusher, 100 TPH",
         "Generates an itemized Bill of Quantities directly from your prompt."),
    ]

    def build(self):
        self.HUE = theme.ACCENT
        self._col.addWidget(self._counter_row())
        super().build()

    # item 70 (12 Nov 2026): "a small BOQ counter... how many were made
    # in a day, a month, a year... and token utilization for each" --
    # one small line, read off the same run files History already reads
    # (addons/boq/history.py's counts_by_period()), not a new counter of
    # its own. Placed before "Recent runs" so it is the first thing on
    # the screen without pushing anything else down by more than one
    # line.
    def _counter_row(self):
        counts = history.counts_by_period()

        def part(period: str, word: str) -> str:
            c = counts[period]
            text = i18n.t("{word}: {boqs} BOQ{plural} · {tokens} tokens")
            text = text.replace("{word}", word)
            text = text.replace("{boqs}", str(c["boqs"]))
            text = text.replace("{plural}", "" if c["boqs"] == 1 else "s")
            text = text.replace("{tokens}", history.format_count(c["tokens"]))
            return text

        line = "   ".join([
            part("day", i18n.t("Today")),
            part("month", i18n.t("This month")),
            part("year", i18n.t("This year")),
        ])

        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(theme.SPACE_2)
        box.addWidget(C.label(line, level="META", size=12,
                             colour=theme.NEUTRAL[600]), stretch=1)
        # item 73 (12 Nov 2026): "start the BOQ count from 0... so i can
        # see how i am spending on each of the BOQ" -- a real action the
        # owner can reach again later, not a one-off only reachable by
        # editing a file: every run before this click stops counting
        # toward the figures above (they keep existing for History,
        # untouched), so a fresh baseline is never more than one click
        # away whenever an old test session's own runs would otherwise
        # skew "tokens per BOQ" going forward.
        box.addWidget(C.button(i18n.t("Reset"), "secondary", small=True,
                               on_click=self._reset_counter))
        return row

    def _reset_counter(self):
        history.reset_counter()
        self.refresh()

    def tool_roles(self):
        """Mirrors BoqDialog._run() exactly — writer, researcher, interpreter."""
        agents = self._agents()
        writer = next((agents[s] for s in ("content", "brains")
                       if agents.get(s)), "")
        return [
            ("pencil", "Writes the BOQ up",
             "Your Writing tool, or Reasoning if you have not set one.",
             writer),
            ("book", "Checks the trade standard",
             "Your Research tool, falling back to Reasoning — used when you "
             "leave “derive from standards” switched on.",
             agents.get("research") or agents.get("brains") or ""),
            ("image", "Reads a drawing screenshot",
             "ChatGPT specifically, and only when you attach an image for it "
             "to read the legend and scope off.",
             "ChatGPT"),
        ]
