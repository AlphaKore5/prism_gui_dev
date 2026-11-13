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
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.boq import industries                          # noqa: E402


class WhichIndustriesHaveAPdfTakeoff(unittest.TestCase):
    def test_hvac_has_one(self):
        self.assertTrue(industries.has_takeoff("HVAC"))

    def test_elv_has_one(self):
        self.assertTrue(industries.has_takeoff("ELV"))

    def test_general_does_not(self):
        self.assertFalse(industries.has_takeoff("General"))

    def test_an_unknown_industry_does_not(self):
        self.assertFalse(industries.has_takeoff("Marine"))

    def test_general_is_first_in_the_dropdown_order(self):
        self.assertEqual(industries.NAMES[0], industries.GENERAL)
        self.assertIn(industries.HVAC, industries.NAMES)
        self.assertIn(industries.ELV, industries.NAMES)


class WhichIndustriesOfferAnAiTagRecheckAlongsideTheirOcr(unittest.TestCase):
    """item 2 (5 Nov 2026): gated the same place has_takeoff() already
    is, so takeoff.py can offer or withhold the AI tag re-check without
    knowing anything HVAC-specific itself."""

    def test_hvac_has_one(self):
        self.assertTrue(industries.has_ai_tag_recheck("HVAC"))

    def test_elv_does_not_this_is_the_other_gate(self):
        self.assertFalse(industries.has_ai_tag_recheck("ELV"))

    def test_general_does_not(self):
        self.assertFalse(industries.has_ai_tag_recheck("General"))

    def test_an_unknown_industry_does_not(self):
        self.assertFalse(industries.has_ai_tag_recheck("Marine"))


class WhichIndustriesAreReadPurelyByAnAiVisionModel(unittest.TestCase):
    """item 63 (7 Nov 2026): ELV has no geometry engine behind it at all --
    the AI reading mode (whole page vs tiled) IS the whole takeoff, a
    different shape from HVAC's AI tag re-check (which only supplements a
    real geometry measurement). The two gates are deliberately exclusive
    today."""

    def test_elv_has_one(self):
        self.assertTrue(industries.has_ai_read_modes("ELV"))

    def test_hvac_does_not_it_has_a_geometry_engine(self):
        self.assertFalse(industries.has_ai_read_modes("HVAC"))

    def test_general_does_not(self):
        self.assertFalse(industries.has_ai_read_modes("General"))

    def test_an_unknown_industry_does_not(self):
        self.assertFalse(industries.has_ai_read_modes("Marine"))


class AnIndustryWithNoRuleSetRaisesRatherThanGuessing(unittest.TestCase):
    """Never silently fall back to HVAC's own rules for an industry that
    has none -- the whole point of item 26's dropdown is that nothing
    about reading a drawing is ever assumed."""

    def test_scan_layers_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.scan_layers("Marine", "/x/does/not/matter.pdf")

    def test_extract_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.extract("Marine", "/x/does/not/matter.pdf", {}, 9.0)

    def test_extract_threads_vision_tag_reader_through_to_hvac(self):
        """item 2: this dispatcher's own job for the new parameter is
        exactly what it already does for use_ocr/log -- pass it straight
        through, never read or interpret it itself."""
        fake_hvac = mock.Mock()
        fake_hvac.extract.return_value = {"labels": []}
        reader = mock.Mock()
        with mock.patch.object(industries, "_hvac", return_value=fake_hvac):
            industries.extract("HVAC", "/x/does/not/matter.pdf", {}, 9.0,
                               vision_tag_reader=reader)
        fake_hvac.extract.assert_called_once()
        self.assertIs(fake_hvac.extract.call_args.kwargs["vision_tag_reader"], reader)


