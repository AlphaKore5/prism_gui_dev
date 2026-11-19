"""Price the measured take-off: the GUI face of core.boq_price.

The engine half landed on 10 Sep 2026 (Harsh, `core/boq_price.py`): a
measured `q` becomes a priced Bill of Quantities -- rates from a rate list
the user brings, amounts and totals by arithmetic, exported to Excel with
live formulas. It had no window. This is the window.

The rule the whole add-on lives by holds here too: **no number of record
is ever produced by an AI.** Quantities come from the measurement, rates
from the user's own list (or typed in), and every amount and total is
Decimal arithmetic in the engine. This widget only shows and edits.

Pure widget over the engine's `Boq`: the grid is built from
`boq_price.boq_from_measured()`, edits are read back into `BoqItem`s, and
the three writers (`write_boq_xlsx/csv/pdf`) get the rebuilt `Boq`. The
prompt text the AI stages receive is untouched -- pricing is optional and
happens beside the write-up, never inside it.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDoubleSpinBox, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from addons.boq.measured import _TintDelegate
from widgets import controls as C
from widgets.stepper import ChoiceCard

# Column order in the grid. Rate, Unit, Description and Section are editable;
# Qty is the measurement and Amount is arithmetic, so neither takes typing.
COL_SECTION, COL_ITEM, COL_DESC, COL_UNIT, COL_QTY, COL_RATE, COL_AMOUNT, COL_BASIS = range(8)
_EDITABLE = {COL_SECTION, COL_DESC, COL_UNIT, COL_RATE}


def rate_list_path(cfg: dict) -> str:
    """The price list the customer already gave Inquiry for quoting, if any.
    Read from config, never from the other add-on: a path is plain data."""
    try:
        path = ((cfg or {}).get("inquiry") or {}).get("rate_list") or ""
    except AttributeError:
        path = ""
    return path if path and os.path.exists(path) else ""


def _money(value) -> str:
    quoting = CB.get_quoting()
    return quoting.indian_currency(quoting.rupees(value))


def _qty(value) -> str:
    d = Decimal(value)
    return f"{d:,.2f}" if d != d.to_integral() else f"{int(d):,}"


class _RuleDelegate(_TintDelegate):
    """The tinted delegate, plus the hairline under every row that the preview's
    calm price rows have (the style sheet's grid is switched off)."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        painter.save()
        painter.setPen(QColor(theme.HAIRLINE))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        painter.restore()


class _QuietLine(QLabel):
    """One line of muted text that elides instead of wrapping; the whole text
    stays in text() and the tooltip."""

    def setText(self, text: str):
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(40)
        return hint

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        painter.setFont(self.font())
        shown = self.fontMetrics().elidedText(self.text(), Qt.ElideRight, self.width())
        painter.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, shown)


