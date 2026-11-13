"""The Companies tab — Apollo's Companies page (addons.leads.companies_page,
company_panel, companies_controller), 24-Oct-2026.

The page is a view: it shows the one page of companies it is handed, a tick
arms the action bar and the *Requested signals carry exactly the ticked
companies, a click opens a profile in place of the list. The controller around
it answers from the same pool the People page uses — filters instant and free,
Total / Net New / Saved, and every act (Save, Add to list, Set stage, Edit,
Delete, a note, a task) carried out on the saved accounts, saving the company
first when it is not one yet. Nothing here touches a real folder, a real key or
a network: every store is a temp dir and every modal is a seam.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt                                   # noqa: E402
from PySide6.QtWidgets import QApplication                      # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector.models import Lead                              # noqa: E402
from addons.leads import accounts as AC                         # noqa: E402
from addons.leads import companies as CO                        # noqa: E402
from addons.leads import companies_page as CP                   # noqa: E402
from addons.leads import company_panel as CPN                   # noqa: E402
from addons.leads import contacts as CT                         # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _company(name, domain="", saved=False, stage="", industry="", location="",
             headcount="", people=()):
    c = CO.Company(name=name, domain=domain, website=domain, industry=industry,
                   location=location, headcount=headcount, saved=saved, stage=stage)
    c.keys = frozenset({"n:" + name.casefold()} | ({"d:" + domain} if domain else set()))
    c.people = tuple(people)
    return c


def _rows():
    return [_company("Acme Tooling", "acme.example", True, "Cold", "Machine tools",
                     "Vadodara, India", "120"),
            _company("Beta Dies", "", False, "", "Moulds", "Pune, India", "51-200"),
            _company("Gamma Fab", "gamma.example", True, "Current Client", "Sheet metal",
                     "Surat, India", "1200")]


class _Signal:
    """Records what a signal carried, so a test reads it back."""

    def __init__(self, signal):
        self.got = []
        signal.connect(lambda *a: self.got.append(a))


class ThePage(unittest.TestCase):
    def setUp(self):
        self.page = CP.CompaniesPage()
        self.page.resize(1100, 700)
        self.rows = _rows()

    def test_it_opens_on_an_empty_state_with_no_action_bar(self):
        self.assertEqual(self.page._view_stack.currentIndex(), 1)
        self.assertTrue(self.page._bulk_bar_w.isHidden())
        self.assertEqual(self.page._table.columnCount(), 6)

    def test_a_row_says_name_domain_industry_place_size_stage_and_people(self):
        self.rows[0].people = (object(), object())
        self.page.set_companies(self.rows, {"page": 0, "pages": 1, "start": 1, "end": 3,
                                            "total": 3},
                                {"total": 3, "net_new": 1, "saved": 2})
        t = self.page._table
        self.assertEqual(self.page._view_stack.currentIndex(), 2)          # the row list is the default view; 1 is the empty state
        self.assertEqual(t.rowCount(), 3)
        self.assertEqual(t.item(0, CP._C_NAME).text(), "Acme Tooling")
        self.assertEqual(t.item(0, CP._C_NAME).data(CP.K._COMPANY_ROLE), "acme.example")
        self.assertEqual(t.item(0, CP._C_INDUSTRY).text(), "Machine tools")
        self.assertEqual(t.item(0, CP._C_INDUSTRY).data(CP.K._WHERE_ROLE), "Vadodara, India")
        self.assertEqual(t.item(0, CP._C_SIZE).text(), "120")
        self.assertEqual(t.item(2, CP._C_SIZE).text(), "1,200")      # a bare number is spaced
        self.assertEqual(t.item(1, CP._C_SIZE).text(), "51-200")     # words stay as written
        self.assertEqual(t.item(0, CP._C_STAGE).text(), "Cold")
        self.assertEqual(t.item(1, CP._C_STAGE).text(), "Net new")   # not an account yet
        self.assertEqual(t.item(0, CP._C_PEOPLE).text(), "2 people")
        self.assertEqual(t.item(1, CP._C_PEOPLE).text(), "")

    def test_the_tabs_carry_their_counts_and_the_pager_its_range(self):
        self.page.set_companies(self.rows, {"page": 0, "pages": 2, "start": 1, "end": 3,
                                            "total": 40},
                                {"total": 40, "net_new": 12, "saved": 28})
        self.assertEqual(self.page._tab_btns["total"].text(), "Total\n40")
        self.assertEqual(self.page._tab_btns["saved"].text(), "Saved\n28")
        self.assertEqual(self.page._range_lbl.text(), "1 - 3 of 40")
        self.assertFalse(self.page._pager.isHidden())
        self.assertTrue(self.page._prev_btn.isEnabled() is False)
        seen = _Signal(self.page.tabChanged)
        self.page._tab_btns["net_new"].click()
        self.assertEqual(seen.got, [("net_new",)])

    def test_ticking_arms_the_action_bar_and_the_signals_carry_the_ticked(self):
        self.page.set_companies(self.rows, {"page": 0, "pages": 1, "start": 1, "end": 3,
                                            "total": 3}, None)
        saved, stage = _Signal(self.page.saveRequested), _Signal(self.page.stageRequested)
        self.page._tick_row(1)
        self.assertFalse(self.page._bulk_bar_w.isHidden())
        self.assertEqual(self.page._sel_lbl.text(), "1 selected")
        self.page._b_save.click()
        self.assertEqual([c.name for c in saved.got[0][0]], ["Beta Dies"])
        self.page.stageRequested.emit(self.page.selected(), "Current Client")
        self.assertEqual(stage.got[0][1], "Current Client")
        self.page._tick_row(1)
        self.assertTrue(self.page._bulk_bar_w.isHidden())

    def test_the_selection_outlives_the_page_and_select_all_takes_every_page(self):
        first, second = self.rows[:2], self.rows[2:]
        everyone = self.rows
        self.page.set_companies(first, {"page": 0, "pages": 2, "start": 1, "end": 2,
                                        "total": 3}, None, universe=everyone)
        self.page._tick_row(0)
        self.page.set_companies(second, {"page": 1, "pages": 2, "start": 3, "end": 3,
                                         "total": 3}, None, universe=everyone)
        self.assertEqual([c.name for c in self.page.selected()], ["Acme Tooling"])
        self.page._select_all()
        self.assertEqual(len(self.page.selected()), 3)
        self.assertEqual(self.page._sel_lbl.text(), "3 selected")
        self.page.clear_selection()
        self.assertEqual(self.page.selected(), [])

    def test_select_number_takes_the_first_n_of_the_result(self):
        self.page.set_companies(self.rows, {"page": 0, "pages": 1, "start": 1, "end": 3,
                                            "total": 3}, None)
        self.page._select_number(2)
        self.assertEqual([c.name for c in self.page.selected()],
                         ["Acme Tooling", "Beta Dies"])

    def test_a_click_opens_the_company_but_a_click_in_the_tick_column_does_not(self):
        self.page.set_companies(self.rows, {"page": 0, "pages": 1, "start": 1, "end": 3,
                                            "total": 3}, None)
        opened = _Signal(self.page.openRequested)
        self.page._on_cell_clicked(0, CP._C_TICK)
        self.assertEqual(opened.got, [])
        self.page._on_cell_clicked(2, CP._C_NAME)
        self.assertEqual(opened.got[0][0].name, "Gamma Fab")

    def test_the_profile_replaces_the_list_and_back_returns_to_it(self):
        view = CPN.CompanyView(company=self.rows[0], account=None, people=[])
        self.page.show_profile(view)
        self.assertTrue(self.page.profile_open())
        self.assertIs(self.page.open_company(), self.rows[0])
        self.page.panel.backRequested.emit()
        self.assertFalse(self.page.profile_open())
        self.assertIsNone(self.page.open_company())

    def test_what_a_lookup_could_still_fill_in(self):
        self.assertTrue(CP.CompaniesPage.needs_lookup(_company("No Site")))
        full = _company("Full", "full.example", headcount="10")
        full.revenue, full.location = "1000000", "Pune"
        self.assertFalse(CP.CompaniesPage.needs_lookup(full))
        self.assertFalse(CP.CompaniesPage.needs_lookup(CO.Company()))


class TheProfilePanel(unittest.TestCase):
    def setUp(self):
        self.panel = CPN.CompanyPanel()
        self.panel.resize(900, 700)
        self.dir = tempfile.mkdtemp()
        AC.save(self.dir, [{"name": "Acme Tooling", "website": "acme.example",
                            "industry": "Machine tools", "location": "Vadodara, India"}],
                via="save")
        AC.add_note(self.dir, {"name": "Acme Tooling", "website": "acme.example"}, "Met at expo")
        AC.add_task(self.dir, {"name": "Acme Tooling", "website": "acme.example"}, "Call back",
                    "2026-11-02")
        self.account = AC.list_accounts(self.dir)[0]
        self.company = CO.build([self.account], [])[0]

    def _show(self, saved=True):
        self.panel.show_company(CPN.CompanyView(
            company=self.company if saved else _company("Net New Co"),
            account=self.account if saved else None))

    def test_a_saved_company_shows_its_notes_tasks_stage_and_activity(self):
        self._show()
        self.assertEqual(self.panel.name.text(), "Acme Tooling")
        self.assertTrue(self.panel._save_btn.isHidden())
        self.assertEqual(self.panel.stage.currentData(), "Cold")
        self.assertEqual(list(self.panel.task_boxes), ["t1"])
        texts = [a["text"] for a in CPN.activities(self.panel.view)]
        self.assertTrue(any("Note: Met at expo" in t for t in texts))
        self.assertTrue(any("Task: Call back" in t for t in texts))
        self.assertTrue(any("Saved as an account" in t for t in texts))

    def test_an_unsaved_company_offers_save_and_says_it_is_not_one_yet(self):
        self._show(saved=False)
        self.assertFalse(self.panel._save_btn.isHidden())
        self.assertFalse(self.panel._act_delete.isEnabled())
        self.assertEqual(self.panel.stage.currentData(), "")

    def test_every_act_is_a_signal_with_the_company(self):
        self._show()
        seen = {name: _Signal(getattr(self.panel, name)) for name in (
            "noteRequested", "taskRequested", "logRequested", "stageRequested",
            "findPeopleRequested", "listRequested", "enrichRequested", "deleteRequested")}
        self.panel.note_edit.setPlainText("  Sent the quote ")
        self.panel._add_note()
        self.panel.task_text.setText("Chase")
        self.panel.task_due_on.setChecked(True)
        self.panel._add_task()
        self.panel._log_form("call")
        self.panel.log_text.setPlainText("Left a voicemail")
        self.panel._log_it()
        self.panel.stage.setCurrentIndex(self.panel.stage.findData("Current Client"))
        self.panel._stage_picked(0)
        self.panel._find_btn.click()
        self.panel._list_btn.click()
        self.panel._enrich()
        self.panel.confirm_delete = lambda name: True
        self.panel._delete()
        self.assertEqual(seen["noteRequested"].got[0][1], "Sent the quote")
        self.assertEqual(seen["taskRequested"].got[0][1], "Chase")
        self.assertRegex(seen["taskRequested"].got[0][2], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(seen["logRequested"].got[0][1:], ("call", "Left a voicemail"))
        self.assertEqual(seen["stageRequested"].got[0][1], "Current Client")
        for name in ("findPeopleRequested", "listRequested", "enrichRequested",
                     "deleteRequested"):
            self.assertIs(seen[name].got[0][0], self.company, name)

    def test_the_enrichment_tab_lists_what_is_missing(self):
        self._show()
        self.assertEqual(self.panel.missing_fields, ["headcount", "revenue", "description"])
        self.assertTrue(self.panel.enrich_btn.isEnabled())

    def test_all_fields_searches_by_name_and_value(self):
        self._show()
        labels = [k for k, _v in self.panel.field_rows]
        self.assertIn("Industry", labels)
        self.panel.field_search.setText("vadodara")
        self.assertEqual([k for k, _v in self.panel.field_rows], ["Headquarters"])

    def test_people_here_are_links_that_pick_a_person(self):
        from addons.leads import pool as P
        run = [Lead(name="Asha Rao", title="Owner", company="Acme Tooling")]
        people = P.build([], [("s1", "2026-10-02T10:00:00+05:30", run, [])])
        company = CO.build([self.account], people)[0]
        self.panel.show_company(CPN.CompanyView(company=company, account=self.account,
                                                people=list(company.people)))
        picked = _Signal(self.panel.personPicked)
        self.panel.people_links[0].click()
        self.assertEqual(picked.got[0][0].lead.name, "Asha Rao")


class TheCompaniesRail(unittest.TestCase):
    """The filter panel in its company kind: Apollo's Companies page rail."""

    def setUp(self):
        from addons.leads import filter_panel as FP
        self.FP = FP
        self.rail = FP.FilterPanel(kind="company")
        self.people = FP.FilterPanel()

    def test_it_offers_only_the_company_level_facets_pinned_first(self):
        self.assertEqual(self.rail.kind, "company")
        self.assertEqual(self.rail._order, self.FP._COMPANY_PINNED + self.FP._COMPANY_MORE)
        for person_only in ("job_titles", "seniority", "functions", "locations",
                            "years_in_role", "email_status", "contact_imports"):
            self.assertNotIn(person_only, self.rail._order)
        self.assertEqual(self.people.kind, "person")                   # the default is unchanged
        self.assertEqual(self.people._order, self.FP._PINNED + self.FP._MORE)

    def test_a_facet_is_called_what_the_companies_page_calls_it(self):
        self.assertEqual(self.rail._title("company_hq"), "Location")
        self.assertEqual(self.rail._title("headcount"), "# of employees")
        self.assertEqual(self.rail._title("account_imports"), "Account CSV import")
        self.assertNotEqual(self.people._title("company_hq"), "Location")

    def test_stage_and_lists_are_the_accounts_own_with_no_switch(self):
        self.assertEqual(self.rail._sides()["stages"], (("account_stages", "Account", ""),))
        self.assertEqual(self.rail._sides()["lists"], (("account_lists", "Company", ""),))
        self.assertEqual(len(self.people._sides()["stages"]), 2)       # People keeps both

    def test_the_all_filters_groups_are_the_companys(self):
        self.assertEqual([k for k, _ in self.rail.categories()], ["company", "records"])
        self.assertIn("person", [k for k, _ in self.people.categories()])

    def test_a_chosen_filter_reads_back_as_the_spec_the_page_filters_with(self):
        spec = self.rail.spec()
        spec.industries.include = ["Forging"]
        spec.company_hq.include = ["Gujarat"]
        self.rail.set_spec(spec)
        got = self.rail.spec()
        self.assertEqual((got.industries.include, got.company_hq.include),
                         (["Forging"], ["Gujarat"]))
        self.assertEqual(self.rail.active_count(), 2)
        self.rail.clear()
        self.assertEqual(self.rail.active_count(), 0)


