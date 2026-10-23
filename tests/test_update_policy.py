"""Signed release policy: rollout, min_updater, revoked -- validation and how
the current client acts on them."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import update_manifest as UM                              # noqa: E402
import updater                                            # noqa: E402
from test_updater_phase1 import Harness                   # noqa: E402


class PolicyValidation(unittest.TestCase):
    def ok(self, **kw):
        UM.check_policy({"version": "1.0.0", **kw})

    def bad(self, **kw):
        with self.assertRaises(UM.ManifestError):
            UM.check_policy({"version": "1.0.0", **kw})

    def test_absent_fields_are_fine(self):
        self.ok()

    def test_rollout_must_be_a_whole_number_0_to_100(self):
        for good in (0, 5, 100):
            self.ok(rollout=good)
        for wrong in (-1, 101, 5.5, "5", True, None):
            with self.subTest(rollout=wrong):
                self.bad(rollout=wrong)

    def test_min_updater_must_be_a_non_negative_whole_number(self):
        self.ok(min_updater=0)
        self.ok(min_updater=3)
        for wrong in (-1, 1.5, "2", True):
            with self.subTest(min_updater=wrong):
                self.bad(min_updater=wrong)

    def test_revoked_must_be_a_short_list_of_strings(self):
        self.ok(revoked=[])
        self.ok(revoked=["1.6.9", "1.6.8"])
        for wrong in ("1.6.9", [1], [""], ["x" * 65], ["1"] * (UM.MAX_REVOKED + 1), None):
            with self.subTest(revoked=wrong):
                self.bad(revoked=wrong)

    def test_a_bad_policy_cannot_get_through_verify(self):
        priv, pub = __import__("test_updater_phase1")._keypair()
        token = UM.sign({"version": "2.0.0", "files": [], "rollout": 500}, priv, kid="u1")
        with self.assertRaises(UM.ManifestError):
            UM.verify(token, public_keys={"u1": pub})


class Buckets(unittest.TestCase):
    def test_bucket_is_stable_and_in_range(self):
        a = UM.rollout_bucket("device-a", "2.0.0")
        self.assertEqual(a, UM.rollout_bucket("device-a", "2.0.0"))
        self.assertTrue(0 <= a < 100)

    def test_same_device_lands_differently_per_version(self):
        buckets = {UM.rollout_bucket("device-a", f"2.0.{i}") for i in range(30)}
        self.assertGreater(len(buckets), 10)

    def test_share_inside_a_rollout_is_roughly_the_percentage(self):
        n = 4000
        for pct in (5, 25, 50):
            inside = sum(UM.in_rollout({"version": "2.0.0", "rollout": pct}, f"dev-{i}")
                         for i in range(n))
            with self.subTest(pct=pct):
                self.assertAlmostEqual(inside / n, pct / 100, delta=0.03)

    def test_widening_never_removes_a_device(self):
        for i in range(500):
            fp = f"dev-{i}"
            if UM.in_rollout({"version": "2.0.0", "rollout": 5}, fp):
                self.assertTrue(UM.in_rollout({"version": "2.0.0", "rollout": 25}, fp))

    def test_zero_includes_nobody_and_full_or_absent_everybody(self):
        self.assertFalse(UM.in_rollout({"version": "2.0.0", "rollout": 0}, "dev-1"))
        self.assertTrue(UM.in_rollout({"version": "2.0.0", "rollout": 100}, "dev-1"))
        self.assertTrue(UM.in_rollout({"version": "2.0.0"}, ""))

    def test_unknown_device_is_not_placed_in_a_partial_rollout(self):
        self.assertFalse(UM.in_rollout({"version": "2.0.0", "rollout": 50}, ""))


class ClientActsOnPolicy(Harness):
    def fetch_for(self, manifest):
        token = self._sign(manifest).encode()
        return lambda url, *, timeout: token

    def check(self, manifest, **kw):
        return updater.check_for_update(running="1.0.0",
                                        fetch=self.fetch_for(manifest), **kw)

    def test_revoked_version_is_not_offered(self):
        self.assertIsNone(self.check({"version": "2.0.0", "files": [],
                                      "revoked": ["2.0.0"]}))

    def test_revoking_another_version_changes_nothing(self):
        self.assertEqual(self.check({"version": "2.0.0", "files": [],
                                     "revoked": ["1.9.0"]}).version, "2.0.0")

    def test_updater_too_old_raises_the_download_page_fallback_error(self):
        with self.assertRaises(updater.UpdaterTooOld):
            self.check({"version": "2.0.0", "files": [],
                        "min_updater": updater.UPDATER_LEVEL + 1})

    def test_updater_too_old_is_an_update_error(self):
        # main_window / UpdateWorker catch UpdateError and open the download page.
        self.assertTrue(issubclass(updater.UpdaterTooOld, updater.UpdateError))

    def test_min_updater_at_or_below_ours_is_fine(self):
        self.assertEqual(self.check({"version": "2.0.0", "files": [],
                                     "min_updater": updater.UPDATER_LEVEL}).version, "2.0.0")

    def test_no_update_means_no_too_old_error(self):
        # A release we would not offer anyway must not show an alarming message.
        self.assertIsNone(self.check({"version": "0.9.0", "files": [],
                                      "min_updater": updater.UPDATER_LEVEL + 5}))

    def test_rollout_gates_automatic_offers_only(self):
        manifest = {"version": "2.0.0", "files": [], "rollout": 0}
        with mock.patch.object(updater, "_device_fingerprint", return_value="dev-1"):
            self.assertIsNone(self.check(manifest, honour_rollout=True))
            # A customer who pressed Download asked for it.
            self.assertEqual(self.check(manifest).version, "2.0.0")

    def test_full_rollout_is_offered_automatically(self):
        with mock.patch.object(updater, "_device_fingerprint", return_value="dev-1"):
            self.assertEqual(self.check({"version": "2.0.0", "files": [], "rollout": 100},
                                        honour_rollout=True).version, "2.0.0")

    def test_manual_check_default_matches_the_old_behaviour(self):
        import inspect
        self.assertFalse(inspect.signature(updater.check_for_update)
                         .parameters["honour_rollout"].default)


if __name__ == "__main__":
    unittest.main()
