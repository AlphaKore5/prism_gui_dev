"""Pulse, the app side: what is recorded, what is never recorded, and that it
cannot hurt the app.

A temp folder stands in for ~/.prism (never the real one), and the licence
client is replaced, so nothing here talks to a server.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pulse  # noqa: E402


def _boom():
    raise KeyError("Shah Engineering quote for ravi@example.com 4471")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-pulse-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        p = mock.patch("paths.user_dir", lambda *parts: os.path.join(self.tmp, *parts))
        p.start(); self.addCleanup(p.stop)
        e = mock.patch.dict(os.environ, {"PRISM_PULSE": "1"})
        e.start(); self.addCleanup(e.stop)
        # No real sender thread in these tests (the suite fails on a leaked one);
        # flush() itself is tested directly in Sending.
        f = mock.patch.object(pulse, "flush_async")
        f.start(); self.addCleanup(f.stop)
        pulse.configure({})
        pulse._start_sent = False
        pulse._last_flush = 0.0

    def queued(self):
        path = os.path.join(self.tmp, "pulse", "queue.jsonl")
        if not os.path.exists(path):
            return []
        return [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]


class WhatIsAllowedToLeave(Base):
    def test_quoted_text_numbers_emails_and_home_are_blanked(self):
        home = os.path.expanduser("~")
        out = pulse.scrub_title(f"KeyError: 'Shah quote' for ravi@example.com at {home}/Clients/a.dxf line 4471")
        for leak in ("Shah", "quote", "ravi", "example.com", "Clients", "4471"):
            self.assertNotIn(leak, out, out)
        self.assertIn("KeyError", out)

    def test_an_error_event_carries_type_frames_and_fingerprint_but_not_the_message_content(self):
        try:
            _boom()
        except KeyError:
            pulse.error(*sys.exc_info())
        (ev,) = self.queued()
        blob = json.dumps(ev)
        for leak in ("Shah", "ravi", "example.com", "4471"):
            self.assertNotIn(leak, blob)
        self.assertEqual("error", ev["kind"])
        self.assertTrue(ev["title"].startswith("KeyError"))
        self.assertEqual(16, len(ev["fingerprint"]))
        self.assertTrue(any(f.startswith("test_pulse_client.py:") for f in ev["detail"]["frames"]), ev["detail"])

    def test_the_same_bug_has_the_same_fingerprint_and_another_does_not(self):
        def make(fn):
            try:
                fn()
            except Exception:
                return sys.exc_info()
        a, b = make(_boom), make(_boom)
        c = make(lambda: 1 / 0)
        fa = pulse.fingerprint(a[0], pulse._app_frames(a[2]))
        fb = pulse.fingerprint(b[0], pulse._app_frames(b[2]))
        fc = pulse.fingerprint(c[0], pulse._app_frames(c[2]))
        self.assertEqual(fa, fb)
        self.assertNotEqual(fa, fc)

    def test_a_run_title_is_blanked_like_an_error(self):
        pulse.run("failed", addon="task", title="Could not read 'Client Drawing 7.dxf'")
        (ev,) = self.queued()
        self.assertNotIn("Client", json.dumps(ev))
        self.assertEqual("failed", ev["result"])


class SlowAndStart(Base):
    def test_only_slow_actions_are_recorded(self):
        pulse.slow("open step", 400)
        pulse.slow("open step", 2600, screen="step")
        (ev,) = self.queued()
        self.assertEqual((2600, "step"), (ev["ms"], ev["screen"]))

    def test_start_is_recorded_once(self):
        pulse.started(); pulse.started()
        self.assertEqual(["start"], [e["kind"] for e in self.queued()])
        self.assertGreaterEqual(self.queued()[0]["ms"], 0)


class OffSwitches(Base):
    def test_the_customer_can_turn_it_off(self):
        pulse.configure({"pulse_enabled": False})
        pulse.run("ok", addon="task")
        self.assertEqual([], self.queued())

    def test_a_source_checkout_sends_nothing_unless_asked(self):
        with mock.patch.dict(os.environ, {"PRISM_PULSE": ""}), mock.patch("paths.is_frozen", lambda: False):
            pulse.run("ok", addon="task")
        self.assertEqual([], self.queued())

    def test_it_never_raises_even_when_the_folder_is_broken(self):
        with mock.patch("paths.user_dir", side_effect=OSError("disk gone")):
            pulse.run("ok", addon="task")
            pulse.slow("x", 9999)
            pulse.started()
            self.assertEqual(0, pulse.flush())

    def test_the_queue_is_capped(self):
        for i in range(pulse.MAX_QUEUE + 25):
            pulse.run("ok", addon="task")
        self.assertEqual(pulse.MAX_QUEUE, len(self.queued()))


class Sending(Base):
    def _send(self, call, events=3):
        for _ in range(events):
            pulse.run("ok", addon="task")
        from licensing import client
        fake_state = mock.Mock(license_id="lic_abc12345")
        with mock.patch("licensing.store.load", lambda d: {"license_id": "lic_abc12345"}), \
             mock.patch("licensing.state", lambda: fake_state), \
             mock.patch("licensing.device_fingerprint", lambda: "f" * 16), \
             mock.patch.object(client, "call", call):
            return pulse.flush()

    def test_a_batch_is_posted_with_the_licence_and_device_and_the_queue_clears(self):
        posted = []
        sent = self._send(lambda ep, body, **kw: posted.append((ep, body)) or {"recorded": 3})
        self.assertEqual(3, sent)
        ep, body = posted[0]
        self.assertEqual("/v1/pulse", ep)
        self.assertEqual(("lic_abc12345", "f" * 16, 3), (body["license_id"], body["device_fp"], len(body["events"])))
        self.assertEqual([], self.queued())

    def test_flush_waits_long_enough_for_a_sleeping_server(self):
        # The server's cold start measured 38-43 s; 8 s made the first send always time out.
        timeouts = []
        self._send(lambda ep, body, **kw: timeouts.append(kw.get("timeout")) or {})
        self.assertEqual(1, len(timeouts))
        self.assertGreaterEqual(timeouts[0] or 0, 60)

    def test_an_unreachable_server_keeps_the_queue(self):
        def down(*a, **k):
            raise OSError("no network")
        self.assertEqual(0, self._send(down))
        self.assertEqual(3, len(self.queued()))

    def test_a_server_that_calls_our_batch_malformed_drops_it_a_5xx_keeps_it(self):
        from licensing import client
        def invalid(*a, **k):
            raise client.ServerError("INVALID_REQUEST", "bad", 400)
        self.assertEqual(3, self._send(invalid))
        self.assertEqual([], self.queued())
        def busy(*a, **k):
            raise client.ServerError("INTERNAL", "oops", 502)
        self.assertEqual(0, self._send(busy))
        self.assertEqual(3, len(self.queued()))

    def test_more_than_fifty_events_go_in_batches_of_fifty(self):
        sizes = []
        self._send(lambda ep, body, **kw: sizes.append(len(body["events"])) or {}, events=120)
        self.assertEqual([50, 50, 20], sizes)


class MatchesServerSchema(Base):
    def test_every_kind_the_client_sends_is_accepted_by_the_server_model(self):
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        # the licence server checkout (it holds /v1/pulse since 2026-11); older names kept for old layouts
        found = [os.path.join(root, d) for d in ("license_server", "wt-license-key", "wt-server-ai")
                 if os.path.isfile(os.path.join(root, d, "app", "pulse.py"))]
        if not found:
            self.skipTest("licence server checkout with app/pulse.py not found under " + root)
        server = found[0]
        sys.path.insert(0, server)
        try:
            from app.schemas import PulseEventIn
        except Exception as e:                                       # noqa: BLE001
            self.skipTest("server schemas not importable: %r" % (e,))
        finally:
            sys.path.remove(server)
        try:
            _boom()
        except KeyError:
            pulse.error(*sys.exc_info(), addon="a" * 40, screen="s" * 40)
        pulse.run("failed", addon="task", title="x" * 500, ms=1200, run_id=pulse.new_run_id())
        pulse.slow("open step", 2600, screen="step")
        pulse.started()
        pulse.feedback("task", "abc123", rating="down", reason="wrong", outcome="used", model="gpt-4.1")
        kinds = set()
        for ev in self.queued():
            PulseEventIn(**ev)                                       # raises if the server would refuse it
            kinds.add(ev["kind"])
        self.assertEqual({"error", "run", "slow", "start", "feedback"}, kinds)


class WiredIn(Base):
    def test_the_crash_hook_in_diagnostics_reports_to_pulse(self):
        import diagnostics
        with mock.patch.object(pulse, "error") as err:
            diagnostics._pulse(KeyError, KeyError("x"), None)
        err.assert_called_once()

    def test_main_window_reports_slow_screens(self):
        import inspect, main_window
        src = inspect.getsource(main_window.MainWindow._show_screen)
        self.assertIn("pulse.slow", src)
        self.assertIn("_show_screen_now", src)


if __name__ == "__main__":
    unittest.main()
