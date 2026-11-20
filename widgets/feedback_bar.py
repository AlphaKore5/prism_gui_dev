"""A thumbs up / thumbs down under a result, and nothing else.

Used wherever a run's result is really shown (the task conversation, the BOQ
dialog). A thumb is recorded through Pulse as a `feedback` event: which add-on,
which run, up or down, and for a thumbs down one of three plain reasons. No
free text is ever collected. Hidden when Pulse would record nothing (the
customer turned it off in Settings, or this is a source checkout), because a
button that does nothing is worse than no button.
"""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

import i18n
import pulse
import theme
from widgets import controls as C
from widgets import icons

_REASONS = (("wrong", "Wrong"), ("incomplete", "Incomplete"), ("slow", "Too slow"))


class FeedbackBar(QWidget):
    def __init__(self, addon: str, run_id: str, model: str = "", parent=None):
        super().__init__(parent)
        self.addon, self.run_id, self.model = addon, run_id, model
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        self.up_btn = self._thumb("thumb-up", "Good result", lambda: self._rate("up"))
        self.down_btn = self._thumb("thumb-down", "Not good", lambda: self._rate("down"))
        row.addWidget(self.up_btn)
        row.addWidget(self.down_btn)
        self.chips: dict[str, QPushButton] = {}
        for key, text in _REASONS:
            chip = C.button(i18n.t(text), "secondary", small=True,
                            on_click=lambda _=False, k=key: self._reason(k))
            chip.setVisible(False)
            self.chips[key] = chip
            row.addWidget(chip)
        self.thanks = C.label(i18n.t("Thanks"), level="SUPPORT")
        self.thanks.setVisible(False)
        row.addWidget(self.thanks)
        row.addStretch(1)
        self.setVisible(pulse.active())

    def _thumb(self, icon_name: str, tip: str, on_click) -> QPushButton:
        b = QPushButton()
        b.setFlat(True)
        b.setFixedSize(28, 28)
        b.setStyleSheet(f"QPushButton {{ border: none; background: transparent; border-radius: 6px; }}"
                        f" QPushButton:hover {{ background: {theme.WELL}; }}")
        b.setToolTip(i18n.t(tip))
        icons.button_icon(b, icon_name, 15, theme.MUTE)
        b.clicked.connect(lambda _=False: on_click())
        return b

    def _send(self, **kw) -> None:
        pulse.feedback(self.addon, self.run_id, model=self.model, **kw)

    def _rate(self, rating: str) -> None:
        self._send(rating=rating)
        for c in self.chips.values():
            c.setVisible(rating == "down")
        self.thanks.setVisible(rating == "up")

    def _reason(self, key: str) -> None:
        self._send(rating="down", reason=key)
        for c in self.chips.values():
            c.setVisible(False)
        self.thanks.setVisible(True)

    def mark(self, outcome: str) -> None:
        """What the person did next with the result (used / edited / redone)."""
        self._send(outcome=outcome)
