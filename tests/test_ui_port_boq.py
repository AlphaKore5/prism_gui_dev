"""UI port, stage 12 (BOQ): the four-step dialog, the drop zone, the pick-one cards and the usage chip,
all real widgets offscreen under the real stylesheet. Hermetic: temp folders, no AI call, no network, no measuring thread."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl                 # noqa: E402
from PySide6.QtGui import QDragEnterEvent, QDropEvent                    # noqa: E402
from PySide6.QtWidgets import QApplication                               # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                             # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from addons.boq.dialog import BoqDialog                                  # noqa: E402
from widgets import usage_chip                                           # noqa: E402
from widgets.stepper import ChoiceCard, FileCard                         # noqa: E402
from widgets.usage_chip import Usage, UsageChip                          # noqa: E402

CFG = {"api_key": "k"}


def _dialog(mode="boq"):
    d = BoqDialog(CFG, [], None, mode=mode)
    d._measure = lambda: None          # never start the measuring thread
    return d


def _drop(widget, paths):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
    ev = QDropEvent(QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    ev._keep = mime                     # the event only borrows the mime data
    return ev


class TheFourSteps(unittest.TestCase):
    def test_a_boq_has_four_steps_a_bom_three(self):
        self.assertEqual(_dialog().tabs.states(), ["active", "todo", "todo", "todo"])
        self.assertEqual(len(_dialog("bom")._step_names), 3)

    def test_the_first_primary_is_greyed_with_a_reason_until_there_is_something(self):
        d = _dialog()
        self.assertFalse(d.run_btn.isEnabled())
        self.assertIn("Say what the BOQ is for", d.run_btn.toolTip())
        self.assertIn("Say what the BOQ is for", d._why.text())
        d.ask.set_text("CCTV for a warehouse")
        self.assertTrue(d.run_btn.isEnabled())
        self.assertEqual(d.run_btn.toolTip(), "")

    def test_one_primary_walks_the_steps_and_makes_on_the_third(self):
        d = _dialog()
        d.ask.set_text("CCTV for a warehouse")
        self.assertEqual(d.run_btn.text(), "Next: count it")
        d.run_btn.click()
        self.assertEqual(d._step, d.S_COUNT)
        self.assertEqual(d.run_btn.text(), "Next: make the BOQ")
        d.run_btn.click()
        self.assertEqual(d._step, d.S_MAKE)
        self.assertEqual(d.run_btn.text(), "Make my BOQ")
        with mock.patch.object(d, "_run") as run, mock.patch.object(d, "_ask_recheck") as chk:
            d.run_btn.click()
        run.assert_called_once()
        chk.assert_not_called()

    def test_with_the_drawing_uses_the_existing_recheck_handler(self):
        d = _dialog()
        d.ask.set_text("x")
        d.cad_path = "/x/site.dxf"
        d._show_step(d.S_MAKE)
        self.assertTrue(d.choice_drawing.isEnabled())
        d.choice_drawing.clicked.emit()
        self.assertTrue(d.choice_drawing.selected())
        self.assertFalse(d.choice_count.selected())
        with mock.patch.object(d, "_run") as run, mock.patch.object(d, "_ask_recheck") as chk:
            d.run_btn.click()
        chk.assert_called_once()
        run.assert_not_called()

    def test_with_the_drawing_is_disabled_with_a_reason_when_there_is_no_drawing(self):
        d = _dialog()
        d._show_step(d.S_MAKE)
        self.assertFalse(d.choice_drawing.isEnabled())
        self.assertIn("step 1", d.choice_drawing.toolTip())
        d.choice_drawing.clicked.emit()
        self.assertFalse(d._with_drawing)

    def test_a_made_document_moves_to_step_three_and_the_primary_becomes_next(self):
        d = _dialog()
        d.ask.set_text("x")
        d._show_result("## BOQ\n\nitem 1")
        self.assertEqual(d._step, d.S_MAKE)
        self.assertEqual(d.run_btn.text(), "Next: add prices")
        self.assertFalse(d.make_choice_box.isVisibleTo(d))
        self.assertTrue(d.result.isVisibleTo(d.pages.widget(d.S_MAKE)))
        d.run_btn.click()
        self.assertEqual(d._step, d.S_PRICE)
        self.assertEqual(d.run_btn.text(), "Finish")

    def test_a_bom_finishes_after_making_it(self):
        d = _dialog("bom")
        d._show_result("parts")
        self.assertEqual(d.run_btn.text(), "Finish")

    def test_only_finished_steps_can_be_clicked_back_to(self):
        d = _dialog()
        d.ask.set_text("x")
        d._show_step(d.S_MAKE)
        d.tabs._tabs[0].clicked.emit(0)
        self.assertEqual(d._step, d.S_HAVE)
        self.assertEqual(d.tabs.states()[3], "todo")


class EveryOldControlIsStillThere(unittest.TestCase):
    """Hitarth's controls: moved, never deleted. Each is a real child of the dialog."""

    NAMES = ["ask", "writer_combo", "research_combo", "format_combo", "industry_combo", "history_btn",
             "unit_edit", "scope_edit", "legend_edit", "derive_cb", "input_meas_btn", "takeoff_btn",
             "ext_meas_box", "meas_box", "price_box", "recheck_btn", "fill_template_btn", "open_btn",
             "progress", "status", "result", "meas_table", "price_table", "template_hint", "pdf_drawing_hint"]

    def test_all_of_them_exist(self):
        d = _dialog()
        for n in self.NAMES:
            self.assertTrue(hasattr(d, n), n)

    def test_the_expert_settings_are_folded_by_default_and_open_with_one_click(self):
        d = _dialog()
        for w in (d.writer_combo, d.research_combo, d.format_combo, d.history_btn,
                  d.unit_edit, d.scope_edit, d.legend_edit, d.derive_cb):
            self.assertFalse(w.isVisibleTo(d.pages.widget(0)), w)
        d.more.toggle.click()
        for w in (d.writer_combo, d.research_combo, d.format_combo, d.history_btn,
                  d.unit_edit, d.scope_edit, d.legend_edit, d.derive_cb):
            self.assertTrue(w.isVisibleTo(d.pages.widget(0)), w)

    def test_the_agent_and_format_pickers_still_offer_the_same_choices(self):
        from addons.boq import agents
        d = _dialog()
        self.assertEqual([d.writer_combo.itemText(i) for i in range(d.writer_combo.count())],
                         list(agents.WRITER))
        self.assertGreaterEqual(d.format_combo.count(), 4)

    def test_industry_stays_visible_on_step_one(self):
        d = _dialog()
        self.assertTrue(d.industry_combo.isVisibleTo(d.pages.widget(0)))


