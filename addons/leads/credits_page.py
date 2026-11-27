"""Credits — what a customer sees of their pool, and how they ask for more.

Apollo's Credit usage page and Upgrade flow, in Prism's shape (the owner sent the
screens, 24-Sep-2026): a small "Team credit usage" card behind the balance pill
(Upgrade plan / View usage), the Credit usage page (Overview with a donut by
feature or by team member, the available credits and when they renew, Usage
details as the activity list, About credits), and the Upgrade flow — Select
plan, Add-ons, Payment, Review.

There is no payment gateway. The last step of the Upgrade flow SENDS A REQUEST to
Alphakore (POST /v1/credits/request), which the operator's console lists and one
click grants; the Payment step says so in plain words instead of pretending a
card is taken. Every number here comes from the licence server
(prospector.gateway.credit_usage / credit_offers), off the UI thread; this module
holds no balance of its own and never computes a price.

Nothing here opens a dialog with exec(): the workbench opens these with open(),
like Search settings, so the screen behind stays alive and a test can look.
"""
from __future__ import annotations

import csv
import datetime
import time

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QSizePolicy, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from addons.leads.month_usage import MonthUsage
from addons.leads.workers import CreditsCallWorker

DAY = 86400


# ── formatting ───────────────────────────────────────────────────────────────

def num(value) -> str:
    """1240 → "1,240"."""
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "0"


def credits_text(value) -> str:
    """"1 credit" / "1,240 credits"."""
    return i18n.t("1 credit") if int(value or 0) == 1 else i18n.t("{n} credits").format(n=num(value))


def rupees(value) -> str:
    """Indian digit grouping: 1234567 → "₹12,34,567"."""
    digits = str(int(value))
    if len(digits) > 3:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        digits = ",".join(parts + [tail])
    return "₹" + digits


def when(ts, with_time: bool = True) -> str:
    """An epoch as "Oct 5, 2026, 12:30 PM" in the customer's own time zone."""
    try:
        d = datetime.datetime.fromtimestamp(int(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    day = f"{d.strftime('%b')} {d.day}, {d.year}"
    if not with_time:
        return day
    return f"{day}, {d.strftime('%I:%M %p').lstrip('0')}"


def price_text(offer: dict) -> str:
    """"₹4,999 / month", "₹49,999 / year", or "Ask Alphakore" until a price is set."""
    price = offer.get("price_inr")
    if price is None:
        return i18n.t("Ask Alphakore")
    if offer.get("kind") == "pack":
        return i18n.t("{p} once").format(p=rupees(price))
    days = int(offer.get("cycle_days") or 30)
    every = (i18n.t("month") if days == 30 else i18n.t("year") if days in (365, 366)
             else i18n.t("{d} days").format(d=days))
    return i18n.t("{p} / {every}").format(p=rupees(price), every=every)


def kind_name(kind: str) -> str:
    return {"grant": i18n.t("Top-up"), "spend": i18n.t("Spent"), "refund": i18n.t("Refunded"),
            "adjust": i18n.t("Correction"), "allowance": i18n.t("Plan credits"),
            "expire": i18n.t("Expired")}.get(kind, kind)


_SLICES = ("#111110", "#C8161D", "#6B6A65", "#1F6B43", "#7A5A0E", "#A9A8A3", "#2A2A28",
           "#CBCAC4")                   # the brand: ink, red, stone greys, the two status tones


def _fit(dialog, width: int, height: int) -> None:
    """Size a dialog for this screen: the size it wants, or what the screen has
    (a 1366x768 laptop is smaller than a designer's monitor)."""
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is not None:
        room = screen.availableGeometry()
        width, height = min(width, room.width() - 60), min(height, room.height() - 90)
    dialog.resize(width, height)


def _discard(widget) -> None:
    """Take a widget off the screen NOW and free it later. deleteLater() alone waits
    for the event loop, and until it runs the old widget is still painted — on top
    of whatever replaced it."""
    if widget is not None:
        widget.hide()
        widget.setParent(None)
        widget.deleteLater()


def _card_css(name: str) -> str:
    """A bordered surface, scoped by object name so it never cascades onto the
    labels inside it (QLabel is a QFrame)."""
    return (f"QFrame#{name}{{background:{theme.CARD};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CARD}px;}}")


def _card(name: str) -> tuple:
    frame = QFrame()
    frame.setObjectName(name)
    frame.setAttribute(Qt.WA_StyledBackground, True)
    frame.setStyleSheet(_card_css(name))
    col = QVBoxLayout(frame)
    col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_5)
    col.setSpacing(theme.SPACE_3)
    return frame, col


# ── the donut ────────────────────────────────────────────────────────────────

class Donut(QWidget):
    """A ring cut into slices, with two lines of text in the middle. With
    nothing used it is a plain grey ring, the way Apollo draws an empty one."""

    THICKNESS = 36

    def __init__(self, parent=None):
        super().__init__(parent)
        self._slices: list = []
        self._top = ""
        self._bottom = ""
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, slices: list, top: str, bottom: str) -> None:
        """slices: [(value, colour)], values above zero."""
        self._slices = [(float(v), c) for v, c in slices if v and v > 0]
        self._top, self._bottom = top, bottom
        self.update()

    def slices(self) -> list:
        return list(self._slices)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height()) - 8
        t = self.THICKNESS
        ring = QRectF((self.width() - side) / 2 + t / 2, (self.height() - side) / 2 + t / 2,
                      side - t, side - t)
        pen = QPen(theme.c(theme.NEUTRAL[300]), t)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        total = sum(v for v, _ in self._slices)
        if total <= 0:
            p.drawEllipse(ring)
        else:
            start = 90 * 16
            for value, colour in self._slices:
                span = -int(round(value / total * 360 * 16))
                pen.setColor(QColor(colour))
                p.setPen(pen)
                p.drawArc(ring, start, span)
                start += span
        p.setPen(theme.c(theme.TEXT))
        big = QFont(self.font())
        big.setPixelSize(20)
        big.setWeight(QFont.DemiBold)
        p.setFont(big)
        mid = self.rect().center()
        p.drawText(QRectF(mid.x() - 90, mid.y() - 28, 180, 26), Qt.AlignCenter, self._top)
        small = QFont(self.font())
        small.setPixelSize(13)
        p.setFont(small)
        p.setPen(theme.c(theme.NEUTRAL[600]))
        p.drawText(QRectF(mid.x() - 90, mid.y() - 1, 180, 22), Qt.AlignCenter, self._bottom)


