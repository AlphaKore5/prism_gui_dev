"""addons/boq/takeoff.py -- the compact PDF-takeoff dialog (item 26).

Found on a real drawing, 26 Oct 2026: every layer defaults to "ignore"
(never a guessed colour), and Step 1 stays folded away on purpose -- so
leaving it untouched ran a full OCR pass and only reported "runs: 0"
afterwards, with nothing earlier warning it was about to happen. This
file is what makes that checkable: the pre-extract confirmation, the
loud zero-runs status, and the warnings list extraction actually
produces being shown in the dialog itself rather than only in the final
plain-text hand-off.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap                                  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox   # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.boq import takeoff as T                                # noqa: E402

# _extract() now calls industries.remember_layer_roles(), which for HVAC
# reaches hvac_takeoff.save_map() -- the REAL, tracked, cross-tender
# hvac_takeoff/layer_map.json. Guard every test in this file from ever
# writing to it; only the dedicated test below re-patches this locally
# to verify the call itself happens.
#
# setUpModule/tearDownModule, not a bare `.start()` -- this file is one of
# several collected into the SAME pytest process (e.g. alongside
# test_boq_industries.py, which tests the real remember_layer_roles), and
# an un-stopped `.start()` here replaced that function for every test in
# every OTHER file for the rest of the process, not just this one.
_remember_guard = None


def setUpModule():
    global _remember_guard
    _remember_guard = mock.patch.object(T.industries, "remember_layer_roles")
    _remember_guard.start()


def tearDownModule():
    _remember_guard.stop()


class _FakeWorker:
    """Same shape as the real HvacTakeoffWorker's signals -- done/failed
    with a no-op connect, start() does nothing (the test drives the
    callbacks directly), never a real QThread."""
    last = None

    def __init__(self, *a, **kw):
        self.args, self.kwargs = a, kw
        self.done = self.failed = self
        _FakeWorker.last = self

    def connect(self, *_):
        pass

    def start(self):
        pass


def _dialog_with_one_layer(role: str = "ignore") -> T.IndustryTakeoffDialog:
    d = T.IndustryTakeoffDialog("HVAC")
    d.show()
    d.pdf_path = "/x/fake.pdf"
    d._fill_mapping([{"key": "k1", "color": "#000000", "linewidth": 1.0,
                      "kind": "line", "segments": 5, "length_pt": 100.0,
                      "pages": [0]}])
    if role != "ignore":
        d._role_combos[0][1].setCurrentText(role)
    return d


class TheAllIgnoreLayerMapIsCaughtBeforeExtracting(unittest.TestCase):
    """Every layer stays "ignore" until the person opens the folded-away
    Step 1 and picks something -- easy to skip. Extraction must ask
    first, not just report zero duct runs afterwards."""

    def test_asks_before_extracting_when_every_role_is_ignore(self):
        d = _dialog_with_one_layer("ignore")
        with mock.patch.object(T.QMessageBox, "question",
                               return_value=QMessageBox.No) as q, \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            _FakeWorker.last = None
            d._extract()
        self.assertTrue(q.called)
        self.assertIsNone(_FakeWorker.last)

    def test_declining_opens_the_layer_mapping_section(self):
        d = _dialog_with_one_layer("ignore")
        with mock.patch.object(T.QMessageBox, "question",
                               return_value=QMessageBox.No), \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            d._extract()
        self.assertTrue(d.mapping_area.isVisibleTo(d))

    def test_confirming_anyway_still_extracts(self):
        d = _dialog_with_one_layer("ignore")
        with mock.patch.object(T.QMessageBox, "question",
                               return_value=QMessageBox.Yes), \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            _FakeWorker.last = None
            d._extract()
        self.assertIsNotNone(_FakeWorker.last)

    def test_a_real_role_assignment_never_triggers_the_question(self):
        d = _dialog_with_one_layer("supply")
        with mock.patch.object(T.QMessageBox, "question") as q, \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            d._extract()
        self.assertFalse(q.called)


class ZeroDuctRunsIsLoudNotJustAnotherStatusLine(unittest.TestCase):
    def test_zero_runs_names_the_fix_and_uses_the_warn_colour(self):
        import theme
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [], "labels": [], "warnings": []})
        self.assertIn("Layer mapping", d.status.text())
        self.assertIn(theme.WARN_INK, d.status.styleSheet())

    def test_a_real_measurement_gets_the_plain_count_not_the_warning(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [{"length_ft": 10.0}], "labels": [],
                         "warnings": []})
        self.assertIn("1 duct run", d.status.text())
        self.assertEqual(d.status.styleSheet(), "")


class ExtractionWarningsAreShownInTheDialogItself(unittest.TestCase):
    """Not buried only in summary_text()'s own WARNINGS section -- the
    same list, visible before "Use these measurements" is ever pressed."""

    def test_warnings_appear_in_the_collapsed_list(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [], "labels": [],
                         "warnings": ["No duct runs found: check the layer "
                                      "mapping (which colour is supply/return)."]})
        self.assertTrue(d.warn_btn.isVisibleTo(d))
        self.assertEqual(d.warn_list.count(), 1)

    def test_no_warnings_means_no_warning_button(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [{"length_ft": 10.0}], "labels": [],
                         "warnings": []})
        self.assertFalse(d.warn_btn.isVisibleTo(d))


class UseButtonStaysDisabledUntilTheScaleIsConfirmed(unittest.TestCase):
    """item 27 rule 5: hvac_takeoff already warns "scale may be wrong" when
    few runs matched a label, but nothing stopped a BOQ being made anyway
    before this -- found on the real file, one bad-scale category came out
    more than 2x the client's real figure with that warning sitting
    unread. The checkbox is the actual gate, not just advice text."""

    def test_extracting_a_real_result_does_not_enable_use_by_itself(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [{"length_ft": 10.0}], "labels": [],
                         "warnings": []})
        self.assertFalse(d.use_btn.isEnabled())

    def test_checking_the_confirmation_after_a_result_exists_enables_use(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [{"length_ft": 10.0}], "labels": [],
                         "warnings": []})
        d.scale_confirm_cb.setChecked(True)
        self.assertTrue(d.use_btn.isEnabled())

    def test_checking_the_confirmation_before_any_result_does_not_enable_use(self):
        d = _dialog_with_one_layer("supply")
        d.scale_confirm_cb.setChecked(True)
        self.assertFalse(d.use_btn.isEnabled())

    def test_changing_the_scale_after_confirming_un_checks_it(self):
        d = _dialog_with_one_layer("supply")
        d._on_extracted({"duct_runs": [{"length_ft": 10.0}], "labels": [],
                         "warnings": []})
        d.scale_confirm_cb.setChecked(True)
        self.assertTrue(d.use_btn.isEnabled())
        d.scale_combo.setCurrentIndex(
            (d.scale_combo.currentIndex() + 1) % max(1, d.scale_combo.count()))
        self.assertFalse(d.scale_confirm_cb.isChecked())
        self.assertFalse(d.use_btn.isEnabled())


def _measure_dialog() -> T._ScaleMeasureDialog:
    """A real client PDF is never kept in the repo (see CLAUDE.md) -- the
    image load is replaced with a plain blank pixmap, since every test
    below is about the click/distance ARITHMETIC, not PDF rendering."""
    with mock.patch.object(T._ScaleMeasureDialog, "_load_image",
                           lambda self: setattr(self, "pixmap", QPixmap(400, 300))):
        return T._ScaleMeasureDialog("/x/fake.pdf")


class ScaleMeasureDialogComputesPointsPerFootFromAClickedDistance(unittest.TestCase):
    """item 27 rule 5's own follow-up: the scale checkbox alone could only
    ever flag the risk, never fix the number. 100 px at the dialog's own
    100 dpi is exactly 72 pt (dpi IS points-per-inch); over a stated 10 ft
    real distance that is 7.2 pt/ft -- plain unit arithmetic, checked
    against the real file in dev, not re-verified here (no PDF kept)."""

    def test_two_clicks_and_a_distance_compute_the_scale(self):
        d = _measure_dialog()
        d._on_click(100, 200)
        d._on_click(200, 200)
        d.distance_edit.setText("10")
        self.assertAlmostEqual(d.pt_per_ft, 7.2)
        self.assertTrue(d.use_btn.isEnabled())

    def test_a_third_click_restarts_from_one_point(self):
        d = _measure_dialog()
        d._on_click(0, 0)
        d._on_click(100, 0)
        d._on_click(500, 500)   # restarts -- only one point now
        d.distance_edit.setText("10")
        self.assertFalse(d.use_btn.isEnabled())   # needs a second click first
        d._on_click(600, 500)
        self.assertIsNotNone(d.pt_per_ft)

    def test_a_non_numeric_distance_does_not_enable_use(self):
        d = _measure_dialog()
        d._on_click(0, 0)
        d._on_click(100, 0)
        d.distance_edit.setText("not a number")
        self.assertFalse(d.use_btn.isEnabled())
        self.assertIsNone(d.pt_per_ft)

    def test_a_zero_or_negative_distance_does_not_enable_use(self):
        d = _measure_dialog()
        d._on_click(0, 0)
        d._on_click(100, 0)
        for bad in ("0", "-5"):
            with self.subTest(bad=bad):
                d.distance_edit.setText(bad)
                self.assertFalse(d.use_btn.isEnabled())

    def test_only_one_point_does_not_enable_use(self):
        d = _measure_dialog()
        d._on_click(0, 0)
        d.distance_edit.setText("10")
        self.assertFalse(d.use_btn.isEnabled())


class MeasuringAScaleOverridesTheDropdownAndCountsAsConfirmation(unittest.TestCase):
    """The whole point of actually measuring a dimension is that it IS
    the scale confirmation -- a person should not have to tick a second
    box saying what they just did."""

    def test_accepting_a_measured_scale_overrides_pt_per_ft(self):
        d = _dialog_with_one_layer("supply")
        d.pdf_path = "/x/fake.pdf"
        fake = mock.Mock()
        fake.pt_per_ft = 12.5
        with mock.patch.object(T, "_ScaleMeasureDialog", return_value=fake):
            fake.exec.return_value = QDialog.Accepted
            d._open_measure_dialog()
        self.assertEqual(d._pt_per_ft(), 12.5)
        self.assertTrue(d.scale_confirm_cb.isChecked())
        self.assertTrue(d.measured_scale_label.isVisibleTo(d))

    def test_cancelling_the_measure_dialog_changes_nothing(self):
        d = _dialog_with_one_layer("supply")
        d.pdf_path = "/x/fake.pdf"
        fake = mock.Mock()
        fake.pt_per_ft = None
        with mock.patch.object(T, "_ScaleMeasureDialog", return_value=fake):
            fake.exec.return_value = QDialog.Rejected
            d._open_measure_dialog()
        self.assertIsNone(d._measured_pt_per_ft)
        self.assertFalse(d.scale_confirm_cb.isChecked())

    def test_changing_the_dropdown_after_measuring_clears_the_override(self):
        d = _dialog_with_one_layer("supply")
        d._measured_pt_per_ft = 12.5
        d.measured_scale_label.setVisible(True)
        d.scale_combo.setCurrentIndex(
            (d.scale_combo.currentIndex() + 1) % max(1, d.scale_combo.count()))
        self.assertIsNone(d._measured_pt_per_ft)
        self.assertFalse(d.measured_scale_label.isVisibleTo(d))

    def test_picking_a_new_pdf_clears_a_previous_measurement(self):
        d = _dialog_with_one_layer("supply")
        d._measured_pt_per_ft = 12.5
        d.measured_scale_label.setVisible(True)
        with mock.patch.object(T, "QFileDialog") as fd, \
                mock.patch.object(T.industries, "scan_layers", return_value=[]):
            fd.getOpenFileName.return_value = ("/x/new.pdf", "")
            d._pick_pdf()
        self.assertIsNone(d._measured_pt_per_ft)
        self.assertFalse(d.measured_scale_label.isVisibleTo(d))


class LayerPreviewOpensTheRightLayerOnTheRealPdf(unittest.TestCase):
    """item 33: pointed out directly against a rival PDF-takeoff tool that
    already has a preview next to its own layer list. Each row's Preview
    button must open exactly the layer that row is for, on the dialog's
    OWN pdf_path -- never a stale or wrong one."""

    def test_opens_the_preview_dialog_for_the_clicked_layers_own_key(self):
        d = _dialog_with_one_layer("supply")
        layer = d._role_combos[0][0]
        fake = mock.Mock()
        with mock.patch.object(T, "_LayerPreviewDialog", return_value=fake) as ctor:
            d._preview_layer(layer)
        ctor.assert_called_once_with("HVAC", "/x/fake.pdf", layer, parent=d)
        self.assertTrue(fake.exec.called)

    def test_does_nothing_without_a_pdf_picked_yet(self):
        d = T.IndustryTakeoffDialog("HVAC")
        d.show()
        layer = {"key": "k1", "color": "#000000", "linewidth": 1.0,
                 "kind": "line", "segments": 5, "length_pt": 100.0, "pages": [0]}
        with mock.patch.object(T, "_LayerPreviewDialog") as ctor:
            d._preview_layer(layer)
        self.assertFalse(ctor.called)


class LayerPreviewDialogRendersOrSaysWhyItCouldNot(unittest.TestCase):
    _LAYER = {"key": "k1", "color": "#000000", "linewidth": 1.0,
             "kind": "line", "segments": 5, "length_pt": 100.0, "pages": [0]}

    def test_a_successful_render_shows_a_real_pixmap(self):
        # A real, freshly-encoded PNG -- a tiny white square -- so the
        # test checks QPixmap actually decoded bytes, not just that some
        # text got set.
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), "white").save(buf, format="PNG")
        png = buf.getvalue()
        with mock.patch.object(T.industries, "layer_preview", return_value=png) as lp:
            dlg = T._LayerPreviewDialog("HVAC", "/x/fake.pdf", self._LAYER)
        lp.assert_called_once_with("HVAC", "/x/fake.pdf", "k1")
        # Walk the dialog's own labels for the one carrying the pixmap --
        # simpler and just as direct as threading a named attribute through.
        labels = dlg.findChildren(T.QLabel)
        self.assertTrue(any(not l.pixmap().isNull() for l in labels
                            if l.pixmap() is not None))

    def test_a_render_failure_shows_the_real_reason_not_a_blank_dialog(self):
        with mock.patch.object(T.industries, "layer_preview",
                               side_effect=RuntimeError("couldn't open PDF")):
            dlg = T._LayerPreviewDialog("HVAC", "/x/fake.pdf", self._LAYER)
        labels = dlg.findChildren(T.QLabel)
        self.assertTrue(any("couldn't open PDF" in l.text() for l in labels))


class LayerMappingPreFillsFromAnEarlierTendersOwnRoles(unittest.TestCase):
    """Found 30 Oct 2026: a real client file read 0 duct runs through this
    dialog while the standalone hvac_takeoff.py tool, run on the exact
    same PDF, measured many -- because that tool's own combo boxes start
    from a saved role for a key it has seen before, and this dialog's
    combo boxes always started at "ignore" regardless. `_fill_mapping`
    must now ask `industries.saved_layer_roles` the same question."""

    def _layer(self, key="k1"):
        return {"key": key, "color": "#000000", "linewidth": 1.56,
                "kind": "line", "segments": 5, "length_pt": 100.0, "pages": [0]}

    def test_a_previously_learned_key_starts_on_its_saved_role(self):
        d = T.IndustryTakeoffDialog("HVAC")
        d.show()
        with mock.patch.object(T.industries, "saved_layer_roles",
                               return_value={"k1": "supply"}):
            d._fill_mapping([self._layer("k1")])
        self.assertEqual(d._role_combos[0][1].currentText(), "supply")

    def test_a_key_never_seen_before_still_starts_on_ignore(self):
        d = T.IndustryTakeoffDialog("HVAC")
        d.show()
        with mock.patch.object(T.industries, "saved_layer_roles",
                               return_value={"some other key": "supply"}):
            d._fill_mapping([self._layer("k1")])
        self.assertEqual(d._role_combos[0][1].currentText(), "ignore")

    def test_a_saved_role_this_industry_no_longer_offers_is_not_forced_in(self):
        """A role list can change between sessions -- never set a combo to
        a value `addItems` was never given."""
        d = T.IndustryTakeoffDialog("HVAC")
        d.show()
        with mock.patch.object(T.industries, "saved_layer_roles",
                               return_value={"k1": "not_a_real_role"}):
            d._fill_mapping([self._layer("k1")])
        self.assertEqual(d._role_combos[0][1].currentText(), "ignore")


class ExtractingRemembersTheChosenRolesForTheNextDrawing(unittest.TestCase):
    """The other half of the fix above: Step 1's choices must reach
    `industries.remember_layer_roles` so the NEXT drawing starts
    pre-filled too -- saved before the worker even runs, so a crash or a
    bad scale never costs the mapping work, same as the standalone tool."""

    def test_extract_passes_the_current_layer_map_to_remember_layer_roles(self):
        d = _dialog_with_one_layer("supply")
        with mock.patch.object(T.industries, "remember_layer_roles") as remember, \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            d._extract()
        remember.assert_called_once_with("HVAC", {"k1": "supply"})

    def test_declining_the_all_ignore_warning_never_saves_anything(self):
        d = _dialog_with_one_layer("ignore")
        with mock.patch.object(T.QMessageBox, "question",
                               return_value=QMessageBox.No), \
                mock.patch.object(T.industries, "remember_layer_roles") as remember, \
                mock.patch.object(T, "HvacTakeoffWorker", _FakeWorker):
            d._extract()
        self.assertFalse(remember.called)


if __name__ == "__main__":
    unittest.main()
