"""hvac_takeoff.py's own test file -- none existed before this. Run with
this tool's own venv:

    cd hvac_takeoff && source .venv/bin/activate && python3 -m unittest test_hvac_takeoff -v

Covers the Hi-Wall equipment-note parser (24 Oct 2026, reverse-engineered
from a real tender drawing, ASPENTECH): "<N>TR HI-WALL" becomes an
equipment entry instead of silently folding into the generic TR tag list,
and a nearby separate "<N>NOS." box sets its quantity.
"""
import math
import unittest
from unittest import mock

import hvac_takeoff as H


class AHiWallNoteBecomesAnEquipmentEntry(unittest.TestCase):

    def test_the_capacity_is_read_as_equipment_not_a_generic_tr_tag(self):
        found = H.parse_label("2TR HI-WALL", 0, 0, "text")
        kinds = [f["kind"] for f in found]
        self.assertIn("equipment", kinds)
        self.assertNotIn("tr", kinds)   # the whole point -- no double-booking
        eq = next(f for f in found if f["kind"] == "equipment")
        self.assertEqual(eq["type"], "Hi-Wall Split AC")
        self.assertEqual(eq["capacity_tr"], 2.0)

    def test_hyphen_or_space_between_hi_and_wall_both_match(self):
        for text in ("2TR HI-WALL", "2TR HI WALL", "2tr hi-wall"):
            with self.subTest(text=text):
                kinds = [f["kind"] for f in H.parse_label(text, 0, 0, "text")]
                self.assertIn("equipment", kinds)

    def test_a_plain_tonnage_tag_with_no_hi_wall_suffix_stays_generic(self):
        found = H.parse_label("17 TR", 0, 0, "text")
        kinds = [f["kind"] for f in found]
        self.assertIn("tr", kinds)
        self.assertNotIn("equipment", kinds)
        self.assertEqual(next(f for f in found if f["kind"] == "tr")["tr"], 17.0)

    def test_nos_count_is_its_own_kind(self):
        found = H.parse_label("2NOS.", 0, 0, "text")
        self.assertEqual([f["kind"] for f in found], ["nos"])
        self.assertEqual(found[0]["nos"], 2)


class TheNosCountJoinsByProximityNotByBeingTheSameString(unittest.TestCase):
    """The real drawing writes the capacity and the installed count as two
    separate text boxes, one line apart -- this is the join that combines
    them, and the fallback when there is nothing to join to."""

    PT_PER_FT = 9.0

    def _labels(self, *specs):
        """specs: (text, x, y) tuples -- 'page' added the way extract()'s
        per-page loop adds it to every real label, not by parse_label()
        itself."""
        out = []
        for text, x, y in specs:
            found = H.parse_label(text, x, y, "ocr0")
            for f in found:
                f["page"] = 0
            out += found
        return out

    def test_a_nearby_nos_label_sets_the_quantity(self):
        labels = self._labels(("2TR HI-WALL", 100, 100), ("2NOS.", 100, 118))  # 2 ft below
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["qty"], 2)

    def test_no_nearby_nos_label_defaults_to_one_not_zero_or_blank(self):
        labels = self._labels(("2TR HI-WALL", 100, 100))
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["qty"], 1)

    def test_a_far_away_nos_label_is_not_joined(self):
        labels = self._labels(("2TR HI-WALL", 100, 100),
                              ("4NOS.", 100, 100 + 50 * self.PT_PER_FT))   # 50 ft away
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(out[0]["qty"], 1)   # the far one must not count

    def test_two_hi_wall_notes_each_get_their_own_nearest_nos(self):
        labels = self._labels(("2TR HI-WALL", 100, 100), ("2NOS.", 100, 118),
                              ("2TR HI-WALL", 500, 500))   # the other, further away, no NOS. nearby
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(len(out), 2)
        by_pos = {round(e["x_pt"]): e["qty"] for e in out}
        self.assertEqual(by_pos[100], 2)
        self.assertEqual(by_pos[500], 1)


