"""Find my buyers, list first (22-Nov-2026).

Signal-first searches of the open web returned a chip startup, a clean-energy fund and an office manager at Regeneron for
a seller of outreach tools to small Indian B2B firms. The company list finds companies that FIT, gates them on size and
place with plain rules, and only then looks for a signal on the ones that stay. Fit is a gate, not a bonus."""
import json
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import buyers as B                      # noqa: E402
from prospector import buyers_list as L                 # noqa: E402
from prospector.models import Signal                    # noqa: E402

TODAY = date(2026, 11, 22)
B.SCORE_PAUSE = 0.0


def _row(name, *, url=None, staff=None, hq=None, about="Makes industrial pumps for other businesses."):
    props = {"name": name, "description": about}
    if staff is not None:
        props["workforce"] = {"total": staff}
    if hq is not None:
        props["headquarters"] = hq
    return {"url": url or f"https://{name.lower().replace(' ', '')}.in", "title": name,
            "entities": [{"type": "company", "properties": props}]}


class FakeLister:
    def __init__(self, rows, signals=None):
        self.rows, self.sig, self.asked, self.signalled = rows, signals or {}, [], []

    def companies(self, text, where, n):
        self.asked.append((text, where, n))
        return None if self.rows is None else L.profile_rows(self.rows)

    def signals(self, name, exclude=()):
        self.signalled.append(name)
        return self.sig.get(name, [])


def _offer(**kw):
    base = dict(text="An outreach tool", regions="India", ideal="Small Indian B2B firms, 5 to 100 staff",
                company_kinds=("small industrial equipment manufacturer",), max_staff=100)
    base.update(kw)
    return B.Offer(**base)


def _ask_fit(scores):
    """A model that rates each company by the score table (default fit 70), and scores intent by what it was shown."""
    def ask(prompt, purpose, json_mode, temperature):
        rows = json.loads(prompt.split("PAGES:\n")[1].split("\n\nReply")[0])
        out = []
        for r in rows:
            fit = scores.get(r["title"], 70)
            signalled = "Recent:" in r["text"]
            out.append({"id": r["id"], "role": "vendor" if fit < 0 else "buyer", "who": r["title"],
                        "fit": abs(fit), "intent": 65 if signalled else 20, "why": "Hiring sales staff." if signalled else "Fits."})
        return json.dumps({"results": out})
    return ask


class TheProfiles(unittest.TestCase):
    def test_a_company_row_is_read_into_a_profile(self):
        p = L.profile_rows([_row("Acme Pumps", url="https://www.acmepumps.in/about", staff=40,
                                 hq={"city": "Vadodara", "country": "India"})])[0]
        self.assertEqual((p["name"], p["domain"], p["headcount"], p["hq"]), ("Acme Pumps", "acmepumps.in", 40, "Vadodara, India"))
        self.assertIn("industrial pumps", p["description"])

    def test_a_row_with_nothing_to_quote_or_no_company_in_it_is_skipped(self):
        no_text = _row("Silent Co", about="")
        person = {"url": "https://x.in", "entities": [{"type": "person", "properties": {"name": "A", "description": "d"}}]}
        self.assertEqual(L.profile_rows([no_text, person, "junk", None]), [])
        self.assertEqual(L.profile_rows(None), [])


class TheRealShape(unittest.TestCase):
    """Rows exactly as Exa's company search returned them on 22-Nov-2026 (tests/fixtures/exa/company_search.json)."""
    ROWS = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "exa",
                                       "company_search.json"), encoding="utf-8"))["results"]

    def test_real_rows_read_into_profiles_with_size_and_place(self):
        got = {p["name"]: p for p in L.profile_rows(self.ROWS)}
        self.assertEqual(len(got), 3)
        self.assertEqual((got["Vineraj Weighing Automation"]["headcount"], got["Vineraj Weighing Automation"]["hq"]),
                         (2, "Vadodara, India"))
        self.assertEqual(got["Jaldhara Industries - India"]["domain"], "jaldharaindustries.com")

    def test_a_small_firm_whose_only_page_is_linkedin_is_listed_not_blocked_and_not_merged_with_another(self):
        rows = self.ROWS + [{**self.ROWS[1], "url": "https://linkedin.com/company/other-firm",
                             "entities": [{"type": "company", "properties": {
                                 **self.ROWS[1]["entities"][0]["properties"], "name": "Other Firm"}}]}]
        qs = B.plan_queries(_offer(), [], (B.LIST,))
        hits, _, _ = L.list_first(_offer(), "s", qs, FakeLister(rows), _ask_fit({}), today=TODAY)
        names = sorted(h.who for h in hits)
        self.assertEqual(names, ["Jaldhara Industries - India", "M/s R B INDUSTRIAL EQUIPMENTS", "Other Firm",
                                 "Vineraj Weighing Automation"])
        self.assertTrue(any(h.url == "https://linkedin.com/company/other-firm" for h in hits))