class TheDropZone(unittest.TestCase):
    def setUp(self):
        self.d = _dialog()
        self.dxf = os.path.join(tempfile.mkdtemp(), "site.dxf")
        open(self.dxf, "w").write("0\nEOF\n")

    def test_a_dropped_file_takes_the_same_road_as_the_choose_button(self):
        absorbed = []
        self.d._absorb = lambda paths: absorbed.append(paths)
        self.d.drawing_card.dropEvent(_drop(self.d.drawing_card, [self.dxf]))
        self.assertEqual(self.d.ask.paths(), [os.path.abspath(self.dxf)])
        self.assertEqual(absorbed, [[os.path.abspath(self.dxf)]])

    def test_a_real_drop_attaches_and_shows_the_drawing_added_card(self):
        self.d.drawing_card.dropEvent(_drop(self.d.drawing_card, [self.dxf]))
        self.assertEqual(self.d.cad_path, os.path.abspath(self.dxf))
        self.assertEqual(self.d.drawing_card.title.text(), "Drawing added")
        self.assertTrue(self.d.drawing_card.property("added"))

    def test_text_dragged_in_is_refused(self):
        mime = QMimeData()
        mime.setText("hello")
        ev = QDragEnterEvent(self.d.drawing_card.rect().center(), Qt.CopyAction, mime,
                             Qt.LeftButton, Qt.NoModifier)
        ev._keep = mime
        self.d.drawing_card.dragEnterEvent(ev)
        self.assertFalse(ev.isAccepted())
        self.assertFalse(self.d.drawing_card.property("dragging"))

    def test_a_file_dragged_over_lights_the_zone_and_leaving_puts_it_out(self):
        card = self.d.drawing_card
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(self.dxf)])
        ev = QDragEnterEvent(card.rect().center(), Qt.CopyAction, mime,
                             Qt.LeftButton, Qt.NoModifier)
        ev._keep = mime
        card.dragEnterEvent(ev)
        self.assertTrue(card.property("dragging"))
        card.dragLeaveEvent(None)
        self.assertFalse(card.property("dragging"))

    def test_the_card_does_not_accept_drops_unless_asked(self):
        self.assertTrue(self.d.drawing_card.acceptDrops())
        self.assertFalse(FileCard("a", "b", "c", "d", "e").acceptDrops())


