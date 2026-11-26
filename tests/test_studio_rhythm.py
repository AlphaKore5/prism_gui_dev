"""Studio reels are measured for rhythm and a reel that is mostly still sends its quietest scenes back."""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402

SCRIPT = json.dumps({"scenes": [
    {"role": "hook", "seconds": 4, "headline": "Happy Christmas"},
    {"role": "statement", "seconds": 4, "headline": "Thank you for this year"},
    {"role": "statement", "seconds": 4, "headline": "Warm and bright"},
    {"role": "endcard", "seconds": 4, "headline": "Merry Christmas"},
]})
TURN_ONE = """```json
{"design": {"name": "night", "cut_ms": 500, "css": ":root{--ink:#12241a}"},
 "storyboard": [
   {"scene": 1, "job": "open", "look": "low", "motion": "rises", "cut": "push"},
   {"scene": 2, "job": "thanks", "look": "left", "motion": "rises", "cut": "zoom"},
   {"scene": 3, "job": "wish", "look": "centre", "motion": "rises", "cut": "push"},
   {"scene": 4, "job": "sign", "look": "mark", "motion": "settles", "cut": "push-up"}]}
```"""


def reply(html="<p class='t'>x</p>", css=".t{font-size:90px}"):
    return "```json\n" + json.dumps({"seconds": 4, "cut": "push", "css": css, "html": html}) + "\n```"


def profile(still):
    return {"seconds": 16.0, "static_pct": still, "per_second": [2.0, 2.0, 2.0, 2.0, 0.1, 0.1, 0.1, 0.1, 3.0, 3.0, 3.0, 3.0, 0.1, 0.1, 0.1, 0.1],
            "longest_hold": 3.5, "holds_ge_1s": 3, "top10_share": 40.0, "luminance": [10.0, 200.0], "holds": [3.5]}


class RepairInTheBuild(unittest.TestCase):
    def _run(self, profiles):
        asked, calls = [], iter(profiles)

        def ask(prompt, expect=None):
            asked.append(prompt)
            return reply()

        spec = RW.build_spec(TURN_ONE, ask, script=SCRIPT, measure=lambda s: next(calls))
        return spec, asked

    def test_a_mostly_still_reel_sends_its_quietest_scene_back_and_keeps_a_real_fix(self):
        spec, asked = self._run([profile(68), profile(40)])
        rhythm_asks = [a for a in asked if "finished film was measured" in a]
        self.assertEqual(len(rhythm_asks), 1)
        self.assertIn("68%", rhythm_asks[0])
        self.assertIn("zoom or drift on the photo", rhythm_asks[0], "Studio is told in Studio's terms")
        self.assertEqual(len(spec["scenes"]), 4)

    def test_the_opening_is_never_the_scene_sent_back(self):
        # scenes 1-4 per_second: 2, .1, 3, .1 -> the quiet ones are 2 and 4 (index 1, 3); never index 0
        spec, asked = self._run([profile(68), profile(68), profile(68)])
        said = [a for a in asked if "finished film was measured" in a]
        self.assertTrue(said)
        self.assertTrue(all("Scene 1 " not in a for a in said), said)

    def test_a_fix_that_does_not_help_is_not_kept(self):
        spec, asked = self._run([profile(68), profile(67), profile(67)])
        self.assertEqual(len([a for a in asked if "finished film was measured" in a]), 2)

    def test_a_reel_inside_the_band_is_left_alone(self):
        spec, asked = self._run([profile(30)])
        self.assertEqual([a for a in asked if "finished film was measured" in a], [])

    def test_a_measure_that_fails_never_costs_the_reel(self):
        def boom(spec):
            raise RuntimeError("no browser")
        spec = RW.build_spec(TURN_ONE, lambda p, expect=None: reply(), script=SCRIPT, measure=boom)
        self.assertEqual(len(spec["scenes"]), 4)


def _chromium():
    ok, _why = RW.available()
    return ok


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class Probe(unittest.TestCase):
    def test_a_reel_of_still_headlines_is_measured_mostly_still(self):
        spec = {"design": {"name": "x", "cut_ms": 300, "css": ""},
                "scenes": [{"seconds": 3, "cut": "cut", "css": ".t{font-size:90px;color:#111}", "html": "<p class='t'>A</p>"},
                           {"seconds": 3, "cut": "cut", "css": ".t{font-size:90px;color:#111}", "html": "<p class='t'>B</p>"}]}
        p = RW.rhythm_probe(spec)
        self.assertIsNotNone(p)
        self.assertGreater(p["static_pct"], 60)
        self.assertAlmostEqual(p["seconds"], 6.0, delta=1.0)


if __name__ == "__main__":
    unittest.main()
