"""The rhythm of a Motion film is measured, and a film that never rests (or never moves) is named."""
from __future__ import annotations

import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import rhythm  # noqa: E402


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _slide(nid, at, dur, frm=-300, to=0):
    return {"id": nid, "type": "shape_rect", "position": [540, 960], "width": 500, "height": 140, "fill": "#111111",
            "animation": {"enter": {"time": at, "duration": dur, "tweens": [
                {"channel": "x", "from": frm, "to": to, "easing": "none"}]}}}


def _spec(nodes, seconds=8):
    return {"project": {"duration": seconds, "fps": 30, "width": 540, "height": 960, "background": "#FAF9F6", "look": "paper"},
            "scenes": [{"id": "a", "duration": seconds, "nodes": nodes}]}


class Faults(unittest.TestCase):
    def test_no_profile_no_faults(self):
        self.assertEqual(rhythm.faults(None), [])
        self.assertEqual(rhythm.faults({"seconds": 2.0, "static_pct": 0}), [])

    def _p(self, **kw):
        p = {"seconds": 14.0, "static_pct": 30.0, "mean_motion": 2.0, "per_second": [1.0] * 14, "holds": [1.9, 1.7],
             "longest_hold": 1.9, "holds_ge_1s": 2, "top10_share": 38.0, "luminance": [236.0, 250.0]}
        p.update(kw)
        return p

    def test_a_film_like_the_reference_has_nothing_to_fix(self):
        self.assertEqual(rhythm.faults(self._p()), [])

    def test_a_film_that_never_rests_is_named_with_what_to_do(self):
        f = rhythm.faults(self._p(static_pct=5.0, longest_hold=0.7, holds=[0.7], holds_ge_1s=0))
        self.assertTrue(any("never rests" in x and "5%" in x for x in f), f)

    def test_a_film_that_never_moves_names_the_quiet_seconds(self):
        f = rhythm.faults(self._p(static_pct=71.0, per_second=[8, 3, 6, 0.05, 0.03, 0.1, 0.05, 0.4, 0.1, 0.2, 0.1, 0.2, 0.1, 0.1]))
        self.assertTrue(any("mostly still" in x and "stretch is seconds 3-14" in x for x in f), f)

    def test_evenly_spread_motion_asks_for_a_payoff(self):
        f = rhythm.faults(self._p(top10_share=12.0))
        self.assertTrue(any("spread evenly" in x for x in f), f)


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class Probe(unittest.TestCase):
    def test_a_slide_then_a_long_hold_is_mostly_still_with_one_burst(self):
        p = rhythm.probe(_spec([_slide("s", 0.5, 1.5)], seconds=8))
        self.assertGreater(p["static_pct"], 60)
        self.assertGreaterEqual(p["holds_ge_1s"], 1)
        self.assertGreater(p["longest_hold"], 4.0)
        self.assertGreater(p["top10_share"], 30)
        self.assertGreater(p["luminance"][0], 200, "a paper page is bright")

    def test_something_always_moving_never_rests(self):
        node = {"id": "w", "type": "shape_rect", "position": [270, 480], "width": 300, "height": 200, "fill": "#111111",
                "animation": {"secondary_motion": {"property": "x", "freq": 0.6, "amount": 160}}}
        p = rhythm.probe(_spec([node], seconds=8))
        self.assertLess(p["static_pct"], 20)
        self.assertTrue(any("never rests" in f for f in rhythm.faults(p)), p)


if __name__ == "__main__":
    unittest.main()
