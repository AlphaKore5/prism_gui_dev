"""Find my buyers — the engine (prospector/buyers.py).

Qt-free. No network, no model, no real folder: `search` and `ask` are stand-ins.
The fixtures are the tender pages the 22-Nov-2026 prototype actually returned, so
the closing-date reader is tested on the wording real portals use."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest import mock
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import buyers as B                          # noqa: E402

TODAY = date(2026, 11, 22)
B.SCORE_PAUSE = 0.0                                          # no waiting between model calls in a test

SAC = ("Tender No : SAC/CPUR/SA202600193701 Bid Submission Start Date : 03-11-2026 12:41 "
       "Bid Clarification Due Date : 24-11-2026 17:30 Bid Submission Due Date : 01-12-2026 15:30 "
       "Bid Opening Date : 01-12-2026 16:30 Price Bid Opening Date : 08-12-2026 11:42")
IIST = ("Published Date : 04-11-2026 10:35 IST Bid Submission Start Date : 04-11-2026 10:35 IST "
        "Bid Submission End Date : 26-11-2026 14:00 IST Clarification End Date : 12-11-2026 14:00 IST "
        "Bid Opening Date: 26-11-2026 14:15 IST")
HAL = ("Opening Date Nov 16, 2026 - Closing Date Nov 24, 2026 | Tender Closing Date | "
       "2026-11-24 01:00 PM")
CLOSED = "Custom bid. Published on: 16 Oct 2026. Closing on: 20 Nov 2026, 04:00 pm IST."


def _type(key="startups", name="Hardware startups", **kw) -> B.BuyerType:
    return B.BuyerType(key=key, name=name, why="They order boards.", needs=["pcb fabrication"],
                       hiring_roles=["PCB design engineer"], triggers=["new plant"], **kw)


def _row(url, title="A page", text="", published="", **kw):
    return {"url": url, "title": title, "text": text, "publishedDate": published, **kw}


class ClosingDates(unittest.TestCase):
    def test_the_submission_date_wins_over_clarification_and_opening(self):
        self.assertEqual(B.closing_date(SAC), date(2026, 12, 1))

    def test_end_date_wording(self):
        self.assertEqual(B.closing_date(IIST), date(2026, 11, 26))

    def test_month_names_and_iso_dates(self):
        self.assertEqual(B.closing_date(HAL), date(2026, 11, 24))
        self.assertEqual(B.closing_date(CLOSED), date(2026, 11, 20))

    def test_a_page_with_no_closing_word_has_no_closing_date(self):
        self.assertIsNone(B.closing_date("Tender for PCB fabrication. Published 04-11-2026."))
        self.assertIsNone(B.closing_date(""))
        self.assertIsNone(B.closing_date("Opening Date : 01-12-2026"))

    def test_an_impossible_date_is_not_read(self):
        self.assertIsNone(B.closing_date("Closing date 31-02-2026"))


class MakingCards(unittest.TestCase):
    def _q(self, channel=B.TENDER):
        return B.Query(channel, "startups", "q")

    def test_an_open_bid_is_open_and_a_closed_one_is_closed(self):
        open_ = B.make_hit(_row("https://eproc.isro.gov.in/a", text=SAC), self._q(), TODAY)
        shut = B.make_hit(_row("https://ibid.win/t/1", text=CLOSED), self._q(), TODAY)
        self.assertEqual((open_.status, open_.closes, open_.kind), (B.OPEN, "2026-12-01", B.DECLARED))
        self.assertEqual((shut.status, shut.closes), (B.CLOSED, "2026-11-20"))

    def test_a_bid_with_no_readable_date_is_unknown_not_open(self):
        h = B.make_hit(_row("https://x.gov.in/t", text="Tender for PCBs"), self._q(), TODAY)
        self.assertEqual((h.status, h.closes), (B.UNKNOWN, ""))

    def test_no_evidence_no_card(self):
        self.assertIsNone(B.make_hit(_row("", text="x"), self._q(), TODAY))
        self.assertIsNone(B.make_hit(_row("https://a.com/x"), self._q(), TODAY))
        self.assertIsNone(B.make_hit("not a row", self._q(), TODAY))

    def test_directories_and_the_sellers_own_site_are_not_buyers(self):
        self.assertIsNone(B.make_hit(_row("https://www.indiamart.com/x", text="t"), self._q(B.NEWS), TODAY))
        self.assertIsNone(B.make_hit(_row("https://shop.acme.in/page", text="t"), self._q(B.NEWS), TODAY,
                                     own_domain="acme.in"))
        self.assertIsNotNone(B.make_hit(_row("https://notacme.in/page", text="t"), self._q(B.NEWS), TODAY,
                                        own_domain="acme.in"))

    def test_a_linkedin_post_is_evidence_but_a_company_page_is_not(self):
        self.assertIsNotNone(B.make_hit(_row("https://www.linkedin.com/posts/x-hiring", text="t"),
                                        self._q(B.HIRING), TODAY))
        self.assertIsNone(B.make_hit(_row("https://www.linkedin.com/company/x", text="t"),
                                     self._q(B.HIRING), TODAY))

    def test_recency_for_news(self):
        new = B.make_hit(_row("https://a.com/1", text="t", published="2026-09-10"), self._q(B.NEWS), TODAY)
        old = B.make_hit(_row("https://a.com/2", text="t", published="2025-01-02"), self._q(B.NEWS), TODAY)
        none = B.make_hit(_row("https://a.com/3", text="t"), self._q(B.NEWS), TODAY)
        self.assertEqual((new.status, old.status, none.status), (B.RECENT, B.OLD, B.UNKNOWN))
        self.assertEqual(new.kind, B.INFERRED)

    def test_one_page_is_one_card_however_the_address_is_written(self):
        self.assertEqual(B.hit_id("https://www.A.com/x/"), B.hit_id("http://a.com/x#top"))
        self.assertNotEqual(B.hit_id("https://a.com/x"), B.hit_id("https://a.com/y"))


class Planning(unittest.TestCase):
    def setUp(self):
        self.offer = B.Offer("We make PCBs", regions="Gujarat")
        self.types = [_type(), _type("makers", "EV makers")]

    def test_one_search_per_type_per_channel(self):
        qs = B.plan_queries(self.offer, self.types, (B.TENDER, B.HIRING, B.NEWS))
        self.assertEqual(len(qs), 6)
        self.assertEqual({q.channel for q in qs}, {B.TENDER, B.HIRING, B.NEWS})
        self.assertTrue(all("Gujarat" in q.text for q in qs))
        self.assertTrue(all(q.num == B.FULL_ROWS for q in qs))

    def test_a_tender_search_has_no_date_window_because_the_closing_date_decides(self):
        [q] = B.plan_queries(self.offer, self.types[:1], (B.TENDER,))
        self.assertEqual(q.days, 0)
        self.assertIn("closing date", q.text)

    def test_a_type_that_was_unticked_is_not_searched(self):
        self.types[1].enabled = False
        qs = B.plan_queries(self.offer, self.types, (B.TENDER,))
        self.assertEqual([q.type_key for q in qs], ["startups"])

    def test_a_preview_is_the_first_two_types_at_most_four_searches_and_fewer_rows(self):
        types = self.types + [_type("third", "Third")]
        qs = B.plan_queries(self.offer, types, (B.TENDER, B.HIRING, B.NEWS), preview=True)
        self.assertEqual(len(qs), 4)
        self.assertTrue(all(q.num == B.PREVIEW_ROWS for q in qs))
        self.assertNotIn("third", {q.type_key for q in qs})

    def test_no_region_means_india_and_no_channel_means_nothing(self):
        [q] = B.plan_queries(B.Offer("x"), self.types[:1], (B.TENDER,))
        self.assertIn("India", q.text)
        self.assertEqual(B.plan_queries(self.offer, self.types, ()), [])

    def test_the_estimate_says_what_a_hunt_will_ask_for(self):
        full = B.estimate(self.offer, self.types, (B.TENDER, B.HIRING, B.NEWS))
        quick = B.estimate(self.offer, self.types, (B.TENDER, B.HIRING, B.NEWS), preview=True)
        self.assertEqual(full, {"searches": 6, "model_calls": 5})           # 4 reads and the intent check
        self.assertEqual(quick, {"searches": 4, "model_calls": 3})
        self.assertEqual(B.estimate(self.offer, self.types, ()), {"searches": 0, "model_calls": 0})


class ReadingTheOffer(unittest.TestCase):
    GOOD = json.dumps({"summary": "PCB prototypes for hardware startups.", "buyer_types": [
        {"name": "Hardware startups", "why": "They order prototypes.", "who_decides": ["Founder"],
         "needs": ["pcb fabrication", "prototype boards"], "hiring_roles": ["PCB design engineer"],
         "triggers": ["seed round"], "exclude": ["PCB makers"]},
        {"name": "hardware STARTUPS", "why": "duplicate by name"},
        {"name": "EV electronics makers", "needs": "bms boards"},
        "not an object"]})

    def test_a_model_answer_becomes_buyer_types(self):
        summary, types = B.read_offer(B.Offer("We make PCBs"), lambda *a: self.GOOD)
        self.assertEqual(summary, "PCB prototypes for hardware startups.")
        self.assertEqual([t.name for t in types], ["Hardware startups", "EV electronics makers"])
        self.assertEqual(types[0].needs, ["pcb fabrication", "prototype boards"])
        self.assertEqual(types[1].needs, ["bms boards"])               # a bare string is one phrase
        self.assertTrue(all(t.enabled for t in types))

    def test_fenced_json_is_read(self):
        _s, types = B.read_offer(B.Offer("x"), lambda *a: "Sure!\n```json\n" + self.GOOD + "\n```")
        self.assertEqual(len(types), 2)

    def test_at_most_six_types(self):
        many = json.dumps({"buyer_types": [{"name": f"Kind {i}"} for i in range(12)]})
        _s, types = B.read_offer(B.Offer("x"), lambda *a: many)
        self.assertEqual(len(types), B.MAX_TYPES)

    def test_every_failure_is_a_sentence_for_the_owner(self):
        for ask in (lambda *a: "no json at all", lambda *a: "{}", lambda *a: json.dumps({"buyer_types": []})):
            with self.assertRaises(B.BuyersError):
                B.read_offer(B.Offer("We make PCBs"), ask)
        def boom(*a):
            raise RuntimeError("down")
        with self.assertRaises(B.BuyersError) as cm:
            B.read_offer(B.Offer("We make PCBs"), boom)
        self.assertIn("down", str(cm.exception))
        with self.assertRaises(B.BuyersError):
            B.read_offer(B.Offer("   "), lambda *a: self.GOOD)


class TheHunt(unittest.TestCase):
    OPEN = "https://eproc.isro.gov.in/open"
    SHUT = "https://ibid.win/shut"
    VENDOR = "https://pcbmaker.in/services"
    JOB = "https://jobs.example.com/pcb"

    def setUp(self):
        self.offer = B.Offer("We make PCBs", website="https://acme.in")
        self.types = [_type()]
        self.calls = []

    def search(self, q):
        self.calls.append(q.channel)
        if q.channel == B.TENDER:
            return [_row(self.OPEN, "ISRO tender", SAC), _row(self.SHUT, "MeitY bid", CLOSED),
                    _row(self.VENDOR, "PCB services", "We offer PCB fabrication"),
                    _row(self.OPEN + "/", "ISRO tender again", SAC), _row("", "no url", "x")]
        return [_row(self.JOB, "Hiring a PCB design engineer", "Drone maker hiring", published="2026-11-02")]

    def ask(self, prompt, purpose, json_mode, temperature):
        ids = {"open": B.hit_id(self.OPEN), "vendor": B.hit_id(self.VENDOR), "job": B.hit_id(self.JOB)}
        return json.dumps({"results": [
            {"id": ids["open"], "role": "buyer", "who": "ISRO SAC", "fit": 80, "intent": 90, "why": "Bid open."},
            {"id": ids["vendor"], "role": "vendor", "who": "PCB maker", "fit": 10, "intent": 5, "why": "Sells PCBs."},
            {"id": ids["job"], "role": "buyer", "who": "Drogo", "fit": 70, "intent": 55, "why": "Hiring."}]})

    def run_hunt(self, ask="default", **kw):
        return B.hunt(self.offer, "PCBs for startups", self.types, (B.TENDER, B.HIRING), self.search,
                      self.ask if ask == "default" else ask, today=TODAY, **kw)

    def test_the_best_card_first_a_vendor_dropped_a_closed_bid_last_and_counted(self):
        res = self.run_hunt()
        urls = [h.url for h in res.hits]
        self.assertEqual(urls, [self.OPEN, self.JOB, self.SHUT])
        self.assertEqual(res.hits[0].who, "ISRO SAC")
        self.assertEqual((res.hits[0].scored_by, res.hits[0].why), ("model", "Bid open."))
        self.assertEqual(res.hits[2].status, B.CLOSED)
        self.assertEqual((res.hits[2].fit, res.hits[2].intent), (0, 0))
        self.assertEqual((res.stats["closed"], res.stats["vendors"], res.stats["kept"]), (1, 1, 2))
        self.assertEqual(res.stats["duplicates"], 1)
        self.assertNotIn(self.VENDOR, urls)

    def test_a_search_that_failed_is_said_and_never_read_as_no_buyers(self):
        def flaky(q):
            return None if q.channel == B.HIRING else self.search(q)
        res = B.hunt(self.offer, "x", self.types, (B.TENDER, B.HIRING), flaky, self.ask, today=TODAY)
        self.assertEqual(res.stats["failed"], 1)
        self.assertTrue(any("1 of 2 searches failed" in n for n in res.notes))
        self.assertTrue(res.hits)

    def test_without_a_model_cards_are_scored_by_rule_and_it_says_so(self):
        res = self.run_hunt(ask=None)
        self.assertTrue(all(h.scored_by == "rule" for h in res.hits))
        self.assertTrue(any("plain rules" in n for n in res.notes))
        live = [h for h in res.hits if h.status != B.CLOSED]
        self.assertEqual(live[0].url, self.OPEN)             # an OPEN bid outranks a hiring post by rule
        self.assertIn(self.VENDOR, [h.url for h in res.hits])  # no model, so nothing can rule a vendor out

    def test_a_model_that_fails_midway_keeps_the_rule_scores(self):
        def down(*a):
            raise RuntimeError("rate limited")
        res = self.run_hunt(ask=down)
        self.assertTrue(all(h.scored_by == "rule" for h in res.hits))
        self.assertTrue(any("rate limited" in n for n in res.notes))

    def test_the_model_cannot_score_a_card_it_was_not_given(self):
        def stray(prompt, *a):
            return json.dumps({"results": [{"id": "zzz", "role": "buyer", "fit": 99, "intent": 99}]})
        res = self.run_hunt(ask=stray)
        self.assertTrue(all(h.scored_by == "rule" for h in res.hits))

    def test_scores_are_clamped_and_junk_is_ignored(self):
        def odd(prompt, *a):
            return json.dumps({"results": [
                {"id": B.hit_id(self.OPEN), "role": "buyer", "fit": 500, "intent": -4, "why": "x"},
                {"id": B.hit_id(self.JOB), "role": "buyer", "fit": "high", "intent": 50}]})
        res = self.run_hunt(ask=odd)
        top = next(h for h in res.hits if h.url == self.OPEN)
        self.assertEqual((top.fit, top.intent), (100, 0))
        job = next(h for h in res.hits if h.url == self.JOB)
        self.assertEqual(job.scored_by, "rule")

    def test_a_page_the_model_calls_neither_a_buyer_nor_a_vendor_is_dropped_too(self):
        def other(prompt, *a):
            return json.dumps({"results": [
                {"id": B.hit_id(self.OPEN), "role": "buyer", "fit": 80, "intent": 90, "why": "Bid open."},
                {"id": B.hit_id(self.VENDOR), "role": "other", "fit": 20, "intent": 10, "why": "Not about a buyer."},
                {"id": B.hit_id(self.JOB), "role": "", "fit": 60, "intent": 60, "why": "no role given"}]})
        res = self.run_hunt(ask=other)
        urls = [h.url for h in res.hits]
        self.assertEqual(urls, [self.OPEN, self.SHUT])
        self.assertEqual(res.stats["vendors"], 2)

    def test_a_search_engines_own_listing_is_never_a_buyer(self):
        self.assertIsNone(B.make_hit(_row("https://exa.ai/library/places?ids=1", text="Campaign Plus agency"),
                                     B.Query(B.ASKING, "k", "q"), TODAY))

    def test_the_model_calls_are_spaced_out_but_not_before_the_first(self):
        rows = [_row(f"https://a.com/{i}", f"T{i}", "text", published="2026-11-01") for i in range(30)]
        naps = []
        with mock.patch.object(B, "SCORE_PAUSE", 2.0), mock.patch.object(B.time, "sleep", naps.append):
            B.hunt(self.offer, "x", self.types, (B.NEWS,), lambda q: rows, lambda *a: json.dumps({"results": []}),
                   today=TODAY)
        self.assertEqual(naps, [2.0, 2.0])                    # 30 cards = 3 calls = 2 gaps

    def test_a_card_hands_the_model_only_a_short_slice_of_the_page(self):
        h = B.Hit(id="a", channel=B.NEWS, kind=B.INFERRED, who="A", title="A", snippet="y" * 2000, url="https://a.com/1")
        self.assertNotIn("y" * (B.CARD_TEXT + 1), B.score_prompt("s", {}, [h]))

    def test_nothing_to_search_says_so(self):
        res = B.hunt(self.offer, "x", self.types, (), self.search, None, today=TODAY)
        self.assertEqual(res.hits, [])
        self.assertTrue(res.notes)
        self.assertEqual(self.calls, [])

    def test_progress_and_stop(self):
        seen = []
        self.run_hunt(on_progress=lambda i, n, q: seen.append((i, n, q.channel)))
        self.assertEqual(seen, [(1, 2, B.TENDER), (2, 2, B.HIRING)])
        stopped = []
        res = B.hunt(self.offer, "x", self.types, (B.TENDER, B.HIRING), lambda q: stopped.append(1) or [],
                     None, today=TODAY, cancelled=lambda: len(stopped) >= 1)
        self.assertEqual(len(stopped), 1)
        self.assertTrue(any("Stopped" in n for n in res.notes))

    def test_the_model_reads_at_most_the_card_cap(self):
        rows = [_row(f"https://a.com/{i}", f"T{i}", "text", published="2026-11-01") for i in range(100)]
        asked = []
        def ask(prompt, *a):
            asked.append(prompt)
            return json.dumps({"results": []})
        res = B.hunt(self.offer, "x", self.types, (B.NEWS,), lambda q: rows, ask, today=TODAY)
        self.assertEqual(len(asked), -(-B.SCORE_CAP // B.SCORE_BATCH))    # the cap, 12 to a call (no check: this offer has no customer line)
        self.assertEqual(len(res.hits), 100)
        self.assertTrue(any(f"{B.SCORE_CAP} most promising" in n for n in res.notes))


class NeverABuyer(unittest.TestCase):
    """22-Nov-2026: Find buyers offered Exa's own listing of WhatsApp agencies as a "fit to sell Prism"."""
    EXA = "https://exa.ai/library/places?ids=l768k0p051x%2Ckwnh075ll2k%2Cssml64f70pw%2C25wstgx9gcy%2Crgvk7cwdgqs%2C63d277y5j62%2Cgsfdx6yk3kl%2Cql62nsfx6wc%2Cnws3y4w02kp%2C0w68d4clv5n"
    PAGE = "# looking for a supplier vendor for run WhatsApp broadcast campaigns, recommendations please, India 1. Campaign Plus - Whatsapp API, Bulk Whatsapp, Chatbot - 3rd Floor, V Mall, 321 /1, off Western Express Highway, Mumbai"

    def _asking(self):
        offer = B.Offer("x", regions="India")
        return B.plan_queries(offer, [B.BuyerType(key="a", name="Founder", needs=["run WhatsApp broadcast campaigns"])],
                              (B.ASKING,))[0]

    def test_a_search_engines_own_listing_is_blocked_by_address(self):
        self.assertTrue(B.blocked(self.EXA))
        self.assertIsNone(B.make_hit(_row(self.EXA, "Agencies", self.PAGE), self._asking(), TODAY))

    def test_a_page_that_repeats_our_search_sentence_is_dropped_even_from_an_unknown_host(self):
        # the sentence we used to search with, which is what the saved page repeats ("or" is missing from the page)
        q = B.Query(B.ASKING, "a", "looking for a supplier or vendor for run WhatsApp broadcast campaigns, "
                                   "recommendations please, India")
        self.assertTrue(B.echoes_query(q.text, self.PAGE))
        self.assertIsNone(B.make_hit(_row("https://listings.example.com/x", "Agencies", self.PAGE), q, TODAY))

    def test_the_search_no_longer_asks_for_a_supplier_or_a_vendor(self):
        """That wording finds the people who SELL. A buyer says what they struggle with."""
        for monid in (False, True):
            for q in B.plan_queries(B.Offer("x", regions="India"),
                                    [B.BuyerType(key="a", name="Founder", needs=["follow up with leads faster"])],
                                    (B.ASKING,), monid=monid):
                self.assertNotRegex(q.text.casefold(), r"supplier|vendor")
                self.assertIn("follow up with leads faster", q.text)

    def test_a_real_post_that_asks_for_the_same_thing_is_kept(self):
        q = self._asking()
        post = "We need a vendor to run WhatsApp broadcast campaigns for our retail stores in Gujarat. Any recommendations?"
        self.assertFalse(B.echoes_query(q.text, post))
        self.assertIsNotNone(B.make_hit(_row("https://forum.example.in/t/1", "Need a vendor", post), q, TODAY))

    def test_a_tender_that_quotes_our_words_is_never_called_an_echo(self):
        q = B.plan_queries(B.Offer("x"), [_type()], (B.TENDER,))[0]
        page = ("Open tender or request for quotation inviting bids for pcb fabrication India bid submission closing date "
                "01-12-2026")
        self.assertTrue(B.echoes_query(q.text, page))                      # the words do match...
        self.assertIsNotNone(B.make_hit(_row("https://eproc.gov.in/t", "Tender", page), q, TODAY))   # ...and a tender stays

    def test_short_queries_cannot_echo(self):
        self.assertFalse(B.echoes_query("pcb tender", "pcb tender in india"))
        self.assertFalse(B.echoes_query("", "anything"))

    def test_the_sellers_own_site_is_blocked_with_its_subdomains(self):
        self.assertTrue(B.blocked("https://shop.acme.in/page", "acme.in"))
        self.assertFalse(B.blocked("https://notacme.in/page", "acme.in"))


