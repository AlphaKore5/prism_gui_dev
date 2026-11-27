"""The Sales cost guard, on the app's side: mobile numbers only when asked, the month's promise
counted and said in plain words, and the bars.

  · a search, a verify or an e-mail find never asks for a mobile number: only the Get mobile
    number actions do, and only for the people picked;
  · the bulk button says WHY when it is off (nothing ticked, nobody who can be looked up, the
    month's 100 used) and its confirm says how many of the 100 it will use;
  · the server's refusal (quota_numbers / spend_cap) stops a batch and shows the server's own
    sentence; the batch is never longer than what is left;
  · the usage line "Emails 120/200, Numbers 40/100, resets 1 Dec" with a percent bar each.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtWidgets import QApplication                         # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from addons.leads import credits_page as CP                        # noqa: E402
from addons.leads.month_usage import MonthUsage, percent, usage_line   # noqa: E402
from prospector import gateway as G                                # noqa: E402
from prospector import mobiles as M                                # noqa: E402

import test_leads_mobiles_ui as TM                                 # noqa: E402
from test_leads_cockpit import _Workbench                          # noqa: E402
from test_leads_credit_pool import FakeServer                      # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

ROOT = Path(__file__).resolve().parent.parent


def month(emails=120, numbers=40, capped=False, guard=True):
    return {"guard": guard, "emails_used": emails, "emails_limit": 200, "numbers_used": numbers,
            "numbers_limit": 100, "resets_on": "2026-12-01", "resets_label": "1 Dec",
            "spend_cap_reached": capped}


class MonthServer(FakeServer):
    """The licence server's status now carries this month's counts; a mobile lookup finds a number."""

    def __init__(self, month_=None, **kw):
        super().__init__(**kw)
        self.month = month_
        self.refuse = None

    def __call__(self, path, body):
        op = path.rsplit("/", 1)[-1]
        if op == "status":
            self.calls.append((op, body))
            out = {"balance": self.balance, "rates": {"phone_mobile": {"credits": 4, "label": "Mobile"}},
                   "ready": {"mobile": True}}
            if self.month is not None:
                out["month"] = self.month
            return out
        if op == "mobile-find" and self.refuse:
            self.calls.append((op, body))
            raise self.refuse
        if op == "mobile-find":
            self.calls.append((op, body))
            return {"result": {"phone": TM.MOBILE, "kind": "mobile", "provider": "ai_ark"},
                    "charged": 4, "balance": self.balance}
        return super().__call__(path, body)


def limit_error(reason="quota_numbers"):
    return G.LimitReached("LEADS_LIMIT", "You have used all 100 mobile numbers included this month. "
                          "They come back on 1 Dec. Nothing was charged.", {"reason": reason})


class _Pooled(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.object(G, "_auth_body", lambda **e: {"license_id": "L", "device_fp": "D", **e})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(G.set_transport, None)
        self.addCleanup(G.forget)

    def serve(self, **kw):
        server = MonthServer(**kw)
        G.set_transport(server)
        return server


@pytest.mark.pooled
class TheGatewayKnowsTheMonth(_Pooled):
    def test_status_carries_the_month_and_says_how_many_numbers_are_left(self):
        self.serve(month_=month(numbers=40))
        G.status()
        self.assertEqual(G.month()["numbers_used"], 40)
        self.assertEqual(G.mobiles_left(), 60)
        self.assertEqual(G.mobiles_why_not(), "")

    def test_no_month_or_no_enforcement_means_no_limit_is_known(self):
        self.serve()                                            # an older server: no "month" at all
        G.status()
        self.assertEqual((G.month(), G.mobiles_left(), G.mobiles_why_not()), (None, None, ""))
        self.serve(month_=month(guard=False, numbers=100))
        G.status()
        self.assertEqual((G.month(), G.mobiles_left()), (None, None))

    def test_a_used_up_month_says_why_and_when_it_resets(self):
        self.serve(month_=month(numbers=100))
        G.status()
        self.assertEqual(G.mobiles_left(), 0)
        self.assertEqual(G.mobiles_why_not(),
                         "You have used all 100 mobile numbers included this month. They come back on 1 Dec.")

    def test_a_reached_spend_cap_stops_numbers_too_and_says_so(self):
        self.serve(month_=month(numbers=10, capped=True))
        G.status()
        self.assertEqual(G.mobiles_left(), 0)
        self.assertIn("limit for paid lookups", G.mobiles_why_not())
        self.assertIn("1 Dec", G.mobiles_why_not())

    def test_the_servers_refusal_is_remembered_until_the_next_run_or_status(self):
        server = self.serve(month_=month())
        server.refuse = limit_error("quota_numbers")
        with self.assertRaises(G.LimitReached) as ctx:
            G.find_mobile("Asha", "Rao", "acme.com", why=None) or G._call("mobile-find", first_name="A")
        self.assertEqual(ctx.exception.reason, "quota_numbers")
        self.assertIn("Nothing was charged", G.limited())
        G.reset()
        self.assertEqual(G.limited(), "")


@pytest.mark.pooled
class TheBatchRespectsTheMonth(_Pooled):
    def leads(self, n):
        return [TM.lead(name=f"P{i} Singh", company=f"Co {i}", domain=f"co{i}.example") for i in range(n)]

    def test_a_batch_is_never_longer_than_what_is_left(self):
        server = self.serve(month_=month(numbers=98))
        G.status()
        counts = M.find(self.leads(5))
        self.assertEqual(server.ops().count("mobile-find"), 2)
        self.assertEqual((counts["asked"], counts["found"]), (2, 2))

    def test_a_refusal_stops_the_batch_and_the_servers_sentence_is_kept(self):
        server = self.serve(month_=month(numbers=10))
        server.refuse = limit_error("spend_cap")
        G.status()
        counts = M.find(self.leads(M.LIMIT))
        self.assertLessEqual(server.ops().count("mobile-find"), M.WORKERS)   # in flight at once, no more
        self.assertEqual(counts["found"], 0)
        self.assertTrue(any("Nothing was charged" in w for w in counts["why"]))

    def test_without_a_known_limit_nothing_is_trimmed(self):
        server = self.serve()
        G.status()
        M.find(self.leads(4))
        self.assertEqual(server.ops().count("mobile-find"), 4)


@pytest.mark.pooled
class MobilesOnlyWhenAsked(_Pooled):
    def test_no_search_enrichment_or_run_path_ever_asks_for_a_mobile(self):
        """Every place that can start a mobile lookup, found by reading the source: the person
        panel and the bulk button reach it through the workbench's _find_mobiles, nothing else."""
        hits = []
        for folder in ("addons", "prospector", "core_bridge.py", "workspace.py", "main_window.py"):
            path = ROOT / folder
            for f in ([path] if path.is_file() else path.rglob("*.py")):
                text = f.read_text(encoding="utf-8")
                for m in re.finditer(r"(?<!class )\b(mobiles\.find\(|mobiles\.find_direct\(|gateway\.find_mobile\(|"
                                     r"LeadsMobileWorker\()", text):
                    hits.append((f.relative_to(ROOT).as_posix(), m.group(1)))
        allowed = {("addons/leads/workers.py", "mobiles.find("),
                   ("addons/leads/workbench.py", "LeadsMobileWorker("),
                   ("prospector/mobiles.py", "gateway.find_mobile(")}
        self.assertTrue(set(hits) <= allowed, sorted(set(hits) - allowed))
        self.assertTrue(allowed <= set(hits), sorted(allowed - set(hits)))