# ── the small card: "Team credit usage" ──────────────────────────────────────

class CreditCard(QFrame):
    """Apollo's side-nav widget: how much of the credits is used, how many are
    left, and the two ways on — Upgrade plan and View usage."""

    upgradeRequested = Signal()
    usageRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("creditCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(_card_css("creditCard"))
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_5, theme.SPACE_4, theme.SPACE_5, theme.SPACE_4)
        col.setSpacing(theme.SPACE_2)
        self.title = C.label(i18n.t("Team credit usage"), level="CARD_TITLE")
        col.addWidget(self.title)
        self.headline = C.label("", level="BODY", weight=600)
        col.addWidget(self.headline)
        self.bar = C.ProgressBar(0.0)
        col.addWidget(self.bar)
        self.left = C.label("", level="META")
        self.left.setAlignment(Qt.AlignRight)
        col.addWidget(self.left)
        self.note = C.label("", level="META", wrap=True)
        col.addWidget(self.note)
        self.month = MonthUsage()                # this month's e-mails and numbers; hidden when not counted
        col.addWidget(self.month)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACE_2)
        self.upgrade = C.button(i18n.t("Upgrade plan"), "primary",
                                on_click=self.upgradeRequested.emit)
        self.view = C.button(i18n.t("View usage"), "secondary",
                             on_click=self.usageRequested.emit)
        row.addWidget(self.upgrade)
        row.addWidget(self.view)
        col.addLayout(row)
        self.setMinimumWidth(320)
        self.set_loading()

    def set_loading(self) -> None:
        self.headline.setText(i18n.t("Reading your credits…"))
        self.bar.setVisible(False)
        self.left.setText("")
        self.note.setText("")

    def set_error(self, why: str) -> None:
        self.headline.setText(i18n.t("Your credits couldn't be read"))
        self.bar.setVisible(False)
        self.left.setText("")
        self.note.setText(why or "")

    def set_usage(self, usage: dict) -> None:
        balance = int(usage.get("balance") or 0)
        allowance = int(usage.get("allowance") or 0)
        used = int(usage.get("used") or 0)
        if allowance > 0:
            self.headline.setText(i18n.t("{used} of {total} credits").format(
                used=num(used), total=num(allowance)))
            self.bar.setVisible(True)
            self.bar.set_fraction(min(1.0, used / allowance))
            self.left.setText(i18n.t("{n} left").format(n=credits_text(balance)))
            cycle = usage.get("cycle") or {}
            self.note.setText(i18n.t("Renews {d}").format(d=when(cycle.get("end"), False))
                              if cycle.get("end") else "")
        else:
            self.headline.setText(i18n.t("{n} left").format(n=credits_text(balance)))
            self.bar.setVisible(False)
            self.left.setText("")
            self.note.setText(i18n.t("{n} used in the last 30 days").format(n=credits_text(used)))


