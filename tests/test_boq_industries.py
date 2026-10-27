"""addons/boq/industries.py -- item 26's per-industry rule-set registry.

No real PDF is read here (that is hvac_takeoff's own job, already covered
by hvac_takeoff/test_hvac_takeoff.py); this file is about the registry
and review/edit logic BOQ's dialog actually depends on: which industries
offer a PDF-takeoff, and whether a person's correction to a reading
actually reaches the numbers the final summary is built from.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.boq import industries                          # noqa: E402


class WhichIndustriesHaveAPdfTakeoff(unittest.TestCase):
    def test_hvac_has_one(self):
        self.assertTrue(industries.has_takeoff("HVAC"))

    def test_general_does_not(self):
        self.assertFalse(industries.has_takeoff("General"))

    def test_an_unknown_industry_does_not(self):
        self.assertFalse(industries.has_takeoff("ELV"))

    def test_general_is_first_in_the_dropdown_order(self):
        self.assertEqual(industries.NAMES[0], industries.GENERAL)
        self.assertIn(industries.HVAC, industries.NAMES)


class AnIndustryWithNoRuleSetRaisesRatherThanGuessing(unittest.TestCase):
    """Never silently fall back to HVAC's own rules for an industry that
    has none -- the whole point of item 26's dropdown is that nothing
    about reading a drawing is ever assumed."""

    def test_scan_layers_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.scan_layers("ELV", "/x/does/not/matter.pdf")

    def test_extract_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.extract("ELV", "/x/does/not/matter.pdf", {}, 9.0)

    def test_summary_text_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.summary_text("ELV", {})

    def test_roles_and_scales_are_just_empty_not_an_error(self):
        """Read-only lookups used to populate a combo box -- an empty list
        (nothing to offer yet) rather than a raised error, since nothing
        here is being asked to measure anything."""
        self.assertEqual(industries.roles("ELV"), [])
        self.assertEqual(industries.scales("ELV"), {})

    def test_review_rows_is_just_empty_not_an_error(self):
        self.assertEqual(industries.review_rows("ELV", {"labels": []}), [])


class ReviewRowsCarryTheRealConfidenceNeverAnInventedOne(unittest.TestCase):
    def _result(self):
        return {"labels": [
            {"kind": "size", "text": '12x8', "conf": 1.0, "page": 0},
            {"kind": "tr", "text": "17 TR", "tr": 17.0, "x_pt": 10, "y_pt": 20,
             "page": 0, "conf": 0.42, "source": "ocr"},
            {"kind": "cfm", "text": "900CFM", "cfm": 900, "x_pt": 1, "y_pt": 2,
             "page": 1, "conf": 0.91, "source": "ocr"},
        ]}

    def test_one_row_per_label_with_its_own_confidence(self):
        rows = industries.review_rows("HVAC", self._result())
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["conf"], 0.42)
        self.assertEqual(rows[2]["conf"], 0.91)

    def test_only_tr_and_cfm_rows_are_marked_editable(self):
        rows = industries.review_rows("HVAC", self._result())
        self.assertFalse(rows[0]["editable"])   # size: paired with duct geometry
        self.assertTrue(rows[1]["editable"])    # tr
        self.assertTrue(rows[2]["editable"])    # cfm


class CorrectingAReadingActuallyChangesTheNumbers(unittest.TestCase):
    """The whole point of letting a person edit a reading before "Make my
    BOQ" is that the correction reaches the figures the write-up prompt
    is actually built from -- a table edit that only looked right on
    screen would be worse than no edit box at all."""

    def _result(self):
        return {"labels": [
            {"kind": "tr", "text": "8 TR", "tr": 8.0, "x_pt": 0, "y_pt": 0,
             "page": 0, "conf": 0.42, "source": "ocr"},
            {"kind": "cfm", "text": "900CFM", "cfm": 900, "x_pt": 1, "y_pt": 2,
             "page": 0, "conf": 0.91, "source": "ocr"},
        ], "tr_labels": [8.0], "cfm_label_counts": {900: 1}}

    def test_correcting_a_tr_reading_updates_tr_labels(self):
        result = self._result()
        ok = industries.apply_review_edit("HVAC", result, 0, "3 TR")
        self.assertTrue(ok)
        self.assertEqual(result["tr_labels"], [3.0])
        self.assertEqual(result["labels"][0]["conf"], 1.0)

    def test_correcting_a_cfm_reading_updates_cfm_label_counts(self):
        result = self._result()
        ok = industries.apply_review_edit("HVAC", result, 1, "450CFM")
        self.assertTrue(ok)
        self.assertEqual(result["cfm_label_counts"], {450: 1})

    def test_text_that_cannot_be_read_as_the_rows_own_kind_is_rejected(self):
        """A TR row's box must not quietly accept "fifty" as if it parsed
        -- the edit is rejected, not silently turned into a 0."""
        result = self._result()
        ok = industries.apply_review_edit("HVAC", result, 0, "not a number")
        self.assertFalse(ok)
        self.assertEqual(result["tr_labels"], [8.0])   # unchanged

    def test_a_size_row_is_not_editable_through_this_path_either(self):
        result = {"labels": [{"kind": "size", "text": "12x8", "w_in": 12,
                              "d_in": 8, "x_pt": 0, "y_pt": 0, "page": 0,
                              "conf": 1.0, "source": "geometry"}]}
        ok = industries.apply_review_edit("HVAC", result, 0, "20x10")
        self.assertFalse(ok)

    def test_an_unbuilt_industry_never_applies_an_edit(self):
        result = self._result()
        ok = industries.apply_review_edit("ELV", result, 0, "3 TR")
        self.assertFalse(ok)
        self.assertEqual(result["tr_labels"], [8.0])


if __name__ == "__main__":
    unittest.main()
