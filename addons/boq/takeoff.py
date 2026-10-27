"""An industry's own PDF-takeoff, embedded compactly in BoqDialog.

Item 26's decision: the Industry dropdown (addons/boq/dialog.py) picks
which whole rule-set runs, and that rule-set's own flow has three parts
-- a calibration/preview step (which line colour is which, same as
hvac_takeoff.py's own standalone "Step 1"), extraction, and a review of
what was read before any of it reaches the BOQ prompt. Step 1 stays
folded away by default (`_LayerMapping`'s own toggle) so Prism's main
screen does not grow a second, cluttered PDF-reading UI for the common
case of someone who never opens it.

Only HVAC has a real rule-set (addons/boq/industries.py); this dialog
itself knows nothing HVAC-specific -- it only calls `industries.*`, so a
second industry's own takeoff plugs into the SAME dialog once
`industries.py` grows an entry for it.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QAbstractItemView, QCheckBox, QHeaderView,
)

import i18n
import theme
from widgets import controls as C
from addons.boq import industries
from addons.boq.measured import _TintDelegate
from addons.boq.workers import HvacTakeoffWorker

COL_TRUST, COL_KIND, COL_TEXT, COL_CONF = range(4)


class _ReviewTable(QWidget):
    """The Step-2 result, one row per text label actually read off the
    drawing (sizes, CFM, TR tags, room notes) -- the only readings with
    real, varying confidence; a duct run's own length is exact vector
    geometry and carries nothing to second-guess, so it is not in this
    table at all (it is in the plain-text summary this dialog hands
    back). Green/yellow from the SAME 0.6 cutoff hvac_takeoff's own
    "unread" warning already uses -- not a second, separate judgement.
    Double-click a TR/CFM row's text to correct a misread number; a size
    row is shown but not editable (see industries.EDITABLE_KINDS)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.industry = ""
        self.result: dict | None = None
        self._rows: list[dict] = []
        self._filling = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_2)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([
            i18n.t("Trust"), i18n.t("Reading"), i18n.t("Text"), i18n.t("Confidence")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked
                                   | QAbstractItemView.EditKeyPressed)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setItemDelegate(_TintDelegate(self.table))
        self.table.itemChanged.connect(self._on_edited)
        head = self.table.horizontalHeader()
        head.setSectionResizeMode(COL_TRUST, QHeaderView.Fixed)
        self.table.setColumnWidth(COL_TRUST, 36)
        head.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        row_h = self.table.verticalHeader().defaultSectionSize()
        self.table.setMaximumHeight(head.sizeHint().height() + 8 * row_h + 4)
        col.addWidget(self.table)

        legend = C.label(i18n.t(
            "Green — read confidently. Yellow — worth a look before this "
            "goes into the BOQ. Double-click a TR or CFM reading's text to "
            "correct it; a size reading is shown but not editable here "
            "(it is already paired with the duct it measures)."),
            level="SUPPORT", wrap=True)
        col.addWidget(legend)

    def set_result(self, industry: str, result: dict):
        self.industry = industry
        self.result = result
        self._rows = industries.review_rows(industry, result)
        self._render()

    def _render(self):
        self._filling = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(self._rows))
        for r, row in enumerate(self._rows):
            confident = row["conf"] >= industries.CONFIDENT
            bg = theme.qcolor(theme.OK_BG if confident else theme.WARN_BG)
            ink = theme.qcolor(theme.OK_INK if confident else theme.WARN_INK)

            dot = QTableWidgetItem("●")
            dot.setForeground(ink)
            dot.setTextAlignment(Qt.AlignCenter)
            dot.setBackground(bg)
            dot.setFlags(dot.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_TRUST, dot)

            kind_item = QTableWidgetItem(row["kind"])
            kind_item.setBackground(bg)
            kind_item.setFlags(kind_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_KIND, kind_item)

            text_item = QTableWidgetItem(row["text"])
            text_item.setBackground(bg)
            text_item.setData(Qt.UserRole, row["index"])
            if not row["editable"]:
                text_item.setFlags(text_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_TEXT, text_item)

            conf_item = QTableWidgetItem(f'{row["conf"]:.2f}')
            conf_item.setBackground(bg)
            conf_item.setFlags(conf_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_CONF, conf_item)
        self.table.setSortingEnabled(True)
        if not self._rows:
            self.table.setRowCount(1)
            self.table.setItem(0, COL_KIND, QTableWidgetItem(
                i18n.t("No text labels were read off this drawing.")))
        self._filling = False

    def _on_edited(self, cell: QTableWidgetItem):
        if self._filling or cell.column() != COL_TEXT or self.result is None:
            return
        row_index = cell.data(Qt.UserRole)
        ok = industries.apply_review_edit(
            self.industry, self.result, row_index, cell.text().strip())
        r = cell.row()
        self._filling = True
        if ok:
            self._rows[r]["conf"] = 1.0
            self._rows[r]["text"] = cell.text().strip()
            for c, item in ((COL_TRUST, self.table.item(r, COL_TRUST)),
                            (COL_KIND, self.table.item(r, COL_KIND)),
                            (COL_CONF, self.table.item(r, COL_CONF))):
                if item is not None:
                    item.setBackground(theme.qcolor(theme.OK_BG))
            dot = self.table.item(r, COL_TRUST)
            if dot:
                dot.setForeground(theme.qcolor(theme.OK_INK))
            conf_item = self.table.item(r, COL_CONF)
            if conf_item:
                conf_item.setText("1.00")
            cell.setBackground(theme.qcolor(theme.OK_BG))
        else:
            # Not a reading this cell's own kind understands -- the edit
            # is left alone on screen (never silently discarded), but it
            # was NOT folded into the numbers summary_text() reads, so say
            # so rather than let a wrong-looking "it worked" sit there.
            cell.setToolTip(i18n.t(
                "Couldn't read this as a {kind} value — the correction was "
                "not applied.").format(kind=self._rows[r]["kind"]))
        self._filling = False


