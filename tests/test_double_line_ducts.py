"""HVAC_DRAWING_RULES.md rule 1: a duct, pipe or cable tray is very often
drawn as its two edges (its real width, to scale), not one centreline.

Found 22 Oct 2026 on a real client HVAC test file: Prism's own measurement
said the supply duct was 78.82 m. The real route is 38.80 m (confirmed
independently, by giving an AI the actual drawing — the thing Prism's own
"the drawing never touches an AI" design exists specifically to avoid
needing). Root cause, traced in the raw DXF: the duct was drawn as two
parallel lines 800 mm apart; `core.boq.measure()` summed every line on the
layer, so it counted both edges as if they were two separate ducts.

The drawing here is built with ezdxf in a temp folder; nothing real is read
and nothing is sent anywhere.
"""
from __future__ import annotations

import math
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


def _dxf(path: str, build):
    doc = ezdxf.new("R2018")
    doc.header["$INSUNITS"] = 4          # millimeters, same as the real file
    msp = doc.modelspace()
    build(msp)
    doc.saveas(path)


def _tmp() -> str:
    return os.path.join(tempfile.mkdtemp(prefix="prism-duct-"), "d.dxf")


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class ADoubleLineDuctIsOneRunNotTwo(unittest.TestCase):

    def test_two_parallel_equal_edges_count_as_one_run(self):
        """The simple case: one straight duct run, 4000 mm long, 600 mm
        wide, both edges plus the two end caps that close it visually."""
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (4000, 0), dxfattribs={"layer": "M-DUCT"})
            msp.add_line((0, 600), (4000, 600), dxfattribs={"layer": "M-DUCT"})
            msp.add_line((0, 0), (0, 600), dxfattribs={"layer": "M-DUCT"})
            msp.add_line((4000, 0), (4000, 600), dxfattribs={"layer": "M-DUCT"})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        # Not 8000 (both edges) and not 9200 (both edges + both caps) —
        # one run's length, the caps excluded as closing geometry.
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT"], 4000.0, delta=1)
        self.assertTrue(any("M-DUCT" in n and "one run" in n for n in q["notes"]))

    def test_the_real_client_drawing_measures_correctly(self):
        """The exact branched supply-duct geometry from the real 22 Oct
        2026 test file (trunk + four branches + two end caps per branch,
        plus the tapering reducer piece at the trunk's far end) —
        reconstructed here so the fix this bug needs is pinned for good,
        without keeping a client's real file in the test suite. Prism's
        own buggy reading was 78,819.8 mm; an AI reading the real drawing
        directly measured 38.80 m.

        23 Oct 2026: rule 2 (HVAC_DRAWING_RULES.md) stopped counting the
        reducer's two converging sides in full (1,019.8 mm) and counts the
        transition once (509.9 mm) instead, moving this test's own expected
        figure from 38,320 mm down to 37,810 mm -- closer to the real
        38.80 m, not further from it. Changed here, in the same commit as
        the fix, with the reason stated plainly, per the project's own
        rule about changing a test alongside the behaviour it pins."""
        path = _tmp()

        def build(msp):
            L = "M-DUCT-SUPPLY"
            # trunk, two edges 800 apart
            for y in (7400, 6600):
                msp.add_line((4000, y), (7800, y), dxfattribs={"layer": L})
                msp.add_line((8200, y), (12800, y), dxfattribs={"layer": L})
                msp.add_line((13200, y), (15000, y), dxfattribs={"layer": L})
            msp.add_line((15500, 7300), (17800, 7300), dxfattribs={"layer": L})
            msp.add_line((15500, 6700), (17800, 6700), dxfattribs={"layer": L})
            # the tapering reducer at the trunk's far end -- NOT parallel
            # (the two sides converge), so this must stay unpaired
            msp.add_line((15000, 7400), (15500, 7300), dxfattribs={"layer": L})
            msp.add_line((15000, 6600), (15500, 6700), dxfattribs={"layer": L})
            # four branches, two edges 400 apart, plus their end caps
            for x0, x1, y0, y1 in ((7800, 8200, 7400, 11500),
                                   (7800, 8200, 6600, 2500),
                                   (12800, 13200, 7400, 11500),
                                   (12800, 13200, 6600, 2500)):
                msp.add_line((x0, y0), (x0, y1), dxfattribs={"layer": L})
                msp.add_line((x1, y0), (x1, y1), dxfattribs={"layer": L})
                msp.add_line((x0, y1), (x1, y1), dxfattribs={"layer": L})
            # the fifth branch, 400 wider (17800/18200)
            for y0, y1 in ((7300, 11500), (6700, 2500)):
                msp.add_line((17800, y0), (17800, y1), dxfattribs={"layer": L})
                msp.add_line((18200, y0), (18200, y1), dxfattribs={"layer": L})
                msp.add_line((17800, y1), (18200, y1), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        length = q["lengths_by_layer"]["M-DUCT-SUPPLY"]
        # Within a metre of the AI's own independent reading of the real
        # drawing (38.80 m) -- nowhere near the old, buggy 78.82 m. The
        # reducer is correctly left unpaired by rule 1 (its sides converge,
        # not parallel) and then correctly counted ONCE by rule 2, not
        # twice -- 37,809.9 mm, not 38,320 mm (rule 2 landed) or 78,819.8
        # (the original bug).
        self.assertAlmostEqual(length, 37810, delta=100)
        self.assertLess(length, 50000)


class ASingleLineRunIsUntouched(unittest.TestCase):
    """The ordinary, far more common case: one centreline, no second edge
    to find -- must measure exactly as it always did."""

    def test_one_line_on_its_own_layer_keeps_its_full_length(self):
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (22000, 1000), dxfattribs={"layer": "M-DUCT-RETURN"})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertAlmostEqual(
            q["lengths_by_layer"]["M-DUCT-RETURN"],
            boq._dist((0, 0), (22000, 1000)), delta=0.01)
        self.assertEqual(q["notes"], [])