class TheReadiness(unittest.TestCase):
    """22-Nov-2026: the owner wants companies that fit AND look ready to buy. A tiny firm rarely makes news, but its
    profile already carries dated posts and a year's headcount growth, at no extra search."""
    ROWS = TheRealShape.ROWS

    def test_posts_and_growth_are_read_from_the_profile_text(self):
        vin, _, jal = (L.profile_rows(self.ROWS)[i] for i in (0, 1, 2))
        self.assertEqual([d for d, _ in vin["posts"]][:2], ["2026-11-08", "2026-10-29"])
        self.assertIsNone(vin["growth"])
        self.assertEqual(jal["growth"], -14.3)
        self.assertEqual(L._facts_of(""), (None, []))
        self.assertEqual(L._facts_of("- Yearly Growth: +25.5%")[0], 25.5)

    def test_a_festival_greeting_or_a_thank_you_is_not_a_sign_of_life(self):
        vin = L.profile_rows(self.ROWS)[0]
        sigs = L.profile_signals(vin, TODAY)
        self.assertEqual([(s.published, s.title) for s in sigs], [("2026-10-29", "Posted on LinkedIn")])   # not Diwali, Prakash Purab or the 500 followers
        self.assertIn("carbon black", sigs[0].snippet)

    def test_a_post_older_than_forty_five_days_is_not_recent(self):
        vin = L.profile_rows(self.ROWS)[0]
        self.assertEqual(L.profile_signals(vin, date(2027, 2, 1)), [])

    def test_headcount_growth_counts_only_when_it_is_real_growth(self):
        grew = {"posts": [], "growth": 25.0, "url": "https://a.in"}
        shrank = {"posts": [], "growth": -14.3, "url": "https://a.in"}
        self.assertEqual([s.title for s in L.profile_signals(grew, TODAY)], ["Headcount up 25% in a year"])
        self.assertEqual(L.profile_signals(shrank, TODAY), [])
        self.assertEqual(L.profile_signals({"posts": [], "growth": None}, TODAY), [])

    def test_a_company_that_posted_something_real_is_read_as_a_sign_even_when_the_web_search_finds_nothing(self):
        qs = B.plan_queries(_offer(), [], (B.LIST,))
        hits, stats, _ = L.list_first(_offer(), "s", qs, FakeLister(self.ROWS), _ask_fit({}), today=TODAY)
        by = {h.who: h for h in hits}
        vin, jal = by["Vineraj Weighing Automation"], by["Jaldhara Industries - India"]
        self.assertGreater(vin.intent, jal.intent)                       # a real post, against nothing
        self.assertEqual((vin.published, vin.status), ("2026-10-29", B.RECENT))
        self.assertIn("Recent:", vin.snippet)
        self.assertEqual(stats["list_signals"], 1)                       # Jaldhara shrank, M/s R B has no text
        self.assertNotIn("Recent:", jal.snippet)


class TheGate(unittest.TestCase):
    def test_a_company_over_the_size_the_seller_sets_is_dropped(self):
        self.assertEqual(L.gate({"headcount": 40000, "hq": "Mumbai, India"}, _offer()), "big")
        self.assertEqual(L.gate({"headcount": 40, "hq": "Vadodara, India"}, _offer()), "")

    def test_a_company_whose_head_office_is_in_another_country_is_dropped(self):
        self.assertEqual(L.gate({"headcount": 40, "hq": "Austin, United States"}, _offer()), "place")

    def test_an_unknown_size_or_place_is_kept_never_guessed(self):
        self.assertEqual(L.gate({"headcount": None, "hq": ""}, _offer()), "")
        self.assertEqual(L.gate({"headcount": 5000, "hq": "Pune, India"}, _offer(max_staff=0)), "")   # size does not matter


