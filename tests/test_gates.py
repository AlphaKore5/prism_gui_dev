"""Do the locks actually lock?

The unit tests in test_licensing.py prove the licence *state* is computed
correctly. These prove the app acts on it — that a locked add-on does not open,
that an expired licence stops new work, and that a routed paid agent cannot
sneak past the rail.

That distinction matters: every one of these would still pass its state test
while the dialog opened anyway, because the gate is a separate line of code
from the thing it guards.

Qt runs offscreen; no window is ever shown.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "devtools"))

from cryptography.hazmat.primitives import serialization as _ser  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: E402
    Ed25519PrivateKey)
from PySide6.QtWidgets import QApplication  # noqa: E402

import licensing  # noqa: E402
import mint  # noqa: E402
from licensing import device, keys, store  # noqa: E402

DAY = 86400
_app = QApplication.instance() or QApplication([])


# ── keep the test suite out of the developer's own run history ──────────────
# These tests drive a real MainWindow, and several of them call _on_run_failed
# to prove a broken run is still recorded. That record is written with
# config.save_run(), which writes to ~/.prism/runs — the REAL one.
#
# Found by counting: 55 of the 127 files in a working ~/.prism/runs were fake
# "Chrome would not launch" failures left by this file. Nearly half of
# somebody's History was test litter, and because those records carry no query
# they looked exactly like real runs whose prompt had been lost — which is a
# far more alarming thing to believe than the truth.
#
# Redirected for the whole module rather than per-test: the next person to add
# a test here will not remember, and should not have to.
#
# BOTH doors have to be shut. config.RUNS_DIR is only the CLI's default —
# MainWindow._save_run passes an explicit folder from workspace.runs_dir(), so
# patching the constant alone still let one file through. Verified by counting
# ~/.prism/runs before and after the suite.
import core_bridge as _CB  # noqa: E402
import workspace as _WS  # noqa: E402

_REAL_RUNS_DIR = _CB.config.RUNS_DIR
_REAL_RUNS_FN = _WS.runs_dir
_SCRATCH_RUNS = tempfile.mkdtemp(prefix="prism-test-runs-")


def setUpModule():
    _CB.config.RUNS_DIR = _SCRATCH_RUNS
    _WS.runs_dir = lambda *a, **kw: _SCRATCH_RUNS


def tearDownModule():
    _CB.config.RUNS_DIR = _REAL_RUNS_DIR
    _WS.runs_dir = _REAL_RUNS_FN


class GateTest(unittest.TestCase):
    """Shared harness: a temp ~/.prism and a throwaway signing key."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-gate-")
        self.private = Ed25519PrivateKey.generate()
        public = self.private.public_key().public_bytes(
            _ser.Encoding.Raw, _ser.PublicFormat.Raw).hex()
        device.reset_cache()
        self.patches = [
            mock.patch.object(licensing, "user_dir", return_value=self.tmp),
            mock.patch.object(keys, "public_keys", return_value={"t": public}),
        ]
        for p in self.patches:
            p.start()
        self.paywalled: list[str] = []
        licensing.set_paywall_handler(
            lambda feature, parent, state: self.paywalled.append(feature))

    def tearDown(self):
        licensing.set_paywall_handler(None)
        for p in self.patches:
            p.stop()
        device.reset_cache()
        licensing.reload()

    def grant(self, features, *, days=10, kind="trial"):
        now = int(time.time())
        claims = {
            "kid": "t", "sub": "lic_t", "cust": "RS Infotech", "plan": kind,
            "kind": kind, "feat": list(features), "seats": 1,
            "dev": device.fingerprint(self.tmp)[0],
            "iat": now, "nbf": now, "exp": now + days * DAY,
            "lend": now + days * DAY, "grace": 0,
        }
        store.save(self.tmp, {"token": mint.sign(claims, self.private),
                              "license_id": "lic_t", "last_seen_utc": now})
        return licensing.reload()

    def _window(self):
        """A real MainWindow, with first-run stubbed — it would otherwise pop
        the setup wizard on a window that has no Groq key configured.

        The cfg is set EXPLICITLY afterwards, and that is not tidiness. A
        MainWindow reads ~/.prism/config.json, and nothing here redirects
        HOME — so these tests ran against whatever the developer happened to
        have configured. On a machine with a real config they passed; on one
        without, `_route_one` took its "Finish Setup first" branch and opened
        a blocking QMessageBox.warning, which in a headless run is a HANG.

        That is the hang README documented a mandatory `--deselect` for, and
        it is NOT the InquiryDialog modal fixed elsewhere on this branch —
        that fix made this test pass locally and left it hanging on CI, where
        there is no config to inherit. Found on the first Windows CI run.

        A test that asserts tasks are planned in turn has to start from a
        window that CAN plan, and say so itself rather than borrowing the
        answer from the machine.
        """
        import main_window
        with mock.patch.object(main_window.MainWindow, "_first_run"):
            win = main_window.MainWindow()
        win.cfg = dict(win.cfg or {})
        win.cfg.update({"api_key": "test-not-a-real-key", "onboarded": True,
                        "agents": {"content": "ChatGPT"}})
        return win

    def _instant_brief(self):
        """Replace PlanBriefWorker with something synchronous that hands the
        steps back unchanged -- the prompt rewrite is Groq on a thread, and
        these tests are about what happens after the person presses Start,
        not about the prompts' wording (tests/test_confirmed_plan.py)."""
        class _Instant:
            def __init__(self, query, cfg, steps, routing):
                self.steps = steps
                self._done = self._failed = None

            @property
            def done(self):
                outer = self

                class _Sig:
                    def connect(self, fn):
                        outer._done = fn
                return _Sig()

            @property
            def failed(self):
                class _Sig:
                    def connect(self, fn):
                        pass
                return _Sig()

            def start(self):
                if self._done:
                    self._done(list(self.steps))
        return _Instant

    def _instant_authorize(self, allowed=True, message=""):
        """Replace AuthorizeWorker with something synchronous.

        The real one is a QThread doing a network round trip. Left running,
        a test finishes while it is still alive and Qt tears the thread down
        underneath it — which segfaults the interpreter at exit rather than
        failing a test, and is miserable to trace back here.
        """
        import licensing

        class _Instant:
            def __init__(self, feature="core", action="run", parent=None):
                self._cb = None

            @property
            def done(self):
                outer = self

                class _Sig:
                    def connect(self, fn):
                        outer._cb = fn
                return _Sig()

            def start(self):
                if self._cb:
                    self._cb(licensing.Authorization(allowed, run_id="run_test",
                                                     message=message))
        return _Instant


