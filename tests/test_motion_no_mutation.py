"""Measuring a film must never change it (12 Nov 2026).

resolve_motion_spec shifts every scene-local time by its scene's start. It used
to do so in place on the caller's nodes, so a spec that was probed and then
rendered was shifted twice: scenes after the first appeared late and the film
was blank. These tests pin that no measuring function, and not the resolver,
changes the spec it is given.
"""
from __future__ import annotations

import copy
import importlib
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import critic, measure, rhythm  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402


def _film():
    cursor = {"id": "c", "type": "cursor", "position": [10, 10], "label": "A",
              "path": [{"at": 0.5, "to": [300, 400], "duration": 0.8, "click": True}]}
    typed = {"id": "t", "type": "text", "content": "Hello there", "position": [540, 900], "font_size": 90,
             "fill": "#111111", "type_on": True, "type_rate": 10, "reveal_start": 0.4,
             "animation": {"enter": {"time": 0.3, "duration": 0.5, "tweens": [{"channel": "opacity", "from": 0, "to": 1}]}}}
    return {"project": {"duration": 6, "fps": 30, "width": 540, "height": 960, "background": "#FAF9F6"},
            "scenes": [{"id": "a", "duration": 3, "nodes": [dict(typed, id="t0")]},
                       {"id": "b", "duration": 3, "nodes": [cursor, typed]}]}


def _frozen(spec):
    return json.dumps(spec, sort_keys=True, default=str)


class Resolver(unittest.TestCase):
    def test_resolving_does_not_change_the_callers_spec(self):
        spec = validate_motion_spec(_film())
        before = _frozen(spec)
        resolve_motion_spec(spec)
        self.assertEqual(_frozen(spec), before)

    def test_two_resolves_of_the_same_spec_agree(self):
        spec = validate_motion_spec(_film())
        a = resolve_motion_spec(spec)
        b = resolve_motion_spec(spec)
        self.assertEqual(_frozen(a["scenes"]), _frozen(b["scenes"]))
        node = a["scenes"][1]["nodes"][1]
        self.assertAlmostEqual(node["reveal_start"], 3.4, places=3)        # shifted once: 3.0 + 0.4

    def test_a_resolved_spec_is_still_not_shifted_again(self):
        once = resolve_motion_spec(validate_motion_spec(_film()))
        twice = resolve_motion_spec(once)
        self.assertEqual(_frozen(once["scenes"]), _frozen(twice["scenes"]))


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class MeasuringLeavesTheFilmAlone(unittest.TestCase):
    def _check(self, fn):
        spec = validate_motion_spec(_film())
        before = _frozen(spec)
        fn(spec)
        self.assertEqual(_frozen(spec), before, "the function changed the spec it was given")

    def test_rhythm_probe(self):
        self._check(lambda s: rhythm.probe(s))

    def test_critic_frames(self):
        self._check(lambda s: critic.settled_frames(s))

    def test_the_geometry_checks(self):
        self._check(lambda s: measure.inspect_rendered(s, moments=(0.35, 0.75, 0.95)))
        self._check(lambda s: measure.fit_to_frame(s))
        self._check(lambda s: measure.content_boxes(s))

    def test_a_probed_film_renders_the_same_frames_as_one_never_probed(self):
        from io import BytesIO
        import numpy as np
        from PIL import Image
        from playwright.sync_api import sync_playwright
        from core import browser as _browser
        import pathlib
        runtime = os.path.join(ENGINE, "core", "motion", "runtime", "index.html")

        def frame_at(spec, seconds):
            r = resolve_motion_spec(validate_motion_spec(spec))
            with sync_playwright() as pw:
                b = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
                try:
                    p = b.new_page(viewport={"width": 540, "height": 960})
                    p.goto(pathlib.Path(runtime).as_uri())
                    p.wait_for_function("typeof window.__loadSpec === 'function'")
                    p.evaluate("s => window.__loadSpec(s)", r)
                    try:
                        p.wait_for_function("document.fonts.ready.then(() => true)", timeout=5000)
                    except Exception:  # noqa: BLE001
                        pass
                    p.evaluate(f"window.__seek({int(seconds * 30)})")
                    return np.asarray(Image.open(BytesIO(p.screenshot(type='png'))).convert("L"), dtype=np.float32)
                finally:
                    b.close()

        fresh = validate_motion_spec(_film())
        probed = validate_motion_spec(_film())
        rhythm.probe(probed)
        critic.settled_frames(probed)
        a, b = frame_at(fresh, 5.0), frame_at(probed, 5.0)
        self.assertGreater(float((a < 200).mean()), 0.001, "scene 2 has something on screen at 5 s")
        self.assertTrue(np.array_equal(a, b), "probing changed what scene 2 looks like")


if __name__ == "__main__":
    unittest.main()