class ThePlan(unittest.TestCase):
    def test_the_list_is_planned_from_the_company_kinds_not_from_the_buyer_types(self):
        plan = B.plan_queries(_offer(company_kinds=("small pump maker", "valve dealer", "a", "b", "c")),
                              [B.BuyerType(key="f", name="Founder")], (B.LIST,))
        self.assertEqual([(q.channel, q.source, q.text) for q in plan][:2],
                         [(B.LIST, "company", "small pump maker"), (B.LIST, "company", "valve dealer")])
        self.assertEqual(len(plan), 4)                                          # at most four kinds
        self.assertEqual(len(B.plan_queries(_offer(), [], (B.LIST,), preview=True)), 1)

    def test_the_list_comes_first_and_is_on_by_default_while_news_and_funding_are_not(self):
        self.assertEqual(B.CHANNELS[0], B.LIST)
        self.assertEqual(B.DEFAULT_CHANNELS, (B.LIST,))                  # hiring as a web search found office managers at Regeneron

    def test_the_estimate_counts_the_signal_lookups_and_two_reads(self):
        types = [B.BuyerType(key="f", name="Founder")]
        only_list = B.estimate(_offer(), types, (B.LIST,))
        self.assertEqual(only_list["searches"], 1 + B.LIST_SIGNALS)
        self.assertGreaterEqual(only_list["model_calls"], 2)
        self.assertLess(B.estimate(_offer(), types, (B.LIST,), preview=True)["searches"], only_list["searches"])


class TheReading(unittest.TestCase):
    def test_the_reading_carries_what_the_buyers_do_and_the_largest_that_fits(self):
        r = B.read(B.Offer("x"), lambda *a: json.dumps({
            "company_kinds": ["small pump maker", "valve dealer", "small pump maker"], "max_staff": 100,
            "buyer_types": [{"name": "Founder"}]}))
        self.assertEqual((r.company_kinds, r.max_staff), (("small pump maker", "valve dealer"), 100))

    def test_a_missing_or_nonsense_size_reads_as_not_known(self):
        for raw in ({}, {"max_staff": "lots"}, {"max_staff": -5}):
            r = B.read(B.Offer("x"), lambda *a, raw=raw: json.dumps({**raw, "buyer_types": [{"name": "F"}]}))
            self.assertEqual(r.max_staff, 0)

    def test_the_prompt_asks_for_company_kinds_and_a_size(self):
        p = B.offer_prompt(B.Offer("x"))
        for expect in ('"company_kinds"', '"max_staff"', "list (companies that match the customer"):
            self.assertIn(expect, p)


