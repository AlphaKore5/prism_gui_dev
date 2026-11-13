"""The Deals board — the screen drafted in "Prism CRM: interface mockups" (3 Nov 2026), section 2.

One column per stage (Qualified · Proposal · Negotiation · PO received · Won), each headed by its name and what it holds; a card per deal with
its value and next step; a deal that has not moved for a week wears a "Stalled" tag. Lost deals leave the board, and closing a deal as Lost
asks why, and as Won asks for the value — the rules deals.py keeps. Nothing here sends anything.

The page reads and writes deals.json itself, through deals.py, in the folder it is given (`set_folder`), as the Sessions and Saved-searches tabs
do. `_ask_value` and `_ask_reason` are the two questions it asks; tests answer them without a window.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDoubleSpinBox, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu, QPushButton, QComboBox,
                               QScrollArea, QSizePolicy, QVBoxLayout, QWidget)

import i18n
import theme
from addons.leads import deals as DL
from addons.leads import result_rows as RR
from addons.leads import store
from dialogs.base import PrismDialog
from widgets import controls as C

_COLUMN_W = 232


class NewDealDialog(PrismDialog):
    """Name, who it is with, what it is worth, where it starts, what happens next."""

    def __init__(self, parent=None, company: str = "", title: str = ""):
        super().__init__(i18n.t("New deal"), i18n.t("Something you are trying to win"), icon="briefcase", parent=parent)
        self.title_edit = QLineEdit(title)
        self.title_edit.setPlaceholderText(i18n.t("Panel order, Proposal for…"))
        self.company_edit = QLineEdit(company)
        self.company_edit.setPlaceholderText(i18n.t("Who it is with"))
        self.value_edit = QDoubleSpinBox()
        self.value_edit.setRange(0, 9_999_999_999)
        self.value_edit.setDecimals(0)
        self.value_edit.setGroupSeparatorShown(True)
        self.value_edit.setPrefix("₹ ")
        self.stage_edit = QComboBox()
        self.stage_edit.addItems(list(DL.STAGES))
        self.next_edit = QLineEdit()
        self.next_edit.setPlaceholderText(i18n.t("Call Thursday"))
        for name, widget in ((i18n.t("Deal"), self.title_edit), (i18n.t("Company"), self.company_edit),
                             (i18n.t("Value"), self.value_edit), (i18n.t("Stage"), self.stage_edit),
                             (i18n.t("Next step"), self.next_edit)):
            self.body.addWidget(C.label(name, level="SUPPORT", weight=600))
            self.body.addWidget(widget)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Add deal"), "primary", on_click=self.accept))
        self.resize(420, 520)

    def values(self) -> dict:
        return {"title": self.title_edit.text(), "company": self.company_edit.text(), "value": self.value_edit.value(),
                "stage": self.stage_edit.currentText(), "next_step": self.next_edit.text()}


class _Card(QFrame):
    """One deal."""

    def __init__(self, deal: DL.Deal, stalled: int, moves, parent=None):
        super().__init__(parent)
        self.deal = deal
        self.setObjectName("dealCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        edge = theme.WARN_INK if stalled else theme.HAIRLINE
        self.setStyleSheet(f"QFrame#dealCard{{background:{theme.CARD};border:1px solid {edge};border-radius:{theme.R_CONTROL}px;}}")
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 9, 10, 9)
        col.setSpacing(3)
        title = RR._Elided(deal.title, f"color:{theme.TEXT};font-size:13px;font-weight:600;background:transparent;border:none;")
        col.addWidget(title)
        if deal.company:
            col.addWidget(RR._Elided(deal.company, f"color:{theme.NEUTRAL[600]};font-size:12px;background:transparent;border:none;"))
        value = QLabel(DL.inr(deal.value) if deal.value else i18n.t("No value yet"))
        value.setStyleSheet(f"color:{theme.TEXT if deal.value else theme.NEUTRAL[500]};font-size:12px;background:transparent;border:none;")
        col.addWidget(value)
        if deal.next_step:
            col.addWidget(RR._Elided(deal.next_step, f"color:{theme.NEUTRAL[600]};font-size:12px;background:transparent;border:none;"))
        if stalled:
            tag = RR.pill(i18n.t("Stalled {n}d").format(n=stalled), "warn")
            col.addWidget(tag, alignment=Qt.AlignLeft)
        if moves:
            self.move_btn = QPushButton(i18n.t("Move"))
            self.move_btn.setCursor(Qt.PointingHandCursor)
            self.move_btn.setFixedHeight(24)
            self.move_btn.setStyleSheet(
                f"QPushButton{{background:transparent;color:{theme.NEUTRAL[700]};border:1px solid {theme.NEUTRAL[300]};"
                f"border-radius:{theme.R_CHIP}px;padding:0 10px;font-size:12px;font-weight:600;}}"
                f"QPushButton:hover{{background:{theme.NEUTRAL[100]};}}"
                f"QPushButton::menu-indicator{{image:none;width:0px;}}")
            self.menu = QMenu(self.move_btn)
            self.actions_by_stage = {}
            for stage, label, call in moves:
                act = self.menu.addAction(label)
                act.triggered.connect(lambda _=False, c=call: c())
                self.actions_by_stage[stage] = act
            self.move_btn.setMenu(self.menu)
            col.addWidget(self.move_btn, alignment=Qt.AlignLeft)


class DealsPage(QWidget):
    """The board."""

    changed = Signal()                      # a deal was added, moved or removed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._folder = ""
        self._deals: list = []
        self._today: Optional[date] = None
        self.cards: list = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QFrame()
        head.setObjectName("dealsHead")
        head.setStyleSheet(f"QFrame#dealsHead{{background:{theme.CARD};border:none;border-bottom:1px solid {theme.HAIRLINE};}}")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(theme.SPACE_4, theme.SPACE_3, theme.SPACE_4, theme.SPACE_3)
        titles = QVBoxLayout()
        titles.setSpacing(2)
        titles.addWidget(C.label(i18n.t("Deals"), level="SECTION", weight=700))
        self.summary = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        titles.addWidget(self.summary)
        hl.addLayout(titles, 1)
        # A lambda, not new_deal itself: clicked passes its "checked" flag, which new_deal would take for the company's name.
        self.new_btn = RR.button(i18n.t("New deal"), True, lambda _checked=False: self.new_deal())
        hl.addWidget(self.new_btn, alignment=Qt.AlignVCenter)
        outer.addWidget(head)

        self.status = C.label("", level="SUPPORT", colour=theme.ERR_INK, wrap=True)
        self.status.setContentsMargins(theme.SPACE_4, theme.SPACE_2, theme.SPACE_4, 0)
        self.status.hide()
        outer.addWidget(self.status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(f"QScrollArea{{background:{theme.CANVAS};border:none;}}")
        self._host = QWidget()
        self._row = QHBoxLayout(self._host)
        self._row.setContentsMargins(theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4)
        self._row.setSpacing(theme.SPACE_3)
        scroll.setWidget(self._host)
        outer.addWidget(scroll, 1)
        foot = C.label(i18n.t("Lost deals leave the board. Closing a deal as Lost asks why, and Won asks for the value."),
                       level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        foot.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, theme.SPACE_3)
        outer.addWidget(foot)
        self.refresh()

    # ── data ─────────────────────────────────────────────────────────────────
    def set_folder(self, folder: str) -> None:
        self._folder = folder or ""
        self.refresh()

    def set_today(self, today: Optional[date]) -> None:
        """Tests pin the day; the app leaves it to the clock."""
        self._today = today
        self._draw()

    def deals(self) -> list:
        return list(self._deals)

    def refresh(self) -> None:
        self._deals = DL.list_deals(self._folder) if self._folder else []
        self._draw()

    # ── drawing ──────────────────────────────────────────────────────────────
    def _draw(self) -> None:
        while self._row.count():
            item = self._row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()                      # hidden first: a detached widget a queued show reaches opens as a window
                w.setParent(None)
                w.deleteLater()
        self.cards = []
        today = self._today or date.today()
        board = DL.by_stage(self._deals)
        for stage in DL.STAGES + (DL.WON,):
            self._row.addWidget(self._column(stage, board[stage], today))
        self._row.addStretch(1)
        open_value = DL.open_pipeline(self._deals)
        won = DL.won_in_month(self._deals, today)
        self.summary.setText(
            i18n.t("No deals yet. Add one when someone asks for a price.") if not self._deals else
            i18n.t("Open pipeline {open} · won this month {won}").format(open=DL.inr(open_value), won=DL.inr(won)))

    def _column(self, stage: str, deals: list, today: date) -> QWidget:
        col = QFrame()
        col.setObjectName("dealCol")
        col.setAttribute(Qt.WA_StyledBackground, True)
        col.setFixedWidth(_COLUMN_W)
        col.setStyleSheet(f"QFrame#dealCol{{background:{theme.NEUTRAL[100]};border:none;border-radius:{theme.R_CARD}px;}}")
        lay = QVBoxLayout(col)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(C.label(i18n.t(stage), level="SUPPORT", weight=700))
        top.addStretch(1)
        top.addWidget(C.label(DL.inr(DL.total(deals)) if deals else "", level="SUPPORT", colour=theme.NEUTRAL[600]))
        lay.addLayout(top)
        for d in deals:
            card = _Card(d, DL.stalled_days(d, today), self._moves_for(d))
            self.cards.append(card)
            lay.addWidget(card)
        if not deals:
            lay.addWidget(C.label(i18n.t("Nothing here yet"), level="SUPPORT", colour=theme.NEUTRAL[500]))
        lay.addStretch(1)
        return col

    def _moves_for(self, deal: DL.Deal) -> list:
        moves = []
        for stage in DL.STAGES + (DL.WON,):
            if stage != deal.stage:
                label = i18n.t("Move to {stage}").format(stage=i18n.t(stage))
                moves.append((stage, label, lambda s=stage, i=deal.id: self.move(i, s)))
        moves.append((DL.LOST, i18n.t("Lost…"), lambda i=deal.id: self.move(i, DL.LOST)))
        return moves

    # ── doing ────────────────────────────────────────────────────────────────
    def _say(self, text: str) -> None:
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def new_deal(self, company: str = "", title: str = "") -> Optional[DL.Deal]:
        dlg = NewDealDialog(self, company=company, title=title)
        # Off the CLASS: PySide 6.11 has no instance attribute for it (filter_panel._ask, 24-Sep-2026).
        if dlg.exec() != PrismDialog.Accepted:
            return None
        return self.add(**dlg.values())

    def add(self, **fields) -> Optional[DL.Deal]:
        try:
            deal = DL.add(self._folder, **fields)
        except (DL.DealError, store.StoreError) as e:
            self._say(str(e))
            return None
        self._say("")
        self.refresh()
        self.changed.emit()
        return deal

    def _ask_value(self, deal: DL.Deal) -> Optional[float]:
        value, ok = QInputDialog.getDouble(self, i18n.t("Won"), i18n.t("What was {deal} worth, in rupees?").format(deal=deal.title),
                                           deal.value, 0, 9_999_999_999, 0)
        return value if ok else None

    def _ask_reason(self, deal: DL.Deal) -> Optional[str]:
        reason, ok = QInputDialog.getItem(self, i18n.t("Lost"), i18n.t("Why was {deal} lost?").format(deal=deal.title),
                                          [i18n.t(r) for r in DL.LOST_REASONS], 0, False)
        return reason if ok else None

    def move(self, deal_id: str, stage: str) -> bool:
        deal = next((d for d in self._deals if d.id == deal_id), None)
        if deal is None:
            return False
        value, reason = None, ""
        if stage == DL.WON and deal.value <= 0:
            value = self._ask_value(deal)
            if value is None:
                return False
        elif stage == DL.LOST:
            reason = self._ask_reason(deal)
            if not reason:
                return False
        try:
            moved = DL.move(self._folder, deal_id, stage, value=value, reason=reason or "")
        except (DL.DealError, store.StoreError) as e:
            self._say(str(e))
            return False
        self._say("")
        self.refresh()
        self.changed.emit()
        return moved

    def remove(self, deal_id: str) -> bool:
        try:
            gone = DL.remove(self._folder, deal_id)
        except store.StoreError as e:
            self._say(str(e))
            return False
        self.refresh()
        self.changed.emit()
        return gone
