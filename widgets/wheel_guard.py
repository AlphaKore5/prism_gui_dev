"""Scrolling a page must never change a field the pointer happens to rest on.

Qt lets the mouse wheel step a drop-down to its next option, and a number box up or down. On a long form that means a person
scrolling with the pointer over a "Category" or "Language" box changes it without noticing, and the page they wanted to move stays put.

One filter on the application fixes it everywhere, in this program and in any dialog added later:

  · a drop-down never reacts to the wheel. The wheel goes on to the page behind it, so the page scrolls.
  · a number or date box reacts only while it has the keyboard focus, which it gets by being clicked or tabbed into: a deliberate act.

The wheel inside an open drop-down list is untouched, as are lists, tables and text boxes.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QAbstractScrollArea, QAbstractSpinBox, QApplication, QComboBox, QWidget


def _owner(obj: QObject):
    """The drop-down or number box this widget is, or is the line edit of."""
    for w in (obj, obj.parent() if isinstance(obj, QWidget) else None):
        if isinstance(w, (QComboBox, QAbstractSpinBox)):
            return w
    return None


class WheelGuard(QObject):
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Wheel or not isinstance(obj, QWidget):
            return False
        owner = _owner(obj)
        if owner is None:
            return False
        if isinstance(owner, QAbstractSpinBox) and owner.hasFocus():
            return False
        _scroll_the_page(owner, event)
        return True


def _scroll_the_page(widget: QWidget, event) -> None:
    """Give the wheel to the nearest page behind the field that can use it, then the next one out. A page already at its end ignores
    the wheel, as Qt's own propagation would have let the next page have it."""
    area = widget.parentWidget()
    while area is not None:
        if isinstance(area, QAbstractScrollArea):
            event.ignore()
            QApplication.sendEvent(area.viewport(), event)
            if event.isAccepted():
                return
        area = area.parentWidget()
    event.ignore()


def install(app: QApplication) -> WheelGuard:
    guard = WheelGuard(app)
    app.installEventFilter(guard)
    return guard
