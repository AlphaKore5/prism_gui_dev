"""Find people: Apollo through the owner's Monid wallet, with Exa as the backup (24-Nov-2026).

The owner's plan: Apollo's people search is free, so Leads asks Apollo FIRST — through the Monid key, with no
Apollo account — and Exa answers when Apollo cannot. SourceWorker.run() is called inline (no thread, no
network); every engine call is a stand-in. What is held:

  · with a Monid key and no Apollo key, Apollo is asked through `monid_transport` — and Exa is not;
  · with an Apollo key the old path is untouched (no transport);
  · Apollo coming back empty, or Monid refusing, falls back to Exa when there is an Exa key, and says so;
  · with no Exa key a Monid refusal is shown in Monid's own words, not swallowed;
  · with neither key the failure names both.

No network, no thread, no key, no real ~/.prism."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from prospector import apollo                                       # noqa: E402
from prospector.models import Lead                                  # noqa: E402


def person(name="Ana Ruiz", company="Acme"):
    lead = Lead(name=name, company=company, title="Head of Operations", email="")
    lead.extra = {"apollo_id": "a1"}
    return lead


class SourceWorkerAsksApolloOnMonid(unittest.TestCase):
    def setUp(self):
        env = mock.patch.dict(os.environ, {"MONID_API_KEY": "", "APOLLO_API_KEY": ""})
        env.start()
        self.addCleanup(env.stop)
        self.apollo_calls: list = []
        self.exa_calls: list = []
        self.apollo_answer = [person()]                  # what Apollo returns, or an exception to raise
        self.own_key_refused = None                      # an exception raised ONLY when a key of their own is used

    def worker(self, cfg):
        from addons.leads.workers import SourceWorker
        from prospector.filters import SearchSpec
        spec = SearchSpec.from_dict({"seniority": {"include": ["head"]}, "functions": {"include": ["operations"]}})
        w = SourceWorker([], [], "Line retrofits", cfg, source="apollo", target=25, verify_limit=0,
                         leads_only=True, spec=spec.to_dict())
        got = {"done": [], "failed": [], "progress": [], "blocked": []}
        w.progress.connect(got["progress"].append)
        w.done.connect(lambda res, drafts: got["done"].append((res, drafts)))
        w.failed.connect(got["failed"].append)
        w.blocked.connect(got["blocked"].append)
        return w, got

    def run_worker(self, cfg, exa_key=""):
        w, got = self.worker(cfg)

        def fake_apollo(spec, key, **kw):
            self.apollo_calls.append({"key": key, "transport": kw.get("transport")})
            if key and self.own_key_refused is not None:
                raise self.own_key_refused
            if isinstance(self.apollo_answer, Exception):
                raise self.apollo_answer
            return list(self.apollo_answer)

        def fake_exa(industries, roles, key, **kw):
            self.exa_calls.append(key)
            return [person("Bo Lund", "Globex")]

        patches = [mock.patch.object(apollo, "search_people", side_effect=fake_apollo),
                   mock.patch("prospector.source.source", side_effect=fake_exa),
                   mock.patch("prospector.signals.exa_key", return_value=exa_key)]
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

    # ── Monid is the way in ─────────────────────────────────────────────────
    def test_a_monid_key_alone_asks_apollo_through_monid_and_not_exa(self):
        got = self.run_worker({"monid_api_key": "mk"}, exa_key="ek")
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.names(got), ["Ana Ruiz"])
        self.assertEqual(len(self.apollo_calls), 1)
        self.assertEqual(self.apollo_calls[0]["key"], "")                    # no Apollo key was needed
        self.assertTrue(callable(self.apollo_calls[0]["transport"]))
        self.assertEqual(self.exa_calls, [])                                 # Apollo answered: Exa is not paid for

    def test_the_monid_key_can_come_from_the_environment(self):
        with mock.patch.dict(os.environ, {"MONID_API_KEY": "from-env"}):
            got = self.run_worker({}, exa_key="")
        self.assertEqual(got["failed"], [])
        self.assertTrue(callable(self.apollo_calls[0]["transport"]))

    def test_an_apollo_key_keeps_the_old_path_with_no_transport(self):
        got = self.run_worker({"apollo_api_key": "ap-test", "monid_api_key": "mk"})
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.apollo_calls[0]["key"], "ap-test")
        self.assertIsNone(self.apollo_calls[0]["transport"])

    # ── the backup ──────────────────────────────────────────────────────────
    def test_apollo_coming_back_empty_falls_back_to_exa_and_says_so(self):
        self.apollo_answer = []
        got = self.run_worker({"monid_api_key": "mk"}, exa_key="ek")
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.names(got), ["Bo Lund"])
        self.assertEqual(self.exa_calls, ["ek"])
        self.assertTrue(any("Exa instead" in line for line in got["progress"]))

    def test_monid_refusing_falls_back_to_exa_and_says_it_could_not_search(self):
        self.apollo_answer = apollo.ApolloError("Your Monid wallet is empty. Top it up at monid.ai, then try again.")
        got = self.run_worker({"monid_api_key": "mk"}, exa_key="ek")
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.names(got), ["Bo Lund"])
        self.assertTrue(any("could not be searched" in line for line in got["progress"]))

    def test_monid_refusing_with_no_exa_key_says_why_in_monids_words(self):
        self.apollo_answer = apollo.ApolloError("Your Monid wallet is empty. Top it up at monid.ai, then try again.")
        got = self.run_worker({"monid_api_key": "mk"}, exa_key="")
        self.assertEqual(got["done"], [])
        self.assertEqual(got["failed"], ["Your Monid wallet is empty. Top it up at monid.ai, then try again."])
        self.assertEqual(self.exa_calls, [])

    def test_an_apollo_key_that_fails_is_not_quietly_replaced_by_exa(self):
        # The owner's own Apollo key refusing is the owner's to fix (the plan/scope wall, blocked): only the
        # Monid route has Exa behind it.
        self.apollo_answer = apollo.ApolloError("Apollo refused that key (401).")
        got = self.run_worker({"apollo_api_key": "ap-test"}, exa_key="ek")
        self.assertEqual(got["failed"], ["Apollo refused that key (401)."])
        self.assertEqual(self.exa_calls, [])

    # ── an Apollo key of their own that Apollo refuses, with a Monid wallet attached ──
    def test_a_refused_apollo_key_is_replaced_by_the_monid_wallet_once_and_says_so(self):
        # 24-Nov-2026: the owner's saved free-plan key ended every run ("Apollo rejected the API key") while his
        # Monid key sat unused.
        self.own_key_refused = apollo.ApolloError(apollo.BAD_KEY)
        got = self.run_worker({"apollo_api_key": "ap-free", "monid_api_key": "mk"}, exa_key="ek")
        self.assertEqual(got["failed"], [])
        self.assertEqual(got["blocked"], [])
        self.assertEqual(self.names(got), ["Ana Ruiz"])
        self.assertEqual([c["key"] for c in self.apollo_calls], ["ap-free", ""])
        self.assertIsNone(self.apollo_calls[0]["transport"])
        self.assertTrue(callable(self.apollo_calls[1]["transport"]))
        self.assertTrue(any("through your Monid wallet" in line for line in got["progress"]))
        self.assertEqual(self.exa_calls, [])

    def test_a_free_plan_refusal_is_not_a_wall_while_a_monid_wallet_can_ask_instead(self):
        self.own_key_refused = apollo.ApolloError(apollo.SCOPED_KEY.format(path="/api/v1/mixed_people/api_search"))
        got = self.run_worker({"apollo_api_key": "ap-free", "monid_api_key": "mk"})
        self.assertEqual(got["blocked"], [])
        self.assertEqual(self.names(got), ["Ana Ruiz"])

    def test_without_a_monid_wallet_a_refused_apollo_key_is_still_the_owners_to_fix(self):
        self.own_key_refused = apollo.ApolloError(apollo.BAD_KEY)
        got = self.run_worker({"apollo_api_key": "ap-free"}, exa_key="ek")
        self.assertEqual(got["failed"], [apollo.BAD_KEY])
        self.assertEqual(len(self.apollo_calls), 1)

    def test_when_monid_cannot_ask_either_the_run_falls_to_exa(self):
        self.own_key_refused = apollo.ApolloError(apollo.BAD_KEY)
        self.apollo_answer = apollo.ApolloError("Your Monid wallet is empty. Top it up at monid.ai, then try again.")
        got = self.run_worker({"apollo_api_key": "ap-free", "monid_api_key": "mk"}, exa_key="ek")
        self.assertEqual(got["failed"], [])
        self.assertEqual(self.names(got), ["Bo Lund"])

    # ── no way in at all ────────────────────────────────────────────────────
    def test_with_neither_key_the_failure_names_both(self):
        got = self.run_worker({}, exa_key="ek")
        self.assertEqual(self.apollo_calls, [])
        self.assertIn("Apollo API key or a Monid key", got["failed"][0])
        self.assertEqual(self.exa_calls, [])


if __name__ == "__main__":
    unittest.main()