class ExtractAiReadIsASeparateEntryPointFromExtract(unittest.TestCase):
    """item 63: extract()'s own signature (layer_map, pt_per_ft) is HVAC's
    Step-1 geometry shape -- an industry with no geometry engine gets its
    own entry point, not an overload with those params ignored."""

    def test_extract_still_raises_for_elv_it_has_no_geometry_shape(self):
        with self.assertRaises(ValueError):
            industries.extract("ELV", "/x/does/not/matter.pdf", {}, 9.0)

    def test_extract_ai_read_raises_for_an_industry_with_no_ai_read_shape(self):
        with self.assertRaises(ValueError):
            industries.extract_ai_read("HVAC", "/x/does/not/matter.pdf", mock.Mock())

    def test_extract_ai_read_threads_path_and_reader_through_to_elv(self):
        fake_elv = mock.Mock()
        fake_elv.extract.return_value = {"method": "ai_tiled", "pages": []}
        reader = mock.Mock()
        with mock.patch.object(industries, "_elv", return_value=fake_elv):
            industries.extract_ai_read("ELV", "/x/does/not/matter.pdf", reader)
        fake_elv.extract.assert_called_once()
        args, kwargs = fake_elv.extract.call_args
        self.assertEqual(args, ("/x/does/not/matter.pdf", reader))

    def test_summary_text_dispatches_to_elv_too(self):
        fake_elv = mock.Mock()
        fake_elv.summary_text.return_value = "an AI reading"
        with mock.patch.object(industries, "_elv", return_value=fake_elv):
            text = industries.summary_text("ELV", {"method": "ai_tiled"})
        self.assertEqual(text, "an AI reading")

    def test_summary_text_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.summary_text("Marine", {})

    def test_layer_preview_raises_for_an_unbuilt_industry(self):
        with self.assertRaises(ValueError):
            industries.layer_preview("Marine", "/x/does/not/matter.pdf", "k1")

    def test_roles_and_scales_are_just_empty_not_an_error(self):
        """Read-only lookups used to populate a combo box -- an empty list
        (nothing to offer yet) rather than a raised error, since nothing
        here is being asked to measure anything."""
        self.assertEqual(industries.roles("Marine"), [])
        self.assertEqual(industries.scales("Marine"), {})

    def test_review_rows_is_just_empty_not_an_error(self):
        self.assertEqual(industries.review_rows("Marine", {"labels": []}), [])

    def test_symbol_counts_and_areas_is_just_empty_not_an_error(self):
        self.assertEqual(industries.symbol_counts_and_areas("Marine", {}), [])

    def test_writeup_note_and_derivation_example_are_just_empty_not_an_error(self):
        self.assertEqual(industries.writeup_note("Marine"), "")
        self.assertEqual(industries.derivation_example("Marine"), "")


class WriteupGuidanceIsHvacsOwnAndLivesHereNotInTheEngine(unittest.TestCase):
    """Found 31 Oct 2026: core/boq.py's own formatting_prompt() used to
    carry this exact HVAC text inline, gated on a bare `hvac: bool` --
    one `if` away from leaking into every other trade's own BOQ, and the
    opposite of the owner's own standing rule that a trade-specific rule
    must live apart. Moved here, the same app-side home every other
    per-industry BOQ rule already lives in; the engine function itself
    now only ever sees whatever string the caller resolved and handed it
    (addons/boq/dialog.py, via these two functions)."""

    def test_hvac_gets_its_own_real_write_up_text(self):
        note = industries.writeup_note("HVAC")
        self.assertIn("HVAC-SPECIFIC WRITE-UP RULES", note)
        self.assertIn("NOT AUTOMATICALLY A DUPLICATE", note)
        self.assertIn("LEGEND/KEY", note)

    def test_hvac_gets_a_rule_against_borrowing_a_type_from_elsewhere(self):
        """31 Oct 2026: the write-up agent once called every bare TR tag
        "Hi-Wall" because that was the only equipment type word anywhere
        else in the document -- this is the standing rule meant to catch
        that whole class of mistake, not just that one instance of it."""
        note = industries.writeup_note("HVAC")
        self.assertIn("A BARE NUMBER IS NOT A TYPE", note)

    def test_hvac_gets_its_own_worked_derivation_example(self):
        example = industries.derivation_example("HVAC")
        self.assertIn("duct", example.lower())
        self.assertNotIn("camera", example.lower())

    def test_hvac_gets_a_rule_against_one_blended_duct_area_total(self):
        """13 Nov 2026: one real write-up broke supply/return duct into a
        per-size sheet-metal/insulation area line each; a later run on the
        same drawing collapsed every duct system into one blended "length x
        assumed average perimeter" total instead -- correct-looking, useless
        for ordering sheet by size. This is the rule meant to stop that."""
        note = industries.writeup_note("HVAC")
        self.assertIn("NEVER ONE BLENDED TOTAL", note)
        self.assertIn("per duct size", note.lower())

    def test_hvac_insulation_area_is_always_a_figure_never_a_blank_line(self):
        """13 Nov 2026: one write-up gave thermal insulation as a worked
        figure (1,063.7 sqm against the client's 1,114.8); a later one on
        the same drawing left it a blank provisional line."""
        note = industries.writeup_note("HVAC")
        self.assertIn("total insulation area", note)
        self.assertIn("never left blank", note)

    def test_hvac_bills_vav_boxes_from_the_shape_count(self):
        note = industries.writeup_note("HVAC")
        self.assertIn("VAV BOX QUANTITY COMES FROM THE SHAPE COUNT", note)

    def test_a_named_layer_can_start_on_a_remembered_colour_role(self):
        """item 80: the same real case hvac_takeoff's own test covers,
        through this add-on's dispatch."""
        layer = {"name": "ACME-HVAC-Z Piece",
                 "color_keys": {"#ff0000@1.08:line": 870.0, "#808080@0.72:line": 3000.0}}
        saved = {"#ff0000@1.08:line": "return", "#808080@0.72:line": "ignore"}
        self.assertEqual(industries.suggest_role_from_memory("HVAC", layer, saved), "return")
        self.assertIsNone(industries.suggest_role_from_memory("Marine", layer, saved))
        self.assertIsNone(industries.suggest_role_from_memory(
            "HVAC", {"name": None, "color_keys": {"#ff0000@1.08:line": 1.0}}, saved))


