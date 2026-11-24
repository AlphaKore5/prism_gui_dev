"""The leak check itself, and the suite setting that keeps real library
imports off background threads (see tests/leakcheck.py, tests/conftest.py)."""
from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import leakcheck  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TheCheckSeesWhatIsStillRunning(unittest.TestCase):
    def test_a_running_worker_is_named_and_a_finished_one_is_not(self):
        import workers
        release = threading.Event()

        class Stuck(workers._Worker):
            def run(self):
                release.wait(30)

        w = Stuck()
        w.start()
        try:
            self.assertEqual(leakcheck.leaks(wait=0), ["QThread Stuck"])
        finally:
            release.set()
            w.wait(10000)
        self.assertEqual(leakcheck.leaks(wait=0), [])

    def test_a_thread_that_can_stop_an_exit_is_named(self):
        release = threading.Event()
        t = threading.Thread(target=release.wait, args=(30,), name="stray", daemon=False)
        t.start()
        try:
            self.assertEqual(leakcheck.leaks(wait=0), ["thread 'stray' daemon=False"])
        finally:
            release.set()
            t.join(10)
        self.assertEqual(leakcheck.leaks(wait=0), [])

    def test_a_licensing_thread_is_named_even_though_it_is_a_daemon(self):
        release = threading.Event()
        t = threading.Thread(target=release.wait, args=(30,), name="prism-license-refresh", daemon=True)
        t.start()
        try:
            self.assertEqual(leakcheck.leaks(wait=0), ["thread 'prism-license-refresh' daemon=True"])
        finally:
            release.set()
            t.join(10)

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "child processes are read from /proc, which only Linux has")
    def test_a_child_process_is_named(self):
        import subprocess
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        try:
            found = leakcheck.leaks(wait=0)
            self.assertEqual(len(found), 1, found)
            self.assertIn(f"child process {p.pid}", found[0])
        finally:
            p.kill()
            p.wait()
        self.assertEqual(leakcheck.leaks(wait=0), [])


class NoTestStartsARealLibraryImportOnAThread(unittest.TestCase):
    """test_gates.py started 31 cadquery imports per run through the window's
    4 s warm-up timer. The suite switches that off; this fails if it comes back."""

    def test_the_windows_warm_up_starts_nothing_under_the_suite(self):
        import main_window
        started = []
        fake = types.SimpleNamespace(WARM_IMPORTS=("cadquery",), _workers=started)
        real = main_window.WarmImportsWorker
        main_window.WarmImportsWorker = lambda mods: types.SimpleNamespace(
            start=lambda: started.append(mods))
        try:
            main_window.MainWindow._warm_heavy_imports(fake)
        finally:
            main_window.WarmImportsWorker = real
        self.assertEqual(started, [])

    def test_the_warm_up_still_starts_its_worker_outside_the_suite(self):
        """So the switch above cannot hide a warm-up that is simply broken."""
        import main_window
        started = []
        fake = types.SimpleNamespace(WARM_IMPORTS=("cadquery",), _workers=started)
        real, was = main_window.WarmImportsWorker, os.environ.pop("PRISM_NO_WARM_IMPORTS")
        main_window.WarmImportsWorker = lambda mods: types.SimpleNamespace(
            start=lambda: started.append(("started", mods)))
        try:
            main_window.MainWindow._warm_heavy_imports(fake)
        finally:
            main_window.WarmImportsWorker = real
            os.environ["PRISM_NO_WARM_IMPORTS"] = was
        self.assertEqual(len(started), 2)       # the worker (fake._workers) and its start
