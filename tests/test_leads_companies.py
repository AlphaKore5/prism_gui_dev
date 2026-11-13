"""addons.leads.companies + the account profile's own writes (24-Oct-2026).

Module 2 of the Apollo rebuild: the Companies page. Its data layer must behave
the way Apollo's does — save a company to turn it into an account, filters AND
across and OR within, Total / Net New / Saved — over the companies Prism
already holds: saved accounts, and the employer of everyone in the People pool.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prospector.filters import SearchSpec                       # noqa: E402
from prospector.models import Lead                              # noqa: E402
from addons.leads import accounts as AC                         # noqa: E402
from addons.leads import companies as CO                        # noqa: E402
from addons.leads import pool as P                              # noqa: E402
from addons.leads.contacts import Contact                       # noqa: E402

IMPORT = "imp-20260923-101011-bbbbbb"


def _lead(name, title="", company="", email="", website="", industry="", headcount=""):
    lead = Lead(name=name, title=title, company=company, email=email, industry=industry)
    if website:
        lead.extra["website"] = website
    if headcount:
        lead.extra["headcount"] = headcount
    return lead


def _spec(**kw):
    spec = SearchSpec()
    for facet, value in kw.items():
        if facet in ("headcount", "revenue", "account_imports"):
            setattr(spec, facet, list(value))
        else:
            getattr(spec, facet).include = list(value)
    return spec


class TheAccountProfilesOwnWrites(unittest.TestCase):
    """Apollo's account profile keeps notes, tasks and an activity log beside
    the stage and lists accounts.py already had."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        AC.save(self.dir, [{"name": "Acme Tooling", "website": "acme.example"},
                           {"name": "Beta Dies", "website": "beta.example"}], via="save")
        self.acme = next(a for a in AC.list_accounts(self.dir) if a.name == "Acme Tooling")

    def test_saving_is_the_first_line_of_the_activity(self):
        self.assertEqual([h["kind"] for h in self.acme.history], ["saved"])
        self.assertEqual(self.acme.history[0]["text"], "save")

    def test_a_note_is_kept_and_an_unsaved_company_keeps_none(self):
        note = AC.add_note(self.dir, self.acme, "  Met at the expo  ")
        self.assertEqual(note["text"], "Met at the expo")
        self.assertEqual([n["text"] for n in AC.get(self.dir, self.acme).notes],
                         ["Met at the expo"])
        self.assertIsNone(AC.add_note(self.dir, self.acme, "   "))
        self.assertIsNone(AC.add_note(self.dir, {"name": "Nobody", "website": "nobody.example"},
                                      "hi"))

    def test_a_task_can_be_added_and_ticked_off(self):
        task = AC.add_task(self.dir, self.acme, "Send the brochure", "2026-11-01")
        self.assertEqual(task["id"], "t1")
        self.assertTrue(AC.set_task_done(self.dir, self.acme, "t1"))
        self.assertFalse(AC.set_task_done(self.dir, self.acme, "t1"))     # already done
        [t] = AC.get(self.dir, self.acme).tasks
        self.assertTrue(t["done"])
        self.assertEqual(t["due"], "2026-11-01")

    def test_the_stage_change_is_logged_with_where_it_went(self):
        self.assertTrue(AC.set_stage(self.dir, self.acme, "Current Client"))
        last = AC.get(self.dir, self.acme).history[-1]
        self.assertEqual((last["kind"], last["text"]), ("stage", "Cold → Current Client"))

    def test_an_activity_logged_by_hand_and_an_unknown_kind(self):
        self.assertEqual(AC.log(self.dir, self.acme, "call", "Asked for a quote")["kind"], "call")
        self.assertIsNone(AC.log(self.dir, self.acme, "teleport", "x"))
        self.assertEqual(AC.get(self.dir, self.acme).history[-1]["text"], "Asked for a quote")

    def test_edit_company_info_writes_fields_and_follows_the_website(self):
        self.assertTrue(AC.edit(self.dir, self.acme, {"industry": "Press tools",
                                                      "website": "https://www.acme-tools.example",
                                                      "phone": "+91 265 000 0000",
                                                      "stage": "ignored"}))
        got = AC.get(self.dir, self.acme)
        self.assertEqual((got.industry, got.phone), ("Press tools", "+91 265 000 0000"))
        self.assertEqual(got.domain, "acme-tools.example")
        self.assertEqual(got.history[-1]["kind"], "edited")
        self.assertIn("industry", got.history[-1]["text"])
        self.assertFalse(AC.edit(self.dir, got, {"industry": "Press tools"}))   # nothing new
        self.assertFalse(AC.edit(self.dir, got, {"stage": "Dead Opportunity"}))

    def test_a_blank_clears_a_field_but_never_the_name(self):
        AC.edit(self.dir, self.acme, {"industry": "Dies"})
        AC.edit(self.dir, self.acme, {"industry": "", "name": ""})
        got = AC.get(self.dir, self.acme)
        self.assertEqual((got.industry, got.name), ("", "Acme Tooling"))

    def test_bulk_stage_and_list_touch_only_the_accounts_named(self):
        self.assertEqual(AC.set_stage_many(self.dir, [self.acme], "Do Not Prospect"), 1)
        self.assertEqual(AC.set_stage_many(self.dir, [self.acme], "Do Not Prospect"), 0)
        self.assertEqual(AC.add_to_list(self.dir, [self.acme], "Vadodara"), 1)
        self.assertEqual(AC.add_to_list(self.dir, [self.acme], "Vadodara"), 0)
        by = {a.name: a for a in AC.list_accounts(self.dir)}
        self.assertEqual((by["Acme Tooling"].stage, by["Acme Tooling"].lists),
                         ("Do Not Prospect", ["Vadodara"]))
        self.assertEqual((by["Beta Dies"].stage, by["Beta Dies"].lists), ("Cold", []))
        self.assertEqual(by["Acme Tooling"].history[-1]["kind"], "list")

    def test_delete_account_removes_exactly_those(self):
        self.assertEqual(AC.remove(self.dir, [self.acme]), 1)
        self.assertEqual([a.name for a in AC.list_accounts(self.dir)], ["Beta Dies"])
        self.assertEqual(AC.remove(self.dir, [self.acme]), 0)

    def test_an_older_file_without_notes_or_history_still_reads(self):
        import json
        path = os.path.join(self.dir, AC.FILE)
        doc = json.load(open(path, encoding="utf-8"))
        for row in doc["accounts"]:
            for key in ("notes", "tasks", "history"):
                row.pop(key, None)
        json.dump(doc, open(path, "w", encoding="utf-8"))
        [a, b] = AC.list_accounts(self.dir)
        self.assertEqual((a.notes, a.tasks, a.history), ([], [], []))

    def test_a_note_noted_by_the_lookup_is_one_line_each(self):
        self.assertEqual(AC.note_enriched(self.dir, [self.acme], "website, size"), 1)
        self.assertEqual(AC.get(self.dir, self.acme).history[-1],
                         {"at": AC.get(self.dir, self.acme).history[-1]["at"],
                          "kind": "enriched", "text": "website, size"})


