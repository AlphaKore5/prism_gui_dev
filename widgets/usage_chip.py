"""UsageChip: credits left and what this run cost, display only.

Direction A ("meter first") of artifacts/openrouter-usage-artifacts/index.html:
a big number, a thin bar, one quiet line. It draws numbers it is GIVEN and
never works anything out, never calls a network, never writes anywhere.

The numbers come from a provider, a function that takes no arguments and
returns a `Usage`, or None when Prism has no AI server to ask yet. None (and
any error the provider raises) hides the chip completely: until the server
exists there is nothing to show, and the app must not invent a number.

    chip = UsageChip()                      # uses the app-wide provider
    chip = UsageChip(provider=my_function)  # or one of its own
    chip.refresh()                          # ask again, e.g. after a run

`set_provider()` is the single place the server work will plug in later;
until then the default provider is "none connected".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

import i18n

RECHECK_MS = 45_000        # how often the app-wide provider is asked again
FIRST_RECHECK_MS = 2_500
LOW_FRACTION = 0.2          # at or under a fifth of the period's credits, say so


@dataclass(frozen=True)
class Usage:
    """What the server told us. Every field after `credits_left` is optional:
    show what is known, leave out what is not."""
    credits_left: int
    credits_total: Optional[int] = None     # this period's allowance, for the bar
    run_cost: Optional[int] = None          # credits the run in front of the person used
    renews: str = ""                        # already-worded, e.g. "Renews in 12 days"

    @property
    def low(self) -> bool:
        if self.credits_total:
            return self.credits_left <= self.credits_total * LOW_FRACTION
        return False


Provider = Callable[[], Optional[Usage]]


def _no_server() -> Optional[Usage]:
    return None


_default_provider: Provider = _no_server


def set_provider(provider: Optional[Provider]) -> None:
    """Install the app-wide provider (None puts it back to "no server")."""
    global _default_provider
    _default_provider = provider or _no_server


_opener: Optional[Callable[[], None]] = None


def set_opener(fn: Optional[Callable[[], None]]) -> None:
    """What a click on any chip does: the app opens Settings > Usage."""
    global _opener
    _opener = fn


class UsageChip(QFrame):
    def mousePressEvent(self, event):
        if _opener is not None and event.button() == Qt.LeftButton:
            _opener()
        else:
            super().mousePressEvent(event)

    def __init__(self, provider: Optional[Provider] = None, parent=None):
        super().__init__(parent)
        self.setObjectName("usageChip")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._provider = provider
        col = QVBoxLayout(self)
        col.setContentsMargins(12, 8, 12, 8)
        col.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.number = QLabel("")
        self.number.setObjectName("usageChipNumber")
        self.caption = QLabel(i18n.t("credits left"))
        self.caption.setObjectName("usageChipCaption")
        top.addWidget(self.number)
        top.addWidget(self.caption)
        top.addStretch(1)
        self.run = QLabel("")
        self.run.setObjectName("usageChipCaption")
        top.addWidget(self.run)
        col.addLayout(top)
        self.bar = QProgressBar()
        self.bar.setObjectName("usageChipBar")
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(5)
        self.bar.setRange(0, 1000)
        col.addWidget(self.bar)
        self.note = QLabel("")
        self.note.setObjectName("usageChipCaption")
        col.addWidget(self.note)
        self.setAccessibleName(i18n.t("Credits"))
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(i18n.t("See your usage"))
        self.refresh()
        # The app-wide provider answers from a cache it fills in the
        # background, so the first draw can be empty; ask again shortly, then
        # now and then. A chip with its own provider (tests) is not re-asked.
        if provider is None:
            self._again = QTimer(self)
            self._again.setInterval(RECHECK_MS)
            self._again.timeout.connect(self.refresh)
            self._again.start()
            QTimer.singleShot(FIRST_RECHECK_MS, self._first_recheck)

    def _first_recheck(self) -> None:
        try:
            self.refresh()
        except RuntimeError:        # the chip was closed before the timer fired
            pass

    def refresh(self) -> None:
        """Ask the provider again and redraw. Hidden when there is no answer."""
        try:
            usage = (self._provider or _default_provider)()
        except Exception:                                   # noqa: BLE001
            usage = None            # display only: a failing provider means "nothing to show"
        self._show(usage)

    def _show(self, usage: Optional[Usage]) -> None:
        if usage is None:
            self.setVisible(False)
            return
        self.number.setText(f"{usage.credits_left:,}")
        self.run.setText(i18n.t("This run: {n} credits").format(n=f"{usage.run_cost:,}")
                         if usage.run_cost is not None else "")
        self.run.setVisible(usage.run_cost is not None)
        has_bar = bool(usage.credits_total)
        self.bar.setVisible(has_bar)
        if has_bar:
            self.bar.setValue(max(0, min(1000, round(1000 * usage.credits_left / usage.credits_total))))
        low = usage.low
        self.note.setText(i18n.t("Running low. Nothing runs without credits; your files are safe.")
                          if low else usage.renews)
        self.note.setVisible(bool(self.note.text()))
        for w in (self, self.bar):          # a style sheet does not see an ancestor's property
            w.setProperty("low", low)
            w.style().unpolish(w)
            w.style().polish(w)
        self.setVisible(True)
