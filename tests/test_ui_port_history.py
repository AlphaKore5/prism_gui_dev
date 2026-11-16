"""UI port, stage 2 (History), checked on the real widgets rendered offscreen:
the run row, the mono add-on tag, the filter pills with painted counts, the
search card, the dark selection strip, the day headings and the page header.
Run records are synthetic and handed in directly: nothing here reads or writes
a real runs folder."""
from __future__ import annotations

import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel      # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

import dashboard_data as DATA                                      # noqa: E402
from widgets import controls as C                                  # noqa: E402
from widgets import history_panel as HP                            # noqa: E402
from widgets.panel_base import _RunRow, _Elided                    # noqa: E402

NOW = time.time()
RUNS = [
    {"title": "BOQ — HVAC ductwork", "tools": ["Prism Agent Claude"], "when": "1 hour ago",
     "ok": True, "error": "", "stamp": NOW - 3600, "path": "/x/run_1.json"},
    {"title": "Research overview", "tools": ["Perplexity"], "when": "5 hours ago",
     "ok": False, "error": "no answer", "stamp": NOW - 5 * 3600, "path": "/x/run_2.json"},
    {"title": "Summarize the PDF", "tools": ["ChatGPT"], "when": "yesterday",
     "ok": True, "error": "", "stamp": NOW - 30 * 3600, "path": "/x/run_3.json"},
]


def _panel():
    with mock.patch.object(DATA, "recent_runs", lambda cfg, limit=6: list(RUNS)):
        p = HP.HistoryPanel({})
        p.resize(1060, 640)
        p.show()
        p.refresh()
    return p


class RunRowMatchesThePreview(unittest.TestCase):
    def setUp(self):
        self.row = _RunRow(RUNS[0], "completed", selectable=True, deletable=True)
        self.row.resize(1000, 62)
        self.row.show()

    def test_title_is_regular_weight_and_sub_line_is_muted_12px(self):
        elided = [w for w in self.row.findChildren(_Elided)]
        title = next(w for w in elided if w._full.startswith("HVAC"))
        sub = next(w for w in elided if w._full == "Prism Agent Claude")
        self.assertEqual(title.font().pixelSize(), 14)
        self.assertEqual(title.font().weight(), 400)
        self.assertEqual(sub.font().pixelSize(), 12)
        self.assertIn(theme.MUTE.lower(), sub.styleSheet().lower())

    def test_add_on_tag_is_mono_caps_on_soft_stone_r6(self):
        tag = next(w for w in self.row.findChildren(C.Pill))
        self.assertEqual(tag.text(), "BOQ")
        css = tag.styleSheet().lower()
        self.assertIn("#efeeea", css)
        self.assertIn("border-radius: 6px", css)
        self.assertIn("geist mono", css)

    def test_time_is_mono(self):
        when = next(w for w in self.row.findChildren(_Elided) if w._full == "1 hour ago")
        self.assertIn("geist mono", when.styleSheet().lower())

    def test_row_height_is_the_previews_61px_pitch(self):
        self.assertIn(self.row.sizeHint().height(), range(58, 63))

    def test_checkbox_indicator_is_17px_with_4px_radius(self):
        self.assertIsNotNone(self.row.tick)
        block = QSS.split("QCheckBox::indicator { width: 17px;", 1)[1].split("}", 1)[0]
        self.assertIn("border-radius: 4px", block)
        self.assertIn("#d8d7d2", block)

    def test_bin_button_is_flat_with_muted_glyph(self):
        bins = [b for b in self.row.findChildren(C.QPushButton) if b.objectName() == "iconBtn"]
        self.assertEqual(len(bins), 1)
        self.assertIn("#iconBtn { background: transparent; border: none; border-radius: 10px; }", QSS)

    def test_ticking_still_emits_picked_and_does_not_open(self):
        got, opened = [], []
        self.row.picked.connect(got.append)
        self.row.activated.connect(lambda: opened.append(1))
        self.row.tick.setChecked(True)
        self.assertEqual(got, [True])
        self.assertEqual(opened, [])


