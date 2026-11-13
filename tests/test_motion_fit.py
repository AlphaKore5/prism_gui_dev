"""Motion fits text into the frame itself, and checks more than one moment.

12 Nov 2026: a film the model wrote shipped a headline 1,470 px wide in a
1,080 px frame and a 1,378 px phone number. The checker named both; the
repair loop kept the "cleaner" scene after two rounds. core.motion.measure
.fit_to_frame measures in the real runtime with the camera off and fixes it.
"""
from __future__ import annotations

import copy
import importlib
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import camera, measure  # noqa: E402


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _text(nid, content, x, y=900, size=120, anchor=(0.5, 0.5), **extra):
    node = {"id": nid, "type": "text", "content": content, "position": [x, y], "font_size": size,
            "font_weight": 800, "fill": "#111111", "anchor": list(anchor), "layer": "foreground"}
    node.update(extra)
    return node


def _spec(*scenes, camera=None):
    spec = {"project": {"duration": 3 * len(scenes), "fps": 30, "width": 1080, "height": 1920,
                        "background": "#FAF9F6"},
            "scenes": [{"id": f"s{i}", "duration": 3, "nodes": nodes} for i, nodes in enumerate(scenes)]}
    if camera:
        spec["camera"] = {"tracks": camera}
    return spec


