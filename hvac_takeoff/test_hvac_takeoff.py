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


class SplitAcNoteCarriesItsOwnRealQtyNeverAGuess(unittest.TestCase):
    """Found reading client_2nd_sample via a tiled OCR re-read, 30 Oct
    2026: this drawing's own split-unit notation is "N#(X.XXTR/Y.YHP)" --
    qty, TR and HP together in one note, never the word "HI-WALL"
    anywhere near it (HIWALL_RE never fires). Unlike a Hi-Wall note, the
    qty here is already IN the text -- must never be thrown away for a
    NOS_RE proximity guess the way a bare Hi-Wall note's qty is."""

    PT_PER_FT = 9.0

    def _labels(self, *specs):
        out = []
        for text, x, y in specs:
            found = H.parse_label(text, x, y, "ocr0")
            for f in found:
                f["page"] = 0
            out += found
        return out

    def test_qty_tr_and_hp_are_all_read_from_one_note(self):
        found = H.parse_label("2#(1.65TR/2.0HP)", 0, 0, "text")
        kinds = [f["kind"] for f in found]
        self.assertEqual(kinds, ["equipment"])
        eq = found[0]
        self.assertEqual(eq["qty"], 2)
        self.assertEqual(eq["capacity_tr"], 1.65)
        self.assertEqual(eq["capacity_hp"], 2.0)

    def test_it_is_never_folded_into_the_generic_tr_list(self):
        found = H.parse_label("2#(1.65TR/2.0HP)", 0, 0, "text")
        self.assertNotIn("tr", [f["kind"] for f in found])

    def test_type_is_marked_not_read_never_guessed_as_hi_wall(self):
        found = H.parse_label("2#(1.65TR/2.0HP)", 0, 0, "text")
        self.assertNotEqual(found[0]["type"], "Hi-Wall Split AC")
        self.assertIn("not read", found[0]["type"])

    def test_a_nearby_nos_label_never_overrides_the_notes_own_qty(self):
        """The whole point of this class: a Hi-Wall note's qty comes from
        the NEAREST "NOS." box; this note's qty is its own and must stay
        2 even with an unrelated "4NOS." sitting right next to it."""
        labels = self._labels(("2#(1.65TR/2.0HP)", 100, 100), ("4NOS.", 100, 118))
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["qty"], 2)
        self.assertEqual(out[0]["capacity"], "1.65TR/2HP")

    def test_a_hi_wall_note_and_a_split_ac_note_both_come_through_untouched(self):
        labels = self._labels(("2TR HI-WALL", 100, 100), ("2#(1.65TR/2.0HP)", 500, 500))
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        self.assertEqual(len(out), 2)
        types = {e["type"] for e in out}
        self.assertIn("Hi-Wall Split AC", types)
        self.assertTrue(any("not read" in t for t in types))

    def test_every_equipment_entry_carries_a_raw_capacity_tr_float(self):
        """extract() reads this field directly (never re-parses the
        formatted "capacity" string, which a Hi-Wall entry's "2TR" and a
        Split AC entry's "1.65TR/2HP" don't share a shape for) -- found
        live, 30 Oct 2026, when that re-parse crashed on the second shape."""
        labels = self._labels(("2TR HI-WALL", 100, 100), ("2#(1.65TR/2.0HP)", 500, 500))
        out = H._equipment_from_labels(labels, self.PT_PER_FT)
        for e in out:
            self.assertIsInstance(e["capacity_tr"], float)


class VavBoxesCountedByTheirOwnUniqueTagNeverTheSizeCode(unittest.TestCase):
    """Found reading client_2nd_sample's own tiled OCR text, 30 Oct 2026:
    this drawing prints two unrelated things that both start "VAV-" --
    "VAV-1-11"/"VAV-2-12"/"VAV-3-19" (a unique tag, one per physical box)
    and "VAV-150"/"VAV-250"/"VAV-300" (a size/model code shared by many
    different boxes, far more common on the sheet). Counting the second
    kind would wildly over-count; VAV_RE must only ever match the first."""

    def test_a_zone_sequence_tag_is_read_as_vav(self):
        found = H.parse_label("VAV-1-11", 0, 0, "text")
        self.assertEqual(found, [{"kind": "vav", "zone": 1, "seq": 11, "tag": "VAV-1-11",
                                  "text": "VAV-1-11", "x_pt": 0, "y_pt": 0,
                                  "source": "text", "conf": 1.0}])

    def test_a_three_digit_size_code_is_not_read_as_a_vav_tag_at_all(self):
        for text in ("VAV-150", "VAV-250", "VAV-300", "VAV-35"):
            with self.subTest(text=text):
                self.assertEqual(H.parse_label(text, 0, 0, "text"), [])

    def test_a_stray_leading_digit_from_ocr_noise_does_not_break_the_real_tag(self):
        found = H.parse_label("5VAV-2-12", 0, 0, "text")
        self.assertEqual([f["tag"] for f in found], ["VAV-2-12"])

    def test_extract_counts_distinct_tags_not_repeat_reads_of_the_same_one(self):
        labels = []
        for text, x, y in [("VAV-1-11", 100, 100), ("VAV-1-11", 100.3, 100.2),  # same box, read twice
                           ("[VAV-1-11]", 100.1, 99.9),                         # same box, bracket-wrapped read
                           ("VAV-2-12", 500, 500)]:                              # a genuinely different box
            found = H.parse_label(text, x, y, "ocr0")
            for f in found: f["page"] = 0
            labels += found
        deduped = H.dedupe_labels(labels, pt_per_ft=9.0)
        tags = sorted(l["tag"] for l in deduped if l["kind"] == "vav")
        self.assertEqual(tags, ["VAV-1-11", "VAV-2-12"])


