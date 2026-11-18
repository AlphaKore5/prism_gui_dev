"""BOQ front door and pipeline, as the user meets them: "What do you have?", "What kind of job
is it?", the strip of steps, the count evidence, and the PDF / picture roads.

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


Q = {"unit": "millimeters", "unit_code": 4, "unit_confirmed": True, "notes": ["A-WALL: pair read"],
     "lengths_by_layer": {"CCTV-CABLE": 5000.0}, "areas_by_layer": {}, "block_counts": {"CAM": 3},
     "block_layers": {"CAM": ["CCTV"]}, "layers": ["CCTV-CABLE"], "entity_count": 4}


class TheTwoQuestions(unittest.TestCase):
    def test_both_questions_are_visible_cards_not_buried(self):
        d = _dialog()
        page = d.pages.widget(0)
        self.assertEqual(set(d.input_cards), {route.CAD, route.SCAN, route.DESCRIBE})
        self.assertEqual(set(d.job_cards), set(I.NAMES))
        for c in list(d.input_cards.values()) + list(d.job_cards.values()):
            self.assertTrue(c.isVisibleTo(page))

    def test_each_job_card_has_a_short_example_line(self):
        d = _dialog()
        self.assertIn("CCTV", d.job_cards[I.ELV].hint.text())
        self.assertIn("Ducts", d.job_cards[I.HVAC].hint.text())

    def test_first_run_starts_on_general_and_picking_a_card_sets_the_industry(self):
        d = _dialog()
        self.assertEqual(d.industry_combo.currentText(), I.GENERAL)
        d._pick_job(I.HVAC)
        self.assertEqual(d.industry_combo.currentText(), I.HVAC)
        self.assertTrue(d.job_cards[I.HVAC].selected())
        self.assertFalse(d.job_cards[I.GENERAL].selected())

    def test_the_choice_is_remembered_for_next_time(self):
        cfg = {"api_key": "k"}
        _dialog(cfg)._pick_job(I.ELV)
        self.assertEqual(cfg["boq_job_kind"], I.ELV)
        again = _dialog(cfg)
        self.assertEqual(again.industry_combo.currentText(), I.ELV)
        self.assertTrue(again.job_cards[I.ELV].selected())

    def test_a_file_never_decides_the_trade(self):
        d = _dialog()
        d._absorb([_dxf()])
        self.assertEqual(d.industry_combo.currentText(), I.GENERAL)

    def test_describe_hides_the_drawing_box_and_cad_shows_it(self):
        d = _dialog()
        page = d.pages.widget(0)
        d._set_input(route.DESCRIBE)
        self.assertFalse(d.drawing_card.isVisibleTo(page))
        d._set_input(route.CAD)
        self.assertTrue(d.drawing_card.isVisibleTo(page))

    def test_hvac_from_a_picture_is_disabled_and_says_why_in_plain_words(self):
        d = _dialog()
        d._set_input(route.SCAN)
        d._absorb([_png()])
        card = d.job_cards[I.HVAC]
        self.assertFalse(card.isEnabled())
        self.assertIn("picture", card.hint.text())
        self.assertIn("picture", card.toolTip())
        d._pick_job(I.HVAC)                             # a disabled card does nothing
        self.assertEqual(d.industry_combo.currentText(), I.GENERAL)

    def test_a_chosen_trade_that_cannot_work_falls_back_to_general_and_says_so(self):
        d = _dialog()
        d._pick_job(I.HVAC)
        d._set_input(route.SCAN)
        d._absorb([_png()])
        self.assertEqual(d.industry_combo.currentText(), I.GENERAL)
        self.assertTrue(d.job_note.isVisibleTo(d.pages.widget(0)))

    def test_old_trade_box_is_hidden_for_a_boq_and_still_there_for_a_bom(self):
        self.assertFalse(_dialog().industry_combo.isVisibleTo(_dialog().pages.widget(0)))
        bom = BoqDialog({"api_key": "k"}, [], None, mode="bom")
        self.assertTrue(bom.industry_combo.isVisibleTo(bom.pages.widget(0)))
        self.assertFalse(hasattr(bom, "job_cards"))


class TheStripFollowsTheJob(unittest.TestCase):
    def test_a_cad_drawing_marks_read_and_measure_done_and_asks_you_to_check(self):
        d = _dialog()
        d._absorb([_dxf()])
        self.assertEqual(d._input_kind, route.CAD)
        d._on_measured(dict(Q), [])
        p = d.pipe
        self.assertEqual(p.state("read"), route.DONE)
        self.assertEqual(p.state("measure"), route.DONE)
        self.assertIn("no AI", p.line_of("measure"))
        self.assertEqual(p.state("check"), route.NEEDS_YOU)
        self.assertIn("1 item", p.line_of("check"))
        self.assertTrue(d.evidence_box.isVisibleTo(d.pages.widget(d.S_COUNT)))
        self.assertIn("Nothing here is an estimate", d.evidence_box.text())

    def test_a_failed_read_says_why(self):
        d = _dialog()
        d._absorb([_dxf()])
        with mock.patch.object(D.QMessageBox, "warning"):
            d._on_measure_failed("The file is damaged.")
        self.assertEqual(d.pipe.state("read"), route.FAILED)
        self.assertIn("damaged", d.pipe.line_of("read"))

    def test_changing_the_trade_after_measuring_measures_again(self):
        d = _dialog()
        d._absorb([_dxf()])
        d._on_measured(dict(Q), [])
        d._measure.reset_mock()
        d._pick_job(I.HVAC)
        d._measure.assert_called_once()
        self.assertIsNone(d.q)

    def test_describe_marks_every_quantity_an_estimate(self):
        d = _dialog()
        d._set_input(route.DESCRIBE)
        self.assertIn("estimate", d.pipe.line.text() + d.pipe._stages[1].detail.lower())
        self.assertEqual(d.pipe.state("describe"), route.NEEDS_YOU)
        d.ask.set_text("CCTV for a warehouse")
        d._replay_pipe()
        self.assertEqual(d.pipe.state("describe"), route.DONE)

    def test_writing_shows_running_then_prism_ai_done(self):
        d = _dialog()
        d.ask.set_text("CCTV for a warehouse")
        with mock.patch.object(d, "_run_stage") as rs:      # typed words only: the road is chosen for you
            d._run()
            self.assertTrue(rs.called)
            d._write()
        self.assertEqual(d.pipe.state("write"), route.RUNNING)
        with mock.patch.object(D.CB.config, "save_run", return_value=""), \
             mock.patch.object(d, "_offer_followup"):
            d._on_written({"format": ["1  Camera  3  nos"]}, {})
        self.assertEqual(d.pipe.state("write"), route.DONE)
        self.assertIn("Prism AI", d.pipe.line_of("write"))
        self.assertEqual(d.pipe.state("check"), route.NEEDS_YOU)

    def test_a_failed_write_says_why_and_never_blames_a_key_or_chrome(self):
        d = _dialog()
        d._set_input(route.CAD)
        with mock.patch.object(D.QMessageBox, "warning"):
            d._on_failed("Couldn't reach Prism's server. Nothing was charged.")
        self.assertEqual(d.pipe.state("write"), route.FAILED)
        self.assertIn("Nothing was charged", d.pipe.line_of("write"))

    def test_the_trade_chosen_applies_to_a_description_with_no_drawing(self):
        d = _dialog()
        d._pick_job(I.HVAC)
        d.ask.set_text("duct for a shop")
        with mock.patch.object(d, "_run_stage"):
            d._run()
        self.assertEqual(d._industry, I.HVAC)
        self.assertTrue(d._hvac)

    def test_detail_button_opens_the_right_step(self):
        d = _dialog()
        d._set_input(route.CAD)
        d._open_stage_detail("write")
        self.assertEqual(d._step, d.S_MAKE)
        d._open_stage_detail("check")
        self.assertEqual(d._step, d.S_COUNT)
        d._open_stage_detail("prices")
        self.assertEqual(d._step, d.S_PRICE)


class ThePdfAndPictureRoads(unittest.TestCase):
    def test_a_picture_marked_as_the_drawing_is_the_drawing_not_a_legend_screenshot(self):
        d = _dialog()
        d._set_input(route.SCAN)
        png = _png()
        d._absorb([png])
        self.assertEqual(d.cad_path, png)
        self.assertEqual(d.images, [])

    def test_without_saying_so_a_picture_stays_a_legend_screenshot_as_before(self):
        d = _dialog()
        d._absorb([_png()])
        self.assertEqual(d.cad_path, "")
        self.assertEqual(len(d.images), 1)

    def test_a_pdf_for_general_goes_to_the_ai_reads_it_road_after_consent(self):
        d = _dialog()
        pdf = _vector_pdf()
        d._absorb([pdf])
        self.assertEqual(d._input_kind, route.SCAN)
        self.assertTrue(d._with_drawing)
        d._refresh_primary()
        self.assertTrue(d.choice_drawing.selected())
        self.assertEqual(d.pipe.state("tags"), route.NEEDS_YOU)
        self.assertIn("With the drawing", d.pipe.line_of("tags"))

    def test_hvac_pdf_shows_the_measure_button_and_opens_the_tool_with_the_file_chosen(self):
        d = _dialog()
        d._pick_job(I.HVAC)
        pdf = _vector_pdf()
        d._set_input(route.SCAN)
        d._absorb([pdf])
        page = d.pages.widget(0)
        self.assertTrue(d.route_btn.isVisibleTo(page))
        self.assertIn("ducts", d.route_btn.text())
        self.assertFalse(d.takeoff_btn.isVisibleTo(page))     # one button, not two
        seen = {}

        class Fake:
            result = {"duct_runs": [{"length_ft": 100.0}], "labels": [{"source": "text", "conf": 1.0}],
                      "unread": [], "warnings": []}

            def __init__(self, industry, parent=None, cfg=None, path=""):
                seen["args"] = (industry, path)

            def exec(self):
                return QDialog.Accepted

            def measurements_text(self):
                return "DUCT SUMMARY supply 24x12 100 ft"

        with mock.patch.object(D, "IndustryTakeoffDialog", Fake):
            d._open_route_tool()
        self.assertEqual(seen["args"], (I.HVAC, pdf))
        self.assertEqual(d.pipe.state("measure"), route.DONE)
        self.assertIn("1 duct run", d.pipe.line_of("measure"))
        self.assertIn("On this computer", d.pipe.line_of("measure"))
        self.assertEqual(d.pipe.state("check"), route.NEEDS_YOU)
        self.assertIn("DUCT SUMMARY", d.summary)
        self.assertIn("Prism AI was not used", d.pipe.line_of("tags"))      # said, not implied

    def test_elv_picture_opens_the_reader_and_is_called_a_reading(self):
        d = _dialog()
        d._pick_job(I.ELV)
        d._set_input(route.SCAN)
        png = _png()
        d._absorb([png])
        seen = {}

        class Fake:
            result = {"method": "ai_tiled", "pages": [{"ocr_text": ["CAM-1"], "ai_text": "CAM-1"}], "notes": []}

            def __init__(self, industry, parent=None, cfg=None, path=""):
                seen["args"] = (industry, path)

            def exec(self):
                return QDialog.Accepted

            def measurements_text(self):
                return "THIS IS AN AI READING"

        with mock.patch.object(D, "ElvReadDialog", Fake):
            d._open_route_tool()
        self.assertEqual(seen["args"], (I.ELV, png))
        self.assertIn("Prism AI was used", d.pipe.line_of("tags"))
        self.assertIn("not a measurement", d.evidence_box.text().lower())


class Wording(unittest.TestCase):
    def test_no_ai_key_or_settings_agents_wording_reaches_the_user(self):
        d = _dialog({"api_key": ""})
        d.writer_combo.setCurrentIndex(0)
        shown = []
        with mock.patch.object(D.QMessageBox, "warning", side_effect=lambda *a: shown.append(a[2])):
            d._run_prism_agent("format", "Prism Agent Claude", "p", [], lambda *a: None)
        self.assertTrue(shown)
        for text in shown:
            for bad in ("OpenRouter", "Settings → Agents", "key"):
                self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main()
