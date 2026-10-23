"""End-to-end update scenarios, in real processes. See e2e_update_harness.py for
exactly what is real and what is a stand-in -- a green run here proves the
update LOGIC on a real Linux filesystem, not behaviour on Windows or macOS."""
from __future__ import annotations

import os
import re
import shutil
import signal
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import e2e_update_harness as H                                  # noqa: E402

NEEDS_TAG = unittest.skipUnless(
    H.tag_available(), f"git tag {H.OLD_TAG} not in this clone -- `git fetch --tags`")


class E2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sec, cls.pub = H.keypair()
        cls.keep = tempfile.mkdtemp(prefix="e2e-src-")
        cls.old_src = H.extract_tag(os.path.join(cls.keep, "old")) if H.tag_available() else None

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.keep, ignore_errors=True)

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="e2e-")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.server = H.FakeGitHub()
        self.addCleanup(self.server.stop)

    def release(self, version, **kw):
        return H.Release(self.work, version, H.ROOT, sec=self.sec, pub=self.pub, **kw)

    def old_client(self):
        tree = H.build_tree(os.path.join(self.work, "c-old"), "1.6.10", self.old_src,
                            test_pub=self.pub)
        return H.App(self.work, tree, self.server)

    def new_client(self, version="1.6.11", **kw):
        kw.setdefault("fallbacks", (H.FALLBACK,))
        tree = H.build_tree(os.path.join(self.work, f"c-{version}"), version, H.ROOT,
                            test_pub=self.pub, **kw)
        return H.App(self.work, tree, self.server)

    def assert_matches_manifest(self, app, release):
        for entry in release.manifest["files"]:
            if "symlink" in entry:
                continue
            path = os.path.join(app.install, entry["path"])
            self.assertTrue(os.path.isfile(path), entry["path"])
            self.assertEqual(UM_sha(path), entry["sha256"], entry["path"])


def UM_sha(path):
    import update_manifest
    return update_manifest.sha256_file(path)


@NEEDS_TAG
class Updating(E2E):
    def test_released_1_6_10_updates_to_the_new_release(self):
        """The one that matters: the real v1.6.10 updater, a release signed by
        the new tooling with every new policy field."""
        rel = self.release("1.6.11", policy={"rollout": 5, "min_updater": 2,
                                             "revoked": ["1.6.8"], "channel": "prod"})
        self.server.publish(rel)
        app = self.old_client()
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.11"), app.names())
        self.assertEqual(app.names()[:5], ["start:1.6.10", "confirmed:1.6.10",
                                           "offered:1.6.11", "staged:1.6.11", "apply_started"])
        self.assert_matches_manifest(app, rel)
        self.assertEqual(app.leftovers(), [], "no backup, staging or failed copies left")
        self.assertEqual(app.update_state()["highest_seen_version"], "1.6.11")

    def test_new_client_updates_again_and_only_changed_files_are_fetched(self):
        app = self.new_client("1.6.11")
        rel = self.release("1.6.12", payload="a different payload\n")
        self.server.publish(rel)
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())
        fetched = set(self.server.hits("cdn", H.PRIMARY))
        self.assertNotIn(f"{rel.plat}___internal__paths.py", fetched,
                         "an unchanged file must not be downloaded")
        self.assertIn(f"{rel.plat}___internal__payload.txt", fetched)
        self.assert_matches_manifest(app, rel)

    def test_nothing_newer_is_a_quiet_no_op(self):
        app = self.new_client("1.6.12")
        self.server.publish(self.release("1.6.11"))
        before = H.tree_digest(app.install)
        app.run("--update")
        self.assertEqual(app.names()[-1], "no_update")
        self.assertEqual(H.tree_digest(app.install), before)