class VisionVavRecountAddsAiReadTagsAlongsideOcrNeverInsteadOfIt(unittest.TestCase):
    """item 2 (5 Nov 2026): a second, independent VAV tag read -- tested
    against a real drawing's actual tiles (not this test), 33 of 48 real
    boxes found vs. RapidOCR's own measured ~31% on the same file. This
    function itself never touches the network -- `tag_reader` is a plain
    callback, built and owned entirely by addons/boq/workers.py."""

    def _fake_pdfium_doc(self, size=(4608, 2400)):
        from PIL import Image
        page = mock.Mock()
        page.render.return_value.to_pil.return_value = Image.new("RGB", size, "white")
        doc = mock.MagicMock()
        doc.__getitem__.return_value = page
        return doc

    def test_tags_from_every_tile_are_collected(self):
        # Two tiles at this page size/dpi (see _tile_bounds) -- a
        # different VAV tag "read" per tile, both must survive.
        reader = mock.Mock(side_effect=["VAV-1-2\nVAV-1-3", "VAV-2-7"])
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_pdfium_doc()):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, dpi=72)
        self.assertEqual(sorted(l["tag"] for l in labels), ["VAV-1-2", "VAV-1-3", "VAV-2-7"])
        self.assertTrue(all(l["source"] == "vision" and l["kind"] == "vav" for l in labels))

    def test_the_same_tag_read_twice_across_tiles_counts_once(self):
        # The overlap between tiles means the SAME box can land in two
        # tiles' own crops -- never two label entries for one real tag.
        reader = mock.Mock(side_effect=["VAV-1-2", "VAV-1-2"])
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_pdfium_doc()):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, dpi=72)
        self.assertEqual([l["tag"] for l in labels], ["VAV-1-2"])

    def test_non_vav_text_in_the_same_reply_is_not_kept(self):
        # A real reply reads sizes/CFM/diffuser notes too -- none of those
        # carry a real pixel position this way (see this function's own
        # docstring), so only "vav" kind survives from it.
        reader = mock.Mock(return_value="VAV-1-2\n20x12\n450CFM")
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_pdfium_doc()):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, dpi=72)
        self.assertEqual([l["kind"] for l in labels], ["vav"])

    def test_a_tile_whose_reader_call_fails_is_skipped_not_fatal(self):
        # A single bad/rate-limited API call for one tile must not lose
        # whatever the OTHER tiles already found.
        reader = mock.Mock(side_effect=[RuntimeError("HTTP 503"), "VAV-3-9"])
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_pdfium_doc()):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, dpi=72)
        self.assertEqual([l["tag"] for l in labels], ["VAV-3-9"])

    def test_no_legible_text_at_all_returns_no_labels(self):
        reader = mock.Mock(return_value="NONE")
        with mock.patch("pypdfium2.PdfDocument", return_value=self._fake_pdfium_doc()):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, dpi=72)
        self.assertEqual(labels, [])


class AhuTagAndAirflowReadTogetherFromOneNote(unittest.TestCase):
    """Found on client_2nd_sample: only AHU-01 has its CFM printed right
    beside the tag, in one note ("2000CFM AHU-01") -- AHU-02/AHU-03 do
    not, checked for real against the raw OCR text within 500pt of each
    tag. AHU_CFM_RE must never invent a figure for those two."""

    def test_tag_and_cfm_are_both_read_from_one_note(self):
        found = H.parse_label("2000CFM AHU-01", 0, 0, "text")
        self.assertEqual(found, [{"kind": "ahu", "cfm": 2000, "tag": "AHU-01",
                                  "text": "2000CFM AHU-01", "x_pt": 0, "y_pt": 0,
                                  "source": "text", "conf": 1.0}])

    def test_the_cfm_is_never_also_double_booked_as_a_generic_cfm_reading(self):
        kinds = [f["kind"] for f in H.parse_label("2000CFM AHU-01", 0, 0, "text")]
        self.assertEqual(kinds, ["ahu"])

    def test_a_bare_tag_with_no_cfm_nearby_in_the_same_note_reads_as_nothing(self):
        """AHU-02/AHU-03's own bare tag -- no invented airflow for a tag
        this format did not actually find a CFM note for."""
        self.assertEqual(H.parse_label("AHU-02", 0, 0, "text"), [])


class AhuCfmMissingALeadingDigitIsCorrectedFromANearbyReading(unittest.TestCase):
    """client_2nd_sample's own "2000CFM AHU-01" turned out to be wrong --
    confirmed by rendering the real drawing and looking: the real label is
    "12000CFM AHU-01", a thin leading "1" merged into the bold tag text
    right next to it and OCR dropped it. The SAME real value is printed a
    second time nearby, as a plain "12000 CFM" note with no tag attached,
    and that one read correctly. Never the other direction -- OCR does
    not hallucinate an extra leading digit that was never drawn -- so a
    plain CFM reading whose digits are the AHU's own reading plus one
    extra LEADING digit, sitting close by, is trusted over the tag note's
    own short reading."""

    PT_PER_FT = 9.0

    def _label(self, kind, x, y, page=0, **kw):
        d = {"kind": kind, "x_pt": x, "y_pt": y, "page": page}
        d.update(kw)
        return d

    def test_a_nearby_superset_reading_corrects_the_short_one(self):
        ahu = [self._label("ahu", 100, 100, tag="AHU-01", cfm=2000)]
        labels = [self._label("cfm", 102, 101, cfm=12000)]
        H._fix_ahu_dropped_leading_digit(ahu, labels, self.PT_PER_FT)
        self.assertEqual(ahu[0]["cfm"], 12000)
        self.assertEqual(ahu[0]["cfm_as_tagged"], 2000)
        self.assertTrue(ahu[0]["cfm_corrected"])

    def test_a_far_away_superset_reading_is_not_used(self):
        ahu = [self._label("ahu", 100, 100, tag="AHU-01", cfm=2000)]
        labels = [self._label("cfm", 100, 100 + 50 * self.PT_PER_FT, cfm=12000)]   # 50 ft away
        H._fix_ahu_dropped_leading_digit(ahu, labels, self.PT_PER_FT)
        self.assertEqual(ahu[0]["cfm"], 2000)
        self.assertNotIn("cfm_corrected", ahu[0])

    def test_a_reading_with_two_extra_digits_is_not_treated_as_the_same_number(self):
        """120000 is not a plausible "missing one digit" reading of 2000 --
        only exactly one extra leading digit counts."""
        ahu = [self._label("ahu", 100, 100, tag="AHU-01", cfm=2000)]
        labels = [self._label("cfm", 101, 100, cfm=120000)]
        H._fix_ahu_dropped_leading_digit(ahu, labels, self.PT_PER_FT)
        self.assertEqual(ahu[0]["cfm"], 2000)

    def test_a_reading_with_different_trailing_digits_is_a_real_different_number(self):
        """12500 is a real, different CFM value seen on this drawing, not
        a dropped-digit misread of 2000 -- must never be treated as one."""
        ahu = [self._label("ahu", 100, 100, tag="AHU-01", cfm=2000)]
        labels = [self._label("cfm", 101, 100, cfm=12500)]
        H._fix_ahu_dropped_leading_digit(ahu, labels, self.PT_PER_FT)
        self.assertEqual(ahu[0]["cfm"], 2000)

    def test_an_ahu_with_no_nearby_superset_reading_is_left_alone(self):
        ahu = [self._label("ahu", 100, 100, tag="AHU-02", cfm=12000)]
        H._fix_ahu_dropped_leading_digit(ahu, [], self.PT_PER_FT)
        self.assertEqual(ahu[0]["cfm"], 12000)
        self.assertNotIn("cfm_corrected", ahu[0])