class TheControllerAroundAWorkbench(unittest.TestCase):
    """A real LeadsWorkbench on temp folders, asked what the owner would ask."""

    def setUp(self):
        from addons.leads import workbench as WB
        self._WB = WB
        self._dirs = {name: tempfile.mkdtemp() for name in (
            "tmp", "sessions", "searches", "contacts", "imports", "accounts", "removed")}
        self._saved_attrs = {name: getattr(WB.LeadsWorkbench, name) for name in (
            "_autosave_dir", "_sessions_dir", "_searches_dir", "_contacts_dir",
            "_imports_dir", "_accounts_dir", "_removed_dir")}
        for attr, key in (("_autosave_dir", "tmp"), ("_sessions_dir", "sessions"),
                          ("_searches_dir", "searches"), ("_contacts_dir", "contacts"),
                          ("_imports_dir", "imports"), ("_accounts_dir", "accounts"),
                          ("_removed_dir", "removed")):
            setattr(WB.LeadsWorkbench, attr, lambda _self, k=key: self._dirs[k])
        AC.save(self._dirs["accounts"], [
            {"name": "Acme Tooling", "website": "acme.example", "industry": "Machine tools",
             "headcount": "120", "location": "Vadodara, India"},
            {"name": "Beta Dies", "industry": "Moulds", "headcount": "40"}], via="import")
        leads = [Lead(name="Asha Rao", title="Owner", company="Acme Tooling",
                      email="asha@acme.example"),
                 Lead(name="Mia Chen", title="Director", company="Gamma Fab",
                      industry="Sheet metal")]
        CT.save(self._dirs["contacts"], leads[:1], via="save")
        self.wb = WB.LeadsWorkbench({})
        self.wb._contacts = CT.list_contacts(self._dirs["contacts"])
        self.wb._runs = {"s1": ("s1", "2026-10-02T10:00:00+05:30", leads, [], [], {})}
        self.wb._reload_accounts()
        self.wb._rebuild_pool()
        self.ctl = self.wb._companies
        self.ctl.on_shown()

    def tearDown(self):
        for name, value in self._saved_attrs.items():
            setattr(self._WB.LeadsWorkbench, name, value)

    def names(self):
        return [self.ctl.page._table.item(r, CP._C_NAME).text()
                for r in range(self.ctl.page._table.rowCount())]

    def company(self, name):
        return next(c for c in self.ctl._pool if c.name == name)

    def test_the_tab_is_there_and_shows_every_company_prism_knows(self):
        from addons.leads import cockpit as CK
        self.assertEqual(CK._TABS[1], "Companies")
        self.assertIs(self.wb._cockpit.companies, self.ctl.page)
        self.assertEqual(sorted(self.names()), ["Acme Tooling", "Beta Dies", "Gamma Fab"])
        self.assertEqual(self.ctl.page._tab_btns["total"].text(), "Total\n3")
        self.assertEqual(self.ctl.page._tab_btns["net_new"].text(), "Net New\n1")
        self.assertEqual(self.ctl.page._tab_btns["saved"].text(), "Saved\n2")

    def test_the_tabs_split_and_the_filters_answer_at_once(self):
        self.ctl.page._tab_btns["saved"].click()
        self.assertEqual(sorted(self.names()), ["Acme Tooling", "Beta Dies"])
        self.ctl.page._tab_btns["total"].click()
        spec = self.ctl.filters.spec()
        spec.industries.include = ["Sheet metal"]
        self.ctl.filters.set_spec(spec)
        self.assertEqual(self.names(), ["Gamma Fab"])
        self.assertEqual(self.ctl.page._filters_btn.text(), "Hide filters  1")
        self.ctl.filters.clear()
        self.assertEqual(len(self.names()), 3)

    def test_the_search_box_and_the_sort_re_answer(self):
        self.ctl.page.queryChanged.emit("beta")
        self.assertEqual(self.names(), ["Beta Dies"])
        self.ctl.page.queryChanged.emit("")
        self.ctl.page.sortChanged.emit("name")
        self.assertEqual(self.names(), ["Acme Tooling", "Beta Dies", "Gamma Fab"])

    def test_the_companies_rail_stays_out_of_the_tour(self):
        """It answers the same facet keys as the People rail; from a tab that is
        not showing it, it used to win a key its sibling should answer and the
        step was skipped as not drawn."""
        from addons.leads import tour as T
        self.assertEqual(self.ctl.filters.help_targets(), {})
        self.ctl.filters.help_reveal("facet_account_imports")           # does nothing
        guide = T.Guide(self.wb)
        found = guide.help_targets()
        self.assertIs(found["facet_account_imports"],
                      self.wb._filters.help_targets()["facet_account_imports"])

    def test_the_company_rail_is_the_companies_own_and_offers_the_pools_names(self):
        self.assertEqual(self.ctl.filters.kind, "company")
        self.assertIn("Acme Tooling", self.ctl._suggest("companies", "acm"))
        self.assertIn("Moulds", self.ctl._suggest("industries", "mou"))

    def test_save_makes_a_net_new_company_an_account_and_moves_it_to_saved(self):
        gamma = self.company("Gamma Fab")
        self.assertFalse(gamma.saved)
        self.ctl._save([gamma, self.company("Acme Tooling")])
        self.ctl.on_shown()
        self.assertIn("Saved 1 company as an account", self.wb._status.text())
        self.assertEqual(sorted(a.name for a in AC.list_accounts(self._dirs["accounts"])),
                         ["Acme Tooling", "Beta Dies", "Gamma Fab"])
        self.assertTrue(self.company("Gamma Fab").saved)
        self.ctl._save([self.company("Gamma Fab")])
        self.assertIn("already saved", self.wb._status.text())

    def test_set_stage_saves_first_and_moves_them(self):
        self.ctl._set_stage([self.company("Gamma Fab"), self.company("Acme Tooling")],
                            "Current Client")
        self.ctl.on_shown()
        stages = {a.name: a.stage for a in AC.list_accounts(self._dirs["accounts"])}
        self.assertEqual((stages["Gamma Fab"], stages["Acme Tooling"], stages["Beta Dies"]),
                         ("Current Client", "Current Client", "Cold"))
        self.assertIn("Moved 2 companies to Current Client.", self.wb._status.text())

    def test_add_to_list_tags_the_accounts_and_cancel_does_nothing(self):
        self.ctl.ask_list_name = lambda default: None
        self.ctl._add_to_list([self.company("Acme Tooling")])
        self.assertEqual(AC.list_accounts(self._dirs["accounts"])[0].lists, [])
        self.ctl.ask_list_name = lambda default: "Vadodara tooling"
        self.ctl._add_to_list([self.company("Acme Tooling"), self.company("Gamma Fab")])
        lists = {a.name: a.lists for a in AC.list_accounts(self._dirs["accounts"])}
        self.assertEqual((lists["Acme Tooling"], lists["Gamma Fab"]),
                         (["Vadodara tooling"], ["Vadodara tooling"]))

    def test_export_writes_a_csv_with_the_record_and_how_many_people_are_held(self):
        path = os.path.join(self._dirs["tmp"], "out.csv")
        self.ctl.ask_export_path = lambda default: path
        self.ctl._export([self.company("Acme Tooling")])
        text = open(path, encoding="utf-8-sig").read()
        self.assertIn("Company,Website,Domain", text)
        self.assertIn("Acme Tooling", text)
        self.assertIn("Exported 1 companies", self.wb._status.text())
        self.ctl.ask_export_path = lambda default: ""
        self.ctl._export([self.company("Acme Tooling")])            # Cancel: no error, nothing

    def test_delete_asks_and_only_saved_companies_are_accounts(self):
        self.ctl.confirm_delete = lambda n: False
        self.ctl._delete([self.company("Acme Tooling")])
        self.assertEqual(len(AC.list_accounts(self._dirs["accounts"])), 2)
        self.ctl.confirm_delete = lambda n: True
        self.ctl._delete([self.company("Acme Tooling"), self.company("Gamma Fab")])
        self.assertEqual([a.name for a in AC.list_accounts(self._dirs["accounts"])],
                         ["Beta Dies"])
        self.assertIn("Deleted 1 account.", self.wb._status.text())
        self.ctl._delete([self.company("Gamma Fab")])
        self.assertIn("nothing to delete", self.wb._status.text())

    def test_find_people_filters_the_people_page_to_those_companies(self):
        self.ctl._find_people([self.company("Acme Tooling"), self.company("Gamma Fab")])
        self.assertEqual(self.wb._filters.spec().companies.include,
                         ["Acme Tooling", "Gamma Fab"])
        self.assertEqual(self.wb._cockpit._stack.currentIndex(), 0)       # the People tab
        self.assertIn("Find new people", self.wb._status.text())

    def test_a_note_on_an_unsaved_company_saves_it_first(self):
        gamma = self.company("Gamma Fab")
        self.ctl._open(gamma)
        self.ctl.page.panel.noteRequested.emit(gamma, "Likes quick quotes")
        self.ctl.on_shown()
        saved = next(a for a in AC.list_accounts(self._dirs["accounts"])
                     if a.name == "Gamma Fab")
        self.assertEqual([n["text"] for n in saved.notes], ["Likes quick quotes"])
        self.assertTrue(self.ctl.page.profile_open())                  # still on it
        self.assertFalse(self.ctl.page.panel._save_btn.isVisible()
                         and not self.ctl.page.panel._save_btn.isHidden())

    def test_tasks_logs_edits_and_flags_land_on_the_account(self):
        acme = self.company("Acme Tooling")
        self.ctl._task(acme, "Send brochure", "2026-11-05")
        self.ctl._task_done(acme, "t1", True)
        self.ctl._log(acme, "call", "Asked for pricing")
        self.ctl._edit(acme, {"phone": "+91 265 000 0000", "industry": "Press tools"})
        self.ctl._flag(acme)
        got = next(a for a in AC.list_accounts(self._dirs["accounts"]) if a.name == "Acme Tooling")
        self.assertEqual((got.tasks[0]["text"], got.tasks[0]["done"]), ("Send brochure", True))
        self.assertEqual((got.phone, got.industry), ("+91 265 000 0000", "Press tools"))
        self.assertEqual([h["kind"] for h in got.history][-3:], ["call", "edited", "flagged"])

    def test_picking_a_colleague_opens_them_on_the_people_tab(self):
        acme = self.company("Acme Tooling")
        person = acme.people[0]
        self.wb._cockpit.open_person(person)
        self.assertEqual(self.wb._cockpit._stack.currentIndex(), 0)
        self.assertEqual(self.wb._cockpit.leads.person_panel.view.lead.name, "Asha Rao")

    def test_the_lookup_asks_first_runs_the_worker_and_saves_what_it_found(self):
        from addons.leads import workers as WK
        wb = self._WB.LeadsWorkbench({"exa_api_key": "k"})
        made = []

        class _FakeWorker:
            def __init__(self, companies, cfg, mode):
                self.companies, self.mode, self.started = companies, mode, False
                self.progress, self.done, self.failed = (_Signal0(), _Signal0(), _Signal0())
                made.append(self)

            def start(self):
                self.started = True

        class _Signal0:
            def __init__(self):
                self.slots = []

            def connect(self, fn):
                self.slots.append(fn)

            def emit(self, *a):
                for fn in self.slots:
                    fn(*a)

        original = WK.LeadsAccountEnrichWorker
        WK.LeadsAccountEnrichWorker = _FakeWorker
        try:
            wb._contacts, wb._runs = [], {}
            wb._reload_accounts()
            wb._rebuild_pool()
            ctl = wb._companies
            ctl.on_shown()
            beta = next(c for c in ctl._pool if c.name == "Beta Dies")
            asked = []
            ctl.confirm_enrich = lambda n: asked.append(n) or True
            ctl._enrich([beta])
            self.assertEqual(asked, [1])
            self.assertTrue(made[0].started)
            made[0].companies[0]["website"] = "beta-dies.example"
            made[0].done.emit(made[0].companies, 1)
        finally:
            WK.LeadsAccountEnrichWorker = original
        beta_saved = next(a for a in AC.list_accounts(self._dirs["accounts"])
                          if a.name == "Beta Dies")
        self.assertEqual(beta_saved.website, "beta-dies.example")
        self.assertEqual(beta_saved.history[-1]["kind"], "enriched")
        self.assertIn("Filled in 1 companies from Exa.", wb._status.text())
        self.assertEqual(wb._jobs, 0)

    def test_the_lookup_needs_a_key_and_has_nothing_to_do_for_a_complete_company(self):
        self.ctl._enrich([self.company("Beta Dies")])
        self.assertIn("Exa API key", self.wb._status.text())
        done = _company("Done Co", "done.example", headcount="10")
        done.revenue, done.location = "1000000", "Pune"
        self.ctl._enrich([done])
        self.assertIn("Nothing to look up", self.wb._status.text())