class _Screen(_Workbench):
    _people = TM.FindMobilesOnTheScreen._people
    _tick = TM.FindMobilesOnTheScreen._tick

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(self._WB.LeadsWorkbench, "_refresh_credits", lambda _s: None),
                        mock.patch.object(G, "ready", lambda op: True),
                        mock.patch.object(G, "_auth_body", lambda **e: {"license_id": "L", "device_fp": "D", **e})):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(G.set_transport, None)
        self.addCleanup(G.forget)
        TM._FakeMobileWorker.made = []
        orig = self._WB.LeadsMobileWorker
        self._WB.LeadsMobileWorker = TM._FakeMobileWorker
        self.addCleanup(setattr, self._WB, "LeadsMobileWorker", orig)

    def bench(self, month_=None, balance=50):
        wb = self._WB.LeadsWorkbench({})
        G.set_transport(MonthServer(month_=month_, balance=balance))
        wb._on_credits(G.status())
        return wb



@pytest.mark.pooled
class TheScreen(_Screen):
    def test_a_search_result_asks_for_no_mobile(self):
        server = MonthServer(month_=month(), balance=50)
        G.set_transport(server)
        wb = self._WB.LeadsWorkbench({})
        wb._on_credits(G.status())
        self._people(wb, 5)                                     # a finished run lands on the screen
        self.assertEqual([op for op in server.ops() if "mobile" in op], [])
        self.assertEqual(TM._FakeMobileWorker.made, [])

    def test_the_bulk_button_says_why_it_is_off(self):
        wb = self.bench(month())
        ck = wb._cockpit.leads
        leads = self._people(wb, 3)
        ck._refresh_bulk()
        self.assertFalse(ck._b_mobiles.isEnabled())
        self.assertEqual(ck._b_mobiles.toolTip(), "Tick the people you want a mobile number for.")
        self._tick(wb, leads)
        self.assertTrue(ck._b_mobiles.isEnabled())
        self.assertIn("60 left this month", ck._b_mobiles.toolTip())
        for l in leads:
            TM.M.apply(l, TM.MOBILE)
        ck._refresh_bulk()
        self.assertFalse(ck._b_mobiles.isEnabled())
        self.assertIn("already has a mobile number", ck._b_mobiles.toolTip())

    def test_with_the_months_100_used_the_button_is_off_and_says_when_it_returns(self):
        wb = self.bench(month(numbers=100))
        ck = wb._cockpit.leads
        leads = self._people(wb, 3)
        self._tick(wb, leads)
        self.assertFalse(ck._b_mobiles.isEnabled())
        self.assertEqual(ck._b_mobiles.toolTip(),
                         "You have used all 100 mobile numbers included this month. They come back on 1 Dec.")
        wb._find_mobiles(ck.selected())                         # even if something calls it directly
        self.assertEqual(TM._FakeMobileWorker.made, [])
        self.assertIn("come back on 1 Dec", wb._status.text())

    def test_the_button_asks_through_the_workbench_for_the_people_ticked(self):
        wb = self.bench(month())
        ck = wb._cockpit.leads
        leads = self._people(wb, 3)
        self._tick(wb, leads)
        asked = []
        wb._find_mobiles = lambda dossiers: asked.append([d.lead.name for d in dossiers])
        wb._cockpit.mobilesRequested.disconnect()
        wb._cockpit.mobilesRequested.connect(wb._find_mobiles)
        ck._b_mobiles.click()
        self.assertEqual(sorted(asked[0]), ["P0 Singh", "P1 Singh", "P2 Singh"])

    def test_the_confirm_says_how_many_of_the_100_it_will_use(self):
        wb = self.bench(month(numbers=40))
        said = []
        wb._confirm_pool = lambda title, lines: (said.append(lines), False)[1]
        leads = self._people(wb, 3)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        [lines] = said
        self.assertIn("This uses up to 3 of your 100 mobile numbers this month (60 left).", lines[1])
        self.assertIn("Only numbers found count", lines[1])

    def test_the_press_is_cut_to_what_is_left_of_the_month(self):
        wb = self.bench(month(numbers=98))
        asked = []
        wb._confirm_mobiles = lambda n: (asked.append(n), True)[1]
        leads = self._people(wb, 5)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        self.assertEqual(asked, [2])
        [worker] = TM._FakeMobileWorker.made
        self.assertEqual(len(worker.leads), 2)

    def test_the_panel_calls_it_get_mobile_number(self):
        from addons.leads import person as PP
        panel = TM.ThePanelSaysWhatTheMobileIs.panel(TM.ThePanelSaysWhatTheMobileIs("test_someone_who_can_be_looked_up_is_offered_it_and_it_is_asked_for"),
                                                     TM.lead())
        texts = [b.text() for b in panel.findChildren(PP.QPushButton)]
        self.assertIn("Get mobile number…", texts)


