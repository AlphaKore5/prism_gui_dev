"""Scrolling a page must not change the drop-down or number box under the pointer (widgets/wheel_guard.py).

Events are sent directly: no processEvents()/exec()/QEventLoop, and nothing touches the real ~/.prism.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QLabel, QScrollArea, QSpinBox, QVBoxLayout,  # noqa: E402
                               QWidget)

from widgets import wheel_guard  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _wheel(down: bool = True) -> QWheelEvent:
    return QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, -120 if down else 120), Qt.NoButton, Qt.NoModifier,
                       Qt.NoScrollPhase, False)


@pytest.fixture
def page():
    """A tall form in a scroll area with a drop-down and a number box in it."""
    guard = wheel_guard.install(_app)
    scroll = QScrollArea()
    host = QWidget()
    col = QVBoxLayout(host)
    combo = QComboBox()
    combo.addItems(["one", "two", "three"])
    spin = QSpinBox()
    spin.setRange(0, 100)
    spin.setValue(10)
    col.addWidget(combo)
    col.addWidget(spin)
    for i in range(40):
        col.addWidget(QLabel("row %d" % i))
    host.adjustSize()                       # the page is taller than the window, so there is something to scroll
    scroll.setWidget(host)
    scroll.resize(400, 200)
    scroll.show()
    assert scroll.verticalScrollBar().maximum() > 0
    yield scroll, combo, spin
    _app.removeEventFilter(guard)
    scroll.close()


def test_the_wheel_over_a_drop_down_scrolls_the_page_and_leaves_the_choice(page):
    scroll, combo, _spin = page
    before = scroll.verticalScrollBar().value()
    _app.sendEvent(combo, _wheel())
    assert combo.currentIndex() == 0
    assert scroll.verticalScrollBar().value() > before


def test_a_number_box_that_was_not_clicked_into_leaves_its_value_and_the_page_scrolls(page):
    scroll, _combo, spin = page
    spin.clearFocus()
    before = scroll.verticalScrollBar().value()
    _app.sendEvent(spin, _wheel())
    assert spin.value() == 10
    assert scroll.verticalScrollBar().value() > before


class _Focused(QSpinBox):
    """Stands in for a box someone has clicked into: the offscreen platform gives no widget the keyboard focus."""

    def hasFocus(self):
        return True


def test_a_number_box_with_the_keyboard_focus_still_takes_the_wheel():
    guard = wheel_guard.install(_app)
    try:
        spin = _Focused()
        spin.setRange(0, 100)
        spin.setValue(10)
        _app.sendEvent(spin, _wheel(down=False))
        assert spin.value() == 11
    finally:
        _app.removeEventFilter(guard)


def test_a_drop_down_with_no_page_behind_it_is_still_left_alone():
    guard = wheel_guard.install(_app)
    try:
        combo = QComboBox()
        combo.addItems(["one", "two"])
        _app.sendEvent(combo, _wheel())
        assert combo.currentIndex() == 0
    finally:
        _app.removeEventFilter(guard)
