"""BOQ file pickers open where the person works, not in a dev build's data folder
(RELEASE_ISSUES.md ISS-009/ISS-012; the owner's screenshot: "Tender PDF" opened in .prism-dev-home)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication                 # noqa: E402

_app = QApplication.instance() or QApplication([])
import paths                                                # noqa: E402
from widgets import file_pick as FP                         # noqa: E402


class TheStartFolder(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.real = os.path.join(self.tmp.name, "real")
        self.data = os.path.join(self.real, ".prism-dev-home")
        os.makedirs(os.path.join(self.real, "Downloads"))
        os.makedirs(self.data)
        env = {"PRISM_REAL_HOME": self.real, "PRISM_HOME_ISOLATED": self.data}
        from PySide6.QtCore import QStandardPaths
        for p in (mock.patch.dict(os.environ, env),
                  mock.patch.object(QStandardPaths, "writableLocation", return_value="")):
            p.start()
            self.addCleanup(p.stop)

    def test_first_time_it_is_the_real_downloads_never_the_dev_home(self):
        got = FP.start_dir({}, "boq-tender-pdf")
        self.assertEqual(got, os.path.join(self.real, "Downloads"))
        self.assertFalse(got.startswith(self.data))

    def test_the_last_folder_used_for_that_kind_wins_and_is_per_kind(self):
        docs = os.path.join(self.real, "Projects", "Tender")
        os.makedirs(docs)
        cfg = {}
        with mock.patch("core_bridge.config.save") as save:
            FP.remember(cfg, "boq-tender-pdf", os.path.join(docs, "a.pdf"))
        save.assert_called_once()
        self.assertEqual(FP.start_dir(cfg, "boq-tender-pdf"), docs)
        self.assertEqual(FP.start_dir(cfg, "boq-template"), os.path.join(self.real, "Downloads"))

    def test_a_folder_that_has_gone_falls_back(self):
        cfg = {"last_dirs": {"k": os.path.join(self.real, "gone")}}
        self.assertEqual(FP.start_dir(cfg, "k"), os.path.join(self.real, "Downloads"))

    def test_the_tender_pdf_picker_in_hitarths_tool_starts_there_with_a_pdf_filter(self):
        from addons.boq import takeoff as T
        with mock.patch("widgets.file_pick.QFileDialog.getOpenFileName", return_value=("", "")) as pick:
            d = T.IndustryTakeoffDialog("HVAC", None, cfg={})
            d._pick_pdf()
        args = pick.call_args.args
        self.assertEqual(args[2], os.path.join(self.real, "Downloads"))
        self.assertIn("*.pdf", args[3])

    def test_every_boq_picker_passes_a_real_start_folder(self):
        from addons.boq import takeoff as T, elv_dialog as E, panel as P
        start = os.path.join(self.real, "Downloads")
        with mock.patch("widgets.file_pick.QFileDialog.getOpenFileName", return_value=("", "")) as one, \
                mock.patch("widgets.file_pick.QFileDialog.getOpenFileNames", return_value=([], "")) as many:
            E.ElvReadDialog("ELV", None, cfg={})._pick_pdf()
            self.assertEqual(one.call_args.args[2], start)
            self.assertIn("*.dxf", one.call_args.args[3])           # drawings: DXF/DWG/PDF/pictures
            self.assertIn("*.png", one.call_args.args[3])
            from addons.boq.dialog import BoqDialog
            d = BoqDialog({"api_key": "k"}, [], None)
            d.ask._pick_file()
            self.assertEqual(many.call_args.args[2], start)
            self.assertIn("*.dwg", many.call_args.args[3])
            from addons.boq.dialog import InputMeasurementsDialog
            InputMeasurementsDialog(d)._upload()
            self.assertEqual(one.call_args.args[2], start)


if __name__ == "__main__":
    unittest.main()
