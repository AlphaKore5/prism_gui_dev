"""An answer uses its whole reading column (MAX_BUBBLE), not its minimum.

19 Nov 2026, real server answer on a 1440 px window: the answer card sat at
its 420 px minimum because the row's stretch spacer took every spare pixel
first, so a long answer read as a narrow strip. A short message of yours
still hugs its text on the right.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget  # noqa: E402

from widgets import chat_thread as CT                             # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
LONG = "Prefabricate duct in the shop, not in the field. " * 30


def _laid_out(row):
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(row)
    host.resize(1100, 900)
    host.show()
    for _ in range(5):
        _app.processEvents()
    return host


def test_a_long_answer_fills_its_reading_column():
    row, bubble = CT.answer_row(LONG, by="Prism AI")
    host = _laid_out(row)
    assert bubble.width() == CT.MAX_BUBBLE, bubble.width()
    host.close()


def test_an_answer_never_passes_the_column_on_a_wide_window():
    row, bubble = CT.answer_row(LONG)
    host = _laid_out(row)
    host.resize(2400, 900)
    for _ in range(5):
        _app.processEvents()
    assert bubble.width() <= CT.MAX_BUBBLE
    host.close()


def test_a_short_message_of_yours_still_hugs_its_text():
    row, bubble = CT.user_row("Make it a table.")
    host = _laid_out(row)
    assert bubble.width() < 400, bubble.width()
    host.close()
