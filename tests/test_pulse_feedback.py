"""Pulse crash marker lifecycle and the thumbs up/down widget, run for real:
a temp folder stands in for ~/.prism, Qt is offscreen, nothing is sent."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget                          # noqa: E402

_app = QApplication.instance() or QApplication([])

import pulse                                                        # noqa: E402
from widgets.feedback_bar import FeedbackBar                        # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-pulse-fb-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        for p in (mock.patch("paths.user_dir", lambda *parts: os.path.join(self.tmp, *parts)),
                  mock.patch.dict(os.environ, {"PRISM_PULSE": "1"}),
                  mock.patch.object(pulse, "flush_async")):
            p.start()
            self.addCleanup(p.stop)
        pulse.configure({})
        pulse._screen = "start"
        self.addCleanup(self._close_trace)

    def _close_trace(self):
        import faulthandler
        faulthandler.disable()
        if pulse._trace_file is not None:
            pulse._trace_file.close()
            pulse._trace_file = None

    def queued(self):
        path = os.path.join(self.tmp, "pulse", "queue.jsonl")
        if not os.path.exists(path):
            return []
        return [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]

    marker = property(lambda self: os.path.join(self.tmp, "pulse", "running.marker"))


class CrashMarker(Base):
    def test_clean_exit_removes_the_marker_and_next_start_reports_nothing(self):
        pulse.begin_session()
        self.assertTrue(os.path.exists(self.marker))
        pulse.clean_exit()
        self.assertFalse(os.path.exists(self.marker))
        self.assertEqual([], self.queued())
        pulse.begin_session()
        self.assertEqual([], [e for e in self.queued() if e["kind"] == "crash"])

    def test_unclean_exit_is_reported_exactly_once_with_the_last_screen(self):
        pulse.begin_session()
        pulse.screen("boq")
        self.assertEqual("boq", json.load(open(self.marker))["last_screen"])
        self._close_trace()                     # the process "died": no clean_exit
        pulse.begin_session()                   # next launch
        crashes = [e for e in self.queued() if e["kind"] == "crash"]
        self.assertEqual(1, len(crashes))
        c = crashes[0]
        self.assertEqual("boq", c["last_screen"])
        # detail is a dict on the wire (server PulseEventIn.detail is dict|None); this used to expect a string
        self.assertEqual({"note": "previous run did not exit cleanly"}, c["detail"])
        self.assertEqual(16, len(c["fingerprint"]))
        import hashlib
        self.assertEqual(hashlib.sha1(("unclean-exit" + c["version"] + "boq").encode()).hexdigest()[:16],
                         c["fingerprint"])
        pulse.clean_exit()
        pulse.begin_session()                   # and a third start is quiet
        self.assertEqual(1, len([e for e in self.queued() if e["kind"] == "crash"]))

    def test_native_crash_trace_tail_is_scrubbed_and_limited_to_ten_lines(self):
        pulse.begin_session()
        self._close_trace()
        home = os.path.expanduser("~")
        with open(os.path.join(self.tmp, "pulse", "native-crash.txt"), "w") as f:
            f.write("\n".join(f'File "{home}/secret/Client Plans/a.py", line {i} in f{i}' for i in range(30)))
        pulse.begin_session()
        detail = [e for e in self.queued() if e["kind"] == "crash"][0]["detail"]["note"]
        self.assertNotIn("secret", detail)
        self.assertNotIn("Client", detail)
        self.assertEqual(10, detail.count(" | "))       # exactly the last ten lines
        self.assertIn("line <n>", detail.replace("in f<n>", ""))
        self.assertNotIn("line 19", detail)

    def test_crash_event_is_accepted_by_the_server_schema(self):
        server = os.path.join(os.path.dirname(ROOT), "wt-server-ai")
        if not os.path.isdir(server):
            self.skipTest("server worktree not found at " + server)
        sys.path.insert(0, server)
        try:
            from app.schemas import PulseEventIn
        except Exception as e:                                       # noqa: BLE001
            self.skipTest("server schemas not importable: %r" % (e,))
        finally:
            sys.path.remove(server)
        pulse.begin_session()
        pulse.screen("a-screen-name-longer-than-twenty-four")
        self._close_trace()
        pulse.begin_session()
        c = [e for e in self.queued() if e["kind"] == "crash"][0]
        PulseEventIn(**c)                                            # raises if the server would refuse it
        self.assertLessEqual(len(c["last_screen"]), 24)
        self.assertIsInstance(c["detail"], dict)

    def test_it_never_raises_and_does_nothing_when_pulse_is_off(self):
        pulse.configure({"pulse_enabled": False})
        pulse.begin_session()
        self.assertFalse(os.path.exists(self.marker))
        pulse.configure({})
        with mock.patch("paths.user_dir", side_effect=OSError("disk gone")):
            pulse.begin_session(); pulse.screen("x"); pulse.clean_exit()


class Widget(Base):
    def bar(self):
        self.host = QWidget()
        b = FeedbackBar("task", "r" * 32, parent=self.host)
        self.host.show()
        return b

    def test_thumb_up_queues_one_up_event(self):
        b = self.bar()
        b.up_btn.click()
        ev = self.queued()
        self.assertEqual(1, len(ev))
        self.assertEqual(("feedback", "task", "r" * 32, "up", "", "none"),
                         tuple(ev[0][k] for k in ("kind", "addon", "run_id", "rating", "reason", "outcome")))
        self.assertFalse(any(c.isVisible() for c in b.chips.values()))

    def test_thumb_down_queues_down_and_shows_three_chips_each_queueing_its_reason(self):
        b = self.bar()
        b.down_btn.click()
        self.assertEqual(["down"], [e["rating"] for e in self.queued()])
        self.assertEqual({"wrong", "incomplete", "slow"}, {k for k, c in b.chips.items() if c.isVisible()})
        b.chips["incomplete"].click()
        ev = self.queued()
        self.assertEqual(2, len(ev))
        self.assertEqual(("down", "incomplete", "none"), (ev[1]["rating"], ev[1]["reason"], ev[1]["outcome"]))
        self.assertFalse(any(c.isVisible() for c in b.chips.values()))

    def test_outcome_is_recorded_without_a_rating(self):
        b = self.bar()
        b.mark("redone")
        e = self.queued()[0]
        self.assertEqual(("", "", "redone"), (e["rating"], e["reason"], e["outcome"]))

    def test_hidden_and_silent_when_pulse_is_off(self):
        pulse.configure({"pulse_enabled": False})
        host = QWidget()                                   # shown as it is inside a result view
        b = FeedbackBar("task", "x", parent=host)
        host.show()
        self.assertFalse(b.isVisible())
        b.up_btn.click()
        self.assertEqual([], self.queued())

    def test_run_id_is_the_one_the_ai_gateway_recorded(self):
        import ai_server
        with mock.patch.dict(ai_server._run), mock.patch.object(ai_server, "active", lambda: True), \
             mock.patch.object(ai_server, "_ai", lambda: mock.Mock()):
            ai_server.begin_run("r0123456789abcdef")
            # patch.dict puts _run back when the block ends, so everything that
            # reads the gateway's id has to happen inside it.
            rid = pulse.new_run_id()
            self.assertEqual("r0123456789abcdef", rid)
            pulse.run("ok", addon="task", run_id=rid)
            FeedbackBar("task", rid).up_btn.click()
        ev = self.queued()
        self.assertEqual(["r0123456789abcdef"] * 2, [e["run_id"] for e in ev])

    def test_a_fresh_id_only_when_the_gateway_tagged_nothing(self):
        import ai_server
        with mock.patch.dict(ai_server._run, {"id": ""}):
            rid = pulse.new_run_id()
        self.assertRegex(rid, r"^[A-Za-z0-9_-]{1,40}$")

    def test_run_event_carries_the_run_id(self):
        pulse.run("ok", addon="task", run_id="abc")
        self.assertEqual("abc", self.queued()[0]["run_id"])

    def test_screenshot_in_a_result_view(self):
        out = os.environ.get("FEEDBACK_SHOT_DIR")
        if not out:
            self.skipTest("set FEEDBACK_SHOT_DIR to save the screenshot")
        from widgets import chat_thread as T
        from PySide6.QtWidgets import QVBoxLayout
        os.makedirs(out, exist_ok=True)
        import paths
        qss = open(paths.resource("style.qss"), encoding="utf-8").read()
        _app.setStyleSheet(qss.replace("%ASSETS%", paths.resource("assets").replace(os.sep, "/")))
        self.addCleanup(lambda: _app.setStyleSheet(""))
        host = QWidget()
        host.setStyleSheet("background: #EEEDEA;")
        col = QVBoxLayout(host)
        row, _ = T.answer_row("## Quotation\n\n| Item | Qty |\n|---|---|\n| Duct | 12 |\n", "Prism AI")
        col.addWidget(row)
        bar = FeedbackBar("task", "r" * 32)
        col.addWidget(bar)
        host.resize(720, 300)
        host.show()
        _app.processEvents()
        host.grab().save(os.path.join(out, "feedback-thumbs.png"))
        bar.down_btn.click()
        _app.processEvents()
        host.grab().save(os.path.join(out, "feedback-thumbs-down-chips.png"))


if __name__ == "__main__":
    unittest.main()
