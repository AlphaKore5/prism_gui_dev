"""Find my buyers learns from the owner (22-Nov-2026).

Every card accepted or put away is kept with the owner's reason. The next hunt does not show or read those companies
again, tells the model what the owner likes and does not, and each source is reported by what the owner did with it
and how the accepted buyers did in People."""
import json
import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector import buyers as B                      # noqa: E402
from prospector import buyers_learn as BL               # noqa: E402
from prospector import buyers_list as L                 # noqa: E402

TODAY = date(2026, 11, 22)
B.SCORE_PAUSE = 0.0
AT = "2026-11-22T10:00:00+05:30"


def _hit(n, who=None, *, channel=B.LIST, url=None, why="", snippet=""):
    return B.Hit(id=f"id{n}", channel=channel, kind=B.KIND_OF[channel], who=who or f"Company {n} Works",
                 title=who or f"Company {n} Works", snippet=snippet or f"Makes things {n}.",
                 url=url or f"https://company{n}.in/", source=f"company{n}.in", why=why)


class TheReasons(unittest.TestCase):
    def test_a_reason_is_read_from_its_key_or_its_label_and_the_models_own_words_are_not_ours(self):
        self.assertEqual(BL.reason_key("size"), "size")
        self.assertEqual(BL.reason_key("Wrong size"), "size")
        self.assertEqual(BL.reason_key("  wrong country or place "), "place")
        self.assertEqual(BL.reason_key("vendor"), "")
        self.assertEqual(BL.reason_key(""), "")

    def test_every_reason_has_a_label_to_show(self):
        self.assertEqual([k for k, _ in BL.REASONS], ["size", "place", "competitor", "not_buying", "customer", "other"])
        self.assertTrue(all(BL.REASON_LABEL[k] for k, _ in BL.REASONS))


class TheMemory(unittest.TestCase):
    def test_a_judged_card_is_kept_with_its_reason_newest_first(self):
        m = BL.remember([], [_hit(1)], B.NOT_A_FIT, "Wrong size", AT)
        m = BL.remember(m, [_hit(2)], B.ACCEPTED, "", AT)
        self.assertEqual([(e["who"], e["decision"], e["reason"]) for e in m],
                         [("Company 2 Works", B.ACCEPTED, ""), ("Company 1 Works", B.NOT_A_FIT, "size")])

    def test_judging_a_card_again_replaces_it_and_putting_it_back_forgets_it(self):
        m = BL.remember([], [_hit(1)], B.NOT_A_FIT, "Wrong size", AT)
        m = BL.remember(m, [_hit(1)], B.ACCEPTED, "", AT)
        self.assertEqual([(e["decision"]) for e in m], [B.ACCEPTED])
        self.assertEqual(BL.remember(m, [_hit(1)], B.NEW, "", AT), [])
        self.assertEqual(BL.remember(m, [_hit(1)], B.SKIPPED, "", AT), [])        # skipped is "not yet", not a judgement

    def test_the_same_company_found_on_another_page_is_the_same_judgement(self):
        m = BL.remember([], [_hit(1, "Acme Pumps Pvt Ltd", url="https://acmepumps.in/")], B.NOT_A_FIT, "", AT)
        m = BL.remember(m, [_hit(9, "Acme Pumps", url="https://linkedin.com/company/acme", channel=B.HIRING)],
                        B.ACCEPTED, "", AT)
        self.assertEqual(len(m), 1)

    def test_the_memory_is_capped_to_the_newest(self):
        m = []
        for i in range(450):
            m = BL.remember(m, [_hit(i, f"Firm number {i:04d} Works")], B.NOT_A_FIT, "", AT)
        self.assertEqual(len(m), BL.MEMORY_CAP)
        self.assertEqual(m[0]["who"], "Firm number 0449 Works")


class TheMatcher(unittest.TestCase):
    def setUp(self):
        m = BL.remember([], [_hit(1, "Acme Pumps")], B.NOT_A_FIT, "Wrong size", AT)
        m = BL.remember(m, [_hit(2, "Bharat Valves")], B.ACCEPTED, "", AT)
        self.verdict = BL.matcher(m)

    def test_a_judged_company_is_recognised_by_its_page_or_its_name(self):
        self.assertEqual(self.verdict(_hit(1, "Acme Pumps")), "rejected")
        self.assertEqual(self.verdict(_hit(7, "ACME PUMPS", url="https://elsewhere.in/jobs")), "rejected")
        self.assertEqual(self.verdict(_hit(2, "Bharat Valves")), "accepted")
        self.assertEqual(self.verdict(_hit(3, "Somebody New")), "")

    def test_a_short_or_generic_name_is_never_matched_by_name(self):
        verdict = BL.matcher(BL.remember([], [_hit(1, "Jobs", url="https://a.in/1")], B.NOT_A_FIT, "", AT))
        self.assertEqual(verdict(_hit(2, "Jobs", url="https://b.in/2")), "")          # "Jobs" is too short to be a name
        self.assertEqual(verdict(_hit(1, "Jobs", url="https://a.in/1")), "rejected")   # the same page still is