class TheList(unittest.TestCase):
    def setUp(self):
        self.rows = [_row("Acme Pumps", staff=40, hq={"city": "Vadodara", "country": "India"}),
                     _row("Giant Works", staff=40000, hq={"city": "Mumbai", "country": "India"}),
                     _row("Texas Pumps", staff=30, hq={"city": "Austin", "country": "United States"}),
                     _row("Bharat Valves", staff=25, hq={"city": "Rajkot", "country": "India"}),
                     _row("WhatsApp Agency", staff=12, hq={"city": "Surat", "country": "India"},
                          about="We run WhatsApp marketing campaigns for clients.")]
        self.qs = B.plan_queries(_offer(), [], (B.LIST,))

    def run_list(self, lister, ask, **kw):
        return L.list_first(_offer(), "An outreach tool", self.qs, lister, ask, today=TODAY, **kw)

    def test_only_companies_that_pass_the_gate_and_the_fit_read_become_cards(self):
        lister = FakeLister(self.rows)
        hits, stats, notes = self.run_list(lister, _ask_fit({"WhatsApp Agency": -90}))
        self.assertEqual(sorted(h.who for h in hits), ["Acme Pumps", "Bharat Valves"])
        self.assertEqual((stats["list_found"], stats["list_big"], stats["list_place"]), (5, 1, 1))
        self.assertEqual(stats["vendors"], 1)                                  # the agency sells the same thing
        self.assertTrue(all(h.channel == B.LIST and h.kind == B.INFERRED for h in hits))
        self.assertIn("1 over the size you set", notes[-1])

    def test_signals_are_searched_only_for_the_companies_that_stayed(self):
        lister = FakeLister(self.rows)
        self.run_list(lister, _ask_fit({"WhatsApp Agency": -90}))
        self.assertEqual(sorted(lister.signalled), ["Acme Pumps", "Bharat Valves"])      # not Giant, Texas or the agency

    def test_a_company_with_a_recent_signal_ranks_above_one_with_none_and_says_why(self):
        sig = {"Acme Pumps": [Signal(title="Acme Pumps hiring two business development executives",
                                      snippet="Acme Pumps is opening a Pune office.", url="https://news.in/a",
                                      published="2026-11-10", source="news.in")]}
        hits, stats, _ = self.run_list(FakeLister(self.rows, sig), _ask_fit({"WhatsApp Agency": -90}))
        hot, cold = hits[0], hits[1]
        self.assertEqual((hot.who, cold.who), ("Acme Pumps", "Bharat Valves"))
        self.assertGreater(hot.intent, cold.intent)
        self.assertEqual((hot.published, hot.status), ("2026-11-10", B.RECENT))
        self.assertIn("Recent:", hot.snippet)
        self.assertEqual(stats["list_signals"], 1)
        self.assertTrue(cold.why)                                              # "Fits.": said, never blank

    def test_a_signal_page_that_does_not_name_the_company_is_dropped(self):
        sig = {"Acme Pumps": [Signal(title="Pump industry grows", snippet="Demand is rising.", url="https://n.in/x",
                                      published="2026-11-10", source="n.in")]}
        hits, stats, _ = self.run_list(FakeLister(self.rows, sig), _ask_fit({"WhatsApp Agency": -90}))
        self.assertEqual(stats["list_signals"], 0)
        self.assertNotIn("Recent:", next(h for h in hits if h.who == "Acme Pumps").snippet)

    def test_a_failed_company_search_is_counted_and_said_not_read_as_no_companies(self):
        hits, stats, notes = self.run_list(FakeLister(None), _ask_fit({}))
        self.assertEqual((hits, stats["failed"]), ([], 1))
        self.assertTrue(any("company searches failed" in n for n in notes))

    def test_without_a_model_cards_are_scored_by_plain_rules_and_say_so(self):
        hits, _, _ = self.run_list(FakeLister(self.rows), None)
        self.assertTrue(hits)
        self.assertTrue(all(h.scored_by == "rule" and not h.checked for h in hits))

    def test_the_sellers_own_site_and_repeat_companies_are_not_listed(self):
        rows = [_row("Own Co", url="https://alphakore.org", staff=10, hq="India"), self.rows[0], self.rows[0]]
        hits, _, _ = L.list_first(_offer(website="alphakore.org"), "s", self.qs, FakeLister(rows), _ask_fit({}),
                                  today=TODAY)
        self.assertEqual([h.who for h in hits], ["Acme Pumps"])

    def test_a_company_name_is_matched_by_its_first_real_word(self):
        self.assertTrue(L._mentions("Acme Pumps Pvt Ltd", "Acme opens a new plant", ""))
        self.assertFalse(L._mentions("Acme Pumps Pvt Ltd", "A pump maker opens a plant", ""))
        self.assertFalse(L._mentions("Pvt Ltd", "anything", ""))


class TheHunt(unittest.TestCase):
    def setUp(self):
        self.rows = [_row("Acme Pumps", staff=40, hq={"city": "Vadodara", "country": "India"})]
        self.types = [B.BuyerType(key="f", name="Founder", needs=["follow up faster"], hiring_roles=["sales executive"])]

    def _checks_all_pass(self, plan_len):
        def ask(prompt, purpose, json_mode, temperature):
            if "PLANNED SEARCHES" in prompt:
                return json.dumps({"checks": [{"n": i, "keep": True} for i in range(plan_len)]})
            return _ask_fit({})(prompt, purpose, json_mode, temperature)
        return ask

    def test_a_hunt_with_the_list_returns_its_company_cards_and_counts_what_it_ran(self):
        offer = _offer()
        plan_len = len(B.plan_queries(offer, self.types, (B.LIST,)))
        res = B.hunt(offer, "An outreach tool", self.types, (B.LIST,), lambda q: [], self._checks_all_pass(plan_len),
                     today=TODAY, lister=FakeLister(self.rows))
        self.assertEqual([h.who for h in res.hits], ["Acme Pumps"])
        self.assertEqual(res.stats["searches"], 2)             # one company search, one signal lookup: what really ran
        self.assertEqual(res.stats["list_found"], 1)

    def test_the_list_is_skipped_and_said_when_there_is_no_own_exa_key(self):
        offer = _offer()
        res = B.hunt(offer, "s", self.types, (B.LIST,), lambda q: [], None, today=TODAY, lister=None)
        self.assertEqual(res.hits, [])
        self.assertTrue(any("needs your own Exa key" in n for n in res.notes))

    def test_the_intent_check_can_skip_a_company_search_before_it_is_paid_for(self):
        offer = _offer()

        def ask(prompt, purpose, json_mode, temperature):
            return json.dumps({"checks": [{"n": 0, "keep": False, "why": "wrong customer"}]})
        lister = FakeLister(self.rows)
        res = B.hunt(offer, "s", self.types, (B.LIST,), lambda q: [], ask, today=TODAY, lister=lister)
        self.assertEqual(lister.asked, [])
        self.assertTrue(any("Skipped the list search for small industrial equipment manufacturer" in n for n in res.notes))

    def test_a_list_card_for_a_company_the_web_search_already_found_is_not_shown_twice(self):
        offer = _offer()
        web = [{"url": "https://acmepumps.in/jobs", "title": "Sales executive at Acme Pumps",
                "text": "Acme Pumps is hiring a sales executive in Vadodara, India. " * 3, "publishedDate": "2026-11-15"}]
        n = len(B.plan_queries(offer, self.types, (B.LIST, B.HIRING)))
        res = B.hunt(offer, "s", self.types, (B.LIST, B.HIRING), lambda q: web, self._checks_all_pass(n), today=TODAY,
                     lister=FakeLister(self.rows))
        self.assertEqual(len([h for h in res.hits if "acmepumps.in" in h.source]), 1)