@NEEDS_TAG
class WhenHostsMisbehave(E2E):
    def test_primary_down_files_and_manifest_come_from_the_fallback(self):
        app = self.new_client("1.6.11")
        rel = self.release("1.6.12", payload="x\n")
        self.server.publish(rel)
        self.server.fault(H.PRIMARY, "down")
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())
        self.assertTrue(self.server.hits("cdn", H.FALLBACK))
        self.assert_matches_manifest(app, rel)

    def test_corrupt_file_on_the_primary_is_replaced_from_the_fallback(self):
        app = self.new_client("1.6.11")
        rel = self.release("1.6.12", payload="x\n")
        self.server.publish(rel)
        self.server.fault(H.PRIMARY, "corrupt", "payload.txt")
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())
        self.assert_matches_manifest(app, rel)

    def test_corrupt_everywhere_fails_and_leaves_the_install_untouched(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", payload="x\n"))
        for repo in (H.PRIMARY, H.FALLBACK):
            self.server.fault(repo, "corrupt", "payload.txt")
        before = H.tree_digest(app.install)
        app.run("--update")
        self.assertIn("update_failed", app.names())
        self.assertNotIn("apply_started", app.names())
        self.assertEqual(H.tree_digest(app.install), before)
        self.assertEqual(app.leftovers(), [], "a failed stage must not be left behind")

    def test_connection_dropped_mid_file_everywhere_leaves_nothing_changed(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", payload="y" * 5000 + "\n"))
        for repo in (H.PRIMARY, H.FALLBACK):
            self.server.fault(repo, "drop_mid", "payload.txt")
        before = H.tree_digest(app.install)
        app.run("--update")
        self.assertIn("update_failed", app.names())
        self.assertEqual(H.tree_digest(app.install), before)
        self.assertEqual(app.leftovers(), [])

    def test_forged_manifest_is_ignored(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12"))
        for repo in (H.PRIMARY, H.FALLBACK):
            self.server.fault(repo, "forge")
        before = H.tree_digest(app.install)
        app.run("--update")
        self.assertIn("update_failed", app.names())
        self.assertEqual(H.tree_digest(app.install), before)

    def test_every_host_unreachable_is_quiet(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12"))
        for repo in (H.PRIMARY, H.FALLBACK):
            self.server.fault(repo, "down")
        app.run("--update")
        self.assertEqual(app.names()[-1], "no_update")

    def test_killed_mid_download_changes_nothing_and_the_next_try_succeeds(self):
        app = self.new_client("1.6.11")
        rel = self.release("1.6.12", payload="z\n")
        self.server.publish(rel)
        self.server.fault(H.PRIMARY, "slow", ("payload.txt", 20))
        before = H.tree_digest(app.install)
        proc = app.popen("--update")
        end = time.time() + 60
        while time.time() < end and "payload.txt" not in " ".join(self.server.hits("cdn")):
            time.sleep(0.05)
        self.assertIn(f"{rel.plat}___internal__payload.txt", self.server.hits("cdn"),
                      "the download never started")
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(10)
        self.assertEqual(H.tree_digest(app.install), before)
        self.assertNotIn("apply_started", app.names())
        self.server.clear_faults()
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())
        self.assert_matches_manifest(app, rel)


@NEEDS_TAG
class WhenTheNewVersionIsBad(E2E):
    def test_a_version_that_crashes_on_start_is_rolled_back_and_not_offered_again(self):
        app = self.new_client("1.6.11")
        rel = self.release("1.6.12", crash_on_start=True, payload="bad\n")
        self.server.publish(rel)
        app.run("--update")
        self.assertTrue(app.wait_for("crash:1.6.12"), app.names())
        # the customer opens Prism again: the unconfirmed update is undone
        app.run()
        self.assertTrue(app.wait_for("rolled_back:1.6.12"), app.names())
        self.assertTrue(app.wait_count("confirmed:1.6.11", 2), app.names())
        self.assertEqual(open(os.path.join(app.install, "_internal", "payload.txt")).read(),
                         "payload of 1.6.11\n")
        self.assertEqual(app.update_state()["failed_version"], "1.6.12")
        # and the broken release is not offered over and over
        app.run("--update")
        self.assertEqual(app.names()[-1], "no_update")
        self.assertEqual(app.leftovers(), [])

    def test_a_good_version_is_not_rolled_back_by_a_later_launch(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", payload="ok\n"))
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())
        app.run()
        self.assertNotIn("rolled_back:1.6.12", app.names())
        self.assertEqual(app.names()[-1], "confirmed:1.6.12")


@NEEDS_TAG
class ReleasePolicy(E2E):
    def test_rollout_zero_blocks_automatic_offers_but_not_a_manual_update(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", policy={"rollout": 0}, payload="r\n"))
        app.run("--auto")
        self.assertEqual(app.names()[-1], "no_update")
        app.run("--update")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())

    def test_full_rollout_is_offered_automatically(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", policy={"rollout": 100}, payload="r\n"))
        app.run("--auto")
        self.assertTrue(app.wait_for("confirmed:1.6.12"), app.names())

    def test_a_revoked_version_is_never_offered(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", policy={"revoked": ["1.6.12"]}))
        app.run("--update")
        self.assertEqual(app.names()[-1], "no_update")

    def test_an_updater_that_is_too_old_says_so_instead_of_trying(self):
        app = self.new_client("1.6.11")
        self.server.publish(self.release("1.6.12", policy={"min_updater": 99}))
        before = H.tree_digest(app.install)
        app.run("--update")
        failed = [e for e in app.events() if e["event"] == "update_failed"]
        self.assertEqual(failed[-1]["kind"], "UpdaterTooOld")
        self.assertEqual(H.tree_digest(app.install), before)


class TheStandInMatchesMain(unittest.TestCase):
    """The harness launcher is not main.py. These pin that it makes the same
    updater calls main.py does, so a change to main.py's update glue that the
    launcher does not follow shows up here instead of silently."""

    def test_main_py_makes_the_calls_the_launcher_makes(self):
        main_src = open(os.path.join(H.ROOT, "main.py"), encoding="utf-8").read()
        for call in ("check_and_rollback_if_pending", "note_rollback",
                     "confirm_startup_success", "note_installed",
                     "perform_apply_and_relaunch", "--prism-apply-update"):
            with self.subTest(call=call):
                self.assertIn(call, main_src)
                self.assertIn(call, H.LAUNCHER)

    def test_rollback_check_comes_before_the_startup_confirmation_in_both(self):
        main_src = open(os.path.join(H.ROOT, "main.py"), encoding="utf-8").read()
        for text in (main_src, H.LAUNCHER):
            self.assertLess(text.index("check_and_rollback_if_pending"),
                            text.index("confirm_startup_success"))


if __name__ == "__main__":
    unittest.main()
