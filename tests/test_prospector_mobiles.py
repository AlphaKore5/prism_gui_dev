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


@pytest.mark.pooled
class FindingMobiles(unittest.TestCase):
    def setUp(self):
        self.server = FakeApollo()
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
        self.sleeps: list = []

    def tearDown(self):
        G.forget()

    def find(self, leads, **kw):
        return M.find(leads, {}, sleep=self.sleeps.append, **kw)

    # ── who is asked for ────────────────────────────────────────────────────
    def test_only_people_who_can_be_looked_up_are_asked_for(self):
        ok = lead()
        no_domain = lead(name="Ravi Shah", domain="", company="Nowhere")
        one_name = lead(name="Madonna")
        has = lead(name="Neha Iyer", extra={"phones": [{"number": MOBILE, "kind": "mobile",
                                                        "scope": "person"}]})
        self.assertTrue(M.needs_mobile(ok))
        self.assertFalse(any(M.needs_mobile(x) for x in (no_domain, one_name, has)))
        out = self.find([ok, no_domain, one_name, has])
        self.assertEqual((out["asked"], self.server.ops().count("mobile-start")), (1, 1))

    def test_a_person_is_looked_up_by_name_and_the_companys_own_domain(self):
        self.find([lead(name="Asha K. Rao", domain="www.new.acme.co.in")])
        [(op, body)] = [c for c in self.server.calls if c[0] == "mobile-start"]
        self.assertEqual((body["first_name"], body["last_name"], body["domain"]),
                         ("Asha", "Rao", "acme.co.in"))     # a website's sub-domain knows nobody

    def test_a_company_number_does_not_stop_a_persons_mobile_being_looked_up(self):
        self.assertTrue(M.needs_mobile(lead(phone="+912265551234")))

    # ── the lookup ──────────────────────────────────────────────────────────
    def test_a_number_that_arrives_late_is_found_and_recorded_with_where_it_came_from(self):
        a = lead()
        self.server.lookup("pending", "pending", MOBILE)
        out = self.find([a])
        self.assertEqual((out["asked"], out["found"], out["given"], out["failed"], out["pending"]),
                         (1, 1, 1, 0, 0))
        self.assertEqual(a.phone, MOBILE)
        [p] = a.extra["phones"]
        self.assertEqual((p["number"], p["kind"], p["scope"], p["provider"], p["checked"]),
                         (MOBILE, "mobile", "person", "apollo", "format"))
        self.assertEqual(len(self.sleeps), 2)                    # waited between reads only

    def test_every_read_of_one_lookup_carries_the_same_idempotency_key(self):
        """What stops a number that arrives on the fifth read being paid for five times."""
        self.server.lookup("pending", "pending", "pending", MOBILE)
        self.find([lead()])
        keys = {body["idem_key"] for op, body in self.server.calls if op == "mobile-result"}
        self.assertEqual(len(keys), 1)
        self.assertEqual(self.server.ops().count("mobile-result"), 4)

    def test_everyone_is_started_before_anyone_is_read(self):
        self.server.lookup("pending", MOBILE)
        self.find([lead(name="Asha Rao"), lead(name="Ravi Shah"), lead(name="Neha Iyer")])
        ops = self.server.ops()
        self.assertEqual(ops[:3], ["mobile-start"] * 3)
        self.assertEqual(self.sleeps, [M.POLL])                  # one wait served all three

    def test_apollo_having_no_number_is_not_a_failure_and_changes_nothing(self):
        a = lead()
        self.server.lookup("")
        out = self.find([a])
        self.assertEqual((out["found"], out["given"], out["failed"]), (0, 0, 0))
        self.assertEqual((a.phone, a.extra.get("phones")), ("", None))

    def test_a_number_the_person_came_with_is_never_replaced(self):
        a = lead(phone="+919000011111")
        self.server.lookup(MOBILE)
        out = self.find([a])
        self.assertEqual((out["given"], a.phone), (1, "+919000011111"))
        self.assertEqual([p["number"] for p in a.extra["phones"]], [MOBILE])

    def test_a_company_number_find_phones_put_there_gives_way_to_the_persons_mobile(self):
        a = lead()
        PH.apply(a, {"phone": "+912265551234", "kind": "landline", "source_kind": "own_website"})
        self.assertEqual(a.phone, "+912265551234")
        self.server.lookup(MOBILE)
        self.find([a])
        self.assertEqual(a.phone, MOBILE)
        self.assertEqual({p["scope"] for p in a.extra["phones"]}, {"company", "person"})

    def test_a_number_already_on_the_lead_is_not_added_twice(self):
        a = lead()
        self.assertTrue(M.apply(a, MOBILE))
        self.assertFalse(M.apply(a, MOBILE))
        self.assertEqual(len(a.extra["phones"]), 1)

    # ── what can go wrong ───────────────────────────────────────────────────
    def test_an_empty_pool_stops_the_starting_and_says_why(self):
        self.server.start_error = G.OutOfCredits("INSUFFICIENT_CREDITS", "You've run out of credits.",
                                                 {"balance": 0, "needed": 10})
        out = self.find([lead(name="Asha Rao"), lead(name="Ravi Shah")])
        self.assertEqual((out["asked"], out["failed"]), (0, 2))
        self.assertIn("You've run out of credits.", out["why"])
        self.assertEqual(self.server.ops().count("mobile-start"), 1)     # the second was not even tried

    def test_an_old_server_says_so_once(self):
        self.server.start_error = G.GatewayError("SERVER_OUTDATED", G.OUTDATED_MESSAGE)
        out = self.find([lead(name="Asha Rao"), lead(name="Ravi Shah")])
        self.assertEqual(out["why"], [G.OUTDATED_MESSAGE])

    def test_a_lookup_that_never_finishes_is_reported_not_waited_for_forever(self):
        self.server.lookup("pending")
        out = self.find([lead()])
        self.assertEqual((out["asked"], out["found"], out["pending"]), (1, 0, 1))
        self.assertTrue(any("still working" in w for w in out["why"]))
        self.assertGreaterEqual(sum(self.sleeps), M.MAX_WAIT)

    def test_at_most_a_page_of_people_per_press(self):
        people = [lead(name="Person%s Surname%s" % (chr(97 + i), chr(97 + i))) for i in range(M.LIMIT + 10)]
        self.server.lookup(MOBILE)
        out = self.find(people)
        self.assertEqual(out["asked"], M.LIMIT)

    def test_progress_is_reported_as_lookups_finish(self):
        seen = []
        self.server.lookup("pending", MOBILE)
        M.find([lead(name="Asha Rao"), lead(name="Ravi Shah")], {},
               on_progress=lambda i, n: seen.append((i, n)), sleep=lambda s: None)
        self.assertEqual(seen[0], (0, 2))
        self.assertEqual(seen[-1], (2, 2))

    def test_the_developers_own_key_mode_has_no_mobile_source_and_says_so(self):
        with mock.patch.dict(os.environ, {"PRISM_LEADS_DIRECT": "1"}):
            out = M.find([lead()], {}, sleep=lambda s: None)
        self.assertEqual((out["asked"], self.server.calls), (0, []))
        self.assertTrue(out["why"])


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
