"""devtools/promote_check.py: the gate for "move to prod". It must refuse the things
that would leave a 1.6.10 customer without the update (a version that is not newer,
a reused production version, a commit that was never a dev release, an engine commit
the build cannot fetch, a release job that does not wait for the tests) and must say
plainly what is left for a human."""
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "devtools"))
sys.path.insert(0, ROOT)

import promote_check as P  # noqa: E402


class TheVersion(unittest.TestCase):
    def test_a_version_not_newer_than_the_oldest_customer_is_refused(self):
        for v in ("1.6.10", "1.6.9", "1.5.0", "nonsense"):
            self.assertEqual(P.check_version(v, ["v1.6.10"]).status, P.FAIL, v)

    def test_a_production_version_is_never_reused(self):
        self.assertEqual(P.check_version("1.6.12", ["v1.6.10", "v1.6.12"]).status, P.FAIL)

    def test_it_must_beat_every_production_tag(self):
        self.assertEqual(P.check_version("1.6.11", ["v1.6.10", "v1.6.12"]).status, P.FAIL)

    def test_a_newer_version_passes(self):
        self.assertEqual(P.check_version("1.6.13", ["v1.6.9", "v1.6.10"]).status, P.PASS)

    def test_the_numbers_compare_as_numbers_not_text(self):
        self.assertEqual(P.check_version("1.6.100", ["v1.6.10"]).status, P.PASS)
        self.assertEqual(P.check_version("1.6.9", ["v1.6.10"]).status, P.FAIL)


class TheReleaseGate(unittest.TestCase):
    GOOD = "jobs:\n  release:\n    name: Publish release\n    needs: [build, tests]\n    runs-on: x\n"

    def test_the_real_workflow_passes(self):
        self.assertEqual(P.check_workflow_gate().status, P.PASS)

    def test_a_release_that_does_not_wait_for_the_tests_fails(self):
        self.assertEqual(P.check_workflow_gate(self.GOOD.replace("[build, tests]", "build")).status, P.FAIL)

    def test_a_release_that_waits_for_both_passes(self):
        self.assertEqual(P.check_workflow_gate(self.GOOD).status, P.PASS)


class TheOpenIssues(unittest.TestCase):
    TEXT = ("## Issue log\n"
            "### ISS-020 — Something fixed (2026-10-27) — FIXED\n"
            "### ISS-019 — Needs Windows (2026-10-27) — OPEN, UNVERIFIED\n"
            "### ISS-018 — Fixed but unproven (2026-10-27) — FIXED in code, UNVERIFIED on Windows\n"
            "body text mentioning OPEN is ignored\n")

    def test_only_open_or_unverified_headings_are_listed(self):
        self.assertEqual([i for i, _ in P.open_issues(self.TEXT)], ["ISS-019", "ISS-018"])

    def test_the_real_file_parses(self):
        self.assertIsInstance(P.open_issues(), list)


class TheRepoChecks(unittest.TestCase):
    def test_this_source_ships_as_prod_with_the_right_fallback(self):
        self.assertEqual(P.check_channel_defaults().status, P.PASS)

    def test_a_commit_that_was_never_a_dev_release_blocks(self):
        with mock.patch.object(P, "_run") as run:
            run.return_value = mock.Mock(stdout="", returncode=0)
            self.assertEqual(P.check_dev_tag("1.6.99").status, P.FAIL)

    def later(self, changed, ancestor=True):
        def fake(*cmd, **kw):
            if cmd[:2] == ("git", "rev-parse"):
                return mock.Mock(stdout="aaaa1111\n", returncode=0)
            if cmd[:2] == ("git", "ls-remote"):
                return mock.Mock(stdout="bbbb2222\trefs/tags/v1.6.99\n", returncode=0)
            if cmd[:2] == ("git", "merge-base"):
                return mock.Mock(stdout="", returncode=0 if ancestor else 1)
            return mock.Mock(stdout="\n".join(changed), returncode=0)         # git diff --name-only
        return mock.patch.object(P, "_run", side_effect=fake)

    def test_a_dev_tag_on_an_unrelated_commit_blocks(self):
        with self.later(["main_window.py"], ancestor=False):
            self.assertEqual(P.check_dev_tag("1.6.99").status, P.FAIL)

    def test_later_commits_that_changed_shipped_code_block(self):
        with self.later(["docs/x.md", "main_window.py"]):
            result = P.check_dev_tag("1.6.99")
        self.assertEqual(result.status, P.FAIL)
        self.assertIn("main_window.py", result.detail)

    def test_later_commits_that_only_touched_docs_tests_and_tools_pass(self):
        with self.later(["docs/x.md", "tests/test_a.py", "devtools/promote_check.py", "RELEASE_ISSUES.md"]):
            result = P.check_dev_tag("1.6.99")
        self.assertEqual(result.status, P.PASS)
        self.assertIn("nothing that ships", result.detail)

    def test_the_engine_pointer_counts_as_shipped(self):
        self.assertEqual(P.shipped_changes(["prism_terminal", "docs/a.md"]), ["prism_terminal"])

    def test_how_production_is_built_or_published_counts_as_shipped(self):
        # Found in review 2026-10-28: the first version treated the CI workflow and the publishing
        # tools as harmless, so a change to how production is built could follow the dev release.
        for path in (".github/workflows/build.yml", "devtools/release_all.py", "devtools/sign_manifest.py",
                     "packaging/build.py"):
            self.assertEqual(P.shipped_changes([path]), [path], path)
        self.assertEqual(P.shipped_changes(["devtools/promote_check.py", "tests/test_x.py"]), [])

    def test_a_dev_tag_on_this_commit_passes(self):
        def fake(*cmd, **kw):
            if cmd[:2] == ("git", "rev-parse"):
                return mock.Mock(stdout="aaaa1111\n", returncode=0)
            return mock.Mock(stdout="aaaa1111\trefs/tags/v1.6.99\n", returncode=0)
        with mock.patch.object(P, "_run", side_effect=fake):
            self.assertEqual(P.check_dev_tag("1.6.99").status, P.PASS)

    def test_an_engine_commit_the_build_cannot_fetch_blocks(self):
        def fake(*cmd, **kw):
            if cmd[:2] == ("git", "ls-tree"):
                return mock.Mock(stdout="160000 commit " + "c" * 40 + "\tprism_terminal\n", returncode=0)
            return mock.Mock(stdout="", returncode=1)           # gh api: not found
        with mock.patch.object(P, "_run", side_effect=fake):
            self.assertEqual(P.check_engine_commit().status, P.FAIL)