class RealTextAndOcrReadingTheSameLabelAreDeduplicated(unittest.TestCase):
    """24 Oct 2026: the real "17 TR" rooftop-unit label was present in
    both a text-sourced and an ocr90-sourced entry at the same spot --
    OCR scans the whole rasterised page with no way to know real
    (selectable) text already read that exact label."""

    PT_PER_FT = 9.0

    def test_a_real_text_label_and_an_ocr_read_of_the_same_spot_collapse_to_one(self):
        text = H.parse_label("17 TR", 100, 100, "text")
        for f in text: f["page"] = 0
        ocr = H.parse_label("17 TR", 100.5, 100.3, "ocr90", conf=0.98)
        for f in ocr: f["page"] = 0
        out = H.dedupe_labels(text + ocr, self.PT_PER_FT)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source"], "text")   # the exact reading wins, not the guess

    def test_two_real_separate_occurrences_stay_separate(self):
        a = H.parse_label("17 TR", 100, 100, "text")
        for f in a: f["page"] = 0
        b = H.parse_label("17 TR", 100, 100 + 50 * self.PT_PER_FT, "text")   # 50 ft away, genuinely different
        for f in b: f["page"] = 0
        out = H.dedupe_labels(a + b, self.PT_PER_FT)
        self.assertEqual(len(out), 2)

    def test_two_ocr_passes_of_the_same_spot_keep_the_higher_confidence_one(self):
        lo = H.parse_label("17 TR", 100, 100, "ocr0", conf=0.70)
        for f in lo: f["page"] = 0
        hi = H.parse_label("17 TR", 100.2, 100.1, "ocr90", conf=0.97)
        for f in hi: f["page"] = 0
        out = H.dedupe_labels(lo + hi, self.PT_PER_FT)
        self.assertEqual(len(out), 1)
        self.assertAlmostEqual(out[0]["conf"], 0.97)


class _FakePage:
    """Just enough of pdfplumber's page shape for count_symbol_rects and
    count_symbol_curves -- they only ever read page.rects / page.curves."""
    def __init__(self, rects=(), curves=()):
        self.rects = list(rects)
        self.curves = list(curves)


_RED = (1.0, 0.0, 0.0)
_CYAN = (0.0, 1.0, 1.0)


def _rect(x0, top, w, h, color=_RED, lw=1.08):
    return {"x0": x0, "x1": x0 + w, "top": top, "bottom": top + h,
            "stroke": True, "stroking_color": color, "non_stroking_color": color,
            "linewidth": lw}


def _curve(cx, cy, w, h, color=_CYAN, lw=0.84):
    """A 4-point polyline whose bounding box is (w, h), centred at
    (cx, cy) -- the real manual-damper symbol's own shape (item 29d)."""
    pts = [(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2),
           (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)]
    return {"pts": pts, "stroke": True, "stroking_color": color,
            "non_stroking_color": color, "linewidth": lw}


