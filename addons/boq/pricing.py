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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDoubleSpinBox, QFileDialog, QHBoxLayout,
    QHeaderView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
from addons.boq.measured import _TintDelegate
from widgets import controls as C

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

        col.addWidget(C.label(i18n.t(
            "Rates come from your own price list, or you type them in. Amounts "
            "and totals are arithmetic. No AI touches a number here."),
            level="SUPPORT", wrap=True))

        # ── rate list ────────────────────────────────────────────────────
        rates_row = QHBoxLayout()
        rates_row.setContentsMargins(0, 0, 0, 0)
        rates_row.setSpacing(theme.SPACE_2)
        self.rates_btn = C.button(i18n.t("Attach your rate list…"), "secondary",
                                  icon_name="paperclip", small=True,
                                  on_click=self._pick_rates)
        rates_row.addWidget(self.rates_btn)
        self.starter_btn = C.button(i18n.t("Use starter rates"), "tertiary",
                                    small=True, on_click=self._use_starter)
        rates_row.addWidget(self.starter_btn)
        self.rates_label = C.label(i18n.t("No rate list yet — every line is unpriced."),
                                   level="SUPPORT", wrap=True)
        rates_row.addWidget(self.rates_label, stretch=1)
        col.addLayout(rates_row)

        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.warn.setStyleSheet(
            f"color: {theme.WARN_INK}; background: {theme.WARN_BG};"
            f" border-radius: {theme.R_CONTROL}px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        self.warn.setVisible(False)
        col.addWidget(self.warn)

        # ── the grid ─────────────────────────────────────────────────────
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels([
            i18n.t("Section"), i18n.t("Item"), i18n.t("Description"),
            i18n.t("Unit"), i18n.t("Qty"), i18n.t("Rate (₹)"),
            i18n.t("Amount (₹)"), i18n.t("Basis")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        # Same fix as addons/boq/measured.py's own table (item 16): the
        # real style.qss forces `QTableWidget::item { color: #09090b; }`,
        # which Qt's style sheet engine paints over every item regardless
        # of its own Qt.BackgroundRole/ForegroundRole -- so the unpriced-row
        # warning tint set below (`cell.setBackground(tint)`) would be
        # silently invisible in the real running app, exactly like item
        # 16's Trust dots were, unless something bypasses style.qss's own
        # paint path. _TintDelegate does.
        self.table.setItemDelegate(_TintDelegate(self.table))
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_DESC, QHeaderView.Stretch)
        for column in (COL_SECTION, COL_ITEM, COL_UNIT, COL_QTY, COL_RATE,
                       COL_AMOUNT, COL_BASIS):
            head.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        row_h = self.table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        self.table.setMinimumHeight(head_h + 6 * row_h + 4)
        self.table.setMaximumHeight(head_h + 12 * row_h + 4)
        self.table.itemChanged.connect(self._on_edited)
        col.addWidget(self.table)

        # ── the bottom of the sheet ──────────────────────────────────────
        tail = QHBoxLayout()
        tail.setContentsMargins(0, 0, 0, 0)
        tail.setSpacing(theme.SPACE_2)
        tail.addWidget(QLabel(i18n.t("Contingency")))
        self.contingency_spin = QDoubleSpinBox()
        self.contingency_spin.setRange(0.0, 50.0)
        self.contingency_spin.setDecimals(1)
        self.contingency_spin.setSuffix(" %")
        self.contingency_spin.setValue(0.0)
        tail.addWidget(self.contingency_spin)
        tail.addWidget(QLabel(i18n.t("GST")))
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
        col.addLayout(tail)
        for w in (self.contingency_spin, self.gst_spin):
            w.valueChanged.connect(self._refresh_totals)
        self.interstate_check.toggled.connect(self._refresh_totals)

        self.totals = C.label("", level="BODY", wrap=True)
        col.addWidget(self.totals)

        # ── exports ──────────────────────────────────────────────────────
        exports = QHBoxLayout()
        exports.setContentsMargins(0, 0, 0, 0)
        exports.setSpacing(theme.SPACE_2)
        self.xlsx_btn = C.button(i18n.t("Save as Excel…"), "primary",
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
        return True

    def _use_starter(self):
        self._rates = self._bp.starter_rate_items()
        self._rates_note = self._bp.STARTER_RATES_NOTE
        self.rates_label.setText(i18n.t("{n} starter rates (indicative)").format(
            n=len(self._rates)))
        self._say_warn(self._rates_note)
        self._rebuild()

    def _pick_rates(self):
        import paths
        start = rate_list_path(self.cfg) or paths.picker_start_dir()
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Your rate list"), start,
            i18n.t("Price lists (*.csv *.xlsx *.xlsm *.pdf *.docx *.txt);;All files (*)"))
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
            if c == COL_AMOUNT:
                font = cell.font()
                font.setBold(True)
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
    def _refresh_totals(self, *_):
        boq = self.boq()
        if boq is None or not boq.items:
            self.totals.setText("")
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
        suggested = os.path.join(os.path.expanduser("~/Downloads"),
                                 f"Priced_BOQ.{kind}")
        path, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save the priced BOQ"), suggested, filters)
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
