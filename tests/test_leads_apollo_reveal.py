"""The Apollo way (the owner, 25-Nov-2026: "do it the apollo way"): a Find-people search on Apollo is free and
shows people by first name and title; a full name and e-mail are bought only for the people the owner ticks and
reveals. Before this, a search revealed up to "Full names up to" people by itself and the owner saw 120 credits
go on 60 people he never picked.

Held here:
  - the search asks Apollo's free search only, never bulk_match, and its rows are previews;
  - a preview's half name is not an identity (two "Rahul S." at Acme are two people);
  - Find e-mails, Find phones and Find mobiles leave previews alone (half a name buys the wrong person);
  - Reveal fills the ticked rows in place, charges only for people Apollo finds, and keeps what it bought when a
    refusal comes part-way;
  - the Reveal button is on the bar only while there is someone to reveal, and asks before it spends.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector import apollo, identity, mobiles                    # noqa: E402
from prospector import gateway as G                                 # noqa: E402

from test_leads_cockpit import _Workbench                         # noqa: E402
from test_leads_credit_pool import FakeServer                     # noqa: E402

SPEC = {"seniority": {"include": ["head"]}}


def card(i, first="Rahul", last="S.", company="Acme", has_email=True):
    return {"id": f"ap{i}", "first_name": first, "last_name_obfuscated": last, "title": "Head of Operations",
            "organization": {"name": company, "primary_domain": "acme.in"}, "has_email": has_email,
            "has_direct_phone": "Yes"}


def person(i, first="Rahul", last="Sharma"):
    return {"id": f"ap{i}", "first_name": first, "last_name": last, "name": f"{first} {last}",
            "title": "Head of Operations", "email": f"{first.lower()}@acme.in", "email_status": "verified",
            "linkedin_url": f"https://linkedin.com/in/{first.lower()}{i}",
            "organization": {"name": "Acme", "primary_domain": "acme.in"}}


class Recorder:
    """Stands in for the transport: answers SEARCH with cards and BULK_MATCH from `found`, remembering each call."""

    def __init__(self, cards, found=None, refuse_after=None):
        self.cards, self.found, self.calls = cards, found or {}, []
        self.refuse_after = refuse_after

    def __call__(self, path, body):
        self.calls.append(path)
        if path == apollo.SEARCH:
            return {"people": self.cards if body.get("page", 1) == 1 else [], "total_entries": len(self.cards)}
        if path == apollo.BULK_MATCH:
            if self.refuse_after is not None and self.calls.count(apollo.BULK_MATCH) > self.refuse_after:
                raise apollo.ApolloError("Your Monid wallet is empty.")
            return {"matches": [self.found.get(d.get("id"), {}) for d in body["details"]]}
        raise AssertionError(path)


class TheSearchIsFree(unittest.TestCase):
    def test_it_asks_the_free_search_only_and_returns_previews(self):
        send = Recorder([card(1), card(2, "Asha", "K.")])
        stats: dict = {}
        leads = apollo.search_people(SPEC, "", target=25, stats=stats, transport=send, reveal=False)
        self.assertNotIn(apollo.BULK_MATCH, send.calls)
        self.assertEqual([l.name for l in leads], ["Rahul S.", "Asha K."])
        self.assertTrue(all(apollo.is_preview(l) for l in leads))
        self.assertEqual(leads[0].title, "Head of Operations")
        self.assertEqual(leads[0].extra["apollo_id"], "ap1")
        self.assertEqual(stats.get("revealed", 0), 0)

    def test_it_stops_at_how_many_the_owner_asked_to_see(self):
        send = Recorder([card(i) for i in range(10)])
        leads = apollo.search_people(SPEC, "", target=4, transport=send, reveal=False)
        self.assertEqual(len(leads), 4)

    def test_two_half_names_at_one_company_are_two_people(self):
        a, b = (apollo._preview_of(apollo._card(card(i), "")) for i in (1, 2))
        self.assertTrue(identity.keys_of(a).isdisjoint(identity.keys_of(b)))


class NothingIsBoughtForHalfAName(unittest.TestCase):
    def test_email_phone_and_mobile_lookups_leave_previews_alone(self):
        from addons.leads.cockpit import needs_email, needs_phone, needs_reveal
        from prospector.models import Dossier
        lead = apollo._preview_of(apollo._card(card(1), ""))
        dos = Dossier(lead=lead)
        self.assertTrue(needs_reveal(dos))
        self.assertFalse(needs_email(dos))
        self.assertFalse(needs_phone(dos))
        self.assertFalse(mobiles.needs_mobile(lead))


class Reveal(unittest.TestCase):
    def previews(self, n):
        return [apollo._preview_of(apollo._card(card(i), "")) for i in range(n)]

    def test_it_fills_the_same_rows_and_charges_only_who_apollo_finds(self):
        rows = self.previews(3)
        send = Recorder([], found={"ap0": person(0), "ap2": person(2, "Asha", "Kumar")})
        out = apollo.reveal_leads(rows, "", transport=send)
        self.assertEqual((out["asked"], out["found"], out["missing"]), (3, 2, 1))
        self.assertEqual(rows[0].name, "Rahul Sharma")
        self.assertEqual(rows[0].email, "rahul@acme.in")
        self.assertFalse(apollo.is_preview(rows[0]))
        self.assertTrue(apollo.is_preview(rows[1]))                     # Apollo did not find them: still a preview
        self.assertEqual(rows[2].name, "Asha Kumar")

    def test_a_refusal_part_way_keeps_what_was_bought(self):
        rows = self.previews(12)                                        # two batches of ten and two
        send = Recorder([], found={f"ap{i}": person(i) for i in range(12)}, refuse_after=1)
        out = apollo.reveal_leads(rows, "", transport=send)
        self.assertEqual(out["found"], 10)
        self.assertTrue(out.get("stopped"))

    def test_a_refusal_before_anything_was_bought_says_why(self):
        send = Recorder([], refuse_after=0)
        with self.assertRaises(apollo.ApolloError):
            apollo.reveal_leads(self.previews(2), "", transport=send)

    def test_someone_already_revealed_is_not_asked_again(self):
        rows = self.previews(1)
        send = Recorder([], found={"ap0": person(0)})
        apollo.reveal_leads(rows, "", transport=send)
        apollo.reveal_leads(rows, "", transport=send)
        self.assertEqual(send.calls.count(apollo.BULK_MATCH), 1)


@pytest.mark.pooled
class TheRevealButton(_Workbench):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(self._WB.LeadsWorkbench, "_refresh_credits", lambda _self: None)
        patch.start()
        self.addCleanup(patch.stop)
        ready = mock.patch.object(G, "ready", lambda op: True)
        ready.start()
        self.addCleanup(ready.stop)

    def bench(self, n=3):
        from prospector.engine import RunResult
        wb = self._WB.LeadsWorkbench({})
        G.set_transport(FakeServer(balance=100))
        self.addCleanup(G.set_transport, None)
        self.addCleanup(G.forget)
        leads = [apollo._preview_of(apollo._card(card(i, f"P{i}"), "")) for i in range(n)]
        res = RunResult(dossiers=[], total_in_sheet=n, signal_source="", all_leads=leads)
        wb._start_export = lambda *a, **k: None
        wb._next_mode = "icp_leads_only"
        wb._next_params = {"mode": "icp_leads_only", "offer": "x"}
        wb._jobs = 1
        wb._on_prepared(res, [])
        return wb, leads

    def test_the_bar_offers_reveal_while_someone_is_a_preview(self):
        wb, _leads = self.bench()
        self.assertTrue(wb._cockpit.leads._reveal_wanted)

    def test_reveal_asks_in_credits_first_and_a_no_starts_nothing(self):
        wb, leads = self.bench()
        said = []
        wb._confirm_pool = lambda title, lines: (said.append((title, lines)), False)[1]
        started = []
        with mock.patch.object(self._WB, "LeadsRevealWorker", lambda *a, **k: started.append(a)):
            wb._reveal_selected([type("D", (), {"lead": l})() for l in leads])
        [(title, lines)] = said
        self.assertEqual(title, "Reveal")
        self.assertIn("3 people", lines[0])
        self.assertIn("up to 6 credits", lines[0])
        self.assertEqual(started, [])


if __name__ == "__main__":
    unittest.main()
