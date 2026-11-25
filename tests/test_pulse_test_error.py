"""Settings > Help & contact > "Send a test error": it exists in dev builds and
nowhere else.

The owner presses it in an installed dev build to prove that an error reaches
Pulse and Discord. A production customer must never see it, and nothing but that
card may be able to start it (RELEASE_ISSUES.md: dev changes must never reach
production). So this file checks, with the real Settings panel and the real
pulse module, that:

  PROD   no widget for it in any section; the work function records and sends
         nothing when called directly
  DEV    the button is there, records exactly one marked error, and the label
         tells the truth about what flush() did (sent / saved / Pulse is off)
  GUARDS channel.py still ships "prod"; no other code can reach the function;
         the gate is channel.is_dev(), not the environment

Everything runs under a throwaway user_dir (never ~/.prism) and the licence
client is replaced, so nothing here talks to a server. Worker results are
waited for with QThread.wait() then sendPostedEvents(), never an event loop.
"""
from __future__ import annotations

import ast
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QCheckBox   # noqa: E402

_app = QApplication.instance() or QApplication([])

import app_meta                                                    # noqa: E402
import channel                                                     # noqa: E402
import pulse                                                       # noqa: E402
from tests.test_ui_port_settings import _panel                     # noqa: E402
from widgets import settings_panel as SP                           # noqa: E402

BUTTON_TEXT = "Send a test error"
TITLE_START = "PulseTestError: test error from a dev build"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-pulse-testerror-")
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        for target, new in (("paths.user_dir", lambda *p: os.path.join(self.tmp, *p)),):
            m = mock.patch(target, new)
            m.start()
            self.addCleanup(m.stop)
        m = mock.patch.dict(os.environ, {"PRISM_PULSE": "1"})
        m.start()
        self.addCleanup(m.stop)
        pulse.configure({})
        pulse._last_flush = 0.0
        self.addCleanup(lambda: pulse.configure({}))
        self.panels = []
        self.addCleanup(lambda: [p.close() for p in self.panels])

    def channel(self, value):
        m = mock.patch.object(channel, "CHANNEL", value)
        m.start()
        self.addCleanup(m.stop)

    def panel(self, section="more", cfg=None):
        p = _panel(section, cfg)
        self.panels.append(p)
        return p

    def queued(self):
        path = os.path.join(self.tmp, "pulse", "queue.jsonl")
        if not os.path.exists(path):
            return []
        return [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]

    def licensed_server(self, call):
        """A licence on file and a stand-in for the licence client. Returns the patchers' ExitStack."""
        from contextlib import ExitStack
        from licensing import client
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch("licensing.store.load", lambda d: {"license_id": "lic_abc12345"}))
        stack.enter_context(mock.patch("licensing.state", lambda: mock.Mock(license_id="lic_abc12345")))
        stack.enter_context(mock.patch("licensing.device_fingerprint", lambda: "f" * 16))
        stack.enter_context(mock.patch.object(client, "call", call))
        return stack

    def press(self, p):
        """Click the button like a person, then wait for its worker and let the
        queued result reach the UI thread."""
        p.test_error_btn.click()
        p._test_error_worker.wait(20000)
        _app.sendPostedEvents()


def _all_texts(panel):
    texts = []
    for cls in (QPushButton, QLabel, QCheckBox):
        texts += [w.text() for w in panel.findChildren(cls)]
    return texts


def _every_section_texts(panel):
    out = []
    for key, *_ in SP.SECTIONS:
        panel.show_section(key)
        _app.sendPostedEvents()
        out += _all_texts(panel)
    return out


class Prod(Base):
    def setUp(self):
        super().setUp()
        self.channel("prod")

    def test_no_widget_for_it_in_any_section_of_the_panel(self):
        p = self.panel("more")
        for text in _every_section_texts(p):
            self.assertNotIn("test error", text.lower(), f"found in a prod build: {text!r}")
        self.assertFalse(hasattr(p, "test_error_btn"), "the button was created in a prod build")
        self.assertFalse(hasattr(p, "test_error_label"))

    def test_no_such_child_in_the_help_section_even_with_pulse_active(self):
        p = self.panel("more")
        self.assertEqual([], [b for b in p.findChildren(QPushButton) if BUTTON_TEXT in b.text()])
        self.assertEqual([], [b for b in p.findChildren(QLabel) if "Dev builds only" in b.text()])

    def test_calling_the_work_function_directly_records_and_sends_nothing(self):
        from licensing import client
        called = mock.Mock()
        with self.licensed_server(called), \
             mock.patch.object(pulse, "record") as rec, \
             mock.patch.object(pulse, "error") as err, \
             mock.patch.object(pulse, "flush") as fl, \
             mock.patch.object(pulse, "flush_async") as fla:
            result = pulse.send_test_error()
        self.assertEqual(("not_dev", 0), result)
        for m in (rec, err, fl, fla, called):
            m.assert_not_called()
        self.assertEqual([], self.queued())
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pulse", "queue.jsonl")))

    def test_the_worker_thread_does_nothing_either(self):
        from workers import SendTestErrorWorker
        called = mock.Mock()
        seen = []
        with self.licensed_server(called):
            w = SendTestErrorWorker()
            w.done.connect(lambda s, n: seen.append((s, n)))
            w.start()
            w.wait(20000)
            _app.sendPostedEvents()
        self.assertEqual([("not_dev", 0)], seen)
        called.assert_not_called()
        self.assertEqual([], self.queued())


