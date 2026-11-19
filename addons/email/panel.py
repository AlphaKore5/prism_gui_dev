"""Email, the screen: two ways to start, and what has already gone.

The old screen was a brochure — "How it works" in four cards, "Which of
your tools it uses" — with one button that opened a window whose To field
was folded away under "Edit the recipient list (optional)". An owner who
wanted to write to one supplier could not find where the address went.

This screen does what the Email-automation launcher does: it answers the
question the owner came with, in plain words, and hands off. Two buttons —
write to one person, send to a list — because those are the two things
anyone does with this add-on. Under them, the emails already sent from this
computer, read back from `~/Prism Email/sent.json`, so "did that go?" is
answered by looking. Under that, the sending account, and the one way to
change it. Nothing on this screen is a second copy of the work.
"""
from __future__ import annotations

import os

import datetime

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
    QScrollArea, QSizePolicy, QStyledItemDelegate, QStyle, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

import i18n
from addons.email import sent_log
import theme
from widgets import controls as C, icons
from widgets.controls import Card, Pill

# The one primary on the populated screen and in the header.
NEW_LABEL = "New email"
ONE_LABEL = "Write to one person"
LIST_LABEL = "Send to a list"
SHOW_SENT = 50


def pillify(btn: QWidget) -> QWidget:
    """The preview's `.btn.light.plain.sm`: a 33px light pill. Look only; the
    button keeps its text, icon, tooltip and `clicked`."""
    btn.setProperty("pill", True)
    btn.setStyleSheet(
        "QPushButton { min-height: 31px; max-height: 31px; padding: 0px 16px;"
        " border-radius: 16px; font-size: 13px; border: 1px solid #e4e3df;"
        " background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffffff, stop:1 #f8f7f4); }"
        " QPushButton:hover { background: #ffffff; border-color: #d8d7d2; }"
        " QPushButton:disabled { color: #a9a8a3; background: #f6f5f2; }")
    btn.setFixedHeight(33)
    return btn


def linkify(btn: QWidget, size: int = 12) -> QWidget:
    """A quiet text action (the preview's `.hint` / `.link`): no box."""
    btn.setStyleSheet(
        f"QPushButton {{ background: transparent; border: none; padding: 2px 4px;"
        f" min-height: 20px; font-size: {size}px; font-weight: 500; color: #111110; }}"
        " QPushButton:hover { color: #000000; text-decoration: underline; }"
        " QPushButton:disabled { color: #a9a8a3; }")
    return btn


ROW_H = 61                      # the preview's .runs li, 61.4px
_TONE_ROLE = Qt.UserRole + 1    # st_ok / st_err / st_warn, set with the item


def _when_text(date: str) -> str:
    """"2026-11-14 08:56" as the preview words it: Today 08:56, Yesterday
    16:40, Mon 18:05, then the date. Display only; the item text is unchanged."""
    try:
        day, _, clock = date.partition(" ")
        then = datetime.date.fromisoformat(day)
    except ValueError:
        return date
    gap = (datetime.date.today() - then).days
    if gap == 0:
        word = i18n.t("Today")
    elif gap == 1:
        word = i18n.t("Yesterday")
    elif 0 < gap < 7:
        word = then.strftime("%a")
    else:
        word = day
    return f"{word} {clock}".strip()


def _soft_pill_colours(tone: str) -> tuple:
    return {"st_ok": (theme.BRAND_OK_BG, theme.BRAND_OK),
            "st_err": (theme.BRAND_ERR_BG, theme.BRAND_ERR),
            "st_warn": ("#F6EDD6", "#7A5A0E")}.get(tone, ("#EFEEEA", "#2A2A28"))


