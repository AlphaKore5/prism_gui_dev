"""Update outcome queue, reason codes and the free-space check."""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import licensing                                          # noqa: E402
import updater                                            # noqa: E402
from licensing import client                              # noqa: E402
from test_updater_phase1 import Harness                   # noqa: E402


class ReasonCodes(unittest.TestCase):
    def test_known_failures_map_to_fixed_codes(self):
        for text, code in (("Prism: hash mismatch after download.", "hash_mismatch"),
                           ("Prism: downloaded 5 bytes, manifest says 9.", "size_mismatch"),
                           ("x: could not be downloaded (down).", "download_failed"),
                           ("not enough disk space to prepare", "disk_full"),
                           ("this computer would not let Prism create a shortcut file", "symlink_privilege"),
                           ("a: staged copy failed final verification.", "verify_failed"),
                           ("needs a newer updater", "updater_too_old")):
            with self.subTest(code=code):
                self.assertEqual(updater.reason_code(updater.UpdateError(text)), code)

    def test_anything_else_is_just_error_and_never_echoes_the_message(self):
        got = updater.reason_code(RuntimeError("/home/someone/secret/path failed"))
        self.assertEqual(got, "error")


class Outbox(Harness):
    def setUp(self):
        super().setUp()
        for p in (mock.patch.object(licensing.store, "load",
                                    return_value={"license_id": "lic_x"}),
                  mock.patch.object(licensing, "device_fingerprint",
                                    return_value="fp-0000000001")):
            p.start()
            self.addCleanup(p.stop)

    def box(self):
        return updater._load()["outbox"]

    def test_outcome_is_queued_with_codes_only(self):
        updater.note_outcome("failed", "2.0.0", reason="hash_mismatch", host="a/b")
        (e,) = self.box()
        self.assertEqual((e["result"], e["to_version"], e["reason"]),
                         ("failed", "2.0.0", "hash_mismatch"))
        self.assertEqual(e["channel"], "prod")

    def test_the_queue_is_capped(self):
        for i in range(updater.OUTBOX_MAX + 7):
            updater.note_outcome("ok", f"2.0.{i}")
        self.assertEqual(len(self.box()), updater.OUTBOX_MAX)
        self.assertEqual(self.box()[-1]["to_version"], f"2.0.{updater.OUTBOX_MAX + 6}")

    def test_delivered_entries_leave_the_queue_and_queue_time_is_not_sent(self):
        updater.note_outcome("ok", "2.0.0")
        with mock.patch.object(client, "call", return_value={"recorded": 1}) as call:
            self.assertEqual(updater.flush_outbox(), 1)
        body = call.call_args[0][1]
        self.assertNotIn("queued_at", body)
        self.assertEqual((body["license_id"], body["device_fp"]), ("lic_x", "fp-0000000001"))
        self.assertEqual(self.box(), [])

    def test_unreachable_keeps_everything_for_next_time(self):
        updater.note_outcome("ok", "2.0.0")
        with mock.patch.object(client, "call", side_effect=client.Unreachable("down")):
            self.assertEqual(updater.flush_outbox(), 0)
        self.assertEqual(len(self.box()), 1)

    def test_a_server_error_is_not_a_verdict_and_keeps_the_report(self):
        updater.note_outcome("ok", "2.0.0")
        with mock.patch.object(client, "call",
                               side_effect=client.ServerError("DOWN", "503", {})):
            self.assertEqual(updater.flush_outbox(), 0)
        self.assertEqual(len(self.box()), 1)

    def test_our_own_malformed_report_is_dropped_not_retried_for_ever(self):
        updater.note_outcome("ok", "2.0.0")
        with mock.patch.object(client, "call",
                               side_effect=client.ServerError("INVALID_REQUEST", "bad", {})):
            self.assertEqual(updater.flush_outbox(), 1)
        self.assertEqual(self.box(), [])

    def test_a_report_older_than_two_weeks_is_dropped_unsent(self):
        updater.note_outcome("ok", "2.0.0")
        state = updater._load()
        state["outbox"][0]["queued_at"] = int(time.time()) - updater.OUTBOX_MAX_AGE - 5
        updater._save(state)
        with mock.patch.object(client, "call") as call:
            updater.flush_outbox()
        call.assert_not_called()
        self.assertEqual(self.box(), [])

    def test_order_is_kept_when_the_server_fails_part_way(self):
        for v in ("2.0.0", "2.0.1", "2.0.2"):
            updater.note_outcome("ok", v)
        answers = [{"recorded": 1}, client.Unreachable("x")]

        def call(*a, **k):
            r = answers.pop(0)
            if isinstance(r, Exception):
                raise r
            return r
        with mock.patch.object(client, "call", side_effect=call):
            self.assertEqual(updater.flush_outbox(), 1)
        self.assertEqual([e["to_version"] for e in self.box()], ["2.0.1", "2.0.2"])

    def test_without_a_licence_nothing_is_sent_and_nothing_is_lost(self):
        updater.note_outcome("ok", "2.0.0")
        with mock.patch.object(licensing.store, "load", return_value={}), \
             mock.patch.object(client, "call") as call:
            with mock.patch.object(licensing, "state",
                                   return_value=mock.Mock(license_id="")):
                self.assertEqual(updater.flush_outbox(), 0)
        call.assert_not_called()
        self.assertEqual(len(self.box()), 1)

    def test_report_async_is_a_no_op_with_an_empty_queue(self):
        with mock.patch.object(updater._threading, "Thread") as thread:
            updater.report_async()
        thread.assert_not_called()