class Dev(Base):
    def setUp(self):
        super().setUp()
        self.channel("dev")

    def test_the_button_and_its_one_line_are_there_and_enabled_when_pulse_is_active(self):
        p = self.panel("more")
        btn = p.test_error_btn
        self.assertEqual(BUTTON_TEXT, btn.text())
        self.assertTrue(btn.isEnabled())
        self.assertIn(btn, p.findChildren(QPushButton))
        self.assertTrue(any("Dev builds only" in l.text() and "test error" in l.text()
                            for l in p.findChildren(QLabel)))
        self.assertEqual("", p.test_error_label.text())

    def test_a_click_records_exactly_one_marked_error_and_flushes_once(self):
        p = self.panel("more")
        with mock.patch.object(pulse, "flush_async"), \
             mock.patch.object(pulse, "flush", return_value=1) as fl:
            self.press(p)
        fl.assert_called_once_with()
        (ev,) = self.queued()
        self.assertEqual("error", ev["kind"])
        self.assertEqual(pulse.scrub_title(f"{TITLE_START} ({app_meta.VERSION})"), ev["title"])
        self.assertTrue(ev["title"].startswith(TITLE_START), ev["title"])
        self.assertEqual("dev", ev["channel"])
        self.assertEqual(app_meta.VERSION[:20], ev["version"])
        self.assertTrue(any(f.startswith("pulse.py:send_test_error") for f in ev["detail"]["frames"]),
                        ev["detail"])

    def test_the_label_says_sent_when_flush_delivered(self):
        p = self.panel("more")
        with mock.patch.object(pulse, "flush_async"), mock.patch.object(pulse, "flush", return_value=1):
            self.press(p)
        self.assertEqual("Sent. 1 delivered to Pulse.", p.test_error_label.text())
        self.assertTrue(p.test_error_btn.isEnabled())

    def test_the_label_says_saved_not_sent_when_the_server_does_not_answer(self):
        p = self.panel("more")
        with mock.patch.object(pulse, "flush_async"), mock.patch.object(pulse, "flush", return_value=0):
            self.press(p)
        text = p.test_error_label.text()
        self.assertIn("Saved on this computer", text)
        self.assertNotIn("Sent", text)
        self.assertEqual(1, len(self.queued()), "the event must wait in the queue for next time")

    def test_a_real_flush_against_a_server_that_is_down_keeps_it_and_says_saved(self):
        def down(*a, **k):
            raise OSError("no network")
        p = self.panel("more")
        with self.licensed_server(down), mock.patch.object(pulse, "flush_async"):
            self.press(p)
        self.assertIn("Saved on this computer", p.test_error_label.text())
        self.assertEqual(1, len(self.queued()))

    def test_a_real_flush_against_a_server_that_answers_posts_one_error_and_says_sent(self):
        posted = []
        p = self.panel("more")
        with self.licensed_server(lambda ep, body, **kw: posted.append((ep, body)) or {"recorded": 1}):
            self.press(p)
        (ep, body), = posted
        self.assertEqual("/v1/pulse", ep)
        (ev,) = body["events"]
        self.assertTrue(ev["title"].startswith(TITLE_START))
        self.assertEqual("Sent. 1 delivered to Pulse.", p.test_error_label.text())
        self.assertEqual([], self.queued())

    def test_it_does_not_start_a_second_send_beside_its_own(self):
        """error() starts a background flush unless one ran in the last minute;
        two at once could deliver the event twice."""
        calls = []
        p = self.panel("more")
        before = {t.ident for t in threading.enumerate()}
        with self.licensed_server(lambda ep, body, **kw: calls.append(body) or {}):
            self.press(p)
        self.assertEqual(1, len(calls), "the event was posted more than once")
        started = [t for t in threading.enumerate() if t.ident not in before and t.name == "prism-pulse"]
        self.assertEqual([], started)

    def test_while_it_waits_the_label_says_sending_and_the_ui_is_not_blocked(self):
        gate = threading.Event()
        p = self.panel("more")

        def slow():
            gate.wait(20)
            return "sent", 1
        with mock.patch.object(pulse, "send_test_error", slow):
            p.test_error_btn.click()
            try:
                self.assertEqual("Sending…", p.test_error_label.text())
                self.assertFalse(p.test_error_btn.isEnabled(), "a second click would start a second send")
                self.assertTrue(p._test_error_worker.isRunning(), "click returned only because the work is on a worker")
            finally:
                gate.set()
            p._test_error_worker.wait(20000)
            _app.sendPostedEvents()
        self.assertEqual("Sent. 1 delivered to Pulse.", p.test_error_label.text())
        self.assertTrue(p.test_error_btn.isEnabled())

    def test_the_result_reaches_the_label_on_the_ui_thread_from_the_worker_thread(self):
        p = self.panel("more")
        where = {}
        real_done = p._test_error_done

        def done(state, delivered):
            where["slot"] = threading.get_ident()
            real_done(state, delivered)
        p._test_error_done = done

        def work():
            where["work"] = threading.get_ident()
            return "saved", 0
        with mock.patch.object(pulse, "send_test_error", work):
            self.press(p)
        self.assertEqual(threading.get_ident(), where["slot"])
        self.assertNotEqual(threading.get_ident(), where["work"])
        self.assertIn("Saved on this computer", p.test_error_label.text())

    def test_a_failure_inside_the_work_never_leaves_the_label_on_sending(self):
        p = self.panel("more")
        with mock.patch.object(pulse, "send_test_error", side_effect=RuntimeError("boom")):
            self.press(p)
        self.assertEqual("The test could not be sent.", p.test_error_label.text())
        self.assertTrue(p.test_error_btn.isEnabled())


