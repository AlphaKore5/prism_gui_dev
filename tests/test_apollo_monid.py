"""Apollo's people search, asked through the owner's Monid wallet (24-Nov-2026).

The search is free on Monid ($0, measured: the wallet did not move) and returns catalogue cards — a first
name and an OBFUSCATED last name, a title, a company name, an Apollo id, and "has e-mail / has phone" flags,
never a contact. Monid has no bulk match, so a reveal is one `people/match` per person (about $0.026 each).
These tests hold the code to:

  · the filters Prism already builds reaching Monid as the query string it takes (`person_titles[]`);
  · a card read from the real shape (fixtures/monid/apollo_people_search.json) never becoming a name;
  · a reveal answered in the bulk shape — one entry per person asked, {} for nobody — so search_people needs
    no other change, and a person Apollo does not find costing nothing;
  · a key or wallet Monid refuses reaching the owner in Monid's own words, and no Apollo key being needed.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import apollo as A                # noqa: E402
from prospector import monid_run as MR            # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "monid")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


SEARCH, MATCH = fixture("apollo_people_search.json"), fixture("apollo_people_match.json")


class FakeMonid:
    """A `call` for monid_run: answers the free search with the real-shaped fixture and each match with one person."""

    def __init__(self, people=None, refuse: Exception | None = None, search=None):
        self.asked: list = []
        self.people = people if people is not None else {"apid-0001": MATCH}
        self.refuse, self.search = refuse, SEARCH if search is None else search

    def __call__(self, provider, endpoint, *, key, max_cost, body=None, query=None):
        self.asked.append({"provider": provider, "endpoint": endpoint, "key": key, "max_cost": max_cost,
                           "query": query, "body": body})
        if self.refuse:
            raise self.refuse
        if endpoint == "/mixed_people/api_search":
            return self.search
        run = self.people.get((query or {}).get("id"))
        return run if run is not None else {"status": "COMPLETED", "providerResponse": {"httpStatus": 404},
                                            "output": None}


SPEC = {"job_titles": {"include": ["Head of Automation"]}, "seniority": {"include": ["head"]},
        "locations": {"include": ["India"]}, "headcount": ["1001-5000"]}


class TheQueryString(unittest.TestCase):
    def test_lists_are_named_the_way_apollos_people_search_names_them(self):
        got = A._monid_query(A.params_for(SPEC))
        self.assertEqual(got["person_titles[]"], ["Head of Automation"])
        self.assertEqual(got["person_seniorities[]"], ["head"])
        self.assertEqual(got["person_locations[]"], ["India"])
        self.assertIn("organization_num_employees_ranges[]", got)

    def test_names_that_already_carry_their_brackets_keep_them(self):
        got = A._monid_query({"revenue_range[min]": 5000, "q_keywords": "forging", "page": 2, "x": None})
        self.assertEqual(got, {"revenue_range[min]": 5000, "q_keywords": "forging", "page": 2})


class TheSearch(unittest.TestCase):
    def test_the_free_search_is_one_run_and_returns_the_answers_body(self):
        call = FakeMonid()
        send = A.monid_transport("K", call=call)
        out = send(A.SEARCH, dict(A.params_for(SPEC), page=1, per_page=100))
        self.assertEqual(len(out["people"]), 2)
        self.assertEqual(out["total_entries"], 318)
        ask = call.asked[0]
        self.assertEqual((ask["provider"], ask["endpoint"], ask["key"]), ("apollo", "/mixed_people/api_search", "K"))
        self.assertEqual((ask["query"]["page"], ask["query"]["per_page"]), (1, 100))
        self.assertLessEqual(ask["max_cost"], 0.02)             # it is listed at $0

    def test_a_search_that_did_not_land_is_unreachable_not_empty(self):
        send = A.monid_transport("K", call=lambda *a, **k: None)
        with self.assertRaises(A.ApolloError) as cm:
            send(A.SEARCH, {})
        self.assertEqual(str(cm.exception), A.UNREACHABLE)

    def test_a_refused_key_or_empty_wallet_is_apollo_error_in_monids_words(self):
        send = A.monid_transport("K", call=FakeMonid(refuse=MR.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again.")))
        with self.assertRaises(A.ApolloError) as cm:
            send(A.SEARCH, {})
        self.assertIn("wallet is empty", str(cm.exception))


class TheReveal(unittest.TestCase):
    def test_a_reveal_is_one_match_per_person_in_the_order_asked(self):
        call = FakeMonid(people={"apid-0001": MATCH, "apid-0002": MATCH})
        send = A.monid_transport("K", call=call)
        out = send(A.BULK_MATCH, {"details": [{"id": "apid-0002"}, {"id": "apid-0001"}]})
        self.assertEqual(len(out["matches"]), 2)
        self.assertEqual(sorted(a["query"]["id"] for a in call.asked), ["apid-0001", "apid-0002"])
        self.assertTrue(all(a["endpoint"] == "/people/match" and a["max_cost"] <= 0.06 for a in call.asked))

    def test_a_person_apollo_does_not_find_is_an_empty_entry_so_it_costs_nothing(self):
        send = A.monid_transport("K", call=FakeMonid())
        out = send(A.BULK_MATCH, {"details": [{"id": "apid-0001"}, {"id": "nobody"}]})
        self.assertEqual(out["matches"][0]["email"], "asha.rao@acme.example")
        self.assertEqual(out["matches"][1], {})

    def test_empty_details_are_not_sent(self):
        call = FakeMonid()
        out = A.monid_transport("K", call=call)(A.BULK_MATCH, {"details": [{}, {"id": ""}, "x"]})
        self.assertEqual(call.asked, [])                                  # nothing identifies them: nobody to ask for
        self.assertEqual(out["matches"], [{}, {}])

    def test_one_person_match_is_the_same_answer_the_finder_reads(self):
        out = A.monid_transport("K", call=FakeMonid())(A.MATCH, {"id": "apid-0001"})
        self.assertEqual(out["person"]["email_status"], "verified")

    def test_a_refusal_during_a_reveal_surfaces_not_swallowed(self):
        send = A.monid_transport("K", call=FakeMonid(refuse=MR.MonidError("Monid refused the API key. Check MONID_API_KEY.")))
        with self.assertRaises(A.ApolloError):
            send(A.BULK_MATCH, {"details": [{"id": "apid-0001"}]})

    def test_a_path_it_does_not_have_is_refused(self):
        with self.assertRaises(A.ApolloError):
            A.monid_transport("K", call=FakeMonid())("/people/other", {})


class SearchPeopleOnMonid(unittest.TestCase):
    def go(self, call=None, **kw):
        stats: dict = {}
        call = call or FakeMonid()
        leads = A.search_people(SPEC, "", target=5, stats=stats, transport=A.monid_transport("K", call=call), **kw)
        return leads, stats, call

    def test_no_apollo_key_is_needed_with_a_transport(self):
        leads, _stats, _call = self.go()
        self.assertEqual(len(leads), 1)

    def test_a_search_without_a_key_and_without_a_transport_still_says_so(self):
        with self.assertRaises(A.ApolloError) as cm:
            A.search_people(SPEC, "", target=5)
        self.assertEqual(str(cm.exception), A.NO_KEY)

    def test_the_revealed_person_arrives_whole(self):
        lead = self.go()[0][0]
        self.assertEqual((lead.name, lead.company, lead.email), ("Asha Rao", "Acme Motors", "asha.rao@acme.example"))
        self.assertEqual(lead.extra["company_domain"], "acme.example")
        self.assertEqual(lead.extra["apollo_id"], "apid-0001")
        self.assertEqual(lead.extra["email_source"], "apollo")

    def test_only_the_person_apollo_found_costs_anything(self):
        _leads, stats, call = self.go()
        self.assertEqual(stats["searched"], 2)                       # two free cards
        self.assertEqual(stats["revealed"], 1)                       # one person found = one match billed
        self.assertEqual(len([a for a in call.asked if a["endpoint"] == "/people/match"]), 2)

    def test_the_cards_are_never_names(self):
        card = A._card(SEARCH["output"]["people"][0], "")
        self.assertEqual(card["name"], "")                           # "Ra***o" is a bucket, not a surname
        self.assertEqual(card["first"], "Asha")
        self.assertEqual(card["id"], "apid-0001")

    def test_a_wallet_that_runs_dry_ends_the_run_with_monids_words(self):
        call = FakeMonid(refuse=MR.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again."))
        with self.assertRaises(A.ApolloError) as cm:
            self.go(call=call)
        self.assertIn("wallet is empty", str(cm.exception))

    def test_the_budget_still_caps_the_reveals(self):
        call = FakeMonid(people={"apid-0001": MATCH, "apid-0002": MATCH})
        _leads, stats, call = self.go(call=call, budget=1)
        self.assertEqual(stats["revealed"], 1)


if __name__ == "__main__":
    unittest.main()