class FilterPillsPaintTheirCounts(unittest.TestCase):
    def test_chip_keeps_its_text_and_draws_label_and_count(self):
        chips = C.FilterChips([("all", "All", 9), ("ok", "Completed", 7)], "all")
        chips.show()
        btn = chips._buttons["all"]
        self.assertEqual(btn.text(), "All  9")
        self.assertTrue(btn.isChecked())
        img = btn.grab().toImage()
        # checked chip is ink with white label: some bright pixels on a dark fill
        light = sum(1 for x in range(img.width()) for y in range(img.height())
                    if img.pixelColor(x, y).value() > 200)
        self.assertGreater(light, 20)
        self.assertGreaterEqual(btn.sizeHint().height(), 28)

    def test_container_is_a_translucent_white_pill(self):
        block = QSS.split("/* ── UI port stage 2", 1)[1].split("#filterChips {", 1)[1].split("}", 1)[0]
        self.assertIn("rgba(255, 255, 255, 0.55)", block)

    def test_clicking_a_chip_still_emits_changed(self):
        chips = C.FilterChips([("all", "All", 3), ("failed", "Failed", 1)], "all")
        seen = []
        chips.changed.connect(seen.append)
        chips._buttons["failed"].click()
        self.assertEqual(seen, ["failed"])


class HistoryScreenPieces(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = _panel()

    @classmethod
    def tearDownClass(cls):
        cls.panel.close()

    def test_search_and_count_sit_in_one_card(self):
        self.assertIsInstance(self.panel._search.parentWidget(), C.Card)
        self.assertIs(self.panel._search.parentWidget(), self.panel._count.parentWidget())
        self.assertEqual(self.panel._count.objectName(), "monoMeta")
        self.assertEqual(self.panel._count.text(), "3 of 3 runs")

    def test_search_field_is_the_previews_r10_soft_stone(self):
        self.assertIn("border-radius: 10px", QSS.split("#searchField {")[-1].split("}")[0])

    def test_day_headings_carry_uppercase_mono_counts(self):
        subs = [w for w in self.panel.findChildren(QLabel) if w.objectName() == "sectionSubtitle"]
        self.assertEqual([w.text() for w in subs], ["2 RUNS", "1 RUN"])
        self.assertTrue(all(w.property("mono") for w in subs))

    def test_selection_strip_is_dark_and_appears_when_a_row_is_ticked(self):
        bar = self.panel._bulk
        self.assertEqual(bar.objectName(), "selBar")
        self.assertTrue(bar.isHidden())
        rows = self.panel.findChildren(_RunRow)
        rows[0].tick.setChecked(True)
        self.assertFalse(bar.isHidden())
        self.assertEqual(self.panel._bulk_label.text(), "1 run selected")
        rows[0].tick.setChecked(False)
        self.assertTrue(bar.isHidden())

    def test_filtering_and_search_still_work(self):
        self.panel._chips.set_current("failed")
        self.panel._render()
        self.assertEqual(len(self.panel.findChildren(_RunRow)), 1)
        self.panel._chips.set_current("all")
        self.panel._search.setText("pdf")
        self.assertEqual(len(self.panel.findChildren(_RunRow)), 1)
        self.panel._search.setText("")

    def test_header_card_is_about_86px_tall(self):
        # stage 4b: the header widget is the card itself, flush with the page
        # (preview .phead: 85.8px tall)
        self.assertIn(self.panel.header.height(), range(85, 88))

    def test_clear_all_is_a_light_pill_with_red_text(self):
        btn = next(b for b in self.panel.header.findChildren(C.QPushButton)
                   if b.objectName() == "dangerBtn")
        self.assertIn("#pageHeader QPushButton#dangerBtn", QSS)
        self.assertIn("border-radius: 17px", QSS.split("#pageHeader QPushButton#dangerBtn {")[1].split("}")[0])
        self.assertEqual(btn.text(), "Clear all")


class EmptyHistory(unittest.TestCase):
    def test_empty_state_shows_and_counter_is_zero(self):
        with mock.patch.object(DATA, "recent_runs", lambda cfg, limit=6: []):
            p = HP.HistoryPanel({})
            p.resize(1060, 640)
            p.show()
            p.refresh()
        try:
            self.assertEqual(p._count.text(), "0 of 0 runs")
            self.assertEqual(len(p.findChildren(C.EmptyState)), 1)
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