class DevWhenPulseIsOff(Base):
    def setUp(self):
        super().setUp()
        self.channel("dev")

    def test_a_source_run_without_the_variable_shows_a_disabled_button_and_why(self):
        with mock.patch.dict(os.environ, {"PRISM_PULSE": ""}), mock.patch("paths.is_frozen", lambda: False):
            p = self.panel("more")
        self.assertFalse(p.test_error_btn.isEnabled())
        self.assertIn("PRISM_PULSE=1", p.test_error_label.text())
        with mock.patch.object(pulse, "record") as rec, mock.patch.object(pulse, "flush") as fl:
            p.test_error_btn.click()
        rec.assert_not_called()
        fl.assert_not_called()

    def test_the_customers_own_off_switch_is_named(self):
        pulse.configure({"pulse_enabled": False})
        p = self.panel("more")
        self.assertFalse(p.test_error_btn.isEnabled())
        self.assertIn("Send Prism's error reports", p.test_error_label.text())
        self.assertIn("Privacy & data", p.test_error_label.text())

    def test_switched_off_after_the_page_was_built_the_click_records_nothing_and_says_so(self):
        p = self.panel("more")
        self.assertTrue(p.test_error_btn.isEnabled())
        pulse.configure({"pulse_enabled": False})
        with mock.patch.object(pulse, "flush") as fl:
            self.press(p)
        fl.assert_not_called()
        self.assertEqual([], self.queued())
        self.assertIn("Privacy & data", p.test_error_label.text())
        self.assertNotIn("Sent", p.test_error_label.text())

    def test_the_work_function_reports_each_reason_and_sends_nothing(self):
        pulse.configure({"pulse_enabled": False})
        self.assertEqual(("off_setting", 0), pulse.send_test_error())
        pulse.configure({})
        with mock.patch.dict(os.environ, {"PRISM_PULSE": ""}), mock.patch("paths.is_frozen", lambda: False):
            self.assertEqual(("off_source", 0), pulse.send_test_error())
        self.assertEqual([], self.queued())


class TheAnswerIsOnlyAsGoodAsFlush(Base):
    def setUp(self):
        super().setUp()
        self.channel("dev")

    def test_sent_only_when_flush_delivered_at_least_one(self):
        with mock.patch.object(pulse, "flush_async"):
            for delivered, want in ((0, ("saved", 0)), (1, ("sent", 1)), (3, ("sent", 3))):
                with mock.patch.object(pulse, "flush", return_value=delivered):
                    self.assertEqual(want, pulse.send_test_error(), delivered)