class TheStaleReading(unittest.TestCase):
    """22-Nov-2026: an offer read before the list existed has no company kinds. The list was searched for "Founder /
    Owner", the intent check rightly skipped it, and the hunt fell back to funding news without saying why."""
    def test_with_no_company_kinds_the_list_is_not_planned_from_a_buyer_types_name(self):
        types = [B.BuyerType(key="f", name="Founder / Owner")]
        self.assertEqual(B.plan_queries(B.Offer("x", regions="India"), types, (B.LIST,)), [])

    def test_a_hunt_says_to_read_the_offer_again_instead_of_searching_for_nothing(self):
        types = [B.BuyerType(key="f", name="Founder / Owner")]
        res = B.hunt(B.Offer("x", regions="India"), "s", types, (B.LIST,), lambda q: [], None, today=TODAY,
                     lister=FakeLister([]))
        self.assertTrue(any("Press Find my buyers to read it again" in n for n in res.notes))
        self.assertFalse(any("Nothing to search" in n for n in res.notes))

    def test_the_other_sources_still_run_and_the_note_is_still_said(self):
        types = [B.BuyerType(key="f", name="Founder", hiring_roles=["sales executive"])]
        searched = []
        res = B.hunt(B.Offer("x", regions="India"), "s", types, (B.LIST, B.HIRING), lambda q: searched.append(q) or [],
                     None, today=TODAY, lister=FakeLister([]))
        self.assertEqual([q.channel for q in searched], [B.HIRING])
        self.assertTrue(any("Press Find my buyers" in n for n in res.notes))


class TheOutsideCalls(unittest.TestCase):
    def test_make_lister_needs_the_owners_own_exa_key(self):
        from prospector import gateway
        self.assertIsNone(L.make_lister({}))
        self.assertIsInstance(L.make_lister({"exa_api_key": "k"}), L.Lister)
        self.assertIsNone(L.make_lister({"exa_api_key": gateway.POOL_KEY}))               # credits have no company list yet

    def test_the_company_search_asks_exa_for_the_company_category_in_the_named_place(self):
        import requests
        seen = {}

        class R:
            status_code = 200

            def json(self):
                return {"results": [_row("Acme Pumps", staff=40, hq="Vadodara, India")]}
        real = requests.post
        requests.post = lambda url, **kw: (seen.update(url=url, **kw), R())[1]
        try:
            rows = L.Lister("k").companies("small pump maker", "Gujarat, India", 36)
        finally:
            requests.post = real
        self.assertEqual(seen["json"], {"query": "small pump maker in Gujarat, India", "category": "company",
                                        "type": "auto", "numResults": 25})
        self.assertEqual(rows[0]["name"], "Acme Pumps")

    def test_a_refused_or_broken_company_search_is_none_not_an_empty_list(self):
        import requests

        class Bad:
            status_code = 402
        real = requests.post
        try:
            requests.post = lambda *a, **k: Bad()
            self.assertIsNone(L.Lister("k").companies("x", "India", 5))

            def boom(*a, **k):
                raise OSError("offline")
            requests.post = boom
            self.assertIsNone(L.Lister("k").companies("x", "India", 5))
        finally:
            requests.post = real


if __name__ == "__main__":
    unittest.main()
