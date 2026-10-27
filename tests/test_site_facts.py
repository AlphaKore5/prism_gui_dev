"""What the coordinates say: the unit, look-alike layers, remote structures.

Three things a person settles in a minute from a drawing and a table of
totals cannot, all met on one site survey on 10 Sep 2026: the unit was
"unconfirmed" in every BOQ written from it although the coordinates are a
survey grid in metres; one estimator dropped half the perimeter as a
"duplicate" layer that was in fact the other half of the same wall; and
six of seven pump houses sat kilometres away on a pipeline and were
counted onto the campus network. Each is answerable locally, from entity
coordinates, and now is.

The drawing here is built with ezdxf in a temp folder; nothing real is
read and nothing is sent anywhere.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

boq = CB.get_boq()

try:
    import ezdxf
except ImportError:                                   # pragma: no cover
    ezdxf = None


def _site(path):
    """A campus on a survey grid: a 400 x 300 m wall drawn as two open
    runs on two mis-spelt layers, a 7 m gate block drawn in mm and placed
    at 0.001, poles on the campus, and two pump houses 2 km away."""
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 0          # the unit was never recorded
    msp = doc.modelspace()
    x0, y0 = 213_400.0, 2_755_100.0
    # west + north sides on one layer, east + south on the other: open runs
    msp.add_lwpolyline([(x0, y0), (x0, y0 + 300), (x0 + 400, y0 + 300)],
                       dxfattribs={"layer": "BOUNDARY WALL"})
    msp.add_lwpolyline([(x0 + 400, y0 + 300), (x0 + 400, y0), (x0, y0)],
                       dxfattribs={"layer": "Boundrary Wall"})
    # a road inside, unrelated to the wall
    msp.add_lwpolyline([(x0 + 50, y0 + 50), (x0 + 350, y0 + 50)],
                       dxfattribs={"layer": "Concrete Road"})
    gate = doc.blocks.new("MAIN-GATE-7M")
    gate.add_line((0, 0), (7000, 0))          # drawn in millimetres
    for i in range(2):
        msp.add_blockref("MAIN-GATE-7M", (x0 + 100 + i * 200, y0),
                         dxfattribs={"xscale": 0.001, "yscale": 0.001})
    pole = doc.blocks.new("EP")
    pole.add_circle((0, 0), 0.3)
    for i in range(5):
        msp.add_blockref("EP", (x0 + 60 * i, y0 + 150))
    pump = doc.blocks.new("PUMP HOUSE")
    pump.add_line((0, 0), (5, 5))
    msp.add_blockref("PUMP HOUSE", (x0 + 200, y0 + 200))          # on campus
    msp.add_blockref("PUMP HOUSE", (x0 + 2200, y0 + 200))         # 2 km east
    msp.add_blockref("PUMP HOUSE", (x0 + 200, y0 - 2500))         # 2.5 km south
    doc.saveas(path)


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class TheCoordinatesSpeak(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(prefix="prism-site-"), "site.dxf")
        _site(cls.path)
        cls.q = boq.measure(cls.path)
        cls.site = cls.q["site"]

    def test_the_unit_is_inferred_from_the_grid_and_the_gate_block(self):
        self.assertFalse(self.q["unit_confirmed"])
        self.assertEqual(self.site["unit_inferred"], "meters")
        evidence = " ".join(self.site["unit_evidence"])
        self.assertIn("survey grid", evidence)
        self.assertIn("MAIN-GATE-7M", evidence)
        self.assertIn("scale 0.001", evidence)      # exactly 0.001 in this drawing

    def test_two_open_runs_on_lookalike_layers_are_one_wall(self):
        lk = [l for l in self.site["lookalikes"]
              if set(l["layers"]) == {"BOUNDARY WALL", "Boundrary Wall"}]
        self.assertEqual(len(lk), 1)
        self.assertIn("one feature drawn on two layers", lk[0]["verdict"])
        self.assertAlmostEqual(lk[0]["combined"], 1400.0, delta=1)
        self.assertAlmostEqual(lk[0]["box_perimeter"], 1400.0, delta=1)

    def test_a_road_inside_the_wall_is_not_called_a_lookalike(self):
        pairs = [set(l["layers"]) for l in self.site["lookalikes"]]
        self.assertNotIn({"BOUNDARY WALL", "Concrete Road"}, pairs)
        self.assertNotIn({"Boundrary Wall", "Concrete Road"}, pairs)

    def test_far_away_blocks_are_flagged_with_their_distance(self):
        remote = {r["name"]: r for r in self.site["remote_blocks"]}
        self.assertIn("PUMP HOUSE", remote)
        self.assertEqual((remote["PUMP HOUSE"]["count"], remote["PUMP HOUSE"]["of"]), (2, 3))
        self.assertTrue(all(d > 1000 for d in remote["PUMP HOUSE"]["distances_m"]))
        self.assertNotIn("EP", remote)

    def test_the_extent_is_the_campus_not_the_pipeline(self):
        ext = self.site["extent"]
        self.assertLess(ext["width"], 500)
        self.assertLess(ext["height"], 500)

    def test_the_facts_reach_the_summary_the_ai_reads(self):
        text = boq.summary_text(self.q)
        self.assertIn("UNIT INFERRED FROM THE COORDINATES: METERS", text)
        self.assertIn("LOOK-ALIKE LAYERS: 'BOUNDARY WALL'", text)
        self.assertIn("REMOTE: 2 of 3 'PUMP HOUSE'", text)

    def test_the_facts_reach_the_screen(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from addons.boq.measured import MeasuredTable
        t = MeasuredTable()
        t.set_quantities(self.q)
        self.assertIn("meters (inferred from the coordinates)", t.header.text())
        # 23 Oct 2026: warnings live in the collapsed bulleted dropdown now,
        # not one ever-growing label -- see warning_lines()/warn_list.
        lines = " ".join(t.warning_lines())
        self.assertIn("Look-alike layers BOUNDARY WALL and Boundrary Wall", lines)
        self.assertIn("2 of 3 PUMP HOUSE blocks are", lines)

    def test_a_drawing_with_a_recorded_unit_is_not_second_guessed(self):
        path = os.path.join(tempfile.mkdtemp(prefix="prism-site-"), "mm.dxf")
        doc = ezdxf.new("R2018"); doc.header["$INSUNITS"] = 4       # millimetres
        msp = doc.modelspace()
        msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "WALL"})
        doc.saveas(path)
        q = boq.measure(path)
        self.assertTrue(q["unit_confirmed"])
        self.assertEqual(q["site"]["unit_inferred"], "")


if __name__ == "__main__":
    unittest.main()
