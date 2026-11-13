"""Home's "Today" insights and its demo-video row.

Two rules, both from the AlphaKore redesign:

  * Nothing on the dashboard is invented. With no inquiry register the three
    inquiry figures read as a dash and say why; they never show a made-up zero
    or a plausible number. (dashboard_data.py's own contract.)
  * A demo tile is only live when its video exists. Until it is recorded it is
    switched off and says why, so no button on Home is dead without a reason.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel           # noqa: E402

_app = QApplication.instance() or QApplication([])

from widgets.home_panel import (                              # noqa: E402
    DEMOS, HomePanel, _DemoTile, _StatTile, demo_path,
)


def _texts(widget) -> list[str]:
    return [lb.text() for lb in widget.findChildren(QLabel) if lb.text()]


class TodayInsights(unittest.TestCase):
    def setUp(self):
        self.panel = HomePanel({})
        self.tiles = self.panel.findChildren(_StatTile)

    def test_four_insight_tiles(self):
        self.assertEqual(len(self.tiles), 4)

    def test_no_register_shows_a_dash_and_says_why(self):
        # The first three read off the inquiry register; this panel has none.
        for tile in self.tiles[:3]:
            texts = _texts(tile)
            self.assertEqual(texts[0], "–", texts)
            self.assertIn("No inquiry register yet", texts)

    def test_every_tile_is_a_way_in(self):
        for tile in self.tiles:
            self.assertTrue(tile.hasFocus() or tile.focusPolicy() != 0)


class DemoVideos(unittest.TestCase):
    def setUp(self):
        self.tiles = HomePanel({}).findChildren(_DemoTile)

    def test_one_tile_per_feature(self):
        self.assertEqual(len(self.tiles), len(DEMOS))

    def test_a_tile_is_live_exactly_when_its_video_exists(self):
        for (key, *_), tile in zip(DEMOS, self.tiles):
            has = bool(demo_path(key))
            self.assertEqual(tile.isEnabled(), has, key)
            if not has:
                self.assertTrue(tile.toolTip(), f"{key}: off but gives no reason")

    def test_missing_demo_resolves_to_nothing(self):
        self.assertEqual(demo_path("no-such-feature"), "")


if __name__ == "__main__":
    unittest.main()
