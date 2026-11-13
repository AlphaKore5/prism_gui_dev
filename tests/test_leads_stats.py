"""Stats (addons/leads/stats.py + stats_page.py): every figure is counted from stored history, and a figure with nothing behind it reads "—",
never a confident zero. Plain contacts and deals stand in for the member's; no real ~/.prism is read."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402

import core_bridge  # noqa: F401,E402
from addons.leads import cockpit as CK                      # noqa: E402
from addons.leads import contacts as CT                     # noqa: E402
from addons.leads import deals as DL                        # noqa: E402
from addons.leads import stats as ST                        # noqa: E402
from addons.leads import stats_page as SP                   # noqa: E402
from prospector.models import Lead                          # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
TODAY = date(2026, 11, 4)


def _contact(name, stage="Approaching", sent="2026-10-28", replied="", interested=""):
    c = CT.Contact(lead=Lead(name=name, company="Co"), saved_at="2026-10-01T10:00:00+05:30", stage=stage)
    if sent:
        c.history.append({"at": f"{sent}T10:00:00+05:30", "kind": "sent", "text": "Hello"})
    if replied:
        c.history.append({"at": f"{replied}T10:00:00+05:30", "kind": "stage", "text": "Approaching → Replied"})
    if interested:
        c.history.append({"at": f"{interested}T10:00:00+05:30", "kind": "stage", "text": "Replied → Interested"})
    return c


def _deal(stage=DL.STAGES[0], value=100, created="2026-10-20", closed="", reason=""):
    return DL.Deal(id=os.urandom(3).hex(), title="d", value=value, stage=stage, created_at=f"{created}T09:00:00+05:30",
                   moved_at=f"{created}T09:00:00+05:30", closed_at=f"{closed}T09:00:00+05:30" if closed else "", lost_reason=reason)


class TheCounts(unittest.TestCase):
    def test_nothing_stored_is_nothing_counted_not_zero_rates(self):
        s = ST.compute([], [], TODAY)
        self.assertTrue(s.is_empty())
        self.assertIsNone(s.reply_rate)
        self.assertIsNone(s.win_rate)
        self.assertIsNone(s.median_reply_days)

    def test_reply_rate_is_replies_over_people_contacted(self):
        people = [_contact("a", "Replied", replied="2026-10-30"), _contact("b"), _contact("c"), _contact("d")]
        s = ST.compute(people, [], TODAY)
        self.assertEqual((s.contacted, s.replied), (4, 1))
        self.assertAlmostEqual(s.reply_rate, 0.25)

    def test_someone_never_sent_to_is_not_contacted(self):
        s = ST.compute([_contact("a", sent="")], [], TODAY)
        self.assertEqual(s.contacted, 0)

    def test_a_send_older_than_the_window_is_not_counted(self):
        s = ST.compute([_contact("a", sent="2026-08-01")], [], TODAY)
        self.assertEqual(s.contacted, 0)

    def test_interested_counts_those_who_reached_it(self):
        people = [_contact("a", "Interested", replied="2026-10-30", interested="2026-11-01"), _contact("b", "Replied", replied="2026-10-31")]
        s = ST.compute(people, [], TODAY)
        self.assertEqual((s.replied, s.interested), (2, 1))

    def test_median_time_to_reply_is_from_first_send_to_first_reply(self):
        people = [_contact("a", "Replied", sent="2026-10-28", replied="2026-10-29"),     # 1 day
                  _contact("b", "Replied", sent="2026-10-25", replied="2026-10-28"),     # 3 days
                  _contact("c", "Replied", sent="2026-10-20", replied="2026-10-30")]     # 10 days
        self.assertEqual(ST.compute(people, [], TODAY).median_reply_days, 3.0)

    def test_win_rate_counts_only_deals_closed_in_the_window(self):
        deals = [_deal(DL.WON, closed="2026-11-02"), _deal(DL.WON, closed="2026-10-30"), _deal(DL.LOST, closed="2026-11-01", reason="Price"),
                 _deal(DL.LOST, closed="2026-07-01", reason="Old")]
        s = ST.compute([], deals, TODAY)
        self.assertEqual((s.won, s.lost), (2, 1))
        self.assertAlmostEqual(s.win_rate, 2 / 3)
        self.assertEqual(s.lost_reasons, {"Price": 1})

    def test_open_pipeline_is_only_open_deals(self):
        deals = [_deal(DL.STAGES[0], 100), _deal(DL.STAGES[1], 50), _deal(DL.WON, 900, closed="2026-11-01")]
        self.assertEqual(ST.compute([], deals, TODAY).open_pipeline, 150)

    def test_deals_started_in_the_window(self):
        deals = [_deal(created="2026-10-20"), _deal(created="2026-06-01")]
        self.assertEqual(ST.compute([], deals, TODAY).deals, 1)


class ThePage(unittest.TestCase):
    def setUp(self):
        self.page = SP.StatsPage()
        self.page.set_today(TODAY)

    def test_an_empty_page_says_so(self):
        self.assertIn("Nothing to count", self.page.summary.text())
        self.assertEqual(self.page.tiles, {})

    def test_the_figures_are_drawn_from_the_data(self):
        people = [_contact("a", "Replied", replied="2026-10-30"), _contact("b")]
        self.page.set_data(people, [_deal(DL.STAGES[1], 420000)])
        self.assertEqual(self.page.tiles["reply_rate"].text(), "50%")
        self.assertEqual(self.page.tiles["pipeline"].text(), "₹4.2L")
        self.assertEqual(self.page.tiles["win_rate"].text(), "—")          # nothing closed: no rate, not 0%

    def test_a_redraw_leaves_no_stray_window(self):
        self.page.show()
        for _ in range(3):
            self.page.set_data([_contact("a")], [])
        tops = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w is not self.page]
        self.assertEqual(tops, [])
        self.page.hide()


class TheWorkspace(unittest.TestCase):
    def test_stats_is_the_last_tab(self):
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        self.assertEqual(w._tabs[-1].text(), "Stats")
        self.assertIs(w._stack.widget(9), w.stats)

    def test_it_reads_the_contacts_and_the_deals_folder(self):
        folder = tempfile.mkdtemp()
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        w.set_deals_folder(folder)
        DL.add(folder, "Panel order", value=250000)
        w.set_stats_contacts([])
        self.assertEqual(w.stats.stats.open_pipeline, 250000)


if __name__ == "__main__":
    unittest.main()
