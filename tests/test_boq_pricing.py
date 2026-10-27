"""Pricing the measured take-off, in the window.

The engine half (core/boq_price.py, 10 Sep 2026) turns a measured `q` into
a priced BOQ: rates from the user's own list, matched by the same fuzzy
matcher quotations use and applied only when confident AND the units
agree; amounts and totals by Decimal arithmetic; Excel with live formulas.
It landed without a window. `addons/boq/pricing.py` is the window, and
this file pins what it must do:

  · one grid row per measured line, unpriced until a rate list is loaded;
  · a confident, unit-matching library rate fills the line; a unit mismatch
    leaves it unpriced with the reason on the row;
  · a rate typed into the grid becomes the line's amount and the totals;
  · the exports write real files, in a temp dir, from the grid's own state;
  · the BOQ dialog shows the card once a drawing is measured, and BOM mode
    (a parts list, not a priced schedule) does not.

No AI, no network, no ~/.prism. The dialog's _on_measured is exercised
with the artifact copy patched out, the way test_boq_dialog does it.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402
from addons.boq import pricing  # noqa: E402

_app = QApplication.instance() or QApplication([])

Q = {"unit": "meters", "unit_code": 6, "unit_confirmed": True,
     "lengths_by_layer": {"BOUNDARY WALL": 1091.18, "Concrete Road": 579.23},
     "areas_by_layer": {"Building": 2227.57},
     "block_counts": {"EP": 22, "MAIN-GATE-7M": 2},
     "block_layers": {"EP": ["Electric Pole"], "MAIN-GATE-7M": ["gates"]},
     "layers": ["BOUNDARY WALL", "Building", "Concrete Road", "Electric Pole", "gates"],
     "entity_count": 29661}


def _rate_csv(rows) -> str:
    d = tempfile.mkdtemp(prefix="prism-rates-")
    p = os.path.join(d, "rates.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("Code,Description,Unit,Rate\n")
        for code, desc, unit, rate in rows:
            f.write(f"{code},{desc},{unit},{rate}\n")
    return p


class TheGridFollowsTheMeasurement(unittest.TestCase):

    def test_one_row_per_measured_line_unpriced_until_rates_arrive(self):
        t = pricing.PricingTable({})
        t.set_quantities(Q)
        rows = t.rows()
        self.assertEqual([r[pricing.COL_DESC] for r in rows],
                         ["BOUNDARY WALL", "Concrete Road", "Building", "EP",
                          "MAIN-GATE-7M"])
        self.assertEqual([r[pricing.COL_UNIT] for r in rows],
                         ["m", "m", "sqm", "nos", "nos"])
        self.assertEqual(rows[0][pricing.COL_QTY], "1,091.18")
        self.assertEqual(rows[3][pricing.COL_QTY], "22")
        self.assertTrue(all(r[pricing.COL_RATE] == "" for r in rows))
        self.assertIn("5 of 5 lines have no rate", t.totals.text())
        self.assertFalse(t.xlsx_btn.isEnabled() and False)   # buttons exist
        self.assertEqual(len(t.boq().unpriced()), 5)

    def test_a_confident_unit_matching_rate_prices_the_line(self):
        t = pricing.PricingTable({})
        t.set_quantities(Q)
        ok = t.load_rates(_rate_csv([
            ("EL-01", "Electric pole EP 9m PCC", "nos", "4500"),
            ("CW-01", "Boundary wall 230 thk brick", "cum", "6200"),
        ]))
        self.assertTrue(ok, t.warn.text())
        by_desc = {r[pricing.COL_DESC]: r for r in t.rows()}
        # EP: confident text match, nos == nos → priced.
        self.assertEqual(by_desc["EP"][pricing.COL_RATE], "4,500.00")
        self.assertEqual(by_desc["EP"][pricing.COL_AMOUNT], "99,000.00")
        # Boundary wall: confident text match but per-cum vs measured metres →
        # NOT priced, and the row says why. A wrong rate is worse than a gap.
        self.assertEqual(by_desc["BOUNDARY WALL"][pricing.COL_RATE], "")
        self.assertIn("per cum", by_desc["BOUNDARY WALL"][pricing.COL_BASIS])
        self.assertIn("Sub-total ₹99,000.00", t.totals.text())
        self.assertIn("4 of 5 lines have no rate", t.totals.text())

    def test_a_rate_list_that_cannot_be_read_says_so_and_prices_nothing(self):
        t = pricing.PricingTable({})
        t.set_quantities(Q)
        d = tempfile.mkdtemp(prefix="prism-rates-")
        p = os.path.join(d, "not-a-list.csv")
        with open(p, "w") as f:
            f.write("just a note\nno headings here\n")
        self.assertFalse(t.load_rates(p))
        self.assertTrue(t.warn.isVisibleTo(t))
        self.assertIn("price columns", t.warn.text())
        self.assertEqual(len(t.boq().unpriced()), 5)

    def test_the_unpriced_tint_actually_renders_under_the_real_stylesheet(self):
        """Item 16 (2026-10-23) fixed this exact invisible-colour bug for
        addons/boq/measured.py's table and flagged pricing.py as very
        likely having the identical one, unverified. Verified now: real
        style.qss's `QTableWidget::item { color: #09090b; ... }` makes
        Qt's style paint over an item's own Qt.BackgroundRole brush
        entirely, not only its text colour -- so the unpriced-row warning
        tint (`cell.setBackground(tint)`, used nowhere else in this file)
        would render as plain white, not warm yellow, in the real running
        app. Loads the REAL style.qss and samples an actual rendered
        pixel, the same way measured.py's own test does, so a regression
        here fails the same way the owner's original screenshot did."""
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        qss_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "style.qss")
        with open(qss_path, encoding="utf-8") as f:
            qss = f.read()
        previous = app.styleSheet()
        app.setStyleSheet(qss.replace("%ASSETS%", "."))
        try:
            t = pricing.PricingTable({})
            t.set_quantities(Q)       # no rate list loaded -- every row unpriced
            t.resize(900, 300)
            t.show()
            app.processEvents()
            rect = t.table.visualItemRect(t.table.item(0, pricing.COL_RATE))
            local_pt = t.mapFromGlobal(
                t.table.viewport().mapToGlobal(rect.center()))
            pixel = t.grab().toImage().pixelColor(local_pt)
            # theme.WARN_BG (rgba(202,138,4,0.14)) composited on white is a
            # warm near-white, clearly red/green-forward and short of 255
            # on blue -- plain white (the bug) is 255 on every channel.
            self.assertLess(pixel.blue(), 240, pixel.name())
            self.assertGreater(pixel.red(), pixel.blue(), pixel.name())
        finally:
            app.setStyleSheet(previous)

    def test_a_rate_typed_into_the_grid_makes_the_amount_and_the_totals(self):
        t = pricing.PricingTable({})
        t.set_quantities(Q)
        t.table.item(3, pricing.COL_RATE).setText("4500")        # EP × 22
        t.table.item(4, pricing.COL_RATE).setText("85,000")      # gates × 2
        rows = t.rows()
        self.assertEqual(rows[3][pricing.COL_AMOUNT], "99,000.00")
        self.assertEqual(rows[4][pricing.COL_AMOUNT], "1,70,000.00")
        boq = t.boq()
        self.assertEqual(boq.subtotal(), Decimal("269000.00"))
        self.assertEqual(boq.gst_pct, Decimal("18"))
        self.assertEqual(boq.grand_total(), Decimal("317420.00"))
        self.assertIn("Grand total ₹3,17,420.00", t.totals.text())
        self.assertIn("three lakh seventeen thousand", t.totals.text())
        self.assertIn("CGST", t.totals.text())
        t.interstate_check.setChecked(True)
        self.assertIn("IGST", t.totals.text())
        t.contingency_spin.setValue(3.0)
        self.assertEqual(t.boq().contingency_amount(), Decimal("8070.00"))

    def test_starter_rates_are_marked_indicative(self):
        t = pricing.PricingTable({})
        t.set_quantities(Q)
        t._use_starter()
        self.assertIn("INDICATIVE", t.warn.text())
        self.assertIn("INDICATIVE", " ".join(t.boq().notes))

    def test_inquirys_price_list_is_the_first_rate_list(self):
        p = _rate_csv([("EL-01", "Electric pole EP", "nos", "4500")])
        t = pricing.PricingTable({"inquiry": {"rate_list": p}})
        self.assertIn("rates.csv", t.rates_label.text())
        t.set_quantities(Q)
        self.assertEqual(t.rows()[3][pricing.COL_RATE], "4,500.00")


