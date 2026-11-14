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
        self.assertLess(_top(p, banner), _top(p, composer))
        self.assertLess(_top(p, composer), _top(p, recent))
        self.assertAlmostEqual(_top(p, recent), _top(p, addons), delta=8)   # side by side
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

    def test_home_has_no_bottom_strip_and_ends_cleanly_after_the_cards(self):
        p = H.HomePanel({})
        p.resize(1076, 668); p.show(); _app.processEvents()
        texts = {l.text() for l in p.findChildren(QLabel)}
        self.assertNotIn("TODAY", texts)
        self.assertNotIn("SEE PRISM WORK", texts)
        self.assertFalse(hasattr(H, "_StatTile") or hasattr(H, "_DemoTile"))
        bottom = max(w.mapTo(p._host, w.rect().bottomLeft()).y() for w in p.findChildren(H.C.Card)
                     if w.isVisibleTo(p) and w.height() > 100)
        # page content ends within the page padding of the last card: no empty gap
        self.assertLessEqual(p._host.height() - bottom, theme.PAGE_PAD + 40)
        self.assertEqual(len(p.findChildren(QScrollArea)), 1)

    def test_motto_once(self):
        p = H.HomePanel({})
        quotes = [l for l in p.findChildren(QLabel) if "possibilities" in l.text().lower()]
        self.assertEqual(len(quotes), 1)
        self.assertIsInstance(quotes[0], H._Motto)

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
