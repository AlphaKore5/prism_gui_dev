"""A length the client names is read, planned to, and held (finding M6).

"A 25-second reel" came back as 21.4 s from Reel and 15 s from Motion:
each planned to its own band and nothing read the number in the ask.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core import reel  # noqa: E402
from core.length import bounds, requested_seconds  # noqa: E402
from core.motion.generate import storyboard_instructions  # noqa: E402


class ReadingTheAsk(unittest.TestCase):
    def test_the_usual_ways_of_saying_it(self):
        for text, secs in (
            ("A 25-second Instagram reel for Shree Precision", 25.0),
            ("make it 30s, vertical", 30.0),
            ("about 45 seconds long", 45.0),
            ("a 1 minute explainer", 60.0),
            ("a one-minute brand film", 60.0),
            ("half a minute on our new line", 30.0),
            ("1.5 min walkthrough", 90.0),
        ):
            self.assertEqual(requested_seconds(text), secs, text)

    def test_numbers_that_are_not_a_length_are_ignored(self):
        for text in (
            "22 years in business, ISO 9001, 500 units a month",
            "founded in 2003, phone +91 98765 43210",
            "a 2-second logo sting",       # under the floor: a transition, not a film
            "a 10 minute documentary",     # over the ceiling: not a reel
            "",
        ):
            self.assertIsNone(requested_seconds(text), text)

    def test_bounds_are_fifteen_percent(self):
        self.assertEqual(bounds(20.0), (17.0, 23.0))


class ReelHoldsTheAsk(unittest.TestCase):
    def _spec(self, *seconds):
        kinds = ["statement", "figure", "pillar", "figure", "list", "hub", "endcard"]
        scenes = []
        for kind, s in zip(kinds, seconds):
            sc = {"type": kind, "seconds": s}
            if kind == "statement":
                sc["lines"] = ["Precision turned parts."]
            elif kind == "figure":
                sc.update(value="22", label="years")
            elif kind == "pillar":
                sc.update(heading="CNC turning", caption="for pumps", icons=["tools"])
            elif kind == "list":
                sc.update(heading="What we make", items=["Shafts", "Housings"])
            elif kind == "hub":
                sc.update(heading="One shop floor", caption="turn, mill, measure")
            else:
                sc.update(name="Shree Precision", tagline_lines=["CNC parts"])
            scenes.append(sc)
        return {"fps": 30, "scenes": scenes}

    def _length_faults(self, spec, requested=None):
        return [f for f in reel.lint_spec(spec, requested=requested)
                if "long" in f or "runs" in f]

    def test_the_prompt_names_the_clients_length_instead_of_the_house_band(self):
        self.assertIn("20–35 seconds in total", reel.spec_instructions())
        text = reel.spec_instructions(requested=25)
        self.assertIn("about 25 seconds in total", text)
        self.assertIn("asked for 25", text)
        self.assertNotIn("20–35 seconds in total", text)

    def test_the_lint_holds_the_plan_to_the_ask(self):
        twenty_one = self._spec(4, 5, 5, 4.5, 2.5)        # the study's own 21.4 s plan
        self.assertEqual(self._length_faults(twenty_one), [], "fine by the house band")
        faults = self._length_faults(twenty_one, requested=25)
        self.assertEqual(len(faults), 1)
        self.assertIn("asked for 25s", faults[0])
        self.assertEqual(self._length_faults(self._spec(5, 5, 5, 5, 4), requested=25), [])
        over = self._length_faults(self._spec(6, 6, 6, 6, 6), requested=25)
        self.assertEqual(len(over), 1)
        self.assertIn("dropping a scene", over[0])


class MotionIsToldTheAsk(unittest.TestCase):
    def test_the_storyboard_turn_carries_the_length_after_the_band(self):
        plain = storyboard_instructions("a reel for a CNC shop")
        self.assertNotIn("LENGTH:", plain)
        for skeleton in (None, "brand_launch", "cinematic_glass"):
            text = storyboard_instructions("A 25-second reel for a CNC shop", skeleton=skeleton)
            self.assertIn("LENGTH: the client asked for 25 seconds", text)
            self.assertLess(text.index("seconds total"), text.index("LENGTH:"),
                            "the ask is stated after the band so it wins")


if __name__ == "__main__":
    unittest.main()
