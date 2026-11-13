"""A scale tween written as absolute values is read as absolute (12 Nov 2026).

A model-written headline had enter tween scale 1.08 -> 1.0, meaning "pop down
to 1x". The runtime adds a scale tween's ends to the node's own scale, so it
drew the node at 2.08x -> 2.0x: twice its size, cut off at both edges. Found by
reading the node's host transform, matrix(2, 0, 0, 2, ...).
"""
from __future__ import annotations

import copy
import importlib
import os
import pathlib
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import generate  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _node(tweens, scale=None, **extra):
    n = {"id": "h", "type": "text", "content": "Twenty-two years", "position": [540, 900], "font_size": 128,
         "animation": {"enter": {"time": 0.1, "duration": 0.8, "tweens": tweens}}}
    if scale:
        n["scale"] = scale
    n.update(extra)
    return n


def _spec(*nodes):
    return {"project": {"duration": 4, "fps": 30, "width": 1080, "height": 1920, "background": "#FAF9F6"},
            "scenes": [{"id": "a", "duration": 4, "nodes": list(nodes)}]}


def _tweens(spec, scene=0, node=0, block="enter"):
    r = resolve_motion_spec(validate_motion_spec(copy.deepcopy(spec)))
    return r["scenes"][scene]["nodes"][node]["animation"][block]["tweens"]


class ResolverReadsAbsoluteScale(unittest.TestCase):
    def test_the_models_pop_down_to_one_becomes_an_offset_from_zero(self):
        tw = _tweens(_spec(_node([{"channel": "scale", "from": 1.08, "to": 1.0, "easing": "power4.out"}])))
        self.assertAlmostEqual(tw[0]["from"], 0.08, places=4)
        self.assertAlmostEqual(tw[0]["to"], 0.0, places=4)

    def test_offsets_the_catalogue_describes_are_left_alone(self):
        for frm, to in ((-0.3, 0.0), (0.1, 0.0), (-0.2, 0.15)):
            tw = _tweens(_spec(_node([{"channel": "scale", "from": frm, "to": to}])))
            self.assertEqual((tw[0]["from"], tw[0]["to"]), (frm, to))

    def test_it_is_relative_to_the_nodes_own_scale_and_handles_axes_exit_and_children(self):
        tw = _tweens(_spec(_node([{"channel": "scaleX", "from": 1.5, "to": 2.0}], scale=[2.0, 2.0])))
        self.assertAlmostEqual(tw[0]["from"], -0.5, places=4)
        self.assertAlmostEqual(tw[0]["to"], 0.0, places=4)
        parent = {"id": "p", "type": "depth_layer", "position": [0, 0], "children": [
            _node([{"channel": "scale", "from": 0.9, "to": 1.0}])]}
        r = resolve_motion_spec(validate_motion_spec(_spec(parent)))
        child = r["scenes"][0]["nodes"][0]["children"][0]["animation"]["enter"]["tweens"][0]
        self.assertAlmostEqual(child["from"], -0.1, places=4)

    def test_resolving_twice_changes_nothing_more(self):
        once = resolve_motion_spec(validate_motion_spec(
            _spec(_node([{"channel": "scale", "from": 1.08, "to": 1.0}]))))
        twice = resolve_motion_spec(once)
        a = once["scenes"][0]["nodes"][0]["animation"]["enter"]["tweens"][0]
        b = twice["scenes"][0]["nodes"][0]["animation"]["enter"]["tweens"][0]
        self.assertEqual((a["from"], a["to"]), (b["from"], b["to"]))

    def test_the_catalogue_states_the_rule_with_an_example(self):
        self.assertIn("a pop that settles at 1x is from 0.08 to 0", generate._NODE_CATALOGUE)
        self.assertIn("opacity is ABSOLUTE", generate._NODE_CATALOGUE)


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class RuntimeDrawsItAtOneTimes(unittest.TestCase):
    def test_the_headline_settles_at_its_own_size_not_double(self):
        from playwright.sync_api import sync_playwright
        from core import browser as _browser
        spec = _spec(_node([{"channel": "scale", "from": 1.08, "to": 1.0, "easing": "power4.out"},
                            {"channel": "opacity", "from": 0.0, "to": 1.0}]))
        r = resolve_motion_spec(validate_motion_spec(spec))
        with sync_playwright() as pw:
            b = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
            try:
                p = b.new_page(viewport={"width": 1080, "height": 1920})
                p.goto(pathlib.Path(RUNTIME, "index.html").as_uri())
                p.wait_for_function("typeof window.__loadSpec === 'function'")
                p.evaluate("s => window.__loadSpec(s)", r)
                p.evaluate("window.__seek(60)")                      # 2 s: the enter is long done
                m = p.evaluate("""() => { const h = document.querySelector('[data-motion-id="h"]');
                      const t = new DOMMatrix(getComputedStyle(h).transform); return {a: t.a, d: t.d}; }""")
            finally:
                b.close()
        self.assertAlmostEqual(m["a"], 1.0, places=2)
        self.assertAlmostEqual(m["d"], 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