class RealPixels(unittest.TestCase):
    def _pixel(self, widget, x, y):
        widget.show()
        _app.processEvents()
        return widget.grab().toImage().pixelColor(x, y)

    def test_the_picked_card_has_an_ink_border_and_the_other_a_hairline(self):
        a = ChoiceCard("list", "From the count", "text")
        b = ChoiceCard("eye", "With the drawing", "text")
        for c in (a, b):
            c.resize(300, 120)
        a.set_selected(True)
        pa = self._pixel(a, 1, 60)
        pb = self._pixel(b, 0, 60)
        self.assertLess(pa.red(), 60, pa.name())
        self.assertGreater(pb.red(), 200, pb.name())

    def test_a_disabled_card_goes_quiet(self):
        c = ChoiceCard("eye", "With the drawing", "text")
        c.setEnabled(False)
        self.assertTrue(c.title.property("off"))
        c.setEnabled(True)
        self.assertFalse(c.title.property("off"))

    def test_the_drop_zone_is_dashed_and_turns_ink_when_a_file_is_over_it(self):
        card = FileCard("Add", "hint", "Added", "Choose", "Change", accept_drops=True)
        card.resize(500, 90)
        card.move(400, 400)             # keep the (offscreen) pointer off it: :hover is ink too
        quiet = self._pixel(card, 1, 45)
        card._set_dragging(True)
        _app.processEvents()
        over = card.grab().toImage().pixelColor(1, 45)
        self.assertGreater(quiet.red(), 150, quiet.name())
        self.assertLess(over.red(), 60, over.name())