class _PriceRow(QFrame):
    """One line of the Prices card: the item and its measured quantity, a rate
    field, and the amount. It holds no numbers of its own: the rate is typed
    into the grid's own rate cell (same handler as typing in the grid) and
    everything shown is read back from the line the grid holds."""

    def __init__(self, on_rate, parent=None):
        super().__init__(parent)
        self.setObjectName("priceRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 6, 14, 6)
        row.setSpacing(theme.SPACE_2)
        left = QVBoxLayout()
        left.setSpacing(1)
        self.name = QLabel("")
        self.name.setObjectName("priceRowName")
        self.qty = QLabel("")
        self.qty.setObjectName("priceRowQty")
        left.addWidget(self.name)
        left.addWidget(self.qty)
        row.addLayout(left, stretch=1)
        cur = QLabel("₹")
        cur.setObjectName("priceRowUnit")
        row.addWidget(cur)
        self.rate = QLineEdit()
        self.rate.setObjectName("priceRowRate")
        self.rate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.rate.setFixedWidth(92)
        self.rate.setPlaceholderText(i18n.t("rate"))
        self.rate.editingFinished.connect(lambda: on_rate(self.rate.text()))
        row.addWidget(self.rate)
        self.per = QLabel("")
        self.per.setObjectName("priceRowUnit")
        self.per.setFixedWidth(54)
        row.addWidget(self.per)
        self.amount = QLabel("")
        self.amount.setObjectName("priceRowAmount")
        self.amount.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.amount.setMinimumWidth(104)
        row.addWidget(self.amount)

    def show_line(self, it, rate_text: str, tip: str = ""):
        self.name.setText(it.description)
        self.name.setToolTip(it.description)
        self.qty.setText(f"{_qty(it.quantity)} {it.unit}".strip())
        if not self.rate.hasFocus():
            self.rate.setText(rate_text)
        self.rate.setToolTip(tip)
        self.per.setText(i18n.t("per {unit}").format(unit=it.unit) if it.unit else "")
        priced = bool(it.priced)
        self.amount.setText(f"₹{_money(it.amount)}" if priced else i18n.t("no rate yet"))
        self.amount.setProperty("empty", not priced)
        self.amount.style().unpolish(self.amount)
        self.amount.style().polish(self.amount)


class PricingTable(QWidget):
    """Rate list, the priced grid, the totals, and the three exports."""

    def __init__(self, cfg: dict | None = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._bp = CB.get_boq_price()
        self._quoting = CB.get_quoting()
        self._rates: list = []
        self._rates_note = ""
        self._q: dict | None = None
        self._boq = None
        self._filling = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)

        intro_text = i18n.t(
            "Rates come from your own price list, or you type them in. Amounts "
            "and totals are arithmetic. No AI touches a number here.")

        # ── how to price it: three cards, each one the old control ──────────
        self.card_list = ChoiceCard("file", i18n.t("Use my price list"),
                                    i18n.t("Pick your rate sheet (Excel, PDF or Word)."), compact=True)
        self.card_starter = ChoiceCard("spark", i18n.t("Use typical prices"),
                                       i18n.t("Good for a first estimate. Check them before you send a quote."),
                                       compact=True)
        self.card_none = ChoiceCard("x", i18n.t("No prices"),
                                    i18n.t("Leave the price columns empty for you to fill."), compact=True)
        cards = QHBoxLayout()
        cards.setContentsMargins(0, 0, 0, 0)
        cards.setSpacing(theme.SPACE_3)
        for card in (self.card_list, self.card_starter, self.card_none):
            cards.addWidget(card)
        col.addLayout(cards)
        self.card_list.clicked.connect(self._pick_rates)
        self.card_starter.clicked.connect(self._use_starter)
        self.card_none.clicked.connect(self._use_no_prices)

        # ── rate list ────────────────────────────────────────────────────
        rates_row = QHBoxLayout()
        rates_row.setContentsMargins(0, 0, 0, 0)
        rates_row.setSpacing(theme.SPACE_2)
        self.rates_btn = C.button(i18n.t("Attach your rate list…"), "secondary",
                                  icon_name="paperclip", small=True,
                                  on_click=self._pick_rates)
        rates_row.addWidget(self.rates_btn)
        self.rates_btn.setVisible(False)        # the "Use my price list" card is this button
        self.starter_btn = C.button(i18n.t("Use starter rates"), "tertiary",
                                    small=True, on_click=self._use_starter)
        rates_row.addWidget(self.starter_btn)
        self.starter_btn.setVisible(False)      # the "Use typical prices" card is this button
        self.rates_label = C.label(i18n.t("No rate list yet — every line is unpriced."),
                                   level="SUPPORT")
        rates_row.addWidget(self.rates_label)
        # One quiet line (full text in the tooltip), not a coloured box.
        self.warn = _QuietLine("")
        self.warn.setObjectName("priceWarn")
        self.warn.setVisible(False)
        rates_row.addWidget(self.warn, stretch=1)
        col.addLayout(rates_row)

        # ── the Prices card: calm rows, the summary pinned under them ─────
        self.prices_card = QFrame()
        self.prices_card.setObjectName("pricesCard")
        self.prices_card.setAttribute(Qt.WA_StyledBackground, True)
        card = QVBoxLayout(self.prices_card)
        card.setContentsMargins(0, 0, 0, 0)
        card.setSpacing(0)
        head_row = QHBoxLayout()
        head_row.setContentsMargins(14, 10, 14, 10)
        ptitle = QLabel(i18n.t("Prices"))
        ptitle.setObjectName("pricesTitle")
        head_row.addWidget(ptitle)
        head_row.addStretch(1)
        # The trust line lives in the card's header (full sentence on hover),
        # which leaves room for the totals on a 768px screen.
        phint = QLabel(i18n.t("Type a rate. No AI touches a number here."))
        phint.setObjectName("priceRowUnit")
        phint.setToolTip(intro_text)
        head_row.addWidget(phint)
        card.addLayout(head_row)
        self._rows_box = QWidget()
        self._rows_box.setObjectName("priceRows")
        self._rows_layout = QVBoxLayout(self._rows_box)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(0)
        self._row_widgets: list = []
        self.rows_scroll = QScrollArea()
        self.rows_scroll.setObjectName("priceRowsScroll")
        self.rows_scroll.setWidgetResizable(True)
        self.rows_scroll.setFrameShape(QFrame.NoFrame)
        self.rows_scroll.setWidget(self._rows_box)
        self.rows_scroll.setMaximumHeight(194)      # four lines; the rest scroll inside
        card.addWidget(self.rows_scroll)
        col.addWidget(self.prices_card)

        # ── the grid ─────────────────────────────────────────────────────
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("priceTable")
        self.table.setShowGrid(False)
        self.table.setHorizontalHeaderLabels([
            i18n.t("Section"), i18n.t("Item"), i18n.t("Description"),
            i18n.t("Unit"), i18n.t("Qty"), i18n.t("Rate (₹)"),
            i18n.t("Amount (₹)"), i18n.t("Basis")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setAlternatingRowColors(False)
        self.table.setSortingEnabled(False)
        # Same fix as addons/boq/measured.py's own table (item 16): the
        # real style.qss forces `QTableWidget::item { color: #09090b; }`,
        # which Qt's style sheet engine paints over every item regardless
        # of its own Qt.BackgroundRole/ForegroundRole -- so the unpriced-row
        # warning tint set below (`cell.setBackground(tint)`) would be
        # silently invisible in the real running app, exactly like item
        # 16's Trust dots were, unless something bypasses style.qss's own
        # paint path. _TintDelegate does.
        self.table.setItemDelegate(_RuleDelegate(self.table))
        self.table.verticalHeader().setDefaultSectionSize(40)
        head = self.table.horizontalHeader()
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for column in (COL_QTY, COL_RATE, COL_AMOUNT):
            self.table.horizontalHeaderItem(column).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        for column in (COL_SECTION, COL_ITEM, COL_UNIT, COL_QTY, COL_RATE,
                       COL_AMOUNT, COL_BASIS):
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        row_h = self.table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        self.table.setMinimumHeight(head_h + 6 * row_h + 4)
        self.table.setMaximumHeight(head_h + 12 * row_h + 4)
        self.table.itemChanged.connect(self._on_edited)
        # Section, item code and basis are real columns (still in rows() and the
        # exports) but folded away, so the rows read item / unit / qty / rate / amount.
        self._detail_cols = (COL_SECTION, COL_ITEM, COL_BASIS)
        for column in self._detail_cols:
            self.table.setColumnHidden(column, True)
        self.table.cellChanged.connect(self._sync_row)        # after _on_edited: show what it made
        # The full grid (section, item code, description, unit, basis are
        # editable there) is one click away, under the summary.
        self.table.setVisible(False)
        self.details_btn = C.button(i18n.t("Show the full table"), "tertiary",
                                    small=True, on_click=self._toggle_details)

        # ── the bottom of the sheet ──────────────────────────────────────
        self.summary_box = summary = QFrame()
        summary.setObjectName("priceSummary")
        summary.setAttribute(Qt.WA_StyledBackground, True)
        sum_col = QVBoxLayout(summary)
        sum_col.setContentsMargins(14, 6, 14, 6)
        sum_col.setSpacing(4)
        # Always on screen: sub-total and grand total, one line each, plus a
        # small "details" toggle. Contingency, GST/IGST and the full totals
        # text (CGST/SGST split, amount in words, unpriced count) sit behind it.
        brief = QHBoxLayout()
        brief.setContentsMargins(0, 0, 0, 0)
        brief.setSpacing(theme.SPACE_3)
        brief_col = QVBoxLayout()
        brief_col.setSpacing(0)
        self.subtotal_line = QLabel("")
        self.subtotal_line.setObjectName("priceTotals")
        self.grand_line = QLabel("")
        self.grand_line.setObjectName("priceGrand")
        brief_col.addWidget(self.subtotal_line)
        brief_col.addWidget(self.grand_line)
        brief.addLayout(brief_col, stretch=1)
        self.totals_btn = C.button(i18n.t("Details"), "tertiary", small=True,
                                   on_click=self._toggle_totals)
        brief.addWidget(self.totals_btn, alignment=Qt.AlignVCenter)
        sum_col.addLayout(brief)
        self.totals_more = QWidget()
        more_col = QVBoxLayout(self.totals_more)
        more_col.setContentsMargins(0, 4, 0, 0)
        more_col.setSpacing(4)
        self.totals_more.setVisible(False)
        tail = QHBoxLayout()
        tail.setContentsMargins(0, 0, 0, 0)
        tail.setSpacing(theme.SPACE_2)
        clab = QLabel(i18n.t("Contingency")); clab.setObjectName("priceRowUnit")
        tail.addWidget(clab)
        self.contingency_spin = QDoubleSpinBox()
        self.contingency_spin.setRange(0.0, 50.0)
        self.contingency_spin.setDecimals(1)
        self.contingency_spin.setSuffix(" %")
        self.contingency_spin.setValue(0.0)
        tail.addWidget(self.contingency_spin)
        glab = QLabel(i18n.t("GST")); glab.setObjectName("priceRowUnit")
        tail.addWidget(glab)
        self.gst_spin = QDoubleSpinBox()
        self.gst_spin.setRange(0.0, 50.0)
        self.gst_spin.setDecimals(1)
        self.gst_spin.setSuffix(" %")
        self.gst_spin.setValue(18.0)
        tail.addWidget(self.gst_spin)
        self.interstate_check = QCheckBox(i18n.t("Inter-state (IGST)"))
        self.interstate_check.setToolTip(i18n.t(
            "Ticked: one IGST line. Unticked: CGST + SGST, half each. "
            "The total tax is the same."))
        tail.addWidget(self.interstate_check)
        tail.addStretch(1)
        more_col.addLayout(tail)
        for w in (self.contingency_spin, self.gst_spin):
            w.setFixedSize(96, 28)
            w.valueChanged.connect(self._refresh_totals)
        self.interstate_check.toggled.connect(self._refresh_totals)

        self.totals = QLabel("")
        self.totals.setWordWrap(True)
        self.totals.setObjectName("priceTotals")
        more_col.addWidget(self.totals)
        sum_col.addWidget(self.totals_more)
        card.addWidget(summary)
        col.addWidget(self.details_btn, alignment=Qt.AlignLeft)
        col.addWidget(self.table)

        # ── exports ──────────────────────────────────────────────────────
        exports = QHBoxLayout()
        exports.setContentsMargins(0, 0, 0, 0)
        exports.setSpacing(theme.SPACE_2)
        self.xlsx_btn = C.button(i18n.t("Save as Excel…"), "secondary",
                                 icon_name="file", small=True,
                                 on_click=lambda: self._export("xlsx"))
        self.docx_btn = C.button(i18n.t("Save as Word…"), "secondary", small=True,
                                 on_click=lambda: self._export("docx"))
        self.csv_btn = C.button(i18n.t("Save as CSV…"), "secondary", small=True,
                                on_click=lambda: self._export("csv"))
        self.pdf_btn = C.button(i18n.t("Save as PDF…"), "secondary", small=True,
                                on_click=lambda: self._export("pdf"))
        for b in (self.xlsx_btn, self.docx_btn, self.csv_btn, self.pdf_btn):
            exports.addWidget(b)
        exports.addStretch(1)
        col.addLayout(exports)
        self.saved_label = QLabel("")
        self.saved_label.setWordWrap(True)
        self.saved_label.setStyleSheet(
            f"color: {theme.OK_INK}; background: {theme.OK_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        self.saved_label.setVisible(False)
        col.addWidget(self.saved_label)

        self._mark(self.card_none)
        self._set_have_lines(False)
        # The price list Inquiry already has is the obvious first rate list.
        known = rate_list_path(self.cfg)
        if known:
            self.load_rates(known)

    # ── rate list ────────────────────────────────────────────────────────
    def load_rates(self, path: str) -> bool:
        """Read a price list (CSV / XLSX) into the matcher. False, with the
        reason on screen, when the file cannot be understood."""
        try:
            self._rates = self._quoting.load_rates(path)
        except Exception as e:                              # noqa: BLE001
            self._rates = []
            self._say_warn(str(e))
            return False
        self._rates_note = ""
        self.rates_label.setText(i18n.t(
            "{n} rates from {name}").format(n=len(self._rates),
                                            name=os.path.basename(path)))
        self._say_warn("")
        self._rebuild()
        self._mark(self.card_list)
        return True

    def _use_starter(self):
        self._rates = self._bp.starter_rate_items()
        self._rates_note = self._bp.STARTER_RATES_NOTE
        self.rates_label.setText(i18n.t("{n} starter rates (indicative)").format(
            n=len(self._rates)))
        self._say_warn(self._rates_note)
        self._rebuild()
        self._mark(self.card_starter)

    def _use_no_prices(self):
        """Back to the state a fresh table starts in: no rate list, every line unpriced."""
        self._rates = []
        self._rates_note = ""
        self.rates_label.setText(i18n.t("No rate list yet — every line is unpriced."))
        self._say_warn("")
        self._rebuild()
        self._mark(self.card_none)

    def _mark(self, card):
        for c in (self.card_list, self.card_starter, self.card_none):
            c.set_selected(c is card)

    def _toggle_details(self):
        show = self.table.isHidden()
        self.table.setVisible(show)
        for column in self._detail_cols:
            self.table.setColumnHidden(column, not show)
        self.details_btn.setText(i18n.t("Hide the full table") if show
                                 else i18n.t("Show the full table"))

    # ── the calm rows (display; the grid holds the data) ─────────────────
    def _render_rows(self):
        for w in self._row_widgets:
            self._rows_layout.removeWidget(w)
            w.hide()
            w.deleteLater()
        self._row_widgets = []
        items = self._boq.items if self._boq is not None else []
        for r, _it in enumerate(items):
            w = _PriceRow(lambda text, r=r: self._rate_typed(r, text))
            self._rows_layout.addWidget(w)
            self._row_widgets.append(w)
            self._show_row(r)

    def _show_row(self, r: int):
        if r >= len(self._row_widgets) or self._boq is None:
            return
        cell = self.table.item(r, COL_RATE)
        self._row_widgets[r].show_line(self._boq.items[r], cell.text() if cell else "",
                                       cell.toolTip() if cell else "")

    def _rate_typed(self, r: int, text: str):
        """A rate typed in a row goes into the grid's own rate cell, so the
        grid's handler (_on_edited) prices it exactly as typing in the grid."""
        cell = self.table.item(r, COL_RATE)
        if cell is not None and cell.text() != text.strip():
            cell.setText(text.strip())

    def _sync_row(self, r: int, _c: int = 0):
        if not self._filling:
            self._show_row(r)

    def _pick_rates(self):
        from widgets import file_pick
        path = file_pick.open_file(self, "Your rate list", "boq-rates", file_pick.PRICES, self.cfg)
        if path:
            self.load_rates(path)

    # ── data ─────────────────────────────────────────────────────────────
    def set_quantities(self, q: dict, title: str = ""):
        self._q = q
        self._title = title or i18n.t("Bill of Quantities")
        self._rebuild()

    def _rebuild(self):
        """A fresh draft from the measurement and whatever rate list is
        loaded. Called when either changes; hand edits are re-applied by the
        user, which is the honest thing when the rate list itself changed."""
        if self._q is None:
            return
        self._boq = self._bp.boq_from_measured(
            self._q, rate_items=self._rates or None, title=self._title)
        self._fill()

    def _fill(self):
        self._filling = True
        self.table.setRowCount(len(self._boq.items))
        for r, it in enumerate(self._boq.items):
            self._fill_row(r, it)
        self._filling = False
        self._set_have_lines(bool(self._boq.items))
        self._render_rows()
        self._refresh_totals()

    def _fill_row(self, r: int, it):
        cells = {
            COL_SECTION: it.section, COL_ITEM: it.code, COL_DESC: it.description,
            COL_UNIT: it.unit, COL_QTY: _qty(it.quantity),
            COL_RATE: (f"{it.rate:,.2f}" if it.priced else ""),
            COL_AMOUNT: (_money(it.amount) if it.priced else ""),
            COL_BASIS: it.remark or (i18n.t("measured") if it.source.startswith("measured")
                                     else it.source),
        }
        tint = theme.qcolor(theme.WARN_BG) if not it.priced else None
        for c, text in cells.items():
            cell = QTableWidgetItem(text)
            if c in (COL_QTY, COL_RATE, COL_AMOUNT):
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if c not in _EDITABLE:
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
            if c in (COL_QTY, COL_RATE, COL_AMOUNT):
                font = QFont(theme.FONT_MONO)
                font.setPixelSize(13)
                font.setBold(c == COL_AMOUNT)
                cell.setFont(font)
            if tint is not None:
                cell.setBackground(tint)
            if c == COL_RATE and not it.priced:
                cell.setToolTip(i18n.t("No confident rate — type one in, "
                                       "or attach a rate list that has it."))
            self.table.setItem(r, c, cell)

    def _on_edited(self, cell: QTableWidgetItem):
        if self._filling or self._boq is None:
            return
        r, c = cell.row(), cell.column()
        if r >= len(self._boq.items) or c not in _EDITABLE:
            return
        it = self._boq.items[r]
        text = cell.text().strip()
        if c == COL_RATE:
            try:
                it.rate = self._quoting.to_decimal(text) if text else Decimal(0)
            except (InvalidOperation, ValueError):
                it.rate = Decimal(0)
            if it.priced and it.remark.startswith("library rate is per"):
                it.remark = ""              # the person settled the unit question
        elif c == COL_UNIT:
            it.unit = text or it.unit
        elif c == COL_DESC:
            it.description = text or it.description
        elif c == COL_SECTION:
            it.section = text or "Measured Works"
        self._filling = True
        self._fill_row(r, it)
        self._filling = False
        self._refresh_totals()

    def boq(self):
        """The priced BOQ as the grid shows it now, with the sheet-level
        figures from the controls. What every export writes."""
        if self._boq is None:
            return None
        self._boq.contingency_pct = self._quoting.to_decimal(self.contingency_spin.value())
        self._boq.gst_pct = self._quoting.to_decimal(self.gst_spin.value())
        self._boq.interstate = self.interstate_check.isChecked()
        notes = [n for n in self._boq.notes if n != self._bp.STARTER_RATES_NOTE]
        if self._rates_note:
            notes.append(self._rates_note)
        self._boq.notes = notes
        return self._boq

    def rows(self) -> list:
        """What is on screen, row by row -- for tests and for eyes."""
        out = []
        for r in range(self.table.rowCount()):
            out.append(tuple((self.table.item(r, c).text() if self.table.item(r, c) else "")
                             for c in range(8)))
        return out

    # ── totals ───────────────────────────────────────────────────────────
    def _toggle_totals(self):
        show = self.totals_more.isHidden()
        self.totals_more.setVisible(show)
        self.totals_btn.setText(i18n.t("Hide details") if show else i18n.t("Details"))

    def _refresh_totals(self, *_):
        boq = self.boq()
        if boq is None or not boq.items:
            self.totals.setText("")
            self.subtotal_line.setText("")
            self.grand_line.setText("")
            return
        unpriced = len(boq.unpriced())
        parts = [
            i18n.t("Sub-total ₹{v}").format(v=_money(boq.subtotal())),
        ]
        if boq.contingency_pct > 0:
            parts.append(i18n.t("contingency ₹{v}").format(v=_money(boq.contingency_amount())))
        if boq.interstate:
            parts.append(i18n.t("IGST ₹{v}").format(v=_money(boq.gst_amount())))
        else:
            half = _money(boq.gst_amount() / 2)
            parts.append(i18n.t("CGST ₹{h} + SGST ₹{h}").format(h=half))
        text = " · ".join(parts) + "\n" + i18n.t(
            "Grand total ₹{v} — {words}").format(
            v=_money(boq.grand_total()), words=self._bp.amount_in_words(boq.grand_total()))
        if unpriced:
            text += "\n" + i18n.t(
                "⚠ {n} of {of} lines have no rate and are not in the total.").format(
                n=unpriced, of=len(boq.items))
        self.totals.setText(text)
        # The two lines that stay on screen: same Boq figures, shorter words.
        self.subtotal_line.setText(i18n.t("Sub-total ₹{v}").format(v=_money(boq.subtotal()))
                                   + (i18n.t("  ·  {n} of {of} lines have no rate yet").format(
                                       n=unpriced, of=len(boq.items)) if unpriced else ""))
        self.grand_line.setText(i18n.t("Grand total ₹{v} incl. tax").format(
            v=_money(boq.grand_total())))

    # ── exports ──────────────────────────────────────────────────────────
    def export(self, kind: str, path: str) -> str:
        """Write the priced BOQ to `path` as xlsx / docx / csv / pdf. Raises
        the engine's BoqError with a plain reason when it cannot."""
        boq = self.boq()
        writer = {"xlsx": self._bp.write_boq_xlsx, "docx": self._bp.write_boq_docx,
                  "csv": self._bp.write_boq_csv,
                  "pdf": self._bp.write_boq_pdf}[kind]
        return writer(boq, path)

    def _export(self, kind: str):
        if self._boq is None:
            return
        filters = {"xlsx": i18n.t("Excel workbook (*.xlsx)"),
                   "docx": i18n.t("Word document (*.docx)"),
                   "csv": i18n.t("CSV (*.csv)"),
                   "pdf": i18n.t("PDF (*.pdf)")}[kind]
        from widgets import file_pick
        path = file_pick.save_file(self, "Save the priced BOQ", "boq-save", f"Priced_BOQ.{kind}", filters, self.cfg)
        if not path:
            return
        if not path.lower().endswith(f".{kind}"):
            path += f".{kind}"
        try:
            self.export(kind, path)
        except Exception as e:                              # noqa: BLE001
            self._say_warn(str(e))
            return
        self.saved_label.setText(i18n.t("Saved → {path}").format(path=path))
        self.saved_label.setVisible(True)

    # ── small helpers ────────────────────────────────────────────────────
    def _say_warn(self, text: str):
        self.warn.setText(f"⚠ {text}" if text else "")
        self.warn.setVisible(bool(text))

    def _set_have_lines(self, have: bool):
        for b in (self.xlsx_btn, self.csv_btn, self.pdf_btn):
            b.setEnabled(have)