class DropperScheduleKeepsEachTypesOwnQtyAndCfmSeparate(unittest.TestCase):
    """Found on client_2nd_sample: two real spellings for the same kind of
    note, "N#Dropper@NNNcfm" and "NDrop.@NNNcfm" -- both seen on the real
    file, neither a typo of the other."""

    def test_the_hash_spelling_reads_qty_and_cfm(self):
        found = H.parse_label("5# Dropper@200cfm", 0, 0, "text")
        self.assertEqual([(f["qty"], f["cfm"]) for f in found if f["kind"] == "dropper"], [(5, 200)])

    def test_the_drop_dot_spelling_also_reads_qty_and_cfm(self):
        found = H.parse_label("4Drop.@113cfm", 0, 0, "text")
        self.assertEqual([(f["qty"], f["cfm"]) for f in found if f["kind"] == "dropper"], [(4, 113)])

    def test_the_cfm_is_never_also_double_booked_as_a_generic_cfm_reading(self):
        kinds = [f["kind"] for f in H.parse_label("5# Dropper@200cfm", 0, 0, "text")]
        self.assertEqual(kinds, ["dropper"])

    def test_extract_keeps_different_types_as_separate_schedule_lines(self):
        labels = []
        for text, x, y in [("5# Dropper@200cfm", 100, 100), ("1# Dropper@250cfm", 500, 500)]:
            found = H.parse_label(text, x, y, "text")
            for f in found: f["page"] = 0
            labels += found
        deduped = H.dedupe_labels(labels, pt_per_ft=9.0)
        pairs = sorted((l["qty"], l["cfm"]) for l in deduped if l["kind"] == "dropper")
        self.assertEqual(pairs, [(1, 250), (5, 200)])


class DiscValveQtyIsReadFromItsOwnNote(unittest.TestCase):
    def test_qty_is_read(self):
        found = H.parse_label("17# FA DISC VALVE 0150", 0, 0, "text")
        self.assertEqual([f["qty"] for f in found if f["kind"] == "disc_valve"], [17])


class DiffuserScheduleIsCountOnlyNeverAGuessedCfmOrNeckJoin(unittest.TestCase):
    """Found on client_2nd_sample's own tiled OCR text, 30 Oct 2026: a
    diffuser schedule entry is THREE separate OCR fragments ("4# OVERALL
    640o SAD", "NECK DIA-400o", "450 CFM EACH"), not one combined note
    the way every OTHER pattern in this file is -- unlike those, this one
    deliberately reads only qty + overall size, and does NOT attempt to
    join the CFM or neck-size fragments by proximity, which could pair
    the wrong numbers from two schedule entries sitting close together.
    Real spelling noise covered here: the diameter symbol varies (o, 0,
    phi, Phi, %, or missing) and "OVERALL" is followed by a space, a
    hyphen, or nothing before the size."""

    def test_the_hash_spelling_reads_qty_and_overall_size(self):
        found = H.parse_label("4# OVERALL 640 SAD", 0, 0, "text")
        self.assertEqual([(f["qty"], f["overall"], f["shape"]) for f in found
                          if f["kind"] == "diffuser_schedule"], [(4, 640, "round")])

    def test_a_hyphen_between_overall_and_the_size_is_tolerated(self):
        found = H.parse_label("8 OVERALL- 445 SAD", 0, 0, "text")
        self.assertEqual([(f["qty"], f["overall"]) for f in found
                          if f["kind"] == "diffuser_schedule"], [(8, 445)])

    def test_a_missing_hash_before_overall_is_tolerated(self):
        found = H.parse_label("10# OVERALL 545 SA DIFFUSER", 0, 0, "text")
        self.assertEqual([(f["qty"], f["overall"]) for f in found
                          if f["kind"] == "diffuser_schedule"], [(10, 545)])

    def test_a_square_diffuser_note_has_no_overall_size_at_all(self):
        found = H.parse_label("4# SA SQ Diffuser", 0, 0, "text")
        self.assertEqual([(f["qty"], f["overall"], f["shape"]) for f in found
                          if f["kind"] == "diffuser_schedule"], [(4, None, "square")])

    def test_cfm_and_neck_size_are_never_invented_for_a_count_only_entry(self):
        found = H.parse_label("4# OVERALL 640 SAD", 0, 0, "text")
        entry = next(f for f in found if f["kind"] == "diffuser_schedule")
        self.assertNotIn("cfm", entry)
        self.assertNotIn("neck", entry)

    def test_extract_keeps_different_schedule_lines_separate(self):
        labels = []
        for text, x, y in [("4# OVERALL 640 SAD", 100, 100), ("12# OVERALL 445ø SAD", 500, 500)]:
            found = H.parse_label(text, x, y, "text")
            for f in found: f["page"] = 0
            labels += found
        deduped = H.dedupe_labels(labels, pt_per_ft=9.0)
        entries = sorted((l["qty"], l["overall"]) for l in deduped if l["kind"] == "diffuser_schedule")
        self.assertEqual(entries, [(4, 640), (12, 445)])


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


class TileBoundsCoversABigImageAndLeavesASmallOneAlone(unittest.TestCase):
    """Found comparing a second real tool run against client_2nd_sample,
    30 Oct 2026: a single call to the OCR engine on that drawing's full
    11702x8278px render was silently crushed by the engine's own
    `Det.limit_side_len=2880` before detection ever ran -- real labels
    came back as noise ("TC M.79 HGA2"). Splitting into tiles under that
    limit is the fix; this is the tiling arithmetic alone, no OCR call."""

    def test_an_image_already_under_the_cap_is_exactly_one_tile(self):
        self.assertEqual(H._tile_bounds(800, 600), [(0, 0, 800, 600)])

    def test_a_square_image_exactly_at_the_cap_is_one_tile(self):
        self.assertEqual(H._tile_bounds(2400, 2400), [(0, 0, 2400, 2400)])

    def test_every_tile_stays_within_the_cap_on_both_sides(self):
        for (x0, y0, x1, y1) in H._tile_bounds(11702, 8278):
            self.assertLessEqual(x1 - x0, 2400)
            self.assertLessEqual(y1 - y0, 2400)

    def test_neighbouring_tiles_overlap_rather_than_leaving_a_seam_gap(self):
        tiles = sorted(set((x0, x1) for x0, _, x1, _ in H._tile_bounds(5000, 2000)))
        for (x0, x1), (nx0, nx1) in zip(tiles, tiles[1:]):
            self.assertLess(nx0, x1)   # the next tile starts before this one ends

    def test_the_far_edge_is_actually_reached_not_just_approached(self):
        tiles = H._tile_bounds(5000, 2000)
        self.assertTrue(any(x1 == 5000 for _, _, x1, _ in tiles))


