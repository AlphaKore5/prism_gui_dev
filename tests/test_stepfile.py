"""core/stepfile.py — /step, the estimator's first hour done offline.

Ground truth is the customer's own hand-made drawing sheet for the demo
assembly (step_file_demo/Assem1.STEP, SolidWorks, three sheet-metal
parts): the formed views on its right-hand side give top = 101 x 93 x 71,
side = 92 x 68.5 with 6 mm flanges, and the holes Ø13 / Ø6.2 / Ø9 / Ø5.2.
Those numbers are pinned here as witnessed — if they move, the reading is
wrong, not the drawing.

Synthetic truth-by-construction backs it: a box of known size with one
known hole, exported to STEP and read back.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

# Where the real customer jobs live on this machine — an env var with the
# old hardcoded Mac path as its fallback. See tests/sample_jobs.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sample_jobs  # noqa: E402

from core import stepfile as SF  # noqa: E402

HAVE = SF.available()[0]
REAL = sample_jobs.path("step_file_demo", "Assem1.STEP")


def _box_with_hole(path: str):
    """A 60 x 40 x 8 mm block with one Ø5 through hole — every figure
    known by construction."""
    import cadquery as cq
    part = (cq.Workplane("XY").box(60, 40, 8)
            .faces(">Z").workplane().hole(5))
    cq.exporters.export(part, path)


@unittest.skipUnless(HAVE, "cadquery not installed")
class ABoxOfKnownSize(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="plastic")

    def test_the_size_is_the_boxs(self):
        self.assertEqual(len(self.report["parts"]), 1)
        self.assertEqual(self.report["parts"][0]["size_mm"], (60.0, 40.0, 8.0))
        self.assertEqual(self.report["overall_mm"], (60.0, 40.0, 8.0))

    def test_the_hole_is_found_once_at_its_diameter(self):
        holes = self.report["parts"][0]["holes"]
        self.assertEqual(holes, [{"dia_mm": 5.0, "count": 1}])

    def test_volume_is_the_boxs_minus_the_hole(self):
        expected = (60 * 40 * 8 - 3.14159 * 2.5 ** 2 * 8) / 1000
        self.assertAlmostEqual(self.report["parts"][0]["volume_cm3"],
                               expected, delta=0.05)

    def test_plastic_mode_prices_the_shot_not_the_sheet(self):
        text = SF.report_text(self.report)
        self.assertIn("plastic moulding", text)
        self.assertIn("wall≈", text)
        self.assertIn("ABS", text)

    def test_every_figure_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)", SF.report_text(self.report)):
            self.assertLessEqual(len(number), 2)


@unittest.skipUnless(HAVE, "cadquery not installed")
class TheBriefForTheImageAgent(unittest.TestCase):
    """/step-auto's prompt: exact measured figures in, the model kept out."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.brief = SF.auto_brief(SF.analyse(cls.path, mode="plastic"))

    def test_the_measured_figures_are_in_it_verbatim(self):
        self.assertIn("60.00 x 40.00 x 8.00 mm", self.brief)
        self.assertIn("Ø5 x 1", self.brief)

    def test_it_says_the_model_is_not_shared(self):
        self.assertIn("MEASURED OFFLINE", self.brief)
        self.assertIn("is not shared", self.brief)

    def test_it_forbids_invented_numbers(self):
        self.assertIn("EXACTLY the numbers above", self.brief)
        self.assertIn("do not round", self.brief)

    def test_it_forbids_fake_flat_patterns_and_tolerances(self):
        """ChatGPT's first real sheet labelled a decorative view 'FLAT
        PATTERN' and invented a ±0.05 tolerance note — both are the kind of
        plausible extra a fabricator would act on."""
        self.assertIn("Never label any view 'flat pattern'", self.brief)
        self.assertIn("Do not state any tolerance", self.brief)

    def test_every_figure_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)", self.brief):
            self.assertLessEqual(len(number), 2)


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "Assem1.STEP") or ""))
class TheCustomersOwnEnclosure(unittest.TestCase):
    """Witnessed against the fab's hand-made drawing sheet."""

    @classmethod
    def setUpClass(cls):
        cls.report = SF.analyse(REAL, mode="metal")
        cls.by_name = {p["name"]: p for p in cls.report["parts"]}

    def test_the_three_parts_keep_their_names(self):
        self.assertEqual(set(self.by_name), {"top", "bottom", "side"})

    def test_the_top_cover_matches_the_drawing(self):
        self.assertEqual(self.by_name["top"]["size_mm"], (101.0, 93.0, 71.0))

    def test_the_side_panel_matches_the_drawing(self):
        self.assertEqual(self.by_name["side"]["size_mm"], (92.0, 68.5, 6.0))

    def test_the_drawings_named_holes_are_all_found(self):
        top = {h["dia_mm"] for h in self.by_name["top"]["holes"]}
        bottom = {h["dia_mm"] for h in self.by_name["bottom"]["holes"]}
        self.assertIn(13.0, top)
        self.assertIn(6.2, top)
        self.assertIn(9.0, bottom)
        self.assertIn(5.2, bottom)

    def test_the_sheet_reads_as_one_millimetre(self):
        for part in self.report["parts"]:
            self.assertGreater(part["thickness_mm"], 0.8)
            self.assertLess(part["thickness_mm"], 1.05)

    def test_the_report_says_formed_not_flat(self):
        self.assertIn("FORMED", SF.report_text(self.report))

    def test_the_excel_sheet_carries_every_part(self):
        import openpyxl
        out = os.path.join(tempfile.mkdtemp(), "dimensions.xlsx")
        SF.write_xlsx(self.report, out)
        wb = openpyxl.load_workbook(out)
        body = "\n".join(str(c.value) for row in wb["Parts"].iter_rows()
                         for c in row if c.value is not None)
        for name in ("top", "bottom", "side"):
            self.assertIn(name, body)
        self.assertIn("101.0", body)
        self.assertEqual(wb["Holes"].max_row - 1,
                         sum(len(p["holes"]) for p in self.report["parts"]))

    def test_the_holes_sheet_names_the_same_tags_as_the_drawing(self):
        import openpyxl
        out = os.path.join(tempfile.mkdtemp(), "dimensions.xlsx")
        SF.write_xlsx(self.report, out)
        wb = openpyxl.load_workbook(out)
        rows = list(wb["Holes"].iter_rows(values_only=True))
        header = rows[0]
        self.assertEqual(header[-1], "Tags")
        top_13 = [r for r in rows[1:] if r[0] == "top" and r[1] == 13.0][0]
        self.assertEqual(top_13[-1], "H3")
        # The 18-hole vent row is one GROUP tag, not 18 repeats of it.
        top_3 = [r for r in rows[1:] if r[0] == "top" and r[1] == 3.0][0]
        self.assertEqual(top_3[-1], "G5")

    def test_the_drawing_sheet_shows_every_part(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        self.assertGreater(os.path.getsize(drawn["png"]), 5000)
        from PIL import Image
        img = Image.open(drawn["png"])
        self.assertGreater(img.width, 100)
        self.assertGreater(img.height, 100)
        for name in ("top", "bottom", "side"):
            self.assertIn(name, drawn["flats"])
            self.assertTrue(os.path.exists(drawn["flats"][name]))
        # The sheet itself carries the model's name.
        self.assertEqual(os.path.basename(drawn["png"]),
                         "Assem1 - drawing sheet.png")


REAL_CORE = sample_jobs.path("step_file_demo", "PET CORE 02 06.STEP")


@unittest.skipUnless(HAVE and os.path.exists(REAL_CORE),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "PET CORE 02 06.STEP") or ""))
class TheMouldersOwnCore(unittest.TestCase):
    """A real customer part whose Draft once read 19 holes for a part with
    roughly 11-13: one threaded, chamfered bore's diameter bands (16.50 /
    18.00 / 19.00 / 24.50 mm, all one axis -- fifteen of the "18.00" faces
    are thread-crest slivers under 0.1 mm long) were each counted as their
    own hole, AND four of its round features (Ø10.0, convex -- locating
    pins/bosses on this mould core, not bores) were counted as holes too.
    Pinned here, witnessed directly against this file's own faces, so that
    regression never comes back quietly."""

    @classmethod
    def setUpClass(cls):
        cls.report = SF.analyse(REAL_CORE, mode="metal")
        cls.holes = cls.report["parts"][0]["holes"]

    def test_the_stepped_bore_reads_as_one_hole_not_four(self):
        dias = {h["dia_mm"] for h in self.holes}
        self.assertNotIn(18.0, dias)
        self.assertNotIn(19.0, dias)
        self.assertIn(24.5, dias)

    def test_a_convex_boss_is_not_read_as_a_hole(self):
        dias = {h["dia_mm"] for h in self.holes}
        self.assertNotIn(10.0, dias)

    def test_the_hole_count_did_not_explode(self):
        self.assertEqual(sum(h["count"] for h in self.holes), 13)  # was 19