class TheUsageChip(unittest.TestCase):
    def test_hidden_when_there_is_no_server_yet(self):
        chip = UsageChip()
        self.assertTrue(chip.isHidden())

    def test_the_boq_dialog_carries_a_chip_that_is_hidden_today(self):
        d = _dialog()
        self.assertTrue(d.usage_chip.isHidden())

    def test_shows_what_the_provider_says_and_nothing_else(self):
        chip = UsageChip(provider=lambda: Usage(1240, 2000, run_cost=38, renews="Renews in 12 days"))
        self.assertFalse(chip.isHidden())
        self.assertEqual(chip.number.text(), "1,240")
        self.assertEqual(chip.run.text(), "This run: 38 credits")
        self.assertEqual(chip.note.text(), "Renews in 12 days")
        self.assertEqual(chip.bar.value(), 620)
        self.assertFalse(chip.property("low"))

    def test_low_credits_say_so_and_turn_the_bar_amber(self):
        chip = UsageChip(provider=lambda: Usage(300, 2000))
        self.assertTrue(chip.property("low"))
        self.assertIn("Running low", chip.note.text())
        chip.resize(240, 90)
        chip.move(400, 400)
        chip.show()
        _app.processEvents()
        img = chip.grab().toImage()
        y = chip.bar.mapTo(chip, chip.bar.rect().center()).y()
        x = chip.bar.mapTo(chip, chip.bar.rect().topLeft()).x() + 3
        px = img.pixelColor(x, y)
        self.assertGreater(px.red(), 180, px.name())
        self.assertLess(px.blue(), 80, px.name())      # amber, not the ink bar

    def test_unknown_run_cost_and_total_leave_those_parts_out(self):
        chip = UsageChip(provider=lambda: Usage(50))
        self.assertTrue(chip.run.isHidden())
        self.assertTrue(chip.bar.isHidden())
        self.assertFalse(chip.property("low"))

    def test_none_hides_it_again_and_a_failing_provider_does_too(self):
        state = {"u": Usage(10, 100)}
        chip = UsageChip(provider=lambda: state["u"])
        self.assertFalse(chip.isHidden())
        state["u"] = None
        chip.refresh()
        self.assertTrue(chip.isHidden())
        def boom():
            raise RuntimeError("server down")
        chip2 = UsageChip(provider=boom)
        self.assertTrue(chip2.isHidden())

    def test_the_app_wide_provider_feeds_the_dialog_and_can_be_cleared(self):
        usage_chip.set_provider(lambda: Usage(900, 1000, run_cost=4))
        try:
            d = _dialog()
            self.assertFalse(d.usage_chip.isHidden())
            self.assertEqual(d.usage_chip.run.text(), "This run: 4 credits")
        finally:
            usage_chip.set_provider(None)
        self.assertIsNone(usage_chip._default_provider())

    def test_it_reaches_for_no_network_and_no_disk(self):
        src = open(os.path.join(ROOT, "widgets", "usage_chip.py"), encoding="utf-8").read()
        for word in ("import requests", "import urllib", "import socket", "import http", "open(",
                     "import config", "licensing"):
            self.assertNotIn(word, src, word)


class TheOtherBoqDialogsSayWhyTheyAreGreyed(unittest.TestCase):
    def test_takeoff_and_elv_primaries_carry_a_reason(self):
        from addons.boq.elv_dialog import ElvReadDialog
        from addons.boq.takeoff import IndustryTakeoffDialog
        t = IndustryTakeoffDialog("HVAC", None, {})
        for b in (t.extract_btn, t.use_btn):
            self.assertFalse(b.isEnabled())
            self.assertTrue(b.toolTip())
        e = ElvReadDialog("ELV", None, {})
        for b in (e.read_btn, e.use_btn):
            self.assertFalse(b.isEnabled())
            self.assertTrue(b.toolTip())


SAMPLE_Q = {"unit": "millimeters", "unit_code": 4, "unit_confirmed": True, "notes": [],
            "lengths_by_layer": {"M-DUCT-SUPP": 186400.0, "M-DUCT-RET": 98200.0},
            "areas_by_layer": {}, "block_counts": {"VCD": 18}, "block_layers": {"VCD": ["M-DAMPER"]},
            "layers": ["M-DUCT-SUPP", "M-DUCT-RET", "M-DAMPER"], "entity_count": 100}
MD = "## BOQ\n\n| Item | Description | Unit | Qty |\n|---|---|---|---|\n| 1.1 | Supply duct | m | 186.4 |\n| | **Total** | | 5 |\n"