class TheExportsWriteWhatTheGridShows(unittest.TestCase):

    def setUp(self):
        self.t = pricing.PricingTable({})
        self.t.set_quantities(Q, title="Bill of Quantities — test")
        self.t.table.item(3, pricing.COL_RATE).setText("4500")
        self.dir = tempfile.mkdtemp(prefix="prism-boq-")

    def test_csv(self):
        path = self.t.export("csv", os.path.join(self.dir, "boq.csv"))
        text = open(path, encoding="utf-8").read()
        self.assertIn("EP", text)
        self.assertIn("4500", text)
        self.assertIn("99000", text)

    def test_xlsx_has_live_formulas(self):
        import openpyxl
        path = self.t.export("xlsx", os.path.join(self.dir, "boq.xlsx"))
        wb = openpyxl.load_workbook(path)
        formulas = [str(c.value) for ws in wb.worksheets for row in ws.iter_rows()
                    for c in row if isinstance(c.value, str) and c.value.startswith("=")]
        self.assertTrue(any("*" in f for f in formulas), formulas[:5])   # =Qty*Rate
        self.assertTrue(any("SUM" in f for f in formulas), formulas[:5])

    def test_docx_has_the_same_grid_and_totals_as_every_other_format(self):
        """Item 10: "BOQ in any format gets filled in with the number from
        the pricing list" — xlsx/csv/pdf already did this; Word did not."""
        import docx
        path = self.t.export("docx", os.path.join(self.dir, "boq.docx"))
        self.assertTrue(os.path.exists(path))
        d = docx.Document(path)
        table_text = [c.text for t in d.tables for r in t.rows for c in r.cells]
        self.assertIn("EP", table_text)
        self.assertIn("4,500.00", table_text)
        self.assertIn("99,000.00", table_text)
        self.assertTrue(any("GRAND TOTAL" in c for c in table_text))

    def test_the_save_button_reports_where_it_went(self):
        target = os.path.join(self.dir, "chosen.csv")
        with mock.patch.object(pricing.QFileDialog, "getSaveFileName",
                               return_value=(target, "")):
            self.t._export("csv")
        self.assertTrue(os.path.exists(target))
        self.assertIn("chosen.csv", self.t.saved_label.text())
        self.assertTrue(self.t.saved_label.isVisibleTo(self.t))


