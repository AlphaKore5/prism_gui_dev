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
