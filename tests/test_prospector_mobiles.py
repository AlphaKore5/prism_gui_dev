"""Find mobiles — one person's own mobile number, from Apollo through the licence
server (3-Nov-2026).

Apollo reveals a mobile in minutes, so a lookup is two calls: a free START and
then READS of the same lookup. These tests hold the app to:

  · asking for exactly the people who need a number and can be looked up (a first
    and last name and a company domain), never for someone who already has a mobile;
  * every lookup started first and all of them read together, so ten people wait as
    long as one;
  · every read of one lookup carrying the SAME idempotency key, which is what stops a
    number that arrives on the fifth read being paid for five times;
  · recording a number with where it came from, beside — never over — a number the
    person came with;
  · an empty pool, an old server and a lookup that never finishes each saying so.

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
from prospector import gateway as G                    # noqa: E402
from prospector import mobiles as M                    # noqa: E402
from prospector import phones as PH                    # noqa: E402
from prospector.models import Lead                     # noqa: E402

MOBILE = "+919825012345"


def lead(name="Asha Rao", company="Acme Works", email="", domain="acme.com", **kw):
    extra = kw.pop("extra", {})
    extra = dict(extra)
    if domain:
        extra.setdefault("company_domain", domain)
    l = Lead(name=name, title="Owner", company=company, email=email, **kw)
    l.extra = extra
    return l


class FakeApollo:
    """Stands in for /v1/leads/mobile-start and /mobile-result."""

    def __init__(self):
        self.calls: list = []
        self.next_id = 0
        self.runs: dict = {}                    # run id -> list of answers, one per read
        self.start_error: Exception | None = None
        self.balance = 100

    def lookup(self, *answers):
        """The answers the next started lookup gives, one per read: "pending", or
        a number string, or "" for 'Apollo had none'."""
        self.queue = list(answers)
        return self

    def __call__(self, path, body):
        op = path.rsplit("/", 1)[-1]
        self.calls.append((op, body))
        if op == "status":
            return {"balance": self.balance, "rates": {}, "ready": {}}
        if op == "mobile-start":
            if self.start_error:
                raise self.start_error
            self.next_id += 1
            run_id = "RUN%07d" % self.next_id
            self.runs[run_id] = list(getattr(self, "queue", ["pending", MOBILE]))
            return {"run_id": run_id, "balance": self.balance}
        if op == "mobile-result":
            answers = self.runs[body["run_id"]]
            answer = answers.pop(0) if len(answers) > 1 else answers[0]
            if answer == "pending":
                return {"result": {"state": "pending", "phone": "", "kind": ""},
                        "charged": 0, "balance": self.balance}
            charged = 10 if answer else 0
            self.balance -= charged
            return {"result": {"state": "done", "phone": answer, "kind": "mobile" if answer else ""},
                    "charged": charged, "balance": self.balance}
        raise AssertionError(path)

    def ops(self):
        return [op for op, _ in self.calls]


class FakePool:
    """Stands in for the licence server's /v1/leads/mobile-find (24-Nov-2026): three sources asked in turn
    by the server, one request, one charge, only when a number comes back."""

    def __init__(self):
        self.calls: list = []
        self.balance = 100
        self.answer = {"phone": MOBILE, "kind": "mobile", "provider": "ai_ark"}   # "" phone = none found
        self.error: Exception | None = None

    def __call__(self, path, body):
        op = path.rsplit("/", 1)[-1]
        self.calls.append((op, body))
        if op == "status":
            return {"balance": self.balance, "rates": {}, "ready": {}}
        if op == "mobile-find":
            if self.error:
                raise self.error
            found = bool(self.answer.get("phone"))
            charged = 10 if found else 0
            self.balance -= charged
            return {"result": dict(self.answer), "units": 1 if found else 0, "charged": charged,
                    "balance": self.balance}
        raise AssertionError(path)

    def asked(self):
        return [body for op, body in self.calls if op == "mobile-find"]


@pytest.mark.pooled
class FindingMobiles(unittest.TestCase):
    """On the credit pool the LICENCE SERVER asks the three sources; the app sends one request a person."""

    def setUp(self):
        self.server = FakePool()
        G.set_transport(self.server)
        patch = mock.patch.object(
            G, "_auth_body",
            lambda **extra: {"license_id": "L-TEST", "device_fp": "D-TEST",
                             "app_version": "0.0.0", **extra})
        patch.start()
        self.addCleanup(patch.stop)
        import requests
        guard = mock.patch.object(requests, "post", side_effect=AssertionError("called requests"))
        guard.start()
        self.addCleanup(guard.stop)

    def tearDown(self):
        G.forget()

    def find(self, leads, **kw):
        return M.find(leads, {}, **kw)

    # -- who is asked for ----------------------------------------------------
    def test_only_people_who_can_be_looked_up_are_asked_for(self):
        ok = lead()
        no_domain = lead(name="Ravi Shah", domain="", company="Nowhere")
        one_name = lead(name="Madonna")
        has = lead(name="Neha Iyer", extra={"phones": [{"number": MOBILE, "kind": "mobile",
                                                        "scope": "person"}]})
        self.assertTrue(M.needs_mobile(ok))
        self.assertFalse(any(M.needs_mobile(x) for x in (no_domain, one_name, has)))
        out = self.find([ok, no_domain, one_name, has])
        self.assertEqual((out["asked"], len(self.server.asked())), (1, 1))

    def test_a_person_is_looked_up_by_name_company_domain_and_title(self):
        self.find([lead(name="Asha K. Rao", domain="www.new.acme.co.in")])
        [body] = self.server.asked()
        self.assertEqual((body["first_name"], body["last_name"], body["domain"]),
                         ("Asha", "Rao", "acme.co.in"))     # a website's sub-domain knows nobody
        self.assertEqual((body["company"], body["title"]), ("Acme Works", "Owner"))

    def test_a_company_number_does_not_stop_a_persons_mobile_being_looked_up(self):
        self.assertTrue(M.needs_mobile(lead(phone="+912265551234")))

    # -- the lookup ----------------------------------------------------------
    def test_a_number_found_is_recorded_with_the_source_the_server_named(self):
        a = lead()
        self.server.answer = {"phone": MOBILE, "kind": "mobile", "provider": "reversecontact"}
        out = self.find([a])
        self.assertEqual((out["asked"], out["found"], out["given"], out["failed"], out["by"]),
                         (1, 1, 1, 0, {"reversecontact": 1}))
        self.assertEqual(a.phone, MOBILE)
        [p] = a.extra["phones"]
        self.assertEqual((p["number"], p["kind"], p["scope"], p["provider"], p["checked"]),
                         (MOBILE, "mobile", "person", "reversecontact", "format"))

    def test_nobody_having_a_number_is_not_a_failure_and_changes_nothing(self):
        a = lead()
        self.server.answer = {"phone": "", "kind": "", "provider": ""}
        out = self.find([a])
        self.assertEqual((out["asked"], out["found"], out["given"], out["failed"]), (1, 0, 0, 0))
        self.assertEqual((a.phone, a.extra.get("phones")), ("", None))

    def test_a_number_the_person_came_with_is_never_replaced(self):
        a = lead(phone="+919000011111")
        out = self.find([a])
        self.assertEqual((out["given"], a.phone), (1, "+919000011111"))
        self.assertEqual([p["number"] for p in a.extra["phones"]], [MOBILE])

    def test_a_company_number_find_phones_put_there_gives_way_to_the_persons_mobile(self):
        a = lead()
        PH.apply(a, {"phone": "+912265551234", "kind": "landline", "source_kind": "own_website"})
        self.assertEqual(a.phone, "+912265551234")
        self.find([a])
        self.assertEqual(a.phone, MOBILE)
        self.assertEqual({p["scope"] for p in a.extra["phones"]}, {"company", "person"})

    def test_a_number_already_on_the_lead_is_not_added_twice(self):
        a = lead()
        self.assertTrue(M.apply(a, MOBILE))
        self.assertFalse(M.apply(a, MOBILE))
        self.assertEqual(len(a.extra["phones"]), 1)

    def test_what_was_charged_is_the_servers_own_count(self):
        self.find([lead(name="Asha Rao"), lead(name="Ravi Shah")])
        self.assertEqual(G.used(), 20)                              # 10 a number, only for numbers found

    # -- what can go wrong ---------------------------------------------------
    def test_an_empty_pool_stops_the_batch_and_says_why(self):
        self.server.error = G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.",
                                           {"balance": 0, "needed": 10})
        people = [lead(name="Person%s Surname%s" % (chr(97 + i), chr(97 + i))) for i in range(10)]
        out = self.find(people)
        self.assertEqual(out["found"], 0)
        self.assertIn("You've run out of credits.", out["why"])
        self.assertEqual(out["failed"], 10)
        self.assertLessEqual(len(self.server.asked()), M.WORKERS)       # the rest were never even tried

    def test_an_old_server_says_so_once(self):
        self.server.error = G.GatewayError("SERVER_OUTDATED", G.OUTDATED_MESSAGE)
        out = self.find([lead(name="Asha Rao"), lead(name="Ravi Shah")])
        self.assertEqual(out["why"], [G.OUTDATED_MESSAGE])
        self.assertEqual((out["asked"], out["failed"]), (0, 2))

    def test_a_failure_of_one_lookup_does_not_stop_the_others(self):
        calls = {"n": 0}
        real = self.server

        def flaky(path, body):
            if path.endswith("mobile-find"):
                calls["n"] += 1
                if body["first_name"] == "Ravi":
                    raise G.GatewayError("PROVIDER_ERROR", "A data provider did not answer.")
            return real(path, body)
        G.set_transport(flaky)
        out = self.find([lead(name="Asha Rao"), lead(name="Ravi Shah"), lead(name="Neha Iyer")])
        self.assertEqual((out["asked"], out["found"], out["failed"]), (2, 2, 1))

    def test_at_most_a_page_of_people_per_press(self):
        people = [lead(name="Person%s Surname%s" % (chr(97 + i), chr(97 + i))) for i in range(M.LIMIT + 10)]
        out = self.find(people)
        self.assertEqual(out["asked"], M.LIMIT)

    def test_progress_is_reported_as_lookups_finish(self):
        seen = []
        M.find([lead(name="Asha Rao"), lead(name="Ravi Shah")], {}, on_progress=lambda i, n: seen.append((i, n)))
        self.assertEqual(seen[0], (0, 2))
        self.assertEqual(seen[-1], (2, 2))

    def test_the_developers_own_key_mode_without_a_monid_key_says_what_it_needs(self):
        # 24-Nov-2026: direct mode HAS a mobile source now (the owner's own Monid wallet, see
        # FindingMobilesDirect below), so it only says "no" when there is no Monid key, and says which.
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1", "MONID_API_KEY": ""}):
            out = M.find([lead()], {})
        self.assertEqual((out["asked"], self.server.calls), (0, []))
        self.assertEqual(out["why"], [M.NO_KEY])
        self.assertIn("Monid key", out["why"][0])


class AMobileTheDigitsCannotTell(unittest.TestCase):
    """24-Nov-2026, found with a real lookup: a number starting 6-8 is recorded "unknown" when the source does not
    say it is a mobile. It IS the person's number, and counting only "mobile" asked for it again and charged again."""

    def test_an_unknown_kind_still_counts_as_the_persons_mobile_and_is_not_asked_for_again(self):
        a = lead()
        self.assertTrue(M.apply(a, "+917123450304", "unknown", "contactout"))
        self.assertTrue(M.has_mobile(a))
        self.assertFalse(M.needs_mobile(a))
        self.assertEqual(M.entry_of(a)["provider"], "contactout")

    def test_a_landline_or_toll_free_number_is_not_the_persons_mobile(self):
        for kind in ("landline", "toll_free"):
            a = lead()
            M.apply(a, "+912265551234", kind, "contactout")
            self.assertFalse(M.has_mobile(a), kind)

    def test_the_direct_lookup_does_not_ask_twice_for_the_same_person(self):
        asked = []

        def find_one(first, last, domain, *, key, company="", title=""):
            asked.append(first)
            return {"number": "+917123450304", "kind": "unknown", "provider": "contactout",
                    "tried": [("contactout", "found")]}
        a = lead()
        M.find_direct([a], {"monid_api_key": "K"}, find_one=find_one)
        M.find_direct([a], {"monid_api_key": "K"}, find_one=find_one)
        self.assertEqual(asked, ["Asha"])                                   # the second press found nobody to ask for