class TwoSeparatePipesOnSeparateLayersAreNeverMergedIntoOne(unittest.TestCase):
    """A flow pipe and a return pipe are often the same length and run
    close together, parallel, right beside each other -- exactly what a
    duct's two edges look like. The only thing telling them apart is that
    the drawing puts them on two different layers, which is also the
    convention every other part of this module already relies on."""

    def test_same_length_parallel_lines_on_different_layers_both_count_in_full(self):
        path = _tmp()

        def build(msp):
            msp.add_line((-3000, 6400), (1000, 6400),
                        dxfattribs={"layer": "M-PIPE-CHW-S"})
            msp.add_line((-3000, 7600), (1000, 7600),
                        dxfattribs={"layer": "M-PIPE-CHW-R"})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertAlmostEqual(q["lengths_by_layer"]["M-PIPE-CHW-S"], 4000.0, delta=1)
        self.assertAlmostEqual(q["lengths_by_layer"]["M-PIPE-CHW-R"], 4000.0, delta=1)
        self.assertEqual(q["notes"], [])


class ARoomsOppositeWallsAreNeverReadAsOneDuct(unittest.TestCase):
    """Caught live building the real fix: a 24 m x 14 m room's opposite
    walls are a similar length and a similar distance apart too (ratio
    14/24 = 0.58), and very nearly got read as one 24 m "duct" before the
    offset/length threshold was tightened from 0.6 to 0.5. A wall is a
    thin strip only in the sense that it has thickness; it is never close
    to as wide as a room is long, which a genuine duct/pipe/tray always
    is."""

    def test_a_large_rectangular_room_keeps_its_real_perimeter(self):
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (24000, 0), dxfattribs={"layer": "A-WALL"})
            msp.add_line((24000, 0), (24000, 14000), dxfattribs={"layer": "A-WALL"})
            msp.add_line((24000, 14000), (0, 14000), dxfattribs={"layer": "A-WALL"})
            msp.add_line((0, 14000), (0, 0), dxfattribs={"layer": "A-WALL"})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertAlmostEqual(q["lengths_by_layer"]["A-WALL"], 76000.0, delta=1)
        self.assertEqual(q["notes"], [])


