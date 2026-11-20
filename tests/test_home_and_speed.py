"""Stage 22: one submit from Home, and nothing on the UI thread waits on the network.

Real MainWindow, offscreen, throw-away HOME. The only doubles are the planner
(RouteWorker) and the licence answer; the navigation, the Task box, the attach
path and the sockets are the real ones.

Run on its own: python -m pytest tests/test_home_and_speed.py
"""
from __future__ import annotations

import os
import sys
import socket
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s22-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication                          # noqa: E402
_app = QApplication.instance() or QApplication([])

import licensing                                                    # noqa: E402
import main_window                                                  # noqa: E402
from main_window import MainWindow, COMPOSE, RUNNING               # noqa: E402

MAIN = threading.main_thread()


def _pump(ms=300):
    end = time.time() + ms / 1000
    while time.time() < end:
        _app.processEvents()
        time.sleep(0.01)


class MainThreadNetworkGuard:
    """Records any socket connect / DNS lookup made on the UI thread."""

    def __enter__(self):
        self.seen = []
        self._cc, self._sc, self._gai = (socket.create_connection,
                                         socket.socket.connect, socket.getaddrinfo)
        guard = self

        def note(kind, addr):
            if threading.current_thread() is MAIN:
                guard.seen.append((kind, str(addr)))

        def cc(addr, *a, **k):
            note("create_connection", addr)
            raise OSError("blocked by test")

        def sc(sock, addr):
            note("connect", addr)
            raise OSError("blocked by test")

        def gai(host, *a, **k):
            note("getaddrinfo", host)
            return guard._gai(host, *a, **k)
        socket.create_connection, socket.socket.connect, socket.getaddrinfo = cc, sc, gai
        return self

    def __exit__(self, *exc):
        socket.create_connection, socket.socket.connect, socket.getaddrinfo = (
            self._cc, self._sc, self._gai)


from PySide6.QtCore import QObject, Signal                          # noqa: E402


class _Plan(QObject):
    """RouteWorker stand-in: answers at once, on a real signal."""
    started = []
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, query, cfg, attachments):
        super().__init__()
        _Plan.started.append(query)

    def start(self):
        self.done.emit({"steps": [], "title": "t"})


def _window():
    with mock.patch.object(MainWindow, "_first_run"):
        win = MainWindow()
    win.cfg = dict(win.cfg or {})
    win.cfg.update({"api_key": "test", "onboarded": True,
                    "agents": {"content": "ChatGPT"}})
    return win


_WIN = []                     # one real window for the whole file (several in one process crash Qt)


class _Base(unittest.TestCase):
    def setUp(self):
        self._p = [mock.patch.object(licensing, "has", return_value=True),
                   mock.patch.object(licensing, "require", return_value=True)]
        for p in self._p:
            p.start()
        if not _WIN:
            _WIN.append(_window())
            _WIN[0].show()
        self.win = _WIN[0]
        # back to a quiet start
        self.win.__dict__.pop("_route", None)      # a test may have replaced it
        self.win.attachments.clear()
        self.win.input_panel.text.clear()
        self.win._run_finished = True
        self.win._attach_pending = 0
        self.win._route_when_attached = False
        self.win.work_stack.setCurrentIndex(COMPOSE)
        self.win.input_panel.set_state("empty")
        self.win.statusBar().clearMessage()
        self.win._show_screen("home")
        _app.processEvents()

    def tearDown(self):
        for p in self._p:
            p.stop()