class _SentRows(QStyledItemDelegate):
    """Paints the sent table as the preview's `.runs` rows. Display only: the
    items, their text and the table's selection behaviour are the ones the
    table always had. Column 2 paints tile + subject + address (column 1's
    text), column 0 the mono time, column 3 the SENT / BOUNCED pill."""

    def paint(self, p, option, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        r = QRectF(option.rect)
        if option.state & (QStyle.State_Selected | QStyle.State_MouseOver):
            p.fillRect(r, QColor("#F6F5F2"))
        col = index.column()
        model = index.model()
        text = index.data(Qt.DisplayRole) or ""
        if col == 2:
            tile = QRectF(r.left() + 17, r.center().y() - 17, 34, 34)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#EFEEEA"))
            p.drawRoundedRect(tile, 9.5, 9.5)
            glyph = icons.pixmap("mail", 15, theme.INK)
            ratio = glyph.devicePixelRatio() or 1.0
            p.drawPixmap(int(tile.center().x() - glyph.width() / ratio / 2),
                         int(tile.center().y() - glyph.height() / ratio / 2), glyph)
            left = tile.right() + 12
            wide = QRectF(left, r.top(), r.right() - left - 8, r.height())
            font = QFont(theme.FONT_BODY)
            font.setPixelSize(14); font.setWeight(QFont.Normal)
            p.setFont(font)
            fm = QFontMetricsF(font)
            p.setPen(QColor(theme.INK))
            p.drawText(QRectF(wide.left(), r.center().y() - 21, wide.width(), 21),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(text, Qt.ElideRight, wide.width()))
            sub = model.index(index.row(), 1).data(Qt.DisplayRole) or ""
            font.setPixelSize(12); p.setFont(font)
            fm = QFontMetricsF(font)
            p.setPen(QColor(theme.MUTE))
            p.drawText(QRectF(wide.left(), r.center().y(), wide.width(), 18),
                       Qt.AlignVCenter | Qt.AlignLeft,
                       fm.elidedText(sub, Qt.ElideRight, wide.width()))
        elif col == 0:
            font = QFont(theme.FONT_MONO); font.setPixelSize(11)
            p.setFont(font)
            p.setPen(QColor(theme.MUTE))
            p.drawText(r.adjusted(0, 0, -6, 0), Qt.AlignVCenter | Qt.AlignRight,
                       _when_text(text))
        elif col == 3:
            bg, ink = _soft_pill_colours(index.data(_TONE_ROLE) or "")
            font = QFont(theme.FONT_MONO); font.setPixelSize(11)
            font.setWeight(QFont.Medium); font.setLetterSpacing(QFont.AbsoluteSpacing, 0.75)
            p.setFont(font)
            label = text.upper()
            w = QFontMetricsF(font).horizontalAdvance(label) + 9.6 + 6 + 8.6 + 9.6
            pill = QRectF(r.right() - 17 - w, r.center().y() - 12.9, w, 25.8)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(bg))
            p.drawRoundedRect(pill, 6.6, 6.6)
            p.setBrush(QColor(ink))
            p.drawRect(QRectF(pill.left() + 9.6, pill.center().y() - 3, 6, 6))
            p.setPen(QColor(ink))
            p.drawText(QRectF(pill.left() + 9.6 + 6 + 8.6, pill.top(), w, pill.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, label)
        if index.row() < model.rowCount() - 1:
            p.setPen(QPen(QColor(theme.HAIRLINE), 1))
            left = r.left() + (17 if col == 2 else 0)
            right = r.right() - (17 if col == 3 else 0)
            p.drawLine(left, r.bottom(), right, r.bottom())
        p.restore()

    def sizeHint(self, option, index):
        from PySide6.QtCore import QSize
        return QSize(option.rect.width(), ROW_H)


class EmailPanel(QWidget):
    opened = Signal()               # header primary — the same as "one"
    open_compose = Signal(str)      # "one" | "list"
    change_account = Signal()
    navigate = Signal(str)          # kept: MainWindow wires every add-on alike
    open_run = Signal(str)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._actions = [
            C.button(i18n.t("Change account"), "secondary", icon_name="key",
                     on_click=self.change_account.emit),
            C.button(i18n.t(NEW_LABEL), "primary",
                     on_click=self.opened.emit),
        ]
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = C.PageHeader(i18n.t("Email Outreach"), "", list(self._actions))
        root.addWidget(self.header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        self._col = QVBoxLayout(host)
        self._col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5 + 11,   # the preview's cards start 11px lower
                                     theme.PAGE_PAD, theme.PAGE_PAD)
        self._col.setSpacing(theme.CARD_GAP)
        self._scroll.setWidget(host)
        root.addWidget(self._scroll, stretch=1)
        self.refresh()

    def header_actions(self) -> list:
        return list(self._actions)

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        self._drop(self._col)
        address = self._address()
        if not address:
            self.header.set_subtitle(i18n.t(
                "Send emails from your own account. Set the account up once."))
            self._col.addWidget(self._not_set_up(), stretch=1)
            return
        self.header.set_subtitle(i18n.t(
            "Send from {address} — to one person or to a whole list. You read "
            "every word before it goes.").format(address=address))
        top = QHBoxLayout()                 # the preview's .emgrid: two cards, then the list
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(theme.CARD_GAP)
        account, start = self._account_card(address), self._start_card()
        top.addWidget(account, 1)
        top.addWidget(start, 1)
        self._col.addLayout(top)
        self._col.addWidget(self._sent_card())
        self._col.addStretch(1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()          # a send in the window must show here at once

    def _address(self) -> str:
        """The address this screen leads with: the one that sends unless
        somebody picks another on the way out."""
        import email_config
        return (email_config.default_sender(self.cfg).get("address")
                or "").strip()

    def _not_set_up(self) -> QWidget:
        door = C.EmptyState(
            "mail", i18n.t("No sending account yet"),
            i18n.t("Prism sends from your own email account. Set it up once "
                   "— address and app password — and every email after that "
                   "goes out in your name."),
            i18n.t("Set up the sending account"))
        door.clicked.connect(self.change_account.emit)
        return door

    def _start_card(self) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.ROW_GAP)
        col.addWidget(C.kicker(i18n.t("Send an email")))
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(theme.SPACE_5)
        grid.setVerticalSpacing(theme.SPACE_2)
        self.one_btn = self._pill_button(
            i18n.t(ONE_LABEL), "user", lambda: self.open_compose.emit("one"))
        self.list_btn = self._pill_button(
            i18n.t(LIST_LABEL), "list", lambda: self.open_compose.emit("list"))
        for column, (button, text) in enumerate((
            (self.one_btn, i18n.t(
                "Type the address, the subject and the message, then press "
                "Send. Prism can write the message for you if you ask it to.")),
            (self.list_btn, i18n.t(
                "Attach a CSV of addresses (name, email). Each person gets "
                "their own copy, with their own name in it.")),
        )):
            grid.addWidget(button, 0, column, alignment=Qt.AlignLeft)
            note = C.label(text, level="SUPPORT", wrap=True, colour=theme.MUTE)
            note.setMinimumWidth(120)
            note.setStyleSheet(note.styleSheet() + " font-size: 12px;")
            grid.addWidget(note, 1, column)
            grid.setColumnStretch(column, 1)
        col.addLayout(grid)
        return card

    def _sent_card(self) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.ROW_GAP)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(C.kicker(i18n.t("Sent from this computer")))
        head.addStretch(1)
        folder_btn = self._pill_button(i18n.t("Open the folder"), "folder",
                                       self._open_folder)
        head.addWidget(folder_btn)
        col.addLayout(head)

        entries = sent_log.load(self.cfg)
        if not entries:
            col.addWidget(C.label(i18n.t(
                "Nothing sent yet. Every email you send is listed here — "
                "when, to whom, and whether it went."), level="SUPPORT",
                wrap=True))
            self.sent_table = None
            return card

        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels([i18n.t(h) for h in
                                         ("Date", "To", "Subject", "Result")])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setAlternatingRowColors(False)
        table.setWordWrap(False)
        table.setShowGrid(False)
        table.setFrameShape(QTableWidget.NoFrame)
        table.setMouseTracking(True)
        table.setObjectName("sentRows")
        table.setStyleSheet("#sentRows { background: transparent; border: none; }")
        table.setItemDelegate(_SentRows(table))
        table.verticalHeader().setDefaultSectionSize(ROW_H)
        head = table.horizontalHeader()
        head.setSectionResizeMode(2, QHeaderView.Stretch)
        head.setSectionResizeMode(0, QHeaderView.Fixed)
        head.setSectionResizeMode(3, QHeaderView.Fixed)
        table.setColumnWidth(0, 120)
        table.setColumnWidth(3, 200)
        table.setColumnHidden(1, True)      # its text is painted under the subject
        head.moveSection(2, 0)              # subject, time, result: the preview's order
        head.setVisible(False)
        for entry in entries[:SHOW_SENT]:
            row = table.rowCount()
            table.insertRow(row)
            date = f"{entry.get('date', '')} {entry.get('time', '')}".strip()
            cells = (date, sent_log.describe_to(entry),
                     entry.get("subject", ""), sent_log.describe_result(entry))
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if column == 3:
                    item.setData(_TONE_ROLE, self._tone(entry))
                    if entry.get("failed"):
                        item.setForeground(Qt.GlobalColor.darkRed)
                table.setItem(row, column, item)
            table.item(row, 1).setToolTip(
                "\n".join(r.get("email", "") for r in entry.get("to") or []))
        # Exactly as tall as its rows (up to twelve; more scroll) — a table
        # sized by Qt's own hint leaves a blank field under two rows.
        rows = min(table.rowCount(), 12)
        row_h = table.verticalHeader().defaultSectionSize()
        table.setFixedHeight(rows * row_h + 4)
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        col.addWidget(table)
        if len(entries) > SHOW_SENT:
            col.addWidget(C.label(i18n.t(
                "Showing the last {n}. The full record is in the folder."
            ).format(n=SHOW_SENT), level="SUPPORT"))
        self.sent_table = table
        return card

    def _account_card(self, address: str) -> QWidget:
        card = Card()
        col = card.body()
        col.setSpacing(theme.SPACE_2)
        col.addWidget(C.kicker(i18n.t("Sending account")))
        import email_config
        senders = email_config.active_senders(self.cfg)
        account = email_config.default_sender(self.cfg)
        line = QHBoxLayout()
        line.setContentsMargins(0, 6, 0, 0)
        line.setSpacing(10)
        avatar = C.Avatar(address, 27, theme.INK)
        avatar.setStyleSheet(avatar.styleSheet() + " font-weight: 500; font-size: 11px;")
        line.addWidget(avatar, 0, Qt.AlignVCenter)
        who = QVBoxLayout()
        who.setSpacing(1)
        who.addWidget(C.label(address, level="BODY", weight=500, colour=theme.INK))
        host = account.get("host") or ""
        if host:
            who.addWidget(C.label(i18n.t("through {host}").format(host=host),
                                  level="SUPPORT", colour=theme.MUTE))
        line.addLayout(who)
        line.addWidget(Pill(i18n.t("Ready"), "st_ok"), 0, Qt.AlignVCenter)
        line.addStretch(1)
        line.addWidget(self._pill_button(i18n.t("Change account"), "key",
                                         self.change_account.emit))
        col.addLayout(line)
        if len(senders) > 1:
            others = ", ".join(a.get("address", "") for a in senders[1:])
            col.addWidget(C.label(
                i18n.t("Also set up: {who}. You choose which one a message "
                       "goes out from when you send it.").replace(
                    "{who}", others), level="SUPPORT", wrap=True))
        col.addWidget(C.label(i18n.t(
            "Every email goes out from this address, through your own mail "
            "provider. Prism has no mail server of its own, and your password "
            "stays on this computer."), level="SUPPORT", wrap=True,
            colour=theme.MUTE))
        col.addStretch(1)
        return card

    @staticmethod
    def _tone(entry: dict) -> str:
        """Pill tone for a log entry: all gone is ok, none gone is err,
        partly gone or stopped is warn. Colour only; the words stay."""
        failed, sent = entry.get("failed"), entry.get("sent")
        if failed and not sent:
            return "st_err"
        if failed or entry.get("stopped"):
            return "st_warn"
        return "st_ok"

    @staticmethod
    def _pill_button(text: str, icon_name: str, on_click) -> QWidget:
        """The preview's `.btn.light.plain.sm`: 33px light pill."""
        return pillify(C.button(text, "secondary", icon_name=icon_name,
                                small=True, on_click=on_click))

    # ── plumbing ──────────────────────────────────────────────────────────
    def _open_folder(self):
        target = sent_log.folder(self.cfg)
        try:
            os.makedirs(target, exist_ok=True)
        except OSError:
            return
        import paths
        paths.open_file(target, self)

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
                continue
            child = item.layout()
            if child is not None:
                self._drop(child)