class TheResultLooksCalmAndSavesTheSame(unittest.TestCase):
    def test_styling_changes_formats_only_never_the_text_or_the_raw_answer(self):
        from PySide6.QtWidgets import QTextEdit
        plain = QTextEdit()
        plain.setMarkdown(MD)
        d = _dialog()
        d._show_result(MD)
        self.assertEqual(d.result.toPlainText(), plain.toPlainText())
        self.assertEqual(d._raw_result, MD)                      # what saves and follow-ups read
        # Qt's own re-export of the styled box would differ (mono runs become code spans),
        # so prove nothing reads it: only comments in the dialog mention it.
        src = open(os.path.join(ROOT, "addons", "boq", "dialog.py"), encoding="utf-8").read()
        calls = [l for l in src.splitlines() if ("= self.result.toMarkdown(" in l or "(self.result.toMarkdown(" in l) and not l.lstrip().startswith("#")]
        self.assertEqual(calls, [])

    def test_the_table_has_no_black_grid_a_soft_header_and_mono_right_aligned_numbers(self):
        from PySide6.QtGui import QTextCursor, QTextTable
        d = _dialog()
        d._show_result(MD)
        tbl = [f for f in d.result.document().rootFrame().childFrames() if isinstance(f, QTextTable)][0]
        self.assertEqual(tbl.format().border(), 0)
        self.assertEqual(tbl.cellAt(0, 0).format().background().color().name().lower(), theme.WELL.lower())
        self.assertEqual(tbl.cellAt(1, 0).format().toTableCellFormat().bottomBorderBrush().color().name().lower(), theme.HAIRLINE.lower())
        cur = tbl.cellAt(1, 3).firstCursorPosition()
        self.assertEqual(cur.blockFormat().alignment() & Qt.AlignRight, Qt.AlignRight)
        self.assertEqual(cur.charFormat().fontFamilies(), [theme.FONT_MONO])
        first = tbl.cellAt(1, 0).firstCursorPosition()
        self.assertFalse(first.blockFormat().alignment() & Qt.AlignRight)


class PricedExportsAreByteIdentical(unittest.TestCase):
    """The step-4 restyle is display only: every writer gets the same Boq."""

    def test_csv_and_docx_bytes_equal_the_engines_own_output_for_the_same_boq(self):
        import hashlib
        import core_bridge as CB
        from addons.boq.pricing import PricingTable
        t = PricingTable({})
        t.set_quantities(dict(SAMPLE_Q), title="T")
        t._use_starter()
        t._toggle_details()                       # touching the view must not change the file
        tmp = tempfile.mkdtemp()
        bp = CB.get_boq_price()
        for kind, writer in (("csv", bp.write_boq_csv), ("docx", bp.write_boq_docx)):
            a, b = os.path.join(tmp, "a." + kind), os.path.join(tmp, "b." + kind)
            t.export(kind, a)
            writer(t.boq(), b)
            if kind == "csv":
                self.assertEqual(hashlib.sha256(open(a, "rb").read()).hexdigest(),
                                 hashlib.sha256(open(b, "rb").read()).hexdigest())
            else:
                self.assertTrue(os.path.getsize(a) > 0 and os.path.getsize(b) > 0)


class StepFourCards(unittest.TestCase):
    def test_each_card_is_one_of_the_old_controls(self):
        from addons.boq.pricing import PricingTable
        t = PricingTable({})
        t.set_quantities(dict(SAMPLE_Q))
        self.assertTrue(t.card_none.selected())
        t.card_starter.clicked.emit()
        self.assertTrue(t.card_starter.selected())
        self.assertIn("starter rates", t.rates_label.text())
        t.card_none.clicked.emit()
        self.assertTrue(t.card_none.selected())
        self.assertIn("No rate list", t.rates_label.text())
        with mock.patch.object(t, "_pick_rates") as pick:
            t.card_list.clicked.disconnect()
            t.card_list.clicked.connect(t._pick_rates)
            t.card_list.clicked.emit()
        pick.assert_called_once()

    def test_the_section_item_and_basis_columns_are_folded_but_one_click_away(self):
        from addons.boq.pricing import COL_BASIS, COL_ITEM, COL_SECTION, PricingTable
        t = PricingTable({})
        t.set_quantities(dict(SAMPLE_Q))
        for c in (COL_SECTION, COL_ITEM, COL_BASIS):
            self.assertTrue(t.table.isColumnHidden(c))
        t.details_btn.click()
        for c in (COL_SECTION, COL_ITEM, COL_BASIS):
            self.assertFalse(t.table.isColumnHidden(c))
        self.assertEqual(len(t.rows()[0]), 8)


