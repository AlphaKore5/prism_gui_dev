"""gui_gc: the cycle collector runs on the GUI thread only (see gui_gc.py)."""
from __future__ import annotations

import gc
import os
import sys
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import gui_gc  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def test_install_turns_automatic_collection_off_and_times_it_on_the_gui_thread():
    was = gc.isenabled()
    try:
        timer = gui_gc.install(_app, interval_ms=50)
        assert not gc.isenabled()
        assert timer.isActive() and timer.thread() is _app.thread()
        assert gui_gc.install(_app) is timer             # once only
    finally:
        timer.stop()
        gui_gc._timer = None
        if was:
            gc.enable()


def test_a_cycle_is_collected_when_due_and_on_the_calling_thread():
    gc.disable()
    seen = []

    class Holder:
        def __del__(self):
            seen.append(threading.current_thread() is threading.main_thread())
    h = Holder()
    h.me = h                                           # a cycle
    del h
    old = gc.get_threshold()
    try:
        gc.set_threshold(1, 1, 1)
        for _ in range(5):
            [object() for _ in range(10)]               # trip the counters
        gui_gc.collect_due()
    finally:
        gc.set_threshold(*old)
    gc.collect()
    assert seen == [True]


def test_main_installs_it_right_after_the_application_is_made():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "main.py"), encoding="utf-8").read()
    i = src.index("app = QApplication(sys.argv)")
    assert "gui_gc.install(app)" in src[i:i + 300]
