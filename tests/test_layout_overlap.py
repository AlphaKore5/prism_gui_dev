"""The page is measured for texts printed over each other.

Until now the in-browser check knew three faults: a text outside the frame,
a text too small, and a text with EVERY sample point under a sibling. The
2026-09-07 reel passed it with one complaint ("an image runs off the frame")
while carrying a running header printed through its own date, a footer under
a caption, a vertical label through a headline, and two white blocks over
half a page counter — each text was inside the frame, large enough, and on
top of *most* of what was under it.

These run the real check in the real browser. Skipped where there is no
Chromium, since a fake DOM would be testing the fake.
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402

READY, WHY = RW.available()

CSS = (".scene{background:#f4efe6}"
       ".t{position:absolute;font:60px/1.1 sans-serif;color:#111;margin:0}")


def spec(html, css=""):
    return {"design": {"css": CSS}, "scenes": [{"seconds": 3, "html": html,
                                                "css": css}]}


@unittest.skipUnless(READY, f"needs the web renderer: {WHY}")
class TwoTextsPrintedOverEachOther(unittest.TestCase):

    def test_scene_root_position_cannot_stack_later_scenes_below_frame(self):
        # Content spans the frame: a lone line leaves most of it bare, which the gap rule (rightly) flags.
        project = spec("<p class='t' style='left:150px;top:500px'>First</p>"
                       "<p class='t' style='left:150px;top:1450px'>Footer</p>")
        project["design"]["css"] += ".scene{position:relative}"
        project["scenes"].append({"seconds": 3, "css": ".scene{position:relative}",
                                  "html": "<p class='t' style='left:150px;top:500px'>Second</p>"
                                          "<p class='t' style='left:150px;top:1450px'>Footer</p>"})
        self.assertEqual(RW.inspect(project), [])

    def test_multiple_filled_animations_are_valid(self):
        project = spec("<p class='t a' style='left:150px;top:500px'>Moving</p>"
                       "<p class='t' style='left:150px;top:1450px'>Footer</p>",
                       ".a{animation:fade 300ms both,rise 400ms both}"
                       "@keyframes fade{from{opacity:0}to{opacity:1}}"
                       "@keyframes rise{from{transform:translateY(10px)}to{transform:translateY(0)}}")
        self.assertEqual(RW.inspect(project), [])

    def test_inspection_checks_the_saved_edit_not_just_original_markup(self):
        project = spec("<p class='t' data-prism-id='headline' style='left:150px;top:500px'>Edited</p>")
        project["edits"] = [{"scene": 0, "element_id": "headline", "dx": 1200, "dy": 0, "scale": 1}]
        self.assertTrue(any("outside" in f for f in RW.inspect(project)))

    def test_are_reported_with_both_names(self):
        faults = RW.inspect(spec(
            "<p class='t' style='left:100px;top:300px'>BRAND GUIDELINES</p>"
            "<p class='t' style='left:360px;top:312px'>EDITION 01</p>"))
        hit = [f for f in faults if "overlap" in f]
        self.assertTrue(hit, faults)
        self.assertIn("BRAND GUIDELINES", hit[0])
        self.assertIn("EDITION 01", hit[0])

    def test_neighbours_that_keep_their_distance_pass(self):
        faults = RW.inspect(spec(
            "<p class='t' style='left:100px;top:300px'>BRAND GUIDELINES</p>"
            "<p class='t' style='left:100px;top:500px'>EDITION 01</p>"))
        self.assertEqual([f for f in faults if "overlap" in f], [])

    def test_a_vertical_label_through_a_headline_is_caught(self):
        faults = RW.inspect(spec(
            "<p class='t' style='left:400px;top:700px'>Typography.</p>"
            "<p class='t' style='left:640px;top:600px;writing-mode:vertical-rl;"
            "font-size:34px'>IDENTITY / 04 PARTS</p>"))
        self.assertTrue(any("overlap" in f and "Typography." in f for f in faults),
                        faults)

    def test_a_hairline_kiss_between_lines_is_not_a_collision(self):
        # Two lines whose boxes touch by a couple of pixels of line-height.
        faults = RW.inspect(spec(
            "<p class='t' style='left:100px;top:300px'>Colour.</p>"
            "<p class='t' style='left:100px;top:364px'>Tokens.</p>"))
        self.assertEqual([f for f in faults if "overlap" in f], [], faults)


@unittest.skipUnless(READY, f"needs the web renderer: {WHY}")
class SomethingPaintedAcrossCopy(unittest.TestCase):

    def test_a_panel_over_part_of_the_text_is_reported(self):
        """The white blocks over the page counter: two of five old sample
        points, so it passed. Two of nine now, so it does not."""
        faults = RW.inspect(spec(
            "<p class='t' style='left:800px;top:150px;z-index:1'>04 / 10</p>"
            "<div style='position:absolute;left:840px;top:130px;width:70px;"
            "height:110px;background:#fff;z-index:5'></div>"))
        hit = [f for f in faults if "covered" in f]
        self.assertTrue(hit, faults)
        self.assertIn("04 / 10", hit[0])
        self.assertIn("<div", hit[0])

    def test_a_panel_behind_the_text_is_fine(self):
        faults = RW.inspect(spec(
            "<div style='position:absolute;left:840px;top:130px;width:70px;"
            "height:110px;background:#fff;z-index:1'></div>"
            "<p class='t' style='left:800px;top:150px;z-index:5'>04 / 10</p>"))
        self.assertEqual([f for f in faults if "covered" in f], [], faults)

    def test_a_label_inside_a_panel_that_has_not_arrived_is_not_on_screen(self):
        """An ancestor at opacity 0 hides everything in it; the old check
        looked only at the text's own opacity."""
        faults = RW.inspect(spec(
            "<div style='position:absolute;inset:0;opacity:0'>"
            "<p class='t' style='left:100px;top:300px'>BRAND GUIDELINES</p></div>"
            "<p class='t' style='left:120px;top:310px'>EDITION 01</p>"))
        self.assertEqual([f for f in faults if "overlap" in f], [], faults)


@unittest.skipUnless(READY, f"needs the web renderer: {WHY}")
class TheReelThatStartedThis(unittest.TestCase):
    """The saved design from 2026-09-07, if it is on this machine. Not a
    fixture in the repo — the point is that a real, model-written page with
    these faults is now caught, and this is the one that was."""

    PATH = os.path.expanduser("~/.prism/runs/reel_1788769798.json")

    def test_its_collisions_are_now_caught(self):
        if not os.path.exists(self.PATH):
            self.skipTest("the reel is not on this machine")
        with open(self.PATH, encoding="utf-8") as f:
            design = json.load(f)
        design.pop("edits", None)          # as first rendered, before hand fixes
        faults = RW.inspect(design)
        overlaps = [f for f in faults if "overlap" in f]
        self.assertGreaterEqual(len(overlaps), 3, faults)
        self.assertTrue(any("BRAND GUIDELINES" in f for f in overlaps), overlaps)


if __name__ == "__main__":
    unittest.main()
