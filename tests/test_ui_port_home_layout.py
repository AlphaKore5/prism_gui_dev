"""UI port, Home chat-first layout: one centred column (headline, slim festival
notice, composer, meta row, three recent-run cards), on the real widgets
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

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QScrollArea   # noqa: E402

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


def _label(p, text):
    return next(l for l in p.findChildren(QLabel) if l.text() == text)


def _runs(n):
    return [{"title": f"BOQ run {i}", "ok": i != 1, "tools": ["Prism"], "when": "1 hour ago",
             "path": f"/runs/{i}.json"} for i in range(n)]


class ChatFirstHome(unittest.TestCase):
    def setUp(self):
        for patcher in (mock.patch.object(festivals, "upcoming",
                                          lambda n, today=None: _real_upcoming(n, today=FEST_DAY)),
                        mock.patch.object(H.DATA, "recent_runs", lambda cfg, n: _runs(5))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _home(self, w=1076, h=668):
        p = H.HomePanel({})
        p.resize(w, h); p.show(); _app.processEvents()
        return p

    def test_order_is_headline_notice_composer_meta_recent(self):
        p = self._home()
        head = _top(p, _label(p, "Good morning,")) if _label_exists(p, "Good morning,") else _top(p, p.findChildren(QLabel)[0])
        notice = _top(p, p.findChild(QFrame, "festivalBanner"))
        composer = _top(p, p._prompt_input)
        chips = _top(p, p.findChildren(QPushButton, "tryChip")[0])
        recent = _top(p, _label(p, "Recent activity"))
        self.assertLess(notice, composer)
        self.assertLess(composer, chips)
        self.assertLess(chips, recent)

    def test_one_centred_column_no_wider_than_the_stage(self):
        p = self._home(1500, 800)
        c = p._prompt_input.parentWidget()
        while not isinstance(c, H.C.Card):
            c = c.parentWidget()
        w = c.width()
        self.assertLessEqual(w, H.STAGE_W)
        left = c.mapTo(p._host, c.rect().topLeft()).x()
        self.assertAlmostEqual(left, p._host.width() - left - w, delta=2)

    def test_the_composer_is_fully_visible_at_1366x768_and_page_is_one_scroll_area(self):
        p = self._home(1366 - 290, 768 - 100)
        send = p.findChild(QPushButton, "promptSendBtn")
        y = send.mapTo(p._scroll.viewport(), send.rect().bottomLeft()).y()
        self.assertLessEqual(y, p._scroll.viewport().height())
        self.assertEqual(len(p.findChildren(QScrollArea)), 1)
        for w in p.findChildren(QLabel):
            if w.isVisibleTo(p):
                r = w.mapTo(p._host, w.rect().topLeft())
                self.assertLessEqual(r.x() + w.width(), p._host.width() + 1, w.text())

    def test_a_short_window_scrolls_instead_of_clipping(self):
        p = self._home(1076, 420)
        self.assertGreater(p._scroll.verticalScrollBar().maximum(), 0)

    def test_the_column_is_vertically_centred_when_there_is_room(self):
        with mock.patch.object(H.DATA, "recent_runs", lambda cfg, n: []), \
             mock.patch.object(festivals, "upcoming", lambda n, today=None: []):
            p = self._home(1500, 1000)
        top = _top(p, p.findChildren(QLabel)[0])
        last = p.findChild(QPushButton, "tryChip")
        bottom = p._host.height() - (_top(p, last) + last.height())
        self.assertAlmostEqual(top, bottom, delta=140)       # meta links row sits below the chips

    def test_removed_pieces_are_gone(self):
        p = self._home()
        for name in ("ShowcaseTourCard", "_Motto", "_ToolTile", "_WatchDemoButton", "_StatTile", "_DemoTile"):
            self.assertFalse(hasattr(H, name), name)
        texts = {l.text() for l in p.findChildren(QLabel)}
        self.assertFalse([t for t in texts if "possibilities" in t.lower()])
        self.assertNotIn("Add-ons", texts)
        self.assertNotIn("TODAY", texts)

    def test_festival_notice_is_one_slim_card_with_working_rows(self):
        p = self._home()
        self.assertEqual(len(p.findChildren(QFrame, "festivalBanner")), 1)
        self.assertEqual(len(p.findChildren(QFrame, "festivalTip")), 2)
        f = _real_upcoming(3, today=FEST_DAY)[0]
        rows = p.findChildren(QFrame, "festivalTip")
        [b for b in rows[0].findChildren(QPushButton) if b.text() == "No"][0].click()
        self.assertIn((f["name"], "post"), p._festival_dismissed)
        rows = p.findChildren(QFrame, "festivalTip")
        self.assertEqual(len(rows), 1)
        [b for b in rows[0].findChildren(QPushButton) if b.text() == "Yes"][0].click()
        self.assertEqual(p.findChildren(QFrame, "festivalBanner"), [])
        self.assertEqual(p._prompt_input.text(), festivals.reel_prompt(f))

    def test_no_notice_when_no_festival(self):
        with mock.patch.object(festivals, "upcoming", lambda n, today=None: []):
            p = self._home()
        self.assertEqual(p.findChildren(QFrame, "festivalBanner"), [])

    def test_three_latest_runs_as_cards_that_open_their_record(self):
        p = self._home()
        cards = p.findChildren(H._RunCard)
        self.assertEqual(len(cards), 3)
        got = []
        p.open_run_record.connect(got.append)
        cards[2].clicked.emit()
        self.assertEqual(got, ["/runs/2.json"])
        texts = {l.text() for l in cards[1].findChildren(QLabel)}
        self.assertTrue(any("FAILED" in t.upper() for t in texts))
        self.assertTrue(any("Prism · 1 hour ago" in t for t in texts))

    def test_see_all_opens_history(self):
        p = self._home()
        got = []
        p.open_history.connect(lambda: got.append("h"))
        [b for b in p.findChildren(QPushButton) if b.text().startswith("See all")][0].click()
        self.assertEqual(got, ["h"])

    def test_recent_activity_is_hidden_with_no_runs(self):
        with mock.patch.object(H.DATA, "recent_runs", lambda cfg, n: []):
            p = self._home()
        self.assertEqual(p.findChildren(H._RunCard), [])
        self.assertNotIn("Recent activity", {l.text() for l in p.findChildren(QLabel)})

    def test_meta_row_keeps_the_demo_and_the_catalogue_reachable(self):
        p = self._home()
        got = []
        p.open_addon.connect(got.append)
        btns = {b.text(): b for b in p.findChildren(QPushButton)}
        demo = next(b for t, b in btns.items() if "Watch demo video" in t)
        manage = next(b for t, b in btns.items() if t.startswith("Manage add-ons"))
        manage.click()
        self.assertEqual(got, ["catalog"])
        with mock.patch.object(H.HomePanel, "_play_demo") as play:
            q = self._home()
            next(b for b in q.findChildren(QPushButton) if "Watch demo video" in b.text()).click()
        play.assert_called_once()

    def test_the_demo_still_plays_through_open_preview(self):
        p = self._home()
        with mock.patch("os.path.exists", lambda x: True), \
             mock.patch("dialogs.preview_dialog.open_preview") as op:
            p._play_demo()
        self.assertTrue(op.called)

    def test_chips_still_route_and_send_still_submits(self):
        p = self._home()
        got = []
        p.open_addon.connect(got.append)
        for b in p.findChildren(QPushButton, "tryChip"):
            b.click()
        self.assertEqual(got, ["inquiry", "reel", "boq", "artifacts"])
        sent = []
        p.task_submitted.connect(lambda t, a: sent.append(t))
        p._prompt_input.setText("hello")
        p.findChild(QPushButton, "promptSendBtn").click()
        self.assertEqual(sent, ["hello"])


def _label_exists(p, text):
    return any(l.text() == text for l in p.findChildren(QLabel))


if __name__ == "__main__":
    unittest.main()