class Entitlements(GateTest):
    def test_require_passes_what_is_owned(self):
        self.grant(["core", "boq"])
        self.assertTrue(licensing.require("boq"))
        self.assertEqual(self.paywalled, [])

    def test_require_blocks_and_pitches_what_is_not(self):
        self.grant(["core"])
        self.assertFalse(licensing.require("boq"))
        self.assertEqual(self.paywalled, ["boq"])

    def test_expired_licence_blocks_everything(self):
        self.grant(["core", "boq"], days=-1)
        self.assertFalse(licensing.require("core"))
        self.assertFalse(licensing.require("boq"))


class WindowGates(GateTest):
    """The real MainWindow methods, with the dialogs stubbed out so a failure
    to gate shows up as an attempted open rather than a hung modal."""

    def test_locked_addon_does_not_open_its_dialog(self):
        import main_window
        self.grant(["core"])            # no boq
        win = self._window()
        with mock.patch.object(main_window, "BoqDialog") as dialog:
            win._open_boq()
        dialog.assert_not_called()
        self.assertEqual(self.paywalled, ["boq"])

    def test_owned_addon_gets_past_the_gate(self):
        import main_window
        self.grant(["core", "boq"])
        win = self._window()
        # boq_available() is the dependency probe that runs *after* the gate;
        # stubbing it False stops the real dialog while still proving the
        # licence check let us through.
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(allowed=True)), \
             mock.patch.object(main_window.CB, "boq_available",
                               return_value=(False, "no ezdxf")), \
             mock.patch.object(main_window.QMessageBox, "information"):
            win._open_boq()
        self.assertEqual(self.paywalled, [])

    def test_owned_addon_still_blocked_when_the_server_is_unreachable(self):
        """No offline fallback: owning BOQ is not enough, the server has to
        say yes at the moment it is opened."""
        import main_window
        self.grant(["core", "boq"])
        win = self._window()
        with mock.patch.object(
                main_window, "AuthorizeWorker",
                self._instant_authorize(
                    allowed=False,
                    message="Prism couldn't reach the licence server.")), \
             mock.patch.object(main_window, "BoqDialog") as dialog, \
             mock.patch.object(main_window.QMessageBox, "warning") as warned:
            win._open_boq()
        dialog.assert_not_called()
        warned.assert_called_once()

    def test_email_gate(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "EmailComposeDialog") as dialog:
            win._open_email()
        dialog.assert_not_called()
        self.assertEqual(self.paywalled, ["email"])

    def test_expired_licence_blocks_planning(self):
        self.grant(["core"], days=-1)
        win = self._window()
        started = []
        with mock.patch.object(win, "_workers", started):
            win._route("build me a bill of quantities")
        self.assertEqual(started, [])       # no RouteWorker ever queued
        self.assertEqual(self.paywalled, ["core"])

    def test_banner_hidden_when_licence_is_healthy(self):
        self.grant(["core", "boq"])
        win = self._window()
        self.assertFalse(win.banner.isVisible())

    def test_banner_shown_when_licence_has_ended(self):
        self.grant(["core"], days=-1)
        win = self._window()
        self.assertTrue(win.banner.isVisibleTo(win))

    def test_sidebar_padlocks_what_is_not_owned(self):
        self.grant(["core", "boq"])
        win = self._window()
        gated = win.sidebar._gated
        self.assertTrue(gated["boq"][0].property("locked") in (False, None))
        self.assertTrue(gated["email"][0].property("locked"))
        # Locked, but still clickable — the click is the customer telling us
        # what they want, and it opens the pitch.
        self.assertTrue(gated["email"][0].isEnabled())


