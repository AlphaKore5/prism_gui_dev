"""BOQ road map: what the user has x what kind of job -> which steps run, and who does them.

Pure logic (addons/boq/route.py, evidence.py) plus the strip widget, offscreen.
"""
from __future__ import annotations
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-boq-route-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication              # noqa: E402
_app = QApplication.instance() or QApplication([])

from addons.boq import route, evidence, industries as I  # noqa: E402
from addons.boq.pipeline_strip import PipelineStrip      # noqa: E402


def keys(inp, ind, path=""):
    return [s.key for s in route.stages(inp, ind, path)]


class FileKinds(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(route.kind_of_file("a.DXF"), route.CAD)
        self.assertEqual(route.kind_of_file("a.dwg"), route.CAD)
        self.assertEqual(route.kind_of_file("a.pdf"), route.SCAN)
        self.assertEqual(route.kind_of_file("a.jpg"), route.SCAN)
        self.assertIsNone(route.kind_of_file("a.docx"))


class Availability(unittest.TestCase):
    def test_everything_works_except_ducts_from_a_picture(self):
        for inp in route.INPUTS:
            for ind in I.NAMES:
                ok, why = route.availability(inp, ind, "x.pdf")
                self.assertTrue(ok, (inp, ind, why))
        ok, why = route.availability(route.SCAN, I.HVAC, "plan.jpg")
        self.assertFalse(ok)
        self.assertIn("picture", why)
        self.assertTrue(route.availability(route.SCAN, I.ELV, "plan.jpg")[0])

    def test_every_job_card_names_a_real_industry(self):
        self.assertEqual(sorted(c[0] for c in route.JOB_CARDS), sorted(I.NAMES))


class Roads(unittest.TestCase):
    def test_dxf_general(self):
        self.assertEqual(keys(route.CAD, I.GENERAL),
                         ["read", "measure", "check", "write", "prices", "files"])

    def test_hvac_pdf_reads_ducts_then_tags_then_you_check(self):
        self.assertEqual(keys(route.SCAN, I.HVAC, "t.pdf"),
                         ["read", "measure", "tags", "check", "write", "prices", "files"])

    def test_a_drawing_never_goes_to_ai_in_the_measuring_steps_of_a_cad_file(self):
        for ind in I.NAMES:
            for s in route.stages(route.CAD, ind):
                if s.key in ("read", "measure"):
                    self.assertEqual(s.where, route.LOCAL)

    def test_writing_is_always_prism_ai_and_checking_is_always_the_user(self):
        for inp in route.INPUTS:
            for ind in I.NAMES:
                by = {s.key: s for s in route.stages(inp, ind, "x.pdf")}
                self.assertEqual(by["write"].where, route.AI)
                self.assertEqual(by["check"].where, route.YOU)

    def test_describe_says_the_quantities_are_estimates(self):
        st = route.stages(route.DESCRIBE, I.GENERAL)
        self.assertEqual(st[0].key, "describe")
        self.assertIn("estimate", st[1].detail.lower())

    def test_ai_reading_of_a_scan_is_labelled_a_reading_not_a_measurement(self):
        for ind in (I.GENERAL, I.ELV):
            tags = [s for s in route.stages(route.SCAN, ind, "a.png") if s.key == "tags"][0]
            self.assertIn("not a measurement", tags.detail.lower())
            self.assertIn(tags.where, (route.AI, route.LOCAL_AI))

    def test_no_chrome_or_agent_words_in_any_step(self):
        for inp in route.INPUTS:
            for ind in I.NAMES:
                for s in route.stages(inp, ind, "a.pdf"):
                    text = (s.label + s.detail).lower()
                    for bad in ("chrome", "openrouter", "/boq", "path", "agent", "browser"):
                        self.assertNotIn(bad, text)


class Evidence(unittest.TestCase):
    Q = {"entity_count": 249, "unit": "millimeters", "unit_code": 4, "unit_confirmed": True,
         "lengths_by_layer": {"A": 1.0, "B": 2.0}, "areas_by_layer": {"C": 5.0},
         "block_counts": {"CAM": 6, "REAder": 2}, "notes": ["A: pairs"], "site": {}}

    def test_quantities(self):
        ev = evidence.for_quantities(self.Q)
        self.assertEqual(ev["flagged"], 1)
        self.assertIn("8 symbols", ev["headline"])
        self.assertIn("Nothing here is an estimate", ev["basis"])

    def test_takeoff_counts_runs_labels_and_unreadable_tags(self):
        res = {"duct_runs": [{"length_ft": 100.0}, {"length_ft": 42.2}],
               "labels": [{"source": "text", "conf": 1.0}, {"source": "ocr0", "conf": 0.4}],
               "unread": [{"text": "?"}], "warnings": ["w"], "vav_tags": ["VAV-1-1"]}
        ev = evidence.for_takeoff(res)
        self.assertIn("2 duct run(s)", ev["headline"])
        self.assertIn("142", dict(ev["rows"])["Duct runs"])
        self.assertEqual(ev["flagged"], 2)           # one unreadable + one low-confidence read

    def test_a_picture_reading_is_never_called_measured(self):
        ev = evidence.for_reading({"method": "ai_tiled", "pages": [{"ocr_text": ["a"], "ai_text": "x"}]})
        self.assertEqual(ev["source"], "read")
        self.assertIn("not a measurement", ev["basis"].lower())

    def test_dxf_entity_reading_is_zero_ai(self):
        ev = evidence.for_reading({"method": "dxf_entities", "dxf": {"text": ["a"], "blocks": {"CAM": 3}}})
        self.assertEqual(ev["source"], "measured")

    def test_description_is_all_estimate(self):
        self.assertEqual(evidence.for_description()["source"], "estimated")

    def test_html_escapes(self):
        ev = evidence.for_quantities(dict(self.Q, notes=["<b>x</b>"]))
        self.assertNotIn("<b>x</b>", evidence.as_html(ev))


class Strip(unittest.TestCase):
    def test_states_lines_and_following_the_step_that_needs_you(self):
        s = PipelineStrip()
        s.set_route(route.stages(route.CAD, I.GENERAL))
        self.assertEqual(s.keys()[0], "read")
        self.assertEqual(s.state("read"), route.WAITING)
        s.set_stage("read", route.DONE, "read 249 objects")
        s.set_stage("check", route.NEEDS_YOU, "2 flagged")
        self.assertEqual(s.state("read"), route.DONE)
        self.assertEqual(s.selected(), "check")
        self.assertEqual(s.line_of("check"), "2 flagged")
        s.set_stage("write", route.FAILED, "no connection")
        self.assertEqual(s.selected(), "write")
        s.select("read")
        self.assertEqual(s.line.text(), "read 249 objects")

    def test_a_step_with_no_line_says_what_it_does(self):
        s = PipelineStrip()
        s.set_route(route.stages(route.CAD, I.GENERAL))
        self.assertIn("converted", s.line.text())

    def test_a_new_route_replaces_the_old_tiles_at_once(self):
        s = PipelineStrip()
        s.set_route(route.stages(route.CAD, I.GENERAL))
        s.set_route(route.stages(route.DESCRIBE, I.GENERAL))
        self.assertEqual(s._row.count(), len(route.stages(route.DESCRIBE, I.GENERAL)))
        self.assertEqual(len(s.findChildren(type(s._tiles["describe"]))), 5)

    def test_details_button_asks_for_the_selected_step(self):
        s = PipelineStrip()
        s.set_route(route.stages(route.CAD, I.GENERAL))
        got = []
        s.detail_requested.connect(got.append)
        s.select("write")
        s.detail_btn.click()
        self.assertEqual(got, ["write"])


if __name__ == "__main__":
    unittest.main()
