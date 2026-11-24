"""A person's mobile, bought from three sources in turn (24-Nov-2026) — and the one-endpoint Monid runner under it.

What the owner measured on 252 real people, and what this holds the code to:

  · every source charges ONLY for a number it returns, so the cheapest goes first and the next is asked only
    when the one before found nothing — a number is paid for once;
  · each answer is read from the shape it really had (fixtures/monid/phone_sources.json: real answers, with
    the names and numbers replaced), and a landline or toll-free line is a company desk, not a mobile;
  · a source that is down is skipped; a key or wallet Monid refuses stops everything;
  · the run asks Monid with a price ceiling, and with the right body for the right endpoint.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import monid_run as MR            # noqa: E402
from prospector import phone_waterfall as W       # noqa: E402

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "monid", "phone_sources.json")
with open(FIX, encoding="utf-8") as f:
    ANSWERS = json.load(f)

MOBILE = "+919825012345"


def runs(**by_source):
    """A `call` that answers each source with a fixture (or None for "down"), and records every ask."""
    asked: list = []

    def call(provider, endpoint, *, key, max_cost, body=None, query=None):
        source = {"/mobile_phone.ai_ark": "ai_ark", "/v2/contact/phone": "reversecontact",
                  "/v1/people/enrich/work-email": "contactout"}[endpoint]
        asked.append({"source": source, "provider": provider, "endpoint": endpoint, "key": key,
                      "max_cost": max_cost, "body": body})
        answer = by_source.get(source, "miss")
        if isinstance(answer, Exception):
            raise answer
        return None if answer is None else ANSWERS[f"{source}_{answer}"]

    call.asked = asked
    return call


class Asking(unittest.TestCase):
    def test_each_source_gets_the_body_its_endpoint_takes(self):
        self.assertEqual(W.request("ai_ark", "Asha Rao", "acme.example"),
                         ("anyapi", "/mobile_phone.ai_ark",
                          {"body": {"domain": "acme.example", "fullName": "Asha Rao"}}))
        self.assertEqual(W.request("reversecontact", "Asha Rao", "acme.example"),
                         ("reversecontact", "/v2/contact/phone",
                          {"body": {"fullName": "Asha Rao", "companyDomain": "acme.example"}}))

    def test_contactout_takes_lists_and_is_asked_for_the_phone_only(self):
        provider, endpoint, kw = W.request("contactout", "Asha Rao", "acme.example",
                                           company="Acme Motors", title="Head of Automation")
        self.assertEqual((provider, endpoint), ("contactout", "/v1/people/enrich/work-email"))
        body = kw["body"]
        self.assertEqual(body["company"], ["Acme Motors"])          # a LIST: a bare string is a 400
        self.assertEqual(body["company_domain"], ["acme.example"])
        self.assertEqual(body["include"], ["phone"])               # the work e-mail is a separate $0.10
        self.assertEqual(body["job_title"], "Head of Automation")

    def test_contactout_without_a_company_name_falls_back_to_the_domain(self):
        body = W.request("contactout", "Asha Rao", "acme.example")[2]["body"]
        self.assertEqual(body["company"], ["acme.example"])
        self.assertNotIn("job_title", body)

    def test_an_unknown_source_is_an_error_not_a_guess(self):
        with self.assertRaises(ValueError):
            W.request("lusha", "Asha Rao", "acme.example")

    def test_no_source_is_asked_for_more_than_it_is_listed_at_plus_a_cent(self):
        listed = {"ai_ark": 0.084, "reversecontact": 0.10, "contactout": 0.20}
        for source, price in listed.items():
            self.assertGreaterEqual(W.MAX_COST[source], price)
            self.assertLessEqual(W.MAX_COST[source], price + 0.03)


class ReadingAnAnswer(unittest.TestCase):
    def test_every_hit_in_its_real_shape_is_the_same_number(self):
        for source in W.SOURCES:
            self.assertEqual(W.number_from(source, ANSWERS[f"{source}_hit"]), (MOBILE, "mobile"), source)

    def test_every_miss_in_its_real_shape_is_nothing(self):
        for source in W.SOURCES:
            self.assertIsNone(W.number_from(source, ANSWERS[f"{source}_miss"]), source)

    def test_reversecontact_puts_the_mobile_before_a_landline(self):
        self.assertEqual(W.candidates("reversecontact", ANSWERS["reversecontact_hit"]["output"])[0], MOBILE)

    def test_a_landline_alone_is_not_a_persons_mobile(self):
        run = {"output": {"success": True, "data": {"result": [{"value": "+91 79 2658 1234", "type": "landline"}]}},
               "providerResponse": {"httpStatus": 200}}
        self.assertIsNone(W.number_from("reversecontact", run))

    def test_a_toll_free_line_is_not_a_persons_mobile(self):
        run = {"output": {"status_code": 200, "profile": {"phone": ["1800 123 4567"]}},
               "providerResponse": {"httpStatus": 200}}
        self.assertIsNone(W.number_from("contactout", run))

    def test_a_number_whose_kind_the_digits_cannot_tell_still_counts(self):
        run = {"output": {"found": True, "data": {"phones": ["+14155550123"]}}, "providerResponse": {"httpStatus": 200}}
        self.assertEqual(W.number_from("ai_ark", run), ("+14155550123", "unknown"))

    def test_an_answer_that_is_not_the_shape_this_was_read_from_is_a_miss_not_a_crash(self):
        for odd in (None, "x", [], {"output": "x"}, {"output": {"found": True, "data": "x"}},
                    {"output": {"data": {"result": "x"}}}, {"output": {"profile": {"phone": "x"}}}):
            for source in W.SOURCES:
                self.assertIsNone(W.number_from(source, odd))

    def test_a_provider_error_status_is_not_a_number(self):
        run = dict(ANSWERS["ai_ark_hit"], providerResponse={"httpStatus": 500})
        self.assertIsNone(W.number_from("ai_ark", run))


class TheWaterfall(unittest.TestCase):
    def go(self, call, **kw):
        return W.find("Asha", "Rao", "acme.example", key="K", call=call, **kw)

    def test_the_cheapest_source_goes_first_and_a_hit_stops_the_asking(self):
        call = runs(ai_ark="hit")
        out = self.go(call)
        self.assertEqual((out["number"], out["provider"], out["kind"]), (MOBILE, "ai_ark", "mobile"))
        self.assertEqual([a["source"] for a in call.asked], ["ai_ark"])          # nothing else was paid for

    def test_a_miss_moves_on_to_the_next_source(self):
        call = runs(ai_ark="miss", reversecontact="hit")
        out = self.go(call)
        self.assertEqual((out["provider"], out["number"]), ("reversecontact", MOBILE))
        self.assertEqual([a["source"] for a in call.asked], ["ai_ark", "reversecontact"])
        self.assertEqual(out["tried"], [("ai_ark", "none"), ("reversecontact", "found")])

    def test_contactout_is_the_last_resort(self):
        call = runs(ai_ark="miss", reversecontact="miss", contactout="hit")
        out = self.go(call)
        self.assertEqual(out["provider"], "contactout")
        self.assertEqual([a["source"] for a in call.asked], ["ai_ark", "reversecontact", "contactout"])

    def test_nobody_having_a_number_says_so_and_asks_everyone_once(self):
        call = runs()
        out = self.go(call)
        self.assertEqual((out["number"], out["provider"]), ("", ""))
        self.assertEqual(len(call.asked), 3)

    def test_a_source_that_is_down_is_skipped_and_said(self):
        call = runs(ai_ark=None, reversecontact="hit")
        out = self.go(call)
        self.assertEqual(out["provider"], "reversecontact")
        self.assertEqual(out["tried"][0], ("ai_ark", "down"))

    def test_a_refused_key_or_empty_wallet_stops_everything(self):
        call = runs(ai_ark=MR.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then try again."))
        with self.assertRaises(MR.MonidError):
            self.go(call)
        self.assertEqual(len(call.asked), 1)

    def test_the_key_and_a_ceiling_travel_with_every_ask(self):
        call = runs()
        self.go(call)
        self.assertTrue(all(a["key"] == "K" and a["max_cost"] > 0 for a in call.asked))

    def test_the_sources_can_be_narrowed(self):
        call = runs(reversecontact="hit")
        out = self.go(call, sources=("reversecontact",))
        self.assertEqual(out["provider"], "reversecontact")
        self.assertEqual(len(call.asked), 1)

    def test_the_name_is_asked_as_one_full_name(self):
        call = runs()
        self.go(call)
        self.assertEqual(call.asked[0]["body"]["fullName"], "Asha Rao")


class RunningOneEndpoint(unittest.TestCase):
    """monid_run.call, with Monid's two HTTP calls replaced."""

    def setUp(self):
        self.sent: list = []
        self.slept: list = []

    def post(self, status=200, data=None):
        def fn(url, headers, body, timeout):
            self.sent.append((url, headers, body))
            return status, ({"status": "COMPLETED", "output": {}} if data is None else data)
        return fn

    def go(self, post, get=None, **kw):
        return MR.call("apollo", "/people/match", key="K", max_cost=0.05, post=post,
                       get=get or (lambda *a: (200, {})), sleep=self.slept.append, **kw)

    def test_a_query_endpoint_sends_query_params_and_a_body_endpoint_sends_a_body(self):
        self.go(self.post(), query={"id": "x"})
        self.go(self.post(), body={"fullName": "A B"})
        self.assertEqual(self.sent[0][2]["input"], {"queryParams": {"id": "x"}})
        self.assertEqual(self.sent[1][2]["input"], {"body": {"fullName": "A B"}})

    def test_the_run_carries_its_ceiling_and_the_owners_key(self):
        self.go(self.post(), query={})
        url, headers, body = self.sent[0]
        self.assertTrue(url.endswith("/v1/run"))
        self.assertEqual(headers["Authorization"], "Bearer K")
        self.assertEqual((body["provider"], body["endpoint"], body["maxCost"]), ("apollo", "/people/match", 0.05))

    def test_a_refused_key_is_said_in_words(self):
        for status in (401, 403):
            with self.assertRaises(MR.MonidError) as cm:
                self.go(self.post(status, {}))
            self.assertIn("API key", str(cm.exception))

    def test_an_empty_wallet_is_said_in_words(self):
        with self.assertRaises(MR.MonidError) as cm:
            self.go(self.post(402, {}))
        self.assertIn("wallet is empty", str(cm.exception))
        with self.assertRaises(MR.MonidError):
            self.go(self.post(200, {"errorCode": "WALLET_INSUFFICIENT_FUNDS"}))

    def test_a_run_that_is_still_going_is_read_until_it_finishes(self):
        answers = iter([(200, {"status": "RUNNING", "runId": "r1"}), (200, {"status": "COMPLETED", "output": {"a": 1}})])
        got = self.go(self.post(202, {"status": "RUNNING", "runId": "r1"}), get=lambda *a: next(answers))
        self.assertEqual(got["output"], {"a": 1})
        self.assertEqual(len(self.slept), 2)

    def test_a_run_that_never_finishes_is_given_up_not_waited_for_forever(self):
        got = self.go(self.post(202, {"status": "RUNNING", "runId": "r1"}),
                       get=lambda *a: (200, {"status": "RUNNING", "runId": "r1"}), max_wait=3.0)
        self.assertIsNone(got)

    def test_a_failed_run_is_none_not_an_answer(self):
        self.assertIsNone(self.go(self.post(200, {"status": "FAILED"})))

    def test_no_network_is_none_not_a_crash(self):
        def down(*a):
            raise OSError("no network")
        self.assertIsNone(self.go(down))

    def test_the_providers_own_status_is_read_from_the_run(self):
        self.assertEqual(MR.http_status({"providerResponse": {"httpStatus": 404}}), 404)
        self.assertEqual(MR.http_status({}), 0)
        self.assertEqual(MR.http_status(None), 0)


if __name__ == "__main__":
    unittest.main()