class GettingOut(GateTest):
    """A customer must be able to abandon work they no longer want.

    A run is tens of minutes of browser automation; before this the only exit
    was force-quitting the app, which threw away every step that had already
    finished.
    """

    def test_stop_asks_the_engine_to_wind_up(self):
        """Not a thread kill: the engine polls a flag and stops at a safe
        point, keeping finished steps and closing Chrome properly."""
        self.grant(["core"])
        win = self._window()

        stopped = []
        win._active_run = mock.Mock(
            isRunning=mock.Mock(return_value=True),
            stop=mock.Mock(side_effect=lambda: stopped.append(True)))
        win._stop_run()
        self.assertEqual(stopped, [True])

    def test_stop_is_harmless_when_nothing_is_running(self):
        self.grant(["core"])
        win = self._window()
        win._active_run = None
        win._stop_run()             # must not raise

    def test_stop_button_only_shows_while_running(self):
        self.grant(["core"])
        win = self._window()
        win.output_panel.set_running(True)
        self.assertTrue(win.output_panel.stop_btn.isVisibleTo(win.output_panel))
        win.output_panel.set_running(False)
        self.assertFalse(win.output_panel.stop_btn.isVisibleTo(win.output_panel))

    def test_stop_latches_so_a_second_click_does_nothing(self):
        self.grant(["core"])
        win = self._window()
        win.output_panel.set_running(True)
        win.output_panel._on_stop()
        self.assertFalse(win.output_panel.stop_btn.isEnabled())
        self.assertIn("Stopping", win.output_panel.stop_btn.text())

    def test_a_cancelled_run_keeps_what_finished(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win._stage_results = [{"stage": "brains", "agent": "Claude",
                               "text": "done", "url": "", "snippet": "s",
                               "ok": True}]
        win._active_run = mock.Mock(stopping=mock.Mock(return_value=True))
        with mock.patch.object(main_window, "CompletionDialog") as dialog, \
             mock.patch.object(win, "_save_run"):
            win._on_run_done({}, {})
        dialog.assert_called_once()          # the finished work is still shown

    def test_discard_clears_the_plan_but_keeps_attachments(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win.attachments = [{"path": "/tmp/x.dwg", "name": "x.dwg"}]
        with mock.patch.object(main_window.QMessageBox, "question",
                               return_value=main_window.QMessageBox.Yes):
            win._discard_plan()
        self.assertIsNone(win.routing)
        self.assertEqual(len(win.attachments), 1)   # explicit choices survive
        # ...and they are still SHOWN: the tray and the chips are drawn from
        # the list, and a first version kept the list but wiped both.
        self.assertEqual(win.files_panel.attached_count_value(), 1)
        self.assertEqual(win.input_panel._attachments_flow.count(), 1)

    def test_discard_can_be_backed_out_of(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        with mock.patch.object(main_window.QMessageBox, "question",
                               return_value=main_window.QMessageBox.Cancel):
            win._discard_plan()
        self.assertIsNotNone(win.routing)


class PlanningIsAuthorised(GateTest):
    """Planning is a Groq call — it costs tokens and every run starts with it,
    so it goes through the server like a run does."""

    def test_planning_asks_the_server(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(allowed=True)), \
             mock.patch.object(main_window, "RouteWorker") as router, \
             mock.patch.object(main_window.CB.config, "is_configured",
                               return_value=True):
            win._route("draw me a bill of quantities")
        router.assert_called_once()

    def test_planning_stops_when_the_server_says_no(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize(
                                   allowed=False, message="Licence ended.")), \
             mock.patch.object(main_window, "RouteWorker") as router, \
             mock.patch.object(main_window.QMessageBox, "warning") as warned, \
             mock.patch.object(main_window.CB.config, "is_configured",
                               return_value=True):
            win._route("draw me a bill of quantities")
        router.assert_not_called()
        warned.assert_called_once()


class RoutedAgentGate(GateTest):
    """Prism Reel can enter a plan through the router without the customer
    ever touching the rail, so the sidebar gate alone would leak it."""

    def test_locked_routed_agent_is_offered_as_a_drop(self):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])            # no reel
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"brains": "Claude",
                                             "media": "Prism Reel"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Yes), \
             mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize()), \
             mock.patch.object(main_window, "AutomationWorker") as worker:
            win._run_pipeline()

        self.assertTrue(worker.called, "the rest of the plan should still run")
        ran = worker.call_args[0][1]["agents"]
        self.assertNotIn("Prism Reel", ran.values())
        self.assertIn("Claude", ran.values())

    def test_declining_the_drop_shows_the_pitch(self):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"media": "Prism Studio"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Cancel), \
             mock.patch.object(main_window, "AutomationWorker") as worker:
            win._run_pipeline()

        worker.assert_not_called()
        self.assertEqual(self.paywalled, ["reel"])

    def test_declining_does_not_arm_the_queue_to_run_by_itself(self):
        """Cancel on a gate used to leave _auto_run set, so the NEXT task
        planned on the same surface started on its own instead of waiting
        for review (review finding 5, 2026-10-01)."""
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"
        self.assertFalse(win._auto_run)

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"media": "Prism Studio"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Cancel), \
             mock.patch.object(main_window, "AutomationWorker"):
            win._run_pipeline()

        self.assertFalse(win._auto_run)

    def test_accepting_the_drop_arms_the_queue(self):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make me a reel"

        with mock.patch.object(win.agents_panel, "selected_agents",
                               return_value={"brains": "Claude",
                                             "media": "Prism Reel"}), \
             mock.patch.object(main_window.QMessageBox, "question",
                               return_value=QMessageBox.Yes), \
             mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize()), \
             mock.patch.object(main_window, "AutomationWorker"):
            win._run_pipeline()

        self.assertTrue(win._auto_run)


