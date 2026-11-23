"""A list is not a blast: the gap between emails, how many go per press and
per day, and when the send begins.

The owner's report: nothing limited or scheduled a list send, and every
email left exactly two seconds after the one before -- a metronome a
provider can hear. What is pinned here:

  · the engine (core/mailer.send_bulk): a jittered gap, a per-run cap, a
    start time that is waited for BEFORE logging in, and a stop that lands
    during the wait and sends nothing;
  · the policy (email_config): defaults that reproduce the old behaviour,
    sane clamping, the plan arithmetic, and that a save keeps the numbers;
  · the log (addons/email/sent_log): who a send left from, and how many
    left today -- with an old entry that names nobody counting against
    everybody;
  · the window (addons/email/dialog): the numbers reach the worker, the
    list is trimmed to the plan, the held-back ones stay on screen, and a
    scheduled send hands the worker its start time.

No SMTP anywhere: _connect is patched with a server that remembers what it
was asked to send. No event loop: every worker is a fake that answers at
once. Nothing touches ~/.prism or ~/Prism Email.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QDateTime  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import core_bridge as CB  # noqa: E402
import email_config  # noqa: E402
from addons.email import dialog as ED  # noqa: E402
from addons.email import sent_log  # noqa: E402
from test_email_compose import _FakeSendWorker, _cfg, _csv, _dialog  # noqa: E402

_app = QApplication.instance() or QApplication([])
mailer = CB.mailer


class _Server:
    def __init__(self):
        self.sent = []

    def send_message(self, msg):
        self.sent.append(msg["To"])

    def quit(self):
        pass


def _people(n):
    return [{"email": f"p{i}@x.in", "name": f"P{i}"} for i in range(n)]


# save_to_sent off: the Sent-folder copy opens a real IMAP connection to
# imap.x.in / mail.x.in (port 993) and is its own feature, not what this file tests.
CFG = {"email": {"address": "sales@x.in", "password": "p", "host": "h",
                 "port": 465, "save_to_sent": False}}


class TheEngineKeepsThePace(unittest.TestCase):

    def _run(self, people, **kw):
        server = _Server()
        naps = []
        with mock.patch.object(mailer, "_connect", return_value=server) as conn, \
                mock.patch.object(mailer.time, "sleep", naps.append):
            sent, failed = mailer.send_bulk(CFG, people, "s", "b", [], **kw)
        return server, sent, failed, naps, conn

    def test_the_gap_is_the_delay_plus_a_random_slice_of_the_jitter(self):
        with mock.patch.object(mailer.random, "uniform", return_value=1.5):
            self.assertAlmostEqual(mailer.pause_after_send(2.0, 3.0), 3.5)
        self.assertEqual(mailer.pause_after_send(2.0, 0.0), 2.0)
        self.assertEqual(mailer.pause_after_send(-5, -5), 0.0)

    def test_the_wait_between_two_sends_is_the_jittered_gap(self):
        with mock.patch.object(mailer.random, "uniform", return_value=1.0):
            server, sent, failed, naps, _ = self._run(
                _people(3), delay=2.0, jitter=1.0)
        self.assertEqual(len(sent), 3)
        # two pauses of 3.0s, slept in quarter-second slices
        self.assertAlmostEqual(sum(naps), 6.0, places=3)

    def test_a_failed_reconnect_still_reports_what_was_already_sent(self):
        """The reconnect used to raise out of send_bulk, discarding `sent`: the
        caller thought nothing had gone out and offered the same people again
        (review finding 1, 2026-10-01)."""
        server = _Server()
        seen, calls = [], []

        def connect(*_a, **_k):
            calls.append(1)
            if len(calls) > 1:                  # the first login works...
                raise OSError("reconnect failed")
            return server                       # ...every later one fails

        with mock.patch.object(mailer, "_connect", side_effect=connect), \
                mock.patch.object(mailer.time, "sleep", lambda _s: None):
            sent, failed = mailer.send_bulk(
                CFG, _people(3), "s", "b", [], session_max=1,
                on_progress=lambda *a: seen.append(a))

        self.assertEqual(sent, ["p0@x.in"])            # one really went out
        self.assertEqual([e for e, _ in failed], ["p1@x.in", "p2@x.in"])
        self.assertIn("reconnect", failed[0][1])
        self.assertEqual(server.sent, ["p0@x.in"])
        # every recipient got a progress report, so the dialog can account for them
        self.assertEqual([a[2] for a in seen], ["p0@x.in", "p1@x.in", "p2@x.in"])

    def test_a_per_run_limit_sends_to_the_first_n_only(self):
        server, sent, failed, naps, _ = self._run(_people(5), limit=2)
        self.assertEqual(sent, ["p0@x.in", "p1@x.in"])
        self.assertEqual(failed, [])
        self.assertEqual(server.sent, ["p0@x.in", "p1@x.in"])

    def test_zero_means_everyone(self):
        _, sent, _, _, _ = self._run(_people(4), limit=0)
        self.assertEqual(len(sent), 4)

    def test_a_start_time_is_waited_for_before_logging_in(self):
        """The login happens only when the hour arrives -- a send set for
        the morning must not hold an SMTP session open all night."""
        now = [1000.0]
        ticks = []

        def sleep(sec):
            now[0] += sec

        with mock.patch.object(mailer.time, "time", lambda: now[0]), \
                mock.patch.object(mailer.time, "sleep", sleep), \
                mock.patch.object(mailer, "_connect") as conn:
            conn.return_value = _Server()
            sent, failed = mailer.send_bulk(
                CFG, _people(1), "s", "b", [], delay=0.5,
                start_at=1003.0, on_wait=ticks.append)
        self.assertEqual(sent, ["p0@x.in"])
        self.assertGreaterEqual(now[0], 1003.0)
        self.assertEqual(ticks[0], 3)          # counted down from three
        self.assertIn(0, ticks)

    def test_a_stop_during_the_wait_sends_nothing_and_never_logs_in(self):
        now = [1000.0]
        with mock.patch.object(mailer.time, "time", lambda: now[0]), \
                mock.patch.object(mailer.time, "sleep", lambda s: None), \
                mock.patch.object(mailer, "_connect") as conn:
            sent, failed = mailer.send_bulk(
                CFG, _people(3), "s", "b", [], start_at=2000.0,
                should_stop=lambda: True)
        self.assertEqual((sent, failed), ([], []))
        conn.assert_not_called()

    def test_a_start_time_already_past_sends_at_once(self):
        _, sent, _, naps, conn = self._run(_people(1), start_at=1.0)
        self.assertEqual(len(sent), 1)
        conn.assert_called_once()


class ThePolicy(unittest.TestCase):

    def test_no_block_means_what_the_engine_always_did(self):
        self.assertEqual(email_config.send_policy({}), {
            "gap_seconds": 2.0, "jitter_seconds": 0.0,
            "max_per_run": 0, "max_per_day": 0})

    def test_junk_and_negatives_read_as_the_default_and_the_gap_has_a_floor(self):
        cfg = {"email": {"send": {"gap_seconds": 0, "jitter_seconds": "x",
                                  "max_per_run": -3, "max_per_day": "40"}}}
        self.assertEqual(email_config.send_policy(cfg), {
            "gap_seconds": 0.5, "jitter_seconds": 0.0,
            "max_per_run": 0, "max_per_day": 40})

    def test_the_plan_is_the_smaller_of_the_two_caps_and_says_why(self):
        p = {"max_per_day": 100, "max_per_run": 30}
        # both caps bite on 120: the day takes it to 100, the press to 30,
        # and both are said -- a reason left out is a number nobody can
        # explain to the person asking why only thirty went
        self.assertEqual(email_config.plan_send(p, 120, 0),
                         (30, ["daily limit 100, 0 already sent today",
                               "at most 30 per send"]))
        self.assertEqual(email_config.plan_send(p, 20, 0), (20, []))
        allowed, why = email_config.plan_send(p, 120, 80)
        self.assertEqual(allowed, 20)
        self.assertEqual(why, ["daily limit 100, 80 already sent today"])
        self.assertEqual(email_config.plan_send(p, 120, 100)[0], 0)
        self.assertEqual(email_config.plan_send({}, 120, 999), (120, []))

    def test_the_numbers_survive_a_save_of_the_accounts_and_the_sender_overlay(self):
        cfg = email_config.with_send_policy(
            {"email": {"address": "a@x.in", "password": "p", "host": "h",
                       "port": 465, "folder": "/f"}},
            {"gap_seconds": 5.0, "jitter_seconds": 2.0, "max_per_run": 25,
             "max_per_day": 200, "stray": 1})
        self.assertNotIn("stray", cfg["email"]["send"])
        accounts = email_config.sending_accounts_of(cfg)
        block = email_config.account_block(cfg, accounts)
        self.assertEqual(block["send"]["max_per_day"], 200)
        overlay = email_config.cfg_for_sender(cfg, accounts[0])
        self.assertEqual(overlay["email"]["send"]["gap_seconds"], 5.0)


class TheLogKnowsWhoSentAndHowManyToday(unittest.TestCase):

    def setUp(self):
        self.cfg = _cfg(tempfile.mkdtemp(prefix="prism-email-"))

    def _record(self, n, sender="", date=None):
        entry = sent_log.record(
            self.cfg, to=_people(n), subject="s", body="b",
            sent=[p["email"] for p in _people(n)], failed=[],
            attachments=[], sender=sender)
        return entry

    def test_the_sender_is_written_down(self):
        e = self._record(2, sender="Sales@X.in")
        self.assertEqual(e["from"], "sales@x.in")

    def test_today_is_counted_per_sender(self):
        self._record(3, sender="sales@x.in")
        self._record(2, sender="accounts@x.in")
        self.assertEqual(sent_log.sent_today(self.cfg, "sales@x.in"), 3)
        self.assertEqual(sent_log.sent_today(self.cfg, "accounts@x.in"), 2)
        self.assertEqual(sent_log.sent_today(self.cfg), 5)

    def test_yesterday_does_not_count(self):
        self._record(4, sender="sales@x.in")
        yesterday = (_dt.date.today() - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
        self.assertEqual(sent_log.sent_today(self.cfg, "sales@x.in", today=yesterday), 0)

    def test_an_old_entry_with_no_sender_counts_against_every_address(self):
        self._record(2)                       # written before "from" existed
        self.assertEqual(sent_log.sent_today(self.cfg, "sales@x.in"), 2)
        self.assertEqual(sent_log.sent_today(self.cfg, "other@x.in"), 2)


class TheWindow(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-email-")
        self.d = _dialog(self.folder)
        self.d.subject_edit.setText("Hello")
        self.d.body_edit.setPlainText("Dear {name}")
        self.d._load_list(_csv([("A", "a@x.in"), ("B", "b@x.in"), ("C", "c@x.in")]))

    def _send(self):
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes) as ask, \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"), \
                mock.patch.object(ED.CB.config, "save"):
            self.d._send()
        return ask

    def test_the_card_starts_from_the_saved_policy(self):
        cfg = _cfg(self.folder)
        cfg["email"]["send"] = {"gap_seconds": 4.0, "jitter_seconds": 1.5,
                                "max_per_run": 10, "max_per_day": 50}
        d = ED.EmailComposeDialog(cfg, [], None)
        self.assertEqual(d.gap_spin.value(), 4.0)
        self.assertEqual(d.jitter_spin.value(), 1.5)
        self.assertEqual(d.per_run_spin.value(), 10)
        self.assertEqual(d.per_day_spin.value(), 50)
        self.assertIn("4 to 5.5 seconds apart", d.pace_note.text())

    def test_the_gap_and_jitter_reach_the_worker(self):
        self.d.gap_spin.setValue(3.0)
        self.d.jitter_spin.setValue(2.0)
        ask = self._send()
        w = _FakeSendWorker.last
        self.assertEqual(w.pace["delay"], 3.0)
        self.assertEqual(w.pace["jitter"], 2.0)
        self.assertEqual(w.pace["start_at"], 0.0)
        self.assertIn("3 to 5 seconds apart", ask.call_args[0][2])

    def test_a_per_send_cap_trims_the_list_and_keeps_the_rest_on_screen(self):
        self.d.per_run_spin.setValue(2)
        self.assertEqual(self.d.send_btn.text(), "Send to 2 of 3 people")
        ask = self._send()
        self.assertEqual([r["email"] for r in _FakeSendWorker.last.recipients],
                         ["a@x.in", "b@x.in"])
        self.assertIn("1 more stay in the list", ask.call_args[0][2])
        # the window stays open with the one who did not go
        self.assertTrue(self.d.isVisible())
        self.assertEqual([r["email"] for r in self.d.recipients], ["c@x.in"])
        self.assertEqual(self.d.list_table.rowCount(), 1)

    def test_the_daily_cap_counts_what_already_left_this_address_today(self):
        sent_log.record(_cfg(self.folder), to=_people(2), subject="s", body="b",
                        sent=["p0@x.in", "p1@x.in"], failed=[], attachments=[],
                        sender="sales@shakti.one")
        self.d.per_day_spin.setValue(3)
        self.d._sync()
        self.assertIn("2 of 3 sent today", self.d.pace_note.text())
        self.assertEqual(self.d.send_btn.text(), "Send to 1 of 3 people")
        self._send()
        self.assertEqual(len(_FakeSendWorker.last.recipients), 1)

    def test_a_used_up_day_refuses_before_asking(self):
        sent_log.record(_cfg(self.folder), to=_people(3), subject="s", body="b",
                        sent=["p0@x.in", "p1@x.in", "p2@x.in"], failed=[],
                        attachments=[], sender="sales@shakti.one")
        self.d.per_day_spin.setValue(3)
        self.d._sync()
        self.assertFalse(self.d.send_btn.isEnabled())
        self.assertEqual(self.d.send_btn.text(), "Daily limit reached")
        with mock.patch.object(ED, "SendWorker") as worker, \
                mock.patch.object(QMessageBox, "information") as told, \
                mock.patch.object(QMessageBox, "question") as ask:
            self.d._send()
        worker.assert_not_called()
        ask.assert_not_called()
        self.assertIn("limit is 3", told.call_args[0][2])

    def test_send_later_hands_the_worker_a_start_time(self):
        later = QDateTime.currentDateTime().addSecs(1800)
        self.d.later_check.setChecked(True)
        self.d.later_edit.setDateTime(later)
        self.assertEqual(self.d.send_btn.text(), "Send to 3 people later")
        self.assertIn("keep Prism open", self.d.pace_note.text())
        ask = self._send()
        start = _FakeSendWorker.last.pace["start_at"]
        self.assertAlmostEqual(start, later.toSecsSinceEpoch(), delta=2)
        self.assertIn("Starts", ask.call_args[0][2])

    def test_a_time_already_past_means_now(self):
        self.d.later_check.setChecked(True)
        self.d.later_edit.setMinimumDateTime(QDateTime.currentDateTime().addDays(-2))
        self.d.later_edit.setDateTime(QDateTime.currentDateTime().addDays(-1))
        self.assertEqual(self.d.start_at(), 0.0)

    def test_the_numbers_are_remembered_on_send(self):
        self.d.gap_spin.setValue(7.0)
        self.d.per_day_spin.setValue(90)
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes), \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"), \
                mock.patch.object(ED.CB.config, "save") as save:
            self.d._send()
        save.assert_called_once()
        self.assertEqual(email_config.send_policy(self.d.cfg)["max_per_day"], 90)
        self.assertEqual(email_config.send_policy(self.d.cfg)["gap_seconds"], 7.0)

    def test_the_sent_log_names_the_sender(self):
        self._send()
        entries = sent_log.load(_cfg(self.folder))
        self.assertEqual(entries[0]["from"], "sales@shakti.one")

    def test_the_controls_lock_while_sending(self):
        self.d._set_sending(True)
        for w in (self.d.gap_spin, self.d.per_day_spin, self.d.later_check):
            self.assertFalse(w.isEnabled())
        self.d._set_sending(False)
        self.assertTrue(self.d.gap_spin.isEnabled())


if __name__ == "__main__":
    unittest.main()


class ACopyInSent(unittest.TestCase):
    """The engine files a copy of every send into the account's Sent folder
    (core/mailer, 10 Sep 2026) and defaults it on. The window shows the
    switch beside the pace, hands it to the worker as ticked, and keeps it
    with the pace; the config carries it across a save like `folder`."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-email-")
        self.d = _dialog(self.folder)
        self.d.subject_edit.setText("Hello")
        self.d.body_edit.setPlainText("Dear {name}")
        self.d._load_list(_csv([("A", "a@x.in")]))

    def _send(self):
        with mock.patch.object(ED, "SendWorker", _FakeSendWorker), \
                mock.patch.object(QMessageBox, "question",
                                  return_value=QMessageBox.Yes), \
                mock.patch.object(QMessageBox, "information"), \
                mock.patch.object(ED.CB.config, "save_run"), \
                mock.patch.object(ED.CB.config, "save"):
            self.d._send()

    def test_on_by_default_and_said_in_the_summary(self):
        self.assertTrue(self.d.sent_copy_check.isChecked())
        self.assertIn("copy kept in Sent", self.d._pace_summary())

    def test_the_switch_reaches_the_worker_either_way(self):
        self._send()
        self.assertTrue(_FakeSendWorker.last.cfg["email"]["save_to_sent"])
        self.d.sent_copy_check.setChecked(False)
        self.assertIn("no copy in Sent", self.d._pace_summary())
        self._send()
        self.assertFalse(_FakeSendWorker.last.cfg["email"]["save_to_sent"])

    def test_switching_it_off_is_remembered_and_reopens_the_card(self):
        self.d.sent_copy_check.setChecked(False)
        with mock.patch.object(ED.CB.config, "save") as save:
            self.d._remember_policy()
        self.assertTrue(save.called)
        self.assertFalse(email_config.save_to_sent(self.d.cfg))
        again = ED.EmailComposeDialog(self.d.cfg, [], None)
        self.assertFalse(again.sent_copy_check.isChecked())
        self.assertTrue(again.pace_details.isVisibleTo(again))

    def test_the_config_carries_it_like_folder(self):
        cfg = _cfg(self.folder)
        cfg["email"]["save_to_sent"] = False
        acct = {"address": "sales@shakti.one", "password": "x",
                "host": "smtp.gmail.com", "port": 465, "label": "Sales"}
        self.assertFalse(email_config.cfg_for_sender(cfg, acct)["email"]["save_to_sent"])
        self.assertFalse(email_config.account_block(cfg, [acct])["save_to_sent"])
        self.assertTrue(email_config.save_to_sent({}))          # missing = on
        self.assertTrue(email_config.cfg_for_sender(_cfg(self.folder), acct)
                        ["email"].get("save_to_sent", True))
