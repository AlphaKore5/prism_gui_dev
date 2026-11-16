"""The rail's look, as the AlphaKore preview has it: no scrollbar line down the
side, a red square (not a bar) marking where you are, and a grey wash on the
current row."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea           # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
from widgets.sidebar import Sidebar                                # noqa: E402


class TheRailMatchesThePreview(unittest.TestCase):
    def setUp(self):
        self.rail = Sidebar()
        self.rail.resize(260, 700)
        self.rail.show()

    def test_there_is_no_scrollbar_line_down_the_side(self):
        areas = self.rail.findChildren(QScrollArea)
        self.assertTrue(areas)
        self.assertEqual(areas[0].verticalScrollBarPolicy(),
                         Qt.ScrollBarAlwaysOff)

    def test_the_you_are_here_marker_is_a_small_red_square(self):
        pip = self.rail._pip
        self.assertIn(theme.BRAND_RED, pip.styleSheet())
        self.rail._place_pip()
        if pip.isVisible():
            self.assertEqual(pip.width(), pip.height())
            self.assertLessEqual(pip.width(), 8)

    def test_the_current_row_is_a_grey_wash_not_a_white_card(self):
        qss = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "style.qss"), encoding="utf-8").read()
        block = qss.split('#navItem[cur="true"] {', 1)[1].split("}", 1)[0]
        self.assertIn("#EEEDEA", block)
        self.assertNotIn("#ffffff", block)


if __name__ == "__main__":
    unittest.main()
