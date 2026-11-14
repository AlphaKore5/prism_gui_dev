"""UI port, Home layout pass: structure of the Home page, on the real widgets
rendered offscreen. Hermetic: licensing state patched, fresh HOME."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_HOME = tempfile.mkdtemp(prefix="prism-home-layout-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QScrollArea   # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
_app.setStyleSheet(open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
                   .replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

import festivals                                                   # noqa: E402
from widgets import home_panel as H                                # noqa: E402

FEST_DAY = date(2026, 10, 27)


_real_upcoming = festivals.upcoming


def _upcoming(festival):
    return _real_upcoming(3, today=FEST_DAY) if festival else []


def _top(p, w):
    return w.mapTo(p._host, w.rect().topLeft()).y()


class HomeLayout(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(festivals, "upcoming",
                                    lambda n, today=None: _real_upcoming(n, today=FEST_DAY))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_structure_order(self):
        p = H.HomePanel({})
        p.resize(1366, 768); p.show(); _app.processEvents()
        banner = p.findChild(QFrame, "festivalBanner")
        composer = p._prompt_input
        recent = next(l for l in p.findChildren(QLabel) if l.text() == "Recent activity")
        addons = next(l for l in p.findChildren(QLabel) if l.text() == "Add-ons")
        today = next(l for l in p.findChildren(QLabel) if l.text() == "TODAY")
        demos = next(l for l in p.findChildren(QLabel) if l.text() == "SEE PRISM WORK")
        self.assertLess(_top(p, banner), _top(p, composer))
        self.assertLess(_top(p, composer), _top(p, recent))
        self.assertLess(_top(p, recent), _top(p, today))
        self.assertAlmostEqual(_top(p, recent), _top(p, addons), delta=8)   # side by side
        self.assertAlmostEqual(_top(p, today), _top(p, demos), delta=4)
        tour = p.findChild(H.ShowcaseTourCard)
        self.assertLess(_top(p, tour), _top(p, composer))                    # demo card on the right, from the top
        self.assertGreater(tour.x(), p._host.width() // 2)

    def test_the_whole_page_is_one_scroll_area(self):
        p = H.HomePanel({})
        self.assertEqual(len(p.findChildren(QScrollArea)), 1)

    def test_one_festival_banner_card_with_two_rows_and_working_handlers(self):
        p = H.HomePanel({})
        self.assertEqual(len(p.findChildren(QFrame, "festivalBanner")), 1)
        self.assertEqual(len(p.findChildren(QFrame, "festivalTip")), 2)
        f = _real_upcoming(3, today=FEST_DAY)[0]
        row = p.findChildren(QFrame, "festivalTip")[0]
        from PySide6.QtWidgets import QPushButton
        no = [b for b in row.findChildren(QPushButton) if b.text() == "No"][0]
        no.click()
        self.assertIn((f["name"], "post"), p._festival_dismissed)
        self.assertEqual(len(p.findChildren(QFrame, "festivalTip")), 1)
        row = p.findChildren(QFrame, "festivalTip")[0]
        yes = [b for b in row.findChildren(QPushButton) if b.text() == "Yes"][0]
        yes.click()
        self.assertEqual(p.findChildren(QFrame, "festivalBanner"), [])
        self.assertEqual(p._prompt_input.text(), festivals.reel_prompt(f))

    def test_no_banner_when_no_festival(self):
        with mock.patch.object(festivals, "upcoming", lambda n, today=None: []):
            p = H.HomePanel({})
        self.assertEqual(p.findChildren(QFrame, "festivalBanner"), [])

    def test_empty_register_collapses_to_one_cell_that_still_opens_inquiries(self):
        p = H.HomePanel({})
        tiles = p.findChildren(H._StatTile)
        self.assertEqual(len(tiles), 2)                        # inquiry note + Tasks run this week
        got = []
        p.open_addon.connect(got.append)
        p.open_history.connect(lambda: got.append("history"))
        tiles[0].clicked.emit()
        tiles[1].clicked.emit()
        self.assertEqual(got, ["inquiry", "history"])

    def test_register_present_keeps_all_four_cells(self):
        rows = [{"Customer": "A", "Status": "New"}]
        with mock.patch.object(H.DATA, "register_rows", return_value=rows), \
             mock.patch.object(H.DATA, "needs_you", return_value={"to_quote": 1, "waiting": 2, "due": 0}), \
             mock.patch.object(H.DATA, "month_summary", return_value={"converted": 3, "month": "Nov"}):
            p = H.HomePanel({})
        self.assertEqual(len(p.findChildren(H._StatTile)), 4)

    def test_motto_once(self):
        p = H.HomePanel({})
        quotes = [l for l in p.findChildren(QLabel) if "possibilities" in l.text().lower()]
        self.assertEqual(len(quotes), 1)
        self.assertIsInstance(quotes[0], H._Motto)

    def test_demo_tiles_still_play_their_video(self):
        with mock.patch.object(H, "demo_path", lambda k: "/x/%s.mp4" % k):
            p = H.HomePanel({})
        tiles = p.findChildren(H._DemoTile)
        self.assertEqual(len(tiles), len(H.DEMOS))
        with mock.patch("dialogs.preview_dialog.open_preview") as op:
            tiles[0].clicked.emit()
        self.assertEqual(op.call_args[0][0], "/x/%s.mp4" % H.DEMOS[0][0])

    def test_nothing_clips_at_1366x768_and_first_screen_has_hero_and_tops_of_cards(self):
        p = H.HomePanel({})
        p.resize(1366 - 290, 768 - 100); p.show(); _app.processEvents()
        view_h = p._scroll.viewport().height()
        recent = next(l for l in p.findChildren(QLabel) if l.text() == "Recent activity")
        addons = next(l for l in p.findChildren(QLabel) if l.text() == "Add-ons")
        self.assertLess(_top(p, recent) + recent.height(), view_h)
        self.assertLess(_top(p, addons) + addons.height(), view_h)
        host = p._host
        for w in p.findChildren(QLabel):
            if w.isVisibleTo(p):
                r = w.mapTo(host, w.rect().topLeft())
                self.assertLessEqual(r.x() + w.width(), host.width() + 1, w.text())

    def test_the_banner_adds_at_most_one_compact_block(self):
        a = H.HomePanel({}); a.resize(1076, 668); a.show(); _app.processEvents()
        ra = next(l for l in a.findChildren(QLabel) if l.text() == "Recent activity")
        with mock.patch.object(festivals, "upcoming", lambda n, today=None: []):
            b = H.HomePanel({}); b.resize(1076, 668); b.show(); _app.processEvents()
        rb = next(l for l in b.findChildren(QLabel) if l.text() == "Recent activity")
        self.assertLessEqual(_top(a, ra) - _top(b, rb), 90)


if __name__ == "__main__":
    unittest.main()
