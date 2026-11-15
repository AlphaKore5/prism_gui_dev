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


if __name__ == "__main__":
    unittest.main()