class TheRuleOnlyAppliesWhenHvacIsAskedFor(unittest.TestCase):
    """The owner's own instruction, 22 Oct 2026: HVAC_DRAWING_RULES.md's
    rules are trade-specific, verified against HVAC drawings specifically
    -- apply them only when the person's own request actually says "HVAC",
    never by default and never by guessing from the drawing's own layer
    names. `measure(..., hvac=False)` (the default) must behave exactly
    as it did before rule 1 existed, double-counted duct and all; only
    `hvac=True` turns the rule on."""

    def _duct_dxf(self) -> str:
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (4000, 0), dxfattribs={"layer": "M-DUCT"})
            msp.add_line((0, 600), (4000, 600), dxfattribs={"layer": "M-DUCT"})

        _dxf(path, build)
        return path

    def test_hvac_false_the_default_keeps_the_old_un_collapsed_reading(self):
        q = boq.measure(self._duct_dxf())
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT"], 8000.0, delta=1)
        self.assertEqual(q["notes"], [])

    def test_hvac_true_applies_rule_1(self):
        q = boq.measure(self._duct_dxf(), hvac=True)
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT"], 4000.0, delta=1)
        self.assertTrue(q["notes"])

    # The BoqDialog-level wiring ("hvac" typed in the ask box turns this
    # on, nothing else does) is tested in tests/test_boq_dialog.py::
    # TheHvacFlagComesOnlyFromTheAskBox -- that file already has the
    # QApplication + BoqDialog setup this needs.


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class ATaperingTransitionCountsOnceNotTwice(unittest.TestCase):
    """HVAC_DRAWING_RULES.md rule 2, 23 Oct 2026: a reducer is drawn as two
    short lines that CONVERGE (not parallel), so rule 1's own pairing
    correctly leaves them unmatched -- but the original code then summed
    both diagonals in full, double-counting the transition by about its
    own length. Found re-verifying rule 1's own fix against an independent
    reading of the same real file: Prism's rule-1 total (38,319.8 mm) was
    still off by the reducer's own length from the true 38.80 m."""

    def test_two_converging_lines_between_two_pairs_count_once(self):
        path = _tmp()

        def build(msp):
            L = "M-DUCT"
            # an 800-wide run, a 500mm reducer, then a 600-wide run --
            # the minimal shape rule 2 exists for.
            msp.add_line((0, 400), (5000, 400), dxfattribs={"layer": L})
            msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": L})
            msp.add_line((5500, 300), (9000, 300), dxfattribs={"layer": L})
            msp.add_line((5500, 100), (9000, 100), dxfattribs={"layer": L})
            msp.add_line((5000, 400), (5500, 300), dxfattribs={"layer": L})
            msp.add_line((5000, 0), (5500, 100), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        # 5000 (800-wide run) + 509.9 (the reducer's own diagonal length,
        # hypot(500, 100), counted once) + 3500 (600-wide run) = 9009.9 --
        # not 9519.8 (that same diagonal counted on both its sides).
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT"], 9009.9, delta=1)
        self.assertTrue(any("tapering transition" in n for n in q["notes"]))

    def test_an_unrelated_long_diagonal_elsewhere_is_never_mistaken_for_one(self):
        """A transition must be no longer than the widest confirmed pair on
        the layer -- an ordinary long diagonal duct run (its own, genuine
        single line, nothing to pair or transition with) stays a plain
        single length, untouched."""
        path = _tmp()

        def build(msp):
            L = "M-DUCT"
            msp.add_line((0, 400), (3000, 400), dxfattribs={"layer": L})
            msp.add_line((0, 0), (3000, 0), dxfattribs={"layer": L})
            # a long diagonal, far longer than the 400-wide pair above --
            # must stay a single, full-length run, not a "transition"
            msp.add_line((10000, 10000), (20000, 15000), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        diag = math.hypot(20000 - 10000, 15000 - 10000)
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT"], 3000.0 + diag, delta=1)


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class TextLabelsBecomeDuctSizesAndSheetArea(unittest.TestCase):
    """HVAC_DRAWING_RULES.md rule 3, 23 Oct 2026: both the owner's own
    independent AI check and a second review of the same file landed on
    the same gap -- the duct/pipe size is written right on the drawing as
    plain TEXT ("800x400", "DN80") and the measurement never read it, so a
    route length alone could never be priced (GI duct is billed in m² of
    sheet per size, not metres of centreline). Reconstructs the real
    file's own trunk-broken-by-branch-gaps shape, since that is exactly
    the case naive nearest-text matching gets wrong (confirmed live: it
    first wrongly attached A-WALL, the architectural perimeter, to a duct
    size label that merely happened to sit nearby -- fixed by scoping
    rule 3 to layers that name themselves duct or pipe work)."""

    def _trunk_split_by_a_branch_gap(self) -> str:
        path = _tmp()

        def build(msp):
            L = "M-DUCT-SUPPLY"
            # two trunk pieces, same 800 width, split by a 400mm branch gap
            msp.add_line((0, 800), (3800, 800), dxfattribs={"layer": L})
            msp.add_line((0, 0), (3800, 0), dxfattribs={"layer": L})
            msp.add_line((4200, 800), (8000, 800), dxfattribs={"layer": L})
            msp.add_line((4200, 0), (8000, 0), dxfattribs={"layer": L})
            # the actual branch tying in at the gap, proving it is a real
            # junction and not just an unexplained split (rule 2 revisited,
            # 25 Oct 2026, would otherwise bridge this gap into one run).
            # Short and far enough from the size label below that it never
            # competes for it -- a lone stub like this would carry its own
            # size label in a real drawing, not the trunk's.
            msp.add_line((4000, 800), (4000, 3000), dxfattribs={"layer": L})
            # the size label sits near ONE of the two pieces only
            msp.add_text("800x400 SA", dxfattribs={"layer": "M-TEXT", "height": 150}) \
               .set_placement((200, 900))
            # an architectural wall nearby -- must never pick up the label
            msp.add_line((0, 5000), (8000, 5000), dxfattribs={"layer": "A-WALL"})

        _dxf(path, build)
        return path

    def test_the_label_propagates_to_both_trunk_pieces(self):
        q = boq.measure(self._trunk_split_by_a_branch_gap(), hvac=True)
        sizes = q["duct_sizes"]
        self.assertEqual(len(sizes), 1)
        entry = sizes[0]
        self.assertEqual(entry["layer"], "M-DUCT-SUPPLY")
        self.assertEqual(entry["size"], "800x400")
        self.assertEqual(entry["kind"], "duct")
        # both pieces (3800 + 3800 = 7600), not just the nearer one
        self.assertAlmostEqual(entry["length"], 7600.0, delta=1)
        self.assertAlmostEqual(entry["area_m2"], 2.4 * 7.6, delta=0.05)

    def test_an_architectural_wall_near_the_same_label_is_never_sized(self):
        q = boq.measure(self._trunk_split_by_a_branch_gap(), hvac=True)
        self.assertFalse(any(e["layer"] == "A-WALL" for e in q["duct_sizes"]))

    def test_no_sizes_at_all_when_hvac_is_off(self):
        q = boq.measure(self._trunk_split_by_a_branch_gap())
        self.assertEqual(q["duct_sizes"], [])

    def test_a_pipe_size_label_is_read_as_dn_not_a_duct_size(self):
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (4000, 0), dxfattribs={"layer": "M-PIPE-CHW-S"})
            msp.add_text("CHWS DN80", dxfattribs={"layer": "M-TEXT", "height": 150}) \
               .set_placement((100, 100))

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertEqual(len(q["duct_sizes"]), 1)
        entry = q["duct_sizes"][0]
        self.assertEqual(entry["size"], "DN80")
        self.assertEqual(entry["kind"], "pipe")
        self.assertNotIn("area_m2", entry)          # pipes aren't sheet metal

    def test_a_pipe_label_near_a_duct_layer_is_never_attached_to_it(self):
        """Caught on the real, more complex tender file: a 'DN32' pipe
        label sat closer to a duct run than any duct-pattern label did,
        and got attached to it, producing a nonsensical duct-sized-in-DN
        entry. A duct layer only ever takes a duct-pattern label now, a
        pipe layer only ever a pipe-pattern one, regardless of distance."""
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (4000, 0), dxfattribs={"layer": "M-DUCT-FLEX"})
            # the only label anywhere nearby is a PIPE size -- must be
            # ignored for this duct layer, not attached just because nothing
            # closer exists.
            msp.add_text("DN32", dxfattribs={"layer": "M-TEXT", "height": 150}) \
               .set_placement((100, 100))

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertEqual(q["duct_sizes"], [])

    def test_a_duct_label_near_a_pipe_layer_is_never_attached_to_it(self):
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (4000, 0), dxfattribs={"layer": "M-PIPE-CHW-S"})
            msp.add_text("400x250", dxfattribs={"layer": "M-TEXT", "height": 150}) \
               .set_placement((100, 100))

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertEqual(q["duct_sizes"], [])

    def test_summary_text_aggregates_one_line_per_layer_and_size(self):
        """A trunk broken into several LINE entities by branch take-offs
        produces several `duct_sizes` entries of the SAME size on the SAME
        layer -- the summary text the write-up AI actually reads must show
        one aggregated line, not several near-duplicates (caught on the
        real tender file: the first version produced a dozen lines for a
        handful of real sizes)."""
        q = boq.measure(self._trunk_split_by_a_branch_gap(), hvac=True)
        self.assertEqual(len(q["duct_sizes"]), 1)      # engine stays granular...
        text = boq.summary_text(q)
        # ...but the text the AI reads says it once, aggregated.
        self.assertEqual(text.count("M-DUCT-SUPPLY 800x400"), 1)
        self.assertIn("7.60 m run", text)
        self.assertIn("do not mark them 'TBC", text)


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class ACornerInASingleLineRunIsAnElbow(unittest.TestCase):
    """HVAC_DRAWING_RULES.md rule 4, 23 Oct 2026: a single-line duct/pipe
    that turns a corner (the return duct's own elbow in the real file) is
    a fitting a real BOQ has to list. Only ever looks at two segments that
    already share an exact endpoint -- a hard topological fact, not a
    proximity guess -- so it carries none of the false-positive risk that
    kept branch-take-off gap bridging out of this round (see
    HVAC_DRAWING_RULES.md's "what this does NOT handle" section)."""

    def test_an_l_shaped_single_line_duct_reports_one_elbow(self):
        path = _tmp()

        def build(msp):
            L = "M-DUCT-RETURN"
            msp.add_line((19000, 1000), (2000, 1000), dxfattribs={"layer": L})
            msp.add_line((2000, 1000), (2000, 6000), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertTrue(any("1 corner(s)" in n and "elbow" in n for n in q["notes"]))
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT-RETURN"], 17000 + 5000, delta=1)

    def test_a_straight_single_line_run_has_no_elbow(self):
        path = _tmp()

        def build(msp):
            msp.add_line((0, 0), (22000, 1000), dxfattribs={"layer": "M-DUCT-RETURN"})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertFalse(any("elbow" in n for n in q["notes"]))


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class ABranchTakeOffGapIsBridgedOnlyWhenNoBranchTiesIn(unittest.TestCase):
    """HVAC_DRAWING_RULES.md rule 2's gap-bridging, revisited 25 Oct 2026
    with the real topology check it was missing the first time: a trunk
    split into two "pair" runs by a branch take-off is bridged into one
    continuous run ONLY when nothing else on the layer ties into the gap.
    When a branch DOES tie in there -- a real tee/cross junction -- the
    gap is left alone, because it is the branch fitting's own width, not
    missing trunk duct. The first version of this idea bridged every such
    gap and was rejected before shipping for exactly this reason (see
    HVAC_DRAWING_RULES.md rule 2's own "what it does NOT handle" note)."""

    def test_a_gap_with_nothing_tied_into_it_is_bridged(self):
        path = _tmp()

        def build(msp):
            L = "M-DUCT-SUPPLY"
            # two 400-wide trunk pieces, a 500mm gap between them, nothing
            # else on the layer -- an ordinary DXF-export split, not a
            # junction.
            msp.add_line((0, 400), (2000, 400), dxfattribs={"layer": L})
            msp.add_line((0, 0), (2000, 0), dxfattribs={"layer": L})
            msp.add_line((2500, 400), (4500, 400), dxfattribs={"layer": L})
            msp.add_line((2500, 0), (4500, 0), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        # 2000 + 500 (the bridged gap) + 2000 = 4500, not 4000 (the two
        # pieces left separate, the gap silently lost).
        self.assertAlmostEqual(q["lengths_by_layer"]["M-DUCT-SUPPLY"], 4500.0, delta=1)
        self.assertTrue(any("bridged" in n and "no branch ties in" in n
                            for n in q["notes"]))

    def test_a_gap_with_a_branch_tied_in_is_left_alone(self):
        """The exact false-positive case that kept this out of item 14's
        first round: a branch duct crosses the trunk and ties in right at
        the gap. Bridging here would silently add the trunk's own width
        as if it were missing duct -- it must stay as two separate runs."""
        path = _tmp()

        def build(msp):
            L = "M-DUCT-SUPPLY"
            msp.add_line((0, 400), (2000, 400), dxfattribs={"layer": L})
            msp.add_line((0, 0), (2000, 0), dxfattribs={"layer": L})
            msp.add_line((2500, 400), (4500, 400), dxfattribs={"layer": L})
            msp.add_line((2500, 0), (4500, 0), dxfattribs={"layer": L})
            # a branch tying into the trunk's own wall, its endpoint
            # landing exactly inside the gap (x=2250, within 2000-2500,
            # at y=400 -- the trunk wall's own line).
            msp.add_line((2250, 400), (2250, 3000), dxfattribs={"layer": L})

        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        # The two 2000mm pieces stay separate (4000 total from them) plus
        # the 500mm branch stub itself (a "single" run) = 4500 -- NOT the
        # bridged 4500 total coincidentally matching above; the real check
        # is that it is NOT reported as bridged.
        self.assertFalse(any("bridged" in n for n in q["notes"]))

    def test_the_real_file_s_own_both_sided_junction_is_never_bridged(self):
        """The real shape this whole rule exists for, reconstructed from
        `hvac_tender_complex.dxf`'s M-DUCT-SUPPLY trunk (not read from the
        file itself -- the exact coordinates found reverse-engineering it,
        24-25 Oct 2026): a trunk takes branches off BOTH sides at the same
        point, x=13275-13725, on two different walls 800mm apart -- one
        branch going up from (13275, 16400), another going down from
        (13725, 15600). Naively bridging both gaps would have added the
        trunk's own 800mm width twice, silently, as if it were duct."""

        def build(msp):
            L = "M-DUCT-SUPPLY"
            # upper wall, split by the gap, with a branch going UP from
            # its left-hand piece's own end point
            msp.add_line((11500, 16400), (13275, 16400), dxfattribs={"layer": L})
            msp.add_line((13725, 16400), (16000, 16400), dxfattribs={"layer": L})
            msp.add_line((11500, 16500), (13275, 16500), dxfattribs={"layer": L})
            msp.add_line((13725, 16500), (16000, 16500), dxfattribs={"layer": L})
            msp.add_line((13275, 16400), (13275, 26725), dxfattribs={"layer": L})
            # lower wall, split by the SAME gap, with a branch going DOWN
            # from its right-hand piece's own end point
            msp.add_line((11500, 15600), (13275, 15600), dxfattribs={"layer": L})
            msp.add_line((13725, 15600), (16000, 15600), dxfattribs={"layer": L})
            msp.add_line((11500, 15700), (13275, 15700), dxfattribs={"layer": L})
            msp.add_line((13725, 15700), (16000, 15700), dxfattribs={"layer": L})
            msp.add_line((13725, 15600), (13725, 3725), dxfattribs={"layer": L})

        path = _tmp()
        _dxf(path, build)
        q = boq.measure(path, hvac=True)
        self.assertFalse(any("bridged" in n for n in q["notes"]))


if __name__ == "__main__":
    unittest.main()