class HomeSubmitIsOneTap(_Base):
    def _route_calls(self):
        calls = []
        self.win._route = lambda q: calls.append(q)
        return calls

    def test_submit_lands_on_the_task_and_plans_it_without_a_second_press(self):
        calls = self._route_calls()
        self.win._show_screen("home")
        self.win.home_panel._prompt_input.setText("make a reel about tea")
        self.win.home_panel._submit_home_task()
        self.assertEqual(self.win.screens.currentIndex(), main_window.SCREEN_INDEX["workbench"])
        self.assertEqual(self.win.work_stack.currentIndex(), COMPOSE)
        self.assertEqual(self.win.input_panel.text.toPlainText(), "make a reel about tea")
        self.assertEqual(calls, ["make a reel about tea"])     # planned once, not twice

    def _plan_for_real(self, submit):
        """The real planning path (RouteWorker faked to answer at once);
        returns how many times the run was started."""
        _Plan.started.clear()
        started = []
        with mock.patch.object(main_window, "RouteWorker", _Plan), \
                mock.patch.object(main_window, "AuthorizeWorker") as auth, \
                mock.patch.object(self.win, "_run_pipeline", lambda: started.append(1)):
            def fake_auth(feature, action):
                w = mock.MagicMock()
                w.start = lambda: self.win._start_route(
                    licensing.Authorization(True, run_id="r1"), self.win._last_query, w)
                w.done = mock.MagicMock()
                return w
            auth.side_effect = fake_auth
            submit()
            _pump(100)
        return started

    def test_home_send_plans_and_starts_the_work_with_no_stop_at_the_plan(self):
        """Owner, 19 Nov 2026: "dont stop at plan just sent it directly".
        Home's Send plans the task and starts it; the plan stays on screen
        as the run's steps."""
        def submit():
            self.win._show_screen("home")
            self.win.home_panel._prompt_input.setText("write a poem")
            self.win.home_panel._submit_home_task()
        started = self._plan_for_real(submit)
        self.assertEqual(_Plan.started, ["write a poem"])
        self.assertEqual(started, [1])
        self.assertFalse(self.win._start_when_planned)        # used up, never left armed

    def test_every_way_in_starts_the_work_once_planned(self):
        """Owner, 19 Nov 2026 (second word): the festival tip's Yes still
        stopped at the plan. Every route through _route() - the Task page,
        the festival tip, the Try chips, Commands - starts once planned."""
        started = self._plan_for_real(lambda: self.win._route("write a haiku"))
        self.assertEqual(_Plan.started, ["write a haiku"])
        self.assertEqual(started, [1])
        self.assertFalse(self.win._start_when_planned)

    def test_a_failed_home_plan_does_not_start_the_next_plan_by_itself(self):
        self.win._start_when_planned = True
        self.win._active_plan_worker = None
        with mock.patch.object(self.win, "sender", return_value=None), \
                mock.patch.object(self.win, "_explain"), \
                mock.patch.object(self.win, "_save_run"):
            self.win._on_route_failed("rate limited")
        self.assertFalse(self.win._start_when_planned)

    def test_empty_submit_goes_to_the_task_page_and_plans_nothing(self):
        calls = self._route_calls()
        self.win.home_panel._submit_home_task()
        self.assertEqual(self.win.screens.currentIndex(), main_window.SCREEN_INDEX["workbench"])
        self.assertEqual(calls, [])

    def test_a_run_in_flight_is_not_hidden_or_replanned(self):
        calls = self._route_calls()
        self.win._run_finished = False
        self.win.work_stack.setCurrentIndex(RUNNING)
        self.win._show_screen("home")
        self.win.home_panel._prompt_input.setText("another task")
        self.win.home_panel._submit_home_task()
        self.assertEqual(self.win.work_stack.currentIndex(), RUNNING)   # still the live run
        self.assertEqual(calls, [])
        self.assertIn("already running", self.win.statusBar().currentMessage())

    def test_tapping_tasks_in_the_rail_during_a_run_shows_the_run(self):
        self.win._run_finished = False
        self.win.work_stack.setCurrentIndex(RUNNING)
        self.win._show_screen("home")
        self.win._handle_command("workbench")
        self.assertEqual(self.win.work_stack.currentIndex(), RUNNING)

    def test_a_big_attachment_from_home_is_read_first_then_planned(self):
        calls = self._route_calls()
        big = os.path.join(_HOME, "big.txt")
        with open(big, "w") as f:
            f.write("x" * (main_window._ATTACH_INLINE_BYTES + 10))
        self.win.home_panel._prompt_input.setText("summarise it")
        self.win.home_panel._home_attachments.append(big)
        self.win.home_panel._submit_home_task()
        self.assertEqual(calls, [])                      # not yet: the file is being read
        for _ in range(100):
            _pump(50)
            if calls:
                break
        self.assertEqual(calls, ["summarise it"])
        self.assertEqual([a["path"] for a in self.win.attachments], [big])