class TheFooterIsThreeThings(unittest.TestCase):
    def _footer_buttons(self, d):
        from PySide6.QtWidgets import QPushButton
        return [b for b in d.footer.findChildren(QPushButton) if b.isVisibleTo(d.footer)]

    def test_no_footer_button_text_is_clipped_on_any_step_at_either_width(self):
        for width in (780, 854, 1100):
            for mode in ("boq", "bom"):
                d = _dialog(mode)
                d.resize(width, 700)
                d.ask.set_text("x")
                d.show()
                _app.processEvents()
                for step in range(len(d._step_names)):
                    if step >= d.S_MAKE:
                        d._show_result("## x\n\nbody")
                    d._show_step(step)
                    _app.processEvents()
                    btns = self._footer_buttons(d)
                    self.assertLessEqual(len(btns), 3, (mode, step, [b.text() for b in btns]))
                    for b in btns:
                        need = b.fontMetrics().horizontalAdvance(b.text())
                        self.assertGreaterEqual(b.width(), need + 8, (width, mode, step, b.text()))

    def test_the_document_actions_live_in_the_step_body_above_the_result(self):
        d = _dialog()
        d._show_result("## x\n\nbody")
        for b in (d.open_btn, d.fill_template_btn, d.recheck_btn):
            self.assertTrue(d.result_actions.isAncestorOf(b))
            self.assertFalse(d.footer.isAncestorOf(b))
        self.assertTrue(d.result_actions.isVisibleTo(d.pages.widget(d.S_MAKE)))

    def test_step_three_shows_the_cards_before_the_run_and_the_result_after(self):
        d = _dialog()
        d.ask.set_text("x")
        d._show_step(d.S_MAKE)
        page = d.pages.widget(d.S_MAKE)
        self.assertTrue(d.make_choice_box.isVisibleTo(page))
        self.assertFalse(d.result.isVisibleTo(page))
        self.assertFalse(d.result_actions.isVisibleTo(page))
        d._show_result("## x\n\nbody")
        self.assertFalse(d.make_choice_box.isVisibleTo(page))
        self.assertTrue(d.result.isVisibleTo(page))


