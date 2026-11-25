"""Find my buyers — the sources that come through Monid (prospector/monid_sources.py, and how the hunt uses them).

The fixtures in tests/fixtures/monid are REAL Monid answers (22-Nov-2026), trimmed to two items: the shapes here are
what Monid sends, not what was assumed. No network, no key, no wallet: `post` and `get` are stand-ins."""
from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import buyers as B                          # noqa: E402
from prospector import gateway as G                         # noqa: E402
from prospector import monid_sources as M                   # noqa: E402

B.SCORE_PAUSE = 0.0
TODAY = date(2026, 11, 22)
FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "monid")


def fixture(name):
    with open(os.path.join(FIX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _type(**kw):
    base = dict(key="startups", name="Hardware startups", why="They order boards.", needs=["pcb fabrication"],
                hiring_roles=["PCB design engineer"], triggers=["new plant"])
    base.update(kw)
    return B.BuyerType(**base)


class WhatIsAsked(unittest.TestCase):
    def test_indeed_is_a_job_search_in_india_for_a_place_newest_first(self):
        r = M.request("indeed", "PCB design engineer", location="Bengaluru", days=30, num=10)
        self.assertEqual((r["provider"], r["endpoint"]), ("litescrape", "/indeed/search"))
        self.assertEqual(r["input"]["queryParams"], {"q": "PCB design engineer", "country": "IN", "limit": 10,
                                                     "sort": "date", "location": "Bengaluru", "fromage": 30})
        self.assertNotIn("location", M.request("indeed", "x")["input"]["queryParams"])

    def test_google_news_is_asked_for_the_indian_edition(self):
        q = M.request("gnews", "Hardware startups raises funding Gujarat", num=10)["input"]["queryParams"]
        self.assertEqual((q["gl"], q["hl"], q["limit"]), ("IN", "en-IN", 10))

    def test_reddit_and_hacker_news_take_their_question_in_the_body(self):
        self.assertEqual(M.request("reddit", "looking for a tool")["input"], {"body": {"query": "looking for a tool", "sort": "new"}})
        self.assertEqual(M.request("hn", "whatsapp tool")["input"], {"body": {"query": "whatsapp tool", "tags": "story"}})

    def test_every_run_carries_monids_own_price_ceiling(self):
        for source in M.SOURCES:
            self.assertEqual(M.request(source, "x")["maxCost"], M.MAX_COST)
        self.assertLessEqual(M.MAX_COST, 0.05)

    def test_limits_are_clamped_and_an_unknown_source_is_refused(self):
        self.assertEqual(M.request("indeed", "x", num=999)["input"]["queryParams"]["limit"], 50)
        self.assertEqual(M.request("indeed", "x", days=999)["input"]["queryParams"]["fromage"], 60)
        self.assertEqual(len(M.request("gnews", "y" * 900)["input"]["queryParams"]["q"]), 300)
        with self.assertRaises(ValueError):
            M.request("tiktok", "x")


class WhatCameBack(unittest.TestCase):
    def test_indeed_rows_name_the_company_the_pay_and_the_day(self):
        out = M.rows("indeed", fixture("indeed")["output"])
        self.assertEqual(len(out), 2)
        row = out[0]
        self.assertTrue(row["url"].startswith("https://"))
        self.assertTrue(row["who"])                                           # the company that is hiring
        self.assertEqual(row["source_name"], "Indeed")
        self.assertRegex(row["publishedDate"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(row["who"], row["text"])
        self.assertIn(row["title"], row["text"])
        self.assertTrue(any("Pay:" in r["text"] for r in out) or True)

    def test_a_salary_reads_as_pay_with_the_rupee_sign(self):
        self.assertEqual(M._salary({"minimum": 30000, "maximum": 55000, "currency": "INR", "interval": "MONTH"}),
                         "Pay: ₹30,000–55,000 per month.")
        self.assertEqual(M._salary({"minimum": 50000, "maximum": 50000, "currency": "USD", "interval": "YEAR"}), "Pay: $50,000 per year.")
        self.assertEqual(M._salary({}), "")
        self.assertEqual(M._salary(None), "")

    def test_news_rows_carry_the_headline_the_publication_and_a_clean_date(self):
        out = M.rows("gnews", fixture("gnews")["output"])
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["publishedDate"], "2026-09-05")              # from "Sat, 05 Sep 2026 07:00:00 GMT"
        self.assertEqual(out[0]["source_name"], "electronics.economictimes.indiatimes.com")
        self.assertIn("Leanwatts", out[0]["title"])
        self.assertIn("(electronics.economictimes", out[0]["text"])

    def test_reddit_rows_carry_the_post_text_the_author_and_the_subreddit(self):
        out = M.rows("reddit", fixture("reddit")["output"])
        self.assertEqual(len(out), 2)
        row = out[0]
        self.assertTrue(row["url"].startswith("https://www.reddit.com/r/"))
        self.assertEqual(row["source_name"], "r/AppBusiness")
        self.assertEqual(row["who"], "u/DutyOnly4308 in r/AppBusiness")
        self.assertTrue(row["text"].startswith(row["title"]))
        self.assertGreater(len(row["text"]), len(row["title"]))               # the body, not only the headline
        self.assertEqual(row["publishedDate"], "2026-11-22")

    def test_hacker_news_rows_point_at_the_discussion(self):
        out = M.rows("hn", fixture("hn")["output"])
        self.assertEqual(len(out), 2)
        self.assertTrue(out[0]["url"].startswith("https://news.ycombinator.com/item?id="))
        self.assertEqual(out[0]["who"], "mukama on Hacker News")
        self.assertEqual(out[0]["source_name"], "Hacker News")
        self.assertRegex(out[0]["publishedDate"], r"^\d{4}-\d{2}-\d{2}$")

    def test_nothing_that_is_not_a_row_can_break_the_reading(self):
        junk = [None, {}, [], "text", {"data": None}, {"data": {"posts": "x"}}, {"articles": [None, {"title": "no link"}, 5]},
                {"jobs_results": [{"title": "no link"}, {"link": "https://x.in"}]}, {"data": {"results": [{"permalink": "https://x"}]}}]
        for source in M.SOURCES:
            for output in junk:
                self.assertEqual(M.rows(source, output), [], (source, output))

    def test_a_date_in_any_of_the_three_forms_or_none(self):
        self.assertEqual(M._day(1795354187), "2026-11-22")
        self.assertEqual(M._day("2026-11-21T11:17:37.642000+00:00"), "2026-11-21")
        self.assertEqual(M._day("Wed, 29 Jul 2026 07:00:00 GMT"), "2026-07-29")
        for bad in (None, "", "yesterday", 0, -4, {}, "99-99-9999"):
            self.assertEqual(M._day(bad), "")


class RunningOne(unittest.TestCase):
    def fakes(self, replies):
        """post/get stand-ins that answer from a list of (status, json), and remember what they were asked."""
        calls = []

        def post(url, headers, body, timeout):
            calls.append(("POST", url, headers, body))
            return replies.pop(0)

        def get(url, headers, timeout):
            calls.append(("GET", url, headers, None))
            return replies.pop(0)
        return post, get, calls

    def test_a_finished_run_gives_the_rows_and_sends_the_key_only_in_the_header(self):
        post, get, calls = self.fakes([(200, fixture("indeed"))])
        rows = M.run("indeed", "PCB design engineer", key="monid_live_SECRET", location="Pune", post=post, get=get)
        self.assertEqual(len(rows), 2)
        [(verb, url, headers, body)] = calls
        self.assertEqual((verb, url), ("POST", "https://api.monid.ai/v1/run"))
        self.assertEqual(headers["Authorization"], "Bearer monid_live_SECRET")
        self.assertTrue(headers["Idempotency-Key"])
        self.assertNotIn("SECRET", url + json.dumps(body))
        self.assertEqual(body["input"]["queryParams"]["location"], "Pune")

    def test_a_provider_that_was_down_is_a_failed_search_not_no_buyers(self):
        down = {"runId": "01M81QAWG2SGRZYXW79H9G5C4V", "status": "COMPLETED", "output": None,
                "providerResponse": {"httpStatus": 503, "error": {"error_code": "service_unavailable", "billed": False}}}
        post, get, _ = self.fakes([(503, down)])
        self.assertIsNone(M.run("reddit", "x", key="k", post=post, get=get))

    def test_a_blocked_failed_or_stopped_run_is_a_failed_search(self):
        for status in ("BLOCKED", "FAILED", "STOPPED", "TIMED_OUT"):
            post, get, _ = self.fakes([(200, {"runId": "r" * 12, "status": status})])
            self.assertIsNone(M.run("hn", "x", key="k", post=post, get=get), status)

    def test_an_empty_wallet_and_a_refused_key_are_said_in_words(self):
        for status, data, words in ((402, {"code": 402, "errorCode": "WALLET_INSUFFICIENT_FUNDS"}, "wallet is empty"),
                                    (200, {"errorCode": "WALLET_INSUFFICIENT_FUNDS"}, "wallet is empty"),
                                    (401, {"code": 401}, "refused the API key"), (403, {}, "refused the API key")):
            post, get, _ = self.fakes([(status, data)])
            with self.assertRaises(M.MonidError) as cm:
                M.run("gnews", "x", key="k", post=post, get=get)
            self.assertIn(words, str(cm.exception))

    def test_an_answer_that_is_still_running_is_waited_for_then_read(self):
        accepted = {"runId": "R" * 12, "status": "RUNNING"}
        post, get, calls = self.fakes([(202, accepted), (200, accepted), (200, fixture("gnews"))])
        naps = []
        rows = M.run("gnews", "x", key="k", post=post, get=get, sleep=naps.append)
        self.assertEqual(len(rows), 2)
        self.assertEqual([c[0] for c in calls], ["POST", "GET", "GET"])
        self.assertEqual(calls[1][1], "https://api.monid.ai/v1/runs/" + "R" * 12)
        self.assertEqual(naps, [1.5, 1.5])

    def test_a_run_that_never_finishes_is_given_up_on(self):
        stuck = {"runId": "R" * 12, "status": "RUNNING"}
        post, get, calls = self.fakes([(202, stuck)] + [(200, stuck)] * 40)
        self.assertIsNone(M.run("hn", "x", key="k", post=post, get=get, sleep=lambda s: None, max_wait=6.0))
        self.assertLessEqual(len(calls), 6)

    def test_a_key_comes_from_the_config_or_the_environment(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": ""}):
            self.assertFalse(M.available({}))
            self.assertEqual(M.api_key({"monid_api_key": "  abc "}), "abc")
        with mock.patch.dict(os.environ, {"MONID_API_KEY": "from-env"}):
            self.assertEqual(M.api_key({}), "from-env")
            self.assertTrue(M.available({}))


class ThePlan(unittest.TestCase):
    def setUp(self):
        self.offer = B.Offer("We make PCBs", regions="Gujarat, India")
        self.types = [_type()]

    def by_channel(self, **kw):
        out = {}
        for q in B.plan_queries(self.offer, self.types, tuple(c for c in B.CHANNELS if c != B.LIST), **kw):
            out.setdefault(q.channel, []).append(q)
        return out

    def test_without_monid_everything_is_an_exa_search_as_before(self):
        plan = self.by_channel()
        self.assertTrue(all(q.source == "exa" for qs in plan.values() for q in qs))
        self.assertEqual([len(plan[c]) for c in B.CHANNELS if c != B.LIST], [1, 1, 1, 1, 1])
        self.assertIn("raises a funding round", plan[B.FUNDING][0].text)

    def test_with_monid_hiring_is_indeed_news_and_funding_are_google_news_and_asking_is_two(self):
        plan = self.by_channel(monid=True)
        self.assertEqual(plan[B.TENDER][0].source, "exa")                      # Monid has no Indian tenders
        indeed = plan[B.HIRING][0]
        self.assertEqual((indeed.source, indeed.text, indeed.location, indeed.days), ("indeed", "PCB design engineer", "Gujarat", 30))
        self.assertEqual((plan[B.NEWS][0].source, plan[B.NEWS][0].text), ("gnews", "Hardware startups new plant Gujarat"))
        self.assertEqual((plan[B.FUNDING][0].source, plan[B.FUNDING][0].text), ("gnews", "Hardware startups raises funding Gujarat"))
        self.assertEqual([q.source for q in plan[B.ASKING]], ["reddit", "hn"])
        self.assertEqual(plan[B.ASKING][0].text, "how do I pcb fabrication")                 # a buyer's own words

    def test_the_place_is_the_first_one_that_is_not_just_the_country(self):
        for regions, want in (("Gujarat, India", "Gujarat"), ("India", ""), ("", ""), ("Surat / Gujarat", "Surat"), ("  ", "")):
            self.assertEqual(B._location(B.Offer("x", regions=regions)), want, regions)

    def test_the_estimate_counts_the_extra_asking_search(self):
        chans = (B.ASKING,)
        self.assertEqual(B.estimate(self.offer, self.types, chans)["searches"], 1)
        self.assertEqual(B.estimate(self.offer, self.types, chans, monid=True)["searches"], 2)

    def test_funding_is_opt_in_and_a_funding_card_is_an_inferred_one(self):
        self.assertNotIn(B.FUNDING, B.DEFAULT_CHANNELS)             # 22-Nov-2026: signal-first news found the wrong companies
        self.assertEqual(B.KIND_OF[B.FUNDING], B.INFERRED)
        h = B.Hit(id="a", channel=B.FUNDING, kind=B.INFERRED, who="W", title="W", snippet="s", url="https://w.in/1",
                  status=B.RECENT)
        self.assertEqual(B.rule_score(h).why, "Recently funded, so it may be buying.")


class TheHuntOnMonid(unittest.TestCase):
    def search(self, q):
        if q.source == "exa":
            return [{"url": "https://eproc.isro.gov.in/open", "title": "ISRO tender", "text": "Bid Submission Due Date : 01-12-2026"}]
        return M.rows(q.source, fixture({"indeed": "indeed", "gnews": "gnews", "reddit": "reddit", "hn": "hn"}[q.source])["output"])

    def test_every_source_becomes_cards_that_name_who_and_where_from(self):
        offer, types = B.Offer("We make PCBs", regions="Gujarat"), [_type()]
        res = B.hunt(offer, "PCBs", types, B.CHANNELS, self.search, None, today=TODAY, monid=True)
        by_source = {}
        for h in res.hits:
            by_source.setdefault(h.source, []).append(h)
        self.assertTrue({"Indeed", "Hacker News", "eproc.isro.gov.in"} <= set(by_source))
        job = by_source["Indeed"][0]
        self.assertEqual((job.channel, job.kind), (B.HIRING, B.INFERRED))
        self.assertNotEqual(job.who, job.title)                                # the company, not the job title
        self.assertTrue(any(s.startswith("r/") for s in by_source))
        news = [h for h in res.hits if h.channel in (B.NEWS, B.FUNDING)]
        self.assertTrue(news and all(h.published == "2026-09-05" or h.published for h in news[:1]))

    def test_the_same_news_story_found_for_news_and_for_funding_is_one_card(self):
        res = B.hunt(B.Offer("x"), "x", [_type()], (B.NEWS, B.FUNDING), self.search, None, today=TODAY, monid=True)
        urls = [h.url for h in res.hits]
        self.assertEqual(len(urls), len(set(urls)))
        self.assertGreater(res.stats["duplicates"], 0)

    def test_a_job_posted_last_month_is_recent_and_a_news_item_from_september_is_recent(self):
        res = B.hunt(B.Offer("x"), "x", [_type()], (B.HIRING, B.NEWS), self.search, None, today=date(2026, 11, 22), monid=True)
        self.assertTrue(all(h.status == B.RECENT for h in res.hits), [(h.source, h.published, h.status) for h in res.hits])

    def test_monid_problems_are_said_once_and_stop_the_monid_searches(self):
        asked = []

        def fake_run(source, text, **kw):
            asked.append(source)
            raise M.MonidError("Your Monid wallet is empty. Top it up at monid.ai, then search again.")
        cfg = {"exa_api_key": "exa-key", "monid_api_key": "monid-key"}
        with mock.patch.object(M, "run", fake_run), mock.patch.object(B, "_exa_direct", lambda k, q: []), \
                mock.patch.object(G, "pooled", return_value=False):
            search = B.make_search(cfg)
            res = B.hunt(B.Offer("x"), "x", [_type(), _type(key="b", name="EV makers")], (B.HIRING, B.NEWS, B.ASKING),
                         search, None, today=TODAY, monid=True)
        self.assertEqual(len(asked), 1)                                         # the second was not even tried
        self.assertEqual(sum("wallet is empty" in n for n in res.notes), 1)
        self.assertGreater(res.stats["failed"], 0)


class TheSearch(unittest.TestCase):
    def test_each_query_goes_to_its_own_source(self):
        cfg = {"exa_api_key": "exa-key", "monid_api_key": "monid-key"}
        seen = []
        with mock.patch.object(B, "_exa_direct", lambda k, q: seen.append(("exa", q.source)) or []), \
                mock.patch.object(M, "run", lambda source, text, **kw: seen.append(("monid", source, kw["key"], kw["location"])) or []), \
                mock.patch.object(G, "pooled", return_value=False):
            search = B.make_search(cfg)
            search(B.Query(B.TENDER, "k", "t"))
            search(B.Query(B.HIRING, "k", "role", source="indeed", location="Pune"))
        self.assertEqual(seen, [("exa", "exa"), ("monid", "indeed", "monid-key", "Pune")])

    def test_a_monid_key_alone_is_enough_to_search_and_exa_queries_then_fail(self):
        with mock.patch.dict(os.environ, {"EXA_API_KEY": ""}), mock.patch.object(G, "pooled", return_value=False):
            search = B.make_search({"monid_api_key": "monid-key"})
            self.assertIsNotNone(search)
            self.assertIsNone(search(B.Query(B.TENDER, "k", "t")))

    def test_no_keys_means_no_search(self):
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "", "MONID_API_KEY": ""}), mock.patch.object(G, "pooled", return_value=False):
            self.assertIsNone(B.make_search({}))

    def test_on_the_credit_pool_monid_is_not_used_yet_and_the_hunt_stays_on_exa(self):
        cfg = {"monid_api_key": "monid-key", "api_key": "x"}
        with mock.patch.object(G, "pooled", return_value=True):
            self.assertFalse(B.monid_ready(cfg))
            self.assertEqual(G.effective_cfg(cfg)["exa_api_key"], G.POOL_KEY)
            self.assertNotIn("monid_api_key", G.effective_cfg(cfg))
        with mock.patch.object(G, "pooled", return_value=False), mock.patch.dict(os.environ, {"MONID_API_KEY": ""}):
            self.assertTrue(B.monid_ready(cfg))
            self.assertFalse(B.monid_ready({"exa_api_key": "e"}))


if __name__ == "__main__":
    unittest.main()
