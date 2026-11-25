"""Find new people with Apollo on the credit pool (24-Nov-2026): the worker asks Apollo through the licence server,
Exa answers when Apollo cannot, and the screen offers Apollo only where the server has it and says what a reveal costs.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox          # noqa: E402

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector import apollo                                     # noqa: E402
from prospector import gateway as G                               # noqa: E402
from prospector.models import Lead                                # noqa: E402

from test_leads_cockpit import _Workbench                         # noqa: E402
from test_leads_credit_pool import FakeServer                     # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def person(name="Ana Ruiz", company="Acme"):
    lead = Lead(name=name, company=company, title="Head of Operations", email="")
    lead.extra = {"apollo_id": "a1"}
    return lead


@pytest.mark.pooled
class TheWorkerOnThePool(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"MONID_API_KEY": "", "APOLLO_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.apollo_calls: list = []
        self.exa_calls: list = []
        self.apollo_answer = [person()]
        self.ready = True

    def run_worker(self, exa_key=""):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]}, "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", {}, source="apollo", target=25, verify_limit=0,
                         leads_only=True, spec=spec.to_dict())
        got = {"done": [], "failed": [], "progress": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)

        def fake_apollo(spec, key, **kw):
            self.apollo_calls.append({"key": key, "transport": kw.get("transport")})
            if isinstance(self.apollo_answer, Exception):
                raise self.apollo_answer
            return list(self.apollo_answer)

        def fake_exa(industries, roles, key, **kw):
            self.exa_calls.append(key)
            return [person("Bo Lund", "Globex")]

        patches = [mock.patch.object(apollo, "search_people", side_effect=fake_apollo),
                   mock.patch("prospector.source.source", side_effect=fake_exa),
                   mock.patch("prospector.signals.exa_key", return_value=exa_key),
                   mock.patch.object(G, "ready", lambda op: self.ready if op == "apollo" else True)]
        for p in patches:
            p.start()
        try:
            w.run()
        finally:
            for p in patches:
                p.stop()
        return got

    def names(self, got):
        return [l.name for l in got["done"][0][0].all_leads]

    def test_the_pool_asks_apollo_through_the_server_and_not_exa(self):
        got = self.run_worker(exa_key="pool")
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.names(got), ["Ana Ruiz"])
        self.assertEqual(self.apollo_calls[0]["key"], "")                      # a customer holds no Apollo key
        self.assertTrue(callable(self.apollo_calls[0]["transport"]))
        self.assertEqual(self.exa_calls, [])

    # 25-Nov-2026: the PR #18 review found the Exa backup spent credits the question before the run never named.
    # The owner kept the backup ("Keep backup, show cost"): the question now names its cost
    # (TheQuestionNamesTheExaBackup), so the run falls back to Exa as before.
    def test_apollo_coming_back_empty_falls_back_to_exa_and_says_so(self):
        self.apollo_answer = []
        got = self.run_worker(exa_key="pool")
        self.assertEqual(self.names(got), ["Bo Lund"])
        self.assertTrue(any("Exa instead" in line for line in got["progress"]))

    def test_the_server_refusing_falls_back_to_exa(self):
        self.apollo_answer = apollo.ApolloError("You've run out of credits.")
        got = self.run_worker(exa_key="pool")
        self.assertEqual(self.names(got), ["Bo Lund"])
        self.assertTrue(any("could not be searched" in line for line in got["progress"]))

    def test_a_server_that_has_not_got_apollo_is_never_asked_and_exa_is_not_searched_either(self):
        self.ready = False
        got = self.run_worker(exa_key="pool")
        self.assertEqual((self.apollo_calls, self.exa_calls), ([], []))
        self.assertIn("isn't switched on for your account yet", got["failed"][0])

    def test_a_server_without_apollo_and_without_exa_says_so(self):
        self.ready = False
        got = self.run_worker(exa_key="")
        self.assertEqual(got["done"], [])
        self.assertIn("isn't switched on for your account yet", got["failed"][0])


@pytest.mark.pooled
class TheScreenOnThePool(_Workbench):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(self._WB.LeadsWorkbench, "_refresh_credits", lambda _self: None)
        patch.start()
        self.addCleanup(patch.stop)

    def bench(self, ready=True, balance=100):
        wb = self._WB.LeadsWorkbench({})
        G.set_transport(FakeServer(balance=balance))
        self.addCleanup(G.set_transport, None)
        self.addCleanup(G.forget)
        auth = mock.patch.object(G, "_auth_body", lambda **e: {"license_id": "L", "device_fp": "D", **e})
        auth.start()
        self.addCleanup(auth.stop)
        wb._on_credits(G.status())
        gate = mock.patch.object(G, "ready", lambda op: ready if op == "apollo" else True)
        gate.start()
        self.addCleanup(gate.stop)
        return wb

    def test_apollo_can_be_picked_where_the_server_has_it(self):
        wb = self.bench(ready=True)
        wb._set_source("apollo")
        self.assertEqual(wb._source, "apollo")
        self.assertTrue(wb._src_apollo.isChecked())

    def test_apollo_falls_back_to_exa_where_the_server_does_not_have_it(self):
        wb = self.bench(ready=False)
        wb._set_source("apollo")
        self.assertEqual(wb._source, "exa")

    # The Apollo way (the owner, 25-Nov-2026): an Apollo search is free and SHOWS people; a full name is paid for
    # only when the owner reveals that person. These replace the tests of the old auto-reveal.
    def test_the_target_says_how_many_a_search_shows_and_names_no_provider_credit(self):
        wb = self.bench()
        wb._set_source("apollo")
        self.assertEqual(wb._target_row.name.text(), "Show up to")
        self.assertNotIn("Apollo credit", wb._target.toolTip())

    def test_the_line_under_find_says_the_search_is_free_and_prices_a_reveal_per_person(self):
        wb = self.bench()
        wb._set_source("apollo")
        wb._target.setValue(40)
        text = wb._pool_search_meta(wb._filters.spec(), [])
        self.assertIn("free", text)
        self.assertIn("2 credits for each full name you reveal", text)
        self.assertNotIn("80 credits", text)                       # nobody is revealed by the search itself

    def test_the_question_before_a_search_says_it_is_free_and_that_reveals_are_picked(self):
        wb = self.bench()
        wb._set_source("apollo")
        wb._target.setValue(40)
        said = []
        wb._confirm_pool = lambda title, lines: (said.append((title, lines)), False)[1]
        self.assertFalse(self._saved_attrs["_confirm_search"](wb, wb._filters.spec(), [], ""))
        [(title, lines)] = said
        self.assertEqual(title, "Find new people")
        self.assertIn("free", lines[0])
        self.assertIn("40 people", lines[0])
        self.assertIn("Nothing is charged for the search", lines[0])
        self.assertIn("people you pick", lines[1])
        self.assertIn("2 credits each", lines[1])

    def test_the_question_names_what_the_exa_backup_can_cost(self):
        # The owner, 25-Nov-2026: "Keep backup, show cost".
        wb = self.bench()
        wb._set_source("apollo")
        wb._searches = lambda spec, companies=(): (4, 2)       # the Exa searches these filters would plan
        said = []
        wb._confirm_pool = lambda title, lines: (said.append(lines), False)[1]
        self._saved_attrs["_confirm_search"](wb, wb._filters.spec(), [], "")
        backup = [line for line in said[0] if "Exa searches instead" in line]
        self.assertEqual(len(backup), 1)
        self.assertIn("up to 18 credits", backup[0])               # 6 searches x the 3-credit default
        self.assertIn("Exa searches up to", wb._pool_search_meta(wb._filters.spec(), []))

    def test_no_exa_on_the_server_means_no_backup_is_promised(self):
        wb = self.bench()
        wb._set_source("apollo")
        with mock.patch.object(G, "ready", lambda op: op != "people"):
            self.assertEqual(wb._exa_backup_cost(wb._filters.spec(), []), 0)
            self.assertNotIn("Exa", wb._pool_search_meta(wb._filters.spec(), []))

    def test_more_than_the_balance_is_said(self):
        wb = self.bench(balance=10)
        wb._set_source("apollo")
        # A search is free now; the balance is weighed where the money is: the question before a Reveal.
        said = []
        wb._confirm_pool = lambda title, lines: (said.append((title, lines)), False)[1]
        self.assertFalse(wb._confirm_reveal(40))
        [(title, lines)] = said
        self.assertEqual(title, "Reveal")
        self.assertIn("up to 80 credits", lines[0])               # 40 people x the 2-credit default
        self.assertTrue(any("more than you have" in line for line in lines))

    def test_an_apollo_search_is_blocked_only_by_apollo_being_off_not_by_exa_being_off(self):
        wb = self.bench()
        wb._set_source("apollo")
        with mock.patch.object(G, "ready", lambda op: op == "apollo"):
            self.assertEqual(wb._missing_key(), "")                 # "people" (Exa) is off, Apollo is on


    # Search settings says what each setting costs on THIS route, in the unit the customer pays in (24-Nov-2026).

    def test_the_source_line_says_search_is_free_a_reveal_costs_credits_and_exa_is_behind_it(self):
        wb = self.bench()
        wb._set_source("apollo")
        said = wb._settings_hints()
        self.assertIn("free", said["source"])
        self.assertIn("2 credits", said["source"])
        self.assertIn("Exa takes over", said["source"])

    def test_the_reveal_ceiling_is_priced_in_credits(self):
        wb = self.bench()
        wb._set_source("apollo")
        wb._target.setValue(300)
        self.assertEqual(wb._settings_hints()["target"], "")        # showing 300 people is free
        self.assertIn("2 credits", wb._settings_hints()["source"])

    def test_exa_only_names_its_own_price(self):
        wb = self.bench()
        wb._set_source("exa")
        said = wb._settings_hints()
        self.assertIn("A search that finds nobody is not charged", said["source"])
        self.assertEqual(said["target"], "")

    def test_exa_by_default_says_why_apollo_is_not_the_one_in_use(self):
        wb = self.bench(ready=False)
        wb._set_source("apollo")                                    # falls back to Exa: the server has no Apollo
        said = wb._settings_hints()
        self.assertIn("Apollo isn't switched on for your account yet", said["source"])
        self.assertIn("Each Exa search costs 3 credits", said["source"])

    def test_exa_picked_on_purpose_does_not_claim_apollo_is_off(self):
        wb = self.bench(ready=True)
        wb._set_source("exa")
        self.assertNotIn("switched on", wb._settings_hints()["source"])

    def test_the_email_and_mobile_lines_use_the_rate_card_not_a_rupee_guess(self):
        said = self.bench()._settings_hints()
        self.assertIn("2 credits for each address found", said["verify"])
        self.assertIn("4 credits for each number found", said["mobiles"])
        self.assertNotIn("\u20b9", " ".join(said.values()))

    def test_the_hints_are_written_on_the_labels_and_follow_the_ceiling(self):
        wb = self.bench()
        wb._set_source("apollo")
        wb._target.setValue(50)
        self.assertEqual(wb._target_meta.text(), "")                # a search's size costs nothing
        self.assertIn("people you pick", wb._source_meta.text())


class TheSettingsWindowOnYourOwnKeys(_Workbench):
    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"MONID_API_KEY": "", "APOLLO_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def hints(self, cfg, source=None):
        wb = self._WB.LeadsWorkbench(cfg)
        if source:
            wb._set_source(source)
        return wb, wb._settings_hints()

    def test_a_monid_wallet_prices_a_reveal_and_the_phone_lookup_in_rupees(self):
        wb, said = self.hints({"monid_api_key": "mk", "exa_api_key": "ek"}, "apollo")
        self.assertIn("Monid wallet", said["source"])
        self.assertIn("Exa takes over", said["source"])
        self.assertIn("\u20b9", said["source"])
        self.assertIn("Monid wallet", said["mobiles"])

    def test_without_an_exa_key_it_does_not_promise_a_backup(self):
        _wb, said = self.hints({"monid_api_key": "mk"}, "apollo")
        self.assertNotIn("Exa", said["source"])

    def test_an_own_apollo_account_is_counted_in_apollo_credits(self):
        _wb, said = self.hints({"apollo_api_key": "ap"}, "apollo")
        self.assertIn("Apollo credit", said["source"])
        self.assertEqual(said["mobiles"], "")                         # no Monid wallet, no mobile lookup to price

    def test_a_monid_wallet_without_a_hunter_key_renames_verify_because_it_finds(self):
        wb, said = self.hints({"monid_api_key": "mk"})
        wb._refresh_settings_hints()
        self.assertEqual(wb._verify_row.name.text(), "Find e-mails")
        self.assertIn("Hunter", said["verify"])

    def test_a_hunter_key_keeps_the_verify_name_and_adds_no_line(self):
        wb, said = self.hints({"monid_api_key": "mk", "hunter_api_key": "hk"})
        wb._refresh_settings_hints()
        self.assertEqual(said["verify"], "")
        self.assertNotEqual(wb._verify_row.name.text(), "Find e-mails")


class TheStartingSourceOnYourOwnKeys(_Workbench):
    """Apollo first, Exa behind it (the owner's plan, 24-Nov-2026): the screen starts on Apollo where its search is
    free and cannot be refused — a Monid wallet and no Apollo account — and on Exa everywhere else."""

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"MONID_API_KEY": "", "APOLLO_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)

    def starts_on(self, cfg):
        return self._WB.LeadsWorkbench(cfg)._source

    def test_a_monid_key_alone_starts_on_apollo(self):
        self.assertEqual(self.starts_on({"monid_api_key": "mk"}), "apollo")

    def test_a_monid_key_from_the_environment_starts_on_apollo_too(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": "from-env"}):
            self.assertEqual(self.starts_on({}), "apollo")

    def test_an_apollo_key_of_their_own_keeps_exa_first_because_a_free_plan_is_refused(self):
        self.assertEqual(self.starts_on({"apollo_api_key": "ap", "monid_api_key": "mk"}), "exa")
        self.assertEqual(self.starts_on({"apollo_api_key": "ap"}), "exa")

    def test_no_key_at_all_starts_on_exa(self):
        self.assertEqual(self.starts_on({}), "exa")
        self.assertEqual(self.starts_on({"exa_api_key": "ek"}), "exa")

    def test_an_apollo_that_already_refused_this_owner_is_not_the_start(self):
        self.assertEqual(self.starts_on({"monid_api_key": "mk", "apollo_api_blocked": True}), "exa")

    def test_they_can_still_pick_exa(self):
        wb = self._WB.LeadsWorkbench({"monid_api_key": "mk", "exa_api_key": "ek"})
        wb._set_source("exa")
        self.assertEqual(wb._source, "exa")


@pytest.mark.pooled
class TheStartingSourceOnTheCreditPool(_Workbench):
    def start(self, ready):
        gate = mock.patch.object(G, "ready", lambda op: ready if op == "apollo" else True)
        gate.start()
        self.addCleanup(gate.stop)
        return self._WB.LeadsWorkbench({})._source

    def test_it_starts_on_apollo_where_the_server_has_it(self):
        self.assertEqual(self.start(True), "apollo")

    def test_it_starts_on_exa_where_the_server_does_not(self):
        self.assertEqual(self.start(False), "exa")


if __name__ == "__main__":
    unittest.main()