if __name__ == "__main__":
    unittest.main()


class TheRows(unittest.TestCase):
    """The default view: one calm row per company (result_rows), the mockup's design. The table stays as the other view."""

    def setUp(self):
        self.page = CP.CompaniesPage()
        self.page.resize(1100, 700)
        self.rows = _rows()
        self.page.set_companies(self.rows, {"page": 0, "pages": 1, "start": 1, "end": 3, "total": 3}, {"total": 3, "net_new": 1, "saved": 2})

    def test_one_row_per_company_saying_who_what_where_and_the_stage(self):
        self.assertEqual(self.page._row_list.count(), 3)
        first = self.page._row_list.rows()[0]
        self.assertEqual(first.name.full_text(), "Acme Tooling")
        self.assertIn("acme.example", first.company.full_text())
        self.assertIn("Machine tools", first.subline.full_text())
        self.assertIn("Vadodara", first.subline.full_text())
        self.assertEqual([p.text() for p in first.pills][0], "Cold")

    def test_an_unsaved_company_offers_save_and_a_saved_one_does_not(self):
        rows = self.page._row_list.rows()
        self.assertEqual([b.text() for b in rows[0].buttons], ["Open"])          # Acme is saved
        self.assertEqual([b.text() for b in rows[1].buttons], ["Open", "Save"])   # Beta Dies is not
        got = []
        self.page.saveRequested.connect(got.append)
        rows[1].buttons[1].click()
        self.assertEqual([c.name for c in got[0]], ["Beta Dies"])

    def test_opening_a_row_opens_the_company_and_a_tick_selects_it(self):
        got = []
        self.page.openRequested.connect(got.append)
        self.page._row_list.rows()[2].buttons[0].click()
        self.assertEqual(got[0].name, "Gamma Fab")
        self.page._row_checks[1].setChecked(True)
        self.assertEqual([c.name for c in self.page.selected()], ["Beta Dies"])
        self.assertEqual(self.page._table.item(1, 0).checkState(), Qt.Checked)      # the table's tick follows

    def test_the_toggle_swaps_between_the_rows_and_the_table(self):
        self.page._set_view("table")
        self.assertEqual(self.page._view_stack.currentIndex(), 0)
        self.page._set_view("list")
        self.assertEqual(self.page._view_stack.currentIndex(), 2)
