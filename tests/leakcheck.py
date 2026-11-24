"""What a test file leaves running when its last test ends.

A thread, a QThread or a child process still alive at the end of a file is
what can keep the process from exiting. On the Windows CI runner test_gates.py
passed every test and then sat 480 s until the runner killed it, and the
watchdog in conftest is cancelled during interpreter shutdown, so nothing
named the cause. `leaks()` names them while the tests are still running.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path


def _running_workers() -> list[str]:
    """Every workers._Worker QThread that is still running (rule 4: all
    Prism background QThreads are _Workers, and each anchors itself there)."""
    workers = sys.modules.get("workers")
    if workers is None:
        return []
    out = []
    for w in list(workers._running):
        try:
            if w.isRunning():
                out.append(f"QThread {type(w).__name__}")
        except RuntimeError:                       # C++ object already gone
            pass
    return out


def _threads() -> list[str]:
    """Python threads other than the main one that can stop an exit
    (non-daemon), and any thread of ours (the licensing refresh) still alive."""
    me = threading.current_thread()
    return [f"thread {t.name!r} daemon={t.daemon}" for t in threading.enumerate()
            if t is not me and t.is_alive() and (not t.daemon or t.name.startswith("prism-"))]


def _children() -> list[str]:
    """Child processes of this process. Read from /proc, so POSIX only."""
    proc = Path("/proc")
    if not proc.is_dir() or not sys.platform.startswith("linux"):
        return []
    me, out = os.getpid(), []
    for d in proc.iterdir():
        if d.name.isdigit():
            try:
                fields = (d / "stat").read_text().rsplit(")", 1)[1].split()
                if int(fields[1]) == me and fields[0] != "Z":
                    cmd = (d / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
                    out.append(f"child process {d.name}: {cmd[:100]}")
            except (OSError, IndexError, ValueError):
                pass
    return out


def leaks(wait: float = 10.0) -> list[str]:
    """What is still running, after giving it up to `wait` seconds to finish
    (a worker that was started a moment ago is not a leak, a stuck one is).
    Never runs the event loop."""
    deadline = time.monotonic() + wait
    while True:
        found = _running_workers() + _threads() + _children()
        if not found or time.monotonic() >= deadline:
            return found
        time.sleep(0.1)
