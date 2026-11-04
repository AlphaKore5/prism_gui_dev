"""The shared modal chrome. Every dialog in this package is built out of it.

Sixteen dialogs shipped with no base class between them, and it showed in the
only place it can: they each invented their own header band, their own footer,
and their own idea of which button was the important one. Four different
header recipes, five footer paddings, and three dialogs with two solid accent
buttons side by side — so on the screens where the product's real work happens
(first-run setup, licence activation, BOQ, Gerber, the register) there was no
answer to "what does this window want me to do next".

`PrismDialog` is the answer. Three bands, always in the same order:

    +---------------------------------------------------------+
    | HEADER    icon · title / subtitle                    [x] |  fixed
    +---------------------------------------------------------+
    | BODY      28px page padding, scrolls if it has to        |  scrolls
    +---------------------------------------------------------+
    | FOOTER    [destructive] [utility…]      [secondary] [ok] |  fixed
    +---------------------------------------------------------+

The footer is the part that carries the rule. Exactly one primary button per
dialog — `set_primary` raises if you ask for a second — secondary buttons
beside it, and anything destructive pushed to the far left of the bar, the
maximum distance the layout can put between "Deactivate this computer" and
"Save". A destructive action that sits next to the primary is a support call
waiting to happen.

What this deliberately does NOT do: change what any dialog *does*. Adopting it
is a chrome change. Every signal, every validation, every `accept()`/`reject()`
result value stays exactly where it was — these windows drive licence
activation, IMAP, Selenium and DXF parsing, and none of that is design's
business.

Tokens come from theme.py and components from widgets.controls; there is no
literal hex and no bare pixel size in this module, because the accent rotation
is a blunt string replace over eleven fixed hexes and an off-palette colour
written here would strand every dialog in the app on Prism blue in a green
profile.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

import i18n
import theme
from widgets import controls as C


class DialogHeader(QFrame):
    """The fixed band at the top of a dialog: optional glyph, title, subtitle,
    optional actions, optional close.

    Deliberately the same shape as `controls.PageHeader` — a dialog is a page
    that happens to float — but on the card surface rather than the canvas, so
    the three bands read as header / work / footer instead of as one flat
    sheet. PageHeader itself is not reused because a modal wants a leading
    glyph and a close affordance, and a screen wants neither.
    """

    def __init__(self, title: str, subtitle: str = "", icon: str = "",
                 actions: list = None, on_close=None, eyebrow: str = "",
                 leading: QWidget = None, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"#dialogHeader {{ background: {theme.CARD};"
            f" border: none; border-bottom: 1px solid {theme.HAIRLINE}; }}")

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                               theme.PAGE_PAD, theme.SPACE_4)
        row.setSpacing(theme.SPACE_4)

        # `leading` wins over `icon`: the licence and paywall sheets lead with
        # the real brand mark rather than a tinted glyph pad, because those two
        # are the surfaces where a customer is deciding whether to trust this
        # window with a key or with money.
        self.pad = leading
        if self.pad is None and icon:
            self.pad = C.IconPad(icon, theme.ACCENT, 38, theme.R_CONTROL, 19)
            # The preview's header tile: solid ink with a white glyph, not a
            # soft tint.
            self.pad.setPixmap(C.icons.pixmap(icon, 19, "#ffffff"))
            self.pad.setStyleSheet(
                f"background: {theme.INK}; border-radius: 12px;")
        if self.pad is not None:
            glyph_col = QVBoxLayout()
            glyph_col.setContentsMargins(0, 0, 0, 0)
            glyph_col.addWidget(self.pad)
            glyph_col.addStretch(1)
            row.addLayout(glyph_col)
            row.setSpacing(theme.SPACE_3)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.eyebrow = C.kicker(eyebrow, muted=True) if eyebrow else None
        if self.eyebrow is not None:
            col.addWidget(self.eyebrow)
        self.title = QLabel(title)
        self.title.setObjectName("pageTitle")
        C.track(self.title, -0.015)
        col.addWidget(self.title)
        # Parented at creation: setVisible below runs before col.addWidget, and
        # setVisible(True) on a parentless widget flashes it as a top-level OS
        # window — the ghost-window flash on every dialog open. See
        # controls.SectionHeader for the full note.
        self.subtitle = QLabel(subtitle, self)
        self.subtitle.setObjectName("pageSubtitle")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        col.addWidget(self.subtitle)
        row.addLayout(col, stretch=1)

        self.actions_row = QHBoxLayout()
        self.actions_row.setContentsMargins(0, 0, 0, 0)
        self.actions_row.setSpacing(theme.SPACE_2)
        self.actions_row.setAlignment(Qt.AlignTop)
        row.addLayout(self.actions_row)
        for widget in actions or []:
            self.actions_row.addWidget(widget)

        self.close_btn = None
        if on_close is not None:
            self.close_btn = C.icon_button("x", i18n.t("Close"), on_close)
            self.actions_row.addWidget(self.close_btn)

    def set_title(self, text: str):
        self.title.setText(text)

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))

    def add_action(self, widget: QWidget) -> QWidget:
        # Before the close button, so the X stays the last thing on the row.
        index = self.actions_row.count() - (1 if self.close_btn else 0)
        self.actions_row.insertWidget(max(0, index), widget)
        return widget


class DialogFooter(QFrame):
    """The fixed action bar. One primary, secondaries beside it, destructive
    exiled to the far left.

    Three clusters rather than one row of buttons, because "which of these is
    irreversible" and "which of these is the thing I came here to do" are two
    different questions and a single row answers neither. Left: destructive,
    then utilities (export, open a folder, sign in). Right: secondaries, then
    the one primary. The stretch between them is the separation.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dialogFooter")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setStyleSheet(
            f"#dialogFooter {{ background: {theme.CARD};"
            f" border: none; border-top: 1px solid {theme.HAIRLINE}; }}")

        row = QHBoxLayout(self)
        row.setContentsMargins(theme.PAGE_PAD, theme.SPACE_MD,
                               theme.PAGE_PAD, theme.SPACE_MD)
        row.setSpacing(theme.SPACE_2)

        self._left = QHBoxLayout()
        self._left.setContentsMargins(0, 0, 0, 0)
        self._left.setSpacing(theme.SPACE_2)
        row.addLayout(self._left)

        self._note_slot = QHBoxLayout()
        self._note_slot.setContentsMargins(0, 0, 0, 0)
        self._note_slot.setSpacing(theme.SPACE_2)
        row.addLayout(self._note_slot, stretch=1)
        row.addStretch(1)

        self._right = QHBoxLayout()
        self._right.setContentsMargins(0, 0, 0, 0)
        self._right.setSpacing(theme.SPACE_2)
        row.addLayout(self._right)

        self.primary = None

    # -- left cluster -----------------------------------------------------
    def add_destructive(self, widget: QWidget) -> QWidget:
        """An irreversible action. Always inserted at the very left, and a
        hairline is dropped after it so it is not read as another utility."""
        self._left.insertWidget(0, widget)
        rule = C.hairline(vertical=True)
        rule.setFixedHeight(C.MIN_TARGET - theme.SPACE_2)
        self._left.insertWidget(1, rule)
        return widget

    def add_utility(self, widget: QWidget) -> QWidget:
        """A side action that is neither the point of the dialog nor a way out
        of it — export diagnostics, open the folder, open login tabs."""
        self._left.addWidget(widget)
        return widget

    def add_note(self, widget: QWidget) -> QWidget:
        """A line of standing text in the bar — a device fingerprint, a licence
        id, a count. Takes the slack so the buttons stay at the two ends."""
        self._note_slot.addWidget(widget)
        return widget

    # -- right cluster ----------------------------------------------------
    def add_secondary(self, widget: QWidget) -> QWidget:
        """Cancel, Close, Not now, Back — anything that is a real choice but
        not the one this window is for. Kept left of the primary."""
        index = self._right.count() - (1 if self.primary is not None else 0)
        self._right.insertWidget(max(0, index), widget)
        return widget

    def set_primary(self, widget: QWidget) -> QWidget:
        """The one thing this dialog is for. Exactly one, and this raises
        rather than letting a second solid accent button on to the bar — two
        primaries is the same as none."""
        if self.primary is not None:
            raise ValueError("a dialog footer takes exactly one primary button")
        self.primary = widget
        self._right.addWidget(widget)
        return widget