# ── source and build guards ───────────────────────────────────────────────
def _py_files():
    skip = {".git", ".venv", "venv", "prism_terminal", "tests", "__pycache__", "node_modules",
            "dist", "build"}
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for f in files:
            if f.endswith(".py"):
                yield os.path.relpath(os.path.join(base, f), ROOT).replace(os.sep, "/")


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


WHY = ("The test-error action must stay reachable only from the dev-only card in "
       "Settings. If you added a menu item, shortcut, flag or other caller, remove it: "
       "a production customer must never be able to send a fake error to our Discord.")


class Guards(unittest.TestCase):
    def test_the_committed_channel_is_prod(self):
        tree = ast.parse(_read("channel.py"))
        values = [n.value.value for n in tree.body if isinstance(n, ast.Assign)
                  and any(getattr(t, "id", "") == "CHANNEL" for t in n.targets)]
        self.assertEqual(["prod"], values, "channel.py must ship \"prod\"; only the dev build rewrites it")

    def _files_naming(self, name):
        return sorted(f for f in _py_files() if re.search(rf"\b{name}\b", _read(f)))

    def test_the_work_function_is_named_only_by_pulse_and_its_worker(self):
        self.assertEqual(["pulse.py", "workers.py"], self._files_naming("send_test_error"), WHY)

    def test_the_worker_is_named_only_by_workers_and_the_settings_card(self):
        self.assertEqual(["widgets/settings_panel.py", "workers.py"],
                         self._files_naming("SendTestErrorWorker"), WHY)

    def test_the_error_class_and_the_card_live_in_one_file_each(self):
        self.assertEqual(["pulse.py"], self._files_naming("PulseTestError"), WHY)
        self.assertEqual(["widgets/settings_panel.py"], self._files_naming("_test_error_card"), WHY)
        self.assertEqual(["widgets/settings_panel.py"], self._files_naming("_send_test_error"), WHY)

    def test_inside_the_panel_the_button_is_the_only_caller_and_the_card_is_built_under_is_dev(self):
        src = _read("widgets/settings_panel.py")
        self.assertEqual(1, src.count("self._send_test_error"), WHY)       # the button's on_click, nothing else
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "_test_error_card"]
        self.assertEqual(1, len(calls), WHY)
        guarded = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and _is_dev_call(node.test):
                guarded += [c for c in ast.walk(node) if c is calls[0]]
        self.assertEqual(1, len(guarded), "the card must be built only inside `if channel.is_dev():`")

    def test_the_work_function_is_gated_by_channel_is_dev_and_not_by_the_environment(self):
        tree = ast.parse(_read("pulse.py"))
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "send_test_error")
        ifs = [n for n in fn.body if isinstance(n, ast.If)]
        self.assertTrue(ifs and _is_not_dev_call(ifs[0].test),
                        "the first check in send_test_error must be `if not channel.is_dev():`")
        self.assertIsInstance(ifs[0].body[0], ast.Return)
        text = ast.get_source_segment(_read("pulse.py"), fn)
        for banned in ("environ", "getenv", "argv", "sys.flags"):
            self.assertNotIn(banned, text, f"send_test_error reads {banned}; the gate is channel.is_dev() only")
        # the same for the card's creation site in the panel
        panel = _read("widgets/settings_panel.py")
        more = ast.get_source_segment(panel, next(n for n in ast.walk(ast.parse(panel))
                                                  if isinstance(n, ast.FunctionDef) and n.name == "_more"))
        for banned in ("environ", "getenv"):
            self.assertNotIn(banned, more)

    def test_no_environment_variable_or_flag_names_the_action(self):
        for rel in _py_files():
            for line in _read(rel).splitlines():
                low = line.lower()
                if ("environ" in low or "getenv" in low or "argv" in low or "add_argument" in low) \
                        and "test_error" in low:
                    self.fail(f"{rel}: {line.strip()!r} -- {WHY}")

    def test_is_dev_is_the_one_check_so_a_real_prod_build_has_no_card(self):
        # channel.is_dev is a plain comparison with the baked constant
        with mock.patch.object(channel, "CHANNEL", "prod"):
            self.assertFalse(channel.is_dev())
        with mock.patch.object(channel, "CHANNEL", "dev"):
            self.assertTrue(channel.is_dev())


def _dotted(node):
    return ast.unparse(node) if isinstance(node, ast.AST) else ""


def _is_dev_call(test):
    return isinstance(test, ast.Call) and _dotted(test.func) == "channel.is_dev"


def _is_not_dev_call(test):
    return isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not) and _is_dev_call(test.operand)


if __name__ == "__main__":
    unittest.main()