class NoNetworkOnTheUiThread(_Base):
    def test_switching_every_page(self):
        with MainThreadNetworkGuard() as g:
            for name in ("home", "workbench", "runs", "artifacts", "guide", "support"):
                self.win._show_screen(name)
                _pump(30)
            self.win._open_settings("usage")
            _pump(100)
        self.assertEqual(g.seen, [])

    def test_opening_a_small_and_a_big_file(self):
        small = os.path.join(_HOME, "a.txt")
        big = os.path.join(_HOME, "b.txt")
        open(small, "w").write("hi")
        with open(big, "w") as f:
            f.write("y" * (main_window._ATTACH_INLINE_BYTES + 1))
        with MainThreadNetworkGuard() as g:
            self.win._attach_path(small)
            self.assertEqual(len(self.win.attachments), 1)      # instant, same turn
            self.win._attach_path(big)
            self.assertEqual(len(self.win.attachments), 1)      # big one is still being read
            for _ in range(100):
                _pump(30)
                if len(self.win.attachments) == 2:
                    break
        self.assertEqual(len(self.win.attachments), 2)
        self.assertEqual(g.seen, [])

    def test_a_big_file_never_blocks_the_ui_thread(self):
        big = os.path.join(_HOME, "slow.txt")
        with open(big, "w") as f:
            f.write("z" * (main_window._ATTACH_INLINE_BYTES + 1))
        real = main_window.CB.files.attach
        reader = []

        def slow(path):
            reader.append(threading.current_thread())
            time.sleep(0.5)
            return real(path)
        with mock.patch.object(main_window.CB.files, "attach", slow):
            t = time.perf_counter()
            self.win._attach_path(big)
            took = time.perf_counter() - t
            for _ in range(100):
                _pump(30)
                if self.win.attachments:
                    break
        self.assertLess(took, 0.25)                     # the click returned at once
        self.assertIsNot(reader[0], MAIN)               # the read ran on a worker
        self.assertEqual(len(self.win.attachments), 1)

    def test_home_submit_and_start(self):
        with MainThreadNetworkGuard() as g:
            self.win._show_screen("home")
            self.win.home_panel._prompt_input.setText("do a thing")
            with mock.patch.object(main_window, "AuthorizeWorker") as auth:
                auth.return_value = mock.MagicMock()
                self.win.home_panel._submit_home_task()
                _pump(50)
                # Start: the planner step builds and starts workers; none of that
                # may open a socket on this thread.
                self.win.routing = {"steps": []}
                try:
                    self.win._authorize_and_start({}, [], [])
                except Exception:
                    pass
                _pump(50)
        self.assertEqual(g.seen, [])

    def test_the_server_warm_up_runs_on_its_own_thread_and_is_throttled(self):
        import ai_server
        where = []
        fake = mock.MagicMock()
        fake.get = lambda url, timeout=0: where.append((threading.current_thread(), url))
        ai_server._warm["at"] = 0.0
        with mock.patch.dict(sys.modules, {"requests": fake}), \
                mock.patch.object(ai_server, "active", return_value=True):
            ai_server.warm_up()
            ai_server.warm_up()                         # inside the window: no second ping
            for _ in range(50):
                time.sleep(0.02)
                if where:
                    break
        self.assertEqual(len(where), 1)
        self.assertIsNot(where[0][0], MAIN)
        self.assertTrue(where[0][1].endswith("/health"))

    def test_no_warm_up_when_ai_is_not_through_the_server(self):
        import ai_server
        ai_server._warm["at"] = 0.0
        with mock.patch.object(ai_server, "active", return_value=False), \
                mock.patch("threading.Thread") as th:
            ai_server.warm_up()
        th.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class SlowLibrariesLoadInTheBackground(unittest.TestCase):
    """20 Nov 2026: STEP's first open took 1.9 s, 1.5 s of it import
    cadquery. It now loads on a worker a few seconds after start."""

    def test_the_worker_imports_what_it_is_given(self):
        import importlib
        import sys as _sys
        _sys.modules.pop("colorsys", None)
        w = main_window.WarmImportsWorker(("colorsys", "no_such_module_xyz"))
        w.run()                                          # a missing one is ignored
        self.assertIn("colorsys", _sys.modules)
        importlib.import_module("colorsys")

    def test_the_window_schedules_it_for_step(self):
        self.assertIn("cadquery", main_window.MainWindow.WARM_IMPORTS)
        self.assertGreater(main_window.MainWindow.WARM_IMPORTS_MS, 0)
        import workers as _w
        self.assertTrue(issubclass(main_window.WarmImportsWorker, _w._Worker))
