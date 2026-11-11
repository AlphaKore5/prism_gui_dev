"""One story grammar, for any business (Phase 3 of the reference-film plan)."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import generate, story  # noqa: E402


def _scene(*nodes):
    return {"id": "s", "duration": 4, "nodes": [dict(n) for n in nodes]}


class Grammar(unittest.TestCase):
    def test_five_parts_in_order_whose_shares_fill_the_film(self):
        self.assertEqual([b["name"] for b in story.BEATS], ["hook", "act", "promise", "proof", "payoff"])
        self.assertAlmostEqual(sum(b["share"] for b in story.BEATS), 1.0, places=6)

    def test_the_beat_list_scales_with_the_requested_length_and_names_rest(self):
        short, long_ = story.storyboard_text(10.0), story.storyboard_text(40.0)
        self.assertIn("~1.8s", short)             # hook: 0.18 * 10
        self.assertIn("~7.2s", long_)             # hook: 0.18 * 40
        self.assertIn("REST IS PART OF THE DESIGN", short)

    def test_no_part_names_a_business_or_a_pixel_position(self):
        for b in story.BEATS:
            text = (b["subject"] + b["recipe"]).lower()
            for banned in ("cnc", "pump", "vadodara", "1080", "1920", "[540"):
                self.assertNotIn(banned, text, b["name"])


class Checks(unittest.TestCase):
    def test_each_part_names_what_it_lacks_and_passes_when_it_has_it(self):
        T = {"id": "n", "type": "text", "content": "Name"}
        cases = {
            "hook": (_scene({"id": "x", "type": "shape_rect"}), _scene(T)),
            "act": (_scene(T), _scene({"id": "i", "type": "ui_input", "text": "hi"})),
            "promise": (_scene({"id": "c", "type": "ui_checklist", "items": [{"label": "a"}]}),
                        _scene({"id": "c", "type": "ui_checklist", "items": [{"label": "a"}, {"label": "b"}, {"label": "c"}]})),
            "proof": (_scene(T), _scene({"id": "w", "type": "ui_window", "children": [T]})),
            "payoff": (_scene({"id": "p", "type": "ui_pill", "label": "x"}),
                       _scene({"id": "p", "type": "ui_pill", "label": "Done", "check": True})),
        }
        for name, (bad, good) in cases.items():
            self.assertTrue(story.beat_faults(bad, name), f"{name}: should be sent back")
            self.assertEqual(story.beat_faults(good, name), [], f"{name}: should pass")

    def test_a_cursor_alone_satisfies_the_act_and_children_are_searched(self):
        self.assertEqual(story.beat_faults(_scene({"id": "c", "type": "cursor", "position": [1, 1]}), "act"), [])
        self.assertEqual(story.beat_faults(_scene({"id": "g", "type": "glass_panel", "children": [
            {"id": "i", "type": "ui_input", "text": "x"}]}), "act"), [])

    def test_a_fault_carries_the_recipe_so_the_writer_knows_what_to_do(self):
        f = story.beat_faults(_scene({"id": "x", "type": "shape_rect"}), "promise")
        self.assertTrue(f and "ui_checklist" in f[0] and "HOLD" in f[0])

    def test_unknown_parts_are_not_policed(self):
        self.assertEqual(story.beat_faults(_scene(), "gather"), [])


class InThePrompts(unittest.TestCase):
    def test_the_storyboard_turn_teaches_the_story_and_not_the_cinematic_profile(self):
        t = generate.storyboard_instructions("A 20-second film for a bakery", skeleton="story")
        self.assertIn("THE STORY", t)
        self.assertIn('"beat": "hook"', t)
        self.assertIn("EXACTLY 5 scenes", t)
        self.assertNotIn("CONTINUOUS CINEMATIC PROFILE", t)
        self.assertNotIn("LAYERS — give every node", t)
        self.assertIn("ui_checklist", t)                       # the catalogue it builds from
        self.assertIn("~3.6s", t)                              # 20 s * 0.18 for the hook

    def test_the_model_is_told_a_flat_page_needs_no_glow(self):
        t = generate.storyboard_instructions("a reel", skeleton="story")
        self.assertIn("Do NOT add light_field or glass_panel on a flat page", t)

    def test_the_old_spine_is_still_selectable(self):
        t = generate.storyboard_instructions("a reel", skeleton="cinematic_glass")
        self.assertIn("THE SPINE", t)
        self.assertNotIn("THE STORY", t)

    def test_a_scene_turn_carries_its_parts_recipe_and_the_check_dispatches(self):
        row = {"seconds": 4, "job": "j", "beat": "act", "caption": "", "subject": "", "look": "", "motion": ""}
        p = generate.scene_instructions(1, 5, row, skeleton="story")
        self.assertIn('THIS SCENE\'S PART: "act"', p)
        self.assertTrue(generate.beat_check(_scene({"id": "t", "type": "text", "content": "x"}), row, "story"))
        self.assertEqual(generate.beat_check(_scene({"id": "i", "type": "ui_input", "text": "x"}), row, "story"), [])
        self.assertEqual(generate.beat_check(_scene({"id": "t", "type": "text"}), row, None), [])


class WhichProfileARunUses(unittest.TestCase):
    def test_the_default_is_unchanged_and_config_can_select_the_story(self):
        from core import automation
        self.assertEqual(automation._motion_skeleton("", {}), "cinematic_glass")
        self.assertEqual(automation._motion_skeleton("", None), "cinematic_glass")
        self.assertEqual(automation._motion_skeleton("", {"motion_skeleton": "story"}), "story")
        self.assertEqual(automation._motion_skeleton("brand_launch", {"motion_skeleton": "story"}), "brand_launch",
                         "a caller's own choice wins")
        self.assertEqual(automation._motion_skeleton("", {"motion_skeleton": "nonsense"}), "cinematic_glass")


if __name__ == "__main__":
    unittest.main()
