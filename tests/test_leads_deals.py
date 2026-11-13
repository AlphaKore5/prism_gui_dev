"""Deals (addons/leads/deals.py + deals_page.py): the store keeps the mockup's two rules, the board shows what the store holds, and the
tab and Due today are wired into the Leads workspace. A temp folder stands in for the member's; nothing is sent, and no real ~/.prism is read."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402

import core_bridge  # noqa: F401,E402
from addons.leads import cockpit as CK                      # noqa: E402
from addons.leads import deals as DL                        # noqa: E402
from addons.leads import deals_page as DP                   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


class TheStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_a_deal_is_kept_and_read_back(self):
        d = DL.add(self.folder, "Panel order", company="Patel Switchgear", value=180000, next_step="Call Thu")
        [back] = DL.list_deals(self.folder)
        self.assertEqual((back.id, back.title, back.company, back.value, back.stage, back.next_step),
                         (d.id, "Panel order", "Patel Switchgear", 180000, "Qualified", "Call Thu"))

    def test_a_deal_needs_a_name(self):
        with self.assertRaises(DL.DealError):
            DL.add(self.folder, "   ")
        self.assertEqual(DL.list_deals(self.folder), [])

    def test_a_deal_moves_through_its_stages(self):
        d = DL.add(self.folder, "Order", value=1000)
        self.assertTrue(DL.move(self.folder, d.id, "Proposal"))
        self.assertFalse(DL.move(self.folder, d.id, "Proposal"))          # already there: nothing changed
        self.assertEqual(DL.list_deals(self.folder)[0].stage, "Proposal")

    def test_won_needs_a_value(self):
        d = DL.add(self.folder, "Order")                                   # no value yet
        with self.assertRaises(DL.DealError):
            DL.move(self.folder, d.id, DL.WON)
        self.assertEqual(DL.list_deals(self.folder)[0].stage, "Qualified")  # refused: it did not move
        self.assertTrue(DL.move(self.folder, d.id, DL.WON, value=240000))
        won = DL.list_deals(self.folder)[0]
        self.assertEqual((won.stage, won.value), (DL.WON, 240000))
        self.assertTrue(won.closed_at)

    def test_lost_needs_a_reason_and_leaves_the_board(self):
        d = DL.add(self.folder, "Order", value=5000)
        with self.assertRaises(DL.DealError):
            DL.move(self.folder, d.id, DL.LOST)
        DL.move(self.folder, d.id, DL.LOST, reason="Price")
        lost = DL.list_deals(self.folder)[0]
        self.assertEqual((lost.stage, lost.lost_reason), (DL.LOST, "Price"))
        self.assertNotIn(lost, [x for col in DL.by_stage([lost]).values() for x in col])

    def test_reopening_a_lost_deal_clears_its_reason(self):
        d = DL.add(self.folder, "Order", value=5000)
        DL.move(self.folder, d.id, DL.LOST, reason="Price")
        DL.move(self.folder, d.id, "Negotiation")
        back = DL.list_deals(self.folder)[0]
        self.assertEqual((back.lost_reason, back.closed_at), ("", ""))

    def test_stalled_counts_open_deals_only_and_from_the_last_move(self):
        d = DL.Deal(id="a", title="x", moved_at="2026-10-25T09:00:00+05:30")
        self.assertEqual(DL.stalled_days(d, date(2026, 11, 3)), 9)
        self.assertEqual(DL.stalled_days(d, date(2026, 10, 30)), 0)        # five days is not stalled
        d.stage = DL.WON
        self.assertEqual(DL.stalled_days(d, date(2026, 11, 3)), 0)

    def test_the_sums(self):
        deals = [DL.Deal(id="1", title="a", value=100, stage="Qualified"),
                 DL.Deal(id="2", title="b", value=50, stage="Proposal"),
                 DL.Deal(id="3", title="c", value=900, stage=DL.WON, closed_at="2026-11-02T10:00:00+05:30"),
                 DL.Deal(id="4", title="d", value=7, stage=DL.WON, closed_at="2026-10-02T10:00:00+05:30")]
        self.assertEqual(DL.open_pipeline(deals), 150)
        self.assertEqual(DL.won_in_month(deals, date(2026, 11, 3)), 900)

    def test_rupees_are_read_the_indian_way(self):
        self.assertEqual(DL.inr(420000), "₹4.2L")
        self.assertEqual(DL.inr(18000000), "₹1.8Cr")
        self.assertEqual(DL.inr(95000), "₹95,000")

    def test_a_damaged_file_is_forgiven_on_read_and_set_aside_on_write(self):
        with open(os.path.join(self.folder, DL.FILE), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(DL.list_deals(self.folder), [])
        DL.add(self.folder, "Order")
        self.assertEqual(len(DL.list_deals(self.folder)), 1)
        self.assertTrue([n for n in os.listdir(self.folder) if "damaged" in n])


class TheBoard(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.page = DP.DealsPage()
        self.page.set_today(date(2026, 11, 3))
        self.page.set_folder(self.folder)

    def _titles(self):
        return sorted(c.deal.title for c in self.page.cards)

    def test_it_opens_empty_and_says_so(self):
        self.assertEqual(self.page.cards, [])
        self.assertIn("No deals yet", self.page.summary.text())

    def test_a_deal_added_shows_on_its_column_and_in_the_summary(self):
        self.page.add(title="Panel order", company="Patel", value=420000, stage="Proposal")
        self.assertEqual(self._titles(), ["Panel order"])
        self.assertIn("₹4.2L", self.page.summary.text())

    def test_a_blank_name_is_refused_with_a_message(self):
        self.assertIsNone(self.page.add(title=""))
        self.assertFalse(self.page.status.isHidden())

    def test_moving_to_won_asks_for_the_value_when_there_is_none(self):
        d = self.page.add(title="Order")
        with mock.patch.object(self.page, "_ask_value", return_value=250000) as ask:
            self.assertTrue(self.page.move(d.id, DL.WON))
        ask.assert_called_once()
        self.assertEqual(DL.list_deals(self.folder)[0].value, 250000)

    def test_a_declined_question_leaves_the_deal_where_it_was(self):
        d = self.page.add(title="Order")
        with mock.patch.object(self.page, "_ask_value", return_value=None):
            self.assertFalse(self.page.move(d.id, DL.WON))
        with mock.patch.object(self.page, "_ask_reason", return_value=None):
            self.assertFalse(self.page.move(d.id, DL.LOST))
        self.assertEqual(DL.list_deals(self.folder)[0].stage, "Qualified")

    def test_lost_asks_why_and_the_card_leaves_the_board(self):
        d = self.page.add(title="Order", value=100)
        with mock.patch.object(self.page, "_ask_reason", return_value="Went quiet"):
            self.assertTrue(self.page.move(d.id, DL.LOST))
        self.assertEqual(self.page.cards, [])
        self.assertEqual(DL.list_deals(self.folder)[0].lost_reason, "Went quiet")

    def test_the_move_menu_moves_the_deal(self):
        d = self.page.add(title="Order", value=100)
        card = self.page.cards[0]
        card.actions_by_stage["Negotiation"].trigger()
        self.assertEqual(DL.list_deals(self.folder)[0].stage, "Negotiation")
        self.assertEqual(self.page.cards[0].deal.id, d.id)

    def test_a_deal_not_moved_for_a_week_wears_the_stalled_tag(self):
        DL.add(self.folder, "Old", value=1)
        with mock.patch.object(DL, "_now", return_value="2026-10-20T09:00:00+05:30"):
            DL.add(self.folder, "Older", value=1)
        self.page.refresh()
        tags = {c.deal.title: [l.text() for l in c.findChildren(type(self.page.status)) if "Stalled" in l.text()]
                for c in self.page.cards}
        self.assertEqual(tags["Older"], ["Stalled 14d"])
        self.assertEqual(tags["Old"], [])

    def test_the_new_deal_button_opens_an_empty_form(self):
        # Clicking passes a "checked" flag; it once landed in the company field and the form crashed (4-Nov, found by the owner running the app).
        seen = {}
        real = DP.NewDealDialog

        def fake(parent=None, company="", title=""):
            seen["args"] = (company, title)
            dlg = real(parent, company=company, title=title)
            dlg.exec = lambda: DP.PrismDialog.Rejected
            return dlg
        with mock.patch.object(DP, "NewDealDialog", fake):
            self.page.new_btn.click()
        self.assertEqual(seen["args"], ("", ""))

    def test_pressing_add_deal_adds_the_deal(self):
        # The click handler compared exec()'s answer with `dlg.Accepted` — an INSTANCE attribute PySide 6.11 does not have — so pressing "Add
        # deal" raised AttributeError and nothing was saved (4-Nov, found by the owner running the app). The window is never shown here:
        # exec is answered as if the owner pressed the primary button.
        real = DP.NewDealDialog

        def fake(parent=None, company="", title=""):
            dlg = real(parent, company=company, title=title)
            dlg.title_edit.setText("Panel order")
            dlg.company_edit.setText("Patel Switchgear")
            dlg.value_edit.setValue(250000)
            dlg.exec = lambda: DP.PrismDialog.Accepted
            return dlg
        with mock.patch.object(DP, "NewDealDialog", fake):
            self.page.new_btn.click()
        [deal] = DL.list_deals(self.folder)
        self.assertEqual((deal.title, deal.company, deal.value), ("Panel order", "Patel Switchgear", 250000))
        self.assertEqual([c.deal.id for c in self.page.cards], [deal.id])

    def test_no_stray_window_opens_while_it_redraws(self):
        self.page.show()
        for i in range(3):
            self.page.add(title=f"Deal {i}", value=10)
        tops = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w is not self.page]
        self.assertEqual(tops, [])
        self.page.hide()


class TheLinkToAPerson(unittest.TestCase):
    def setUp(self):
        from prospector.models import Lead
        self.folder = tempfile.mkdtemp()
        self.lead = Lead(name="Ramesh Patel", company="Patel Switchgear", email="ramesh@patel.example")

    def test_a_deal_tied_to_a_person_is_found_by_their_keys(self):
        from prospector.identity import keys_of
        DL.add(self.folder, "Panel order", person="Ramesh Patel", keys=sorted(keys_of(self.lead)))
        DL.add(self.folder, "Unrelated")
        self.assertEqual([d.title for d in DL.linked(self.folder, self.lead)], ["Panel order"])

    def test_the_drawer_shows_the_deal_or_offers_to_create_one(self):
        from addons.leads import person as PP
        from prospector.models import Dossier
        panel = PP.PersonPanel()
        asked = []
        panel.dealRequested.connect(asked.append)
        row = Dossier(lead=self.lead, verdict="", generated_at="", status="ok")
        panel.show_person(PP.PersonView(row=row))
        self.assertEqual(panel.deal_lines, [])
        panel.deal_btn.click()
        self.assertEqual(asked, [self.lead])
        deal = DL.Deal(id="x", title="Panel order", stage="Proposal", value=420000, next_step="Call Thu")
        panel.show_person(PP.PersonView(row=row, deals=[deal]))
        self.assertEqual([l.text() for l in panel.deal_lines], ["Panel order · Proposal · ₹4.2L"])


class TheStalledDealsOnDueToday(unittest.TestCase):
    def test_a_stalled_open_deal_is_listed_and_a_moving_one_is_not(self):
        from addons.leads import due_today as DT
        old = DL.Deal(id="a", title="Mehta Drives", company="Mehta", next_step="call about GST", moved_at="2026-10-25T09:00:00+05:30")
        fresh = DL.Deal(id="b", title="Fresh", moved_at="2026-11-02T09:00:00+05:30")
        won = DL.Deal(id="c", title="Done", stage=DL.WON, moved_at="2026-09-01T09:00:00+05:30")
        [item] = DT.due_items([], date(2026, 11, 3), deals=[old, fresh, won])
        self.assertEqual((item.kind, item.name, item.pill), ("deal", "Mehta Drives", "Stalled 9d"))
        self.assertIn("call about GST", item.subline)

    def test_open_deal_reaches_the_workspace_and_selects_the_board(self):
        folder = tempfile.mkdtemp()
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        w.set_deals_folder(folder)
        with mock.patch.object(DL, "_now", return_value="2026-01-01T09:00:00+05:30"):
            DL.add(folder, "Old deal", value=5)
        w.set_due_contacts([])
        self.assertEqual(w.due.count(), 1)
        self.assertEqual(w._tabs[8].text(), "Due today  1")
        w.due.list.rows()[0].buttons[0].click()
        self.assertIs(w._stack.currentWidget(), w.deals)


class TheWorkspace(unittest.TestCase):
    def setUp(self):
        self.w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())

    def test_deals_and_due_today_follow_the_original_seven_tabs(self):
        # Stats was appended after them, so they are no longer the last two; their places did not move.
        self.assertEqual([b.text().split("  ")[0] for b in self.w._tabs][7:9], ["Deals", "Due today"])
        self.assertIs(self.w._stack.widget(7), self.w.deals)
        self.assertIs(self.w._stack.widget(8), self.w.due)

    def test_the_due_tab_says_how_many_wait(self):
        from addons.leads import contacts as CT
        from prospector.models import Lead
        c = CT.Contact(lead=Lead(name="Ramesh", company="Patel"), saved_at="2026-10-01T10:00:00+05:30")
        c.tasks = [{"id": "t", "at": "2026-10-01", "text": "Call", "due": "2000-01-01", "done": False}]
        self.w.set_due_contacts([c])
        self.assertEqual(self.w._tabs[8].text(), "Due today  1")
        self.w.set_due_contacts([])
        self.assertEqual(self.w._tabs[8].text(), "Due today")

    def test_due_rows_reach_the_workspace_signals(self):
        from addons.leads import contacts as CT
        from prospector.models import Lead
        c = CT.Contact(lead=Lead(name="Ramesh", company="Patel"), saved_at="2026-10-01T10:00:00+05:30")
        c.tasks = [{"id": "t", "at": "2026-10-01", "text": "Call", "due": "2000-01-01", "done": False}]
        self.w.set_due_contacts([c])
        opened, done = [], []
        self.w.dueOpenRequested.connect(opened.append)
        self.w.dueTaskDoneRequested.connect(lambda lead, tid, flag: done.append((lead.name, tid, flag)))
        row = self.w.due.list.rows()[0]
        row.buttons[0].click()
        row.buttons[1].click()
        self.assertEqual([l.name for l in opened], ["Ramesh"])
        self.assertEqual(done, [("Ramesh", "t", True)])


if __name__ == "__main__":
    unittest.main()