class TaskQueue(GateTest):
    """The queue plans and runs tasks one at a time, and keeps each one's
    results apart so the completion window can report them per task."""

    def _queued(self, win, *tasks):
        for t in tasks:
            win.input_panel.set_query_text(t)
            win.input_panel._queue_current()

    def test_the_box_counts_as_the_last_task(self):
        self.grant(["core"])
        win = self._window()
        self._queued(win, "one", "two")
        win.input_panel.set_query_text("three")
        self.assertEqual(win.input_panel.tasks(), ["one", "two", "three"])

    def test_plan_button_survives_an_empty_box(self):
        """Add task clears the box; without a queued task counting, the very
        button Add task leads to would go dead."""
        self.grant(["core"])
        win = self._window()
        self._queued(win, "only task")
        self.assertEqual(win.input_panel.text.toPlainText(), "")
        self.assertTrue(win.input_panel.route_btn.isEnabled())

    def test_each_task_is_planned_in_turn(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        self._queued(win, "task one", "task two", "task three")

        planned, started = [], []

        def fake_route_worker(query, cfg, attachments):
            planned.append(query)
            return mock.MagicMock()

        with mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize()), \
             mock.patch.object(main_window, "RouteWorker",
                               side_effect=fake_route_worker):
            win._route("")
            self.assertEqual(planned, ["task one"])   # only the first, so far

            # Pretend the plan came back and the user pressed Start the work.
            win._auto_run = True
            for _ in range(3):
                win._last_query = win._task_queue[win._task_pos - 1]
                started.append(win._last_query)
                win._stage_results = [{"stage": "content", "agent": "Claude",
                                       "text": "x", "url": "", "ok": True}]
                win._record_task_run()
                if win._more_tasks():
                    win._advance_queue()

        self.assertEqual(started, ["task one", "task two", "task three"])
        self.assertEqual(planned, ["task one", "task two", "task three"])

    def test_results_are_kept_per_task(self):
        """_stage_results is wiped at the top of every run; the queue has to
        bank each task's stages before that happens."""
        self.grant(["core"])
        win = self._window()
        win._task_queue = ["a", "b"]

        win._task_pos = 1
        win._last_query = "a"
        win._stage_results = [{"stage": "content", "agent": "Claude", "ok": True}]
        win._record_task_run()

        win._task_pos = 2
        win._last_query = "b"
        win._stage_results = [{"stage": "research", "agent": "Apollo", "ok": True}]
        win._record_task_run()

        self.assertEqual([g["task"] for g in win._task_runs], ["a", "b"])
        self.assertEqual([g["stages"][0]["agent"] for g in win._task_runs],
                         ["Claude", "Apollo"])

    def test_a_failed_task_does_not_kill_the_queue(self):
        import main_window
        self.grant(["core"])
        win = self._window()
        win._task_queue = ["a", "b"]
        win._task_pos = 1
        win._auto_run = True
        with mock.patch.object(win, "_advance_queue") as advance, \
             mock.patch.object(main_window.QMessageBox, "warning") as warned:
            win._on_run_failed("Chrome would not launch")
        advance.assert_called_once()
        warned.assert_not_called()      # status bar, not a modal, mid-queue
        self.assertEqual(win._task_runs[0]["error"], "Chrome would not launch")

    def test_a_licence_refusal_stops_the_whole_queue(self):
        """One refusal will refuse every task behind it — firing the rest at
        the server would be pure noise."""
        import main_window
        self.grant(["core"])
        win = self._window()
        win._task_queue = ["a", "b", "c"]
        win._task_pos = 1
        with mock.patch.object(main_window.QMessageBox, "warning"), \
             mock.patch.object(win, "_finish_queue") as finish:
            win._start_run(licensing.Authorization(False, message="nope"), {})
        self.assertTrue(win._queue_stopped)
        self.assertFalse(win._more_tasks())
        finish.assert_called_once()

    def test_stopping_a_run_stops_the_queue(self):
        self.grant(["core"])
        win = self._window()
        win._task_queue = ["a", "b"]
        win._task_pos = 1
        win._active_run = mock.MagicMock(**{"stopping.return_value": True})
        with mock.patch.object(win, "_finish_queue") as finish, \
             mock.patch.object(win, "_save_run"):
            win._on_run_done({}, {})
        self.assertTrue(win._queue_stopped)
        finish.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Attachments(GateTest):
    """Attaching, and — the part that was missing — un-attaching.

    "Add folder" hands the engine the folder's individual FILES, because that
    is what it uploads. So there was no single thing representing the folder
    and no way to take one back out: undoing a fifteen-file folder meant
    fifteen selections, and until you had done all fifteen every tool in the
    run was still being sent them.
    """

    def _window(self):
        from main_window import MainWindow
        self.grant(["core"])
        return MainWindow()

    def _tmpfiles(self):
        import tempfile
        root = tempfile.mkdtemp(prefix="prism-att-")
        folder = os.path.join(root, "brand assets")
        os.makedirs(folder)
        for name in ("logo.png", "banner.png", "notes.txt"):
            with open(os.path.join(folder, name), "wb") as f:
                f.write(b"\x89PNG\r\n" if name.endswith(".png") else b"hi")
        loose = os.path.join(root, "spec.png")
        with open(loose, "wb") as f:
            f.write(b"\x89PNG\r\n")
        return loose, folder

    def test_a_png_attaches(self):
        """An image has no extractable text, which is exactly the case a
        text-first attach path gets wrong."""
        loose, _folder = self._tmpfiles()
        win = self._window()
        win._attach_path(loose)
        self.assertEqual([a["name"] for a in win.attachments], ["spec.png"])
        self.assertEqual(win.attachments[0]["kind"], "image")

    def test_a_folder_becomes_one_row_over_its_files(self):
        loose, folder = self._tmpfiles()
        win = self._window()
        win._attach_path(loose)
        win._attach_path(folder)
        # The tray is a column of controls.FileItem rows now rather than a
        # QListWidget, so a row's name and its "Folder · 3 files" line are two
        # fields instead of one string. Same assertion, read off both.
        rows = win.files_panel.attached_labels()
        details = win.files_panel.attached_details()
        self.assertIn("spec.png", rows)
        self.assertTrue(
            any("brand assets" in name and "3 files" in detail
                for name, detail in zip(rows, details)),
            list(zip(rows, details)))
        # The engine still receives the flat file list.
        self.assertEqual(len(win.attachments), 4)

    def test_detaching_a_folder_takes_all_of_it(self):
        loose, folder = self._tmpfiles()
        win = self._window()
        win._attach_path(loose)
        win._attach_path(folder)
        win._detach_folder(folder)
        self.assertEqual([a["name"] for a in win.attachments], ["spec.png"])

    def test_detaching_a_folder_leaves_a_loose_file_of_the_same_name(self):
        """A file attached on its own is not part of the folder group even if
        the folder holds one with the same name."""
        _loose, folder = self._tmpfiles()
        win = self._window()
        win._attach_path(os.path.join(folder, "logo.png"))   # on its own
        win._attach_path(folder)
        win._detach_folder(folder)
        self.assertEqual([a["name"] for a in win.attachments], ["logo.png"])
        self.assertNotIn("from_dir", win.attachments[0])

    def test_detach_all_empties_the_tray(self):
        loose, folder = self._tmpfiles()
        win = self._window()
        win._attach_path(loose)
        win._attach_path(folder)
        win._detach_all()
        self.assertEqual(win.attachments, [])
        self.assertEqual(win.files_panel.attached_count_value(), 0)

    def test_the_same_file_is_not_queued_twice(self):
        """Attaching a folder and then a file inside it used to send that file
        to every tool twice."""
        loose, folder = self._tmpfiles()
        win = self._window()
        win._attach_path(folder)
        win._attach_path(os.path.join(folder, "logo.png"))
        paths = [a["path"] for a in win.attachments]
        self.assertEqual(len(paths), len(set(paths)))

    def test_a_missing_file_reports_instead_of_failing_silently(self):
        """Failures go through _explain now, which shows the plain-English
        dialog rather than a raw QMessageBox."""
        win = self._window()
        with mock.patch.object(type(win), "_explain") as explained:
            win._attach_path("/no/such/file.png")
        self.assertTrue(explained.called)
        self.assertEqual(explained.call_args[0][1], "attach")
        self.assertEqual(win.attachments, [])