class TheTaste(unittest.TestCase):
    def test_nothing_judged_says_nothing(self):
        self.assertEqual(BL.lessons([]), "")

    def test_the_model_is_told_what_was_accepted_and_what_was_put_away_and_why(self):
        m = BL.remember([], [_hit(1, "Texas Pumps")], B.NOT_A_FIT, "Wrong country or place", AT)
        m = BL.remember(m, [_hit(2, "Giant Works")], B.NOT_A_FIT, "Wrong size", AT)
        m = BL.remember(m, [_hit(3, "Bharat Valves", why="Hiring two sales executives.")], B.ACCEPTED, "", AT)
        text = BL.lessons(m)
        self.assertIn("ACCEPTED (they want more like these): Bharat Valves (Hiring two sales executives.)", text)
        self.assertIn("Texas Pumps - Wrong country or place", text)
        self.assertIn("Giant Works - Wrong size", text)
        self.assertIn("most often first", text)
        self.assertIn("fit 30 or lower", text)

    def test_the_block_is_capped_so_a_long_history_cannot_swamp_the_prompt(self):
        m = []
        for i in range(100):
            m = BL.remember(m, [_hit(i, f"Firm number {i:04d} Works", why="x" * 200)], B.NOT_A_FIT, "Wrong size", AT)
        self.assertLessEqual(len(BL.lessons(m)), 1400)

    def test_the_scorer_and_the_search_check_both_get_the_taste(self):
        taste = BL.lessons(BL.remember([], [_hit(1, "Texas Pumps")], B.NOT_A_FIT, "Wrong size", AT))
        self.assertIn("Texas Pumps", B.score_prompt("A tool", {}, [_hit(5)], learned=taste))
        self.assertIn("Texas Pumps", B.check_prompt(B.Offer("x"), "s", {}, [], taste))
        self.assertNotIn("ALREADY JUDGED", B.score_prompt("A tool", {}, [_hit(5)]))


class TheReport(unittest.TestCase):
    def test_a_source_is_counted_by_what_the_owner_did_with_its_cards(self):
        m = []
        for i in range(3):
            m = BL.remember(m, [_hit(i, f"Listed firm number {i}")], B.ACCEPTED, "", AT)
        m = BL.remember(m, [_hit(10, "Hiring firm one", channel=B.HIRING)], B.NOT_A_FIT, "", AT)
        rep = {r["channel"]: r for r in BL.report(m)}
        self.assertEqual((rep[B.LIST]["accepted"], rep[B.LIST]["put_away"]), (3, 0))
        self.assertEqual((rep[B.HIRING]["accepted"], rep[B.HIRING]["put_away"]), (0, 1))
        self.assertEqual([r["channel"] for r in BL.report(m)], [B.LIST, B.HIRING])        # in the page's order

    def test_a_source_that_is_nearly_all_put_away_is_named_only_after_enough_cards(self):
        few = [BL.entry_of(_hit(i, f"Hire firm {i}0", channel=B.HIRING), B.NOT_A_FIT, "", AT) for i in range(3)]
        self.assertFalse(BL.report(few)[0]["advice"])
        many = [BL.entry_of(_hit(i, f"Hire firm {i}0", channel=B.HIRING), B.NOT_A_FIT, "", AT) for i in range(9)]
        self.assertTrue(BL.report(many)[0]["advice"])
        mixed = many[:5] + [BL.entry_of(_hit(i + 50, f"Won firm {i}0", channel=B.HIRING), B.ACCEPTED, "", AT)
                            for i in range(4)]
        self.assertFalse(BL.report(mixed)[0]["advice"])

    def test_what_happened_to_the_accepted_buyers_in_people_is_counted_per_source(self):
        out = BL.outcomes([(B.LIST, "Replied"), (B.LIST, "Cold"), (B.LIST, "Interested"), (B.HIRING, "Do Not Contact"),
                           (B.HIRING, "Approaching")])
        self.assertEqual(out[B.LIST], {"saved": 3, "replied": 2, "lost": 0})
        self.assertEqual(out[B.HIRING], {"saved": 2, "replied": 0, "lost": 1})
        m = BL.remember([], [_hit(1)], B.ACCEPTED, "", AT)
        row = BL.report(m, out)[0]
        self.assertEqual((row["replied"], row["saved"]), (2, 3))