class CreditPopover(QFrame):
    """The card, dropped from the balance pill. Click anywhere else and it goes."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("creditPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QFrame#creditPopover{{background:{theme.CARD};"
                           f"border:1px solid {theme.BORDER};border-radius:{theme.R_CARD}px;}}")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        self.card = CreditCard(self)
        # The popover is the border; the card inside is only its content.
        self.card.setStyleSheet("QFrame#creditCard{background:transparent;border:none;}")
        col.addWidget(self.card)
        self.card.upgradeRequested.connect(self.close)
        self.card.usageRequested.connect(self.close)

    # The two slots a CreditsCallWorker("usage") is connected to. Methods, not
    # lambdas: Qt drops a connection to a QObject slot when its owner is gone.
    def show_usage(self, _what: str, usage: dict) -> None:
        self.card.set_usage(usage)
        self.adjustSize()

    def show_error(self, _what: str, why: str) -> None:
        self.card.set_error(why)
        self.adjustSize()

    def open_below(self, anchor: QWidget) -> None:
        self.adjustSize()
        corner = anchor.mapToGlobal(QPoint(anchor.width(), anchor.height() + 4))
        self.move(corner.x() - self.width(), corner.y())
        self.show()


# ── Credit usage ─────────────────────────────────────────────────────────────

class CreditUsageDialog(PrismDialog):
    """Apollo's Credit usage page: Overview, Usage details, About credits, with
    the Date / Team member / Features filters over the first two."""

    upgradeRequested = Signal()

    def __init__(self, rates: dict | None = None, parent=None):
        super().__init__(i18n.t("Credit usage"), i18n.t("What your credits were spent on"),
                         icon="chart", parent=parent, scrollable=True)
        _fit(self, 1040, 700)
        self._rates = dict(rates or {})
        self._usage: dict = {}
        self._worker = None
        self._again = False
        self._view = "features"                 # the donut's grouping: features | members
        self._loading = False

        self._tabs = C.Tabs([i18n.t("Overview"), i18n.t("Usage details"), i18n.t("About credits")])
        self.body.addWidget(self._tabs)

        # Date / Team member / Features — over Overview and Usage details.
        self._filters = QWidget()
        # A flow layout: three filters and a status line are wider than a 1366px
        # laptop's dialog, and the last of them must step down a line, not clip.
        frow = C.FlowLayout(self._filters, h_space=theme.SPACE_4, v_space=theme.SPACE_2)
        self.date_box = self._filter(frow, i18n.t("Date"))
        self.member_box = self._filter(frow, i18n.t("Team member"))
        self.feature_box = self._filter(frow, i18n.t("Features"))
        self._status = C.label("", level="META")
        frow.addWidget(self._status)
        self.body.addWidget(self._filters)
        self._fill_dates(cycle=False)
        self.member_box.addItem(i18n.t("All members"), None)
        self.feature_box.addItem(i18n.t("All features"), "")
        for box in (self.date_box, self.member_box, self.feature_box):
            box.currentIndexChanged.connect(self._filter_changed)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_overview())
        self._pages.addWidget(self._build_details())
        self._pages.addWidget(self._build_about())
        self.body.addWidget(self._pages, stretch=1)
        self._tabs.changed.connect(self._show_tab)

        self.footer.set_primary(self.button(i18n.t("Done"), "primary", on_click=self.accept))
        self.reload()

    # -- building -----------------------------------------------------------
    def _filter(self, row, caption: str) -> QComboBox:
        """One "Date [ Current billing cycle v ]" pair, kept together in the flow."""
        box = QComboBox()
        box.setMinimumHeight(C.MIN_TARGET)
        box.setMinimumWidth(200)
        host = QWidget()
        pair = QHBoxLayout(host)
        pair.setContentsMargins(0, 0, 0, 0)
        pair.setSpacing(theme.SPACE_2)
        pair.addWidget(C.label(caption, level="META"))
        pair.addWidget(box)
        row.addWidget(host)
        return box

    def _fill_dates(self, cycle: bool) -> None:
        keep = self.date_box.currentData()
        self.date_box.blockSignals(True)
        self.date_box.clear()
        self.date_box.addItem(i18n.t("Current billing cycle") if cycle else i18n.t("Last 30 days"), "default")
        for days, text in ((7, i18n.t("Last 7 days")), (30, i18n.t("Last 30 days")),
                           (90, i18n.t("Last 90 days"))):
            if days == 30 and not cycle:
                continue                        # already the first entry
            self.date_box.addItem(text, days)
        self.date_box.addItem(i18n.t("All time"), 0)
        at = self.date_box.findData(keep)
        self.date_box.setCurrentIndex(max(0, at))
        self.date_box.blockSignals(False)

    def _build_overview(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.CARD_GAP)
        row = QHBoxLayout()
        row.setSpacing(theme.CARD_GAP)

        left, lcol = _card("usageLeft")
        lcol.addWidget(C.label(i18n.t("Team credit usage"), level="SECTION"))
        self._group = C.Tabs([i18n.t("Features"), i18n.t("Team members")])
        self._group.changed.connect(self._regroup)
        lcol.addWidget(self._group, alignment=Qt.AlignLeft)
        mid = QHBoxLayout()
        mid.setSpacing(theme.SPACE_5)
        self.donut = Donut()
        mid.addWidget(self.donut, stretch=3)
        self._legend = QVBoxLayout()
        self._legend.setSpacing(theme.SPACE_2)
        legend_host = QWidget()
        legend_host.setLayout(self._legend)
        mid.addWidget(legend_host, stretch=2, alignment=Qt.AlignVCenter)
        lcol.addLayout(mid)
        row.addWidget(left, stretch=3)

        right, rcol = _card("usageRight")
        rcol.addWidget(C.label(i18n.t("Overview"), level="SECTION"))
        inner, icol = _card("usageAvailable")
        icol.addWidget(C.label(i18n.t("Available credits"), level="BODY", weight=600))
        self.available = C.label("—", level="PAGE_TITLE")
        icol.addWidget(self.available)
        self.renews = C.label("", level="SUPPORT", wrap=True)
        icol.addWidget(self.renews)
        self.plan_line = C.label("", level="META", wrap=True)
        icol.addWidget(self.plan_line)
        rcol.addWidget(inner)
        self.month = MonthUsage()                # this month's e-mails and numbers; hidden when not counted
        rcol.addWidget(self.month)
        rcol.addStretch(1)
        self.add_credits = C.button(i18n.t("Add more credits"), "primary",
                                    on_click=self.upgradeRequested.emit)
        rcol.addWidget(self.add_credits, alignment=Qt.AlignRight)
        row.addWidget(right, stretch=2)
        col.addLayout(row)

        info, icol2 = _card("usageInfo")
        icol2.addWidget(C.label(i18n.t("Information"), level="SECTION"))
        icol2.addWidget(C.label(i18n.t("NEED MORE CREDITS?"), level="LABEL"),
                        alignment=Qt.AlignHCenter)
        need = C.label(i18n.t("You can upgrade your plan to increase your credit limit, or ask "
                              "Alphakore for a top-up. Nothing is charged until Alphakore confirms."),
                       level="SUPPORT", wrap=True)
        need.setAlignment(Qt.AlignCenter)
        icol2.addWidget(need)
        self.upgrade_btn = C.button(i18n.t("Upgrade plan"), "primary",
                                    on_click=self.upgradeRequested.emit)
        icol2.addWidget(self.upgrade_btn, alignment=Qt.AlignHCenter)
        col.addWidget(info)
        col.addStretch(1)
        return page

    def _build_details(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t("Every movement of your credits, newest first."), level="SUPPORT"))
        top.addStretch(1)
        self.export_btn = C.button(i18n.t("Export CSV"), "secondary", icon_name="download",
                                   on_click=self._export)
        top.addWidget(self.export_btn)
        col.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([i18n.t("When"), i18n.t("What"), i18n.t("Feature"),
                                              i18n.t("Team member"), i18n.t("Credits"),
                                              i18n.t("Balance")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(320)
        self.table.setStyleSheet(
            f"QTableWidget{{background:transparent;border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CONTROL}px;color:{theme.TEXT};gridline-color:transparent;}}"
            f"QTableWidget::item{{padding:6px 10px;color:{theme.TEXT};"
            f"border-bottom:1px solid {theme.HAIRLINE};}}"
            f"QHeaderView::section{{background:transparent;color:{theme.NEUTRAL[600]};border:none;"
            f"border-bottom:1px solid {theme.BORDER};padding:8px 10px;font-weight:600;}}")
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(QHeaderView.Stretch)
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        col.addWidget(self.table, stretch=1)
        self.empty = C.label(i18n.t("Nothing has moved in this period."), level="SUPPORT")
        self.empty.setAlignment(Qt.AlignCenter)
        col.addWidget(self.empty)
        return page

    def _build_about(self) -> QWidget:
        page = QWidget()
        self._about = QVBoxLayout(page)
        self._about.setContentsMargins(0, 0, 0, 0)
        self._about.setSpacing(theme.SPACE_3)
        self._about.addWidget(C.label(i18n.t("What are credits?"), level="SECTION"))
        self._about.addWidget(C.label(
            i18n.t("Credits pay for the lookups Leads makes for you: finding people, finding and "
                   "checking e-mail addresses, researching a company and writing a draft. Filtering, "
                   "saving, importing and sending are free."), level="SUPPORT", wrap=True))
        self._about_grid = QGridLayout()
        self._about_grid.setSpacing(theme.SPACE_3)
        host = QWidget()
        host.setLayout(self._about_grid)
        self._about.addWidget(host)
        self._about.addStretch(1)
        self._fill_about()
        return page

    def _fill_about(self) -> None:
        while self._about_grid.count():
            item = self._about_grid.takeAt(0)
            _discard(item.widget())
        shown = ("people_search", "company_lookup", "domain_lookup", "email_find", "email_verify",
                 "signals", "ai_qualify", "ai_draft")
        names = {a["action"]: a["name"] for a in (self._usage.get("actions") or [])}
        cells = []
        for action in shown:
            entry = self._rates.get(action)
            if entry:
                cells.append((names.get(action) or entry.get("label") or action,
                              credits_text(entry.get("credits", 0)), entry.get("label", "")))
        for i, (title, cost, detail) in enumerate(cells):
            frame, col = _card(f"aboutCell{i}")
            head = QHBoxLayout()
            head.addWidget(C.label(title, level="BODY", weight=600, wrap=True), stretch=1)
            head.addWidget(C.label(cost, level="META", weight=600))
            col.addLayout(head)
            if detail and detail != title:
                col.addWidget(C.label(detail, level="SUPPORT", wrap=True))
            self._about_grid.addWidget(frame, i // 2, i % 2)
        if not cells:
            self._about_grid.addWidget(C.label(i18n.t("The price list isn't loaded yet."),
                                               level="SUPPORT"), 0, 0)

    # -- data ---------------------------------------------------------------
    def params(self) -> dict:
        """What the current filters ask the server for."""
        out: dict = {}
        date = self.date_box.currentData()
        if isinstance(date, int):
            out["min_at"] = 0 if date == 0 else int(time.time()) - date * DAY
        member = self.member_box.currentData()
        if member:
            out["device_id"] = int(member)
        feature = self.feature_box.currentData()
        if feature:
            out["action"] = feature
        return out

    def reload(self) -> None:
        if self._worker is not None:
            self._again = True                  # the answer in flight is for old filters
            return
        self._loading = True
        self._status.setText(i18n.t("Loading…"))
        self._worker = CreditsCallWorker("usage", **self.params())
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _filter_changed(self, _index=0) -> None:
        self.reload()

    def _finish(self) -> None:
        self._worker = None
        self._loading = False
        if self._again:
            self._again = False
            self.reload()

    def _on_done(self, _what: str, usage: dict) -> None:
        self._usage = dict(usage or {})
        self._status.setText("")
        self._finish()
        self.show_usage(self._usage)

    def _on_failed(self, _what: str, why: str) -> None:
        self._status.setText(why or i18n.t("Couldn't read your credits."))
        self._finish()

    # -- showing ------------------------------------------------------------
    def show_usage(self, usage: dict) -> None:
        """Draw one server answer. Public so a test (or the popover) can hand it
        a usage dict without a worker."""
        self._usage = dict(usage or {})
        cycle = self._usage.get("cycle")
        self._fill_dates(cycle=bool(cycle))
        self._fill_combo(self.member_box, i18n.t("All members"), None,
                         [(m["id"], m["name"] + (i18n.t(" (you)") if m.get("you") else ""))
                          for m in self._usage.get("members") or []])
        self._fill_combo(self.feature_box, i18n.t("All features"), "",
                         [(a["action"], a["name"]) for a in self._usage.get("actions") or []])

        balance = int(self._usage.get("balance") or 0)
        allowance = int(self._usage.get("allowance") or 0)
        used = int(self._usage.get("used") or 0)
        if allowance > 0:
            self.available.setText(f"{num(balance)} / {num(allowance)}")
            self.renews.setText(i18n.t("Credits will renew on {d}").format(d=when(cycle.get("end")))
                                if cycle else "")
            self.plan_line.setText(
                (i18n.t("Plan: {p}. ").format(p=self._usage.get("plan_name") or self._usage.get("plan"))
                 if self._usage.get("plan") else "")
                + (i18n.t("Unused credits roll over.") if self._usage.get("rollover")
                   else i18n.t("Unused credits don't roll over.")))
        else:
            self.available.setText(num(balance))
            self.renews.setText(i18n.t("Your credits don't expire. Alphakore tops them up."))
            self.plan_line.setText("")
        self._draw_donut(used, allowance)
        self._fill_table(self._usage.get("activity") or [])
        self._fill_about()

    def _fill_combo(self, box: QComboBox, all_text: str, all_data, items: list) -> None:
        keep = box.currentData()
        box.blockSignals(True)
        box.clear()
        box.addItem(all_text, all_data)
        for data, text in items:
            box.addItem(text, data)
        at = box.findData(keep)
        box.setCurrentIndex(max(0, at))
        box.blockSignals(False)

    def _regroup(self, index: int) -> None:
        self._view = "members" if index == 1 else "features"
        self._draw_donut(int(self._usage.get("used") or 0), int(self._usage.get("allowance") or 0))

    def _draw_donut(self, used: int, allowance: int) -> None:
        rows = (self._usage.get("by_member") if self._view == "members"
                else self._usage.get("by_action")) or []
        slices = [(r["credits"], _SLICES[i % len(_SLICES)]) for i, r in enumerate(rows)]
        top = (i18n.t("{used} of {total}").format(used=num(used), total=num(allowance))
               if allowance > 0 else num(used))
        self.donut.set_data(slices, top, i18n.t("credits used"))
        while self._legend.count():
            item = self._legend.takeAt(0)
            _discard(item.widget())
        total = sum(r["credits"] for r in rows) or 1
        for i, r in enumerate(rows):
            line = QHBoxLayout()
            dot = QLabel("●")
            dot.setStyleSheet(f"color:{_SLICES[i % len(_SLICES)]};font-size:14px;")
            line.addWidget(dot)
            name = r["name"] + (i18n.t(" (you)") if r.get("you") else "")
            line.addWidget(C.label(name, level="SUPPORT"), stretch=1)
            line.addWidget(C.label(f"{num(r['credits'])}  ·  {round(100 * r['credits'] / total)}%",
                                   level="META", weight=600))
            host = QWidget()
            host.setLayout(line)
            line.setContentsMargins(0, 0, 0, 0)
            self._legend.addWidget(host)
        if not rows:
            self._legend.addWidget(C.label(i18n.t("Nothing used in this period."), level="SUPPORT"))

    def _fill_table(self, rows: list) -> None:
        self.table.setRowCount(len(rows))
        for r, e in enumerate(rows):
            cells = (when(e.get("at")), kind_name(e.get("kind", "")), e.get("name") or "",
                     e.get("member") or "", f"{int(e.get('delta') or 0):+,}",
                     num(e.get("balance_after")))
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c >= 4:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, item)
        self.empty.setVisible(not rows)
        self.table.setVisible(bool(rows))

    def _show_tab(self, index: int) -> None:
        self._pages.setCurrentIndex(index)
        self._filters.setVisible(index < 2)

    # -- export -------------------------------------------------------------
    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, i18n.t("Export activity"),
                                              "credit-activity.csv", "CSV (*.csv)")
        if path:
            self.write_csv(path)

    def write_csv(self, path: str) -> int:
        """The activity on screen as a CSV Excel opens cleanly. Returns the rows written."""
        rows = self._usage.get("activity") or []
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            out = csv.writer(f)
            out.writerow(["When", "What", "Feature", "Team member", "Credits", "Balance", "Note"])
            for e in rows:
                out.writerow([when(e.get("at")), kind_name(e.get("kind", "")), e.get("name") or "",
                              e.get("member") or "", e.get("delta"), e.get("balance_after"),
                              e.get("note") or ""])
        self._status.setText(i18n.t("Saved {n} rows.").format(n=len(rows)))
        return len(rows)


# ── Upgrade: Select plan → Add-ons → Payment → Review ────────────────────────

class _OfferCard(QFrame):
    """One plan or pack, as a card that can be picked."""

    chosen = Signal(str)

    def __init__(self, offer: dict, parent=None):
        super().__init__(parent)
        self.offer = offer
        self.setObjectName("offerCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"QFrame#offerCard{{background:{theme.CARD};border:1px solid {theme.BORDER};"
            f"border-radius:{theme.R_CARD}px;}}"
            f"QFrame#offerCard[sel=\"true\"]{{border:2px solid {theme.ACCENT};}}")
        col = QVBoxLayout(self)
        col.setContentsMargins(theme.SPACE_5, theme.SPACE_5, theme.SPACE_5, theme.SPACE_4)
        col.setSpacing(theme.SPACE_2)
        col.addWidget(C.label(offer["name"], level="SECTION"))
        col.addWidget(C.label(price_text(offer), level="PAGE_TITLE" if offer.get("price_inr") is not None
                              else "BODY", weight=600))
        per = (i18n.t("{n} credits, one time").format(n=num(offer["credits"]))
               if offer["kind"] == "pack" else
               i18n.t("{n} credits every {d} days").format(n=num(offer["credits"]),
                                                            d=int(offer.get("cycle_days") or 30)))
        col.addWidget(C.label(per, level="SUPPORT", weight=600))
        if offer.get("blurb"):
            col.addWidget(C.label(offer["blurb"], level="SUPPORT", wrap=True))
        col.addStretch(1)
        self.button = C.button(i18n.t("Select"), "secondary", on_click=lambda: self.chosen.emit(offer["key"]))
        col.addWidget(self.button)
        self.state = ""

    def set_state(self, selected: bool, current: bool = False, requested: bool = False) -> None:
        self.setProperty("sel", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if current:
            self.state, text = "current", i18n.t("Current plan")
        elif requested:
            self.state, text = "requested", i18n.t("Requested")
        elif selected:
            self.state, text = "selected", i18n.t("Selected")
        else:
            self.state, text = "", i18n.t("Select")
        self.button.setText(text)
        self.button.setEnabled(not (current or requested))


class UpgradeDialog(PrismDialog):
    """Select plan, Add-ons, Payment, Review — Apollo's flow, ending in a request
    to Alphakore rather than a card form (there is no payment gateway, and this
    dialog says so on its Payment step)."""

    def __init__(self, parent=None):
        super().__init__(i18n.t("Upgrade plan"), i18n.t("Ask Alphakore for more credits"),
                         icon="sparkles", parent=parent, scrollable=True)
        _fit(self, 1040, 700)
        self._offers: list = []
        self._plan = ""
        self._pack = ""
        self._open: set = set()
        self._current_plan = ""
        self._step = 0
        self._worker = None
        self._queue: list = []
        self._sent: list = []
        self._cards: dict = {}

        self._stepper = QHBoxLayout()
        self._stepper.setSpacing(theme.SPACE_5)
        self._step_labels = []
        for i, name in enumerate((i18n.t("Select plan"), i18n.t("Add-ons"),
                                  i18n.t("Payment"), i18n.t("Review"))):
            lab = C.label(f"{i + 1}  {name}", level="SUPPORT")
            self._step_labels.append(lab)
            self._stepper.addWidget(lab)
        self._stepper.addStretch(1)
        host = QWidget()
        host.setLayout(self._stepper)
        self.body.addWidget(host)

        self._banner = C.label("", level="SUPPORT", wrap=True)
        self._banner.setVisible(False)
        self.body.addWidget(self._banner)

        self._pages = QStackedWidget()
        self._plans_host = self._page_grid(i18n.t("Choose your plan"),
                                           i18n.t("A plan's credits renew every cycle."))
        self._packs_host = self._page_grid(i18n.t("Add credits"),
                                           i18n.t("A one-off top-up, on top of your plan. Optional."))
        self._pages.addWidget(self._plans_host[0])
        self._pages.addWidget(self._packs_host[0])
        self._pages.addWidget(self._build_payment())
        self._pages.addWidget(self._build_review())
        self._pages.addWidget(self._build_done())
        self.body.addWidget(self._pages, stretch=1)

        self._back = self.button(i18n.t("Back"), "secondary", on_click=self._go_back)
        self._next = self.button(i18n.t("Next"), "primary", on_click=self._go_next)
        self.footer.add_secondary(self._back)
        self.footer.set_primary(self._next)
        self._show_step(0)
        self._load()

    # -- building -----------------------------------------------------------
    def _page_grid(self, title: str, hint: str) -> tuple:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.addWidget(C.label(title, level="PAGE_TITLE"))
        col.addWidget(C.label(hint, level="SUPPORT", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(theme.CARD_GAP)
        host = QWidget()
        host.setLayout(grid)
        col.addWidget(host)
        empty = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(empty)
        col.addStretch(1)
        return page, grid, empty

    def _build_payment(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.addWidget(C.label(i18n.t("Payment"), level="PAGE_TITLE"))
        card, ccol = _card("payInfo")
        ccol.addWidget(C.label(i18n.t("No card is taken here"), level="SECTION"))
        ccol.addWidget(C.label(
            i18n.t("Alphakore confirms your request, sends you an invoice or a payment link, and "
                   "your credits are added as soon as it is settled. Until then nothing is charged "
                   "and nothing changes."), level="SUPPORT", wrap=True))
        col.addWidget(card)
        col.addWidget(C.label(i18n.t("Anything Alphakore should know? (optional)"), level="META"))
        self._note = QPlainTextEdit()
        self._note.setFixedHeight(96)
        self._note.setPlaceholderText(i18n.t("e.g. start from the 1st, invoice to our accounts team"))
        col.addWidget(self._note)
        col.addStretch(1)
        return page

    def _build_review(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.addWidget(C.label(i18n.t("Review"), level="PAGE_TITLE"))
        card, ccol = _card("reviewCard")
        self._review = C.label("", level="BODY", wrap=True)
        ccol.addWidget(self._review)
        col.addWidget(card)
        self._error = C.label("", level="SUPPORT", wrap=True, colour=theme.ERR_INK)
        self._error.setVisible(False)
        col.addWidget(self._error)
        col.addStretch(1)
        return page

    def _build_done(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_3)
        col.addWidget(C.label(i18n.t("Request sent"), level="PAGE_TITLE"))
        self._done_text = C.label("", level="BODY", wrap=True)
        col.addWidget(self._done_text)
        col.addStretch(1)
        return page

    # -- data ---------------------------------------------------------------
    def _load(self) -> None:
        if self._worker is not None:
            return
        self._banner.setText(i18n.t("Loading the plans…"))
        self._banner.setVisible(True)
        self._worker = CreditsCallWorker("offers")
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, what: str, out: dict) -> None:
        self._worker = None
        if what == "offers":
            self.show_offers(out)
        else:
            self._sent.append(out.get("request") or {})
            self._send_next()

    def _on_failed(self, what: str, why: str) -> None:
        self._worker = None
        if what == "offers":
            self._banner.setText(why or i18n.t("Couldn't load the plans."))
            self._banner.setVisible(True)
        else:
            self._queue = []
            self._error.setText(why or i18n.t("Couldn't send your request."))
            self._error.setVisible(True)
            self._next.setEnabled(True)

    def show_offers(self, out: dict) -> None:
        """Draw the plans and packs from one server answer."""
        self._offers = list(out.get("offers") or [])
        self._open = {r.get("offer_key") for r in (out.get("requests") or [])}
        self._current_plan = out.get("plan") or ""
        self._banner.setVisible(False)
        if self._open:
            names = [o["name"] for o in self._offers if o["key"] in self._open]
            self._banner.setText(i18n.t("You've already asked for {what}. Alphakore will get "
                                        "back to you.").format(what=", ".join(names)))
            self._banner.setVisible(True)
        self._cards = {}
        for host, kind in ((self._plans_host, "plan"), (self._packs_host, "pack")):
            _page, grid, empty = host
            while grid.count():
                item = grid.takeAt(0)
                _discard(item.widget())
            picks = [o for o in self._offers if o["kind"] == kind]
            for i, offer in enumerate(picks):
                card = _OfferCard(offer)
                card.chosen.connect(self._choose)
                self._cards[offer["key"]] = card
                grid.addWidget(card, i // 3, i % 3)
            empty.setText("" if picks else i18n.t("Nothing to choose here yet — ask Alphakore."))
        self._refresh_cards()

    def _choose(self, key: str) -> None:
        offer = next((o for o in self._offers if o["key"] == key), None)
        if offer is None or key in self._open:
            return                              # not on offer, or already asked for
        if offer["kind"] == "plan" and key == self._current_plan:
            return                              # they are on it already
        if offer["kind"] == "plan":
            self._plan = "" if self._plan == key else key
        else:
            self._pack = "" if self._pack == key else key
        self._refresh_cards()

    def _refresh_cards(self) -> None:
        for key, card in self._cards.items():
            picked = key in (self._plan, self._pack)
            card.set_state(picked, current=(key == self._current_plan and card.offer["kind"] == "plan"),
                           requested=key in self._open)

    # -- the steps ----------------------------------------------------------
    def _show_step(self, step: int) -> None:
        self._step = step
        self._pages.setCurrentIndex(step)
        for i, lab in enumerate(self._step_labels):
            state = "done" if (i < step or step == 4) else "now" if i == step else "later"
            lab.setStyleSheet(
                f"font-weight:{700 if state == 'now' else 500};"
                f"color:{theme.TEXT if state == 'now' else theme.NEUTRAL[600] if state == 'done' else theme.NEUTRAL[500]};")
        self._back.setVisible(0 < step < 4)
        if step == 3:
            self._review.setText(self.summary())
            self._error.setVisible(False)
            self._next.setText(i18n.t("Send request"))
            self._next.setEnabled(bool(self._plan or self._pack))
        elif step == 4:
            self._next.setText(i18n.t("Done"))
            self._next.setEnabled(True)
        else:
            self._next.setText(i18n.t("Next"))
            self._next.setEnabled(True)

    def summary(self) -> str:
        """What is about to be sent, in words."""
        lines = []
        for key in (self._plan, self._pack):
            offer = next((o for o in self._offers if o["key"] == key), None)
            if offer is None:
                continue
            if offer["kind"] == "plan":
                what = i18n.t("{n} credits every {d} days").format(
                    n=num(offer["credits"]), d=int(offer.get("cycle_days") or 30))
                lines.append(f"{offer['name']} — {what} — {price_text(offer)}")
            else:
                lines.append(i18n.t("{name}, one time — {price}").format(
                    name=offer["name"], price=price_text(offer)))
        if not lines:
            return i18n.t("You haven't picked anything yet. Go back and choose a plan or a pack.")
        note = self._note.toPlainText().strip()
        if note:
            lines.append(i18n.t("Your note: {n}").format(n=note))
        return "\n".join(lines)

    def _go_back(self) -> None:
        if 0 < self._step < 4:
            self._show_step(self._step - 1)

    def _go_next(self) -> None:
        if self._step == 4:
            self.accept()
        elif self._step == 3:
            self.send()
        else:
            self._show_step(self._step + 1)

    def send(self) -> None:
        """Send the request(s) — one per pick — one after the other."""
        self._queue = [k for k in (self._plan, self._pack) if k]
        self._sent = []
        if not self._queue:
            return
        self._next.setEnabled(False)
        self._error.setVisible(False)
        self._send_next()

    def _send_next(self) -> None:
        if not self._queue:
            if self._sent:
                self._done_text.setText(
                    i18n.t("Alphakore has your request. They will confirm and send you an invoice "
                           "or a payment link, and your credits change as soon as it is settled. "
                           "You'll see them on the Credit usage page."))
                self._show_step(4)
            return
        key = self._queue.pop(0)
        self._worker = CreditsCallWorker("request", offer_key=key,
                                         note=self._note.toPlainText().strip())
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()
