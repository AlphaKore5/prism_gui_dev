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

from PySide6.QtWidgets import QApplication, QMessageBox            # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.boq import takeoff as T                                # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