class IndustryTakeoffDialog(QDialog):
    """Pick a PDF, confirm what each line colour is (Step 1, folded away
    by default), extract, review and correct the readings, then hand the
    result back to BoqDialog exactly like InputMeasurementsDialog does --
    a plain-text summary, treated from there on like any other external
    measurement."""

    def __init__(self, industry: str, parent=None):
        super().__init__(parent)
        self.industry = industry
        self.pdf_path = ""
        self.result: dict | None = None
        self._role_combos: list[tuple[dict, QComboBox]] = []

        self.setWindowTitle(i18n.t("{industry} PDF takeoff").format(industry=industry))
        self.resize(640, 560)
        col = QVBoxLayout(self)
        col.addWidget(C.label(i18n.t(
            "Reads a tender PDF locally -- the drawing itself is never "
            "sent anywhere. Pick the file, confirm what each line colour "
            "is, then extract."), level="SUPPORT", wrap=True))

        pick_row = QHBoxLayout()
        self.pick_btn = C.button(i18n.t("Pick a PDF…"), "secondary",
                                 icon_name="paperclip", small=True,
                                 on_click=self._pick_pdf)
        pick_row.addWidget(self.pick_btn)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        pick_row.addWidget(self.path_label, stretch=1)
        col.addLayout(pick_row)

        settings_row = QHBoxLayout()
        settings_row.addWidget(QLabel(i18n.t("Drawing scale:")))
        self.scale_combo = QComboBox()
        for label in industries.scales(self.industry):
            self.scale_combo.addItem(label, label)
        settings_row.addWidget(self.scale_combo)
        self.ocr_cb = QCheckBox(i18n.t("Read text labels (OCR)"))
        self.ocr_cb.setChecked(True)
        settings_row.addWidget(self.ocr_cb)
        settings_row.addStretch(1)
        col.addLayout(settings_row)

        # Step 1 -- folded away by default; opening the main add-on must
        # not grow a second, cluttered PDF-reading screen for the common
        # case of someone who never needs to touch this.
        self.mapping_btn = C.button("", "tertiary", small=True,
                                    on_click=self._toggle_mapping)
        self.mapping_btn.setVisible(False)
        col.addWidget(self.mapping_btn, alignment=Qt.AlignLeft)
        self.mapping_area = QScrollArea()
        self.mapping_area.setWidgetResizable(True)
        self.mapping_area.setMaximumHeight(220)
        self.mapping_area.setVisible(False)
        self.mapping_inner = QWidget()
        self.mapping_layout = QVBoxLayout(self.mapping_inner)
        self.mapping_area.setWidget(self.mapping_inner)
        col.addWidget(self.mapping_area)

        self.extract_btn = C.button(i18n.t("Extract"), "primary", icon_name="check",
                                    small=True, on_click=self._extract)
        self.extract_btn.setEnabled(False)
        col.addWidget(self.extract_btn, alignment=Qt.AlignLeft)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        # The extractor's own warnings (e.g. "No duct runs found: check
        # the layer mapping") -- found the hard way on a real drawing, 26
        # Oct 2026: these already existed in summary_text()'s own text,
        # but buried in the final hand-off is too late to notice before
        # pressing "Use these measurements" and feeding the BOQ a quiet
        # zero. Same collapsed-list pattern as measured.py's own
        # warn_btn/warn_list, open by default here (unlike there) since
        # there is no result yet to clutter the screen with until
        # extraction has actually run once.
        self.warn_btn = C.button("", "tertiary", small=True,
                                 on_click=self._toggle_warnings)
        self.warn_btn.setVisible(False)
        col.addWidget(self.warn_btn, alignment=Qt.AlignLeft)
        self.warn_list = QListWidget()
        self.warn_list.setVisible(False)
        self.warn_list.setMaximumHeight(140)
        col.addWidget(self.warn_list)

        self.review = _ReviewTable()
        self.review.setVisible(False)
        col.addWidget(self.review, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(C.button(i18n.t("Cancel"), "secondary", on_click=self.reject))
        self.use_btn = C.button(i18n.t("Use these measurements"), "primary",
                                on_click=self._confirm)
        self.use_btn.setEnabled(False)
        btn_row.addWidget(self.use_btn)
        col.addLayout(btn_row)

    # ── Step 1 ───────────────────────────────────────────────────────────

    def _pick_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Tender PDF"), os.path.expanduser("~"), i18n.t("PDF (*.pdf)"))
        if not path:
            return
        self.pdf_path = path
        self.path_label.setText(os.path.basename(path))
        try:
            layers = industries.scan_layers(self.industry, path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "BOQ", i18n.t(
                "Couldn't read that PDF: {error}").format(error=e))
            return
        self._fill_mapping(layers)
        self.extract_btn.setEnabled(bool(layers))

    def _fill_mapping(self, layers: list[dict]):
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._role_combos = []
        role_opts = industries.roles(self.industry)
        for layer in layers:
            row = QHBoxLayout()
            swatch = QLabel()
            swatch.setFixedSize(16, 16)
            swatch.setStyleSheet(
                f"background: {layer['color']}; border-radius: 3px;")
            row.addWidget(swatch)
            ft = layer["length_pt"] / 72  # a plain visual cue, not a measurement
            row.addWidget(QLabel(
                f'{layer["color"]}  {layer["kind"]}  {layer["segments"]} segs  ~{ft:.0f} pt'))
            combo = QComboBox()
            combo.addItems(role_opts)
            row.addWidget(combo)
            row.addStretch(1)
            wrap = QWidget()
            wrap.setLayout(row)
            self.mapping_layout.addWidget(wrap)
            self._role_combos.append((layer, combo))
        self.mapping_btn.setText(i18n.t("▾ Layer mapping ({n} found)").format(n=len(layers)))
        self.mapping_btn.setVisible(bool(layers))
        self.mapping_area.setVisible(False)

    def _toggle_mapping(self):
        show = not self.mapping_area.isVisible()
        self.mapping_area.setVisible(show)
        n = len(self._role_combos)
        arrow = "▴" if show else "▾"
        self.mapping_btn.setText(i18n.t("{arrow} Layer mapping ({n} found)").format(
            arrow=arrow, n=n))

    def _layer_map(self) -> dict:
        return {layer["key"]: combo.currentText() for layer, combo in self._role_combos}

    def _pt_per_ft(self) -> float:
        label = self.scale_combo.currentData()
        return (industries.scales(self.industry).get(label) or 1.0)

    # ── Step 2 ───────────────────────────────────────────────────────────

    def _extract(self):
        if not self.pdf_path:
            return
        # Found on a real drawing, 26 Oct 2026: every layer defaults to
        # "ignore" (the safe default, never a guessed colour), so leaving
        # Step 1 untouched -- easy to do, since it stays folded away on
        # purpose -- runs the whole OCR pass and then reports zero duct
        # runs, with no earlier sign anything was about to go unmeasured.
        # Asking first costs one click and catches it before the wait,
        # not after; "No" still runs it, for a sheet that genuinely has
        # only equipment notes/labels and no duct geometry to pair.
        layer_map = self._layer_map()
        if layer_map and not any(role != "ignore" for role in layer_map.values()):
            answer = QMessageBox.question(
                self, "BOQ", i18n.t(
                    "Every line colour is still set to \"ignore\" in Layer "
                    "mapping above -- extraction will not find any duct "
                    "runs until at least one is set to supply/return (or "
                    "another role). Extract anyway?"),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                self.mapping_area.setVisible(True)
                self.mapping_btn.setText(i18n.t("▴ Layer mapping ({n} found)").format(
                    n=len(self._role_combos)))
                return
        self.extract_btn.setEnabled(False)
        self.use_btn.setEnabled(False)
        self.status.setText(i18n.t("Reading the drawing — a large PDF can take a minute…"))
        self._worker = HvacTakeoffWorker(
            self.industry, self.pdf_path, layer_map, self._pt_per_ft(),
            use_ocr=self.ocr_cb.isChecked())
        self._worker.done.connect(self._on_extracted)
        self._worker.failed.connect(self._on_extract_failed)
        self._worker.start()

    def _on_extracted(self, result: dict):
        self.result = result
        self.review.set_result(self.industry, result)
        self.review.setVisible(True)
        self.extract_btn.setEnabled(True)
        self.use_btn.setEnabled(True)
        n = len(result.get("duct_runs") or [])
        if n:
            self.status.setStyleSheet("")
            self.status.setText(i18n.t("{n} duct run(s) measured.").format(n=n))
        else:
            # Loud on purpose -- the same WARN colour MeasuredTable uses
            # for a row it does not trust, here for the whole result:
            # "0 duct runs" read as ordinary status text is exactly how
            # this went unnoticed on a real drawing until it showed up
            # unexplained in the final BOQ prompt.
            self.status.setStyleSheet(f"color: {theme.WARN_INK};")
            self.status.setText(i18n.t(
                "0 duct runs measured — check Layer mapping above: at "
                "least one line colour needs to be set to supply/return "
                "for this drawing's ductwork to be measured."))
        self._set_warnings(result.get("warnings") or [])

    def _on_extract_failed(self, error: str):
        self.extract_btn.setEnabled(True)
        self.status.setText("")
        QMessageBox.warning(self, "BOQ", error)

    def _set_warnings(self, warnings: list[str]):
        self.warn_list.clear()
        for w in warnings:
            item = QListWidgetItem(f"•  {w}")
            item.setBackground(theme.qcolor(theme.WARN_BG))
            item.setForeground(theme.qcolor(theme.WARN_INK))
            self.warn_list.addItem(item)
        self.warn_btn.setVisible(bool(warnings))
        self.warn_list.setVisible(bool(warnings))
        self._refresh_warn_btn_text(len(warnings))

    def _refresh_warn_btn_text(self, n: int):
        arrow = "▴" if self.warn_list.isVisible() else "▾"
        self.warn_btn.setText(i18n.t("⚠ {n} warning(s) from the extraction {arrow}").format(
            n=n, arrow=arrow))

    def _toggle_warnings(self):
        self.warn_list.setVisible(not self.warn_list.isVisible())
        self._refresh_warn_btn_text(self.warn_list.count())

    # ── handing the result back ─────────────────────────────────────────

    def _confirm(self):
        if self.result is None:
            return
        self.accept()

    def measurements_text(self) -> str:
        if self.result is None:
            return ""
        return industries.summary_text(self.industry, self.result)