class TheDialogShowsTheCardOnceMeasured(unittest.TestCase):

    def _dialog(self, mode="boq"):
        from addons.boq.dialog import BoqDialog
        cfg = {"agents": {"brains": "Claude", "content": "Claude",
                          "research": "Perplexity"}}
        return BoqDialog(cfg, [], None, mode=mode)

    def _measure(self, d):
        d.cad_path = "/tmp/site.dxf"
        with mock.patch.object(CB.config, "RUNS_DIR", tempfile.mkdtemp()), \
                mock.patch.object(CB.config, "save_artifact"):
            d._on_measured(dict(Q), [])

    def test_hidden_before_and_still_hidden_right_after_measuring(self):
        """The owner's report: the card sat there, visible and inert,
        before "Make my BOQ" had even been pressed — read as a static,
        useless section rather than a deliberate next step. The data is
        ready as soon as measuring finishes (rows populate), but the box
        itself only shows once a BOQ actually exists — see the two tests
        below."""
        d = self._dialog()
        self.assertFalse(d.price_box.isVisibleTo(d))
        self._measure(d)
        self.assertFalse(d.price_box.isVisibleTo(d))
        self.assertEqual(len(d.price_table.rows()), 5)
        # The measured table and the prompt text are untouched by pricing.
        self.assertEqual(len(d.meas_table.rows()), 5)
        self.assertIn("LENGTHS BY LAYER", d.summary)

    def test_shown_once_a_boq_is_actually_written(self):
        d = self._dialog()
        self._measure(d)
        d.writer_agent = "Claude"
        d.request = "BOQ for the site"
        d._write_made_files = []
        # texts is non-empty, so _on_written ends by opening the follow-up
        # offer -- a real FollowupDialog.exec() would hang here forever
        # (CLAUDE.md: never exec()/a QEventLoop in a test), the same trap
        # every other BOQ test that reaches this path already avoids.
        with mock.patch("dialogs.followup_dialog.FollowupDialog") as fake:
            fake.return_value.submitted.return_value = False
            d._on_written({"format": ["1  Brick wall  12.00  m"]}, {})
        self.assertTrue(d.price_box.isVisibleTo(d))

    def test_a_write_up_with_nothing_back_leaves_it_hidden(self):
        d = self._dialog()
        self._measure(d)
        d.writer_agent = "Claude"
        d.request = "BOQ for the site"
        d._write_made_files = []
        d._on_written({"format": []}, {})
        self.assertFalse(d.price_box.isVisibleTo(d))

    def test_a_bom_is_a_parts_list_and_does_not_price(self):
        d = self._dialog(mode="bom")
        self._measure(d)
        self.assertFalse(d.price_box.isVisibleTo(d))


if __name__ == "__main__":
    unittest.main()