def _ask_scores(seen):
    def ask(prompt, purpose, json_mode, temperature):
        seen.append(prompt)
        if "PLANNED SEARCHES" in prompt:
            n = prompt.count('"source":')
            return json.dumps({"checks": [{"n": i, "keep": True} for i in range(n)]})
        rows = json.loads(prompt.split("PAGES:\n")[1].split("\n\nReply")[0])
        return json.dumps({"results": [{"id": r["id"], "role": "buyer", "who": r["title"], "fit": 70, "intent": 30,
                                        "why": "Fits."} for r in rows]})
    return ask


def _row(name, hq="Vadodara, India", staff=20):
    return {"url": f"https://{name.lower().replace(' ', '')}.in", "title": name, "entities": [{"type": "company", "properties": {
        "name": name, "description": f"{name} makes industrial pumps for other businesses.", "workforce": {"total": staff},
        "headquarters": hq}}]}


class FakeLister:
    def __init__(self, rows):
        self.rows, self.signalled = rows, []

    def companies(self, text, where, n):
        return L.profile_rows(self.rows)

    def signals(self, name, exclude=()):
        self.signalled.append(name)
        return []


class TheNextHunt(unittest.TestCase):
    def setUp(self):
        self.offer = B.Offer("An outreach tool", regions="India", ideal="Small Indian B2B firms",
                             company_kinds=("pump maker",), max_staff=100)
        self.rows = [_row("Acme Pumps"), _row("Bharat Valves"), _row("Rajkot Castings")]
        self.memory = BL.remember([], [_hit(1, "Acme Pumps", url="https://acmepumps.in")], B.NOT_A_FIT, "Wrong size", AT)
        self.memory = BL.remember(self.memory, [_hit(2, "Bharat Valves", url="https://bharatvalves.in")], B.ACCEPTED, "", AT)

    def run_hunt(self, memory, seen):
        lister = FakeLister(self.rows)
        res = B.hunt(self.offer, "A tool", [B.BuyerType(key="f", name="Founder")], (B.LIST,), lambda q: [],
                     _ask_scores(seen), today=TODAY, lister=lister, memory=memory)
        return res, lister

    def test_a_company_the_owner_already_judged_is_not_shown_again_and_not_read_again(self):
        seen = []
        res, lister = self.run_hunt(self.memory, seen)
        self.assertEqual([h.who for h in res.hits], ["Rajkot Castings"])
        self.assertEqual(lister.signalled, ["Rajkot Castings"])                       # no signal search spent on them
        self.assertEqual((res.stats["remembered_rejected"], res.stats["remembered_accepted"]), (1, 1))
        self.assertTrue(any("Left out 2 you already judged: 1 you put away, 1 already in People." in n for n in res.notes))
        score_calls = [p for p in seen if "PAGES:" in p]
        self.assertTrue(score_calls and all("Acme Pumps\"" not in p.split("PAGES:")[1] for p in score_calls))

    def test_the_owners_taste_is_in_the_prompts_of_the_next_hunt(self):
        seen = []
        self.run_hunt(self.memory, seen)
        self.assertTrue(all("THE OWNER HAS ALREADY JUDGED" in p for p in seen))
        self.assertTrue(any("Acme Pumps - Wrong size" in p for p in seen))

    def test_with_no_memory_a_hunt_is_what_it_was(self):
        seen = []
        res, _ = self.run_hunt(None, seen)
        self.assertEqual(len(res.hits), 3)
        self.assertFalse(any("ALREADY JUDGED" in p for p in seen))
        self.assertFalse(any("Left out" in n for n in res.notes))

    def test_a_web_card_for_a_company_already_put_away_is_dropped_too(self):
        web = [{"url": "https://jobs.example.com/acme", "title": "Sales executive at Acme Pumps",
                "text": "Acme Pumps is hiring a sales executive in Vadodara, India. " * 3, "publishedDate": "2026-11-15"}]
        offer = B.Offer("x", regions="India")
        mem = BL.remember([], [B.Hit(id="z", channel=B.HIRING, kind=B.INFERRED, who="Sales executive at Acme Pumps",
                                     title="t", snippet="s", url="https://jobs.example.com/acme", source="jobs.example.com")],
                          B.NOT_A_FIT, "", AT)
        types = [B.BuyerType(key="f", name="Founder", hiring_roles=["sales executive"])]
        res = B.hunt(offer, "s", types, (B.HIRING,), lambda q: web, None, today=TODAY, memory=mem)
        self.assertEqual(res.hits, [])
        self.assertEqual(res.stats["remembered_rejected"], 1)


if __name__ == "__main__":
    unittest.main()
