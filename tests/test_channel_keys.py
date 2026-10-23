"""Which update keys a build trusts, per channel -- and that the repo itself
can never ship as a dev build."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import channel                                           # noqa: E402
import paths                                             # noqa: E402
from licensing import keys                               # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class UpdateKeysPerChannel(unittest.TestCase):

    def keys_for(self, *, frozen, dev):
        with mock.patch.object(paths, "is_frozen", return_value=frozen), \
             mock.patch.object(channel, "CHANNEL", "dev" if dev else "prod"):
            return keys.update_public_keys()

    def test_frozen_prod_trusts_only_the_production_key(self):
        got = self.keys_for(frozen=True, dev=False)
        self.assertEqual(got, keys.UPDATE_PRODUCTION)
        for kid in keys.UPDATE_DEVELOPMENT:
            self.assertNotIn(kid, got)

    def test_frozen_dev_trusts_only_the_development_key(self):
        got = self.keys_for(frozen=True, dev=True)
        self.assertEqual(got, keys.UPDATE_DEVELOPMENT)
        for kid in keys.UPDATE_PRODUCTION:
            self.assertNotIn(kid, got)

    def test_source_run_trusts_both_as_before(self):
        got = self.keys_for(frozen=False, dev=False)
        self.assertEqual(got, {**keys.UPDATE_PRODUCTION, **keys.UPDATE_DEVELOPMENT})

    def test_licence_keys_are_unaffected_by_channel(self):
        with mock.patch.object(paths, "is_frozen", return_value=True), \
             mock.patch.object(channel, "CHANNEL", "dev"):
            self.assertEqual(keys.public_keys(), keys.PRODUCTION)


class TheRepositoryShipsAsProd(unittest.TestCase):
    def test_source_literal_is_prod(self):
        with open(os.path.join(ROOT, "channel.py"), encoding="utf-8") as f:
            self.assertIn('CHANNEL = "prod"', f.read(),
                          "channel.py must stay prod in the repository; only "
                          "packaging/build.py bakes dev, and restores it")


class BuildBakesDevChannel(unittest.TestCase):
    def setUp(self):
        # These tests must give the same answer in any repository's CI. CI sets
        # GITHUB_REPOSITORY (to the dev repo's name, in the dev repo), and the
        # channel guard reads it -- so isolate it. Found by the first dev CI run.
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("GITHUB_REPOSITORY", None)
        os.environ.pop("PRISM_CHANNEL", None)
        os.environ.pop("PRISM_UPDATE_REPO", None)
        sys.path.insert(0, os.path.join(ROOT, "packaging"))
        import build
        self.build = build
        with open(os.path.join(ROOT, "channel.py"), encoding="utf-8") as f:
            self.channel_src = f.read()
        with open(os.path.join(ROOT, "updater.py"), encoding="utf-8") as f:
            self.updater_src = f.read()

    def test_patch_sets_dev_and_dev_repo(self):
        c, u = self.build.patch_channel(self.channel_src, self.updater_src,
                                        "someone/prism_dev")
        self.assertIn('CHANNEL = "dev"', c)
        self.assertIn('UPDATE_REPO = "someone/prism_dev"', u)
        self.assertNotIn('UPDATE_REPO = "AlphaKore5/prism_gui"', u)

    def test_patch_leaves_inputs_untouched(self):
        self.build.patch_channel(self.channel_src, self.updater_src, "a/b")
        self.assertIn('CHANNEL = "prod"', self.channel_src)

    def test_missing_marker_refuses_to_build(self):
        with self.assertRaises(SystemExit):
            self.build.patch_channel("nothing here", self.updater_src, "a/b")
        with self.assertRaises(SystemExit):
            self.build.patch_channel(self.channel_src, "nothing here", "a/b")

    def test_bad_repo_name_refuses(self):
        for bad in ("noslash", "a/b/c", 'a/"b', "a /b"):
            with self.subTest(repo=bad), self.assertRaises(SystemExit):
                self.build.patch_channel(self.channel_src, self.updater_src, bad)

    def test_a_dev_build_is_refused_inside_a_production_repository(self):
        with mock.patch.dict(os.environ, {"PRISM_CHANNEL": "dev"}):
            for repo in ("HitarthTrivedi/prism_gui", "AlphaKore5/prism_gui"):
                with self.subTest(repo=repo), self.assertRaises(SystemExit):
                    self.build.requested_channel(repo)
            self.assertEqual(self.build.requested_channel("AlphaKore5/prism_gui_dev"), "dev")
            self.assertEqual(self.build.requested_channel(""), "dev")   # a local build

    def test_a_prod_build_is_refused_inside_the_dev_repository(self):
        for value in ("prod", "", "  "):
            with mock.patch.dict(os.environ, {"PRISM_CHANNEL": value}):
                with self.subTest(channel=value), self.assertRaises(SystemExit):
                    self.build.requested_channel("AlphaKore5/prism_gui_dev")
        with mock.patch.dict(os.environ, {"PRISM_CHANNEL": ""}):
            self.assertEqual(self.build.requested_channel("AlphaKore5/prism_gui"), "prod")

    def test_the_ci_variables_being_empty_means_prod_and_the_default_dev_repo(self):
        with mock.patch.dict(os.environ, {"PRISM_CHANNEL": "", "PRISM_UPDATE_REPO": "",
                                          "GITHUB_REPOSITORY": "x/y"}):
            self.assertEqual(self.build.requested_channel(), "prod")
        import inspect
        self.assertIn('os.environ.get("PRISM_UPDATE_REPO") or DEV_UPDATE_REPO',
                      inspect.getsource(self.build.build),
                      "an EMPTY repository variable must fall back to the default")

    def test_workflow_passes_the_channel_variables_and_the_repository(self):
        text = open(os.path.join(ROOT, ".github", "workflows", "build.yml"),
                    encoding="utf-8").read()
        for needle in ("PRISM_CHANNEL: ${{ vars.PRISM_CHANNEL }}",
                       "PRISM_UPDATE_REPO: ${{ vars.PRISM_UPDATE_REPO }}",
                       "GITHUB_REPOSITORY: ${{ github.repository }}"):
            self.assertIn(needle, text)

    def test_a_flaky_command_is_retried_and_a_real_failure_still_fails(self):
        import subprocess
        calls = []

        def flaky(cmd, **kw):
            calls.append(cmd)
            if len(calls) < 3:
                raise subprocess.CalledProcessError(1, cmd)
        with mock.patch.object(self.build.subprocess, "run", side_effect=flaky), \
             mock.patch("time.sleep") as slept:
            self.build.run_with_retries(["hdiutil", "create"], attempts=4, wait=5)
        self.assertEqual(len(calls), 3)
        self.assertEqual(slept.call_count, 2)
        calls.clear()
        always = subprocess.CalledProcessError(1, ["hdiutil"])
        with mock.patch.object(self.build.subprocess, "run", side_effect=always), \
             mock.patch("time.sleep"):
            with self.assertRaises(subprocess.CalledProcessError):
                self.build.run_with_retries(["hdiutil", "create"], attempts=3, wait=0)

    def test_a_partial_image_is_removed_between_attempts(self):
        import subprocess, tempfile
        partial = os.path.join(tempfile.mkdtemp(), "Prism.dmg")
        open(partial, "w").write("half")
        seen = []

        def flaky(cmd, **kw):
            seen.append(os.path.exists(partial))
            if len(seen) == 1:
                raise subprocess.CalledProcessError(1, cmd)
        with mock.patch.object(self.build.subprocess, "run", side_effect=flaky), \
             mock.patch("time.sleep"):
            self.build.run_with_retries(["hdiutil"], attempts=2, wait=0, cleanup=partial)
        self.assertEqual(seen, [True, False])

    def test_unknown_channel_refuses(self):
        with mock.patch.dict(os.environ, {"PRISM_CHANNEL": "beta"}):
            with self.assertRaises(SystemExit):
                self.build.requested_channel()
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PRISM_CHANNEL", None)
            self.assertEqual(self.build.requested_channel(), "prod")


if __name__ == "__main__":
    unittest.main()