class SavedLayerRolesIsStep1sOwnCrossTenderMemory(unittest.TestCase):
    """Found 30 Oct 2026: a real client file read 0 duct runs through
    BOQ's dialog while the standalone hvac_takeoff.py tool, run on the
    exact same PDF, measured many -- because that tool's own combo boxes
    always start from `load_map()`'s saved roles and BOQ's dialog never
    looked at that file at all. These two functions are the fix's
    dispatch surface; the dialog wiring is covered in test_boq_takeoff.py.
    """

    def test_an_unbuilt_industry_has_no_memory_to_read(self):
        self.assertEqual(industries.saved_layer_roles("Marine"), {})

    def test_an_unbuilt_industry_silently_ignores_a_remember_call(self):
        industries.remember_layer_roles("Marine", {"k1": "supply"})  # must not raise

    def test_hvac_reads_whatever_hvac_takeoff_itself_has_saved(self):
        with mock.patch.object(industries, "_hvac") as hv:
            hv.return_value.load_map.return_value = {"#000000@1.56:line": "supply"}
            self.assertEqual(industries.saved_layer_roles("HVAC"),
                              {"#000000@1.56:line": "supply"})

    def test_hvac_remember_reaches_hvac_takeoffs_own_save_map(self):
        with mock.patch.object(industries, "_hvac") as hv:
            industries.remember_layer_roles("HVAC", {"k1": "return"})
            hv.return_value.save_map.assert_called_once_with({"k1": "return"})


class SuggestRoleReadsARealLayerNameItem76(unittest.TestCase):
    """item 76's own dispatch surface -- the actual keyword reading lives
    in hvac_takeoff.suggest_role_from_name(), already tested on its own
    in hvac_takeoff/test_hvac_takeoff.py; this only covers industry
    dispatch and the "nothing to read" cases."""

    def test_hvac_reaches_hvac_takeoffs_own_suggestion(self):
        with mock.patch.object(industries, "_hvac") as hv:
            hv.return_value.suggest_role_from_name.return_value = "supply"
            self.assertEqual(
                industries.suggest_role("HVAC", "ACME-HVAC-Supply Air Duct"), "supply")
            hv.return_value.suggest_role_from_name.assert_called_once_with(
                "ACME-HVAC-Supply Air Duct")

    def test_an_unbuilt_industry_suggests_nothing(self):
        self.assertIsNone(industries.suggest_role("Marine", "Anything"))

    def test_no_name_at_all_suggests_nothing_without_even_asking_hvac_takeoff(self):
        with mock.patch.object(industries, "_hvac") as hv:
            self.assertIsNone(industries.suggest_role("HVAC", None))
            hv.return_value.suggest_role_from_name.assert_not_called()


class SymbolCountsAndAreasReachTheReviewScreen(unittest.TestCase):
    """item 27 rule 3, completed: the per-symbol area was computed in
    hvac_takeoff.extract() (28c) but never reached a screen -- this is the
    dispatcher the review table actually calls, so a regression here would
    silently go back to count-only."""

    def _result(self):
        return {"terminals": [
            {"type": "Supply Diffuser", "area_sqft": 2.0},
            {"type": "Supply Diffuser", "area_sqft": 2.0},
        ], "accessories": [
            {"type": "Volume Control Damper", "area_sqft": 0.5},
        ]}

    def test_one_row_per_type_with_count_and_total_area(self):
        rows = industries.symbol_counts_and_areas("HVAC", self._result())
        by_type = {t: (n, a) for t, n, a in rows}
        self.assertEqual(by_type["Supply Diffuser"], (2, 4.0))
        self.assertEqual(by_type["Volume Control Damper"], (1, 0.5))

    def test_a_type_with_no_area_data_reports_none_not_zero(self):
        result = {"terminals": [{"type": "Supply Diffuser"}], "accessories": []}
        rows = industries.symbol_counts_and_areas("HVAC", result)
        self.assertEqual(rows, [("Supply Diffuser", 1, None)])


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
        ok = industries.apply_review_edit("Marine", result, 0, "3 TR")
        self.assertFalse(ok)
        self.assertEqual(result["tr_labels"], [8.0])


if __name__ == "__main__":
    unittest.main()
