"""Run Prism and write down every window it opens, with what was under the mouse and where in the code it was shown.

For the bug that cannot be reproduced offscreen: "a small box appears when I click Companies". A menu, a tooltip, a
dialog and a stray widget are all top-level windows to Qt, and they look alike in a screenshot. This names each one.

    python devtools/window_trace.py              # Prism, as `python main.py` runs it
    python devtools/window_trace.py some_script.py   # any script that makes a QApplication (the tracer's own test)

It changes nothing about how Prism runs; it only watches. It uses YOUR ~/.prism, as `python main.py` does, so run it
yourself, not from a script. The log is ~/prism-test-logs/windows_trace.txt (a fresh file each run): click around, close
Prism, and read it. Each entry is one window that was shown:

    12:03:41.220  QMenu 'filtersMenu'  160x70 at (552,172)  text=''  under the mouse: QPushButton 'Companies'
        shown from: addons/leads/cockpit.py:3990 _select

Windows that are expected (the main window, a menu YOU opened, a dialog YOU asked for) are in the log too. What matters
is a window that appears when you did not ask for one.
"""
from __future__ import annotations

import os
import runpy
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(os.path.expanduser("~"), "prism-test-logs", "windows_trace.txt")


def _name(w) -> str:
    return f"{type(w).__name__} {w.objectName()!r}" if w is not None else "nothing"


def _text(w) -> str:
    for attr in ("text", "windowTitle"):
        fn = getattr(w, attr, None)
        if callable(fn):
            try:
                t = fn()
            except Exception:                                   # noqa: BLE001
                continue
            if isinstance(t, str) and t:
                return " ".join(t.split())[:120]
    return ""


def _where() -> str:
    """The first frames of Prism's own code on the stack: where the window was asked to show."""
    frames = [f for f in traceback.extract_stack()[:-3]
              if f.filename.startswith(ROOT) and "window_trace" not in f.filename]
    return "\n        ".join(f"{os.path.relpath(f.filename, ROOT)}:{f.lineno} {f.name}" for f in frames[-4:]) or "(Qt itself)"


def install(app) -> None:
    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication, QWidget

    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    out = open(LOG, "w", encoding="utf-8")
    out.write("Windows Prism showed. Each is one top-level window.\n\n")
    out.flush()

    class Tracer(QObject):
        def eventFilter(self, obj, event):                      # noqa: N802
            try:
                if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                    g = obj.geometry()
                    under = QApplication.widgetAt(QCursor.pos())
                    out.write(f"{time.strftime('%H:%M:%S')}.{int(time.time() * 1000) % 1000:03d}  {_name(obj)}  "
                              f"{g.width()}x{g.height()} at ({g.x()},{g.y()})  text={_text(obj)!r}  "
                              f"under the mouse: {_name(under)}\n        shown from: {_where()}\n")
                    out.flush()
            except Exception:                                   # noqa: BLE001 - a tracer must never break the app
                pass
            return False

    app._window_tracer = Tracer(app)
    app.installEventFilter(app._window_tracer)


def main() -> None:
    from PySide6.QtWidgets import QApplication
    original = QApplication.__init__

    def init(self, *args, **kwargs):
        original(self, *args, **kwargs)
        install(self)

    QApplication.__init__ = init
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "main.py")
    sys.path.insert(0, os.path.dirname(os.path.abspath(target)))
    sys.argv = [target] + sys.argv[2:]
    runpy.run_path(target, run_name="__main__")


if __name__ == "__main__":
    main()