class FindingMobilesDirect(unittest.TestCase):
    """The same job on the owner's OWN Monid wallet (24-Nov-2026): three sources asked in turn, cheapest
    first, each charging only for a number it returns (prospector/phone_waterfall.py). The engine is
    handed a stand-in for the waterfall: nothing here reaches Monid."""

    def setUp(self):
        self.asked: list = []
        self.answers: dict = {}                 # person's first name -> the waterfall's answer
        self.refuse: str = ""

    def find_one(self, first, last, domain, *, key, company="", title=""):
        self.asked.append({"first": first, "last": last, "domain": domain, "key": key,
                           "company": company, "title": title})
        if self.refuse:
            raise M.monid_run.MonidError(self.refuse)
        return self.answers.get(first, {"number": "", "kind": "", "provider": "", "tried": [("ai_ark", "none")]})

    def find(self, leads, cfg=None, **kw):
        cfg = {"monid_api_key": "K"} if cfg is None else cfg
        return M.find_direct(leads, cfg, find_one=self.find_one, **kw)

    def hit(self, provider="ai_ark", number=MOBILE):
        return {"number": number, "kind": "mobile", "provider": provider, "tried": [(provider, "found")]}

    def test_without_a_monid_key_nothing_is_asked_and_it_says_which_key(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": ""}):
            out = M.find_direct([lead()], {}, find_one=self.find_one)
        self.assertEqual((out["asked"], self.asked), (0, []))
        self.assertEqual(out["why"], [M.NO_KEY])

    def test_the_key_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": "from-env"}):
            M.find_direct([lead()], {}, find_one=self.find_one)
        self.assertEqual(self.asked[0]["key"], "from-env")

    def test_find_goes_direct_when_this_is_not_the_credit_pool(self):
        self.answers["Asha"] = self.hit()
        with mock.patch.object(M.phone_waterfall, "find", self.find_one):
            out = M.find([lead()], {"monid_api_key": "K"}, sleep=lambda s: None)
        self.assertEqual((out["asked"], out["found"]), (1, 1))

    def test_only_people_who_can_be_looked_up_are_asked_for(self):
        has = lead(name="Ravi Shah", extra={"phones": [{"number": MOBILE, "scope": "person", "kind": "mobile"}]})
        no_domain = lead(name="Neha Iyer", domain="", company="Nowhere")
        self.find([lead(), has, no_domain, lead(name="Madonna")])
        self.assertEqual([a["first"] for a in self.asked], ["Asha"])

    def test_a_person_is_asked_for_by_name_and_the_companys_own_domain_with_their_title(self):
        self.find([lead()])
        ask = self.asked[0]
        self.assertEqual((ask["first"], ask["last"], ask["domain"]), ("Asha", "Rao", "acme.com"))
        self.assertEqual((ask["company"], ask["title"]), ("Acme Works", "Owner"))

    def test_a_number_is_recorded_with_the_source_that_sold_it(self):
        self.answers["Asha"] = self.hit("reversecontact")
        mine = lead()
        out = self.find([mine])
        entry = M.entry_of(mine)
        self.assertEqual((entry["number"], entry["provider"], entry["scope"]), (MOBILE, "reversecontact", "person"))
        self.assertEqual(mine.phone, MOBILE)
        self.assertEqual((out["found"], out["given"], out["by"]), (1, 1, {"reversecontact": 1}))

    def test_nobody_having_a_number_is_not_a_failure_and_changes_nothing(self):
        mine = lead()
        out = self.find([mine])
        self.assertEqual((out["asked"], out["found"], out["failed"]), (1, 0, 0))
        self.assertFalse(M.has_mobile(mine))

    def test_every_source_being_down_is_a_failure_not_nobody(self):
        self.answers["Asha"] = {"number": "", "kind": "", "provider": "", "tried": [("ai_ark", "down"), ("reversecontact", "down")]}
        out = self.find([lead()])
        self.assertEqual((out["asked"], out["failed"]), (0, 1))

    def test_a_number_the_person_came_with_is_never_replaced(self):
        self.answers["Asha"] = self.hit()
        mine = lead(phone="+919000000001")
        self.find([mine])
        self.assertEqual(mine.phone, "+919000000001")
        self.assertEqual(M.entry_of(mine)["number"], MOBILE)

    def test_a_refused_key_or_empty_wallet_stops_the_batch_and_says_so_once(self):
        self.refuse = "Your Monid wallet is empty. Top it up at monid.ai, then try again."
        out = self.find([lead(name=f"Person{i} Rao") for i in range(6)])
        self.assertEqual(out["why"], [self.refuse])
        self.assertEqual(out["found"], 0)
        self.assertLessEqual(len(self.asked), M.WORKERS)        # the rest were never asked

    def test_at_most_a_page_of_people_per_press(self):
        self.find([lead(name=f"Person{i} Rao") for i in range(M.LIMIT + 10)])
        self.assertEqual(len(self.asked), M.LIMIT)

    def test_progress_is_reported_as_lookups_finish(self):
        seen: list = []
        self.find([lead(name="Asha Rao"), lead(name="Ravi Shah")], on_progress=lambda i, n: seen.append((i, n)))
        self.assertEqual(seen[0], (0, 2))
        self.assertEqual(seen[-1], (2, 2))

    def test_the_person_panel_names_the_source_not_always_apollo(self):
        from prospector import exports as EX
        mine = lead()
        M.apply(mine, MOBILE, "mobile", "contactout")
        self.assertIn("ContactOut", EX.phone_source_of(mine))
        old = lead(name="Ravi Shah")
        M.apply(old, MOBILE)                                            # no provider given: it has always been Apollo
        self.assertIn("Apollo", EX.phone_source_of(old))
        self.assertEqual(PH.provider_label(M.entry_of(mine)), "ContactOut")
        self.assertIn("{who}", PH.person_line(M.entry_of(mine)))
        self.assertNotIn("{who}", PH.person_line(M.entry_of(old)))


@pytest.mark.pooled
class TheGatewayCalls(unittest.TestCase):
    def setUp(self):
        self.server = FakeApollo()
        G.set_transport(self.server)
        patch = mock.patch.object(
            G, "_auth_body",
            lambda **extra: {"license_id": "L-TEST", "device_fp": "D-TEST",
                             "app_version": "0.0.0", **extra})
        patch.start()
        self.addCleanup(patch.stop)

    def tearDown(self):
        G.forget()

    def test_starting_returns_the_run_id_and_charges_nothing(self):
        self.assertEqual(G.start_mobile("Asha", "Rao", "acme.com"), "RUN0000001")
        self.assertEqual(G.used(), 0)

    def test_a_failed_start_gives_the_servers_own_sentence(self):
        self.server.start_error = G.GatewayError("PROVIDER_NOT_CONFIGURED", "Not switched on yet.")
        why: list = []
        self.assertEqual(G.start_mobile("Asha", "Rao", "acme.com", why), "")
        self.assertEqual(why, ["Not switched on yet."])

    def test_a_read_counts_what_it_was_charged(self):
        self.server.lookup(MOBILE)
        run_id = G.start_mobile("Asha", "Rao", "acme.com")
        self.assertEqual(G.mobile_result(run_id), {"state": "done", "phone": MOBILE, "kind": "mobile"})
        self.assertEqual(G.used(), 10)

    def test_an_answer_that_is_not_one_this_version_can_read_is_a_failure(self):
        with mock.patch.object(G, "_raw_call", return_value={"result": {"state": "weird"}}):
            self.assertIsNone(G.mobile_result("RUN0000001"))


if __name__ == "__main__":
    unittest.main()