class IntentCheck(unittest.TestCase):
    """22-Nov-2026: the first preview searched for office managers at Regeneron and government SMS tenders, none of them
    a small Indian B2B firm. Every planned search is checked against the owner's customer before it is paid for."""
    def setUp(self):
        self.offer = B.Offer("A WhatsApp and email outreach tool", regions="India",
                             ideal="Small Indian B2B firms, not large enterprises or government bodies")
        self.types = [B.BuyerType(key="ops", name="Operations Manager", needs=["keep one inbox"],
                                  hiring_roles=["office administrator"]),
                      B.BuyerType(key="founder", name="Founder", needs=["follow up with leads faster"],
                                  hiring_roles=["sales executive"])]
        self.plan = B.plan_queries(self.offer, self.types, (B.TENDER, B.HIRING))

    def _ask(self, checks):
        def ask(prompt, purpose, json_mode, temperature):
            return json.dumps({"checks": checks})
        return ask

    def test_the_model_is_given_the_customer_and_every_planned_search(self):
        prompt = B.check_prompt(self.offer, "summary", {"ops": "Operations Manager"}, self.plan)
        self.assertIn("THE CUSTOMER: Small Indian B2B firms", prompt)
        self.assertIn(self.plan[0].text, prompt)
        self.assertEqual(prompt.count('"source":'), len(self.plan))

    def test_a_search_the_model_rules_out_is_dropped_and_said_with_its_reason(self):
        ask = self._ask([{"n": 0, "keep": False, "why": "Government tenders are not small private firms."},
                         {"n": 1, "keep": True}, {"n": 2, "keep": True}, {"n": 3, "keep": True}])
        kept, notes = B.check_queries(self.offer, "s", self.types, self.plan, ask)
        self.assertEqual(len(kept), len(self.plan) - 1)
        self.assertNotIn(self.plan[0], kept)
        self.assertEqual(len(notes), 1)
        self.assertIn("Skipped the tender search for Operations Manager: Government tenders", notes[0])

    def test_a_sharper_search_replaces_the_text_but_never_brings_back_supplier_wording(self):
        ask = self._ask([{"n": 1, "keep": True, "better": "small Indian company hiring a sales executive to do outreach"},
                         {"n": 2, "keep": True, "better": "looking for a supplier of outreach tools"}])
        kept, _ = B.check_queries(self.offer, "s", self.types, self.plan, ask)
        self.assertEqual(kept[1].text, "small Indian company hiring a sales executive to do outreach")
        self.assertEqual(kept[2].text, self.plan[2].text)

    def test_an_unreachable_or_unreadable_model_lets_every_search_run_and_says_so(self):
        def boom(*a):
            raise RuntimeError("rate limited")
        for ask in (boom, lambda *a: "not json", lambda *a: json.dumps({"results": []})):
            kept, notes = B.check_queries(self.offer, "s", self.types, self.plan, ask)
            self.assertEqual(kept, self.plan)
            self.assertIn("could not be checked", notes[0])

    def test_a_hunt_runs_only_the_searches_that_pass_and_counts_the_skipped(self):
        searched = []

        def search(q):
            searched.append(q)
            return []
        ask = self._ask([{"n": i, "keep": i % 2 == 0, "why": "no"} for i in range(len(self.plan))])
        res = B.hunt(self.offer, "s", self.types, (B.TENDER, B.HIRING), search, ask, today=TODAY)
        self.assertEqual(len(searched), len(self.plan) // 2)
        self.assertEqual((res.stats["searches"], res.stats["skipped"]), (len(self.plan) // 2, len(self.plan) // 2))

    def test_a_hunt_where_everything_is_skipped_searches_nothing_and_says_why(self):
        searched = []
        ask = self._ask([{"n": i, "keep": False, "why": "wrong customer"} for i in range(len(self.plan))])
        res = B.hunt(self.offer, "s", self.types, (B.TENDER, B.HIRING), lambda q: searched.append(q) or [], ask, today=TODAY)
        self.assertEqual(searched, [])
        self.assertTrue(any("Every planned search was skipped" in n for n in res.notes))

    def test_without_a_customer_line_nothing_is_skipped_on_the_models_say_so_and_the_owner_is_told(self):
        """22-Nov-2026: an old reading has no customer line, and the check skipped every search it was shown."""
        searched = []
        asked = []

        def ask(prompt, *a):
            asked.append(prompt)
            return json.dumps({"checks": [{"n": i, "keep": False, "why": "vibes"} for i in range(9)]})
        offer = B.Offer("x", regions="India")                       # no ideal
        res = B.hunt(offer, "s", self.types, (B.TENDER,), lambda q: searched.append(q) or [], ask, today=TODAY)
        self.assertTrue(searched)
        self.assertFalse(any("PLANNED SEARCHES" in p for p in asked))
        self.assertTrue(any("not checked against your customer" in n for n in res.notes))

    def test_the_scorer_is_told_the_customer_so_a_giant_or_a_ministry_is_not_a_fit(self):
        h = B.Hit(id="a", channel=B.HIRING, kind=B.INFERRED, who="W", title="t", snippet="s", url="https://w.in/1")
        prompt = B.score_prompt("A tool", {}, [h], ideal="Small Indian B2B firms")
        self.assertIn("THE CUSTOMER: Small Indian B2B firms", prompt)
        self.assertIn("a government body", prompt)
        self.assertNotIn("THE CUSTOMER", B.score_prompt("A tool", {}, [h]))

    def test_the_reading_carries_the_ideal_customer(self):
        r = B.read(B.Offer("x"), lambda *a: json.dumps({"ideal_customer": "Small Indian B2B firms, 5-50 staff",
                                                         "buyer_types": [{"name": "Founder"}]}))
        self.assertEqual(r.ideal, "Small Indian B2B firms, 5-50 staff")
        self.assertIn('"ideal_customer"', B.offer_prompt(B.Offer("x")))


class Competitors(unittest.TestCase):
    """22-Nov-2026: Find buyers listed the AGENCIES THAT SELL WhatsApp services as buyers of a WhatsApp tool."""
    GOOD = json.dumps({
        "summary": "A desktop app for outreach.",
        "competitors": ["WhatsApp marketing agencies", "bulk SMS and WhatsApp API providers", "WhatsApp marketing agencies"],
        "channels": ["Hiring", "news", "tender", "nonsense", "asking", "funding"],
        "buyer_types": [{"name": "Founder", "needs": ["follow up with leads faster"], "exclude": ["agencies"]},
                        {"name": "Sales lead", "needs": ["track replies in one place"]}]})

    def test_the_model_is_told_what_a_buyer_is_and_that_a_seller_of_the_same_thing_is_not(self):
        prompt = B.offer_prompt(B.Offer("We sell a WhatsApp and email outreach tool"))
        for expect in ("BUYER is an organisation that would USE", "COMPETITOR and never a buyer", '"competitors"',
                       '"channels"', "never 'supplier' or 'vendor' words"):
            self.assertIn(expect, prompt)

    def test_a_reading_carries_the_competitors_and_the_channels_that_fit(self):
        r = B.read(B.Offer("x"), lambda *a: self.GOOD)
        self.assertEqual([t.name for t in r.types], ["Founder", "Sales lead"])
        self.assertEqual(r.competitors, ["WhatsApp marketing agencies", "bulk SMS and WhatsApp API providers"])   # no repeat
        self.assertEqual(r.channels, (B.TENDER, B.HIRING, B.NEWS, B.FUNDING, B.ASKING))     # in the page's order, the junk dropped
        self.assertEqual(B.read(B.Offer("x"), lambda *a: json.dumps(
            {"channels": ["Hiring", "x"], "buyer_types": [{"name": "F"}]})).channels, (B.HIRING,))

    def test_an_old_style_answer_with_no_competitors_or_channels_still_reads(self):
        r = B.read(B.Offer("x"), lambda *a: json.dumps({"buyer_types": [{"name": "Founder"}]}))
        self.assertEqual((r.competitors, r.channels), ([], ()))
        self.assertEqual(B.read_offer(B.Offer("x"), lambda *a: json.dumps({"summary": "s", "buyer_types": [{"name": "Founder"}]}))[0], "s")

    def test_the_scorer_is_given_the_competitors_and_each_types_skip_list(self):
        h = B.Hit(id="a", channel=B.NEWS, kind=B.INFERRED, who="W", title="t", snippet="s", url="https://w.in/1",
                  buyer_type="founder")
        prompt = B.score_prompt("A tool", {"founder": "Founder"}, [h], "WhatsApp marketing agencies",
                                {"founder": ["agencies", "resellers"]})
        self.assertIn("COMPETITORS (they SELL the same or a similar thing: NEVER buyers): WhatsApp marketing agencies", prompt)
        self.assertIn('"skip_kinds": ["agencies", "resellers"]', prompt)
        self.assertIn("even when it says it wants clients, partners or suppliers", prompt)
        self.assertNotIn("COMPETITORS (", B.score_prompt("A tool", {}, [h]))          # nothing to say, nothing said

    def test_a_hunt_hands_the_competitors_to_the_scorer_and_drops_what_it_calls_a_seller(self):
        seen = []

        def ask(prompt, purpose, json_mode, temperature):
            seen.append(prompt)
            return json.dumps({"results": [
                {"id": B.hit_id("https://agency.in/whatsapp"), "role": "vendor", "who": "Agency", "fit": 90, "intent": 90,
                 "why": "Sells WhatsApp marketing."},
                {"id": B.hit_id("https://retailer.in/post"), "role": "buyer", "who": "Retailer", "fit": 70, "intent": 70,
                 "why": "Wants to message customers."}]})
        rows = [_row("https://agency.in/whatsapp", "We run WhatsApp campaigns", "Agency text", published="2026-11-10"),
                _row("https://retailer.in/post", "Need WhatsApp", "Retailer text", published="2026-11-11")]
        offer = B.Offer("A WhatsApp tool", competitors="WhatsApp marketing agencies")
        res = B.hunt(offer, "A tool", [_type(exclude=["agencies"])], (B.NEWS,), lambda q: rows, ask, today=TODAY)
        self.assertTrue(any("WhatsApp marketing agencies" in p for p in seen))
        self.assertEqual([h.url for h in res.hits], ["https://retailer.in/post"])
        self.assertEqual(res.stats["vendors"], 1)


class WeakAndChecked(unittest.TestCase):
    def _h(self, fit, intent, by="model", status=B.RECENT):
        return B.Hit(id="x", channel=B.TENDER, kind=B.DECLARED, who="W", title="W", snippet="s",
                     url="https://w.in/1", status=status, fit=fit, intent=intent, scored_by=by)

    def test_a_card_under_forty_is_weak_and_a_closed_bid_is_closed_not_weak(self):
        self.assertTrue(self._h(20, 30).weak)                      # round(.45*20 + .55*30) = 26
        self.assertFalse(self._h(50, 50).weak)
        self.assertFalse(self._h(0, 0, status=B.CLOSED).weak)

    def test_only_a_model_read_counts_as_checked(self):
        self.assertTrue(self._h(50, 50).checked)
        self.assertFalse(self._h(50, 50, by="rule").checked)


class TheDossier(unittest.TestCase):
    """A card as the Dossier the person drawer draws: the same words, with nothing added the card does not hold."""

    def _hit(self, **kw):
        base = dict(id="a", channel=B.TENDER, kind=B.DECLARED, who="HAL", title="PCB tender", snippet="Open bid.",
                    url="https://x.in/1", source="x.in", closes="2026-11-24", status=B.OPEN, fit=75, intent=90,
                    why="Open bid for PCBs.", scored_by="model")
        base.update(kw)
        return B.Hit(**base)

    def test_the_verdict_follows_the_score(self):
        verdict = lambda f, i: B.to_dossier(self._hit(fit=f, intent=i), today=TODAY).verdict         # noqa: E731
        self.assertEqual((verdict(80, 90), verdict(55, 55), verdict(20, 30)), ("hot", "warm", "cold"))

    def test_fit_need_and_timing_each_carry_evidence_and_a_source(self):
        d = B.to_dossier(self._hit(), "Hardware startups", TODAY)
        self.assertEqual([x.name for x in d.dimensions], ["Fit", "Need", "Timing"])
        fit, need, timing = d.dimensions
        self.assertEqual((fit.verdict, need.verdict), ("pass", "pass"))
        self.assertIn("Hardware startups", fit.evidence)
        self.assertEqual((need.evidence, need.source), ("Open bid for PCBs.", "x.in · 24 Nov 2026"))
        self.assertEqual((timing.verdict, timing.evidence), ("warn", "The bid closes on 24 Nov 2026."))     # two days left
        self.assertEqual(d.summary, "Open bid for PCBs.")
        self.assertEqual(d.confidence, 1.0)

    def test_the_page_itself_is_the_why_now(self):
        [sig] = B.to_dossier(self._hit(), today=TODAY).signals
        self.assertEqual((sig.url, sig.source, sig.snippet), ("https://x.in/1", "x.in", "Open bid."))

    def test_timing_for_a_closed_a_far_off_and_an_undated_bid(self):
        timing = lambda **kw: B.to_dossier(self._hit(**kw), today=TODAY).dimensions[2]                  # noqa: E731
        self.assertEqual(timing(closes="2026-11-20", status=B.CLOSED).verdict, "fail")
        self.assertEqual(timing(closes="2026-12-30").verdict, "pass")
        undated = timing(closes="", status=B.UNKNOWN)
        self.assertEqual((undated.verdict, undated.evidence), ("unknown", "No closing date was found on the page."))

    def test_timing_for_news_uses_the_publication_date(self):
        timing = lambda **kw: B.to_dossier(self._hit(channel=B.NEWS, kind=B.INFERRED, closes="", **kw),
                                           today=TODAY).dimensions[2]                                   # noqa: E731
        self.assertEqual(timing(published="2026-11-10", status=B.RECENT).verdict, "pass")
        old = timing(published="2025-01-02", status=B.OLD)
        self.assertEqual(old.verdict, "warn")
        self.assertIn("out of date", old.evidence)
        self.assertEqual(timing(published="", status=B.UNKNOWN).verdict, "unknown")

    def test_a_card_the_model_never_read_is_not_dressed_up_as_a_finding(self):
        d = B.to_dossier(self._hit(scored_by="rule", why="A public bid page that matched your search."), today=TODAY)
        fit, need, _timing = d.dimensions
        self.assertEqual((fit.verdict, need.verdict), ("unknown", "unknown"))
        self.assertIn("Not read by the model", need.evidence)
        self.assertEqual((d.summary, d.confidence), ("", 0.0))


class Decisions(unittest.TestCase):
    def _hits(self):
        return [B.Hit(id="a", channel=B.TENDER, kind=B.DECLARED, who="A", title="A", snippet="s", url="https://a.com/1"),
                B.Hit(id="b", channel=B.NEWS, kind=B.INFERRED, who="B", title="B", snippet="s", url="https://b.com/1")]

    def test_decide_sets_and_counts(self):
        hits = self._hits()
        self.assertEqual(B.decide(hits, ["a"], B.NOT_A_FIT, "too big"), 1)
        self.assertEqual((hits[0].decision, hits[0].reason, hits[1].decision), (B.NOT_A_FIT, "too big", B.NEW))
        self.assertEqual(B.decide(hits, ["a"], B.NOT_A_FIT, "too big"), 0)       # nothing changed
        with self.assertRaises(ValueError):
            B.decide(hits, ["a"], "banana")

    def test_a_card_survives_being_stored_and_read_back(self):
        h = self._hits()[0]
        h.fit, h.intent, h.closes = 70, 90, "2026-12-01"
        back = B.hit_from_dict(B.asdict(h))
        self.assertEqual(B.asdict(back), B.asdict(h))
        self.assertEqual(back.score, round(0.45 * 70 + 0.55 * 90))

    def test_junk_in_a_stored_card_is_repaired_or_refused(self):
        self.assertIsNone(B.hit_from_dict({"id": "x"}))
        self.assertIsNone(B.hit_from_dict("nope"))
        d = B.asdict(self._hits()[0])
        d.update(decision="banana", fit="lots", intent=900, surprise="ignored")
        h = B.hit_from_dict(d)
        self.assertEqual((h.decision, h.fit, h.intent), (B.NEW, 0, 100))

    def test_an_accepted_card_becomes_an_organisation_lead_with_an_identity(self):
        from prospector.identity import keys_of
        h = self._hits()[0]
        h.who, h.why = "ISRO SAC", "Bid open."
        lead = B.to_lead(h)
        self.assertEqual((lead.name, lead.company), ("", "ISRO SAC"))
        self.assertEqual(lead.extra["buyer_channel"], B.TENDER)
        self.assertTrue(keys_of(lead))                       # saveable: contacts skip a lead nothing identifies


if __name__ == "__main__":
    unittest.main()
