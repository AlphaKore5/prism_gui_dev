"""Email inquiry automation, the screen: what needs you today, in words.

This used to be a second working surface — six figures and four tabs named
almost exactly like the working window's, showing different things under
the same names ("What arrived" here listed register rows; there it listed
mail). An owner could not tell which one to use, and the honest answer was
"the other one" for everything except reading.

So this screen is now the launcher, and only the launcher. It answers the
one question the product docs say the owner opens Prism with — *what needs
me?* — as a short list in plain words with a button beside each line that
opens the working window straight onto the right tab. Under that, this
month's figures as a plain two-column table (a Tally user reads a column of
labelled numbers faster than six tiles), and the mailboxes being watched.
Nothing here is a second copy of the work; every button hands off.

Every figure is read from the real register CSV and the worklist files
through dashboard_data. With no register configured the screen says so and
offers the way in, because zero to quote and no register at all are very
different facts and must not look the same.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
    QWidget,
)

import dashboard_data as DATA
import i18n
import theme
from widgets import icons
from inquiry_config import TAB_INDEX, TABS  # noqa: F401 — re-exported
from widgets import controls as C
from widgets.controls import Card, IconPad, Pill

# The one primary on the populated screen. Named here so the tests and the
# door both read it from one place.
OPEN_LABEL = "Open Email inquiry automation"


class _FrontDoor(C.EmptyState):
    """controls.EmptyState with one quieter action under the primary one.

    This front door needs two ways forward — run a check, or go back into
    setup — and EmptyState carries a single action by design. Borrowing the
    shared one and appending to the column it already centres is the whole of
    the change; the alternative was what shipped before, a private copy of
    `simple_panels._AddonFrontDoor` that could not centre itself because it was
    a fixed-height card in a top-anchored scroll.
    """

    secondary = Signal()

    def __init__(self, icon: str, title: str, body: str, action_text: str,
                 secondary_text: str = "", parent=None):
        super().__init__(icon, title, body, action_text, parent)
        if not secondary_text:
            return
        column = getattr(self, "content_layout", None)
        if column is None:
            outer = self.layout()
            for index in range(outer.count()):
                item = outer.itemAt(index)
                if item.layout() is not None:
                    column = item.layout()
                    break
        if column is None:                  # EmptyState changed shape
            return
        button = C.button(secondary_text, "tertiary")
        button.clicked.connect(self.secondary.emit)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        column.addLayout(row)


class InquiryPanel(QWidget):
    # The tab index of the working window to open on — see
    # addons.inquiry.dialog.TABS. 0 is "To quote".
    open_dialog = Signal(int)
    # The front door's "Check my mail now" specifically: open the working
    # window AND start a check immediately, rather than leaving the owner to
    # find the second button of the same name once the window is up. Every
    # other button that opens the window (the header's "Open Email
    # automation", each "what needs you today" line) hands off without
    # forcing a fetch nobody asked for.
    check_requested = Signal()
    set_up = Signal()               # no register yet — open setup

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._rows: list | None = None      # register cache; None = never read

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self._header = C.PageHeader(i18n.t("Email inquiry automation"))
        root.addWidget(self._header)

        # widgetResizable, so a short window scrolls the page instead of
        # compressing its children past their minimum — which is what makes
        # an empty state print its title over its own icon.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._host = QWidget()
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5 + 14,
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        self._scroll.setWidget(self._host)
        root.addWidget(self._scroll, stretch=1)
        self.refresh()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self, reread: bool = True):
        """Rebuild the screen. `reread` False re-renders from the rows already
        in hand — the register is a CSV that may sit on a shared drive."""
        self._drop(self._col)
        self._clear_actions()

        self._header.set_subtitle(self._watching() or i18n.t(
            "Prism reads your inbox, writes every inquiry in the register, "
            "and tells you what needs you."))

        if reread or self._rows is None:
            self._rows = DATA.register_rows(self.cfg)
        stats = DATA.inquiry_stats(self.cfg, self._rows)
        if not stats:
            self._col.addWidget(self._not_set_up(), stretch=1)
            for widget in self._waiting_room():
                self._col.addWidget(widget)
            return

        self._header.add_action(C.button(i18n.t("Edit setup"), "secondary",
                                         icon_name="sliders",
                                         on_click=self.set_up.emit))
        door = C.button(i18n.t(OPEN_LABEL), "primary",
                        on_click=lambda: self.open_dialog.emit(0))
        door.setToolTip(i18n.t(
            "Opens the working window — check the mail, quote, chase, and "
            "record the order."))
        self._header.add_action(door)

        # Two columns like the preview's .inqdash: what needs you (1.25) beside
        # this month and the mailboxes (1).
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(theme.SPACE_4 - 1)
        cols.addWidget(self._needs_you_card(), 125, Qt.AlignTop)
        right = self._month_card()
        if right is not None:
            cols.addWidget(right, 100, Qt.AlignTop)
        else:
            cols.addStretch(100)
        self._col.addLayout(cols)
        self._col.addStretch(1)

    def _clear_actions(self):
        row = self._header.actions_row
        while row.count():
            item = row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()   # before setParent(None): avoids ghost-window flash
                widget.setParent(None)
                widget.deleteLater()

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()   # before setParent(None): avoids ghost-window flash
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── what needs you today ──────────────────────────────────────────────
    def _needs_you_card(self) -> QWidget:
        """The four lines the owner opens Prism for, each with the button
        that opens the working window on exactly that list. A zero is said
        in words, greyed, with no button — "No new orders" is news too."""
        counts = DATA.needs_you(self.cfg, self._rows)
        card = Card()
        col = card.body((18, 16, 18, 16), 0)
        col.addWidget(C.kicker(i18n.t("What needs you today")))
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.hairline())

        n = counts["to_quote"]
        self._line(col, n,
                   i18n.t("{n} new inquiry to quote") if n == 1
                   else i18n.t("{n} new inquiries to quote"),
                   i18n.t("Nothing new to quote"),
                   i18n.t("Quote them"), "to_quote")

        n = counts["waiting"]
        due = counts["due"]
        waiting_text = (i18n.t("{n} quotation with no answer yet") if n == 1
                        else i18n.t("{n} quotations with no answer yet"))
        if due:
            waiting_text += " · " + (
                i18n.t("{d} needs a reminder today") if due == 1
                else i18n.t("{d} need a reminder today")).replace(
                    "{d}", str(due))
        self._line(col, n, waiting_text,
                   i18n.t("Every quotation has been answered"),
                   i18n.t("Send a reminder") if due else i18n.t("See them"),
                   "waiting")

        n = counts["replies"]
        self._line(col, n,
                   i18n.t("{n} customer answered") if n == 1
                   else i18n.t("{n} customers answered"),
                   i18n.t("No new answers"), i18n.t("Read the answer"),
                   "replies")

        n = counts["orders"]
        self._line(col, n,
                   i18n.t("{n} order came") if n == 1
                   else i18n.t("{n} orders came"),
                   i18n.t("No new orders"), i18n.t("Open the order"), "orders")

        col.addSpacing(13)
        foot = []
        if counts["sent_today"]:
            n = counts["sent_today"]
            # Without the period, " ".join(foot) below ran this straight
            # into the next sentence with no separator at all — "...for you
            # today Prism checks..." — the run-on that made the footer read
            # as one confused sentence.
            foot.append((i18n.t("Prism sent {n} mail for you today.") if n == 1
                         else i18n.t("Prism sent {n} mails for you today."))
                        .replace("{n}", str(n)))
        minutes = self._auto_minutes()
        if minutes:
            foot.append(i18n.t("Prism checks the mail by itself every {n} "
                               "minutes.").replace("{n}", str(minutes)))
        else:
            foot.append(i18n.t("Prism checks the mail when you press Check "
                               "my mail now. Switch on \"Check by itself\" "
                               "in the working window to have it run alone."))
        col.addWidget(C.label(" ".join(foot), level="META", colour=theme.MUTE,
                              wrap=True))
        return card

    def _line(self, col, count: int, text: str, none_text: str,
              button_text: str, tab: str):
        """One row of the preview's .nline: the figure in mono, the sentence,
        and (only when there is something to do) the light pill that opens
        the working window on that tab. A hairline closes every row."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 12, 0, 12)
        row.setSpacing(12)
        number = QLabel(str(count))
        number.setObjectName("needsFigure")
        number.setFixedWidth(38)
        number.setStyleSheet(
            f"font-family: {theme.FONT_MONO_STACK}; font-size: 25px;"
            f" font-weight: 400; color: {theme.INK if count else theme.FAINT};")
        row.addWidget(number)
        if count:
            label = C.label(text.replace("{n}", str(count)), level="BODY",
                            weight=400, colour=theme.INK, wrap=True)
        else:
            label = C.label(none_text, level="BODY", colour=theme.MUTE,
                            wrap=True)
        label.setMinimumHeight(C.MIN_TARGET)
        row.addWidget(label, stretch=1)
        if count:
            index = TAB_INDEX[tab]
            act = C.button(button_text, "secondary", small=True,
                           on_click=lambda: self.open_dialog.emit(index))
            act.setProperty("pill", True)       # the light pill, QSS only
            # `.btn.sm` is 33px; the sheet's padding and min-height would make it 45.
            act.setStyleSheet("min-height: 31px; max-height: 31px; padding: 0px 16px;")
            act.setFixedHeight(33)
            row.addWidget(act)
        col.addLayout(row)
        col.addWidget(C.hairline())

    def _auto_minutes(self) -> int:
        try:
            from inquiry_config import settings_of
            return int((settings_of(self.cfg) or {}).get("auto_minutes", 0) or 0)
        except Exception:                   # noqa: BLE001
            return 0

    # ── this month ────────────────────────────────────────────────────────
    def _month_card(self) -> QWidget | None:
        """This month's rows and the mailboxes, on one card (the preview's
        .month). The figures are read straight off register.summarise() — the
        same arithmetic the month-end summary uses, so the two can never
        disagree. None when there is neither a month nor a mailbox."""
        month = DATA.month_summary(self.cfg, self._rows)
        from inquiry_config import active_accounts_of
        accounts = active_accounts_of(self.cfg)
        if not month and not accounts:
            return None
        card = Card()
        col = card.body((18, 16, 18, 16), 0)
        if month:
            self._month_rows(col, month)
        if accounts:
            if month:
                col.addSpacing(theme.SPACE_4)
            col.addWidget(C.kicker(i18n.t("Mailboxes Prism reads")))
            col.addSpacing(theme.SPACE_2)
            sub = C.label(i18n.t("Every one of them feeds the same register."),
                          level="SUPPORT", colour=theme.MUTE, wrap=True)
            col.addWidget(sub)
            col.addSpacing(theme.SPACE_1)
            for account in accounts:
                col.addWidget(C.hairline())
                col.addLayout(self._mailbox_row(account))
        return card

    def _month_rows(self, col, month: dict):
        col.addWidget(C.kicker(
            i18n.t("This month — {month}").replace("{month}", month["month"])))
        col.addSpacing(theme.SPACE_2)
        lines = [
            (i18n.t("Inquiries received"), str(month["received"]), ""),
            (i18n.t("Quotations sent"), str(month["quoted"]),
             month["quoted_value"] if month["quoted"] else ""),
            (i18n.t("Orders won"), str(month["converted"]),
             month["converted_value"] if month["converted"] else ""),
            (i18n.t("Orders won out of quotations"),
             f"{month['conversion']:g}%", ""),
            (i18n.t("Quotations with no answer yet"), str(month["waiting"]), ""),
        ]
        reasons = month.get("reasons") or {}
        if reasons:
            said = ", ".join(f"{reason} ({n})" for reason, n in
                             sorted(reasons.items(), key=lambda kv: -kv[1]))
            lines.append((i18n.t("Lost because"), said, ""))
        for index, (name, figure, money) in enumerate(lines):
            if index:
                col.addWidget(C.hairline())
            row = QHBoxLayout()
            row.setContentsMargins(0, 10, 0, 10)
            row.setSpacing(theme.SPACE_2)
            name_label = C.label(name, level="BODY", colour=theme.MUTE)
            name_label.setMinimumHeight(22)
            row.addWidget(name_label, stretch=1)
            if money:
                money_label = C.label(money, level="MONO", colour=theme.MUTE)
                row.addWidget(money_label)
            figure_label = C.label(figure, level="BODY", colour=theme.INK)
            figure_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row.addWidget(figure_label)
            col.addLayout(row)

    def _mailbox_row(self, account: dict) -> QHBoxLayout:
        """One line of the preview's .inc list: glyph, address, READY pill.
        `is_complete` is the setup dialog's own test for a mailbox Prism can
        actually sign in to — a half-entered one is exactly the reason a first
        check finds nothing. The server line is the app's own, kept."""
        from inquiry_config import is_complete
        row = QHBoxLayout()
        row.setContentsMargins(0, 9, 0, 9)
        row.setSpacing(12)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("inbox", 16, theme.MUTE))
        row.addWidget(glyph, 0, Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(C.label(account.get("address", ""), level="BODY",
                               colour=theme.INK, weight=500))
        host = (account.get("host") or "").strip()
        detail = f"{host}:{account.get('port') or 993}" if host else ""
        folder = (account.get("folder") or "INBOX").strip()
        text.addWidget(C.label(" · ".join(p for p in (detail, folder) if p),
                               level="MONO", colour=theme.MUTE))
        row.addLayout(text, stretch=1)
        ready = bool(is_complete(account))
        row.addWidget(Pill(i18n.t("Ready") if ready
                           else i18n.t("Needs a password"),
                           "st_ok" if ready else "st_warn"), 0, Qt.AlignVCenter)
        return row

    # ── not set up yet ────────────────────────────────────────────────────
    def _not_set_up(self) -> QWidget:
        """The empty register, told apart from "never configured".

        A mailbox can be fully set up and tested and still have an empty
        register — nobody has pressed Check yet, or the first check has not
        run. Offering "Set up Email inquiry automation" here as the ONLY way forward
        sent a working setup back into the setup sheet in a loop: that button
        reopens Setup, Setup saves and returns here, the register is still
        empty because nothing has actually gone and read the inbox, so the
        same screen greets it again. The way out is Check, not Setup — this
        state now offers whichever one is actually missing.
        """
        from inquiry_config import accounts_of
        configured = any(a.get("address") for a in accounts_of(self.cfg))

        if configured:
            door = _FrontDoor(
                "inbox", i18n.t("Nothing in the register yet"),
                i18n.t("Your mailbox is set up. Run a check and anything "
                       "waiting there gets a number, a quote and a chase."),
                i18n.t("Check my mail now"), i18n.t("Edit setup"))
            door.clicked.connect(self.check_requested.emit)
            door.secondary.connect(self.set_up.emit)
            return door
        door = _FrontDoor(
            "inbox", i18n.t("Point Prism at a mailbox to begin"),
            i18n.t("Once it can read the inbox, every inquiry gets a number, "
                   "a quote and a chase — and shows up here."),
            i18n.t("Set up Email inquiry automation"))
        door.clicked.connect(self.set_up.emit)
        return door

    # ── the empty register, furnished ─────────────────────────────────────
    def _waiting_room(self) -> list:
        """What a configured-but-empty screen can honestly show underneath its
        empty state: the mailboxes actually being watched and whether each is
        complete, the folder the CSV will be written to, and the register's
        own status vocabulary. A customer waiting for their first check should
        be able to see where it is going to land and what it will say."""
        from inquiry_config import active_accounts_of, settings_of
        accounts = active_accounts_of(self.cfg)
        if not accounts:
            return []                   # nothing configured, nothing to state

        out = []
        settings = settings_of(self.cfg)
        rows = [(i18n.t("Register file"),
                 self._path(settings.get("folder") or "—"))]
        if (settings.get("company") or "").strip():
            rows.insert(0, (i18n.t("Quoting as"), settings["company"].strip()))
        out.append(self._head(
            i18n.t("Where the first check will land"),
            i18n.t("Every mailbox below feeds the same register.")))
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for index, (name, value) in enumerate(rows):
            if index:
                col.addWidget(C.hairline())
            line = QHBoxLayout()
            line.setContentsMargins(0, theme.SPACE_3 - 1, 0,
                                    theme.SPACE_3 - 1)
            line.addWidget(C.label(name, level="SUPPORT",
                                   colour=theme.NEUTRAL[600]))
            line.addStretch(1)
            line.addWidget(value if isinstance(value, QWidget)
                           else C.label(str(value), level="SUPPORT",
                                        colour=theme.TEXT, weight=500))
            col.addLayout(line)
        out.append(card)

        grid = C.CardGrid(min_col_width=300)
        for account in accounts:
            grid.add(self._mailbox_card(account))
        out.append(grid)

        out.append(self._head(
            i18n.t("What the Status column will say"),
            i18n.t("Prism moves an inquiry along this line as you quote it, "
                   "chase it and close it.")))
        out.append(self._status_ladder())
        return out

    @staticmethod
    def _head(title: str, subtitle: str = "") -> QWidget:
        """A mono kicker over a muted line, like the preview's card labels. The
        subtitle WRAPS: an unbreakable line pushed the page wider than the
        viewport and silently clipped the right-hand column."""
        host = QWidget()
        col = QVBoxLayout(host)
        col.setContentsMargins(4, theme.SPACE_2, 4, 0)
        col.setSpacing(theme.SPACE_1)
        col.addWidget(C.kicker(title))
        if subtitle:
            col.addWidget(C.label(subtitle, level="SUPPORT", colour=theme.MUTE,
                                  wrap=True))
        return host

    def _mailbox_card(self, account: dict) -> Card:
        """One configured mailbox. `_complete` is the setup dialog's own test
        for a mailbox Prism can actually sign in to — a half-entered one is
        exactly the reason a first check finds nothing."""
        from inquiry_config import is_complete
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(IconPad("inbox", theme.ACCENT, 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(account.get("address", ""), level="SUPPORT",
                               colour=theme.TEXT, weight=500), stretch=1)
        ready = bool(is_complete(account))
        head.addWidget(Pill(i18n.t("Ready") if ready
                            else i18n.t("Needs a password"),
                            "st_ok" if ready else "st_warn"))
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        host = (account.get("host") or "").strip()
        detail = f"{host}:{account.get('port') or 993}" if host else ""
        folder = (account.get("folder") or "INBOX").strip()
        col.addWidget(C.label(" · ".join(p for p in (detail, folder) if p),
                              level="MONO"))
        return card

    def _status_ladder(self) -> Card:
        """The register's own status vocabulary, in its own order, wearing the
        same pill the table does. Read off the register module — this screen
        must never teach a word the CSV does not use."""
        import core_bridge as CB
        statuses = list(getattr(CB.get_register(), "STATUSES", ()) or ())
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        for index, status in enumerate(statuses):
            if index:
                row.addWidget(C.label("→", level="META"))
            row.addWidget(Pill(status, DATA.status_tone(status)))
        row.addStretch(1)
        col.addLayout(row)
        return card

    @staticmethod
    def _path(text: str) -> QLabel:
        text = str(text)
        label = C.label(text if len(text) <= 52 else "…" + text[-51:],
                        level="MONO", tooltip=text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    def _watching(self) -> str:
        """"Watching sales@… and 2 more — one register." — or "" for one
        mailbox, where the standing blurb says everything already."""
        try:
            from inquiry_config import active_accounts_of
            addresses = [a.get("address", "")
                         for a in active_accounts_of(self.cfg)]
        except Exception:                   # noqa: BLE001
            return ""
        if len(addresses) < 2:
            return ""
        return (i18n.t("Watching {first} and {n} more — every inquiry lands "
                       "in one register.")
                .replace("{first}", addresses[0])
                .replace("{n}", str(len(addresses) - 1)))