@pytest.mark.pooled
class EveryLeadHasItsOwnAction(_Screen):
    def rows(self, wb):
        return wb._cockpit.leads._grid.rows()

    def test_each_listed_lead_offers_get_mobile_number_and_asks_for_that_person_only(self):
        wb = self.bench(month())
        self._people(wb, 3)
        asked = []
        wb._cockpit.mobilesRequested.disconnect()
        wb._cockpit.mobilesRequested.connect(lambda ds: asked.append([d.lead.name for d in ds]))
        rows = self.rows(wb)
        self.assertEqual(len(rows), 3)
        for row in rows:
            self.assertEqual(row.mobile_button.text(), "Get mobile number")
            self.assertTrue(row.mobile_button.isEnabled())
            self.assertIn("60 left this month", row.mobile_button.toolTip())
        rows[1].mobile_button.click()
        self.assertEqual(len(asked), 1)
        self.assertEqual(len(asked[0]), 1)

    def test_with_the_quota_used_the_row_action_is_off_with_the_reason(self):
        wb = self.bench(month(numbers=100))
        self._people(wb, 2)
        for row in self.rows(wb):
            self.assertFalse(row.mobile_button.isEnabled())
            self.assertIn("come back on 1 Dec", row.mobile_button.toolTip())

    def test_rows_already_drawn_go_off_when_the_month_runs_out(self):
        wb = self.bench(month(numbers=99))
        self._people(wb, 2)
        self.assertTrue(self.rows(wb)[0].mobile_button.isEnabled())
        G.set_transport(MonthServer(month_=month(numbers=100)))
        wb._on_credits(G.status())
        self.assertFalse(self.rows(wb)[0].mobile_button.isEnabled())

    def test_the_person_panel_says_why_it_is_off(self):
        from addons.leads import person as PP
        G.set_transport(MonthServer(month_=month(numbers=100)))
        G.status()
        case = TM.ThePanelSaysWhatTheMobileIs(
            "test_someone_who_can_be_looked_up_is_offered_it_and_it_is_asked_for")
        panel = case.panel(TM.lead())
        [link] = [b for b in panel.findChildren(PP.QPushButton) if b.text() == "Get mobile number…"]
        self.assertFalse(link.isEnabled())
        self.assertIn("come back on 1 Dec", link.toolTip())
        self.assertTrue(any("come back on 1 Dec" in w.text() for w in panel.findChildren(PP.QLabel)))
        self.assertFalse(panel.enrich_boxes["mobile"].isEnabled())