class FreeSpace(Harness):
    def setUp(self):
        super().setUp()
        self.install_dir = tempfile.mkdtemp(prefix="prism-install-")

    def files(self, size):
        return [{"path": "Prism", "size": size, "sha256": "0" * 64, "mode": 0}]

    def test_enough_space_passes(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10**12)):
            updater._check_free_space(self.tmp, self.files(10**6))

    def test_too_little_space_is_refused_with_a_plain_message(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=10**6)):
            with self.assertRaises(updater.UpdateError) as ctx:
                updater._check_free_space(self.tmp, self.files(10**9))
        self.assertIn("not enough disk space", str(ctx.exception))
        self.assertEqual(updater.reason_code(ctx.exception), "disk_full")

    def test_the_margin_is_included(self):
        size = 10**9
        need = int(size * (1 + updater.FREE_SPACE_MARGIN)) + updater.FREE_SPACE_FLOOR
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=need - 1)):
            with self.assertRaises(updater.UpdateError):
                updater._check_free_space(self.tmp, self.files(size))
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=need)):
            updater._check_free_space(self.tmp, self.files(size))

    def test_symlinks_cost_nothing(self):
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(
                free=updater.FREE_SPACE_FLOOR + 10)):
            updater._check_free_space(self.tmp, [{"path": "l", "symlink": "x"}])

    def test_an_unreadable_disk_does_not_block_the_update(self):
        with mock.patch("shutil.disk_usage", side_effect=OSError("?")):
            updater._check_free_space(self.tmp, self.files(10**12))

    def test_a_full_disk_stops_staging_before_anything_is_written(self):
        manifest = {"version": "2.0.0", "files": self.files(10**9)}
        check = updater.UpdateCheck(version="2.0.0", manifest=manifest)
        with mock.patch("shutil.disk_usage", return_value=mock.Mock(free=1000)):
            with self.assertRaises(updater.UpdateError):
                updater.stage_update(check, self.install_dir,
                                     fetch=lambda url, *, timeout: b"")
        stage = os.path.join(updater.stage_root(self.install_dir), "2.0.0")
        self.assertFalse(os.path.exists(stage))
        self.assertEqual(updater._load()["outbox"][-1]["reason"], "disk_full")


if __name__ == "__main__":
    unittest.main()