class OcrPageTilesABigRenderAndRemapsEachTilesOwnCoordinates(unittest.TestCase):
    """The tiling arithmetic alone (above) says nothing about whether a
    label found INSIDE one tile lands back at its real page position --
    this is that remapping, with a fake engine (never a real OCR model)
    returning the same canned box every call so any difference in the
    reported position can only have come from the tile offset."""

    def _fake_pdfium_doc(self, size):
        from PIL import Image
        page = mock.Mock()
        page.render.return_value.to_pil.return_value = Image.new("RGB", size, "white")
        doc = mock.MagicMock()
        doc.__getitem__.return_value = page
        return doc

    def _fake_engine_result(self, box_center=(30, 30), text="500CFM"):
        result = mock.Mock()
        half = 10
        cx, cy = box_center
        result.boxes = [[(cx - half, cy - half), (cx + half, cy - half),
                         (cx + half, cy + half), (cx - half, cy + half)]]
        result.txts = [text]
        result.scores = [0.99]
        return result

    def test_a_big_page_is_split_into_more_than_one_tile_worth_of_calls(self):
        fake_engine = mock.Mock(return_value=self._fake_engine_result())
        with mock.patch("pypdfium2.PdfDocument",
                        return_value=self._fake_pdfium_doc((6000, 4000))), \
                mock.patch.object(H, "_rapidocr_engine", return_value=fake_engine):
            H.ocr_page("/x/fake.pdf", 0, dpi=72)   # dpi=72 keeps scale=1, 6000x4000px
        self.assertGreater(fake_engine.call_count, 2)

    def test_a_label_found_in_a_later_tile_reports_a_position_past_that_tiles_own_start(self):
        # One real CFM match ("500CFM" at local (30, 30) in every tile) --
        # the tool keeps only the highest-confidence read per real spot
        # (dedupe_labels), so distinct tiles must show up as distinct
        # x_pt/y_pt, each a tile's own offset away, not one spot repeated.
        fake_engine = mock.Mock(return_value=self._fake_engine_result())
        with mock.patch("pypdfium2.PdfDocument",
                        return_value=self._fake_pdfium_doc((6000, 4000))), \
                mock.patch.object(H, "_rapidocr_engine", return_value=fake_engine):
            labels = H.ocr_page("/x/fake.pdf", 0, dpi=72)
        xs = sorted({round(l["x_pt"]) for l in labels if l["kind"] == "cfm"})
        self.assertGreater(len(xs), 1)
        self.assertEqual(xs[0], 30)             # the first tile's own local position, offset 0
        self.assertGreater(xs[-1], 2400)        # a later tile's position, past its own tile start


class _FakePage:
    """Just enough of pdfplumber's page shape for count_symbol_rects and
    count_symbol_curves -- they only ever read page.rects / page.curves."""
    def __init__(self, rects=(), curves=(), lines=()):
        self.rects = list(rects)
        self.curves = list(curves)
        self.lines = list(lines)


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