class BuildingThePool(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        AC.save(self.dir, [
            {"name": "Acme Tooling Pvt. Ltd.", "website": "acme.example",
             "industry": "Machine tools", "headcount": "120", "location": "Vadodara, India",
             "revenue": "5000000"},
            {"name": "Beta Dies", "industry": "Moulds and dies", "headcount": "40",
             "location": "Pune, India"}], via="import", import_id=IMPORT)
        self.accounts = AC.list_accounts(self.dir)
        run = [_lead("Asha Rao", "Owner", "Acme Tooling", "asha@acme.example"),
               _lead("Ravi Shah", "Purchase Head", "ACME TOOLING PVT LTD"),
               _lead("Mia Chen", "Director", "Gamma Fabrication",
                     website="https://www.gamma-fab.example", industry="Sheet metal",
                     headcount="500+"),
               _lead("Tom Boyd", "Buyer", "Gamma Fab", "tom@gamma-fab.example"),
               _lead("Zed Pal", "Manager", "Beta Dies"),
               _lead("Joe Lee", "Manager", "Mailbox Co", "joe@gmail.com"),
               _lead("No Company", "Clerk", "")]
        saved = [Contact(lead=run[0], saved_at="2026-10-01T10:00:00+05:30", via=["save"])]
        self.people = P.build(saved, [("s1", "2026-10-02T10:00:00+05:30", run, [])])
        self.pool = CO.build(self.accounts, self.people)

    def by_name(self, fragment):
        return next(c for c in self.pool if fragment.lower() in c.name.lower())

    def test_one_company_per_domain_or_name_and_nobody_without_one(self):
        names = sorted(c.name for c in self.pool)
        self.assertEqual(names, ["Acme Tooling Pvt. Ltd.", "Beta Dies", "Gamma Fabrication",
                                 "Mailbox Co"])
        self.assertNotIn("No Company", names)

    def test_a_saved_accounts_own_record_wins_and_it_carries_its_people(self):
        acme = self.by_name("acme")
        self.assertTrue(acme.saved)
        self.assertEqual((acme.stage, acme.industry, acme.location),
                         ("Cold", "Machine tools", "Vadodara, India"))
        self.assertEqual(sorted(p.lead.name for p in acme.people), ["Asha Rao", "Ravi Shah"])
        self.assertEqual(acme.people[0].lead.name, "Asha Rao")        # a saved contact first
        self.assertEqual((acme.people_count, acme.saved_people), (2, 1))

    def test_a_company_only_known_from_a_person_is_net_new_with_their_facts(self):
        gamma = self.by_name("gamma")
        self.assertFalse(gamma.saved)
        self.assertEqual(gamma.stage, "")
        self.assertEqual((gamma.domain, gamma.industry, gamma.headcount),
                         ("gamma-fab.example", "Sheet metal", "500+"))
        self.assertEqual(gamma.people_count, 2)       # "Gamma Fab" joined by the domain

    def test_a_free_mail_domain_is_nobodys_company(self):
        mailbox = self.by_name("mailbox")
        self.assertEqual(mailbox.domain, "")
        self.assertEqual(self.by_name("beta").people_count, 1)

    def test_a_directory_address_does_not_become_a_company_domain(self):
        run = [_lead("Dee Roy", "Owner", "Local Works", "dee@tradeindia.com")]
        pool = CO.build([], P.build([], [("s2", "2026-10-03T00:00:00+05:30", run, [])]))
        self.assertEqual((pool[0].name, pool[0].domain), ("Local Works", ""))

    def test_total_net_new_and_saved(self):
        tabs = CO.split(self.pool)
        self.assertEqual({k: len(v) for k, v in tabs.items()},
                         {"total": 4, "net_new": 2, "saved": 2})
        self.assertEqual(sorted(c.name for c in tabs["net_new"]),
                         ["Gamma Fabrication", "Mailbox Co"])


class FilteringLikeApollo(unittest.TestCase):
    def setUp(self):
        BuildingThePool.setUp(self)

    def names(self, spec, **kw):
        return sorted(c.name for c in CO.filter_companies(self.pool, spec, **kw))

    def test_no_filter_keeps_everyone(self):
        self.assertEqual(len(self.names(SearchSpec())), 4)

    def test_a_company_filter_matches_the_name_once_legal_words_go_or_the_domain(self):
        self.assertEqual(self.names(_spec(companies=["Acme Tooling Ltd"])),
                         ["Acme Tooling Pvt. Ltd."])
        self.assertEqual(self.names(_spec(companies=["gamma-fab.example"])),
                         ["Gamma Fabrication"])

    def test_or_within_a_filter_and_across_filters(self):
        self.assertEqual(self.names(_spec(companies=["Acme", "Beta"])),
                         ["Acme Tooling Pvt. Ltd.", "Beta Dies"])
        self.assertEqual(self.names(_spec(companies=["Acme", "Beta"],
                                          industries=["Moulds"])), ["Beta Dies"])

    def test_an_industry_include_needs_a_company_that_says_so(self):
        self.assertEqual(self.names(_spec(industries=["Sheet metal"])), ["Gamma Fabrication"])
        self.assertEqual(self.names(_spec(industries=["Aerospace"])), [])

    def test_an_industry_exclude_removes_what_says_so(self):
        spec = SearchSpec()
        spec.industries.exclude = ["Machine tools"]
        self.assertNotIn("Acme Tooling Pvt. Ltd.", self.names(spec))

    def test_headcount_bands_and_an_unknown_size_is_let_through(self):
        # Acme 120 and Beta 40 are on record; Mailbox Co has no size at all.
        self.assertEqual(self.names(_spec(headcount=["51-200"])),
                         ["Acme Tooling Pvt. Ltd.", "Mailbox Co"])
        self.assertEqual(self.names(_spec(headcount=["11-50"])), ["Beta Dies", "Mailbox Co"])

    def test_revenue_band_reads_the_dollar_figure(self):
        self.assertEqual(self.names(_spec(revenue=["1m-10m"])),
                         ["Acme Tooling Pvt. Ltd.", "Beta Dies", "Gamma Fabrication",
                          "Mailbox Co"])           # only Acme has a figure, in range
        self.assertEqual(self.names(_spec(revenue=["50m-100m"])),
                         ["Beta Dies", "Gamma Fabrication", "Mailbox Co"])

    def test_a_location_filter_reads_the_companys_own_hq(self):
        self.assertEqual(self.names(_spec(company_hq=["Vadodara"])),
                         ["Acme Tooling Pvt. Ltd."])
        # a company whose HQ nobody knows can't be proven inside a place
        self.assertNotIn("Gamma Fabrication", self.names(_spec(company_hq=["India"])))

    def test_stage_and_lists_are_the_accounts_and_a_net_new_company_has_neither(self):
        AC.set_stage(self.dir, self.accounts[0], "Current Client")
        pool = CO.build(AC.list_accounts(self.dir), self.people)
        spec = SearchSpec()
        spec.account_stages.include = ["Current Client"]
        self.assertEqual([c.name for c in CO.filter_companies(pool, spec)],
                         [self.accounts[0].name])
        spec = SearchSpec()
        spec.account_stages.exclude = ["Current Client"]
        self.assertEqual(len(CO.filter_companies(pool, spec)), 3)     # net new passes an exclude

    def test_the_account_csv_import_filter(self):
        self.assertEqual(self.names(_spec(account_imports=[IMPORT])),
                         ["Acme Tooling Pvt. Ltd.", "Beta Dies"])
        self.assertEqual(self.names(_spec(account_imports=["imp-none"])), [])

    def test_a_custom_field_on_the_account(self):
        AC.save(self.dir, [{"name": "Beta Dies", "custom": {"Tier": "A"}}], via="import",
                update=True)
        pool = CO.build(AC.list_accounts(self.dir), self.people)
        spec = SearchSpec()
        spec.custom_fields = {"account:Tier": ["A"]}
        self.assertEqual([c.name for c in CO.filter_companies(pool, spec)], ["Beta Dies"])
        spec.custom_fields = {"contact:Tier": ["A"]}                  # not a company's field
        self.assertEqual(len(CO.filter_companies(pool, spec)), 4)

    def test_the_search_box_reads_name_domain_industry_and_place(self):
        self.assertEqual(self.names(SearchSpec(), query="gamma-fab"), ["Gamma Fabrication"])
        self.assertEqual(self.names(SearchSpec(), query="pune"), ["Beta Dies"])
        self.assertEqual(self.names(SearchSpec(), query="machine"), ["Acme Tooling Pvt. Ltd."])


class SortingPagingAndPicking(unittest.TestCase):
    def setUp(self):
        BuildingThePool.setUp(self)

    def test_the_sorts(self):
        names = lambda how: [c.name for c in CO.sort_companies(self.pool, how)]
        self.assertEqual(names("name"), ["Acme Tooling Pvt. Ltd.", "Beta Dies",
                                         "Gamma Fabrication", "Mailbox Co"])
        self.assertEqual(names("people")[:2], ["Acme Tooling Pvt. Ltd.", "Gamma Fabrication"])
        self.assertEqual(names("size")[0], "Gamma Fabrication")        # 500+ over Acme's 120
        self.assertEqual(names("size")[-1], "Mailbox Co")                # unknown last
        self.assertEqual(names("relevance")[0], "Acme Tooling Pvt. Ltd.")

    def test_a_page_of_twenty_five_and_a_number_to_pick(self):
        info = CO.page(self.pool, 0)
        self.assertEqual((info["total"], info["pages"], info["start"], info["end"]),
                         (4, 1, 1, 4))
        self.assertEqual(len(CO.pick(self.pool, 2)), 2)
        self.assertEqual(len(CO.pick(self.pool, 0)), 4)

    def test_the_export_table_carries_the_record_the_stage_and_the_people(self):
        header, rows = CO.export_table(self.pool)
        acme = next(r for r in rows if r[0].startswith("Acme"))
        self.assertEqual(header[:3], ["Company", "Website", "Domain"])
        self.assertEqual(acme[header.index("Stage")], "Cold")
        self.assertEqual((acme[header.index("People held")], acme[header.index("Saved contacts")]),
                         (2, 1))

    def test_money_and_sizes_as_a_sheet_writes_them(self):
        self.assertEqual(CO.number("51-200"), 51)
        self.assertEqual(CO.number("1,200"), 1200)
        self.assertIsNone(CO.number("Not Found"))
        self.assertEqual(CO.revenue_usd("$5M"), 5_000_000)
        self.assertEqual(CO.revenue_usd("12.5 million"), 12_500_000)
        self.assertEqual(CO.revenue_usd("50000000"), 50_000_000)
        self.assertIsNone(CO.revenue_usd("₹120 Cr"))                  # rupees are never guessed
        self.assertIsNone(CO.revenue_usd("Not Found"))


if __name__ == "__main__":
    unittest.main()