class PrismDialog(QDialog):
    """Header / body / footer, wired up. Subclass this instead of QDialog.

    Everything a dialog puts on screen goes into `self.body`, which is a plain
    QVBoxLayout already carrying the page padding and the card gutter. If the
    content can outgrow the window, pass `scrollable=True` and it gets a
    QScrollArea whose viewport claims the full height — a dialog that
    top-anchors a form and leaves a grey field under it is the same defect the
    screens have, and it is fixed the same way.

        class MyDialog(PrismDialog):
            def __init__(self, parent=None):
                super().__init__("Title", "One line saying what this is for",
                                 icon="key", parent=parent)
                self.body.addWidget(...)
                self.footer.add_secondary(self.button("Cancel",
                                                      on_click=self.reject))
                self.footer.set_primary(self.button("Save", "primary",
                                                    on_click=self._save))

    `accept()` and `reject()` are untouched QDialog. So is `exec()`. Adopting
    this class must never change what a caller gets back.
    """

    def __init__(self, title: str, subtitle: str = "", icon: str = "",
                 parent=None, scrollable: bool = False,
                 closable: bool = False, body_spacing: int = theme.CARD_GAP,
                 eyebrow: str = "", leading: QWidget = None):
        super().__init__(parent)
        self.setWindowTitle(title)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.header = DialogHeader(
            title, subtitle, icon, eyebrow=eyebrow, leading=leading,
            on_close=self.reject if closable else None)
        root.addWidget(self.header)

        self._content = QWidget()
        self._content.setObjectName("dialogBody")
        self.body = QVBoxLayout(self._content)
        self.body.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                     theme.PAGE_PAD, theme.SPACE_5 + 16)
        self.body.setSpacing(body_spacing)

        if scrollable:
            self.scroll = QScrollArea()
            self.scroll.setWidgetResizable(True)
            self.scroll.setFrameShape(QScrollArea.NoFrame)
            self.scroll.verticalScrollBar().valueChanged.connect(lambda _: self.scroll.viewport().update())
            self.scroll.setWidget(self._content)
            root.addWidget(self.scroll, stretch=1)
        else:
            self.scroll = None
            root.addWidget(self._content, stretch=1)

        self.footer = DialogFooter()
        root.addWidget(self.footer)

    # -- buttons ----------------------------------------------------------
    def button(self, text: str, variant: str = "secondary",
               icon_name: str = "", on_click=None, tooltip: str = "",
               small: bool = False):
        """One footer button, on the four-variant scale. A thin wrapper over
        `controls.button` so a dialog never has to remember an object name —
        guessing one is how the app ended up with eleven button styles and a
        `primary` that had no rule at all."""
        btn = C.button(text, variant, icon_name, small=small, on_click=on_click)
        if tooltip:
            btn.setToolTip(tooltip)
            if not btn.accessibleName():
                btn.setAccessibleName(f"{text}. {tooltip}")
        if variant == "primary":
            btn.setDefault(True)
            btn.setAutoDefault(True)
        return btn

    def tab_chain(self, *widgets):
        """Set the tab order across the widgets given, skipping any that are
        None. A first-run dialog that cannot be completed from the keyboard is
        an accessibility failure, and Qt's default order follows construction
        order — which, once a form is built in three helper methods, is not the
        order anything is read in."""
        real = [w for w in widgets if w is not None]
        for first, second in zip(real, real[1:]):
            QDialog.setTabOrder(first, second)
        return real
