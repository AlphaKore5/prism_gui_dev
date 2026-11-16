"""The Leads & Outreach screen.

The whole workbench, in the window — not a launcher for a modal. The rail shows
this panel; the panel IS the surface: a page header (title + the run's batch
actions) over the tabbed cockpit (addons/leads/workbench.py), whose left rail
carries the search and whose results fill the rest. The heavy widget is built
the first time the screen is shown, so it costs nothing at startup (MainWindow
builds every screen up front).

`opened`, `navigate` and `open_run` stay as signals because MainWindow wires
them for every add-on panel; this one only ever emits `navigate` (the "AI tools"
shortcut). It never opens a modal — including the "?" in the header, which
slides addons/leads/help.py over the right of the body (F1 does the same) and
leaves the screen behind it usable while you read.

Two things float over the body, both children of it and neither in its layout:
that help panel, and the walkthrough (addons/leads/tour.py), which the panel's
"Show me on screen" button starts and `start_tour()` starts from code. Because
they float, `resizeEvent` is what keeps them the size of the body.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QVBoxLayout, QWidget

import i18n
from widgets import controls as C


class LeadsPanel(QWidget):
    TITLE = "Leads & Outreach"
    # One line, on purpose: PageHeader's subtitle does not wrap, so a long one
    # sets the window's minimum width and pushes a 1366px laptop sideways.
    BLURB = "Find, qualify and reach the right people — Prism drafts, you send."

    opened = Signal()               # kept for MainWindow's generic wiring
    navigate = Signal(str)          # "AI tools" → the agents screen
    open_run = Signal(str)          # kept for MainWindow's generic wiring

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._workbench = None
        self._help = None
        self._tour = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # The "?" comes FIRST, and is the only action here that is not about
        # the run: the team who asked for it were stuck before they had a run
        # at all, so it must not sit past two buttons they were afraid to press.
        self.help_btn = C.icon_button("help", i18n.t("What's on this screen (F1)"),
                                      on_click=self.toggle_help)
        # The app sheet pads every button in a page header 6px 14px (labelled
        # buttons); on this 34px glyph button that made it 64x48 beside the 34px
        # Credits, Export and Send buttons. Its own sheet outranks the header's;
        # a QSS min/max-width is the content box, so 32 + the 1px borders = 34.
        self.help_btn.setStyleSheet(
            "QPushButton#iconBtn{padding:0px;min-width:32px;max-width:32px;"
            "min-height:32px;max-height:32px;}")
        self.header = C.PageHeader(
            i18n.t(self.TITLE), i18n.t(self.BLURB), [self.help_btn])
        root.addWidget(self.header)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 13, 0, 0)       # the preview starts the card 30px under the header
        self._body_lay.setSpacing(0)
        root.addWidget(self._body, stretch=1)

        # F1 anywhere on this screen, whatever holds the focus — which is why
        # this is a WINDOW shortcut and not WidgetWithChildren: someone who has
        # just landed here has focus on nothing in particular, and that is
        # exactly the person pressing F1. Qt only fires a shortcut whose widget
        # is visible, and MainWindow's stack hides every screen but one, so
        # another screen's F1 (there is none today) would still be its own.
        ask = QShortcut(QKeySequence(Qt.Key_F1), self)
        ask.setContext(Qt.WindowShortcut)
        ask.activated.connect(self.toggle_help)

    # -- lifecycle --------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        # Re-read settings on every show. MainWindow swaps its cfg dict (first-run
        # wizard, Email → Change account, inquiry setup) without telling this
        # panel, which it built once at startup; a stale copy would miss the Groq
        # key and the sending account — and, saved back, would wipe them.
        try:
            import core_bridge as CB
            self.cfg = CB.config.load()
        except Exception:                                   # noqa: BLE001
            pass
        if self._workbench is None:
            self._build()
            # Land on the last run instead of an empty screen (loaded off the UI
            # thread; dropped if the user starts something first).
            self._workbench.restore_latest()
        else:
            self._workbench.cfg = self.cfg
            self._workbench.refresh_lists()

    def _build(self):
        # Imported lazily so the (prospector-adjacent) workbench never loads on a
        # startup where the screen is not opened.
        from addons.leads.workbench import LeadsWorkbench
        self._workbench = LeadsWorkbench(self.cfg, self)
        self._body_lay.addWidget(self._workbench)
        # The credit pool's balance, first: what every paid action below is
        # charged to. None when Leads runs on the developer's own keys.
        pill = self._workbench.credits_button()
        if pill is not None:
            self.header.add_action(pill)
        # Export sheets + Send all act on the whole run: page-level actions,
        # so they sit in the header, primary last.
        for button in self._workbench.action_buttons():
            self.header.add_action(button)

    def refresh(self):
        """A run or a saved list elsewhere should show here — re-scan on show."""
        if self._workbench is not None:
            self._workbench.refresh_lists()

    # -- help -------------------------------------------------------------------
    def help_panel(self):
        """The help panel, built on first ask. Lazy for the same reason the
        workbench is: most startups never open this screen, and none of them
        open the help."""
        if self._help is None:
            from addons.leads.help import LeadsHelp
            # Parented to the body, not to the panel: it covers the workbench
            # and leaves the header — and the "?" that opened it — in view.
            self._help = LeadsHelp(self._body)
            self._help.closed.connect(
                lambda: self.help_btn.setFocus(Qt.OtherFocusReason))
            self._help.tourRequested.connect(self.start_tour)
        return self._help

    def toggle_help(self):
        self.help_panel().toggle()

    # -- the walkthrough ----------------------------------------------------------
    def tour(self):
        """The coach-mark walkthrough, built on first ask — same laziness as
        the help panel, and for the same reason."""
        if self._tour is None:
            from addons.leads.tour import Guide, Tour
            # Over the body, like the help panel, so the header's "?" stays in
            # view. Guide walks the body for every part that answers
            # help_targets(): the workbench rail, its filter panel, the cockpit.
            self._tour = Tour(Guide(self._body), self._body)
            self._tour.finished.connect(
                lambda: self.help_btn.setFocus(Qt.OtherFocusReason))
        return self._tour

    def start_tour(self):
        """Walk the screen, ringing one control at a time and saying what it
        is. The help panel's primary button, and the way in from code."""
        if self._workbench is None:
            self._build()           # there is nothing to point at otherwise
        if self._help is not None and self._help.is_open():
            self._help.close_panel()        # the tour would open behind it
        walk = self.tour()
        walk.start()
        return walk

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Both of these float over the body rather than sitting in its layout,
        # so nothing re-places them for us when the window changes size.
        if self._help is not None and self._help.is_open():
            self._help.place()
        if self._tour is not None and self._tour.is_open():
            self._tour.place()
