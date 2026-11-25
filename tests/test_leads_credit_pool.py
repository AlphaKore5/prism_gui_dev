"""Leads & Outreach on the credit pool (23/24-Sep-2026).

Leads no longer runs on the customer's own Exa / Groq / verifier keys. Every paid
lookup goes to Prism's licence server (prospector/gateway.py), which holds the
provider keys, charges the customer's credits and makes the call. These tests
hold the client half of that, with a fake licence server — no network, no key,
no thread, no real ~/.prism:

  · the gateway: the mode switch, the sentinel key, what a lookup carries, how
    spend and balance are counted, and the empty-pool fast-fail that stops a
    run instead of letting it read "the call failed" as "no results";
  · each engine seam — find people, company lookup, website, why-now news,
    qualify, draft, check an address, find an address — asks the gateway when
    (and only when) its key is the sentinel, and never touches `requests`;
  · the screen: the balance pill, the price list, what each paid button says
    it will cost in CREDITS before it runs, no API-key boxes, and Send all
    counting only drafts that have a real address.

The suite as a whole runs in the developer's direct mode (tests/conftest.py);
everything here is marked `pooled` to get the real default back.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox   # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector import enrich as E                                # noqa: E402
from prospector import gateway as G                               # noqa: E402
from prospector import reach as R                                 # noqa: E402
from prospector import source as S                                # noqa: E402
from prospector import verify as V                                # noqa: E402
from prospector.models import Dossier, Lead                       # noqa: E402
from prospector.qualify import Qualifier                          # noqa: E402
from prospector.signals import ExaSignalProvider                  # noqa: E402

from test_leads_cockpit import _Workbench, _dos                   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)

RATES = {
    "people_search": {"credits": 3, "label": "Find people — one search"},
    "company_lookup": {"credits": 1, "label": "Look up a company"},
    "domain_lookup": {"credits": 1, "label": "Find a company's website"},
    "email_find": {"credits": 2, "label": "Find an e-mail address"},
    "email_verify": {"credits": 1, "label": "Check an e-mail address"},
    "signals": {"credits": 1, "label": "Why-now news"},
    "ai_qualify": {"credits": 1, "label": "Qualify a lead"},
    "ai_draft": {"credits": 1, "label": "Draft an e-mail"},
}


class FakeServer:
    """Stands in for the licence server's /v1/leads/*: answers each op from what
    the test set up, keeps a balance, and remembers every call."""

    def __init__(self, balance: int = 100):
        self.balance = balance
        self.calls: list = []                   # (op, body)
        self.replies: dict = {}                 # op -> (result, charged) | Exception

    def answer(self, op: str, result, charged: int = 1) -> "FakeServer":
        self.replies[op] = (result, charged)
        return self

    def fail(self, op: str, error: Exception) -> "FakeServer":
        self.replies[op] = error
        return self

    def __call__(self, path: str, body: dict) -> dict:
        op = path.rsplit("/", 1)[-1]
        self.calls.append((op, body))
        if op == "status":
            return {"balance": self.balance, "rates": RATES, "ready": {}}
        reply = self.replies.get(op)
        if isinstance(reply, Exception):
            raise reply
        result, charged = reply if reply else ({}, 0)
        self.balance -= charged
        return {"result": result, "charged": charged, "balance": self.balance}

    def ops(self) -> list:
        return [op for op, _ in self.calls]


def _empty_pool(balance: int = 0, needed: int = 3) -> G.OutOfCredits:
    return G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.",
                          {"balance": balance, "needed": needed})


class _Pooled(unittest.TestCase):
    """Runs against a fake server, with the seat's auth pair faked (nothing here
    may read the real licence state)."""

    def setUp(self):
        self.server = FakeServer()
        G.set_transport(self.server)
        patch = mock.patch.object(
            G, "_auth_body",
            lambda **extra: {"license_id": "L-TEST", "device_fp": "D-TEST",
                             "app_version": "0.0.0", **extra})
        patch.start()
        self.addCleanup(patch.stop)
        # An engine call that slipped past the gateway would reach for `requests`.
        import requests
        guard = mock.patch.object(
            requests, "post", side_effect=AssertionError("a pooled lookup called requests"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        G.forget()


# ── the gateway ──────────────────────────────────────────────────────────────

@pytest.mark.pooled
class TheModeAndTheSentinel(_Pooled):

    def test_the_pool_is_the_default_and_direct_is_a_dev_switch(self):
        self.assertTrue(G.pooled())
        self.assertFalse(G.direct())
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            self.assertTrue(G.direct())
            self.assertFalse(G.pooled())

    def test_the_engine_gets_the_sentinel_and_no_provider_key(self):
        cfg = {"exa_api_key": "live-exa", "api_key": "gsk_live", "apollo_api_key": "ap",
               "hunter_api_key": "hu", "reoon_api_key": "re", "tomba_key": "k:s",
               "sender_name": "Asha", "model": "llama"}
        out = G.effective_cfg(cfg)
        self.assertEqual(out["exa_api_key"], G.POOL_KEY)
        self.assertEqual(out["api_key"], G.POOL_KEY)
        self.assertTrue(out["leads_pool"])
        # Pooled means pooled (owner, 25-Sep-2026): no key of the customer's reaches
        # a provider — verifiers and e-mail finders alike are the server's.
        for gone in ("apollo_api_key", "hunter_api_key", "reoon_api_key", "tomba_key"):
            self.assertNotIn(gone, out)
        self.assertEqual(out["sender_name"], "Asha")        # the rest is left alone
        self.assertEqual(cfg["exa_api_key"], "live-exa")    # and the caller's dict too

    def test_direct_mode_hands_the_config_back_untouched(self):
        cfg = {"exa_api_key": "live-exa", "api_key": "gsk_live"}
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            self.assertIs(G.effective_cfg(cfg), cfg)

    def test_the_sentinel_is_recognised_bare_or_in_a_dict_of_keys(self):
        self.assertTrue(G.is_pool(G.POOL_KEY))
        self.assertTrue(G.is_pool({"pool": G.POOL_KEY}))
        self.assertFalse(G.is_pool("a-real-key"))
        self.assertFalse(G.is_pool({"reoon_api_key": "a-real-key"}))
        self.assertFalse(G.is_pool({}))
        self.assertFalse(G.is_pool(""))

    def test_a_pooled_config_collects_one_verifier_entry(self):
        # Verifier-only key (reoon): just the pool sentinel, reoon is stripped.
        self.assertEqual(V.collect_keys(G.effective_cfg({"reoon_api_key": "x"})),
                         {"pool": G.POOL_KEY})

    def test_a_pooled_config_collects_no_key_of_the_customers_not_even_a_finders(self):
        """Pooled means pooled (owner, 25-Sep-2026: "we need to design this
        system as pooled credits"). Apollo's and Hunter's keys, saved in
        ~/.prism from before the pool, are not carried to a provider either: an
        e-mail is found, like everything else, by the licence server."""
        cfg = G.effective_cfg({"apollo_api_key": "apo", "hunter_api_key": "hun",
                               "tomba_key": "k:s", "reoon_api_key": "re"})
        self.assertEqual(V.collect_keys(cfg), {"pool": G.POOL_KEY})
        # ...and not from the environment either.
        with mock.patch.dict(os.environ, {"HUNTER_API_KEY": "from-env", "APOLLO_API_KEY": "from-env"}):
            self.assertEqual(V.collect_keys(cfg), {"pool": G.POOL_KEY})


@pytest.mark.pooled
class TheAccounting(_Pooled):

    def test_a_lookup_carries_the_seat_and_a_fresh_key_each_time(self):
        self.server.answer("people", {"results": [{"id": "1"}]}, charged=3)
        G.search_people("founders of pump makers", 10)
        G.search_people("founders of valve makers", 10)
        (_, first), (_, second) = self.server.calls
        for body in (first, second):
            self.assertEqual(body["license_id"], "L-TEST")
            self.assertEqual(body["device_fp"], "D-TEST")
            self.assertEqual(body["num_results"], 10)
        self.assertNotEqual(first["idem_key"], second["idem_key"])
        self.assertRegex(first["idem_key"], r"^[A-Za-z0-9_-]{8,64}$")

    def test_spend_and_balance_are_counted_for_the_run(self):
        self.server.answer("people", {"results": []}, charged=0)
        self.server.answer("verify", {"status": "valid"}, charged=1)
        G.reset()
        G.search_people("q")
        G.check_email("a@b.com")
        G.check_email("c@d.com")
        self.assertEqual(G.used(), 2)
        self.assertEqual(G.known_balance(), 98)
        G.reset()
        self.assertEqual(G.used(), 0)
        self.assertEqual(G.known_balance(), 98)             # a new run keeps the balance

    def test_an_empty_pool_stops_every_later_call_without_asking(self):
        self.server.fail("people", _empty_pool(balance=0))
        G.reset()
        self.assertIsNone(G.search_people("q"))
        self.assertIn("run out of credits", G.exhausted())
        self.assertEqual(G.known_balance(), 0)
        asked = len(self.server.calls)
        self.assertIsNone(G.search_people("another"))
        self.assertEqual(G.check_email("a@b.com"), "")
        self.assertEqual(G.find_email("Asha", "Rao", "rao.in"), ("", "", ""))
        with self.assertRaises(G.OutOfCredits):
            G.ask("hi", "draft")
        self.assertEqual(len(self.server.calls), asked)     # not one more round trip
        G.reset()                                            # a top-up, then a new run
        self.assertEqual(G.exhausted(), "")

    def test_a_pool_too_short_for_one_lookup_can_still_buy_a_cheaper_one(self):
        """Two credits left cannot buy a 3-credit search but can buy a 1-credit
        check — one refusal must not switch every other lookup off."""
        self.server.fail("people", _empty_pool(balance=2, needed=3))
        self.server.answer("verify", {"status": "valid"}, charged=1)
        self.assertIsNone(G.search_people("q"))
        self.assertEqual(G.exhausted(), "")
        self.assertEqual(G.known_balance(), 2)
        self.assertEqual(G.check_email("a@b.com"), "valid")

    def test_status_remembers_the_price_list_and_what_is_switched_on(self):
        self.assertEqual(G.rate("people_search", 7), 7)     # never asked: the default
        self.assertTrue(G.ready("people"))                  # never asked: try it
        out = G.status()
        self.assertEqual(out["balance"], 100)
        self.assertEqual(G.rate("people_search", 7), 3)
        self.assertEqual(G.rate("email_find"), 2)
        self.assertEqual(G.rate("no_such_action"), 1)
        self.assertEqual(G.known_balance(), 100)
        G.forget()
        G.set_transport(mock.Mock(return_value={"balance": 5, "rates": {},
                                                "ready": {"people": False}}))
        G.status()
        self.assertFalse(G.ready("people"))
        self.assertTrue(G.ready("llm"))

    def test_a_topped_up_balance_lifts_an_earlier_refusal(self):
        self.server.fail("people", _empty_pool(balance=0))
        G.search_people("q")
        self.assertTrue(G.exhausted())
        self.server.balance = 50
        G.status()
        self.assertEqual(G.exhausted(), "")


@pytest.mark.pooled
class TheServerMayBeOlderThanTheApp(_Pooled):
    """The owner's app shows a blank "Credits" pill because the hosted licence
    server has no /v1/leads routes yet (24-Sep-2026). A 404 with no error
    envelope is that, and is said once in words rather than as "rejected"."""

    def _old_server(self):
        from licensing.client import ServerError
        G.set_transport(None)                                   # the real call, patched below
        patch = mock.patch("licensing.client.call",
                           side_effect=ServerError("http_404", "The licence server rejected this request."))
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_route_the_server_does_not_have_says_the_server_needs_updating(self):
        self._old_server()
        with self.assertRaises(G.GatewayError) as caught:
            G.status()
        self.assertEqual(caught.exception.code, "SERVER_OUTDATED")
        self.assertIn("server needs updating", caught.exception.message)
        self.assertIn("Nothing was charged", caught.exception.message)
        self.assertTrue(G.outdated())

    def test_every_lookup_then_reads_as_not_ready_and_fails_quietly_with_nothing_charged(self):
        self._old_server()
        self.assertIsNone(G.search_people("q"))
        self.assertEqual(G.check_email("a@b.com"), "")
        self.assertFalse(G.ready("people"))
        self.assertFalse(G.ready("find_email"))
        self.assertEqual(G.used(), 0)
        with self.assertRaises(G.GatewayError):
            G.credit_usage()

    def test_an_error_the_server_named_is_not_mistaken_for_an_old_server(self):
        from licensing.client import ServerError
        G.set_transport(None)
        patch = mock.patch("licensing.client.call",
                           side_effect=ServerError("DEVICE_NOT_ACTIVATED", "This machine isn't set up."))
        patch.start()
        self.addCleanup(patch.stop)
        with self.assertRaises(G.GatewayError) as caught:
            G.status()
        self.assertEqual(caught.exception.code, "DEVICE_NOT_ACTIVATED")
        self.assertFalse(G.outdated())

    def test_the_next_answer_that_is_not_a_404_clears_it(self):
        G._state["outdated"] = True
        with mock.patch("licensing.client.call", return_value={"balance": 5, "rates": {}, "ready": {}}):
            G.set_transport(None)
            G.status()
        self.assertFalse(G.outdated())
        self.assertTrue(G.ready("people"))


@pytest.mark.pooled
class TheLookups(_Pooled):

    def test_find_people_gives_the_rows_or_none_when_it_failed(self):
        self.server.answer("people", {"results": [{"id": "a"}, {"id": "b"}]}, charged=3)
        self.assertEqual(G.search_people("q", 999), [{"id": "a"}, {"id": "b"}])
        self.assertEqual(self.server.calls[0][1]["num_results"], 50)     # capped
        self.server.answer("people", {"results": []}, charged=0)
        self.assertEqual(G.search_people("q"), [])           # answered: nobody
        self.server.fail("people", G.GatewayError("PROVIDER_ERROR", "Exa is down."))
        self.assertIsNone(G.search_people("q"))               # failed: not "nobody"
        self.server.answer("people", {"unexpected": 1}, charged=0)
        self.assertIsNone(G.search_people("q"))

    def test_company_website_and_news_rows(self):
        self.server.answer("company", {"results": [{"url": "https://acme.com"}]})
        self.server.answer("domain", {"results": [{"url": "https://acme.com", "title": "Acme"}]})
        self.server.answer("signals", {"results": [{"url": "https://news.example/a"}]})
        self.assertEqual(G.company_rows("Acme"), [{"url": "https://acme.com"}])
        self.assertEqual(G.website_rows("Acme")[0]["title"], "Acme")
        rows = G.news_rows("Acme", focus="new plant", exclude_domains=("rival.com",),
                           num_results=4)
        self.assertEqual(rows, [{"url": "https://news.example/a"}])
        body = dict(self.server.calls)["signals"]
        self.assertEqual(body["exclude_domains"], ["rival.com"])
        self.assertEqual(body["num_results"], 4)
        self.server.fail("signals", G.GatewayError("UNREACHABLE", "offline"))
        self.assertIsNone(G.news_rows("Acme"))

    def test_the_model_call_returns_text_or_raises(self):
        self.server.answer("llm", {"text": "SUBJECT: Hi\nBODY: Hello"})
        self.assertEqual(G.ask("write", "draft", temperature=0.4), "SUBJECT: Hi\nBODY: Hello")
        body = self.server.calls[0][1]
        self.assertEqual(body["purpose"], "draft")
        self.assertEqual(body["temperature"], 0.4)
        self.server.answer("llm", {"text": "   "})
        with self.assertRaises(G.GatewayError):
            G.ask("write", "draft")
        self.server.fail("llm", G.GatewayError("GATEWAY_DISABLED", "Switched off."))
        with self.assertRaises(G.GatewayError):
            G.ask("write", "qualify", json_mode=True)

    def test_a_check_and_a_find_say_nothing_when_nobody_answered(self):
        self.server.answer("verify", {"status": "catch-all"})
        self.server.answer("find-email", {"email": "asha@rao.in", "status": "valid",
                                          "provider": "hunter"}, charged=2)
        self.assertEqual(G.check_email("a@b.com"), "catch-all")
        self.assertEqual(G.find_email("Asha", "Rao", "rao.in"),
                         ("asha@rao.in", "valid", "hunter"))
        self.server.answer("find-email", {}, charged=0)
        self.assertEqual(G.find_email("Asha", "Rao", "rao.in"), ("", "", ""))
        self.server.fail("verify", G.GatewayError("PROVIDER_ERROR", "no verifier answered"))
        self.assertEqual(G.check_email("a@b.com"), "")


# ── the engine's seams ───────────────────────────────────────────────────────

@pytest.mark.pooled
class TheEngineAsksTheGateway(_Pooled):
    """Each provider call already took an `api_key`; in the pool that key is the
    sentinel and the ONE branch at the call site sends it to the gateway. What
    is done with the answer is unchanged."""

    def test_finding_people(self):
        self.server.answer("people", {"results": [{"id": "p1"}]}, charged=3)
        self.assertEqual(S._exa_people("q", G.POOL_KEY, 20), [{"id": "p1"}])
        self.server.fail("people", G.GatewayError("PROVIDER_ERROR", "down"))
        self.assertIsNone(S._exa_people("q", G.POOL_KEY, 20))

    def test_a_company_lookup(self):
        self.server.answer("company", {"results": [{
            "url": "https://www.acmepumps.com",
            "entities": [{"type": "company", "properties": {
                "name": "Acme Pumps", "workforce": {"total": 420},
                "headquarters": {"city": "Vadodara", "country": "India"}}}]}]})
        got = S._exa_company("Acme Pumps", G.POOL_KEY)
        self.assertEqual(got["headcount"], 420)
        self.assertEqual(got["hq"], "Vadodara, India")
        self.server.fail("company", G.GatewayError("PROVIDER_ERROR", "down"))
        self.assertIsNone(S._exa_company("Acme Pumps", G.POOL_KEY))

    def test_a_website_is_a_real_company_site_not_a_directory(self):
        self.server.answer("domain", {"results": [
            {"url": "https://www.justdial.com/acme", "title": "Acme - Justdial"},
            {"url": "https://www.acmepumps.com/about", "title": "Acme Pumps"}]})
        self.assertEqual(E._real_domain("Acme Pumps", G.POOL_KEY), "acmepumps.com")
        self.server.fail("domain", G.GatewayError("PROVIDER_ERROR", "down"))
        self.assertEqual(E._real_domain("Acme Pumps", G.POOL_KEY), "")

    def test_enrich_writes_the_domain_and_never_an_address(self):
        self.server.answer("domain", {"results": [
            {"url": "https://www.acmepumps.com", "title": "Acme Pumps"}]})
        lead = Lead(name="Asha Rao", title="Owner", company="Acme Pumps", email="")
        E.enrich([lead], G.POOL_KEY)
        self.assertEqual(lead.extra.get("company_domain"), "acmepumps.com")
        self.assertEqual(lead.email, "")

    def test_why_now_news(self):
        self.server.answer("signals", {"results": [{
            "url": "https://news.example/acme-plant", "title": "Acme opens a new plant",
            "publishedDate": "2026-09-01T00:00:00.000Z",
            "highlights": ["Acme Pumps is investing in automation."]}]})
        provider = ExaSignalProvider(G.POOL_KEY)
        lead = Lead(name="Asha Rao", title="Owner", company="Acme Pumps")
        got = provider.fetch(lead, focus="new plant")
        self.assertFalse(provider.errored)
        self.assertEqual(self.server.ops(), ["signals"])
        self.assertTrue(got)
        self.server.fail("signals", G.GatewayError("PROVIDER_ERROR", "down"))
        self.assertEqual(provider.fetch(lead), [])
        self.assertTrue(provider.errored)                     # a failure is not "no news"

    def test_qualifying_asks_the_model_through_the_gateway(self):
        self.server.answer("llm", {"text": "not json"})
        lead = Lead(name="Asha Rao", title="Owner", company="Acme Pumps")
        got = Qualifier(G.POOL_KEY).qualify(lead, [], "automation")
        self.assertEqual(got.status, "non_json")
        self.assertEqual(self.server.calls[0][1]["purpose"], "qualify")
        self.assertTrue(self.server.calls[0][1]["json_mode"])
        self.server.fail("llm", _empty_pool(balance=0, needed=1))
        got = Qualifier(G.POOL_KEY).qualify(lead, [], "automation")
        self.assertEqual(got.status, "qualify_error")         # a status on the row, no crash

    def test_drafting_asks_the_model_through_the_gateway(self):
        self.server.answer("llm", {"text": "SUBJECT: Quick idea\nBODY:\nHi Asha, hello."})
        dossier = _dos("Asha Rao", 90, "asha@rao.in", "valid")
        draft = R.draft_for(dossier, "automation", {"api_key": G.POOL_KEY})
        self.assertEqual(self.server.calls[0][1]["purpose"], "draft")
        self.assertEqual(draft.subject, "Quick idea")
        self.server.fail("llm", G.GatewayError("PROVIDER_ERROR", "down"))
        fallback = R.draft_for(dossier, "automation", {"api_key": G.POOL_KEY})
        self.assertIn("unreachable", fallback.note)           # degrades, never fails

    def test_checking_an_address(self):
        self.server.answer("verify", {"status": "valid"})
        keys = V.collect_keys(G.effective_cfg({}))
        self.assertEqual(V.verify_email("asha@rao.in", keys), "valid")
        self.assertEqual(V.verify_email("", keys), "")
        self.assertEqual(self.server.ops(), ["verify"])

    def test_finding_an_address_asks_a_finder_and_checks_what_it_sold(self):
        self.server.answer("find-email", {"email": "asha.rao@rao.in", "status": "",
                                          "provider": "hunter"}, charged=2)
        self.server.answer("verify", {"status": "valid"})
        lead = Lead(name="Asha Rao", title="Owner", company="Rao Works")
        lead.extra["company_domain"] = "rao.in"
        V.find_and_verify(lead, V.collect_keys(G.effective_cfg({})))
        self.assertEqual(lead.email, "asha.rao@rao.in")
        self.assertEqual(lead.extra["email_source"], "hunter")
        self.assertEqual(lead.extra["email_check"], "valid")
        self.assertEqual(self.server.ops(), ["find-email", "verify"])

    def test_nobody_found_leaves_no_address_and_a_sold_one_is_not_bought_twice(self):
        self.server.answer("find-email", {}, charged=0)
        lead = Lead(name="Asha Rao", title="Owner", company="Rao Works")
        lead.extra["company_domain"] = "rao.in"
        keys = V.collect_keys(G.effective_cfg({}))
        V.find_and_verify(lead, keys)
        self.assertEqual(lead.email, "")                      # never a guess
        self.assertEqual(self.server.ops(), ["find-email"])
        # A finder already sold this one; unconfirmed, it is not asked again.
        held = Lead(name="Asha Rao", title="Owner", company="Rao Works",
                    email="asha@rao.in")
        held.extra.update({"company_domain": "rao.in", "email_source": "hunter"})
        self.server.calls.clear()
        self.server.answer("verify", {"status": "unknown"})
        V.find_and_verify(held, keys)
        self.assertEqual(self.server.ops(), ["verify"])

    def test_a_pool_that_finds_nobody_is_no_email_and_never_reaches_a_customers_key(self):
        """The server's finder knew nobody: the lead has no address. Nothing
        falls through to a finder key the customer saved before the pool."""
        self.server.answer("find-email", {}, charged=0)
        lead = Lead(name="Asha Rao", title="Owner", company="Rao Works")
        lead.extra["company_domain"] = "rao.in"
        def boom(*_a, **_k):
            raise AssertionError("a customer's finder key was used")
        finders = [("apollo_api_key", "Apollo", boom), ("hunter_api_key", "Hunter", boom)]
        # Even handed a customer's finder keys beside the sentinel (which
        # collect_keys never does), the pooled path returns before any finder.
        keys = {"pool": G.POOL_KEY, "apollo_api_key": "apo", "hunter_api_key": "hun"}
        with mock.patch.object(V, "_FINDERS", finders):
            V.find_and_verify(lead, keys)
        self.assertEqual(lead.email, "")
        self.assertEqual(self.server.ops(), ["find-email"])

    def test_a_bulk_check_stops_when_the_pool_runs_dry(self):
        self.server.fail("verify", _empty_pool(balance=0, needed=1))
        dossiers = []
        for i in range(4):
            d = _dos(f"Person Number{i}", 90 - i, f"p{i}@x.com", "")
            d.verdict = "hot"
            dossiers.append(d)
        keys = V.collect_keys(G.effective_cfg({}))
        G.reset()
        done = V.verify_reachable(dossiers, keys, limit=4)
        self.assertLess(done, 4)
        self.assertEqual(self.server.ops().count("verify"), 1)   # one refusal, then none


# ── the screen ───────────────────────────────────────────────────────────────

class _PooledScreen(_Workbench):
    """The workbench on the pool. Its balance read runs a worker thread, which a
    test never starts: the status is handed to the screen the way the worker's
    `done` signal would."""

    def setUp(self):
        super().setUp()
        self.server = FakeServer(balance=1240)
        G.set_transport(self.server)
        seat = mock.patch.object(
            G, "_auth_body",
            lambda **extra: {"license_id": "L-TEST", "device_fp": "D-TEST",
                             "app_version": "0.0.0", **extra})
        seat.start()
        self.addCleanup(seat.stop)
        self._saved_attrs["_refresh_credits"] = self._WB.LeadsWorkbench._refresh_credits
        self._WB.LeadsWorkbench._refresh_credits = lambda _self: None
        self.asked_box = []

        def question(_parent, title, text, *args, **kwargs):
            self.asked_box.append((title, text))
            return QMessageBox.StandardButton.Yes
        patch = mock.patch.object(QMessageBox, "question", staticmethod(question))
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        super().tearDown()
        G.forget()

    def _bench(self, balance: int = 1240):
        wb = self._WB.LeadsWorkbench({"exa_api_key": "live-exa", "api_key": "gsk_live"})
        self.server.balance = balance
        wb._on_credits(G.status())
        # 24-Nov-2026: on the credit pool the screen now starts on Apollo (the server asks it for free). These
        # tests are about what an EXA search costs in credits, so they pick Exa, as an owner can.
        wb._set_source("exa")
        return wb


@pytest.mark.pooled
class TheScreenOnThePool(_PooledScreen):

    def test_the_balance_pill_is_offered_and_says_what_is_left(self):
        wb = self._bench()
        self.assertIs(wb.credits_button(), wb._credits_btn)
        self.assertEqual(wb._credits_btn.text(), "1,240 credits")
        wb._on_credits({"balance": 1, "rates": RATES})
        self.assertEqual(wb._credits_btn.text(), "1 credit")
        wb._on_credits_failed("Couldn't reach Prism's licence server.")
        self.assertIn("Couldn't reach", wb._credits_btn.toolTip())

    def test_direct_mode_has_no_pill(self):
        wb = self._bench()
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            self.assertIsNone(wb.credits_button())

    def test_the_panel_puts_the_pill_before_the_batch_actions(self):
        from addons.leads.panel import LeadsPanel
        panel = LeadsPanel({})
        panel._build()
        row = panel.header.actions_row
        self.assertEqual(row.count(), 4)                        # ?, pill, Export, Send all
        # The pill is the workbench's first action, right after the "?" and ahead of
        # the batch actions. (There used to be an "AI tools" button between them;
        # the header dropped it, 788c29a, so this counts from the "?" now.)
        self.assertIs(row.itemAt(1).widget(), panel._workbench.credits_button())

    def test_the_customer_is_shown_no_key_boxes(self):
        wb = self._bench()
        self.assertTrue(wb._source_row.isHidden())
        self.assertTrue(wb._keys_box.isHidden())
        self.assertTrue(all(w.isHidden() for w in wb._byo_widgets))
        self.assertEqual(wb._keys_toggle.text(), "Approved claims")

    def test_the_cockpit_says_credits_and_verify_is_not_called_free(self):
        wb = self._bench()
        page = wb._cockpit.leads
        self.assertEqual(page._b_verify.text(), "Verify")
        self.assertIn("credit", page._b_verify.toolTip())
        self.assertNotIn("free", page._b_emails.toolTip().replace("Nothing", ""))
        badges = [l.text() for l in wb._cockpit.findChildren(QLabel)]
        self.assertIn("Your credits · your inbox", badges)
        self.assertNotIn("Local · BYO-key · your inbox", badges)

    def test_the_pill_turns_red_when_credits_are_nearly_gone(self):
        wb = self._bench(balance=1240)
        self.assertEqual(wb._credits_btn.styleSheet(), "")
        self.assertNotIn("nearly out", wb._credits_btn.toolTip())
        wb._on_credits({"balance": 5, "rates": RATES})           # under three 3-credit searches
        self.assertIn("color", wb._credits_btn.styleSheet())
        self.assertIn("nearly out of credits", wb._credits_btn.toolTip())
        wb._on_credits({"balance": 0, "rates": RATES})
        self.assertEqual(wb._credits_btn.text(), "0 credits")
        self.assertIn("out of credits", wb._credits_btn.toolTip())
        wb._on_credits({"balance": 9, "rates": RATES})            # exactly three searches' worth: fine
        self.assertEqual(wb._credits_btn.styleSheet(), "")

    def test_the_pill_says_what_a_click_will_show(self):
        """The usage, the price list and how to get more live behind the pill
        (tests/test_leads_credit_pages.py holds the screens themselves)."""
        wb = self._bench()
        tip = wb._credits_btn.toolTip()
        self.assertIn("how many are left", tip)
        self.assertIn("how to get more", tip)
        wb._on_credits_failed("Couldn't reach Prism's licence server.")
        self.assertTrue(wb._credits_btn.toolTip().startswith("Couldn't reach"))

    def test_a_lookup_the_server_has_not_switched_on_is_said_before_it_runs(self):
        wb = self._bench()
        self.assertEqual(wb._pool_blocker("people"), "")
        G._state["ready"] = {"people": False}
        self.assertIn("isn't switched on", wb._pool_blocker("people"))
        self.assertIn("haven't been charged", wb._pool_blocker("people"))

    def test_an_old_server_is_said_before_a_worker_starts(self):
        wb = self._bench()
        G._state["outdated"] = True
        for op in ("people", "find_email", "llm"):
            self.assertIn("server needs updating", wb._pool_blocker(op))

    def test_an_empty_pool_is_said_before_a_worker_starts(self):
        wb = self._bench(balance=0)
        self.assertIn("no credits left", wb._pool_blocker("people"))
        wb = self._bench(balance=5)
        self.assertEqual(wb._pool_blocker("people"), "")

    def test_a_big_e_mail_batch_asks_in_credits_and_names_the_balance(self):
        wb = self._bench()
        self.assertTrue(wb._confirm_emails(5))                # up to ten: no question
        self.assertEqual(self.asked_box, [])
        self.assertTrue(wb._confirm_emails(20))
        title, text = self.asked_box[-1]
        self.assertEqual(title, "Find e-mails")
        self.assertIn("up to 80 credits", text)               # 20 x (website 1 + find 2 + check 1)
        self.assertIn("You have 1,240 credits.", text)
        self.assertIn("Nothing is guessed", text)
        for vendor in ("Hunter", "Apollo", "Groq"):
            self.assertNotIn(vendor, text)

    def test_a_search_says_how_many_searches_and_that_a_blank_one_is_free(self):
        wb = self._bench()
        # The base class answers Yes to the whole search question; this asks the
        # pool's own, with the number of searches a press makes fixed.
        with mock.patch.object(wb, "_searches", return_value=(12, 0)):
            self.assertTrue(wb._confirm_pool_search(wb._filters.spec(), [], ""))
        title, text = self.asked_box[-1]
        self.assertEqual(title, "Find new people")
        self.assertIn("about 12 searches", text)
        self.assertIn("up to 36 credits", text)               # 12 x the 3-credit search
        self.assertIn("A search that finds nobody is not charged.", text)
        self.assertIn("You have 1,240 credits.", text)
        for vendor in ("Exa", "Apollo", "Groq"):
            self.assertNotIn(vendor, text)

    def test_a_search_dearer_than_the_balance_is_flagged(self):
        wb = self._bench(balance=20)
        with mock.patch.object(wb, "_searches", return_value=(12, 0)):
            wb._confirm_pool_search(wb._filters.spec(), [], "")
        self.assertIn("more than you have", self.asked_box[-1][1])
        wb = self._bench(balance=500)
        with mock.patch.object(wb, "_searches", return_value=(12, 0)):
            wb._confirm_pool_search(wb._filters.spec(), [], "")
        self.assertNotIn("more than you have", self.asked_box[-1][1])

    def test_the_line_under_find_new_people_is_in_credits(self):
        wb = self._bench()
        with mock.patch.object(wb, "_searches", return_value=(12, 0)):
            self.assertEqual(wb._pool_search_meta(wb._filters.spec(), []),
                             "About 12 searches — up to 36 credits")
        with mock.patch.object(wb, "_searches", return_value=(0, 0)):
            self.assertEqual(wb._pool_search_meta(wb._filters.spec(), []),
                             "Searches for new people")

    def test_a_runs_spend_ends_its_line_and_an_empty_pool_says_why_it_stopped(self):
        wb = self._bench()
        self.assertEqual(wb._used_note(), "")
        G._state["used"] = 96
        self.assertIn("96 credits used", wb._used_note())
        G._state["exhausted"] = "You've run out of credits."
        self.assertIn("out of credits", wb._used_note())

    def test_saving_settings_never_writes_a_key(self):
        """The hidden boxes hold whatever an older build saved; writing it back
        would keep a provider key on a customer's machine."""
        wb = self._bench()
        wb._exa.setText("a-key-typed-into-a-hidden-box")
        with mock.patch.object(wb, "_save_cfg") as save:
            wb._save_keys()
        save.assert_not_called()
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            with mock.patch.object(wb, "_save_cfg") as save:
                wb._save_keys()
            self.assertTrue(save.called)                     # the dev switch still saves

    def test_the_verifier_key_card_is_not_shown_to_a_customer(self):
        from widgets.settings_panel import SettingsPanel
        host = mock.MagicMock()             # `self` — only what _agents asks of it
        host.cfg = {}
        column = mock.MagicMock()           # the layout the cards are added to
        SettingsPanel._agents(host, column)
        host._verifier_card.assert_not_called()
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            host = mock.MagicMock()
            host.cfg = {}
            SettingsPanel._agents(host, mock.MagicMock())
            host._verifier_card.assert_called_once()


@pytest.mark.pooled
class SendAllCountsOnlyWhatCanBeMailed(_PooledScreen):
    """A guessed address is set aside when a lead is read back (24-Sep-2026),
    and reach.send skips a draft with no address — so "N ready to send" and
    Send all's enabled state must say the same."""

    def _draft(self, email):
        from prospector.reach import Draft
        return Draft(dossier=_dos("Asha Rao", 90, email, "valid" if email else ""),
                     subject="Hi", body="Hello")

    def test_a_draft_with_no_address_is_not_ready_to_send(self):
        wb = self._bench()
        real, blank = self._draft("asha@rao.in"), self._draft("")
        self.assertEqual(wb._sendable([real, blank]), [real])
        self.assertEqual(wb._sendable([blank]), [])

    def test_an_address_of_only_spaces_is_no_address(self):
        wb = self._bench()
        spaces = self._draft("   ")
        self.assertEqual(wb._sendable([spaces]), [])

    def test_a_mailed_draft_is_still_left_out(self):
        wb = self._bench()
        sent = self._draft("asha@rao.in")
        sent.status = "sent"
        self.assertEqual(wb._sendable([sent]), [])


if __name__ == "__main__":
    unittest.main()
