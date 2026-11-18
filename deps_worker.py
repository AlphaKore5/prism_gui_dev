"""The background half of "Install it from Prism" (see deps.py)."""
from __future__ import annotations

import threading

from PySide6.QtCore import Signal

import deps
from workers import _Worker


class ComponentInstallWorker(_Worker):
    """Fetch one component off the UI thread. `consent` is required: the
    worker refuses to download without it, whoever started it."""
    progress = Signal(int, int)      # bytes done, bytes total (0 = unknown)
    note = Signal(str)               # a line of installer output
    done = Signal(str)               # "ok" or "cancelled"
    failed = Signal(str)             # a sentence for the customer

    def __init__(self, key: str, consent: bool, parent=None):
        super().__init__(parent)
        self.key, self.consent = key, consent
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            result = deps.install(
                self.key, self.consent,
                on_progress=lambda d, t: self.progress.emit(int(d), int(t)),
                cancelled=self._cancel.is_set,
                on_line=self.note.emit)
        except deps.DepsError as e:
            self.failed.emit(str(e))
            return
        except Exception as e:                        # noqa: BLE001
            self.failed.emit("Something went wrong while getting this part. "
                             f"Press Repair to try again. ({e})")
            return
        self.done.emit(result)
