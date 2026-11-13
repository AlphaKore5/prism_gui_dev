"""The Motion checker measures geometry in the real runtime (finding M4).

core.motion.inspect estimates a text's box from its character count and
never sees the camera. core.motion.measure reads the box Chromium lays
out, after the camera, and replaces the estimate's off-frame and
safe-area faults with measured ones.
"""
from __future__ import annotations

import importlib
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import inspect as motion_inspect  # noqa: E402
from core.motion import measure  # noqa: E402


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _text(nid, position, content="Precision in every part", anchor=(0.5, 0.5), size=96):
    return {"id": nid, "type": "text", "content": content, "font_size": size,
            "font_weight": 800, "fill": "#111111", "anchor": list(anchor),
            "position": list(position), "mode": "standard", "layer": "foreground"}


def _spec(nodes, camera=None):
    spec = {"project": {"duration": 2, "fps": 30, "width": 1080, "height": 1920},
            "scenes": [{"id": "one", "duration": 2, "nodes": [
                {"id": "bg", "type": "light_field", "position": [540, 960], "width": 1400,
                 "height": 2200, "color": "#ECE6D8", "intensity": 0.3, "layer": "background"},
                *nodes]}]}
    if camera:
        spec["camera"] = camera
    return spec


class WithoutABrowser(unittest.TestCase):
    def test_inspect_all_is_the_estimate_when_no_browser_is_here(self):
        from unittest import mock
        spec = _spec([_text("far", (1000, 900), anchor=(0, 0))])
        with mock.patch("core.motion.render._playwright_available", return_value=False):
            self.assertEqual(measure.inspect_all(spec), motion_inspect.inspect(spec))


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed — "
                     "the layout box can only be read from a real browser")
class MeasuredInChromium(unittest.TestCase):
    def test_a_headline_past_the_edge_and_one_under_the_status_bar_are_named(self):
        faults = measure.inspect_rendered(_spec([
            _text("far", (1000, 900), anchor=(0, 0)),   # starts near the right edge, runs off it
            _text("high", (540, 100)),                   # inside the top 11% band
            _text("fine", (540, 960)),                   # centred, inside everything
        ]))
        self.assertIsNotNone(faults)
        joined = "\n".join(faults)
        self.assertIn('node "far" (text) runs off the edge', joined)
        self.assertIn('node "high" (text) sits inside the top', joined)
        self.assertNotIn('"fine"', joined)
        self.assertIn("measured in the browser", joined)

    def test_the_camera_is_applied_the_estimate_cannot_see_it(self):
        # A 1.6x zoom at the centre shows x = 202..877 of the stage. A
        # headline left-anchored at x=150 is inside the AUTHORED frame — the
        # estimate passes it — and off the left of the FILMED one.
        spec = _spec([_text("left", (150, 960), content="Turned.", anchor=(0, 0))],
                     camera={"tracks": [{"time": 0.0, "position": [540, 960], "zoom": 1.6}]})
        est = [f for f in motion_inspect.inspect(spec) if "runs off the edge" in f]
        self.assertEqual(est, [], "the estimate has no camera and passes this")
        measured = measure.inspect_rendered(spec)
        self.assertTrue(any('node "left" (text) runs off the edge' in f for f in measured), measured)

    def test_a_measured_box_replaces_a_wrong_estimate(self):
        # Twenty "i"s at 48px: the estimate (chars x 0.55 x size) says 528px
        # wide, so from x=600 it "runs off" at 1128; a real sans lays them
        # out in roughly a quarter of that and the line fits with room.
        spec = _spec([_text("narrow", (600, 960), content="i" * 20, anchor=(0, 0), size=48)])
        est = motion_inspect.inspect(spec)
        self.assertTrue(any("runs off the edge" in f for f in est), est)
        both = measure.inspect_all(spec)
        self.assertFalse(any("runs off the edge" in f for f in both), both)

    def test_inspect_all_keeps_every_non_geometry_fault(self):
        # Two foreground texts on the same spot: the overlap check is the
        # estimate's and must survive the merge.
        spec = _spec([_text("a", (540, 960)), _text("b", (540, 980))])
        both = measure.inspect_all(spec)
        self.assertTrue(any("overlap by" in f for f in both), both)


if __name__ == "__main__":
    unittest.main()