class WithoutABrowser(unittest.TestCase):
    def test_no_browser_means_no_change_and_no_error(self):
        spec = _spec([_text("a", "A very long headline that will not fit anywhere", 540)])
        with mock.patch("core.motion.render._playwright_available", return_value=False):
            out, changes = measure.fit_to_frame(spec)
        self.assertEqual(changes, [])
        self.assertEqual(out["scenes"][0]["nodes"][0]["font_size"], 120)


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class FitInChromium(unittest.TestCase):
    def _width_after(self, spec, nid="a", scene=0):
        """The laid-out width of a node, with the camera off, after fitting."""
        from playwright.sync_api import sync_playwright
        from core import browser as _browser
        import pathlib
        from core.motion.resolver import resolve_motion_spec
        r = resolve_motion_spec(copy.deepcopy(spec))
        r.pop("camera", None)
        with sync_playwright() as pw:
            b = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
            try:
                p = b.new_page(viewport={"width": 1080, "height": 1920})
                p.goto(pathlib.Path(measure.__file__).with_name("runtime").joinpath("index.html").as_uri())
                p.wait_for_function("typeof window.__loadSpec === 'function'")
                p.evaluate("s => window.__loadSpec(s)", r)
                try:
                    p.wait_for_function("document.fonts.ready.then(() => true)", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
                return p.evaluate("""([i, id]) => { const sw = window.__runtime.sceneWindows[i]; sw.el.style.display = '';
                    const h = [...sw.el.children].find(c => c.dataset.motionId === id);
                    const m = new DOMMatrix(getComputedStyle(h).transform);
                    const w = h.firstElementChild.offsetWidth;
                    return {w, x: m.e}; }""", [scene, nid])
            finally:
                b.close()

    def test_a_headline_wider_than_the_frame_is_scaled_to_fit_the_margins(self):
        spec = _spec([_text("a", "Twenty-two years of precision", 540, size=150)])
        before = self._width_after(__import__("core.motion.schema", fromlist=["x"]).validate_motion_spec(copy.deepcopy(spec)))
        self.assertGreater(before["w"], 1080, "the premise: it really is wider than the frame")
        fixed, changes = measure.fit_to_frame(spec)
        self.assertTrue(changes and "font_size" in changes[0], changes)
        after = self._width_after(fixed)
        self.assertLessEqual(after["w"], 1080 * 0.88 + 2)
        self.assertGreater(after["w"], 1080 * 0.88 * 0.9, "scaled to fit, not crushed")
        self.assertLess(fixed["scenes"][0]["nodes"][0]["font_size"], 150)

    def test_text_that_already_fits_is_left_alone(self):
        spec = _spec([_text("a", "Fits fine", 540, size=100)])
        fixed, changes = measure.fit_to_frame(spec)
        self.assertEqual(changes, [])
        self.assertEqual(fixed["scenes"][0]["nodes"][0]["font_size"], 100)
        self.assertEqual(fixed["scenes"][0]["nodes"][0]["position"], [540, 900])

    def test_a_narrow_node_placed_past_the_edge_is_nudged_inside(self):
        spec = _spec([_text("a", "Quote", 1060, size=90)])             # centre anchor at 1060: half is off the right
        fixed, changes = measure.fit_to_frame(spec)
        self.assertTrue(any("moved" in c for c in changes), changes)
        w = self._width_after(fixed)["w"]
        x = fixed["scenes"][0]["nodes"][0]["position"][0]
        self.assertLessEqual(x + w / 2, 1080 * 0.94 + 1)
        self.assertEqual(fixed["scenes"][0]["nodes"][0]["font_size"], 90, "moved, not shrunk")

    def test_a_left_anchored_wide_line_is_fitted_from_its_own_anchor(self):
        spec = _spec([_text("a", "+91 98765 43210 call us today", 70, size=140, anchor=(0, 0.5))])
        fixed, changes = measure.fit_to_frame(spec)
        w = self._width_after(fixed)["w"]
        x = fixed["scenes"][0]["nodes"][0]["position"][0]
        self.assertGreaterEqual(x, 1080 * 0.06 - 1)
        self.assertLessEqual(x + w, 1080 * 0.94 + 1)

    def test_the_camera_is_ignored_so_a_deliberate_push_does_not_shrink_text(self):
        spec = _spec([_text("a", "Precision", 540, size=120)],
                     camera=[{"time": 0, "position": [540, 960], "zoom": 1.0},
                             {"time": 1.0, "position": [540, 900], "zoom": 3.0, "duration": 1.0}])
        fixed, changes = measure.fit_to_frame(spec)
        self.assertEqual(changes, [], "it fits at 1x; the push is the author's choice")

    def test_scenes_that_reuse_a_node_id_are_fitted_separately(self):
        spec = _spec([_text("headline", "Short", 540, size=100)],
                     [_text("headline", "A much much longer headline than fits", 540, size=140)])
        fixed, changes = measure.fit_to_frame(spec)
        self.assertEqual(fixed["scenes"][0]["nodes"][0]["font_size"], 100)
        self.assertLess(fixed["scenes"][1]["nodes"][0]["font_size"], 140)

    def test_fitting_twice_changes_nothing_more(self):
        spec = _spec([_text("a", "Twenty-two years of precision", 540, size=150)])
        once, _ = measure.fit_to_frame(spec)
        twice, again = measure.fit_to_frame(once)
        self.assertEqual(again, [])
        self.assertEqual(once["scenes"][0]["nodes"][0]["font_size"], twice["scenes"][0]["nodes"][0]["font_size"])

    def test_coloured_runs_are_fitted_too(self):
        spec = _spec([_text("a", "", 540, size=150, runs=[{"text": "Twenty-two "}, {"text": "years of precision"}])])
        fixed, changes = measure.fit_to_frame(spec)
        self.assertTrue(changes)
        self.assertLessEqual(self._width_after(fixed)["w"], 1080 * 0.88 + 2)

    def test_fit_stores_content_boxes_and_the_resolved_camera_then_keeps_copy_in_frame(self):
        scenes = [[_text("t", f"Scene {i} headline here", 540, y=900, size=110)] for i in range(4)]
        scenes.append([_text("name", "Shree Precision\nEngineering.", 540, y=520, size=96),
                       _text("phone", "+91 98765 43210", 228, y=1000, size=56, anchor=(0, 0.5))])
        spec = _spec(*scenes)
        for i, sc in enumerate(spec["scenes"]):
            sc["shot"] = {"intent": "push", "target": [540, 1000]} if i < 4 else {"intent": "hold"}
        fixed, _ = measure.fit_to_frame(spec)
        self.assertEqual(len(fixed["_content_boxes"]), 5)
        self.assertTrue(all(b is None or b[2] > b[0] for b in fixed["_content_boxes"]))
        faults = measure.inspect_rendered(fixed, moments=(0.35, 0.75, 0.95))
        self.assertEqual([f for f in faults if "runs off the edge" in f], [], faults)

    def test_the_checker_reports_a_fault_that_persists_but_not_one_that_is_passing_through(self):
        # Wide and static: off the edge at every moment -> reported.
        wide = _spec([_text("wide", "Twenty-two years of precision", 540, size=150)])
        faults = measure.inspect_rendered(wide, moments=(0.35, 0.75, 0.95))
        self.assertTrue(any('"wide"' in f and "runs off the edge" in f for f in faults), faults)
        # Fitted: nothing to report.
        fixed, _ = measure.fit_to_frame(wide)
        self.assertEqual([f for f in measure.inspect_rendered(fixed, moments=(0.35, 0.75, 0.95))
                          if "runs off the edge" in f], [])
        # Sliding in from far off-screen for the first 1.2 s: only the first
        # sample (0.35 of 3 s = 1.05 s) sees it outside -> not reported.
        sliding = _spec([_text("slide", "Slides in", 540, size=100, animation={"enter": {
            "time": 0.0, "duration": 1.2, "tweens": [{"channel": "x", "from": -1500, "to": 0,
                                                        "easing": "power2.out"}]}})])
        self.assertEqual([f for f in measure.inspect_rendered(sliding, moments=(0.35, 0.75, 0.95))
                          if '"slide"' in f], [])


class CameraKeepsCopyInView(unittest.TestCase):
    """core.motion.camera.keep_in_view and the compile that uses it (pure Python)."""

    def test_zoom_is_capped_to_what_the_copy_allows_and_never_below_one(self):
        # A 700x400 box with a plain 4 % margin: width is the limit, 1080 / (700 + 2*43.2) = 1.3733.
        pos, z = camera.keep_in_view((540, 960), 1.75, [190, 760, 890, 1160], 1080, 1920, margin=0.04)
        self.assertAlmostEqual(z, 1.3733, places=3)
        # With no margin given the platform's safe area is used (6 % sides, 11 % top, 20 % bottom).
        pos2, z2 = camera.keep_in_view((540, 960), 1.75, [190, 760, 890, 1160], 1080, 1920)
        self.assertAlmostEqual(z2, 1080 / (700 + 2 * 64.8), places=2)
        # A narrow box lets the author's own zoom stand.
        pos, z = camera.keep_in_view((540, 960), 1.5, [390, 860, 690, 1060], 1080, 1920)
        self.assertAlmostEqual(z, 1.5)
        # A box nearly as wide as the frame allows only ~1.0x.
        pos, z = camera.keep_in_view((540, 960), 1.75, [60, 800, 1020, 1100], 1080, 1920)
        self.assertLess(z, 1.1)
        self.assertGreaterEqual(z, 1.0)
        # Wider than the frame at 1x: pull-out is the text-fit pass's job; zoom stays 1.0, centre on the box.
        pos, z = camera.keep_in_view((540, 960), 1.5, [-100, 800, 1180, 1100], 1080, 1920)
        self.assertEqual(z, 1.0)
        self.assertAlmostEqual(pos[0], 540, delta=1)

    def test_the_centre_is_clamped_so_the_box_stays_in_view(self):
        (cx, cy), z = camera.keep_in_view((540, 1250), 1.75, [228, 400, 624, 1035], 1080, 1920)
        hw, hh = 1080 / (2 * z), 1920 / (2 * z)
        # Inside the safe area, not just the frame: top 11 % (211 px) and bottom 20 % (384 px) stay clear.
        self.assertLessEqual(cy - hh, 400 - 0.11 * 1920 + 1)
        self.assertGreaterEqual(cy + hh, 1035 + 0.20 * 1920 - 1)
        self.assertLessEqual(cx - hw, 228 - 0.06 * 1080 + 1)
        self.assertGreaterEqual(cx + hw, 624 + 0.06 * 1080 - 1)

    def test_compounding_pushes_and_a_final_hold_do_not_film_copy_out_of_frame(self):
        scenes = [{"start": i * 3.0, "duration": 3.0, "shot": {"intent": "push", "target": [540, 1000]}}
                  for i in range(4)] + [{"start": 12.0, "duration": 4.0, "shot": {"intent": "hold"}}]
        boxes = [[100, 600, 980, 1200]] * 4 + [[228, 400, 624, 1035]]
        free = camera.compile_tracks(scenes, 1080, 1920, {})
        guarded = camera.compile_tracks(scenes, 1080, 1920, {}, content_boxes=boxes)
        self.assertGreater(free[-1]["zoom"], 1.7, "the premise: unguarded it compounds to 1.75x")
        self.assertLess(guarded[-1]["zoom"], 1.3)
        z = guarded[-1]["zoom"]; cx, cy = guarded[-1]["position"]
        self.assertLessEqual(cy - 1920 / (2 * z), 400)
        self.assertGreaterEqual(cy + 1920 / (2 * z), 1035)

    def test_crop_true_means_the_close_up_is_deliberate(self):
        scenes = [{"start": 0.0, "duration": 3.0, "shot": {"intent": "macro", "target": [540, 960], "zoom": 4.0, "crop": True}}]
        tracks = camera.compile_tracks(scenes, 1080, 1920, {}, content_boxes=[[100, 700, 980, 1200]])
        self.assertEqual(tracks[-1]["zoom"], 4.0)


if __name__ == "__main__":
    unittest.main()
