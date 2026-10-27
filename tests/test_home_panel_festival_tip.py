"""widgets/home_panel.py's festival tip -- the UI half of festivals.py.

Two yellow rows above the composer (one "make a post", one "make a
reel") for the nearest upcoming festival, each with its own Yes/No;
Yes pre-fills the SAME prompt box "Create a reel" and the other quick
chips already use. tests/test_festivals.py covers the calendar/prompt
logic; this file covers that HomePanel actually wires it up -- shown
only when one is due, each kind answerable independently, dismissal
surviving the wholesale refresh() rebuild, and Yes landing in the box
that is actually on screen afterwards (refresh() replaces
self._prompt_input with a new one every time it runs).
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                 # noqa: E402

_app = QApplication.instance() or QApplication([])

import festivals                                            # noqa: E402
from widgets.home_panel import HomePanel                    # noqa: E402


def _panel() -> HomePanel:
    return HomePanel({})


class ATipShowsOnlyWhenAFestivalIsDue(unittest.TestCase):
    def test_no_tip_when_nothing_is_within_the_window(self):
        p = _panel()
        self.assertIsNone(p._festival_tips(today=date(2026, 1, 30)))

    def test_a_tip_appears_when_a_festival_is_within_three_days(self):
        p = _panel()
        self.assertIsNotNone(p._festival_tips(today=date(2026, 10, 27)))

    def test_only_the_nearest_festivals_tip_rows_are_shown(self):
        """Diwali (8 Nov) and Govardhan Puja (10 Nov) can both land in a
        wide window -- only Diwali's own two tip rows must appear, not a
        second feed stacking every festival in range."""
        p = _panel()
        col = p._festival_tips(today=date(2026, 11, 7))
        self.assertIsNotNone(col)
        # Both rows (post + reel) belong to the SAME, nearest festival --
        # never a mix of two different festivals' rows at once.
        self.assertEqual(col.count(), 2)
        nearest = festivals.upcoming(3, today=date(2026, 11, 7))[0]
        self.assertEqual(nearest["name"], "Diwali")


class EachKindIsIndependentlyAnswerable(unittest.TestCase):
    def _festival(self):
        return festivals.upcoming(3, today=date(2026, 10, 27))[0]

    def test_answering_post_does_not_dismiss_reel(self):
        p = _panel()
        f = self._festival()
        p._on_festival_answer(f, "post", False, "")
        self.assertIn((f["name"], "post"), p._festival_dismissed)
        self.assertNotIn((f["name"], "reel"), p._festival_dismissed)

    def test_both_answered_means_no_more_tip_for_that_festival(self):
        p = _panel()
        f = self._festival()
        p._on_festival_answer(f, "post", False, "")
        p._on_festival_answer(f, "reel", False, "")
        self.assertIsNone(p._festival_tips(today=date(2026, 10, 27)))

    def test_dismissal_survives_a_refresh(self):
        """refresh() rebuilds the whole screen from scratch -- the
        dismissed set must live on the panel itself, not get rebuilt
        away with everything else."""
        p = _panel()
        f = self._festival()
        p._on_festival_answer(f, "post", False, "")
        p.refresh()
        self.assertIn((f["name"], "post"), p._festival_dismissed)


class SayingYesFillsTheBoxThatIsActuallyOnScreen(unittest.TestCase):
    """refresh() replaces self._prompt_input with a brand new QLineEdit
    every time it runs (HomePanel is rebuilt wholesale) -- a prefill
    written to the OLD box before that rebuild would be silently lost
    the instant refresh() ran. 26 Oct 2026's BOQ session hit the mirror
    image of this bug once already (a stale worker reference); same
    class of mistake, different widget."""

    def test_yes_on_post_fills_the_post_prompt(self):
        p = _panel()
        f = festivals.upcoming(3, today=date(2026, 10, 27))[0]
        p._on_festival_answer(f, "post", True, festivals.post_prompt(f))
        self.assertEqual(p._prompt_input.text(), festivals.post_prompt(f))

    def test_yes_on_reel_fills_the_reel_prompt_and_mentions_reel(self):
        p = _panel()
        f = festivals.upcoming(3, today=date(2026, 10, 27))[0]
        p._on_festival_answer(f, "reel", True, festivals.reel_prompt(f))
        self.assertEqual(p._prompt_input.text(), festivals.reel_prompt(f))
        self.assertIn("reel", p._prompt_input.text().lower())

    def test_no_leaves_the_box_empty(self):
        p = _panel()
        f = festivals.upcoming(3, today=date(2026, 10, 27))[0]
        p._on_festival_answer(f, "post", False, "")
        self.assertEqual(p._prompt_input.text(), "")


if __name__ == "__main__":
    unittest.main()
