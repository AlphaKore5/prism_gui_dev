"""What PR #18's security-and-money review found (25-Nov-2026), each held by a test.

  1. A lookup the server never names is not ready (apollo, mobile, hunt), and on the credit pool a Find-people run
     never starts an Exa search the owner did not approve.
  2. Apollo reveals over an account import stop at "Reveal up to" across every company group, not per group.
  3. A Find-buyers card keeps a website only when it is the buyer's own, never the publisher's.
  4. Reveals already paid through Monid are kept when the wallet runs dry part-way.
  5. The mobile waterfall stops at the first source that returned a number of any kind (it billed).
  6. Text from a stranger is plain in a tooltip and is never a spreadsheet formula.
  7. Find buyers on the pool asks whether the server has the hunt lookup before anything is spent.

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
from prospector import apollo, monid_run                            # noqa: E402
from prospector import gateway as G                                 # noqa: E402
from prospector import phone_waterfall as W                         # noqa: E402
from prospector.models import Lead                                  # noqa: E402

# The licence server's own readiness() on a server that predates the Monid routes: no apollo, mobile or hunt.
OLD_SERVER_READY = {"people": True, "company": True, "domain": True, "signals": True, "phones": True,
                    "llm": False, "verify": True, "find_email": True}


def person(name="Ana Ruiz", company="Acme"):
    lead = Lead(name=name, company=company, title="Head of Operations", email="")
    lead.extra = {"apollo_id": "a1"}
    return lead


# ── 1. readiness ─────────────────────────────────────────────────────────────

class ALookupTheServerNeverNamed(unittest.TestCase):
    def setUp(self):
        self.addCleanup(G.forget)

    def status_says(self, ready: dict):
        G.set_transport(lambda path, body: {"balance": 100, "rates": {}, "ready": ready})
        self.addCleanup(G.set_transport, None)
        with mock.patch.object(G, "_auth_body", lambda **e: {"license_id": "L", "device_fp": "D", **e}):
            G.status()

    def test_an_old_server_has_no_apollo_mobile_or_hunt(self):
        self.status_says(OLD_SERVER_READY)
        for op in ("apollo", "mobile", "hunt"):
            self.assertFalse(G.ready(op), op)
        self.assertTrue(G.ready("people"))                      # an older lookup it names is still ready

    def test_a_server_that_names_them_has_them(self):
        self.status_says({**OLD_SERVER_READY, "apollo": True, "mobile": True, "hunt": True})
        for op in ("apollo", "mobile", "hunt"):
            self.assertTrue(G.ready(op), op)

    def test_before_the_server_is_asked_the_new_lookups_are_not_offered(self):
        G.forget()
        self.assertFalse(G.ready("apollo"))
        self.assertTrue(G.ready("people"))                      # an older one still reads as ready until asked


@pytest.mark.pooled
class NoUnapprovedExaOnThePool(unittest.TestCase):
    """The question before a pooled Apollo run prices Apollo. An Exa search is never started in its place."""

    def setUp(self):
        env = mock.patch.dict(os.environ, {"MONID_API_KEY": "", "APOLLO_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.exa_calls: list = []

    def run_worker(self, answer, ready=True):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]}})
        w = SourceWorker([], [], "x", {}, source="apollo", target=25, verify_limit=0, leads_only=True,
                         spec=spec.to_dict())
        got = {"done": [], "failed": []}
        w.done.connect(lambda res, drafts: got["done"].append(res))
        w.failed.connect(got["failed"].append)

        def fake_apollo(spec, key, **kw):
            if isinstance(answer, Exception):
                raise answer
            return list(answer)

        def fake_exa(*a, **k):
            self.exa_calls.append(1)
            return [person("Bo Lund", "Globex")]
        patches = [mock.patch.object(apollo, "search_people", side_effect=fake_apollo),
                   mock.patch("prospector.source.source", side_effect=fake_exa),
                   mock.patch("prospector.signals.exa_key", return_value="pool"),
                   mock.patch.object(G, "ready", lambda op: ready)]
        for p in patches:
            p.start()
        try:
            w.run()
        finally:
            for p in patches:
                p.stop()
        return got

    def test_apollo_empty_ends_the_run_without_exa(self):
        got = self.run_worker([])
        self.assertEqual(self.exa_calls, [])
        self.assertEqual(got["done"], [])
        self.assertTrue(got["failed"])

    def test_apollo_refused_is_said_in_its_words_without_exa(self):
        got = self.run_worker(apollo.ApolloError("You've run out of credits."))
        self.assertEqual(self.exa_calls, [])
        self.assertEqual(got["failed"], ["You've run out of credits."])

    def test_a_server_without_apollo_fails_and_does_not_search_exa(self):
        got = self.run_worker([person()], ready=False)
        self.assertEqual(self.exa_calls, [])
        self.assertIn("isn't switched on for your account yet", got["failed"][0])


# ── 2. the reveal ceiling across company groups ──────────────────────────────

@pytest.mark.pooled
class TheRevealCeilingHoldsAcrossCompanyGroups(unittest.TestCase):
    def test_200_companies_with_filters_dropping_everyone_reveal_at_most_the_target(self):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]}})
        companies = [{"name": f"Co {i}", "domain": f"co{i}.com"} for i in range(200)]
        w = SourceWorker([], [], "x", {}, source="apollo", target=25, verify_limit=0, leads_only=True,
                         spec=spec.to_dict(), companies=companies)
        revealed: list = []

        def fake_apollo(spec, key, *, target, budget=None, stats=None, **kw):
            n = min(target, budget if budget is not None else target)
            revealed.append(n)
            if stats is not None:
                stats["revealed"] = n              # paid for — and every one dropped by the filters
            return []
        with mock.patch.object(apollo, "search_people", side_effect=fake_apollo), \
                mock.patch("prospector.signals.exa_key", return_value="pool"), \
                mock.patch.object(G, "ready", lambda op: True):
            w.run()
        self.assertGreater(len(revealed), 0)
        self.assertLessEqual(sum(revealed), 25)


# ── 3. a buyer's website ─────────────────────────────────────────────────────

class ABuyerCardsWebsite(unittest.TestCase):
    def hit(self, channel, source):
        from prospector import buyers as B
        return B.Hit(id="h", channel=channel, kind=B.KIND_OF[channel], who="Acme", title="Acme",
                     snippet="", url="https://" + source + "/x", source=source)

    def site(self, channel, source):
        from prospector import buyers as B
        return B.to_lead(self.hit(channel, source)).extra["website"]

    def test_a_company_list_card_keeps_the_companys_own_domain(self):
        from prospector import buyers as B
        self.assertEqual(self.site(B.LIST, "acme.in"), "https://acme.in")

    def test_a_news_hiring_or_asking_card_does_not_turn_the_publisher_into_the_buyer(self):
        from prospector import buyers as B
        for ch, src in ((B.NEWS, "economictimes.indiatimes.com"), (B.HIRING, "Indeed"),
                        (B.ASKING, "reddit.com"), (B.TENDER, "eprocure.gov.in")):
            self.assertEqual(self.site(ch, src), "", ch)

    def test_a_linkedin_page_is_not_a_website(self):
        from prospector import buyers as B
        self.assertEqual(self.site(B.LIST, "linkedin.com"), "")


# ── 4. paid reveals survive an empty wallet ──────────────────────────────────

class PaidRevealsSurviveAnEmptyWallet(unittest.TestCase):
    def test_the_batch_keeps_what_was_revealed_and_the_next_call_ends_the_run(self):
        asked = []

        def call(provider, endpoint, *, key, query=None, max_cost=None, **kw):
            asked.append(endpoint)
            if endpoint == "/people/match" and len([a for a in asked if a == "/people/match"]) > 2:
                raise monid_run.MonidError("Your Monid wallet is empty.")
            return {"output": {"person": {"id": "p", "first_name": "Ana", "last_name": "Ruiz"}}}
        send = apollo.monid_transport("K", call=call)
        got = send(apollo.BULK_MATCH, {"details": [{"id": str(i)} for i in range(5)]})
        found = [m for m in got["matches"] if m]
        self.assertEqual(len(found), 2)                           # the two bought before the refusal are kept
        with self.assertRaises(apollo._Unreachable) as caught:   # and the run then ends, keeping its list
            send(apollo.SEARCH, {"page": 2})
        self.assertIn("wallet is empty", str(caught.exception))


# ── 5. the mobile waterfall ──────────────────────────────────────────────────

class TheWaterfallPaysOncePerPerson(unittest.TestCase):
    def run_of(self, output):
        return {"output": output, "providerResponse": {"httpStatus": 200}}

    def test_a_desk_line_stops_the_waterfall_because_the_source_billed_for_it(self):
        asked = []

        def call(provider, endpoint, *, key, max_cost=None, **kw):
            asked.append(provider)
            if provider == "anyapi":
                return self.run_of({"found": False})
            if provider == "reversecontact":
                return self.run_of({"data": {"result": [{"value": "+912652345678", "type": "landline"}]}})
            return self.run_of({"profile": {"phone": ["+919825012345"]}})
        res = W.find("Ana", "Ruiz", "acme.in", key="K", call=call)
        self.assertEqual(asked, ["anyapi", "reversecontact"])     # ContactOut is never asked: one bill a person
        self.assertEqual((res["number"], res["provider"]), ("", "reversecontact"))
        self.assertEqual(res["tried"][-1], ("reversecontact", "desk"))


# ── 6. stranger's text ───────────────────────────────────────────────────────

class StrangersText(unittest.TestCase):
    def test_a_formula_is_kept_as_text_and_a_phone_number_is_left_alone(self):
        from prospector.exports import safe_cell
        self.assertEqual(safe_cell('=HYPERLINK("http://x","y")'), '\'=HYPERLINK("http://x","y")')
        for v in ("@SUM(A1)", "-2+3", "+cmd"):
            self.assertTrue(safe_cell(v).startswith("'"), v)
        self.assertEqual(safe_cell("+91 98250 12345"), "+91 98250 12345")
        self.assertEqual(safe_cell("Acme"), "Acme")
        self.assertEqual(safe_cell(3), 3)

    def test_the_leads_sheet_never_holds_a_formula(self):
        import tempfile
        import openpyxl
        from prospector import exports
        lead = Lead(name="Ana", company='=HYPERLINK("http://evil","x")', title="Head", email="")
        path = os.path.join(tempfile.mkdtemp(), "leads.xlsx")
        exports.leads_xlsx([lead], path)
        ws = openpyxl.load_workbook(path).active
        cells = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
        self.assertFalse(any(v.startswith("=") for v in cells))

    def test_a_tooltip_shows_markup_as_written(self):
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication(sys.argv)
        from addons.leads import result_rows as R
        w = R._Elided('<img src="http://evil/x.png"> Acme ' + "x" * 200, "")
        w.resize(40, 20)
        w._refit()
        self.assertIn("&lt;img", w.toolTip())
        self.assertNotIn("<img", w.toolTip())


# ── 7. Find buyers asks first ────────────────────────────────────────────────

@pytest.mark.pooled
class FindBuyersAsksTheServerFirst(unittest.TestCase):
    def test_no_hunt_lookup_means_no_model_call_and_no_search(self):
        from addons.leads.workers import BuyerHuntWorker
        from prospector import buyers
        asked = []
        w = BuyerHuntWorker.__new__(BuyerHuntWorker)
        BuyerHuntWorker.__init__(w, *_hunt_args())
        got = {"failed": []}
        w.failed.connect(got["failed"].append)
        with mock.patch.object(buyers, "make_search", return_value=lambda q: asked.append("search") or []), \
                mock.patch.object(buyers, "make_ask", return_value=lambda *a, **k: asked.append("ask") or "{}"), \
                mock.patch.object(G, "status", return_value={}), \
                mock.patch.object(G, "ready", lambda op: op != "hunt"):
            w.run()
        self.assertEqual(asked, [])
        self.assertIn("isn't switched on for your account yet", got["failed"][0])


def _hunt_args():
    """The arguments BuyerHuntWorker takes, read off its signature so this test follows it."""
    import inspect
    from addons.leads.workers import BuyerHuntWorker
    from prospector import buyers
    params = [p for p in inspect.signature(BuyerHuntWorker.__init__).parameters.values() if p.name != "self"]
    values = {"offer": buyers.Offer(text="x", ideal="small firms"), "summary": "", "types": [], "channels": (), "cfg": {}}
    return [values.get(p.name, None) for p in params if p.default is inspect.Parameter.empty]


if __name__ == "__main__":
    unittest.main()