class UpdateBanner(GateTest):
    """Phase 0 of update-plan.md: the server's version advice becomes a
    banner, in the right place in the pecking order, and "Not now" is
    remembered per version. How the advice gets INTO the state is
    test_updater.py's job; this is what the window does with it."""

    def setUp(self):
        super().setUp()
        import workspace
        self.extra = [
            # The shared-folder banner reads the developer's real config.
            # Pinned to "reachable" so it cannot outrank the update banner
            # on one machine and not another.
            mock.patch.object(workspace, "unreachable", return_value=""),
            mock.patch.object(licensing.secretstore, "_keyring",
                              return_value=None),
        ]
        for p in self.extra:
            p.start()

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def _advised(self, **fields):
        """A valid licence whose server has said `fields` about versions."""
        self.grant(["core"])
        store.update(self.tmp, **fields)
        licensing.reload()
        return self._window()

    def test_a_newer_version_is_offered_and_can_wait(self):
        win = self._advised(latest_version="99.0.0")
        self.assertFalse(win.banner.isHidden())
        self.assertIn("99.0.0", win._banner_text.text())
        self.assertEqual(win._banner_btn.text(), "Download")
        self.assertFalse(win._banner_alt.isHidden())
        self.assertEqual(win._banner_alt.text(), "Not now")
        win._banner_alt_clicked()
        self.assertTrue(win.banner.isHidden())

    def test_the_same_or_an_older_version_is_not_offered(self):
        import app_meta
        for version in (app_meta.VERSION, "0.0.1", "", "garbage"):
            win = self._advised(latest_version=version)
            self.assertTrue(win.banner.isHidden(), version)

    def test_not_now_is_per_version(self):
        win = self._advised(latest_version="99.0.0")
        win._dismiss_update("99.0.0")
        self.assertTrue(win.banner.isHidden())
        # Still dismissed on the next launch…
        self.assertTrue(self._advised(latest_version="99.0.0")
                        .banner.isHidden())
        # …until a newer one comes along.
        self.assertFalse(self._advised(latest_version="99.1.0")
                         .banner.isHidden())

    def test_a_retired_build_is_told_to_update_and_cannot_wait(self):
        """Below MIN_CLIENT_VERSION the server already refuses leases. The
        banner says so in those words, with no "Not now" — waiting is not a
        thing the customer can do about it."""
        win = self._advised(min_supported_version="99.0.0",
                            latest_version="99.1.0")
        self.assertFalse(win.banner.isHidden())
        text = win._banner_text.text()
        self.assertIn("99.1.0", text)
        self.assertIn("continue", text)
        self.assertEqual(win._banner_btn.text(), "Download update")
        self.assertTrue(win._banner_alt.isHidden())
        win._banner_alt_clicked()                 # nothing to dismiss
        self.assertFalse(win.banner.isHidden())

    def test_a_licence_problem_outranks_an_update(self):
        """A nudge must never sit on top of a problem: an ended licence
        says "ended", whatever the server thinks about versions."""
        self.grant(["core"], days=-1)
        store.update(self.tmp, latest_version="99.0.0",
                     min_supported_version="99.0.0")
        licensing.reload()
        win = self._window()
        self.assertFalse(win.banner.isHidden())
        self.assertNotIn("99.0.0", win._banner_text.text())
        self.assertIn("ended", win._banner_text.text())
        self.assertEqual(win._banner_btn.text(), "Enter a licence key")

    def test_the_download_button_opens_the_fixed_address(self):
        import app_meta
        import main_window
        win = self._advised(latest_version="99.0.0")
        with mock.patch.object(main_window.QDesktopServices,
                               "openUrl") as opened:
            win._banner_clicked()
        self.assertTrue(opened.called)
        self.assertEqual(opened.call_args[0][0].toString(),
                         app_meta.DOWNLOAD_URL)

    def test_settings_offers_check_for_updates(self):
        from PySide6.QtWidgets import QPushButton
        win = self._advised()
        win.settings_panel.show_section("diagnostics")
        labels = [b.text() for b in win.settings_panel.findChildren(QPushButton)]
        self.assertIn("Check for updates", labels)

    def test_check_for_updates_lands_in_both_places(self):
        """The round trip runs on the licensing worker thread; its answer has
        to come back to the UI thread and redraw BOTH the settings page and
        the window's banner."""
        from PySide6.QtWidgets import QLabel
        from licensing import client
        win = self._advised()
        self.assertTrue(win.banner.isHidden())
        panel = win.settings_panel
        panel.show_section("diagnostics")
        with mock.patch.object(client, "_post",
                               return_value={"latest_version": "99.0.0"}):
            panel._check_for_updates()
            self.assertEqual(panel._update_check, "checking")
            for t in threading.enumerate():
                if t.name == "prism-license-refresh":
                    t.join(10)
            # The Signal was emitted on the worker thread; Qt queued it.
            for _ in range(40):
                _app.processEvents()
                if panel._update_check == "done":
                    break
                time.sleep(0.05)
        self.assertEqual(panel._update_check, "done")
        self.assertFalse(win.banner.isHidden())
        self.assertIn("99.0.0", win._banner_text.text())
        texts = [l.text() for l in panel.findChildren(QLabel)]
        self.assertTrue(any("99.0.0" in t for t in texts), texts)


