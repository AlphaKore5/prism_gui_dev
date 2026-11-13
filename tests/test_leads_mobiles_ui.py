"""Find mobiles on the screen (4-Nov-2026) — the person panel's "Find their mobile…" and its Enrichment
box, through the workbench, and what the panel and the sheet say a found mobile is.

The engine (prospector/mobiles.py) and its worker are tested in test_prospector_mobiles.py. Here:

  · the workbench hands the worker exactly the people who can be looked up and have no mobile yet,
    asks first in credits and says what it is, and starts nothing when declined, when the server has
    not switched it on, or on a developer's own keys (no mobile source sits behind those);
  · what comes back is said plainly — found, none on file, failed, still being looked up;
  · the panel offers the lookup, shows a found mobile as the PERSON's own number from Apollo — never as
    "the company's number, published" — and shows it even when a number the person came with keeps the
    Phone field; the sheet's Phone source column says the same.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton   # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from addons.leads import person as PP                              # noqa: E402
from prospector import exports as EX                               # noqa: E402
from prospector import gateway as G                                # noqa: E402
from prospector import mobiles as M                                # noqa: E402
from prospector.models import Dossier, Lead                        # noqa: E402

from test_leads_cockpit import _FakeSignal, _Workbench             # noqa: E402
from test_leads_credit_pool import FakeServer                      # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

MOBILE = "+919825012345"


def lead(name="Asha Rao", company="Acme Works", domain="acme.example", **kw):
    extra = dict(kw.pop("extra", {}))
    extra.setdefault("location", "Vadodara")
    if domain:
        extra.setdefault("company_domain", domain)
    l = Lead(name=name, title="Owner", company=company, **kw)
    l.extra = extra
    return l


class _FakeMobileWorker:
    """Stands in for LeadsMobileWorker: records what it was handed; start() only records."""
    made: list = []

    def __init__(self, leads, cfg):
        self.leads, self.cfg, self.started = leads, cfg, False
        self.progress, self.done, self.failed = _FakeSignal(), _FakeSignal(), _FakeSignal()
        _FakeMobileWorker.made.append(self)

    def start(self):
        self.started = True


class FindMobilesOnTheScreen(_Workbench):

    def setUp(self):
        super().setUp()
        # A finished run refreshes the balance with a REAL call on the pool (see test_leads_phones).
        patcher = mock.patch.object(self._WB.LeadsWorkbench, "_refresh_credits", lambda _self: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        _FakeMobileWorker.made = []
        orig = self._WB.LeadsMobileWorker
        self._WB.LeadsMobileWorker = _FakeMobileWorker
        self.addCleanup(setattr, self._WB, "LeadsMobileWorker", orig)

    def _people(self, wb, n=3):
        from prospector.engine import RunResult
        leads = [lead(name=f"P{i} Singh", company=f"Co {i}", domain=f"co{i}.example", fit_score=60 + i)
                 for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="", all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "offer": "Automation"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return leads

    def _tick(self, wb, leads):
        ck = wb._cockpit.leads
        for r in range(ck._table.rowCount()):
            if ck._dossier_at(r).lead in leads:
                ck._table.item(r, 0).setCheckState(Qt.Checked)

    def _bench(self):
        wb = self._WB.LeadsWorkbench({})
        wb._confirm_mobiles = lambda n: True
        return wb

    def _pooled_bench(self, balance=50):
        wb = self._WB.LeadsWorkbench({})
        G.set_transport(FakeServer(balance=balance))
        self.addCleanup(G.set_transport, None)
        self.addCleanup(G.forget)
        patch = mock.patch.object(G, "_auth_body", lambda **e: {"license_id": "L", "device_fp": "D", **e})
        patch.start()
        self.addCleanup(patch.stop)
        wb._on_credits(G.status())
        return wb

    # ── what is asked, and when ─────────────────────────────────────────────
    @pytest.mark.pooled
    def test_the_worker_gets_exactly_the_people_who_can_be_looked_up_and_have_no_mobile(self):
        wb = self._pooled_bench()
        wb._confirm_mobiles = lambda n: True
        leads = self._people(wb, 4)
        M.apply(leads[1], MOBILE)                               # already has theirs
        leads[2].extra.pop("company_domain")                    # nothing to look them up with
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        [worker] = _FakeMobileWorker.made
        self.assertTrue(worker.started)
        self.assertEqual(sorted(l.name for l in worker.leads), ["P0 Singh", "P3 Singh"])
        self.assertIn("2 people", wb._status.text())
        self.assertIn("a few minutes", wb._status.text())

    @pytest.mark.pooled
    def test_a_second_press_while_it_runs_starts_nothing(self):
        wb = self._pooled_bench()
        wb._confirm_mobiles = lambda n: True
        leads = self._people(wb)
        self._tick(wb, leads)
        picked = wb._cockpit.leads.selected()
        wb._find_mobiles(picked)
        wb._find_mobiles(picked)
        self.assertEqual(len(_FakeMobileWorker.made), 1)

    @pytest.mark.pooled
    def test_it_asks_in_credits_first_and_says_what_it_is(self):
        wb = self._pooled_bench()
        said = []
        wb._confirm_pool = lambda title, lines: (said.append((title, lines)), False)[1]
        leads = self._people(wb)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        [(title, lines)] = said
        self.assertEqual(title, "Find mobiles")
        self.assertIn("3 people", lines[0])
        self.assertIn("up to 30 credits", lines[0])             # 3 x the 10-credit default
        self.assertIn("only for a number found", lines[1])
        self.assertIn("a few minutes", lines[1])
        self.assertEqual(_FakeMobileWorker.made, [])            # declined: nothing ran, nothing spent

    @pytest.mark.pooled
    def test_it_asks_for_no_more_than_a_page_of_people(self):
        wb = self._pooled_bench()
        asked = []
        wb._confirm_mobiles = lambda n: (asked.append(n), False)[1]
        leads = self._people(wb, M.LIMIT + 5)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        self.assertEqual(asked, [M.LIMIT])

    @pytest.mark.pooled
    def test_a_lookup_the_server_has_not_switched_on_says_so_and_charges_nothing(self):
        wb = self._pooled_bench()
        wb._confirm_mobiles = lambda n: True
        leads = self._people(wb)
        self._tick(wb, leads)
        with mock.patch.object(G, "ready", lambda op: op != "mobile"):
            wb._find_mobiles(wb._cockpit.leads.selected())
        self.assertIn("isn't switched on yet", wb._status.text())
        self.assertEqual(_FakeMobileWorker.made, [])

    def test_with_your_own_keys_it_says_there_is_no_mobile_source(self):
        wb = self._bench()                                      # the suite runs in direct mode
        leads = self._people(wb)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        self.assertIn("runs on Prism's credits", wb._status.text())
        self.assertEqual(_FakeMobileWorker.made, [])

    def test_nobody_left_to_look_up_says_so(self):
        wb = self._bench()
        leads = self._people(wb)
        for l in leads:
            M.apply(l, MOBILE)
        self._tick(wb, leads)
        wb._find_mobiles(wb._cockpit.leads.selected())
        self.assertIn("already have a mobile number", wb._status.text())
        self.assertEqual(_FakeMobileWorker.made, [])

    @pytest.mark.pooled
    def test_the_person_panel_asks_for_one_person_through_the_enrichment_queue(self):
        wb = self._pooled_bench()
        wb._confirm_mobiles = lambda n: True
        self._people(wb)
        dos = wb._cockpit.leads._dossier_at(0)
        wb._panel_enrich(dos, ["mobile"])
        [worker] = _FakeMobileWorker.made
        self.assertEqual([l.name for l in worker.leads], [dos.lead.name])

    # ── what comes back ─────────────────────────────────────────────────────
    def test_found_numbers_are_said_with_what_they_are_and_are_not(self):
        wb = self._bench()
        self._people(wb)
        wb._jobs = 1
        wb._on_mobiles_found({"asked": 3, "found": 2, "given": 2, "failed": 0, "pending": 0, "why": []})
        said = wb._status.text()
        self.assertIn("Found 2 mobile number(s) for 3 people", said)
        self.assertIn("not called, format checked only", said)
        self.assertIn("1 have none on file", said)
        self.assertEqual(wb._jobs, 0)

    def test_a_lookup_that_never_ran_says_why_and_is_not_found_zero_of_zero(self):
        wb = self._bench()
        self._people(wb)
        wb._jobs = 1
        wb._on_mobiles_found({"asked": 0, "found": 0, "given": 0, "failed": 2, "pending": 0,
                              "why": ["Prism's server needs updating."]})
        self.assertEqual(wb._status.text(), "No mobile numbers were looked up.   ·   Prism's server needs updating.")

    def test_lookups_still_going_when_it_stopped_waiting_are_not_called_empty(self):
        wb = self._bench()
        self._people(wb)
        wb._jobs = 1
        wb._on_mobiles_found({"asked": 3, "found": 1, "given": 1, "failed": 0, "pending": 2,
                              "why": ["Apollo was still working on 2 of them when Prism stopped waiting."]})
        said = wb._status.text()
        self.assertIn("Found 1 mobile number(s) for 3 people", said)
        self.assertNotIn("have none on file", said)             # 2 are pending, not empty
        self.assertIn("still working on 2", said)

    def test_a_partial_failure_says_how_many(self):
        wb = self._bench()
        self._people(wb)
        wb._jobs = 1
        wb._on_mobiles_found({"asked": 1, "found": 1, "given": 1, "failed": 4, "pending": 0, "why": []})
        self.assertIn("4 couldn't be looked up", wb._status.text())

    def test_what_comes_back_is_saved_with_where_it_came_from(self):
        from addons.leads import sessions
        wb = self._bench()
        leads = self._people(wb)
        M.apply(leads[0], MOBILE)
        wb._jobs = 1
        wb._on_mobiles_found({"asked": 3, "found": 1, "given": 1, "failed": 0, "pending": 0, "why": []})
        loaded = sessions.load(self._sessions, wb._session_id)
        first = loaded["all_leads"][0]
        self.assertEqual(first.phone, MOBILE)
        self.assertEqual((first.extra["phones"][0]["scope"], first.extra["phones"][0]["provider"]),
                         ("person", "apollo"))


class ThePanelSaysWhatTheMobileIs(unittest.TestCase):

    def panel(self, l):
        p = PP.PersonPanel()
        p.resize(760, 900)
        self.asked = []
        p.enrichRequested.connect(lambda row, picks: self.asked.append(picks))
        p.show_person(PP.PersonView(row=Dossier(lead=l, status="ok", verdict="warm")))
        return p

    @staticmethod
    def texts(p):
        return [w.text() for w in p._left.findChildren(QLabel)]

    @staticmethod
    def buttons(p, text):
        return [b for b in p._left.findChildren(QPushButton) if b.text() == text]

    def test_someone_who_can_be_looked_up_is_offered_it_and_it_is_asked_for(self):
        p = self.panel(lead())
        [find] = self.buttons(p, "Find their mobile…")
        find.click()
        self.assertEqual(self.asked, [["mobile"]])
        self.assertTrue(p.enrich_boxes["mobile"].isEnabled())

    def test_someone_with_no_company_website_is_not_offered_a_lookup(self):
        p = self.panel(lead(domain=""))
        self.assertFalse(self.buttons(p, "Find their mobile…"))
        self.assertFalse(p.enrich_boxes["mobile"].isEnabled())

    def test_a_found_mobile_is_their_own_number_not_the_companys(self):
        l = lead()
        M.apply(l, MOBILE)
        texts = self.texts(self.panel(l))
        self.assertIn("+91 98250 12345", texts)
        line = [t for t in texts if t.startswith("Their own mobile number, from Apollo")]
        self.assertEqual(len(line), 1)
        self.assertIn("not called, format checked only", line[0])
        self.assertFalse([t for t in texts if "The company's number" in t])      # never said of this number

    def test_a_found_mobile_is_not_offered_again(self):
        l = lead()
        M.apply(l, MOBILE)
        p = self.panel(l)
        self.assertFalse(self.buttons(p, "Find their mobile…"))
        self.assertFalse(p.enrich_boxes["mobile"].isEnabled())

    def test_a_number_they_came_with_keeps_the_phone_field_and_the_mobile_is_still_shown(self):
        l = lead(phone="+91 98250 99999")
        M.apply(l, MOBILE)
        self.assertEqual(l.phone, "+91 98250 99999")            # never replaced
        texts = self.texts(self.panel(l))
        self.assertIn("+91 98250 99999", texts)
        self.assertIn("+91 98250 12345", texts)                 # paid for, so it is visible
        self.assertTrue([t for t in texts if t.startswith("Their own mobile number, from Apollo")])


class TheSheetSaysWhatTheMobileIs(unittest.TestCase):

    def test_the_phone_source_column_names_apollo_and_says_it_was_not_called(self):
        l = lead()
        M.apply(l, MOBILE)
        said = EX.phone_source_of(l)
        self.assertTrue(said.startswith("Their own mobile — Apollo"))
        self.assertTrue(said.endswith("not called"))
        self.assertNotIn("company", said)


if __name__ == "__main__":
    unittest.main()
