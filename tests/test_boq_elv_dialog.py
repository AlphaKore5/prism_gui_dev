"""addons/boq/elv_dialog.py -- ElvReadDialog (item 63, generalized onto the
shared reader at item 64, BOQ-CHANGES-TODO.md).

ELV has no geometry Step 1, so this dialog's own tests are about the two
things IndustryTakeoffDialog's own tests don't need to cover: the
drawing-type-dependent consent (a DWG/DXF that reads from real entities
never asks at all; a PDF always does), and that no mode choice is shown
any more -- drawing_reader.py decides the reading path from the file
itself."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox              # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.boq import elv_dialog as D                             # noqa: E402


class _FakeWorker:
    """Same shape as the real ElvReadWorker's signals -- done/failed with
    a no-op connect, start() does nothing (the test drives the callbacks
    directly), never a real QThread."""
    last = None

    def __init__(self, *a, **kw):
        self.args, self.kwargs = a, kw
        self.done = self.failed = self
        _FakeWorker.last = self

    def connect(self, *_):
        pass

    def start(self):
        pass


def _dialog_with_key(api_key: str = "sk-or-x", path: str = "/x/fake.pdf") -> D.ElvReadDialog:
    d = D.ElvReadDialog("ELV", cfg={"openrouter_api_key": api_key})
    d.show()
    d.pdf_path = path
    d.path_label.setText(os.path.basename(path))
    d.read_btn.setEnabled(True)
    return d


class PickingADrawingEnablesTheReadButton(unittest.TestCase):
    def test_the_read_button_starts_disabled(self):
        d = D.ElvReadDialog("ELV")
        self.assertFalse(d.read_btn.isEnabled())

    def test_the_file_picker_offers_pdf_dwg_and_dxf(self):
        d = D.ElvReadDialog("ELV")
        self.assertIn("*.pdf", D._DRAWING_FILTER)
        self.assertIn("*.dwg", D._DRAWING_FILTER)
        self.assertIn("*.dxf", D._DRAWING_FILTER)

    def test_no_mode_choice_is_offered_any_more(self):
        d = D.ElvReadDialog("ELV")
        self.assertFalse(hasattr(d, "whole_rb"))
        self.assertFalse(hasattr(d, "tiled_rb"))


class NoApiKeyRefusesToReadAPdfAtAll(unittest.TestCase):
    def test_no_key_shows_a_message_and_never_asks_consent_for_a_pdf(self):
        d = _dialog_with_key(api_key="", path="/x/fake.pdf")
        with mock.patch.object(D.QMessageBox, "information") as info, \
                mock.patch.object(D.QMessageBox, "question") as q:
            d._read()
        self.assertTrue(info.called)
        self.assertFalse(q.called)

    def test_a_dxf_needs_no_key_at_all(self):
        """A DWG/DXF may read entirely off real entities, zero AI -- the
        shared reader decides that, not this dialog, so no key means no
        block here the way it does for a PDF."""
        d = _dialog_with_key(api_key="", path="/x/fake.dxf")
        with mock.patch.object(D.QMessageBox, "information") as info, \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            d._read()
        self.assertFalse(info.called)
        self.assertIsNotNone(_FakeWorker.last)


class OnlyAPdfEverAsksConsent(unittest.TestCase):
    """A DWG/DXF tries real entities first and only reaches the AI-tiled
    path (through drawing_reader.py, not this dialog) if that found
    nothing -- so this dialog, which cannot know that in advance, only
    ever gates on a prompt for a PDF, which always needs the AI path."""

    def test_a_pdf_asks_consent_before_reading(self):
        d = _dialog_with_key(path="/x/fake.pdf")
        with mock.patch.object(D.QMessageBox, "question",
                               return_value=QMessageBox.No) as q, \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            d._read()
        self.assertTrue(q.called)
        message = q.call_args.args[2]
        self.assertIn("NOT sent", message)
        self.assertIn("as a whole", message)

    def test_a_dxf_never_asks_consent(self):
        d = _dialog_with_key(path="/x/fake.dxf")
        with mock.patch.object(D.QMessageBox, "question") as q, \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            d._read()
        self.assertFalse(q.called)
        self.assertIsNotNone(_FakeWorker.last)

    def test_a_dwg_never_asks_consent(self):
        d = _dialog_with_key(path="/x/fake.dwg")
        with mock.patch.object(D.QMessageBox, "question") as q, \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            d._read()
        self.assertFalse(q.called)
        self.assertIsNotNone(_FakeWorker.last)

    def test_declining_consent_on_a_pdf_never_starts_the_worker(self):
        d = _dialog_with_key(path="/x/fake.pdf")
        with mock.patch.object(D.QMessageBox, "question",
                               return_value=QMessageBox.No), \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            _FakeWorker.last = None
            d._read()
        self.assertIsNone(_FakeWorker.last)

    def test_accepting_consent_on_a_pdf_starts_the_worker(self):
        d = _dialog_with_key(path="/x/fake.pdf")
        with mock.patch.object(D.QMessageBox, "question",
                               return_value=QMessageBox.Yes), \
                mock.patch.object(D, "ElvReadWorker", _FakeWorker):
            _FakeWorker.last = None
            d._read()
        self.assertIsNotNone(_FakeWorker.last)
        self.assertEqual(_FakeWorker.last.args, ("ELV", "/x/fake.pdf"))
        self.assertEqual(_FakeWorker.last.kwargs["api_key"], "sk-or-x")


class ReadResultFeedsTheOutputAndEnablesUseThisReading(unittest.TestCase):
    def test_a_successful_read_shows_the_summary_and_enables_use(self):
        d = _dialog_with_key()
        with mock.patch.object(D.industries, "summary_text",
                               return_value="AI READING\n  CAM-01\n") as st:
            d._on_read({"method": "ai_tiled", "pages": []})
            self.assertEqual(d.measurements_text(), "AI READING\n  CAM-01\n")
        st.assert_called_with("ELV", {"method": "ai_tiled", "pages": []})
        self.assertTrue(d.use_btn.isEnabled())
        self.assertTrue(d.output.isVisible())
        self.assertEqual(d.output.toPlainText(), "AI READING\n  CAM-01\n")

    def test_no_result_yet_means_empty_measurements_text(self):
        d = D.ElvReadDialog("ELV")
        self.assertEqual(d.measurements_text(), "")

    def test_a_failed_read_shows_a_warning_not_a_crash(self):
        d = _dialog_with_key()
        with mock.patch.object(D.QMessageBox, "warning") as warn:
            d._on_read_failed("No OpenRouter key set.")
        self.assertTrue(warn.called)
        self.assertFalse(d.use_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
