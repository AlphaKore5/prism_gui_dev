"""The e-mail finder bought through the owner's Monid wallet.

Changed 25-Nov-2026 (the owner: "no room for hunter now"): Apollo is the only finder, and a Monid key buys
APOLLO's finder when there is no Apollo key. Hunter's own Monid finder (`_hunter_find_monid`) is kept, out of
the chain, and TheFinder below still holds what it does. Held here:

  · a Monid key alone gives Hunter's finder; a Hunter key of their own is used directly, never asked twice;
  · the request is the finder's own (name + domain, or the company's name when there is no domain);
  · the answer is read from the real shape (fixtures/monid/hunter_email_finder.json): an address and Hunter's
    own deliverability word, a LinkedIn link kept; nobody found is ("", "") and costs nothing;
  · a key or wallet Monid refuses is a FinderRefused, so the batch stops asking and says why;
  · the address that comes back is recorded as Hunter's.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import monid_run as MR            # noqa: E402
from prospector import verify as V                # noqa: E402
from prospector.models import Lead                # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "monid")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return json.load(f)


HIT, MISS = fixture("hunter_email_finder.json"), fixture("hunter_email_finder_miss.json")
# Apollo's /people/match through Monid: the person, with the address Apollo holds for them.
APOLLO_HIT = {"output": {"person": {"id": "ap1", "first_name": "Asha", "last_name": "Rao", "name": "Asha Rao",
                                    "email": "asha.rao@acme.example", "email_status": "verified",
                                    "organization": {"name": "Acme Motors", "primary_domain": "acme.example"}}}}


def lead(name="Asha Rao", company="Acme Motors", domain="acme.example"):
    l = Lead(name=name, title="Head of Automation", company=company)
    l.extra = {"company_domain": domain} if domain else {}
    return l


class Calls:
    def __init__(self, answer=HIT, refuse=None):
        self.asked, self.answer, self.refuse = [], answer, refuse

    def __call__(self, provider, endpoint, *, key, max_cost, body=None, query=None):
        self.asked.append({"provider": provider, "endpoint": endpoint, "key": key, "max_cost": max_cost, "query": query})
        if self.refuse:
            raise self.refuse
        return self.answer


class TheKeys(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {k: "" for k in ("MONID_API_KEY", "HUNTER_API_KEY")})
        env.start()
        self.addCleanup(env.stop)

    def test_a_monid_key_alone_is_collected(self):
        self.assertEqual(V.collect_keys({"monid_api_key": "mk"}), {"monid_api_key": "mk"})

    def test_the_monid_key_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": "from-env"}):
            self.assertEqual(V.collect_keys({}), {"monid_api_key": "from-env"})

    def test_with_an_apollo_key_of_their_own_monid_is_not_asked_for_the_same_person(self):
        got = V.collect_keys({"apollo_api_key": "ak", "monid_api_key": "mk"})
        self.assertEqual(got, {"apollo_api_key": "ak"})

    def test_a_hunter_key_is_no_longer_a_finder_key(self):
        self.assertEqual(V.collect_keys({"hunter_api_key": "hk"}), {})

    def test_no_keys_is_no_keys(self):
        self.assertEqual(V.collect_keys({}), {})

    def test_apollo_is_the_only_finder(self):
        self.assertEqual([name for _k, name, _f in V._FINDERS], ["Apollo"])


class TheFinder(unittest.TestCase):
    def go(self, who=None, **kw):
        call = Calls(**kw)
        with mock.patch.object(MR, "call", call):
            return V._hunter_find_monid(who or lead(), "mk"), call

    def test_a_person_is_asked_for_by_name_and_domain(self):
        _got, call = self.go()
        ask = call.asked[0]
        self.assertEqual((ask["provider"], ask["endpoint"], ask["key"]), ("hunterio", "/email-finder", "mk"))
        self.assertEqual(ask["query"], {"first_name": "Asha", "last_name": "Rao", "domain": "acme.example"})
        self.assertLessEqual(ask["max_cost"], 0.06)                      # listed at $0.0245

    def test_with_no_domain_the_company_name_is_asked_instead(self):
        _got, call = self.go(lead(domain=""))
        self.assertEqual(call.asked[0]["query"], {"first_name": "Asha", "last_name": "Rao", "company": "Acme Motors"})

    def test_nobody_to_look_up_asks_nothing(self):
        for who in (lead(name="Madonna"), lead(domain="", company=""), lead(domain="", company="AB")):
            got, call = self.go(who)
            self.assertEqual((got, call.asked), (("", ""), []))

    def test_the_address_and_hunters_own_word_come_back(self):
        got, _call = self.go()
        self.assertEqual(got, ("asha.rao@acme.example", "valid"))

    def test_a_linkedin_link_is_kept_when_the_lead_had_none(self):
        who = lead()
        self.go(who)
        self.assertEqual(who.extra["linkedin"], "https://www.linkedin.com/in/asha-rao-fake")
        mine = lead()
        mine.extra["linkedin"] = "https://www.linkedin.com/in/theirs"
        self.go(mine)
        self.assertEqual(mine.extra["linkedin"], "https://www.linkedin.com/in/theirs")

    def test_nobody_found_is_empty_and_so_is_a_provider_that_did_not_answer(self):
        self.assertEqual(self.go(answer=MISS)[0], ("", ""))
        self.assertEqual(self.go(answer=None)[0], ("", ""))
        self.assertEqual(self.go(answer={"output": "x"})[0], ("", ""))

    def test_a_refused_key_or_empty_wallet_is_a_finder_refusal_in_monids_words(self):
        with self.assertRaises(V.FinderRefused) as cm:
            self.go(refuse=MR.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again."))
        self.assertIn("wallet is empty", str(cm.exception))


class InTheFinderLoop(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {k: "" for k in ("MONID_API_KEY", "HUNTER_API_KEY")})
        env.start()
        self.addCleanup(env.stop)

    def run_loop(self, keys, who=None, refused=None, **kw):
        who = who or lead()
        kw.setdefault("answer", APOLLO_HIT)
        call = Calls(**kw)
        with mock.patch.object(MR, "call", call), mock.patch.object(V, "verify_email", return_value=""):
            V.find_and_verify(who, keys, refused)
        return who, call

    def test_a_monid_key_alone_finds_the_address_through_apollo_and_records_it_as_apollos(self):
        who, call = self.run_loop({"monid_api_key": "mk"})
        self.assertEqual(who.email, "asha.rao@acme.example")
        self.assertEqual(who.extra["email_source"], "apollo")
        self.assertEqual([(c["provider"], c["endpoint"]) for c in call.asked], [("apollo", "/people/match")])

    def test_an_apollo_that_already_sold_the_address_is_not_asked_again(self):
        who = lead()
        who.email, who.extra["email_source"] = "old@acme.example", "apollo"
        _who, call = self.run_loop({"monid_api_key": "mk"}, who=who)
        self.assertEqual(call.asked, [])

    def test_a_refusal_is_collected_once_and_the_batch_stops_asking(self):
        refused: dict = {}
        _w, call = self.run_loop({"monid_api_key": "mk"}, refused=refused,
                                 refuse=MR.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again."))
        self.assertIn("wallet is empty", refused["Apollo"])
        _w2, call2 = self.run_loop({"monid_api_key": "mk"}, who=lead(name="Ravi Shah"), refused=refused)
        self.assertEqual(len(call.asked), 1)
        self.assertEqual(call2.asked, [])                                 # the second person was never asked

    def test_nobody_found_keeps_no_address(self):
        who, _call = self.run_loop({"monid_api_key": "mk"}, answer={"output": {}})
        self.assertEqual(who.email, "")


if __name__ == "__main__":
    unittest.main()