class UnpromptedStepGate(GateTest):
    """A step ticked on by hand starts with no prompt behind it. Run as it
    stood, that was the 2026-09-07 reel run: a step that uploads the files,
    asks nothing, and waits the whole 300 s cap.

    The first fix asked the owner to DROP such a step. Since 788c29a Start the
    work instead writes a stage-tailored default prompt for it from the task
    (`ensure_prompts`), so it shows on the card, is editable, and the run
    carries it — nothing is asked and nothing is dropped. These tests pin that
    behaviour; the old "drop it?" dialog is unreachable because the same
    condition that would raise it is the one `ensure_prompts` has just fixed.
    Seen in the real plan panel, 1 Oct 2026 (before: no prompt on the card;
    after Start: "Find relevant contacts… for: <the task>")."""

    def _window_with_a_hand_ticked_step(self, agents=None, routing=None,
                                        tick="leads"):
        self.grant(["core"])
        win = self._window()
        win.routing = {"stages": {}}
        win._last_query = "make a reel for instagram for this brand"
        win.agents_panel.set_content(
            routing or {"leads": {"needed": False, "questions": []},
                        "content": {"needed": True,
                                    "questions": ["Write the script."]}},
            agents or {"leads": "ChatGPT", "content": "ChatGPT"},
            win._last_query)            # as main_window._on_routed passes it
        row = next(r for r in win.agents_panel.rows() if r.stage == tick)
        row.set_included(True)
        return win, row

    def _run(self, win, answer):
        import main_window
        from PySide6.QtWidgets import QMessageBox
        with mock.patch.object(main_window.QMessageBox, "question",
                               return_value=answer) as asked, \
             mock.patch.object(main_window, "AuthorizeWorker",
                               self._instant_authorize()), \
             mock.patch.object(main_window, "PlanBriefWorker",
                               self._instant_brief()), \
             mock.patch.object(main_window, "AutomationWorker") as worker:
            win._run_pipeline()
        return asked, worker

    def test_start_writes_a_prompt_naming_the_task_for_a_hand_ticked_step(self):
        win, row = self._window_with_a_hand_ticked_step()
        self.assertEqual(win.agents_panel.unprompted_steps(), ["Find the people"])
        win.agents_panel.ensure_prompts()
        self.assertEqual(win.agents_panel.unprompted_steps(), [])
        [prompt] = row.questions()
        self.assertIn("make a reel for instagram for this brand", prompt)

    def test_a_hand_ticked_step_runs_with_its_default_prompt_and_asks_nothing(self):
        from PySide6.QtWidgets import QMessageBox
        win, _ = self._window_with_a_hand_ticked_step()
        asked, worker = self._run(win, QMessageBox.Cancel)
        asked.assert_not_called()
        self.assertTrue(worker.called)
        stages = {s[0]: s[2] for s in worker.call_args.kwargs["custom_stages"]}
        self.assertIn("leads", stages)
        self.assertIn("make a reel for instagram", stages["leads"][0])
        self.assertIn("leads", worker.call_args[0][1]["agents"])

    def test_a_hand_ticked_picture_step_in_a_studio_reel_is_kept(self):
        """It used to be offered as a drop ("Prism Studio makes its own
        artwork"). Ticking it by hand is now taken as meant."""
        from PySide6.QtWidgets import QMessageBox
        import main_window
        win, _ = self._window_with_a_hand_ticked_step(
            agents={"visual": "ChatGPT", "content": "ChatGPT",
                    "media": "Prism Studio"},
            routing={"visual": {"needed": False, "questions": []},
                     "content": {"needed": True, "questions": ["Write it."]},
                     "media": {"needed": True, "questions": ["Film it."]}},
            tick="visual")
        with mock.patch.object(main_window.CB, "studio_available",
                               return_value=(True, "")):
            asked, worker = self._run(win, QMessageBox.Yes)
        # The only thing it may ask is the separate licence question for
        # Prism Studio — never "this step has no prompt".
        for call in asked.call_args_list:
            self.assertNotIn("no prompt", call[0][2])
        self.assertTrue(worker.called)
        self.assertNotIn("visual", worker.call_args.kwargs["skip_stages"])
        self.assertIn("visual",
                      [s[0] for s in worker.call_args.kwargs["custom_stages"]])

    def test_a_plan_with_a_prompt_on_every_step_asks_nothing(self):
        from PySide6.QtWidgets import QMessageBox
        win, leads = self._window_with_a_hand_ticked_step()
        leads.set_included(False)
        asked, worker = self._run(win, QMessageBox.Cancel)
        asked.assert_not_called()
        self.assertTrue(worker.called)

    def test_what_was_left_out_reaches_the_engine_by_name(self):
        """Unticking "Make the images" has to reach the engine, which inserts
        that stage itself — or the run puts it straight back (2026-09-07)."""
        from PySide6.QtWidgets import QMessageBox
        win, _ = self._window_with_a_hand_ticked_step(
            agents={"visual": "ChatGPT", "content": "ChatGPT",
                    "media": "Prism Studio"},
            routing={"visual": {"needed": True, "questions": ["Pictures."]},
                     "content": {"needed": True, "questions": ["Write it."]},
                     "media": {"needed": True, "questions": ["Film it."]}},
            tick="content")
        next(r for r in win.agents_panel.rows() if r.stage == "visual") \
            .set_included(False)
        import main_window
        with mock.patch.object(main_window.CB, "studio_available",
                               return_value=(True, "")):
            asked, worker = self._run(win, QMessageBox.Yes)
        self.assertTrue(worker.called)
        self.assertEqual(worker.call_args.kwargs["skip_stages"], ["visual"])
        self.assertNotIn("visual",
                         [s[0] for s in worker.call_args.kwargs["custom_stages"]])

    def test_a_hand_ticked_step_is_not_left_out_of_the_run(self):
        from PySide6.QtWidgets import QMessageBox
        win, _ = self._window_with_a_hand_ticked_step()      # leads, no prompt
        asked, worker = self._run(win, QMessageBox.Yes)
        self.assertNotIn("leads", worker.call_args.kwargs["skip_stages"])



