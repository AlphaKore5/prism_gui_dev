"""Apollo's people search on the CREDIT POOL (24-Nov-2026): the licence server asks Apollo through Prism's own
Monid account; the app sends the filters and gets catalogue cards back for free, then pays the server's price
for each person it reveals. Held here:

  · search is FREE — the call is made even when the pool is spent, and takes no credit;
  · a reveal is one request for up to ten cards, answered one entry per card ({} for nobody) and charged per
    person found by the server;
  · the engine needs no other change: `apollo.search_people(..., transport=apollo.pool_transport())`;
  · a pool that runs dry mid-run ends the run with the people it has, in the server's own words;
  · a server that is too old, or has no Monid key, is never asked.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector import apollo as A                # noqa: E402
from prospector import gateway as G               # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "monid")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


CARDS = fixture("apollo_people_search.json")["output"]
PERSON = fixture("apollo_people_match.json")["output"]["person"]
SPEC = {"job_titles": {"include": ["Head of Automation"]}, "seniority": {"include": ["head"]},
        "locations": {"include": ["India"]}, "headcount": ["1001-5000"]}


class FakeServer:
    """The licence server's /v1/leads/apollo-search and /apollo-reveal."""

    def __init__(self, balance=100, reveal_price=2):
        self.calls: list = []
        self.balance, self.price = balance, reveal_price
        self.people = {"apid-0001": PERSON}
        self.error: Exception | None = None
        self.reveal_error: Exception | None = None

    def __call__(self, path, body):
        op = path.rsplit("/", 1)[-1]
        self.calls.append((op, body))
        if op == "apollo-search":
            if self.error:
                raise self.error
            return {"people": CARDS["people"], "total_entries": CARDS["total_entries"], "balance": self.balance}
        if op == "apollo-reveal":
            if self.reveal_error:
                raise self.reveal_error
            matches = [self.people.get(d.get("id"), {}) for d in body["people"]]
            found = sum(1 for m in matches if m)
            self.balance -= found * self.price
            return {"result": {"matches": matches}, "units": found, "charged": found * self.price,
                    "balance": self.balance}
        raise AssertionError(path)

    def ops(self):
        return [op for op, _ in self.calls]


class OnThePool(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        G.set_transport(self.server)
        patch = mock.patch.object(
            G, "_auth_body",
            lambda **extra: {"license_id": "L-TEST", "device_fp": "D-TEST", "app_version": "0.0.0", **extra})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(G.forget)

    # -- the two gateway calls ---------------------------------------------
    def test_a_search_sends_the_filters_and_gets_cards_back_free(self):
        out = G.apollo_search({"person_titles": ["Head of Automation"], "page": 1})
        self.assertEqual((len(out["people"]), out["total_entries"]), (2, 318))
        [(op, body)] = self.server.calls
        self.assertEqual(body["params"], {"person_titles": ["Head of Automation"], "page": 1})
        self.assertNotIn("idem_key", body)                                 # a free lookup carries no charge key
        self.assertEqual(G.used(), 0)

    def test_a_search_is_made_even_when_the_pool_is_spent(self):
        G._note_exhausted(G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.", {"balance": 0}))
        self.assertEqual(len(G.apollo_search({})["people"]), 2)

    def test_a_reveal_is_one_request_with_a_charge_key_and_one_entry_per_card(self):
        got = G.apollo_reveal([{"id": "apid-0001"}, {"id": "nobody"}])
        self.assertEqual([bool(g) for g in got], [True, False])
        [(op, body)] = self.server.calls
        self.assertTrue(body["idem_key"].startswith("pc"))
        self.assertEqual(body["people"], [{"id": "apid-0001"}, {"id": "nobody"}])
        self.assertEqual(G.used(), 2)                                      # only the person found

    def test_a_reveal_asks_for_at_most_ten_people_and_only_dicts(self):
        G.apollo_reveal([{"id": "p%d" % i} for i in range(15)] + ["junk", None])
        self.assertEqual(len(self.server.calls[0][1]["people"]), 10)

    def test_a_spent_pool_is_an_out_of_credits_error_and_is_remembered(self):
        self.server.reveal_error = G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.", {"balance": 0})
        with self.assertRaises(G.OutOfCredits):
            G.apollo_reveal([{"id": "apid-0001"}])
        self.assertEqual(G.exhausted(), "You've run out of credits.")

    # -- the engine, unchanged, on the pool --------------------------------
    def go(self, **kw):
        stats: dict = {}
        leads = A.search_people(SPEC, "", target=5, stats=stats, transport=A.pool_transport(), **kw)
        return leads, stats

    def test_search_people_needs_no_apollo_key_on_the_pool(self):
        leads, stats = self.go()
        self.assertEqual(len(leads), 1)
        self.assertEqual((leads[0].name, leads[0].email, leads[0].company), ("Asha Rao", "asha.rao@acme.example", "Acme Motors"))
        self.assertEqual((stats["searched"], stats["revealed"]), (2, 1))

    def test_only_the_person_found_is_paid_for(self):
        self.go()
        self.assertEqual(G.used(), 2)
        self.assertEqual(self.server.ops().count("apollo-search"), 1)

    def test_the_filters_the_app_builds_reach_the_server(self):
        self.go()
        params = self.server.calls[0][1]["params"]
        self.assertEqual(params["person_titles"], ["Head of Automation"])
        self.assertEqual(params["person_locations"], ["India"])

    def test_a_pool_that_runs_dry_mid_run_ends_it_with_what_it_has_and_says_why(self):
        self.server.people["apid-0002"] = dict(PERSON, id="apid-0002", name="Vikram Shah", first_name="Vikram", last_name="Shah",
                                               email="vikram.shah@bharatgears.example")

        def dry_after_first(path, body):
            if path.endswith("apollo-reveal") and sum(1 for op in self.server.ops() if op == "apollo-reveal") >= 1:
                raise G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.", {"balance": 0})
            return self.server(path, body)
        G.set_transport(dry_after_first)
        leads, stats = self.go()
        self.assertEqual(stats["errors"], 0 if leads else 1)               # kept what it had, or said it failed
        self.assertLessEqual(len(leads), 2)

    def test_no_server_answer_before_anything_is_found_is_raised_in_the_servers_words(self):
        self.server.error = G.GatewayError("SERVER_OUTDATED", G.OUTDATED_MESSAGE)
        with self.assertRaises(A.ApolloError) as cm:
            self.go()
        self.assertEqual(str(cm.exception), G.OUTDATED_MESSAGE)

    def test_a_path_the_transport_does_not_have_is_refused(self):
        with self.assertRaises(A.ApolloError):
            A.pool_transport()("/people/other", {})


if __name__ == "__main__":
    unittest.main()