class CountSymbolRectsCountsShapesNotRawRects(unittest.TestCase):
    """24 Oct 2026, reverse-engineered from the real damper layer: it carried
    both an unrelated huge border rect and every real damper drawn as two
    overlapping squares (outer + inner) at the same spot."""

    LAYER_MAP = {"#ff0000@1.08:rect": "volume_damper", "#00ffff@0.84:rect": "diffuser"}

    def test_only_rects_mapped_to_the_role_are_counted(self):
        page = _FakePage([_rect(0, 0, 9, 9, _RED), _rect(500, 500, 4.4, 4.4, _CYAN, lw=0.84)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_an_oversized_rect_on_the_same_layer_is_excluded(self):
        page = _FakePage([_rect(0, 0, 9, 9, _RED), _rect(0, 0, 888, 1556, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_a_nested_outer_and_inner_square_at_the_same_spot_count_as_one_symbol(self):
        page = _FakePage([_rect(100, 100, 9, 9, _RED), _rect(102.3, 102.3, 4.4, 4.4, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_two_genuinely_separate_symbols_both_count(self):
        page = _FakePage([_rect(100, 100, 9, 9, _RED), _rect(500, 500, 9, 9, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 2)

    def test_each_symbol_carries_its_own_width_and_height(self):
        """item 27 rule 3: billing a damper by area (sq.m, the client's
        own convention on the real file) needs its size, not just a
        centre point -- count_symbol_rects now returns (cx, cy, w, h)."""
        page = _FakePage([_rect(100, 100, 9, 4.5, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)
        cx, cy, w, h = out[0]
        self.assertAlmostEqual(w, 9)
        self.assertAlmostEqual(h, 4.5)

    def test_a_nested_pair_keeps_the_outer_larger_footprint_not_the_inner(self):
        """Reverse-engineered from the real damper symbol: an outer ~9x9pt
        frame with a smaller ~4.4x4.4pt mark inside it at the same spot.
        Billing by area needs the frame someone would actually cut a hole
        for -- the outer one -- regardless of which rect pdfplumber
        happens to return first."""
        outer_first = _FakePage([_rect(100, 100, 9, 9, _RED), _rect(102.3, 102.3, 4.4, 4.4, _RED)])
        inner_first = _FakePage([_rect(102.3, 102.3, 4.4, 4.4, _RED), _rect(100, 100, 9, 9, _RED)])
        for page in (outer_first, inner_first):
            with self.subTest(page=page):
                out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
                self.assertEqual(len(out), 1)
                _, _, w, h = out[0]
                self.assertAlmostEqual(w, 9)
                self.assertAlmostEqual(h, 9)


class TheSecondDuctSystemIsDetectedByItsInkColorNotGuessed(unittest.TestCase):
    """24 Oct 2026: every room on the real drawing has a primary black
    size/CFM pair and a second one, right below it, in orange -- no
    legend says what the second one is. These are the exact pixel colors
    sampled off the real rendered page (both real orange reads and real
    black/grey reads, including ones contaminated by a nearby colored
    gridline), used to set _is_secondary_duct_pixel's threshold."""

    def test_real_orange_samples_are_all_flagged_secondary(self):
        orange_samples = [
            (255, 170, 85), (255, 169, 84), (255, 170, 87), (255, 168, 83),
            (255, 166, 78), (255, 168, 82), (255, 163, 72), (255, 181, 109),
            (255, 178, 102), (255, 198, 142), (255, 164, 74), (255, 163, 73),
        ]
        for rgb in orange_samples:
            with self.subTest(rgb=rgb):
                self.assertTrue(H._is_secondary_duct_pixel(*rgb))

    def test_real_black_grey_samples_including_contaminated_ones_are_not_flagged(self):
        grey_samples = [
            (116, 116, 116), (143, 143, 143), (74, 74, 74), (121, 121, 121),
            (80, 80, 80), (84, 84, 84), (82, 82, 82), (89, 89, 89),
            (113, 113, 113), (162, 162, 162),
            (118, 132, 104), (91, 104, 77), (118, 129, 107),  # gridline-contaminated
        ]
        for rgb in grey_samples:
            with self.subTest(rgb=rgb):
                self.assertFalse(H._is_secondary_duct_pixel(*rgb))

    def test_a_pure_green_outlier_is_not_mistaken_for_orange(self):
        self.assertFalse(H._is_secondary_duct_pixel(75, 255, 75))


class SymbolCountsAndAreasFeedBothTheSummaryAndTheReviewScreen(unittest.TestCase):
    """item 27 rule 3, completed 29 Oct 2026: per-symbol area was computed
    (28c) but neither summary_text() nor the review table read it -- this
    is the one function both now call, so they can't drift apart."""

    def _result(self, terminals=None, accessories=None):
        return {"terminals": terminals or [], "accessories": accessories or []}

    def test_counts_and_sums_area_per_type(self):
        res = self._result(
            terminals=[{"type": "Supply Diffuser", "area_sqft": 2.0},
                      {"type": "Supply Diffuser", "area_sqft": 2.5}],
            accessories=[{"type": "Volume Control Damper", "area_sqft": 0.3}])
        out = {t: (n, a) for t, n, a in H.symbol_counts_and_areas(res)}
        self.assertEqual(out["Supply Diffuser"], (2, 4.5))
        self.assertEqual(out["Volume Control Damper"], (1, 0.3))

    def test_a_type_with_no_area_field_reports_none(self):
        res = self._result(terminals=[{"type": "Supply Diffuser"}])
        self.assertEqual(H.symbol_counts_and_areas(res), [("Supply Diffuser", 1, None)])

    def test_summary_text_includes_the_area_line(self):
        res = {"source": {"file": "x.pdf", "pages": 1}, "checks": {"runs": 0, "label_match_rate": 0},
              "duct_summary": [], "tr_labels": [], "cfm_label_counts": {}, "rooms": [],
              "equipment": [], "unresolved_duct_labels": [], "warnings": [],
              "terminals": [{"type": "Supply Diffuser", "area_sqft": 2.0}], "accessories": []}
        text = H.summary_text(res)
        self.assertIn("Supply Diffuser: 1", text)
        self.assertIn("sq.ft", text)
        self.assertIn("sq.m", text)


class CountSymbolCurvesFindsThePolylineDamperSymbol(unittest.TestCase):
    """29 Oct 2026, reverse-engineered from the real file: the manual
    volume-control-damper symbol is a hatched rectangle with a bowtie
    blade mark, drawn as a filled polyline -- count_symbol_rects (which
    only reads page.rects) never finds it. Visually confirmed at 4
    separate real positions before this was built (BOQ-CHANGES-TODO.md
    item 29d)."""

    LAYER_MAP = {"#00ffff@0.84:poly": "volume_damper"}

    def test_a_curve_on_the_mapped_layer_is_counted(self):
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)
        cx, cy, w, h = out[0]
        self.assertAlmostEqual(cx, 100)
        self.assertAlmostEqual(w, 4.4)
        self.assertAlmostEqual(h, 36.0)

    def test_a_curve_on_an_unmapped_layer_is_ignored(self):
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0, color=_RED)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(out, [])

    def test_two_curves_at_the_same_spot_count_as_one(self):
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0),
                                 _curve(100.5, 100.3, 4.6, 36.0)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_two_genuinely_separate_curves_both_count(self):
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0),
                                 _curve(500, 500, 4.4, 36.0)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 2)

    def test_an_oversized_curve_is_excluded(self):
        """A room outline or a long duct run drawn with the same colour/
        weight would otherwise be mistaken for the symbol."""
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0),
                                 _curve(900, 900, 400, 600)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_an_empty_points_list_does_not_crash(self):
        page = _FakePage(curves=[{"pts": [], "stroking_color": _CYAN,
                                  "non_stroking_color": _CYAN, "stroke": True, "linewidth": 0.84}])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(out, [])


class ACurveSourcedSymbolsAreaIsNoneNotAWrongNumber(unittest.TestCase):
    """item 29d: a curve symbol's bounding box is the drawn mark's own
    extent along the duct, not the item's physical cross-section the way
    a rect icon's bbox is -- area_sqft must stay blank for these, not a
    real-looking number that means nothing."""

    def test_rect_sourced_diffuser_gets_a_real_area(self):
        out = {t: a for t, n, a in H.symbol_counts_and_areas(
            {"terminals": [{"type": "Supply Diffuser", "area_sqft": 2.0}], "accessories": []})}
        self.assertEqual(out["Supply Diffuser"], 2.0)

    def test_curve_sourced_damper_gets_no_area(self):
        out = {t: a for t, n, a in H.symbol_counts_and_areas(
            {"terminals": [], "accessories": [{"type": "Volume Control Damper", "area_sqft": None}]})}
        self.assertIsNone(out["Volume Control Damper"])


class IsolatedDuctRunsAreFlaggedNeverAlteredOrMerged(unittest.TestCase):
    """item 29c: report-only, deliberately narrower than the DXF
    pipeline's own rejected gap-bridging idea (HVAC_DRAWING_RULES.md
    rule 2) -- this only ever adds a warning string, never touches a
    run's own length or geometry."""

    def _run(self, system, x1, y1, x2, y2, length_ft=10.0):
        return {"system": system, "x1_ft": x1, "y1_ft": y1, "x2_ft": x2,
                "y2_ft": y2, "length_ft": length_ft, "label": None}

    def test_a_run_connected_at_one_end_is_not_isolated(self):
        """A normal terminal run -- free at ONE end (a diffuser, a stub)
        is completely ordinary and must not be flagged."""
        runs = [self._run("supply", 0, 0, 10, 0),
               self._run("supply", 10, 0, 10, 10)]   # shares (10,0) with the first
        self.assertEqual(H._isolated_runs(runs), [])

    def test_a_run_connected_at_neither_end_is_isolated(self):
        runs = [self._run("supply", 0, 0, 10, 0),
               self._run("supply", 10, 0, 10, 10),
               self._run("supply", 500, 500, 510, 500)]   # nowhere near the other two
        out = H._isolated_runs(runs)
        self.assertEqual(len(out), 1)
        self.assertEqual((out[0]["x1_ft"], out[0]["y1_ft"]), (500, 500))

    def test_endpoints_within_tolerance_still_count_as_connected(self):
        """A real CAD gap of a foot or so at a junction is normal --
        tol_ft is there precisely so this is not flagged."""
        runs = [self._run("supply", 0, 0, 10, 0),
               self._run("supply", 10.5, 0.3, 10.5, 10)]   # 0.58ft from (10,0)
        self.assertEqual(H._isolated_runs(runs, tol_ft=2.0), [])

    def test_systems_are_checked_separately_a_return_run_does_not_rescue_a_supply_run(self):
        runs = [self._run("supply", 0, 0, 10, 0),
               self._run("return", 10, 0, 10, 10)]   # same point, DIFFERENT system
        out = H._isolated_runs(runs)
        self.assertEqual(len(out), 2)   # neither rescues the other

    def test_never_mutates_a_run(self):
        runs = [self._run("supply", 0, 0, 10, 0),
               self._run("supply", 500, 500, 510, 500)]
        before = [dict(r) for r in runs]
        H._isolated_runs(runs)
        self.assertEqual(runs, before)


class LayerPreviewPngIsolatesOnlyTheRequestedLayer(unittest.TestCase):
    """BOQ-CHANGES-TODO.md item 33: "what does this colour actually draw",
    as a picture, pointed out directly against a rival PDF-takeoff tool
    that already shows one next to its own layer list. Mocks pypdfium2's
    PdfDocument (a real PDF render) and `layer_lines` (a real pdfplumber
    open) -- same level this file already tests at, never a real PDF
    fixture. Returns bytes, not a path, so a person deciding every
    layer's role can click this on many of them without littering the
    client's own folder with a file per click."""

    def _fake_doc(self, size=(100, 80)):
        from PIL import Image
        page = mock.Mock()
        page.render.return_value.to_pil.return_value = Image.new("RGB", size, "white")
        doc = mock.MagicMock()
        doc.__getitem__.return_value = page
        return doc

    def test_returns_real_png_bytes(self):
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_doc()), \
                mock.patch.object(H, "layer_lines", return_value=([], (100, 80))):
            png = H.layer_preview_png("/x/fake.pdf", "k1")
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

    def test_asks_layer_lines_for_exactly_the_requested_key_and_page(self):
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_doc()), \
                mock.patch.object(H, "layer_lines",
                                  return_value=([], (100, 80))) as ll:
            H.layer_preview_png("/x/fake.pdf", "#ff0000@1.08:line", page_index=2)
        ll.assert_called_once_with("/x/fake.pdf", "#ff0000@1.08:line", 2)

    def test_a_layer_with_no_segments_still_returns_a_picture_not_an_error(self):
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_doc()), \
                mock.patch.object(H, "layer_lines", return_value=([], (100, 80))):
            png = H.layer_preview_png("/x/fake.pdf", "k1")
        self.assertGreater(len(png), 0)


class SaveMapRemembersRolesAcrossTendersWithoutTouchingTheRealFile(unittest.TestCase):
    """Found 30 Oct 2026: the standalone tool's own `start()` always wrote
    the current roles back to MAP_FILE before extracting, so a key learned
    on one drawing is pre-filled on the next -- this is now a function
    BOQ's dialog (via industries.py) can call too, instead of reading only.
    Patches `H.MAP_FILE` to a tmp path -- never the repo's real
    hvac_takeoff/layer_map.json, which real tenders' history lives in."""

    def test_a_new_key_is_added_without_losing_the_old_ones(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(json.dumps({"#ff0000@1.08:line": "return"}).encode())
            path = f.name
        with mock.patch.object(H, "MAP_FILE", path):
            H.save_map({"#000000@1.56:line": "supply"})
            self.assertEqual(H.load_map(), {
                "#ff0000@1.08:line": "return",
                "#000000@1.56:line": "supply"})

    def test_re_saving_the_same_key_overwrites_rather_than_duplicates(self):
        import json
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            f.write(json.dumps({"#000000@1.56:line": "ignore"}).encode())
            path = f.name
        with mock.patch.object(H, "MAP_FILE", path):
            H.save_map({"#000000@1.56:line": "supply"})
            self.assertEqual(H.load_map(), {"#000000@1.56:line": "supply"})

    def test_a_write_failure_is_swallowed_not_raised(self):
        with mock.patch.object(H, "MAP_FILE", "/no/such/dir/map.json"):
            H.save_map({"#000000@1.56:line": "supply"})  # must not raise


if __name__ == "__main__":
    unittest.main()