class EnterMovesTheTaskOn(GateTest):
    """Enter does what the New task screen's main button does.

    "Make a plan" and "Start the work" could only be pressed with the mouse.
    A key nothing focused used reaches the window, which now acts on it. The
    cases that matter are the ones where it must NOT: typing in a box, a focused
    Discard button, a held-down key, and any screen but New task.
    """

    def _press(self, win, key=None, auto_repeat=False):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        event = QKeyEvent(QEvent.KeyPress, key or Qt.Key_Return, Qt.NoModifier,
                          "\r", auto_repeat, 1)
        win.keyPressEvent(event)
        return event.isAccepted()

    def _planned_window(self):
        """A window on New task with a plan on the bench and Start live."""
        win = self._window()
        win.show()
        self.addCleanup(win.close)
        win._show_screen("workbench")
        win.agents_panel.set_run_enabled(True)
        self.starts, self.discards = [], []
        win.agents_panel.run_btn.clicked.connect(lambda: self.starts.append(1))
        win.agents_panel.discard_btn.clicked.connect(lambda: self.discards.append(1))
        return win

    def _focused(self, widget):
        import main_window
        patcher = mock.patch.object(main_window.QApplication, "focusWidget",
                                    return_value=widget)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_enter_starts_the_work_once_there_is_a_plan(self):
        win = self._planned_window()
        self.assertTrue(win.agents_panel.run_btn.isVisible())
        self.assertTrue(self._press(win))
        self.assertEqual((self.starts, self.discards), ([1], []))

    def test_enter_on_a_focused_discard_button_discards_and_never_starts(self):
        from PySide6.QtWidgets import QMessageBox
        win = self._planned_window()
        self._focused(win.agents_panel.discard_btn)
        asked = []
        # Discard asks first; answering Cancel keeps the test off a real modal.
        with mock.patch.object(QMessageBox, "question",
                               side_effect=lambda *a, **k: asked.append(a[1]) or QMessageBox.Cancel):
            self.assertTrue(self._press(win))
        self.assertEqual((self.starts, self.discards), ([], [1]))
        self.assertEqual(asked, ["Discard these steps"])

    def test_enter_inside_a_text_box_is_left_to_the_box(self):
        win = self._planned_window()
        self._focused(win.input_panel.text)
        self.assertFalse(self._press(win))
        self.assertEqual(self.starts, [])

    def test_a_held_down_enter_does_not_repeat(self):
        win = self._planned_window()
        self.assertFalse(self._press(win, auto_repeat=True))
        self.assertEqual(self.starts, [])

    def test_a_modified_enter_is_not_ours(self):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        win = self._planned_window()
        win.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Return,
                                    Qt.ControlModifier, "\r"))
        self.assertEqual(self.starts, [])

    def test_other_keys_do_nothing(self):
        from PySide6.QtCore import Qt
        win = self._planned_window()
        self._press(win, key=Qt.Key_Space)
        self.assertEqual(self.starts, [])

    def test_enter_on_another_screen_starts_nothing(self):
        win = self._planned_window()
        win._show_screen("home")
        self.assertFalse(self._press(win))
        self.assertEqual(self.starts, [])

    def test_without_a_plan_enter_makes_the_plan_from_the_composer(self):
        win = self._window()
        win.show()
        self.addCleanup(win.close)
        win._show_screen("workbench")
        win.input_panel.text.setPlainText("Summarise this tender")
        planned = []
        win.input_panel.route_clicked.connect(planned.append)
        self.assertTrue(win.input_panel.route_btn.isEnabled())
        self.assertTrue(self._press(win))
        self.assertEqual(planned, ["Summarise this tender"])

    def test_enter_never_cancels_a_plan_in_progress(self):
        win = self._window()
        win.show()
        self.addCleanup(win.close)
        win._show_screen("workbench")
        win.input_panel.text.setPlainText("Summarise this tender")
        win.input_panel.set_busy(True)
        cancelled = []
        win.input_panel.cancel_route_clicked.connect(lambda: cancelled.append(1))
        self._press(win)
        self.assertEqual(cancelled, [])


