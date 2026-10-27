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
    """Just enough of pdfplumber's page shape for count_symbol_rects --
    it only ever reads page.rects."""
    def __init__(self, rects):
        self.rects = rects


_RED = (1.0, 0.0, 0.0)
_CYAN = (0.0, 1.0, 1.0)


def _rect(x0, top, w, h, color=_RED, lw=1.08):
    return {"x0": x0, "x1": x0 + w, "top": top, "bottom": top + h,
            "stroke": True, "stroking_color": color, "non_stroking_color": color,
            "linewidth": lw}


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


if __name__ == "__main__":
    unittest.main()