@pytest.mark.pooled
class EmailRefusalsAreSaid(_Screen):
    def test_find_emails_does_not_start_when_the_months_emails_are_used(self):
        wb = self.bench(month(emails=200))
        leads = self._people(wb, 2)
        self._tick(wb, leads)
        with mock.patch.object(self._WB, "LeadsEmailWorker",
                               side_effect=AssertionError("started")):
            wb._find_emails(wb._cockpit.leads.selected())
        self.assertIn("200 e-mail lookups", wb._status.text())
        self.assertIn("1 Dec", wb._status.text())

    def test_a_refusal_part_way_ends_the_runs_line_with_the_servers_sentence(self):
        server = MonthServer(month_=month())
        G.set_transport(server)
        wb = self._WB.LeadsWorkbench({})
        server.replies["find-email"] = G.LimitReached(
            "LEADS_LIMIT", "You have used all 200 e-mail lookups included this month. They come back on "
            "1 Dec. Nothing was charged.", {"reason": "quota_emails"})
        self.assertEqual(G.find_email("Asha", "Rao", "rao.in"), ("", "", ""))
        self.assertIn("They come back on 1 Dec", wb._used_note())
        self.assertEqual(G.limited("quota_numbers", "spend_cap"), "")      # numbers are not stopped by it

    def test_a_spend_cap_blocks_paid_lookups_but_not_the_free_apollo_search(self):
        self.bench(month(capped=True))
        self.assertIn("1 Dec", G.limit_why_not("people"))
        self.assertIn("1 Dec", G.limit_why_not("verify"))
        self.assertEqual(G.limit_why_not("apollo"), "")


class TheUsageLine(unittest.TestCase):
    def test_the_line_reads_the_way_the_owner_wrote_it(self):
        self.assertEqual(usage_line(month()), "Emails 120/200, Numbers 40/100, resets 1 Dec")
        self.assertEqual(usage_line(None), "")

    def test_percent_is_whole_and_bounded(self):
        self.assertEqual((percent(120, 200), percent(40, 100), percent(250, 200), percent(0, 100)),
                         (60, 40, 100, 0))
        self.assertEqual(percent(5, 0), 100)

    def test_the_widget_shows_a_percent_bar_each_and_hides_without_a_month(self):
        w = MonthUsage()
        w.set_month(None)
        self.assertTrue(w.isHidden())
        w.set_month(month())
        self.assertFalse(w.isHidden())
        self.assertEqual((w.percents["emails"].text(), w.percents["numbers"].text()), ("60%", "40%"))
        self.assertAlmostEqual(w.bars["emails"]._fraction, 0.6)
        self.assertAlmostEqual(w.bars["numbers"]._fraction, 0.4)
        self.assertEqual(w.line.text(), "Emails 120/200, Numbers 40/100, resets 1 Dec")
        w.set_month(month(guard=False))
        self.assertTrue(w.isHidden())

    def test_the_credit_card_and_the_usage_page_carry_it(self):
        card = CP.CreditCard()
        card.month.set_month(month())
        self.assertFalse(card.month.isHidden())
        dlg = CP.CreditUsageDialog({})
        self.addCleanup(dlg.close)
        dlg.month.set_month(month(emails=200))
        self.assertEqual(dlg.month.percents["emails"].text(), "100%")


if __name__ == "__main__":
    unittest.main()
