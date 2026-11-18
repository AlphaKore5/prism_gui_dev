"""A picture or PDF of a drawing, for the readers: the shared drawing reader, the writer's attachment, and
the two PDF tools opened on a file chosen on the BOQ screen.

Real widgets offscreen, real small files (a DXF from ezdxf, a vector PDF from matplotlib, a PNG),
a sandbox HOME, no AI call (the writer is patched), no measuring thread, no exec().
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-boq-flow-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtGui import QImage                         # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog      # noqa: E402

_app = QApplication.instance() or QApplication([])

import core_bridge as CB                                 # noqa: E402
from addons.boq import dialog as D                       # noqa: E402
from addons.boq import industries as I, route            # noqa: E402
from addons.boq.dialog import BoqDialog                  # noqa: E402

_patches = [
    mock.patch.object(CB.config, "CONFIG_PATH", os.path.join(_HOME, "config.json")),
    mock.patch.object(CB.config, "RUNS_DIR", os.path.join(_HOME, "runs")),
    mock.patch.object(CB.config, "ARTIFACTS_DIR", os.path.join(_HOME, "Prism Artifacts")),
]
for _p in _patches:
    _p.start()


def tearDownModule():
    for _p in _patches:
        _p.stop()
    shutil.rmtree(_HOME, ignore_errors=True)


def _dialog(cfg=None):
    d = BoqDialog({"api_key": "k"} if cfg is None else cfg, [], None)
    d._measure = mock.Mock()           # never start the measuring thread
    return d


def _png(name="sheet.png"):
    p = os.path.join(tempfile.mkdtemp(dir=_HOME), name)
    img = QImage(80, 50, QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    img.save(p)
    return p


def _dxf():
    import ezdxf
    p = os.path.join(tempfile.mkdtemp(dir=_HOME), "plan.dxf")
    doc = ezdxf.new()
    doc.layers.add("CCTV-CABLE")
    doc.blocks.new("CAM")
    msp = doc.modelspace()
    msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "CCTV-CABLE"})
    for i in range(3):
        msp.add_blockref("CAM", (i * 1000, 500))
    doc.saveas(p)
    return p


def _vector_pdf():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams["pdf.fonttype"] = 42
    fig = plt.figure(figsize=(10, 7))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 720)
    ax.set_ylim(0, 504)
    ax.axis("off")
    for y in (200, 218):
        ax.plot([50, 500], [y, y], color="#000000", lw=1.56)
    ax.text(250, 230, "24x12", fontsize=9)
    ax.text(520, 400, "AHU-01 12 TR", fontsize=10)
    p = os.path.join(tempfile.mkdtemp(dir=_HOME), "tender.pdf")
    fig.savefig(p)
    plt.close(fig)
    return p


class PictureReaders(unittest.TestCase):
    def test_the_shared_reader_reads_a_picture_tile_by_tile_with_the_ai_callback(self):
        from addons.boq import drawing_reader as R
        calls = []
        res = R.extract(_png(), lambda b: (calls.append(len(b)) or "CAM-1\nCAM-2"), log=lambda *a: None)
        self.assertEqual(res["method"], "ai_tiled")
        self.assertEqual(len(calls), 1)                      # a small picture is one tile
        self.assertIn("CAM-1", res["pages"][0]["ai_text"])

    def test_a_picture_can_be_shown_to_the_writer(self):
        from addons.boq import cad_render
        for name, mime in (("a.png", "image/png"), ("a.jpg", "image/jpeg")):
            p = _png(name)
            self.assertEqual(cad_render.prepare_for_ai(p)["mime"], mime)
        tif = _png("a.tif")
        self.assertEqual(cad_render.prepare_for_ai(tif)["mime"], "image/png")   # converted

    def test_the_reader_dialog_asks_before_a_picture_leaves_and_sends_nothing_on_cancel(self):
        from addons.boq import elv_dialog as E
        cfg = {"openrouter_api_key": "prism-ai"}
        dlg = E.ElvReadDialog(I.ELV, None, cfg=cfg, path=_png())
        self.assertTrue(dlg.read_btn.isEnabled())
        with mock.patch.object(E.send_to_ai, "ask_consent", return_value=False) as ask, \
             mock.patch.object(E, "ElvReadWorker") as w:
            dlg._read()
        ask.assert_called_once()
        w.assert_not_called()

    def test_a_dxf_in_the_reader_needs_no_consent_and_no_ai(self):
        from addons.boq import elv_dialog as E
        dlg = E.ElvReadDialog(I.ELV, None, cfg={}, path=_dxf())
        with mock.patch.object(E.send_to_ai, "ask_consent") as ask, \
             mock.patch.object(E, "ElvReadWorker") as w:
            dlg._read()
        ask.assert_not_called()
        w.assert_called_once()

    def test_the_takeoff_dialog_takes_the_chosen_file(self):
        from addons.boq import takeoff as T
        pdf = _vector_pdf()
        dlg = T.IndustryTakeoffDialog(I.HVAC, None, cfg={}, path=pdf)
        self.assertEqual(dlg.pdf_path, pdf)
        self.assertTrue(dlg.extract_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