class TheEngineFolder(unittest.TestCase):
    """RELEASE_ISSUES.md ISS-017: an engine checkout that differs from the recorded commit once got
    committed with `git add -A` and rolled another person's engine update back."""

    def status(self, text):
        return mock.patch.object(P, "_run", return_value=mock.Mock(stdout=text, returncode=0))

    def test_a_modified_engine_folder_blocks_with_the_fix_in_the_message(self):
        with self.status(" M prism_terminal\n"):
            result = P.check_tree_clean()
        self.assertEqual(result.status, P.FAIL)
        self.assertIn("git submodule update", result.detail)
        self.assertIn("git add -A", result.detail)

    def test_ordinary_uncommitted_files_block(self):
        with self.status(" M main_window.py\n"):
            self.assertEqual(P.check_tree_clean().status, P.FAIL)

    def test_a_clean_tree_passes(self):
        with self.status(""):
            self.assertEqual(P.check_tree_clean().status, P.PASS)


class TheReport(unittest.TestCase):
    def test_the_plan_names_the_version_and_who_must_act(self):
        text = P.plan_text("1.6.99")
        for expected in ("v1.6.99", "needs your explicit OK", "offline, human", "check_as_old_client.py --expect-version 1.6.99",
                         "Prism 1.6.99 is available", "rolls back to 1.6.10"):
            self.assertIn(expected, text)

    def test_nothing_in_the_plan_is_run_by_the_check(self):
        # The gate reads and tests; it never pushes, tags, signs, publishes or sets a version.
        # Checked on the commands it RUNS (every _run(...) call), not on mentions in lists or text.
        import re
        source = open(os.path.join(ROOT, "devtools", "promote_check.py"), encoding="utf-8").read()
        calls = re.findall(r"_run\(([^)]*)\)", source)
        self.assertTrue(calls)
        for call in calls:
            for forbidden in ('"push"', '"tag"', "release_all", "sign_manifest", '"release"', "UPDATE_SIGNING_KEY_HEX"):
                self.assertNotIn(forbidden, call, f"the gate must not run: {call}")
        self.assertNotIn("UPDATE_SIGNING_KEY_HEX", source)

    def test_exit_code_is_failure_when_anything_failed(self):
        failing = [P.Result(P.FAIL, "version", "x")]
        with mock.patch.object(P, "prod_tags", return_value=[]), \
             mock.patch.object(P, "check_version", return_value=failing[0]), \
             mock.patch.object(P, "check_tree_clean", return_value=P.Result(P.PASS, "a")), \
             mock.patch.object(P, "check_dev_tag", return_value=P.Result(P.PASS, "b")), \
             mock.patch.object(P, "check_engine_commit", return_value=P.Result(P.PASS, "c")), \
             mock.patch.object(P, "check_channel_defaults", return_value=P.Result(P.PASS, "d")), \
             mock.patch.object(P, "check_workflow_gate", return_value=P.Result(P.PASS, "e")), \
             mock.patch.object(P, "check_licence_server", return_value=P.Result(P.PASS, "f")), \
             mock.patch.object(P, "check_open_issues", return_value=P.Result(P.PASS, "g")), \
             mock.patch("builtins.print"):
            self.assertEqual(P.main(["--skip-tests"]), 1)


if __name__ == "__main__":
    unittest.main()