REAL_TEST_B = sample_jobs.path("step_file_demo", "PET_CORE_TEST_B.STEP")


@unittest.skipUnless(HAVE and os.path.exists(REAL_TEST_B),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "PET_CORE_TEST_B.STEP") or ""))
class TheNamedHoleScheduleOfSampleB(unittest.TestCase):
    """A deliberately hard feature-recognition test block (23 holes, 5
    faces, every hole individually tagged B1-B23 with its own stages on
    the sender's own PDF hole schedule) and 4 rounded OUTER corners
    (R6, "4 PL.") that are not holes at all. Ground truth is that PDF's
    own schedule, totalled by this test the same way _holes_of groups
    them: one position per tag, at that tag's LARGEST stage diameter.
    Before the corner-fillet fix this read as 27 holes (a phantom
    "Ø12 x4" from the 4 corners); before the stepped-hole fix it would
    also have split B1, B8-B11 and B15-B18's multi-stage bores apart."""

    @classmethod
    def setUpClass(cls):
        cls.report = SF.analyse(REAL_TEST_B, mode="metal")
        cls.holes = cls.report["parts"][0]["holes"]

    def test_matches_the_senders_own_hole_schedule_exactly(self):
        # TAG: largest Ø stage, from the PDF's own HOLE SCHEDULE table.
        expected = {3.0: 2, 4.0: 5, 6.0: 7, 8.0: 2, 10.0: 2, 15.0: 4, 22.0: 1}
        got = {h["dia_mm"]: h["count"] for h in self.holes}
        self.assertEqual(got, expected)

    def test_the_total_is_23_not_27(self):
        self.assertEqual(sum(h["count"] for h in self.holes), 23)

    def test_no_phantom_corner_hole(self):
        self.assertNotIn(12.0, {h["dia_mm"] for h in self.holes})

    def test_every_hole_is_individually_tagged(self):
        named = SF._named_holes(self.report["_shapes"][0][1])
        self.assertEqual(len(named), 23)
        self.assertEqual([h["tag"] for h in named],
                         [f"H{i}" for i in range(1, 24)])
        # Every tag lands on one of the three views Prism actually draws —
        # the one that shows that hole as a circle to point an arrow at.
        for h in named:
            self.assertIn(h["view"], {"FRONT VIEW", "TOP VIEW", "SIDE VIEW"})

    def test_the_drawing_sheet_names_and_points_at_every_hole(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        self.assertGreater(os.path.getsize(drawn["png"]), 5000)
        svg = SF.sheet_svg(self.report)
        for tag in ("H1", "H10", "H23"):
            self.assertIn(tag, svg)
        # One leader-arrow colour per tagged hole, not the plain black
        # lines the rest of the drawing uses.
        self.assertIn("#1a5fb4", svg)

    def test_asking_for_one_tagged_hole_leaves_its_six_siblings_alone(self):
        """Ø6 has 7 real holes (H11, H14, H15, H16, H18, H19, H22) on this
        part. Before hole-tagging, "enlarge this one" could only ever say
        "enlarge the Ø6 holes" and grow all 7 at once. Naming H11 must
        grow exactly that one and leave the other six Ø6 holes be."""
        out = os.path.join(tempfile.mkdtemp(), "one-hole.step")
        plan = {"changes": [{"op": "enlarge_hole", "part": "PET_CORE_TEST_B",
                             "dia_mm": 6.0, "new_dia_mm": 7.0,
                             "hole": "H11", "why": "fit a bolt"}],
                "advice": []}
        done = SF.apply_plan(REAL_TEST_B, plan, out)
        self.assertTrue(any("H11" in l and "1 hole(s) enlarged" in l
                            for l in done["log"]), done["log"])
        after = SF.analyse(out, mode="metal")["parts"][0]["holes"]
        by_dia = {h["dia_mm"]: h["count"] for h in after}
        self.assertEqual(by_dia.get(6.0), 6)    # one left this group
        self.assertEqual(by_dia.get(7.0), 1)    # ... and landed in a new one

        pred = SF.predicted_parts(self.report, plan)[0]["holes"]
        pred_by_dia = {h["dia_mm"]: h["count"] for h in pred}
        self.assertEqual(pred_by_dia.get(6.0), 6)
        self.assertEqual(pred_by_dia.get(7.0), 1)


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "Assem1.STEP") or ""))
class TheFlatPatternOfTheCustomersEnclosure(unittest.TestCase):
    """The gap the drawing sheet's own warning used to name out loud:
    'a bent sheet's flat pattern is not shown.' Witnessed against the same
    real job as TheCustomersOwnEnclosure -- three real formed parts,
    real bends, real holes."""

    @classmethod
    def setUpClass(cls):
        cls.report = SF.analyse(REAL, mode="metal")
        cls.by_name = {p["name"]: p for p in cls.report["parts"]}

    def test_all_three_parts_unfold(self):
        for name in ("top", "bottom", "side"):
            self.assertIsNotNone(self.by_name[name]["flat"], name)

    def test_the_bottom_panels_square_window_is_not_invisible(self):
        """Checked against a fabricator's own reference drawing of this
        exact job: a real 46 x 46 mm square window cut into the bottom
        panel. unfold() used to read only each face's OUTER wire — the
        window is an INNER wire, cut into the middle of a face, and was
        silently never looked at: drawn as nothing at all, not even a
        gap in the outline. Any panel with a genuine non-round opening
        should carry it now."""
        cutouts = self.by_name["bottom"]["flat"]["cutouts"]
        self.assertTrue(cutouts, "no cutouts found on 'bottom' at all")
        sizes = [(round(max(x for x, _ in c) - min(x for x, _ in c), 1),
                 round(max(y for _, y in c) - min(y for _, y in c), 1))
                for c in cutouts]
        self.assertIn((46.0, 46.0), sizes, sizes)

    def test_the_flat_size_is_not_the_formed_size(self):
        """The whole point: a bend adds real flat length that the formed
        bounding box does not show."""
        for name in ("top", "bottom", "side"):
            flat_w, flat_h = self.by_name[name]["flat"]["flat_size_mm"]
            formed = self.by_name[name]["size_mm"]
            self.assertGreater(flat_w * flat_h, 0)
            # At least one flat dimension exceeds every formed dimension --
            # several formed legs straightened into one flat run.
            self.assertTrue(flat_w > max(formed) or flat_h > max(formed),
                            (name, flat_w, flat_h, formed))

    def test_every_hole_lands_inside_the_flat_outline(self):
        """Regression: a hole once landed 64 mm outside its own panel
        because the nearest-plane test picked a different, merely nearby,
        flat face instead of the one the hole is actually on."""
        for name, part in self.by_name.items():
            flat = part["flat"]
            if not flat:
                continue
            w, h = flat["flat_size_mm"]
            for hole in flat["holes"]:
                self.assertGreaterEqual(hole["x"], -0.01, (name, hole))
                self.assertGreaterEqual(hole["y"], -0.01, (name, hole))
                self.assertLessEqual(hole["x"], w + 0.01, (name, hole))
                self.assertLessEqual(hole["y"], h + 0.01, (name, hole))

    def test_bend_lines_are_ninety_degrees_on_this_job(self):
        for part in self.by_name.values():
            for bend in (part["flat"] or {}).get("bend_lines", []):
                self.assertAlmostEqual(bend["angle_deg"], 90.0, places=1)

    def test_a_bigger_k_factor_makes_a_bigger_flat_pattern(self):
        """The bend-allowance formula is angle x (radius + K x thickness) —
        strictly increasing in K, so a bigger K-factor must never produce a
        smaller (or equal) flat pattern for a part that actually has a
        bend in it."""
        low = SF.analyse(REAL, mode="metal", k_factor=0.2)
        high = SF.analyse(REAL, mode="metal", k_factor=0.45)
        low_by = {p["name"]: p for p in low["parts"]}
        high_by = {p["name"]: p for p in high["parts"]}
        grew = False
        for name in ("top", "bottom", "side"):
            lo, hi = low_by[name]["flat"], high_by[name]["flat"]
            if not lo or not hi:
                continue
            self.assertGreaterEqual(hi["flat_size_mm"][0] * hi["flat_size_mm"][1],
                                    lo["flat_size_mm"][0] * lo["flat_size_mm"][1],
                                    name)
            if hi["flat_size_mm"] != lo["flat_size_mm"]:
                grew = True
        self.assertTrue(grew, "no part's flat size changed with K-factor at all")

    def test_the_default_k_factor_is_stated_not_silent(self):
        self.assertEqual(self.report["k_factor"], SF._DEFAULT_K_FACTOR)
        self.assertTrue(any("K-factor" in w for w in self.report["warnings"]))

    def test_a_custom_k_factor_is_stated_as_entered(self):
        report = SF.analyse(REAL, mode="metal", k_factor=0.38)
        self.assertEqual(report["k_factor"], 0.38)
        self.assertTrue(any("as entered" in w for w in report["warnings"]))

    def test_plastic_mode_never_computes_a_flat_pattern(self):
        report = SF.analyse(REAL, mode="plastic")
        for part in report["parts"]:
            self.assertIsNone(part["flat"])

    def test_the_drawing_sheet_shows_the_flat_pattern(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        self.assertTrue(os.path.exists(drawn["png"]))
        self.assertTrue(drawn["flats"])
        for path in drawn["flats"].values():
            self.assertTrue(os.path.exists(path))
            self.assertGreater(os.path.getsize(path), 2000, path)

    def test_the_square_window_is_drawn_and_sized_on_the_page(self):
        html = SF.sheet_svg(self.report)
        self.assertIn("46.00 x 46.00", html)

    def test_a_round_holes_inner_wire_is_not_double_drawn_as_a_cutout(self):
        """A plain punched hole's boundary is ALSO an inner wire on its
        face — the same wire-walk that finds a real window would find
        every ordinary hole too, if it did not filter out the
        degenerate ones. It must not: a hole is already drawn once, as a
        circle, from its cylindrical face."""
        for part in self.by_name.values():
            flat = part["flat"]
            if not flat:
                continue
            hole_count = len(flat["holes"])
            cutout_count = len(flat.get("cutouts", []))
            # Real cutouts on this job are a handful at most; nowhere near
            # one per hole, which is what "every hole's wire leaked
            # through as a cutout too" would look like.
            self.assertLess(cutout_count, max(hole_count, 1),
                            (part["name"], hole_count, cutout_count))

    def test_a_ventilation_grilles_cutouts_are_not_each_individually_labelled(self):
        """Regression: the 'top' part's vent row is a real STEP feature —
        eighteen individually-real rectangular cutouts, not one shape
        Prism invented — and the first version of cutout labelling wrote
        a size on every single one of them, which at that spacing prints
        as an overlapping smear exactly like the hole-position chain did
        before it got the same one-label-per-distinct-value rule. Cutout
        labels follow it too now."""
        html = SF.sheet_svg(self.report)
        top = self.by_name["top"]["flat"]
        cutouts = top.get("cutouts", [])
        self.assertGreater(len(cutouts), 5,
                           "the vent row itself should still be many real cutouts")
        sizes = set()
        for c in cutouts:
            xs = [p[0] for p in c]
            ys = [p[1] for p in c]
            sizes.add((round(max(xs) - min(xs), 1), round(max(ys) - min(ys), 1)))
        # However many individual vent slats there are, the PAGE should
        # only ever carry one label text per distinct size among them.
        for w, h in sizes:
            self.assertEqual(html.count(f"{w:.2f} x {h:.2f}"), 1, (w, h))

    def test_flat_pattern_and_isometric_are_separate_labelled_sections(self):
        """The owner's own complaint: the formed 3-view band buried the
        flat pattern instead of standing on its own, and a shop-floor
        worker reading the sheet — not an estimator who already knows to
        cross-reference a hole table — needs the two visually apart, each
        headed plainly."""
        html = SF.sheet_svg(self.report)
        self.assertIn("FLAT PATTERN", html)
        self.assertIn("ISOMETRIC", html)
        # The formed 3-view band (FRONT VIEW / TOP VIEW / SIDE VIEW) is now
        # only the fallback for a part that did NOT unfold — every real
        # part on this job did, so none of those headings should appear.
        for heading in ("FRONT VIEW", "TOP VIEW", "SIDE VIEW"):
            self.assertNotIn(heading, html)

    def test_every_hole_diameter_is_labelled_on_the_drawing_itself(self):
        """Not only in a side table — the owner's own words: 'even the
        radius and diameters are marked inside the diagram itself.'"""
        html = SF.sheet_svg(self.report)
        for name, part in self.by_name.items():
            for dia in {h["dia_mm"] for h in (part["flat"] or {}).get("holes", ())}:
                self.assertIn(f"Ø{dia:g}", html, (name, dia))

    def test_hole_positions_are_dimensioned_not_only_shown_to_scale(self):
        """A real, non-zero position figure for at least one hole on each
        part — not just its outline drawn to scale."""
        html = SF.sheet_svg(self.report)
        for name, part in self.by_name.items():
            flat = part["flat"]
            if not flat or not flat["holes"]:
                continue
            some_x = f"{flat['holes'][0]['x']:.1f}"
            self.assertTrue(some_x in html or
                            any(f"{h['x']:.1f}" in html for h in flat["holes"]),
                            name)

    def test_positions_are_dimensioned_as_gaps_not_datum_distances(self):
        """The owner's own words: 'I don't see any measurements' — meaning
        Prism drew each hole's bare distance from an edge, so reading the
        distance BETWEEN two holes meant subtracting two numbers by hand.
        A chain draws that gap directly, the way the reference sheet
        does. Checked the honest way: rebuild the same chain the drawing
        function does, off the same measured positions, and confirm
        those exact gap figures — not the raw positions — are what is on
        the page."""
        html = SF.sheet_svg(self.report)
        found_a_chain = False
        for name, part in self.by_name.items():
            flat = part["flat"]
            if not flat or not flat["holes"]:
                continue
            for axis, span in (("x", flat["flat_size_mm"][0]),
                               ("y", flat["flat_size_mm"][1])):
                pts = SF._cluster([h[axis] for h in flat["holes"]])
                chain = SF._chain_points(pts, span, min_gap=1.0)
                if not chain or len(chain) < 2:
                    continue
                gaps = [round(b - a, 2) for a, b in zip(chain, chain[1:])]
                # At least one real (non-edge, non-total) gap actually
                # printed on the page — proves it is drawing the chain,
                # not just the overall span it already drew before this.
                interior = [g for g in gaps if g not in
                           (span, round(flat["flat_size_mm"][0], 2),
                            round(flat["flat_size_mm"][1], 2))]
                if any(f"{g:.2f}" in html for g in interior):
                    found_a_chain = True
        self.assertTrue(found_a_chain,
                        "no chain-dimension gap value found anywhere on "
                        "the sheet")

    def test_a_chain_always_sums_to_the_full_span(self):
        """Regression: an earlier version could drop the FAR edge itself
        during thinning when the nearest real feature sat within
        tolerance of it — the chain fell 2 mm short of a real part's own
        measured height without saying so. Both ends must always survive."""
        for part in self.by_name.values():
            flat = part["flat"]
            if not flat:
                continue
            for axis, span in (("x", flat["flat_size_mm"][0]),
                               ("y", flat["flat_size_mm"][1])):
                pts = SF._cluster([h[axis] for h in flat["holes"]])
                chain = SF._chain_points(pts, span, min_gap=1.0)
                if not chain:
                    continue
                self.assertAlmostEqual(chain[0], 0.0, places=2)
                self.assertAlmostEqual(chain[-1], span, places=2)
                self.assertAlmostEqual(sum(b - a for a, b in
                                           zip(chain, chain[1:])), span, places=2)

    def test_the_vent_row_did_not_need_the_fallback_on_this_real_job(self):
        """The top part's vent-slot row (eighteen Ø3 holes a few mm apart)
        is exactly the shape of data _chain_points' own fallback exists
        for — but on THIS job the same small scale the tall Y span forces
        also collapses the vent row down to two clean segments, so the
        fallback is never actually reached here. That is a real
        assertion worth pinning, not just an absence: the drawing shows
        real numbers for this row, not a shrug. The fallback path itself
        is covered directly, on synthetic data, in
        TheDimensionChainAlwaysReachesBothEdges — that is the right place
        to prove it works, since it does not fire on this particular
        job's own numbers."""
        html = SF.sheet_svg(self.report)
        top = self.by_name["top"]["flat"]
        fw = top["flat_size_mm"][0]
        self.assertIn("45.00", html)          # 0 -> 45, the first stop
        self.assertIn(f"{fw - 45.0:.2f}", html)  # 45 -> the far edge
        self.assertNotIn("too closely packed", html)

    def test_the_excel_sheet_carries_the_flat_size(self):
        import openpyxl
        out = os.path.join(tempfile.mkdtemp(), "dimensions.xlsx")
        SF.write_xlsx(self.report, out)
        wb = openpyxl.load_workbook(out)
        # Row 1 is the title, row 2 blank, row 3 the header — see write_xlsx.
        header = [c.value for c in wb["Parts"][3]]
        self.assertIn("Flat L (mm)", header)
        self.assertIn("Flat W (mm)", header)

    def test_nothing_is_actually_missing_on_this_real_job(self):
        """A hand-drawn fabricator reference for this exact job showed a
        stepped/notched corner on the 'side' part that looked, at first
        glance, absent from Prism's flat pattern — and the old disclosure
        ("N of 28 faces unfolded — small features ... not shown") read
        like confirmation something real was missing. Checked directly
        against the geometry: it was not. The step is already in the
        placed panel's own outline; every face the bend graph could not
        reach is either that panel's untouched back face or a sliver of
        the sheet's own edge thickness, neither of which is a feature
        left off the drawing. Pinned on all three real parts so a future
        change to the bend graph cannot quietly start hiding real
        geometry again without this test noticing."""
        for name in ("top", "bottom", "side"):
            flat = self.by_name[name]["flat"]
            self.assertEqual(flat["faces_hidden_meaningful"], 0, name)
        self.assertNotIn("could not be unfolded", SF.sheet_svg(self.report))

    def test_the_panels_own_outline_joins_the_dimension_chain(self):
        """Position dimensioning used to read only hole positions — a
        panel's own step or notch was drawn (it is part of the outline)
        but never numbered. The real 'bottom' panel's 46mm square window
        is cut into the outline as its own shape; its edges are genuine
        chain stops a holes-only chain never saw."""
        flat = self.by_name["bottom"]["flat"]
        holes_only_x = SF._cluster([h["x"] for h in flat["holes"]])
        outline_x = [x for poly in flat["panels"] for x, _y in poly]
        combined_x = SF._cluster([h["x"] for h in flat["holes"]] + outline_x)
        self.assertGreater(len(combined_x), len(holes_only_x))

    def test_no_two_red_callouts_overlap_on_a_real_generated_job(self):
        """A real Prism-generated run of this exact job had a hole's Ø, a
        cutout's size and a SECOND cutout's size all land on the same
        few pixels on 'top', and separately a cutout's size land on top
        of a different nearby hole's own drawn circle on 'bottom' —
        illegible, and the actual bug report that led to leader lines
        (_place_label). Checked here the way it was actually found: by
        collecting every red callout _draw_flat_pattern put on the page
        and asking whether any two (or a label and a drawn shape) share
        ground, not by eyeballing a render."""
        for name in ("top", "bottom", "side"):
            part = self.by_name[name]
            sh = SF._Canvas()
            SF._draw_flat_pattern(sh, 1, part, None, with_isometric=False)
            labels, shapes = [], []
            for op in sh._ops:
                if op[0] == "text" and op[7] == "#a33":
                    _, x, y, text, size, anchor, _bold, _fill, _rot = op
                    labels.append(SF._label_box(x, y, text, size, anchor))
                elif op[0] == "circle":
                    _, cx, cy, r, *_ = op
                    shapes.append((cx - r, cy - r, cx + r, cy + r))
            # A label must not sit on another label, nor on a drawn
            # shape (a hole's own circle). Two real holes' circles
            # overlapping each other, if the model genuinely has them
            # that close, is real geometry -- not this test's business.
            for i, a in enumerate(labels):
                for b in labels[i + 1:] + shapes:
                    self.assertFalse(SF._boxes_overlap(a, b, pad=0),
                                     (name, a, b))


class BendAllowanceIsTheNeutralAxisNotEitherRadius(unittest.TestCase):
    """A pure arithmetic check, no geometry -- the one formula every flat
    size in this file depends on."""

    def test_a_ninety_degree_bend(self):
        import math
        got = SF._bend_allowance(radius_mm=2.0, angle_rad=math.pi / 2,
                                 thickness_mm=1.0, k_factor=0.4133)
        expected = (math.pi / 2) * (2.0 + 0.4133 * 1.0)
        self.assertAlmostEqual(got, expected, places=6)

    def test_zero_radius_is_just_k_times_thickness_times_angle(self):
        import math
        got = SF._bend_allowance(radius_mm=0.0, angle_rad=math.pi / 2,
                                 thickness_mm=2.0, k_factor=0.4133)
        self.assertAlmostEqual(got, (math.pi / 2) * 0.4133 * 2.0, places=6)

    def test_a_bigger_k_factor_is_strictly_more_allowance(self):
        import math
        small = SF._bend_allowance(2.0, math.pi / 2, 1.0, 0.2)
        big = SF._bend_allowance(2.0, math.pi / 2, 1.0, 0.45)
        self.assertGreater(big, small)


class ClusteringHolePositionsForTheDrawing(unittest.TestCase):
    """_cluster is what keeps a ventilation grille's dozen slot positions
    from printing as one unreadable smear of digits on the flat pattern —
    see _draw_flat_pattern's own note on why two stagger rows were not
    enough on a real job."""

    def test_identical_positions_collapse_to_one(self):
        self.assertEqual(SF._cluster([10.0, 10.0, 10.0]), [10.0])

    def test_positions_a_millimetre_apart_merge_by_default(self):
        self.assertEqual(SF._cluster([10.0, 10.4, 10.9]), [10.0])

    def test_positions_well_apart_all_survive(self):
        self.assertEqual(SF._cluster([0.0, 20.0, 40.0]), [0.0, 20.0, 40.0])

    def test_a_wider_tolerance_merges_more(self):
        tight = SF._cluster([0.0, 5.0, 10.0], tol=1.0)
        wide = SF._cluster([0.0, 5.0, 10.0], tol=6.0)
        self.assertGreater(len(tight), len(wide))

    def test_empty_in_is_empty_out(self):
        self.assertEqual(SF._cluster([]), [])


class TheDimensionChainAlwaysReachesBothEdges(unittest.TestCase):
    """_chain_points builds the stops a position CHAIN runs between —
    0, every real feature, and the far edge — the way the reference
    sheet's own "26.5 / 90.5 / 50 / 3.5" reads: gaps between things, not
    each thing's bare distance from a datum a reader has to subtract by
    hand. The one rule that must never break: both ends of the chain are
    always in it, however close a real feature sits to either one."""

    def test_a_lone_feature_gives_two_segments(self):
        self.assertEqual(SF._chain_points([50.0], 100.0), [0.0, 50.0, 100.0])

    def test_no_features_is_still_one_span_edge_to_edge(self):
        self.assertEqual(SF._chain_points([], 100.0), [0.0, 100.0])

    def test_a_feature_against_the_start_edge_does_not_drop_the_edge(self):
        chain = SF._chain_points([0.3], 100.0, min_gap=1.0)
        self.assertAlmostEqual(chain[0], 0.0, places=2)

    def test_a_feature_against_the_far_edge_does_not_drop_the_edge(self):
        """The actual regression: the chain used to fall short of the
        part's own measured span when the last real feature sat within
        tolerance of the far edge — it silently dropped the edge instead
        of the near-duplicate feature."""
        chain = SF._chain_points([99.7], 100.0, min_gap=1.0)
        self.assertAlmostEqual(chain[-1], 100.0, places=2)
        self.assertEqual(sum(b - a for a, b in zip(chain, chain[1:])), 100.0)

    def test_gaps_sum_to_the_full_span_regardless_of_how_many_features(self):
        chain = SF._chain_points([10.0, 22.0, 22.4, 71.0], 100.0, min_gap=1.0)
        self.assertAlmostEqual(sum(b - a for a, b in zip(chain, chain[1:])),
                               100.0, places=2)

    def test_too_many_stops_gives_up_cleanly_instead_of_overlapping(self):
        """Round 44's actual bug: eighteen close-together vent-hole
        positions chained anyway and printed as an unreadable smear.
        Past the cap, this returns None so the caller can fall back to
        showing the feature to scale instead of forcing a label onto it."""
        dense = [float(i) for i in range(1, 30)]
        self.assertIsNone(SF._chain_points(dense, 100.0, min_gap=1.0))

    def test_a_reasonable_number_of_stops_is_not_dropped(self):
        few = [10.0, 30.0, 50.0, 70.0]
        self.assertIsNotNone(SF._chain_points(few, 100.0, min_gap=1.0))


class ThePlanIsValidatedNotTrusted(unittest.TestCase):
    """/step-ask: whatever the agent answers, only the two executable ops
    survive, and only with sane numbers."""

    def test_a_fenced_json_plan_parses(self):
        plan, _ = SF.parse_plan([
            'Here you go:\n```json\n{"changes": [{"op": "enlarge_hole", '
            '"part": "top", "dia_mm": 5, "new_dia_mm": 6.5, "why": "M6"}], '
            '"advice": ["add draft"]}\n```'])
        self.assertEqual(plan["changes"], [
            {"op": "enlarge_hole", "part": "top", "dia_mm": 5.0,
             "new_dia_mm": 6.5, "hole": "", "why": "M6"}])
        self.assertEqual(plan["advice"], ["add draft"])

    def test_a_shrink_or_unknown_op_is_dropped(self):
        plan, _ = SF.parse_plan([
            '{"changes": [{"op": "enlarge_hole", "part": "x", "dia_mm": 6, '
            '"new_dia_mm": 5}, {"op": "delete_part", "part": "x"}, '
            '{"op": "scale", "part": "x", "factor": 99}], "advice": []}'])
        self.assertEqual(plan["changes"], [])

    def test_garbage_returns_none_with_a_sentence(self):
        plan, why = SF.parse_plan(["no json here", ""])
        self.assertIsNone(plan)
        self.assertIn("no JSON plan", why)

    def test_the_newest_capture_wins(self):
        older = '{"changes": [], "advice": ["old"]}'
        newer = '{"changes": [], "advice": ["new"]}'
        plan, _ = SF.parse_plan([older, newer])
        self.assertEqual(plan["advice"], ["new"])


@unittest.skipUnless(HAVE, "cadquery not installed")
class ThePromptsCarryNumbersNotTheModel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "block.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="plastic")

    def test_the_model_hears_the_figures_and_the_confidentiality(self):
        p = SF.ask_prompt(self.report, "make it lighter")
        self.assertIn("60.00 x 40.00 x 8.00", p)
        self.assertIn("make it lighter", p)
        self.assertIn("cannot be shown to you", p)

    def test_the_prompt_names_the_hole_not_just_its_size(self):
        """Reported 2026-11-05: Ask said "19 holes" and, asked to name
        them, could not — because the text it was given only ever had
        "Ø19.0 x 1", nothing a model could point at. Every hole now has
        its own tag and position in the prompt itself."""
        p = SF.ask_prompt(self.report, "which hole is this?")
        self.assertIn("H1", p)
        self.assertIn("Ø5", p)
        self.assertIn("use the tag", p)

    def test_a_factual_question_is_told_to_stay_short(self):
        """Reported live, 2026-11-06: asked plainly "how many holes are
        there", Haiku correctly named all 23 tags, then ALSO produced an
        unasked-for Makeability / Cost drivers / Changes report, because
        the old prompt demanded that structure unconditionally. The
        prompt itself must now draw the line between a factual question
        (short) and an open-ended one (the fuller write-up)."""
        p = SF.ask_prompt(self.report, "how many holes are there?")
        self.assertIn("FACTUAL", p)
        self.assertIn("OPEN-ENDED", p)
        self.assertIn("ONE or TWO plain sentences", p)
        self.assertIn("do not pad a simple question with a full report", p)

    def test_the_planner_gets_the_schema_and_the_honest_out(self):
        p = SF.plan_prompt(self.report, "q", "advice text")
        self.assertIn('"enlarge_hole"', p)
        self.assertIn('"scale"', p)
        self.assertIn('"hole"', p)
        self.assertIn("never shrunk", p)
        self.assertIn("empty changes list", p)


@unittest.skipUnless(HAVE, "cadquery not installed")
class ChangesLandOnACopy(unittest.TestCase):
    """apply_plan edits real geometry and the re-measure proves it."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.path = os.path.join(cls.dir, "block.step")
        _box_with_hole(cls.path)

    def test_a_hole_is_enlarged_and_nothing_else_moves(self):
        out = os.path.join(self.dir, "bigger.step")
        done = SF.apply_plan(self.path, {"changes": [
            {"op": "enlarge_hole", "part": "all", "dia_mm": 5.0,
             "new_dia_mm": 6.0, "why": ""}], "advice": []}, out)
        self.assertTrue(any("1 hole(s) enlarged" in l for l in done["log"]))
        part = SF.analyse(out, mode="plastic")["parts"][0]
        self.assertEqual(part["size_mm"], (60.0, 40.0, 8.0))
        self.assertEqual(part["holes"], [{"dia_mm": 6.0, "count": 1}])

    def test_a_planner_added_suffix_on_the_part_name_still_matches(self):
        """Round: a reviewing agent wrote "part": "<real name> — 1 NOS"
        (a quantity annotation it invented, never asked for) instead of
        the measured name verbatim. Exact matching found no part at all —
        predicted_parts() silently showed no change, and apply_plan(),
        with nothing else in the plan, raised "Nothing in the plan could
        be applied" — a real, reviewed, correct-looking plan that could
        never actually reach the file. The real name is accepted as a
        case-insensitive PREFIX of whatever the plan wrote instead."""
        block_name = SF.load_parts(self.path)[0][0]
        out = os.path.join(self.dir, "bigger2.step")
        plan = {"changes": [
            {"op": "enlarge_hole", "part": f"{block_name} — 1 NOS",
             "dia_mm": 5.0, "new_dia_mm": 6.0, "why": ""}], "advice": []}
        done = SF.apply_plan(self.path, plan, out)
        self.assertTrue(any("1 hole(s) enlarged" in l for l in done["log"]),
                        done["log"])
        part = SF.analyse(out, mode="plastic")["parts"][0]
        self.assertEqual(part["holes"], [{"dia_mm": 6.0, "count": 1}])

        report = SF.analyse(self.path, mode="plastic")
        pred = SF.predicted_parts(report, plan)
        self.assertEqual(pred[0]["holes"], [{"dia_mm": 6.0, "count": 1}],
                         "the review page's predicted column must show "
                         "the same change the real build applies")

    def test_a_scaled_part_keeps_its_holes_as_holes(self):
        out = os.path.join(self.dir, "scaled.step")
        SF.apply_plan(self.path, {"changes": [
            {"op": "scale", "part": "all", "factor": 1.5, "why": ""}],
            "advice": []}, out)
        part = SF.analyse(out, mode="plastic")["parts"][0]
        self.assertEqual(part["size_mm"], (90.0, 60.0, 12.0))
        self.assertEqual(part["holes"], [{"dia_mm": 7.5, "count": 1}])

    def test_the_original_file_is_untouched(self):
        before = open(self.path, "rb").read()
        SF.apply_plan(self.path, {"changes": [
            {"op": "scale", "part": "all", "factor": 2, "why": ""}],
            "advice": []}, os.path.join(self.dir, "x.step"))
        self.assertEqual(open(self.path, "rb").read(), before)

    def test_a_plan_that_lands_nowhere_refuses_to_write(self):
        out = os.path.join(self.dir, "never.step")
        with self.assertRaises(SF.StepError):
            SF.apply_plan(self.path, {"changes": [
                {"op": "enlarge_hole", "part": "no-such-part",
                 "dia_mm": 5.0, "new_dia_mm": 6.0, "why": ""}],
                "advice": []}, out)
        self.assertFalse(os.path.exists(out))


class TheReviewPageComesBeforeTheBuild(unittest.TestCase):
    """The user confirms against a page they can see — a table of every
    dimension before → after and the drawing — and only then is
    modified.step written."""

    PLAN = {"changes": [{"op": "enlarge_hole", "part": "p", "dia_mm": 5.0,
                         "new_dia_mm": 6.0, "why": "fitting"}],
            "advice": ["add draft"]}
    REPORT = {"file": "x.step", "mode": "plastic",
              "overall_mm": (60.0, 40.0, 8.0),
              "parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                         "thickness_mm": 6.0, "volume_cm3": 38.0,
                         "holes": [{"dia_mm": 5.0, "count": 1},
                                   {"dia_mm": 6.0, "count": 1}]}],
              "warnings": []}

    def test_prediction_merges_an_enlarged_hole_into_its_new_group(self):
        parts = SF.predicted_parts(self.REPORT, self.PLAN)
        self.assertEqual(parts[0]["holes"], [{"dia_mm": 6.0, "count": 2}])
        self.assertEqual(parts[0]["size_mm"], (60.0, 40.0, 8.0))

    def test_prediction_scales_every_figure(self):
        parts = SF.predicted_parts(self.REPORT, {"changes": [
            {"op": "scale", "part": "all", "factor": 2.0, "why": ""}],
            "advice": []})
        self.assertEqual(parts[0]["size_mm"], (120.0, 80.0, 16.0))
        self.assertEqual(parts[0]["holes"][0], {"dia_mm": 10.0, "count": 1})

    def test_the_page_says_nothing_is_built_yet(self):
        out = tempfile.mkdtemp()
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   question="fit 6mm"),
                    encoding="utf-8").read()
        self.assertIn("Nothing is built yet", page)
        self.assertIn("Hole Ø5 → Ø6", page)
        self.assertIn("60.00 x 40.00 x 8.00", page)
        self.assertIn("class='changed'", page)
        self.assertIn("add draft", page)
        self.assertIn("fit 6mm", page)

    def test_after_the_build_the_page_says_re_measured(self):
        out = tempfile.mkdtemp()
        after = {"parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                            "thickness_mm": 5.9, "volume_cm3": 37.5,
                            "holes": [{"dia_mm": 6.0, "count": 2}]}]}
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   after=after), encoding="utf-8").read()
        self.assertIn("BUILT", page)
        self.assertIn("re-measured", page)
        self.assertNotIn("Nothing is built yet", page)

    def test_after_the_build_both_drawings_are_on_the_page(self):
        out = tempfile.mkdtemp()
        names = SF.names(self.REPORT)
        for name in (names["png"], names["png_after"]):
            open(os.path.join(out, name), "wb").write(b"png")
        after = {"parts": [{"name": "p", "size_mm": (60.0, 40.0, 8.0),
                            "thickness_mm": 5.9, "volume_cm3": 37.5,
                            "holes": [{"dia_mm": 6.0, "count": 2}]}]}
        page = open(SF.review_html(self.REPORT, self.PLAN, out,
                                   after=after), encoding="utf-8").read()
        # URL-quoted in the src attribute — the name carries spaces.
        self.assertIn("x%20-%20drawing%20sheet%20after%20change.png", page)
        self.assertIn("from the BUILT file", page)

    def test_before_the_build_only_the_received_drawing_shows(self):
        out = tempfile.mkdtemp()
        names = SF.names(self.REPORT)
        for name in (names["png"], names["png_after"]):
            open(os.path.join(out, name), "wb").write(b"png")
        page = open(SF.review_html(self.REPORT, self.PLAN, out),
                    encoding="utf-8").read()
        self.assertNotIn("after%20change.png", page)
        self.assertIn("x%20-%20drawing%20sheet.png", page)


    def test_the_terminal_builds_only_after_the_page_and_the_yes(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        body = src[src.index("def cmd_step_ask("):src.index("def cmd_gerber(")]
        self.assertLess(body.index("review_html"),
                        body.index("Reviewed the page — build"))
        self.assertLess(body.index("Reviewed the page — build"),
                        body.index("apply_plan"))


@unittest.skipUnless(HAVE and os.path.exists(REAL),
                     "cadquery missing, or " + (sample_jobs.missing(
                         "step_file_demo", "Assem1.STEP") or ""))
class ChangesOnTheCustomersEnclosure(unittest.TestCase):
    """Witnessed on the real assembly: one hole grows, names and every
    other figure hold still."""

    def test_only_the_named_hole_on_the_named_part_changes(self):
        out = os.path.join(tempfile.mkdtemp(), "m.step")
        SF.apply_plan(REAL, {"changes": [
            {"op": "enlarge_hole", "part": "top", "dia_mm": 6.2,
             "new_dia_mm": 8.0, "why": ""}], "advice": []}, out)
        by = {p["name"]: p for p in SF.analyse(out, "metal")["parts"]}
        self.assertEqual(set(by), {"top", "bottom", "side"})
        top = {h["dia_mm"] for h in by["top"]["holes"]}
        self.assertIn(8.0, top)
        self.assertNotIn(6.2, top)
        self.assertEqual(by["top"]["size_mm"], (101.0, 93.0, 71.0))
        self.assertEqual(by["side"]["size_mm"], (92.0, 68.5, 6.0))
        self.assertIn(5.2, {h["dia_mm"] for h in by["bottom"]["holes"]})


class TheTerminalDoor(unittest.TestCase):

    def test_step_and_s_reach_the_command(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertIn("def cmd_step(", src)
        self.assertIn('line.startswith("/step")', src)
        self.assertIn('line == "/s" or line.startswith("/s ")', src)
        self.assertIn("no AI sees the STEP file", src)

    def test_the_mode_words_are_metal_and_plastic(self):
        self.assertEqual(SF.MODES, ("metal", "plastic"))

    def test_step_auto_is_dispatched_before_step(self):
        """startswith("/step") would swallow "/step-auto" — the auto branch
        must be checked first or the command silently runs plain /step."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertIn("def cmd_step_auto(", src)
        self.assertLess(src.index('line.startswith("/step-auto")'),
                        src.index('line.startswith("/step") or'))

    def test_step_auto_never_uploads_the_model(self):
        """The only attachment /step-auto builds is Prism's OWN render; the
        customer's STEP file must never be in the file list."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        body = src[src.index("def cmd_step_auto("):
                   src.index("def cmd_step_ask(")]
        self.assertIn('F.attach(drawn["png"])', body)
        self.assertNotIn("F.attach(target", body)
        self.assertIn("STEP file stays here", body)

    def test_step_ask_is_dispatched_and_never_uploads_the_model(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        self.assertLess(src.index('line.startswith("/step-ask")'),
                        src.index('line.startswith("/step") or'))
        body = src[src.index("def cmd_step_ask("):
                   src.index("def cmd_gerber(")]
        self.assertNotIn("F.attach(target", body)
        self.assertIn('F.attach(drawn["png"])', body)
        self.assertIn("groq_chat", body)
        # The file actually written is named by modified_name() (stamped
        # with when it was built), not the flat names()['modified'] base —
        # see core.stepfile.modified_name's own docstring for why. The
        # un-stamped base is still the right thing for the pre-build
        # "about to write X" prompt, which this still checks for.
        self.assertIn("SF.modified_name(report)", body)
        self.assertIn("build {out['modified']} now?", body)


class EveryFileCarriesTheModelsName(unittest.TestCase):
    """An estimator keeps ten jobs' sheets in one folder, and ten files all
    called dimensions.xlsx are ten files nobody can tell apart. Every
    deliverable now starts with the customer's own file name, and where the
    folders go is the person's choice (the GUI asks; the terminal has
    /step-folder). Pure functions — no cadquery needed."""

    def test_the_stem_is_the_customers_own_name(self):
        self.assertEqual(SF.stem_of("~/Downloads/Assem1.STEP"), "Assem1")
        self.assertEqual(SF.stem_of("housing v2.stp"), "housing v2")

    def test_the_stem_is_safe_on_windows_and_never_empty(self):
        self.assertEqual(SF.stem_of('bad:name?<x>.stp'), "badnamex")
        self.assertEqual(SF.stem_of(""), "model")
        self.assertEqual(SF.stem_of("?.stp"), "model")   # nothing legal left
        self.assertLessEqual(len(SF.stem_of("x" * 200 + ".step")), 60)

    def test_every_deliverable_starts_with_the_stem(self):
        out = SF.names("Assem1")
        for key, name in out.items():
            self.assertTrue(name.startswith("Assem1 - "), (key, name))
        self.assertEqual(out["xlsx"], "Assem1 - dimensions.xlsx")
        self.assertEqual(out["modified"], "Assem1 - modified.step")
        self.assertEqual(SF.flat_image_name("Assem1", "top", 1),
                         "Assem1 - top - flat pattern.png")
        self.assertEqual(SF.ai_sheet_name("Assem1", 1, ".png"),
                         "Assem1 - AI drawing sheet 1.png")

    def test_the_built_files_real_name_is_stamped_not_flat(self):
        """Round: every Edit of the same model writes its own numbered
        sibling folder (output_dir()), but inside it the file was always
        literally "<stem> - modified.step" — identical on every build, so
        two different requests' results were indistinguishable by name,
        both inside and especially once moved out of their folder. The
        stamp is what names()['modified'] (still flat, still used for the
        pre-build "about to write X" message) deliberately does not
        carry — it is called more than once per build and would disagree
        with itself if it read the clock."""
        a = SF.modified_name("Assem1")
        self.assertTrue(a.startswith("Assem1 - modified "))
        self.assertTrue(a.endswith(".step"))
        self.assertNotEqual(a, SF.names("Assem1")["modified"])

    def test_two_builds_a_second_apart_get_different_names(self):
        import datetime
        from unittest import mock
        with mock.patch.object(SF, "_dt") as dt_mod:
            dt_mod.datetime.now.return_value = datetime.datetime(
                2026, 10, 14, 6, 35, 1)
            first = SF.modified_name("Assem1")
            dt_mod.datetime.now.return_value = datetime.datetime(
                2026, 10, 14, 6, 35, 2)
            second = SF.modified_name("Assem1")
        self.assertNotEqual(first, second)

    def test_names_read_the_stem_off_a_report(self):
        report = {"file": "Assem1.STEP", "stem": "Assem1"}
        self.assertEqual(SF.names(report)["png"], "Assem1 - drawing sheet.png")
        # An older report without a stem still names correctly.
        self.assertEqual(SF.names({"file": "x.step"})["review"],
                         "x - change review.html")

    def test_the_folder_is_named_after_the_model_under_the_chosen_root(self):
        root = tempfile.mkdtemp()
        got = SF.output_dir("/anywhere/Assem1.STEP", root)
        self.assertEqual(got, os.path.join(root, "Assem1"))
        self.assertFalse(os.path.exists(got))    # writers create it

    def test_a_second_run_never_overwrites_the_first(self):
        root = tempfile.mkdtemp()
        first = SF.output_dir("/anywhere/Assem1.STEP", root)
        os.makedirs(first)
        self.assertEqual(SF.output_dir("/anywhere/Assem1.STEP", root), first,
                         "an empty folder is reused, not numbered")
        open(os.path.join(first, "Assem1 - dimensions.xlsx"), "w").close()
        second = SF.output_dir("/anywhere/Assem1.STEP", root)
        self.assertEqual(second, os.path.join(root, "Assem1 (2)"))
        os.makedirs(second)
        open(os.path.join(second, "f"), "w").close()
        self.assertEqual(SF.output_dir("/anywhere/Assem1.STEP", root),
                         os.path.join(root, "Assem1 (3)"))

    def test_no_root_means_the_desktop_folder(self):
        got = SF.output_dir("/anywhere/Assem1.STEP", "")
        self.assertEqual(os.path.dirname(got), SF.DEFAULT_OUT_ROOT)
        self.assertTrue(SF.DEFAULT_OUT_ROOT.endswith("Prism Step"))

    def test_the_review_page_names_the_modified_file(self):
        report = dict(TheReviewPageComesBeforeTheBuild.REPORT, stem="x")
        out = tempfile.mkdtemp()
        path = SF.review_html(report, TheReviewPageComesBeforeTheBuild.PLAN,
                              out, question="q")
        self.assertEqual(os.path.basename(path), "x - change review.html")
        self.assertIn("x - modified.step", open(path, encoding="utf-8").read())

    def test_the_terminal_uses_the_shared_names_and_the_chosen_root(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        src = open(os.path.join(root, "prism_terminal", "prism.py"),
                   encoding="utf-8").read()
        measured = src[src.index("def _step_measured("):src.index("def cmd_step(")]
        self.assertIn('SF.output_dir(target, cfg.get("step_out_dir"', measured)
        self.assertIn('SF.names(report)["xlsx"]', measured)
        self.assertNotIn('"dimensions.xlsx"', src)
        self.assertNotIn('"drawing_after.png"', src)
        self.assertNotIn('"modified.step"', src)
        # /step-folder must be dispatched before the /step prefix swallows it.
        self.assertIn("def cmd_step_folder(", src)
        self.assertLess(src.index('line.startswith("/step-folder")'),
                        src.index('line.startswith("/step") or'))

    def test_the_config_knows_the_key(self):
        from core import config as C
        self.assertIn("step_out_dir", C.DEFAULT)
        self.assertEqual(C.DEFAULT["step_out_dir"], "")


@unittest.skipUnless(HAVE, "cadquery not installed")
class TheSheetIsDrawnByPrismNotAnAI(unittest.TestCase):
    """The dimensioned drawing sheet — three orthographic views per part
    with the sizes on dimension lines, a hole table, notes and a title
    block — comes out of the geometry itself, in a second, with no image
    model in the loop. Checked on a box whose every figure is known."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(tempfile.mkdtemp(), "Bracket A.step")
        _box_with_hole(cls.path)
        cls.report = SF.analyse(cls.path, mode="metal")
        cls.shape = cls.report["_shapes"][0][1]
        cls.svg = SF.sheet_svg(cls.report)

    def test_the_three_views_project_the_right_extents(self):
        """Front sees X by Z, top sees X by Y, side sees Y by Z — the box is
        60 x 40 x 8, so the projections must measure exactly that."""
        want = {"FRONT VIEW": (60, 8), "TOP VIEW": (60, 40),
                "SIDE VIEW": (40, 8)}
        for title, n, xdir, _axes in SF._VIEWS:
            proj = SF._project(self.shape, n, xdir)
            self.assertIsNotNone(proj, title)
            xmin, xmax, ymin, ymax = proj["bb"]
            self.assertAlmostEqual(xmax - xmin, want[title][0], places=2, msg=title)
            self.assertAlmostEqual(ymax - ymin, want[title][1], places=2, msg=title)
            self.assertTrue(proj["visible"], title)

    def test_the_hole_shows_up_as_hidden_lines_in_the_side_view(self):
        """Looking from the side, a through hole is inside the material —
        hidden-line removal must draw it dashed, not drop it."""
        proj = SF._project(self.shape, (1, 0, 0), (0, 1, 0))
        self.assertTrue(proj["hidden"])

    def test_every_view_is_titled_and_dimensioned_in_mm(self):
        for title in ("FRONT VIEW", "TOP VIEW", "SIDE VIEW"):
            self.assertIn(title, self.svg)
        for figure in ("60.00", "40.00", "8.00"):
            self.assertIn(f">{figure}<", self.svg)
        self.assertIn("millimetres (mm)", self.svg)

    def test_the_hole_table_notes_and_title_block_are_there(self):
        self.assertIn("HOLES (", self.svg)
        self.assertIn("H1  Ø5", self.svg)
        self.assertIn("NOTES:", self.svg)
        self.assertIn("JOB NAME:", self.svg)
        self.assertIn("Bracket A.step", self.svg)
        self.assertIn("DRAWN BY:", self.svg)
        self.assertIn("Measured offline by Prism", self.svg)
        self.assertIn("CRC SHEET", self.svg)

    def test_every_figure_on_the_sheet_is_two_decimals(self):
        for number in re.findall(r"\d+\.(\d+)<", self.svg):
            self.assertLessEqual(len(number), 2)

    def test_the_sheet_lands_under_the_models_name(self):
        out = tempfile.mkdtemp()
        drawn = SF.render_sheet(self.report, out)
        self.assertEqual(os.path.basename(drawn["png"]),
                         "Bracket A - drawing sheet.png")
        self.assertTrue(os.path.exists(drawn["png"]))
        # A plain box has no bend, so no part of it has a flat pattern —
        # no flat-only image for a part that has none.
        self.assertEqual(drawn["flats"], {})

    def test_a_part_with_no_geometry_still_gets_a_line(self):
        report = dict(self.report, _shapes=[])
        svg = SF.sheet_svg(report)
        self.assertIn("no geometry to draw", svg)
        self.assertIn("JOB NAME:", svg)

    def test_a_narrow_dimension_puts_its_figure_outside_the_arrows(self):
        sh = SF._Sheet()
        sh.dim_h(100, 110, 50, 6.0)          # 10px wide: the figure won't fit
        narrow = "".join(sh.items)
        self.assertIn(">6.00<", narrow)
        self.assertIn('x="132.0"', narrow)   # beside, not between
        sh = SF._Sheet()
        sh.dim_h(100, 300, 50, 60.0)         # 200px: the figure sits above
        self.assertIn('x="200.0"', "".join(sh.items))


class TheImageStageGetsItsBudget(unittest.TestCase):
    """The AI-drawn sheet was coming back as a blurred preview: a generic
    visual turn waits 60s and gives up after 12s if no picture has shown,
    while ChatGPT's image model takes minutes and previews progressively.
    Both surfaces now tell the engine a picture IS the deliverable."""

    def _src(self, *parts):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return open(os.path.join(root, *parts), encoding="utf-8").read()

    def test_the_terminal_promises_a_picture(self):
        src = self._src("prism_terminal", "prism.py")
        body = src[src.index("def cmd_step_auto("):src.index("def cmd_step_ask(")]
        self.assertIn('image_stages={"visual"}', body)

    def test_the_terminal_draws_with_chatgpt_only_and_never_falls_over(self):
        src = self._src("prism_terminal", "prism.py")
        body = src[src.index("def cmd_step_auto("):src.index("def cmd_step_ask(")]
        self.assertIn('artist = "ChatGPT"', body)
        self.assertIn("failover=False", body)
        self.assertNotIn('agents.get("visual")', body)

    def test_the_engine_gives_a_promised_stage_minutes_not_seconds(self):
        src = self._src("prism_terminal", "core", "automation.py")
        self.assertIn("image_stages=None", src)
        block = src[src.index("elif stage in promised:"):]
        block = block[:block.index("else:")]
        cap = int(re.search(r"want, cap, grace = 1, (\d+), None", block).group(1))
        self.assertGreaterEqual(cap, 300)

    def test_a_preview_that_changes_is_not_finished(self):
        """The wait watches the images' sources and sizes, and the page's
        own 'creating image' text — not just how many images there are."""
        src = self._src("prism_terminal", "core", "automation.py")
        body = src[src.index("def _wait_for_images("):src.index("def _wait_for_files(")]
        self.assertIn("sig != last_sig", body)
        self.assertIn("creating image", body)
        self.assertIn("not busy", body)


class TheMaterialMouldCatalogIsPlainArithmeticNotAI(unittest.TestCase):
    """load_catalog/match_catalog -- a shop's own Sr No sheet (CSV/XLSX),
    read offline and matched against an inquiry's ID/OD by |difference|
    against tolerance. No cadquery needed: this is just a spreadsheet and
    arithmetic, so it runs even where HAVE (cadquery) is False."""

    _CSV = (
        "Sr No,Product ID mm,Product OD mm,ID Tolerance mm,OD Tolerance mm,"
        "Material Sr No,Mould Sr No,Seal Size (IDxODxW),Compound\n"
        "1,12,22,0.15,0.2,MAT-201,MLD-101,12x22x7,NBR\n"
        "2,20,32,0.15,0.2,MAT-202,MLD-103,20x32x7,FKM\n"
    )

    def _csv_path(self, tmp, text: str = "") -> str:
        path = os.path.join(tmp, "catalog.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text or self._CSV)
        return path

    def test_a_real_file_loads_both_rows_with_their_sr_nos(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = SF.load_catalog(self._csv_path(tmp))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].material_sr_no, "MAT-201")
        self.assertEqual(rows[1].mould_sr_no, "MLD-103")

    def test_an_inquiry_inside_tolerance_matches_the_right_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = SF.load_catalog(self._csv_path(tmp))
        match, nearest = SF.match_catalog(rows, 20.05, 31.9)
        self.assertIsNotNone(match)
        self.assertEqual(match.material_sr_no, "MAT-202")
        self.assertEqual(match.mould_sr_no, "MLD-103")
        text = SF.catalog_match_text(20.05, 31.9, match, nearest)
        self.assertIn("MATCH", text)
        self.assertIn("MAT-202", text)
        self.assertIn("MLD-103", text)

    def test_an_inquiry_outside_every_rows_tolerance_is_reported_as_a_miss(self):
        """A close-looking row is never reported as a hit just because it
        is the nearest one -- `nearest` still comes back, flagged as a
        miss to check by hand, not silently promoted to a match."""
        with tempfile.TemporaryDirectory() as tmp:
            rows = SF.load_catalog(self._csv_path(tmp))
        match, nearest = SF.match_catalog(rows, 20.9, 33.0)
        self.assertIsNone(match)
        self.assertIsNotNone(nearest)
        self.assertEqual(nearest.material_sr_no, "MAT-202")
        text = SF.catalog_match_text(20.9, 33.0, match, nearest)
        self.assertIn("no catalog row within tolerance", text)
        self.assertIn("check this one by hand", text)

    def test_a_row_with_no_tolerance_column_falls_back_to_the_default(self):
        csv_text = (
            "Product ID mm,Product OD mm,Material Sr No,Mould Sr No\n"
            "20,32,MAT-202,MLD-103\n")
        with tempfile.TemporaryDirectory() as tmp:
            rows = SF.load_catalog(self._csv_path(tmp, csv_text))
        self.assertAlmostEqual(rows[0].id_tolerance_mm,
                               SF._DEFAULT_CATALOG_TOLERANCE_MM)
        match, _ = SF.match_catalog(rows, 20.2, 32.2)
        self.assertIsNotNone(match)

    def test_a_missing_file_is_a_clear_error_not_a_crash(self):
        with self.assertRaises(SF.CatalogError):
            SF.load_catalog("/no/such/catalog.csv")

    def test_a_file_with_no_id_od_columns_is_a_clear_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._csv_path(tmp, "Name,Price\nWidget,10\n")
            with self.assertRaises(SF.CatalogError):
                SF.load_catalog(path)

    def test_a_file_with_headings_but_no_numeric_rows_is_a_clear_error(self):
        csv_text = ("Product ID mm,Product OD mm,Material Sr No,Mould Sr No\n"
                   "n/a,n/a,MAT-201,MLD-101\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = self._csv_path(tmp, csv_text)
            with self.assertRaises(SF.CatalogError):
                SF.load_catalog(path)

    def test_an_empty_catalog_matches_nothing_without_crashing(self):
        match, nearest = SF.match_catalog([], 20.0, 32.0)
        self.assertIsNone(match)
        self.assertIsNone(nearest)

    @unittest.skipUnless(SF.HAVE_XLSX, "openpyxl not installed")
    def test_the_generated_demo_xlsx_matches_the_same_as_its_csv_twin(self):
        """The real demo fixture shipped for this feature (step_file_demo/
        material_mould_catalog_demo.{csv,xlsx}) -- both formats of the same
        catalog must answer an inquiry identically."""
        demo_dir = sample_jobs.path("step_file_demo")
        csv_path = os.path.join(demo_dir, "material_mould_catalog_demo.csv")
        xlsx_path = os.path.join(demo_dir, "material_mould_catalog_demo.xlsx")
        if not (os.path.exists(csv_path) and os.path.exists(xlsx_path)):
            self.skipTest("demo catalog fixtures not present on this machine")
        csv_rows = SF.load_catalog(csv_path)
        xlsx_rows = SF.load_catalog(xlsx_path)
        self.assertEqual(len(csv_rows), len(xlsx_rows))
        csv_match, _ = SF.match_catalog(csv_rows, 25.0, 40.0)
        xlsx_match, _ = SF.match_catalog(xlsx_rows, 25.0, 40.0)
        self.assertEqual(csv_match.material_sr_no, xlsx_match.material_sr_no)
        self.assertEqual(csv_match.mould_sr_no, xlsx_match.mould_sr_no)


class TheCatalogMissExplainerPromptCarriesNumbersOnly(unittest.TestCase):
    """catalog_explain_prompt is the one thing that leaves this machine for
    the near-miss case -- it must carry the inquiry's ID/OD, the nearest
    row's own figures and Sr Nos, and nothing else: never a file path,
    never the catalog's other rows, never the STEP file."""

    def _nearest(self):
        return SF.CatalogRow(
            id_mm=20.0, od_mm=32.0, id_tolerance_mm=0.15, od_tolerance_mm=0.2,
            material_sr_no="MAT-202", mould_sr_no="MLD-103",
            raw={"Seal Size (IDxODxW)": "20x32x7", "Compound": "FKM"})

    def test_the_prompt_carries_both_sets_of_numbers_and_both_sr_nos(self):
        prompt = SF.catalog_explain_prompt(20.9, 33.0, self._nearest())
        self.assertIn("20.90", prompt)
        self.assertIn("33.00", prompt)
        self.assertIn("20.00", prompt)
        self.assertIn("32.00", prompt)
        self.assertIn("MAT-202", prompt)
        self.assertIn("MLD-103", prompt)
        self.assertIn("not a confirmed match", prompt)

    def test_the_prompt_never_names_a_file_or_path(self):
        prompt = SF.catalog_explain_prompt(20.9, 33.0, self._nearest())
        self.assertNotIn(".csv", prompt)
        self.assertNotIn(".xlsx", prompt)
        self.assertNotIn(".step", prompt.lower())

    def test_asks_for_a_short_plain_answer_not_a_report(self):
        prompt = SF.catalog_explain_prompt(20.9, 33.0, self._nearest())
        self.assertIn("ONE or TWO short", prompt)
        self.assertIn("no bullet points", prompt)


if __name__ == "__main__":
    unittest.main()