class QuietUpdateBanner(GateTest):
    """A downloaded, verified update waits behind a banner; only the customer's
    "Restart now" applies it, and never while a task is running. The download,
    verification and re-verification are tests/test_e2e_update.py's job; this
    is what the window does with the result."""

    def setUp(self):
        super().setUp()
        import workspace
        self.extra = [
            mock.patch.object(workspace, "unreachable", return_value=""),
            mock.patch.object(licensing.secretstore, "_keyring", return_value=None),
        ]
        for p in self.extra:
            p.start()

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def _staged(self, version="99.0.0"):
        import updater
        return updater.StagedUpdate(version=version, stage_dir="/nonexistent/stage",
                                    manifest={})

    def _ready_window(self, version="99.0.0", **advised):
        self.grant(["core"])
        if advised:
            store.update(self.tmp, **advised)
            licensing.reload()
        win = self._window()
        win._on_quiet_update_ready(self._staged(version))
        return win

    def test_a_waiting_update_is_offered_with_restart_and_later(self):
        win = self._ready_window()
        self.assertFalse(win.banner.isHidden())
        self.assertIn("99.0.0", win._banner_text.text())
        self.assertIn("ready", win._banner_text.text())
        self.assertEqual(win._banner_btn.text(), "Restart now")
        self.assertEqual(win._banner_alt.text(), "Later")

    def test_it_replaces_the_plain_download_offer_for_the_same_release(self):
        win = self._ready_window(latest_version="99.0.0")
        self.assertEqual(win._banner_btn.text(), "Restart now")

    def test_a_licence_problem_still_outranks_it(self):
        self.grant(["core"], days=-1)
        win = self._window()
        win._on_quiet_update_ready(self._staged())
        self.assertIn("ended", win._banner_text.text())
        self.assertEqual(win._banner_btn.text(), "Enter a licence key")

    def test_later_hides_it_for_this_version_only(self):
        win = self._ready_window()
        win._later_ready_update()
        self.assertTrue(win.banner.isHidden())
        win._on_quiet_update_ready(self._staged("99.1.0"))
        self.assertFalse(win.banner.isHidden())

    def test_restart_now_applies_the_waiting_update_and_quits(self):
        import updater
        win = self._ready_window()
        with mock.patch.object(updater, "apply_ready") as apply, \
             mock.patch.object(QApplication, "quit") as quit_:
            win._banner_action()
        apply.assert_called_once_with()
        quit_.assert_called_once_with()

    def test_restart_waits_while_a_task_is_running(self):
        import main_window
        import updater
        win = self._ready_window()
        win._active_run = mock.Mock(isRunning=mock.Mock(return_value=True))
        with mock.patch.object(updater, "apply_ready") as apply, \
             mock.patch.object(QApplication, "quit") as quit_, \
             mock.patch.object(main_window.QMessageBox, "information") as told:
            win._banner_action()
        apply.assert_not_called()
        quit_.assert_not_called()
        told.assert_called_once()
        self.assertIsNotNone(win._ready_update, "the update keeps waiting")

    def test_an_update_that_fails_its_recheck_falls_back_to_the_download_page(self):
        import main_window
        import updater
        win = self._ready_window()
        with mock.patch.object(updater, "apply_ready",
                               side_effect=updater.UpdateError("changed")), \
             mock.patch.object(QApplication, "quit") as quit_, \
             mock.patch.object(main_window.QDesktopServices, "openUrl") as opened:
            win._banner_action()
        quit_.assert_not_called()
        opened.assert_called_once()
        self.assertIsNone(win._ready_update)

    def test_the_download_button_uses_a_waiting_update_instead_of_downloading(self):
        import paths
        import updater
        win = self._ready_window()
        with mock.patch.object(paths, "is_frozen", return_value=True), \
             mock.patch.object(updater, "apply_ready") as apply, \
             mock.patch.object(QApplication, "quit"):
            win._open_download()
        apply.assert_called_once_with()

    def test_a_source_run_never_starts_the_background_check(self):
        win = self._window()
        self.assertIsNone(win._quiet_worker)
        self.assertFalse(hasattr(win, "_quiet_timer"))

    def test_the_background_check_runs_one_worker_at_a_time(self):
        import main_window
        win = self._window()
        fake = mock.MagicMock()
        fake.isRunning.return_value = True
        with mock.patch.object(main_window, "QuietUpdateWorker",
                               return_value=fake) as made:
            win._quiet_update_check()
            win._quiet_update_check()            # still running: no second one
        made.assert_called_once_with()
        fake.start.assert_called_once_with()
        fake.ready.connect.assert_called_once()

    def test_no_background_check_while_an_update_is_already_waiting(self):
        import main_window
        win = self._ready_window()
        with mock.patch.object(main_window, "QuietUpdateWorker") as made:
            win._quiet_update_check()
        made.assert_not_called()

    def test_frozen_builds_schedule_the_check_and_report_on_the_licence_tick(self):
        import main_window
        import paths
        import updater
        with mock.patch.object(paths, "is_frozen", return_value=True), \
             mock.patch.object(main_window.QTimer, "singleShot") as single:
            win = self._window()
        self.assertTrue(hasattr(win, "_quiet_timer"))
        self.assertTrue(win._quiet_timer.isActive())
        self.assertIn(mock.call(win.QUIET_UPDATE_FIRST_MS, win._quiet_update_check),
                      single.call_args_list)
        with mock.patch.object(updater, "report_async") as report, \
             mock.patch.object(licensing, "refresh"):
            win._tick_licence()
        report.assert_called_once_with()
