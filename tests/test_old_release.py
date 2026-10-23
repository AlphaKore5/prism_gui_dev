"""tests/old_release.py trusts a tag by its content, not its name."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import old_release                                          # noqa: E402


class TagIsTrustedByContent(unittest.TestCase):
    def test_the_current_code_is_never_mistaken_for_the_old_release(self):
        # HEAD holds the fallback list and the channel module, by definition.
        reason = old_release.skip_reason("HEAD")
        self.assertIn("holds current code", reason)

    def test_a_missing_tag_says_how_to_get_it(self):
        self.assertIn("git fetch --tags", old_release.skip_reason("v0.0.0-nope"))

    def test_the_real_release_is_accepted_when_it_is_present(self):
        if old_release._git("rev-parse", "-q", "--verify", "v1.6.10^{commit}").returncode:
            self.skipTest("v1.6.10 is not in this clone")
        shown = old_release._git("show", "v1.6.10:updater.py").stdout
        if "UPDATE_FALLBACK_REPOS" in shown:
            self.skipTest("this clone's v1.6.10 is a dev release of current code")
        self.assertEqual(old_release.skip_reason("v1.6.10"), "")

    def test_a_tag_whose_updater_has_the_new_markers_is_refused(self):
        fake = mock.Mock(returncode=0, stdout="UPDATER_LEVEL = 2\n")
        with mock.patch.object(old_release, "_git", return_value=fake):
            self.assertIn("UPDATER_LEVEL", old_release.skip_reason("v1.6.10"))


class TheHarnessSkipsWhereItCannotRun(unittest.TestCase):
    def test_windows_is_skipped_with_a_reason(self):
        import e2e_update_harness as H
        with mock.patch.object(H.sys, "platform", "win32"):
            self.assertIn("Linux and macOS only", H.skip_reason())


if __name__ == "__main__":
    unittest.main()
