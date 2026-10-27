"""festivals.py -- the Indian festival calendar behind Home's yellow tip.

27 Oct 2026, the owner's ask: nudge a user a few days ahead of an Indian
festival toward making an on-brand Instagram post or reel. This file
covers the data/logic half (widgets/home_panel.py's own
test_home_panel_festival_tip.py covers the UI half): the window math,
the year-boundary lookahead, and that the two prompt templates actually
agree with the tip's own wording about how many days out a festival is.
"""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import festivals                                            # noqa: E402


class TheUpcomingWindow(unittest.TestCase):
    def test_a_festival_three_days_out_is_included(self):
        # Karva Chauth is 29 Oct 2026; 26 Oct + 3 days reaches it exactly.
        names = [f["name"] for f in festivals.upcoming(3, today=date(2026, 10, 26))]
        self.assertIn("Karva Chauth", names)

    def test_a_festival_four_days_out_is_not_included(self):
        names = [f["name"] for f in festivals.upcoming(3, today=date(2026, 10, 25))]
        self.assertNotIn("Karva Chauth", names)

    def test_todays_own_festival_is_included_at_zero_days(self):
        u = festivals.upcoming(3, today=date(2026, 11, 8))
        diwali = next(f for f in u if f["name"] == "Diwali")
        self.assertEqual(diwali["days_until"], 0)

    def test_a_festival_that_already_passed_is_not_included(self):
        names = [f["name"] for f in festivals.upcoming(3, today=date(2026, 11, 9))]
        self.assertNotIn("Diwali", names)

    def test_results_are_sorted_nearest_first(self):
        u = festivals.upcoming(3, today=date(2026, 11, 7))
        self.assertEqual([f["days_until"] for f in u], sorted(f["days_until"] for f in u))

    def test_no_festival_in_the_window_is_an_empty_list_not_an_error(self):
        # A quiet stretch with nothing in CALENDAR within 3 days.
        self.assertEqual(festivals.upcoming(1, today=date(2026, 1, 20)), [])


class TheYearBoundaryIsLookedAhead(unittest.TestCase):
    """A festival on Jan 1 must still be found from Dec 30 -- the window
    must not stop dead at the calendar year's edge. 2027 has no real
    CALENDAR entries yet (added once a year, see the module docstring),
    so this patches in a synthetic one to prove the LOOKAHEAD mechanism
    itself, independent of whether next year's real dates exist yet."""

    def test_a_festival_on_jan_1_next_year_is_found_from_dec_30(self):
        from unittest import mock
        synthetic = {2026: festivals.CALENDAR[2026],
                     2027: [{"name": "Synthetic New Year", "month": 1,
                            "day": 1, "category": festivals.MINOR}]}
        with mock.patch.dict(festivals.CALENDAR, synthetic, clear=True):
            names = [f["name"] for f in
                    festivals.upcoming(3, today=date(2026, 12, 30))]
        self.assertIn("Synthetic New Year", names)

    def test_an_unentered_future_year_is_skipped_not_a_crash(self):
        # 2027 has no CALENDAR entry yet -- must not raise.
        try:
            result = festivals.upcoming(3, today=date(2027, 12, 30))
        except Exception as e:                              # noqa: BLE001
            self.fail(f"upcoming() raised for an unentered year: {e}")
        self.assertEqual(result, [])


class PromptsAgreeWithTheTipsOwnWording(unittest.TestCase):
    """The tip row and the two prompts must never disagree about how many
    days out the same festival is -- both come from when_phrase()."""

    def _festival(self, days_until: int) -> dict:
        return {"name": "Test Festival", "days_until": days_until}

    def test_zero_days_reads_as_today(self):
        self.assertEqual(festivals.when_phrase(self._festival(0)), "today")

    def test_one_day_reads_as_tomorrow(self):
        self.assertEqual(festivals.when_phrase(self._festival(1)), "tomorrow")

    def test_several_days_reads_as_in_n_days(self):
        self.assertEqual(festivals.when_phrase(self._festival(3)), "in 3 days")

    def test_post_prompt_names_the_festival_and_the_same_when_phrase(self):
        f = self._festival(2)
        prompt = festivals.post_prompt(f)
        self.assertIn("Test Festival", prompt)
        self.assertIn(festivals.when_phrase(f), prompt)

    def test_reel_prompt_names_the_festival_and_the_same_when_phrase(self):
        f = self._festival(2)
        prompt = festivals.reel_prompt(f)
        self.assertIn("Test Festival", prompt)
        self.assertIn(festivals.when_phrase(f), prompt)
        self.assertIn("reel", prompt.lower())

    def test_post_and_reel_prompts_are_not_the_same_text(self):
        f = self._festival(2)
        self.assertNotEqual(festivals.post_prompt(f), festivals.reel_prompt(f))


class TheCalendarDataItself(unittest.TestCase):
    def test_every_2026_entry_is_a_real_calendar_date(self):
        for f in festivals.CALENDAR[2026]:
            try:
                date(2026, f["month"], f["day"])
            except ValueError:
                self.fail(f"{f['name']!r} is not a real date: "
                         f"month={f['month']} day={f['day']}")

    def test_every_entry_has_a_category(self):
        for f in festivals.CALENDAR[2026]:
            self.assertIn(f["category"], (festivals.MAJOR, festivals.MINOR))

    def test_no_duplicate_names_in_the_same_year(self):
        names = [f["name"] for f in festivals.CALENDAR[2026]]
        self.assertEqual(len(names), len(set(names)))


if __name__ == "__main__":
    unittest.main()