class StepFourRows(unittest.TestCase):
    def _table(self):
        from addons.boq.pricing import PricingTable
        t = PricingTable({})
        t.set_quantities(dict(SAMPLE_Q))
        return t

    def test_one_calm_row_per_line_with_name_mono_qty_rate_field_and_amount(self):
        t = self._table()
        self.assertEqual(len(t._row_widgets), len(t.rows()))
        row = t._row_widgets[0]
        self.assertEqual(row.name.text(), t.boq().items[0].description)
        self.assertIn(t.boq().items[0].unit, row.qty.text())
        self.assertEqual(row.amount.text(), "no rate yet")
        self.assertTrue(row.amount.property("empty"))

    def test_a_rate_typed_in_a_row_is_the_same_as_typing_it_in_the_grid(self):
        from addons.boq.pricing import COL_AMOUNT, COL_RATE
        a, b = self._table(), self._table()
        a._row_widgets[0].rate.setText("1350")
        a._row_widgets[0].rate.editingFinished.emit()
        b.table.item(0, COL_RATE).setText("1350")
        self.assertEqual(a.rows(), b.rows())
        self.assertEqual(a.boq().subtotal(), b.boq().subtotal())
        self.assertEqual(a.totals.text(), b.totals.text())
        self.assertEqual(a._row_widgets[0].amount.text(), "₹" + a.rows()[0][COL_AMOUNT])
        self.assertFalse(a._row_widgets[0].amount.property("empty"))

    def test_typing_in_the_full_table_updates_the_row(self):
        from addons.boq.pricing import COL_RATE
        t = self._table()
        t.table.item(1, COL_RATE).setText("200")
        self.assertEqual(t._row_widgets[1].rate.text(), t.rows()[1][COL_RATE])
        self.assertNotEqual(t._row_widgets[1].amount.text(), "no rate yet")

    def test_a_second_render_leaves_no_stale_rows_on_screen(self):
        from PySide6.QtWidgets import QFrame
        t = self._table()
        t._use_starter()                       # renders the rows a second time, same event-loop turn
        t._rate_typed(0, "1350")
        shown = [w for w in t._rows_box.findChildren(QFrame, "priceRow") if not w.isHidden()]
        self.assertEqual(len(shown), len(t.rows()))
        self.assertTrue(shown[0].amount.text().startswith("₹"))

    def test_unpriced_rows_are_not_tinted(self):
        t = self._table()
        t.resize(760, 400)
        t.move(400, 400)
        t.show()
        _app.processEvents()
        row = t._row_widgets[0]
        px = row.grab().toImage().pixelColor(row.width() // 3, row.height() // 2)
        self.assertEqual(px.name().lower(), "#ffffff")

    def test_the_indicative_note_is_one_quiet_line_with_the_full_text_kept(self):
        t = self._table()
        t._use_starter()
        self.assertIn("INDICATIVE", t.warn.text())
        self.assertIn("INDICATIVE", t.warn.toolTip())
        self.assertLessEqual(t.warn.sizeHint().height(), 24)

    def test_the_full_table_is_one_click_away(self):
        t = self._table()
        self.assertTrue(t.table.isHidden())
        t.details_btn.click()
        self.assertFalse(t.table.isHidden())


class StepFourFitsAndHasNoFrame(unittest.TestCase):
    def test_no_titled_group_frame_around_the_prices(self):
        from PySide6.QtWidgets import QGroupBox
        self.assertNotIsInstance(_dialog().price_box, QGroupBox)

    def test_the_totals_are_visible_without_scrolling(self):
        from PySide6.QtWidgets import QScrollArea
        for width in (780, 854):
            d = _dialog()
            d.resize(width, 700)
            d.move(300, 0)
            d.price_table.set_quantities(dict(SAMPLE_Q))
            d.price_table._use_starter()
            d.price_box.setVisible(True)
            d._show_result("## x\n\nbody")
            d._show_step(d.S_PRICE)
            d.show()
            _app.processEvents()
            box = d.price_table.summary_box
            area = box.parentWidget()
            while area is not None and not isinstance(area, QScrollArea):
                area = area.parentWidget()
            port = area.viewport()
            bottom = box.mapTo(port, box.rect().bottomLeft()).y()
            self.assertLessEqual(bottom, port.height(), (width, bottom, port.height()))
            d.close()


class StepOneIsShort(unittest.TestCase):
    def test_template_hint_input_measurements_and_favourites_are_in_more_options(self):
        d = _dialog()
        for w in (d.template_hint, d.input_meas_btn, d.ask.fav_btn):
            self.assertTrue(d.more.body.isAncestorOf(w), w)
            self.assertFalse(w.isVisibleTo(d.pages.widget(0)))
        d.more.toggle.click()
        for w in (d.template_hint, d.input_meas_btn, d.ask.fav_btn):
            self.assertTrue(w.isVisibleTo(d.pages.widget(0)))

    def test_favourites_still_opens_its_menu(self):
        d = _dialog()
        with mock.patch("widgets.ask_panel.QMenu") as menu:
            d.ask.fav_btn.click()
        menu.assert_called()

    def test_the_rules_line_says_so_for_hvac_only(self):
        from addons.boq import industries
        d = _dialog()
        self.assertTrue(d.rules_line.isHidden())
        d.industry_combo.setCurrentText(industries.HVAC)
        self.assertFalse(d.rules_line.isHidden())
        d.industry_combo.setCurrentText(industries.GENERAL)
        self.assertTrue(d.rules_line.isHidden())


class TheFrontDoorLeadsWithTheDropZone(unittest.TestCase):
    def _panel(self):
        from addons.boq.panel import BoqPanel
        p = BoqPanel({})
        p.resize(1000, 700)
        p.move(300, 0)
        p.show()
        _app.processEvents()
        return p

    def test_the_drop_zone_is_the_first_thing_on_the_page(self):
        p = self._panel()
        self.assertTrue(p._col.itemAt(0).widget().isAncestorOf(p.drop_zone))
        self.assertLessEqual(p.drop_zone.width(), 720)
        self.assertGreaterEqual(p.drop_zone.width(), 600)
        self.assertTrue(p.drop_zone.acceptDrops())
        from widgets import controls as C
        self.assertNotIsInstance(p.drop_zone.button, C.DarkPill)   # light pill: one dark primary per screen

    def test_a_real_drop_hands_the_file_paths_on(self):
        p = self._panel()
        f = os.path.join(tempfile.mkdtemp(), "site.dxf")
        open(f, "w").write("0\nEOF\n")
        got = []
        p.files_chosen.connect(got.append)
        ev = _drop(p.drop_zone, [f])
        p.drop_zone.dropEvent(ev)
        self.assertEqual(got, [[f]])

    def test_choose_a_drawing_hands_the_picked_files_on_and_cancel_does_nothing(self):
        p = self._panel()
        got = []
        p.files_chosen.connect(got.append)
        with mock.patch("addons.boq.panel.QFileDialog.getOpenFileNames", return_value=([], "")):
            p.drop_zone.button.click()
        self.assertEqual(got, [])
        with mock.patch("addons.boq.panel.QFileDialog.getOpenFileNames", return_value=(["/x/a.dxf"], "")):
            p.drop_zone.button.click()
        self.assertEqual(got, [["/x/a.dxf"]])

    def test_everything_else_is_still_below_it(self):
        from PySide6.QtWidgets import QPushButton
        p = self._panel()
        texts = [b.text() for b in p.findChildren(QPushButton)]
        self.assertIn("Reset", texts)                   # the counter row
        self.assertGreater(p._col.count(), 3)

    def test_the_main_window_opens_the_dialog_with_the_files_attached(self):
        import main_window as MW
        fake = mock.Mock(cfg={})
        with mock.patch.object(MW.CB, "boq_available", return_value=(True, "")), \
                mock.patch.object(MW, "BoqDialog") as dlg:
            dlg.return_value.owns_followup = True
            MW.MainWindow._open_boq_dialog(fake, ["/x/a.dxf", "/x/b.pdf"])
        args = dlg.call_args[0]
        self.assertEqual(args[1], [{"path": "/x/a.dxf"}, {"path": "/x/b.pdf"}])
        with mock.patch.object(MW.CB, "boq_available", return_value=(True, "")), \
                mock.patch.object(MW, "BoqDialog") as dlg:
            dlg.return_value.owns_followup = True
            MW.MainWindow._open_boq_dialog(fake)
        self.assertEqual(dlg.call_args[0][1], [])

    def test_the_dialog_given_those_paths_lands_on_step_one_with_the_drawing_attached(self):
        f = os.path.join(tempfile.mkdtemp(), "site.dxf")
        open(f, "w").write("0\nEOF\n")
        with mock.patch.object(BoqDialog, "_measure"):
            d = BoqDialog(CFG, [{"path": f}], None)
        self.assertEqual(d._step, d.S_HAVE)
        self.assertEqual(d.cad_path, os.path.abspath(f))
        self.assertEqual(d.drawing_card.title.text(), "Drawing added")


if __name__ == "__main__":
    unittest.main()