class CountSymbolRectsVolumeDamperFloorAndRaisedCapItem79(unittest.TestCase):
    """item 79, found on the client's second real sample file: that
    file's real damper mark is a long rect (one side a steady ~6pt, the
    other 15-77pt), not the small square icon the original 12pt cap was
    tuned for -- and the same real layer carries ~2pt corner-tick noise
    the floor must drop."""

    LAYER_MAP = {"#ff0000@1.08:rect": "volume_damper"}

    def test_the_real_elongated_damper_mark_is_counted(self):
        page = _FakePage([_rect(100, 100, 6.24, 76.8, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_a_tiny_corner_tick_under_the_floor_is_dropped(self):
        page = _FakePage([_rect(100, 100, 6.24, 76.8, _RED), _rect(500, 500, 2.04, 1.92, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)

    def test_a_page_border_is_still_excluded_by_the_raised_cap(self):
        page = _FakePage([_rect(100, 100, 6.24, 76.8, _RED), _rect(0, 0, 888, 1556, _RED)])
        out = H.count_symbol_rects(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)


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


class TrTagsAreNeverPresentedAsHiWallInTheSummary(unittest.TestCase):
    """Found comparing a second real tool run against client_2nd_sample,
    30 Oct 2026: the write-up agent called every bare TR tag "Hi-Wall" in
    the finished BOQ -- Hi-Wall is the only equipment TYPE word anywhere
    in this summary, so with nothing saying otherwise it filled the gap
    with that one name. summary_text() must say the type was NOT read,
    explicitly, every time there is at least one bare TR tag."""

    def _result(self, tr_labels):
        return {"source": {"file": "x.pdf", "pages": 1}, "checks": {"runs": 0, "label_match_rate": 0},
               "duct_summary": [], "tr_labels": tr_labels, "cfm_label_counts": {}, "rooms": [],
               "equipment": [], "unresolved_duct_labels": [], "warnings": [],
               "terminals": [], "accessories": []}

    def test_a_bare_tr_tag_is_marked_type_not_read(self):
        text = H.summary_text(self._result([8.0, 1.6]))
        self.assertIn("type NOT read", text)
        self.assertIn("do NOT call these Hi-Wall", text)

    def test_the_actual_values_are_still_present(self):
        text = H.summary_text(self._result([8.0, 1.6]))
        self.assertIn("8.0", text)
        self.assertIn("1.6", text)

    def test_an_empty_tr_list_still_shows_the_line_plainly(self):
        text = H.summary_text(self._result([]))
        self.assertIn("TR tags", text)
        self.assertIn("[]", text)


class SummaryTextShowsAhuVavDropperAndDiscValveWhenPresent(unittest.TestCase):
    """The write-up agent only ever sees what's in this text -- an
    aggregated field (extract()'s own ahu/vav_tags/dropper_schedule/
    disc_valve_count) that never reaches summary_text() may as well not
    exist for the BOQ. Built with .get(...) in summary_text() so an
    older/minimal result dict (without these keys, as every OTHER test
    in this file still builds one) keeps summarising instead of
    KeyError-ing -- checked here by the base dict carrying none of them."""

    def _result(self, **extra):
        base = {"source": {"file": "x.pdf", "pages": 1}, "checks": {"runs": 0, "label_match_rate": 0},
               "duct_summary": [], "tr_labels": [], "cfm_label_counts": {}, "rooms": [],
               "equipment": [], "unresolved_duct_labels": [], "warnings": [],
               "terminals": [], "accessories": []}
        base.update(extra)
        return base

    def test_a_result_dict_with_none_of_the_new_fields_still_summarises(self):
        H.summary_text(self._result())   # must not raise

    def test_ahu_shows_tag_and_cfm_together(self):
        text = H.summary_text(self._result(ahu=[{"tag": "AHU-01", "cfm": 2000}]))
        self.assertIn("AHU-01", text)
        self.assertIn("2000 CFM", text)

    def test_a_corrected_ahu_cfm_says_so_and_shows_both_numbers(self):
        """extract()'s own _fix_ahu_dropped_leading_digit() can correct a
        reading -- summary_text() must never hide that a number changed,
        the same standing rule as every other correction in this file."""
        text = H.summary_text(self._result(
            ahu=[{"tag": "AHU-01", "cfm": 12000, "cfm_as_tagged": 2000}]))
        self.assertIn("12000 CFM", text)
        self.assertIn("corrected", text.lower())
        self.assertIn("2000 CFM", text)   # the wrong, as-tagged figure is still shown, not erased

    def test_vav_shows_a_count_not_the_tags_and_warns_about_the_size_code_lookalike(self):
        text = H.summary_text(self._result(vav_tags=["VAV-1-11", "VAV-2-12", "VAV-3-19"]))
        self.assertIn("3 distinct tags", text)
        self.assertIn("VAV-150", text)   # the lookalike warning, named explicitly

    def test_vav_count_is_explicitly_called_a_lower_bound_not_a_final_count(self):
        """item 1 (4 Nov 2026): a real job's own client-side comparison
        found 15 tags read against 48 real VAV boxes (31%) -- not a
        VAV_RE bug (already verified correct for that exact drawing), an
        OCR recall gap: a box whose tag never reads cleanly is simply
        never counted. A reader of this summary alone, without having
        seen that finding, had no way to know "15" was a floor rather
        than a final count."""
        text = H.summary_text(self._result(vav_tags=["VAV-1-11"]))
        self.assertIn("LOWER BOUND", text)
        self.assertIn("overlay", text.lower())

    def test_ai_tag_recheck_adds_a_note_only_when_the_setting_says_it_ran(self):
        """item 2 (5 Nov 2026): the "lower bound" wording above is never
        dropped just because an AI tag re-check also ran -- it's still a
        read, not a count of the real boxes -- but a reader should be
        told the AI pass is already folded into the one number shown."""
        with_ai = H.summary_text(self._result(
            vav_tags=["VAV-1-11"], settings={"ai_tag_recheck": True}))
        self.assertIn("LOWER BOUND", with_ai)
        self.assertIn("AI tag re-check", with_ai)

        without_ai = H.summary_text(self._result(
            vav_tags=["VAV-1-11"], settings={"ai_tag_recheck": False}))
        self.assertIn("LOWER BOUND", without_ai)
        self.assertNotIn("AI tag re-check", without_ai)

        no_settings_at_all = H.summary_text(self._result(vav_tags=["VAV-1-11"]))
        self.assertNotIn("AI tag re-check", no_settings_at_all)

    def test_dropper_schedule_keeps_each_type_on_its_own_line(self):
        text = H.summary_text(self._result(dropper_schedule=[{"qty": 5, "cfm": 200}, {"qty": 1, "cfm": 250}]))
        self.assertIn("5 x @200 CFM", text)
        self.assertIn("1 x @250 CFM", text)

    def test_disc_valve_count_is_shown(self):
        text = H.summary_text(self._result(disc_valve_count=27))
        self.assertIn("27", text)
        self.assertIn("disc valve", text.lower())

    def test_a_zero_disc_valve_count_is_not_shown_as_a_false_line(self):
        text = H.summary_text(self._result(disc_valve_count=0))
        self.assertNotIn("disc valve", text.lower())

    def test_diffuser_schedule_shows_qty_and_size_but_warns_against_guessing_cfm(self):
        text = H.summary_text(self._result(diffuser_schedule=[
            {"qty": 4, "overall": 640, "shape": "round"}, {"qty": 2, "overall": None, "shape": "square"}]))
        self.assertIn("4 x round, overall 640", text)
        self.assertIn("2 x square", text)
        self.assertIn("NOT joined here", text)


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

    def test_a_tiny_hatch_fragment_under_the_floor_is_dropped(self):
        """item 79: a real named layer can carry hatch-fill fragments far
        smaller than the damper's own tested mark (4.4 x 36pt) -- these
        must never be counted as a second, separate damper."""
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0),
                                 _curve(200, 200, 1.6, 0.2)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "volume_damper")
        self.assertEqual(len(out), 1)


class CountSymbolCurvesRequiresASquareBoxForADiffuserItem79(unittest.TestCase):
    """item 79, found on the client's second real sample file: a diffuser
    icon's real OCG layer also carries direction-arrow ticks (~5x14pt,
    never square) and hatch fragments (2.5-4.7pt, far below any real
    icon) -- diffuser's own real icon (round or square) is always
    bbox-square, which volume_damper's bowtie mark never needs to be."""

    LAYER_MAP = {"#00ffff@0.84:poly": "diffuser"}

    def test_a_square_curve_above_the_floor_is_counted(self):
        page = _FakePage(curves=[_curve(100, 100, 10.4, 10.4)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "diffuser")
        self.assertEqual(len(out), 1)

    def test_a_long_thin_tick_mark_is_excluded(self):
        page = _FakePage(curves=[_curve(100, 100, 5.3, 14.3)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "diffuser")
        self.assertEqual(out, [])

    def test_a_tiny_hatch_fragment_is_excluded_even_if_square(self):
        page = _FakePage(curves=[_curve(100, 100, 2.5, 2.5)])
        out = H.count_symbol_curves(page, self.LAYER_MAP, "diffuser")
        self.assertEqual(out, [])

    def test_volume_damper_itself_is_never_held_to_the_square_rule(self):
        page = _FakePage(curves=[_curve(100, 100, 4.4, 36.0)])
        out = H.count_symbol_curves(page, {"#00ffff@0.84:poly": "volume_damper"}, "volume_damper")
        self.assertEqual(len(out), 1)


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


class DuctSizesAreReadInEitherInchesOrMillimetres(unittest.TestCase):
    """Root cause of client_2nd_sample's own 0% label-match, found 30 Oct
    2026, AFTER the OCR tiling fix and the equipment fixes in this same
    item already found everything else on the sheet correctly: this
    drawing writes duct sizes in millimetres ("550x300", "1000x88"...),
    and the old `2 <= w <= 120` check -- written for inches, where no
    duct is ever 550 wide -- silently rejected every single one. Not a
    wrong scale (item 33/35's own earlier suspicion); a wrong assumed
    unit. General on purpose: this affects ANY metric-convention HVAC
    drawing run through this tool, not only this one file -- the fix
    lives in parse_label() itself, not in anything keyed to this
    drawing's name or its layer map."""

    def test_a_small_pair_is_read_as_inches_unchanged(self):
        labels = H.parse_label("12x8", 0, 0, "text")
        size = next(l for l in labels if l["kind"] == "size")
        self.assertEqual((size["w_in"], size["d_in"], size["unit_read"]), (12, 8, "in"))

    def test_a_millimetre_pair_is_converted_to_inches(self):
        labels = H.parse_label("550x300", 0, 0, "text")
        size = next(l for l in labels if l["kind"] == "size")
        self.assertEqual(size["unit_read"], "mm")
        self.assertAlmostEqual(size["w_in"], 21.7, places=1)
        self.assertAlmostEqual(size["d_in"], 11.8, places=1)
        self.assertEqual((size["w_mm"], size["d_mm"]), (550, 300))

    def test_a_four_digit_millimetre_width_is_not_truncated_to_its_last_three_digits(self):
        """`\\d{1,3}` matched "1000x88" as "000"x"88" (0in wide) the same
        way the old TR_RE truncated "2.07" to "07" -- \\d{1,4} fixes both
        at once."""
        labels = H.parse_label("1000x88", 0, 0, "text")
        size = next(l for l in labels if l["kind"] == "size")
        self.assertAlmostEqual(size["w_in"], 39.4, places=1)

    def test_a_pair_too_large_for_either_convention_is_not_invented_as_a_size(self):
        labels = H.parse_label("5000x9000", 0, 0, "text")
        self.assertEqual([l for l in labels if l["kind"] == "size"], [])

    def test_a_millimetre_size_actually_pairs_with_duct_geometry(self):
        """The point of the fix: split_by_labels() already matches a
        label's own w_in against the run's geometrically-measured width
        -- it was never broken, it was being handed nothing. A run
        measured at ~21.7in wide (550mm) must now find this label."""
        sizes = H.parse_label("550x300", 100, 100, "text")
        run = {"orientation": "H", "width_in": 21.7, "pt": (0, 100, 500, 100)}
        pieces = H.split_by_labels(run, sizes, pt_per_ft=9.0, match_ft=8)
        self.assertIsNotNone(pieces[0]["label"])
        self.assertEqual(pieces[0]["label"], "21.7x11.8")


class TwoDecimalDigitTrValuesAreReadWholeNotTruncated(unittest.TestCase):
    """Found comparing a second real tool run against client_2nd_sample,
    30 Oct 2026: every "2.07 TR" on that drawing came out as 7.0, and one
    "0.8 TR" (split by a stray mid-number space the PDF's own text
    extraction produced, "0. 8 TR") came out as 8.0. Both are the same
    bug: the old TR_RE/HIWALL_RE only allowed ONE digit after the decimal
    point, so a second decimal digit, or a digit separated from its dot
    by a space, made the match fail at the real start of the number and
    backtrack onto just its tail end -- "07" read as a bare 7.0."""

    def test_two_decimal_digits_are_kept_not_truncated_to_the_tail_digit(self):
        labels = H.parse_label("2.07 TR", 0, 0, "text")
        self.assertEqual([l["tr"] for l in labels if l["kind"] == "tr"], [2.07])

    def test_a_stray_space_inside_the_number_does_not_strand_the_tail_digit(self):
        labels = H.parse_label("0. 8 TR", 0, 0, "text")
        self.assertEqual([l["tr"] for l in labels if l["kind"] == "tr"], [0.8])

    def test_the_same_fix_applies_to_a_hi_wall_tagged_capacity(self):
        labels = H.parse_label("2.07 TR HI-WALL", 0, 0, "text")
        equip = [l for l in labels if l["kind"] == "equipment"]
        self.assertEqual([e["capacity_tr"] for e in equip], [2.07])

    def test_a_clean_single_decimal_digit_is_unaffected(self):
        labels = H.parse_label("1.6TR", 0, 0, "text")
        self.assertEqual([l["tr"] for l in labels if l["kind"] == "tr"], [1.6])

    def test_a_whole_number_tr_is_unaffected(self):
        labels = H.parse_label("17 TR", 0, 0, "text")
        self.assertEqual([l["tr"] for l in labels if l["kind"] == "tr"], [17.0])


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


class LayerKeyIsNeverChangedByACarriedOcgNameItem74(unittest.TestCase):
    """item 74 (12 Nov 2026), found thinking it through before shipping,
    not live: a saved layer_map.json is keyed entirely on layer_key()'s
    own colour@weight:kind output. If layer_key() started returning a
    name-based key the moment an object carried "ocg_name" (real CAD
    layer names, read off a PDF's own Optional Content Groups), every
    already-correct, already-saved colour-keyed mapping would silently
    stop matching the first time that exact PDF was reopened -- a role
    quietly falling through to "ignore" with nothing telling anyone why.
    layer_key() must stay colour-only, unconditionally, forever; the new
    name-based lookup lives ONLY in layer_display_key()/resolve_role()."""

    def test_an_object_carrying_ocg_name_still_gets_the_old_colour_key(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        obj["ocg_name"] = "ACME-HVAC-Exhaust Air Duct"
        self.assertEqual(H.layer_key(obj, "rect"), "#ff0000@1.08:rect")

    def test_layer_display_key_shows_the_real_name_when_present(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        obj["ocg_name"] = "ACME-HVAC-Exhaust Air Duct"
        self.assertEqual(H.layer_display_key(obj, "rect"),
                        "[ACME-HVAC-Exhaust Air Duct]")

    def test_layer_display_key_falls_back_to_the_colour_key_with_no_name(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        self.assertEqual(H.layer_display_key(obj, "rect"), H.layer_key(obj, "rect"))


class ResolveRoleTriesTheNameBeforeFallingBackToColourItem74(unittest.TestCase):
    """The one place a real layer_map is actually consulted for a role,
    from item 74 on -- every real caller (extract()'s own duct-wall
    loop, count_symbol_rects(), count_symbol_curves()) uses this, not a
    bare `layer_map.get(layer_key(...), "ignore")`."""

    def test_an_existing_colour_only_layer_map_keeps_working_unchanged(self):
        """The regression this whole item exists to prevent: a real,
        already-saved layer_map.json has no "[name]" keys in it at all."""
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        obj["ocg_name"] = "ACME-HVAC-Exhaust Air Duct"
        layer_map = {"#ff0000@1.08:rect": "return"}
        self.assertEqual(H.resolve_role(obj, "rect", layer_map), "return")

    def test_a_name_based_mapping_wins_over_a_colour_based_one(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        obj["ocg_name"] = "ACME-HVAC-Exhaust Air Duct"
        layer_map = {"#ff0000@1.08:rect": "return",
                    "[ACME-HVAC-Exhaust Air Duct]": "toilet_exhaust"}
        self.assertEqual(H.resolve_role(obj, "rect", layer_map), "toilet_exhaust")

    def test_a_name_with_no_matching_entry_falls_back_to_the_colour_key(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        obj["ocg_name"] = "Some Other Layer"
        layer_map = {"#ff0000@1.08:rect": "return"}
        self.assertEqual(H.resolve_role(obj, "rect", layer_map), "return")

    def test_no_name_and_no_colour_match_is_ignore(self):
        obj = _rect(0, 0, 10, 10, color=_RED, lw=1.08)
        self.assertEqual(H.resolve_role(obj, "rect", {}), "ignore")


class OcgPageFallsBackToTheRealPageWhenNothingIsTagged(unittest.TestCase):
    """_OcgPage must never leave a caller with no geometry at all just
    because tagged_page_objects() found nothing to tag -- the ordinary
    case for a flattened PDF export with no layer data in it."""

    def test_empty_tagged_objects_falls_back_to_the_wrapped_pages_own_geometry(self):
        fake_page = _FakePage(rects=[_rect(0, 0, 5, 5)], curves=[_curve(0, 0, 4, 4)])
        fake_page.lines = []
        with mock.patch.object(H, "tagged_page_objects", return_value=([], [], [])):
            wrapped = H._OcgPage(fake_page, "/x/does/not/matter.pdf", 0)
            self.assertEqual(wrapped.rects, fake_page.rects)
            self.assertEqual(wrapped.curves, fake_page.curves)

    def test_a_non_empty_tagged_result_is_used_instead_of_the_wrapped_page(self):
        fake_page = _FakePage(rects=[_rect(0, 0, 5, 5)])
        tagged_rect = _rect(1, 1, 9, 9)
        tagged_rect["ocg_name"] = "ACME-HVAC-Exhaust Air Duct"
        with mock.patch.object(H, "tagged_page_objects",
                              return_value=([], [tagged_rect], [])):
            wrapped = H._OcgPage(fake_page, "/x/does/not/matter.pdf", 0)
            self.assertEqual(wrapped.rects, [tagged_rect])

    def test_other_attributes_pass_through_to_the_wrapped_page(self):
        fake_page = _FakePage()
        fake_page.width = 3370
        wrapped = H._OcgPage(fake_page, "/x/does/not/matter.pdf", 0)
        self.assertEqual(wrapped.width, 3370)


class SuggestRoleFromNameReadsTheLayersOwnWordsItem76(unittest.TestCase):
    """item 76, the owner's own reaction to item 74 landing with every
    real layer name still defaulted to "ignore": "we have to manually do
    it". A real CAD layer name is usually already plain English -- this
    reads it instead of asking a person to. Every name here is a REAL
    one found on the same real client file item 74/75 were built and
    verified against, not invented for the test."""

    def test_the_real_supply_duct_layer_suggests_supply(self):
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-Supply Air Duct"), "supply")

    def test_the_real_return_duct_layer_suggests_return(self):
        self.assertEqual(
            H.suggest_role_from_name("PLAN_01_ACME-HVAC-Return Air Duct"),
            "return")

    def test_the_real_exhaust_duct_layer_suggests_exhaust(self):
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-Exhaust Air Duct"), "exhaust")

    def test_a_name_naming_both_toilet_and_exhaust_suggests_the_narrower_role(self):
        """Not on the real file (its own exhaust layer never says
        "toilet") -- generalised for a drawing whose drafter did write
        the specific branch into the layer name."""
        self.assertEqual(H.suggest_role_from_name("M-HVAC-Toilet Exhaust Duct"),
                        "toilet_exhaust")

    def test_the_real_damper_layer_suggests_volume_damper(self):
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-DAMPER"), "volume_damper")

    def test_the_real_flex_duct_layer_suggests_flex_connector(self):
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-FLEX.DUCT"), "flex_connector")

    def test_a_diffuser_layer_wins_over_the_word_supply_in_the_same_name(self):
        """"ACME-HVAC-Supply Air Diffuser" contains both "supply" and
        "diffuser" -- the diffuser is the real, narrower answer, found
        live: a naive first-match-wins order would have suggested
        "supply" for the one layer item 74/75 actually needed as
        "diffuser"."""
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-Supply Air Diffuser"),
                        "diffuser")

    def test_a_text_annotation_layer_is_never_suggested_a_geometry_role(self):
        """"ACME-HVAC-Exhaust Air Duct Text" is a real layer on the same
        real file -- label text, not duct-wall geometry, despite
        containing "exhaust" just as plainly as the real duct layer."""
        self.assertIsNone(H.suggest_role_from_name("ACME-HVAC-Exhaust Air Duct Text"))

    def test_a_cfm_note_layer_with_a_typo_is_never_suggested_supply(self):
        """"ACME-HVAC-Suppil air cfm" -- a real, typo'd layer name on the
        same real file. Still correctly excluded, by "cfm" alone, not by
        the typo breaking a "supply" match it would otherwise have won."""
        self.assertIsNone(H.suggest_role_from_name("ACME-HVAC-Suppil air cfm"))

    def test_a_layer_with_no_recognisable_system_word_suggests_nothing(self):
        # item 80 changed this rule on purpose: "ACME-HVAC-VAV" used to
        # be asserted None here, when nothing could count a VAV layer.
        # It now suggests "vav_box" (see the item 80 class below).
        self.assertIsNone(H.suggest_role_from_name("ACME-HVAC-Grille"))
        self.assertIsNone(H.suggest_role_from_name("ACME-HVAC-Z Piece"))

    def test_no_name_at_all_suggests_nothing(self):
        self.assertIsNone(H.suggest_role_from_name(None))
        self.assertIsNone(H.suggest_role_from_name(""))


if __name__ == "__main__":
    unittest.main()


class VavBoxesAreCountedAsDrawnBlocksItem80(unittest.TestCase):
    """13 Nov 2026, the client's second real sample file: the same
    drawing read 42, 38 and 34 VAV tags on three runs against 48 real
    boxes. Its own "ACME-HVAC-VAV" layer, grouped into touching
    clusters, gives 49 every time."""

    LAYER_MAP = {"#ff0000@1.08:rect": "vav_box", "#ff0000@1.08:line": "vav_box"}

    def _box(self, x, y):
        """An outline rect plus two inner marks, the way one block draws."""
        return [_rect(x, y, 38, 15, _RED), _rect(x + 4, y + 3, 10, 8, _RED),
                _rect(x + 20, y + 3, 10, 8, _RED)]

    def test_one_block_of_several_primitives_counts_once(self):
        page = _FakePage(self._box(100, 100))
        self.assertEqual(len(H.count_symbol_clusters(page, self.LAYER_MAP, "vav_box")), 1)

    def test_two_separate_blocks_count_twice(self):
        page = _FakePage(self._box(100, 100) + self._box(400, 300))
        self.assertEqual(len(H.count_symbol_clusters(page, self.LAYER_MAP, "vav_box")), 2)

    def test_a_stray_tick_and_a_page_wide_shape_are_not_boxes(self):
        page = _FakePage(self._box(100, 100) + [_rect(600, 600, 2, 2, _RED),
                                                _rect(0, 900, 2000, 5, _RED)])
        self.assertEqual(len(H.count_symbol_clusters(page, self.LAYER_MAP, "vav_box")), 1)

    def test_geometry_on_another_layer_is_ignored(self):
        page = _FakePage(self._box(100, 100) + [_rect(400, 300, 38, 15, _CYAN, lw=0.84)])
        self.assertEqual(len(H.count_symbol_clusters(page, self.LAYER_MAP, "vav_box")), 1)

    def test_the_real_vav_layer_name_suggests_vav_box(self):
        self.assertEqual(H.suggest_role_from_name("ACME-HVAC-VAV"), "vav_box")

    def test_vav_wiring_and_text_layers_never_suggest_vav_box(self):
        for name in ("M HVAC VAV LOOPING CABLE-1", "M HVAC VAV POWER POINT",
                     "ACME-HVAC-VAV TEXT."):
            with self.subTest(name=name):
                self.assertIsNone(H.suggest_role_from_name(name))

    def test_a_smoke_detector_layer_is_never_suggested_as_smoke_extract_duct(self):
        self.assertIsNone(H.suggest_role_from_name(
            "FAS-Smoke Detector.FAS_Pen_No__204"))
        self.assertEqual(H.suggest_role_from_name("Smoke Extract Duct"), "smoke_extract")

    def test_vav_box_is_a_real_role_and_never_paired_as_duct_wall(self):
        self.assertIn("vav_box", H.ROLES)
        self.assertIn("vav_box", H.CLUSTER_ROLES)

    def test_the_summary_names_the_shape_count_as_the_quantity(self):
        res = {"source": {"file": "x.pdf", "pages": 1}, "duct_summary": [],
               "checks": {"runs": 0, "label_match_rate": 0}, "tr_labels": [],
               "cfm_label_counts": {}, "rooms": [], "warnings": [], "terminals": [],
               "accessories": [], "equipment": [], "unresolved_duct_labels": [],
               "settings": {},
               "vav_boxes": [{"page": 0}] * 49, "vav_tags": ["VAV-1-1"]}
        text = H.summary_text(res)
        self.assertIn("VAV BOXES COUNTED BY SHAPE: 49", text)


class ARememberedColourSuggestsARoleForAnUnnamedPurposeLayerItem80(unittest.TestCase):
    """13 Nov 2026: return duct fell from 16.5 ft to 4.9 ft on the same
    drawing -- the geometry one remembered colour ("#ff0000@1.08:line" ->
    return) used to pick up sat inside the real layer "ACME-HVAC-Z
    Piece", which no name hint matches."""

    SAVED = {"#ff0000@1.08:line": "return", "#808080@0.72:line": "ignore",
             "#000000@1.56:line": "supply"}

    def test_the_remembered_role_is_suggested(self):
        keys = {"#808080@0.72:line": 3000.0, "#ff0000@1.08:line": 870.0}
        self.assertEqual(H.suggest_role_from_colours(keys, self.SAVED), "return")

    def test_the_role_with_more_length_wins(self):
        keys = {"#000000@1.56:line": 5000.0, "#ff0000@1.08:line": 870.0}
        self.assertEqual(H.suggest_role_from_colours(keys, self.SAVED), "supply")

    def test_only_ignored_or_unknown_colours_suggest_nothing(self):
        self.assertIsNone(H.suggest_role_from_colours({"#808080@0.72:line": 3000.0}, self.SAVED))
        self.assertIsNone(H.suggest_role_from_colours({"#123456@1:line": 10.0}, self.SAVED))
        self.assertIsNone(H.suggest_role_from_colours(None, self.SAVED))
        self.assertIsNone(H.suggest_role_from_colours({"#ff0000@1.08:line": 1.0}, {}))


class AnAiTagTileThatFailsIsRetriedAndCountedItem80(unittest.TestCase):
    """A tile whose AI read raised used to be skipped with no trace --
    its tags silently missing from the VAV count."""

    def _run(self, reader):
        fake_img = mock.MagicMock()
        fake_img.size = (100, 100)
        fake_img.crop.return_value.save = lambda buf, format: buf.write(b"png")
        fake_pdf = mock.MagicMock()
        fake_pdf.__getitem__.return_value.render.return_value.to_pil.return_value.convert.return_value = fake_img
        stats = {"tiles": 0, "failed": 0}
        with mock.patch("pypdfium2.PdfDocument", return_value=fake_pdf):
            labels = H.vision_vav_recount("/x/fake.pdf", 0, reader, log=lambda *a: None, stats=stats)
        return labels, stats

    def test_a_tile_that_fails_once_is_read_on_the_second_try(self):
        calls = []
        def reader(png):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("network")
            return "VAV-1-11"
        labels, stats = self._run(reader)
        self.assertEqual([l["tag"] for l in labels], ["VAV-1-11"])
        self.assertEqual(stats, {"tiles": 1, "failed": 0})

    def test_a_tile_that_fails_twice_is_counted_as_failed(self):
        def reader(png):
            raise RuntimeError("network")
        labels, stats = self._run(reader)
        self.assertEqual(labels, [])
        self.assertEqual(stats, {"tiles": 1, "failed": 1})

