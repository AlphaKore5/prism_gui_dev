"""A WhatsApp list that is rebuilt must never flash its old rows up as windows of their own.

When a widget is added to a visible layout Qt queues a "show it if it is not hidden". If the row is detached (setParent(None)) before that
runs, it is parentless and not explicitly hidden, so the queued call shows it as a top-level window. Rebuilding a list that quickly (a poll
landing just after a load) put a window on screen for each row. Detaching must hide first.

Nothing here runs an event loop (no processEvents()/exec()/QEventLoop): the queued call is delivered by hand.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtCore import Qt, QMetaObject  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.whatsapp import template_editor as T, ui  # noqa: E402


def _row() -> QFrame:
    row = QFrame()
    QVBoxLayout(row).addWidget(QLabel("a template"))
    return row


@pytest.mark.parametrize("discard", [ui.discard, T.discard])
def test_a_row_discarded_right_after_it_was_added_never_becomes_a_window(discard):
    host = QWidget()
    col = QVBoxLayout(host)
    host.show()
    row = _row()
    col.addWidget(row)                       # queues "show if not hidden" on the row
    col.takeAt(0)
    discard(row)
    QMetaObject.invokeMethod(row, "_q_showIfNotHidden", Qt.DirectConnection)    # what the event loop delivers next
    assert not row.isVisible()
    host.close()


class _WindowWatch:
    """Records every top-level widget that is shown while it is installed."""

    def __init__(self):
        from PySide6.QtCore import QEvent, QObject

        outer = self

        class _Filter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Show and isinstance(obj, QWidget) and obj.isWindow():
                    outer.seen.append(type(obj).__name__)
                return False

        self.seen: list = []
        self._filter = _Filter()

    def __enter__(self):
        _app.installEventFilter(self._filter)
        return self

    def __exit__(self, *_):
        _app.removeEventFilter(self._filter)


def test_building_a_message_bubble_never_shows_a_window():
    # The bubble's text label was shown before it was placed in the bubble, so each message flashed a small window of its own while a
    # conversation loaded.
    from addons.whatsapp.thread import Bubble
    with _WindowWatch() as watch:
        for text in ("Hello there", "", "[template] order_ready_test"):
            Bubble({"direction": "in", "text": text, "created_at": "2026-11-03T12:09:00+0530", "status": "read"}, tail=True)
    assert watch.seen == []
