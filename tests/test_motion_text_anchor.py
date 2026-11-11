"""Motion's text nodes honour their anchor, in the real runtime.

The 11 Nov 2026 study (artifacts/image-video-study-2026-11-11, finding M1):
generate.py's catalogue tells the model `anchor [0, 0]` is a node's top-left
corner, inspect._node_bounds measures from that anchor, and every primitive
in runtime/primitives.js applied it — except text, which forced
translate(-50%,-50%) and so centred a left-anchored headline ON its own
left edge, cutting its first half off the frame. The checker could not see
it because it believed the anchor. These tests read the box Chromium
actually lays out, so the three parties cannot drift apart again unseen.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _text(nid, anchor, position, content="Precision in every part"):
    return {"id": nid, "type": "text", "content": content, "font_size": 96,
            "font_weight": 800, "fill": "#111111", "anchor": anchor,
            "position": position, "mode": "standard", "layer": "foreground"}


class TextAnchorInSource(unittest.TestCase):
    def test_text_no_longer_hard_codes_a_centred_transform(self):
        src = pathlib.Path(RUNTIME, "primitives.js").read_text(encoding="utf-8")
        text_cls = src[src.index("class TextNode"):src.index("class ", src.index("class TextNode") + 1)]
        self.assertNotIn('transform = "translate(-50%,-50%)"', text_cls)
        self.assertRegex(text_cls, r"translate\(\$\{-this\.anchor\[0\]")


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed — "
                     "the layout box can only be read from a real browser")
class TextAnchorInChromium(unittest.TestCase):
    """Load the runtime, seek a settled frame, read getBoundingClientRect."""

    @classmethod
    def setUpClass(cls):
        from core.motion.resolver import resolve_motion_spec
        from core.motion.schema import validate_motion_spec
        nodes = [
            {"id": "bg", "type": "light_field", "position": [540, 960], "width": 1400,
             "height": 2200, "color": "#ECE6D8", "intensity": 0.3, "layer": "background"},
            _text("tl", [0, 0], [80, 400]),
            _text("c", [0.5, 0.5], [540, 900]),
            _text("br", [1, 1], [1000, 1500]),
            {"id": "rect", "type": "shape_rect", "anchor": [0, 0], "position": [80, 1600],
             "width": 300, "height": 60, "fill": "#C8161D", "layer": "accent"},
        ]
        spec = {"project": {"duration": 2, "fps": 30, "width": 1080, "height": 1920},
                "scenes": [{"id": "one", "duration": 2, "nodes": nodes}]}
        cls.spec = resolve_motion_spec(validate_motion_spec(spec))

    def _boxes(self):
        from playwright.sync_api import sync_playwright
        from core import browser as _browser
        index = pathlib.Path(RUNTIME, "index.html")
        # Boxes in STAGE coordinates: the compiled camera curve translates
        # the whole #stage by a few px even at frame 0 with no shot named,
        # and that is the camera's business, not the anchor's.
        js = """() => {
            const stage = document.getElementById('stage').getBoundingClientRect();
            const out = {};
            for (const host of document.querySelectorAll('[data-motion-id]')) {
                const box = host.firstElementChild;
                if (!box) continue;
                const r = box.getBoundingClientRect();
                out[host.dataset.motionId] = [r.left - stage.left, r.top - stage.top,
                                              r.right - stage.left, r.bottom - stage.top];
            }
            return out;
        }"""
        with sync_playwright() as pw:
            browser = _browser.launch_chromium(
                pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
            try:
                page = browser.new_page(viewport={"width": 1080, "height": 1920})
                page.goto(index.as_uri(), wait_until="domcontentloaded")
                page.wait_for_function("typeof window.__loadSpec === 'function'", timeout=15_000)
                page.evaluate("spec => window.__loadSpec(spec)", self.spec)
                # Frame 0, on purpose: no node here has an enter block, so
                # every box is at its authored place, and the compiled
                # camera curve (which drifts the whole stage a few px by
                # mid-scene even with no shot named) has not moved yet.
                page.evaluate("window.__seek(0)")
                return page.evaluate(js)
            finally:
                browser.close()

    def test_each_anchor_pins_that_corner_of_the_laid_out_box(self):
        boxes = self._boxes()
        for nid in ("tl", "c", "br", "rect"):
            self.assertIn(nid, boxes, f"{nid} was not mounted")
        tol = 2.0
        left, top, right, bottom = boxes["tl"]
        self.assertAlmostEqual(left, 80, delta=tol, msg="[0,0]: left edge sits on x")
        self.assertAlmostEqual(top, 400, delta=tol, msg="[0,0]: top edge sits on y")
        self.assertGreater(right, 600, "a 96px headline is wide; it must run RIGHT of x, not be centred on it")
        left, top, right, bottom = boxes["c"]
        self.assertAlmostEqual((left + right) / 2, 540, delta=tol, msg="[0.5,0.5]: centred on x")
        self.assertAlmostEqual((top + bottom) / 2, 900, delta=tol, msg="[0.5,0.5]: centred on y")
        left, top, right, bottom = boxes["br"]
        self.assertAlmostEqual(right, 1000, delta=tol, msg="[1,1]: right edge sits on x")
        self.assertAlmostEqual(bottom, 1500, delta=tol, msg="[1,1]: bottom edge sits on y")
        # Text now behaves exactly like a rect with the same anchor.
        left, top, right, bottom = boxes["rect"]
        self.assertAlmostEqual(left, 80, delta=tol)
        self.assertAlmostEqual(top, 1600, delta=tol)

    def test_the_checker_and_the_browser_agree_on_a_left_anchored_headline(self):
        from core.motion import inspect as motion_inspect
        boxes = self._boxes()
        node = next(n for n in self.spec["scenes"][0]["nodes"] if n["id"] == "tl")
        est = motion_inspect._node_bounds(node, 1080, 1920)
        real = boxes["tl"]
        # The estimate is deliberately rough on width (no font metrics), but
        # it must put the box on the same SIDE of x as the browser does.
        self.assertAlmostEqual(est[0], real[0], delta=2.0)
        self.assertGreater(min(est[2], real[2]), 540)


class RenderQualityTests(unittest.TestCase):
    def test_screenshot_quality_is_the_profiled_fast_setting_and_is_used(self):
        render = importlib.import_module("core.motion.render")
        self.assertLessEqual(render.SCREENSHOT_JPEG_QUALITY, 85)
        self.assertGreaterEqual(render.SCREENSHOT_JPEG_QUALITY, 70)
        src = pathlib.Path(render.__file__).read_text(encoding="utf-8")
        self.assertNotRegex(src, re.compile(r"quality\s*=\s*95"))
        self.assertIn("quality=SCREENSHOT_JPEG_QUALITY", src)


if __name__ == "__main__":
    unittest.main()
