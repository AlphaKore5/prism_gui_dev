"""Python's cycle collector, run on the GUI thread only.

The collector runs on whichever thread happens to allocate when its counters
trip. A cycle that holds a Qt widget (a widget and a lambda connected to its
own signal, say) can therefore be freed on a worker thread, and Qt then
destroys a widget off the GUI thread: heap corruption on Windows (0xC0000374)
and access violations later. Seen in CI on 19-20 Nov 2026 with
"Garbage-collecting" on the stack inside a usage-fetching worker.

The usual cure for PySide/PyQt apps (pyqtgraph ships the same): switch the
automatic collector off and let a QTimer on the GUI thread collect, only when
gc's own thresholds say a collection is due, so the cost does not change.
"""
from __future__ import annotations

import gc

INTERVAL_MS = 1000
_timer = None


def collect_due() -> int:
    """Collect the generation gc itself would have collected now; 0 when
    nothing is due. Returns the number of objects found unreachable."""
    t0, t1, t2 = gc.get_threshold()
    c0, c1, c2 = gc.get_count()
    if c0 <= t0:
        return 0
    gen = 2 if (c1 > t1 and c2 > t2) else 1 if c1 > t1 else 0
    return gc.collect(gen)


def install(app, interval_ms: int = INTERVAL_MS):
    """Call once, on the GUI thread, after the QApplication exists."""
    global _timer
    from PySide6.QtCore import QTimer
    if _timer is not None:
        return _timer
    gc.disable()
    _timer = QTimer(app)
    _timer.setInterval(interval_ms)
    _timer.timeout.connect(collect_due)
    _timer.start()
    return _timer
