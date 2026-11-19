"""The scale view: choose the page, zoom, snap, markers, undo, units, closest standard scale.
Hitarth's scale arithmetic (pixel distance at dpi -> points -> points per foot) is unchanged and
is still checked in test_boq_takeoff. Client PDFs are never kept in the repo: a small vector
drawing is made here with matplotlib; the real client samples are read only if present."""
from __future__ import annotations

import math
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-scale-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME
from PySide6.QtWidgets import QApplication                  # noqa: E402

_app = QApplication.instance() or QApplication([])
import theme                                                 # noqa: E402
theme.load_fonts()
from addons.boq import scale_view as SV, industries as I     # noqa: E402
from addons.boq.workers import PageScanWorker                # noqa: E402

def _real_home():
    try:
        import pwd                                  # Unix only; tests may have a sandboxed HOME
        return pwd.getpwuid(os.getuid()).pw_dir
    except ImportError:
        return os.path.expanduser("~")
REAL = os.path.join(_real_home(), "prism-test-data", "client") + os.sep


def _plan_pdf(pages_with_lines=(1,), n_pages=2) -> str:
    """A 2-page PDF: the pages listed get a lot of drawn lines (a "plan"), the others only text."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    p = os.path.join(tempfile.mkdtemp(dir=_HOME), "plan.pdf")
    with PdfPages(p) as pdf:
        for i in range(n_pages):
            fig = plt.figure(figsize=(8.27, 11.69))
            ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 595); ax.set_ylim(0, 842); ax.axis("off")
            if i in pages_with_lines:
                for k in range(400):
                    ax.plot([20 + k * 1.4, 20 + k * 1.4], [100, 700], color="black", lw=0.5)
                    ax.plot([40, 520], [100 + k * 1.5, 100 + k * 1.5], color="black", lw=0.5)
            else:
                ax.text(50, 400, "A table of words only", fontsize=12)
            pdf.savefig(fig)
            plt.close(fig)
    return p


def _wait(dlg):
    """Let the page scan finish, and the follow-up scan a page change starts."""
    for _ in range(4):
        scan = dlg._scan
        if scan is not None:
            scan.wait(30000)
        for _ in range(3):
            _app.processEvents()
        if dlg._scan is scan:
            break


def _dialog(path, page=None):
    d = SV.ScaleMeasureDialog(path, page, None, industry=I.HVAC)
    d.show()
    _wait(d)
    return d


class WhichPage(unittest.TestCase):
    def test_the_page_with_the_most_drawn_lines_is_offered_first_and_labelled(self):
        d = _dialog(_plan_pdf(pages_with_lines=(1,)), None)
        self.assertEqual(d.page_index, 1)
        self.assertEqual(d.page_combo.count(), 2)
        self.assertIn("Page 2 of 2", d.page_combo.currentText())
        self.assertIn("most drawn lines", d.page_combo.currentText())
        self.assertNotIn("Few drawn lines", d.page_note.text())
        self.assertIn("Extract reads every page", d.page_note.text())

    def test_picking_another_page_shows_it_and_clears_the_points(self):
        d = _dialog(_plan_pdf(), None)
        d._on_click(100, 100)
        d.page_combo.setCurrentIndex(0)
        self.assertEqual(d.page_index, 0)
        self.assertEqual(d._points, [])
        _wait(d)
        self.assertIn("Few drawn lines", d.page_note.text())     # page 1 is words only: said honestly

    def test_a_chosen_page_is_kept(self):
        d = _dialog(_plan_pdf(), 0)
        self.assertEqual(d.page_index, 0)


class TheView(unittest.TestCase):
    def test_the_view_fills_the_dialog_and_wheel_zoom_changes_the_level(self):
        d = _dialog(_plan_pdf(), None)
        self.assertGreater(d.view.height(), 300)
        before = d.view.zoom_level()
        d.view.zoom_by(2.0)
        self.assertAlmostEqual(d.view.zoom_level(), before * 2, places=3)
        d.view.zoom_by(1e6)
        self.assertAlmostEqual(d.view.zoom_level(), 60.0, places=3)    # clamped
        d.view.fit()
        self.assertAlmostEqual(d.view.zoom_level(), before, places=1)

    def test_snaps_to_a_line_end_near_the_click_but_not_far_from_one(self):
        d = _dialog(_plan_pdf(), None)
        self.assertTrue(d._snap)                                  # corners/line ends were found
        px, py = next(iter(next(iter(d._snap.values()))))
        sx, sy, hit = d._snap_to(px + 3, py - 2)
        self.assertTrue(hit)
        self.assertEqual((round(sx, 3), round(sy, 3)), (round(px, 3), round(py, 3)))
        _, _, hit_far = d._snap_to(-5000, -5000)
        self.assertFalse(hit_far)

    def test_markers_label_start_and_end_and_show_the_paper_length(self):
        d = _dialog(_plan_pdf(), None)
        d._on_click(100, 100)
        self.assertIn("Step 2 of 3", d.points_label.text())
        d._on_click(200, 100)
        self.assertIn("Step 3 of 3", d.points_label.text())
        self.assertIn("72.0 points", d.points_label.text())        # 100 px at 100 dpi = 72 pt
        self.assertIn("25.4 mm", d.points_label.text())

    def test_undo_and_start_again(self):
        d = _dialog(_plan_pdf(), None)
        d._on_click(0, 0); d._on_click(100, 0)
        d.undo()
        self.assertEqual(len(d._points), 1)
        d.restart()
        self.assertEqual(d._points, [])
        self.assertFalse(d.use_btn.isEnabled())

    def test_the_instruction_is_plain(self):
        d = _dialog(_plan_pdf(), None)
        texts = " ".join(l.text() for l in d.findChildren(SV.QLabel))
        self.assertIn("Click one end of a ruler line or a labelled dimension, then the other end, "
                      "then type its real length.", texts)


class UnitsAndTheResultingScale(unittest.TestCase):
    def _two_points(self, d):
        d._on_click(0, 0); d._on_click(100, 0)               # 72 pt on paper

    def test_feet_metres_and_millimetres_all_give_the_same_scale_for_the_same_length(self):
        d = _dialog(_plan_pdf(), None)
        self._two_points(d)
        got = {}
        for label, value in (("ft", "10"), ("m", str(10 * 0.3048)), ("mm", str(10 * 304.8))):
            d.unit_combo.setCurrentIndex([u for u, _ in SV.UNITS].index(label))
            d.distance_edit.setText(value)
            got[label] = d.pt_per_ft
        self.assertAlmostEqual(got["ft"], 7.2)
        self.assertAlmostEqual(got["m"], 7.2)
        self.assertAlmostEqual(got["mm"], 7.2)

    def test_the_closest_standard_scale_is_named_when_it_is_close(self):
        d = _dialog(_plan_pdf(), None)
        eighth = I.scales(I.HVAC)['1/8" = 1\'-0"']                # 9 pt per foot
        self._two_points(d)
        d.distance_edit.setText(str(72.0 / eighth))
        self.assertEqual(d.closest_label, '1/8" = 1\'-0"')
        self.assertIn("standard scale", d.result_label.text())
        d.distance_edit.setText("3")                              # 24 pt/ft: nothing standard is near
        self.assertIsNone(d.closest_label)
        self.assertIn("Your measured scale will be used", d.result_label.text())

    def test_closest_standard_helper(self):
        label, close = SV.closest_standard(9.0, I.scales(I.HVAC))
        self.assertEqual(label, '1/8" = 1\'-0"')
        self.assertGreater(close, 0.99)
        self.assertEqual(SV.closest_standard(9.0, {}), (None, 0.0))


class TheToolRemembersThePage(unittest.TestCase):
    def test_the_page_measured_on_is_passed_next_time_and_reset_for_a_new_pdf(self):
        from addons.boq import takeoff as T
        t = T.IndustryTakeoffDialog(I.HVAC, None, cfg={})
        t.pdf_path = "/x/a.pdf"
        fake = mock.Mock(pt_per_ft=9.0, page_index=1, closest_label=None)
        fake.exec.return_value = T.QDialog.Accepted
        with mock.patch.object(T, "_ScaleMeasureDialog", return_value=fake) as ctor:
            t._open_measure_dialog()
            t._open_measure_dialog()
        self.assertIsNone(ctor.call_args_list[0].args[1])         # first time: auto page
        self.assertEqual(ctor.call_args_list[1].args[1], 1)       # then: the sheet used before
        self.assertIn("page 2", t.measured_scale_label.text())
        with mock.patch.object(T.industries, "scan_layers", return_value=[]):
            t._load_pdf("/x/b.pdf")
        self.assertIsNone(t._scale_page)


class TheRealClientSamples(unittest.TestCase):
    """Honest finding: 201_wo_ai.pdf and 205.pdf are Prism's own BOQ OUTPUT (tables), not
    tender drawings, so the view must say so rather than pretend there is a plan to measure."""

    @unittest.skipUnless(os.path.exists(REAL + "205.pdf"), "client sample not on this machine")
    def test_a_boq_table_pdf_is_called_a_table(self):
        d = _dialog(REAL + "205.pdf", None)
        self.assertEqual(d.page_combo.count(), 3)
        self.assertIn("Few drawn lines", d.page_note.text())


if __name__ == "__main__":
    unittest.main()
