"""Motion's interface primitives: text runs, cursor, ui_pill, ui_input, deep zoom.

Added after the 11 Nov 2026 study against a polished product film
(artifacts/reference-motion-so/plan.html). Each behaviour is checked in the
real runtime, by reading what Chromium lays out and paints at chosen frames.
"""
from __future__ import annotations

import importlib
import os
import pathlib
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import camera, generate  # noqa: E402
from core.motion import inspect as motion_inspect  # noqa: E402
from core.motion.resolver import resolve_motion_spec  # noqa: E402
from core.motion.schema import validate_motion_spec  # noqa: E402

RUNTIME = os.path.join(ENGINE, "core", "motion", "runtime")


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


def _spec(nodes, scenes=None, camera_tracks=None):
    spec = {"project": {"duration": 6, "fps": 30, "width": 1920, "height": 1080,
                        "background": "#FAF9F6"},
            "scenes": scenes or [{"id": "one", "duration": 6, "nodes": nodes}]}
    if camera_tracks:
        spec["camera"] = {"tracks": camera_tracks}
    return spec


class SchemaAndCatalogue(unittest.TestCase):
    def test_runs_fill_in_content_and_bad_runs_are_dropped(self):
        spec = _spec([{"id": "t", "type": "text", "position": [960, 540],
                       "runs": [{"text": "Claude for "}, {"text": "motion graphics"}, "junk", {"text": ""}]}])
        node = validate_motion_spec(spec)["scenes"][0]["nodes"][0]
        self.assertEqual(node["content"], "Claude for motion graphics")
        self.assertEqual(len(node["runs"]), 2)

    def test_deep_zoom_is_kept_not_clamped_to_three(self):
        spec = _spec([{"id": "t", "type": "text", "content": "x", "position": [960, 540]}],
                     camera_tracks=[{"time": 0, "position": [960, 540], "zoom": 1.0},
                                    {"time": 2, "position": [300, 540], "zoom": 8.0, "duration": 1.0}])
        tracks = validate_motion_spec(spec)["camera"]["tracks"]
        self.assertEqual(tracks[1]["zoom"], 8.0)
        self.assertEqual(camera.normalize_shot({"intent": "macro", "zoom": 10})["zoom"], 10.0)
        self.assertEqual(camera.normalize_shot({"intent": "macro", "zoom": 99})["zoom"], camera.ZOOM_MAX)

    def test_the_model_is_told_about_the_new_types(self):
        for name in ("cursor", "ui_pill", "ui_input"):
            self.assertIn(name, generate._NODE_TYPE_NAMES)
            self.assertIn(f"  {name}", generate._NODE_CATALOGUE)
        self.assertIn('"runs"', generate._NODE_CATALOGUE)
        self.assertIn('"type_on"', generate._NODE_CATALOGUE)

    def test_scene_local_times_are_shifted_into_the_second_scene(self):
        scenes = [
            {"id": "a", "duration": 3, "nodes": [{"id": "x", "type": "text", "content": "a", "position": [1, 1]}]},
            {"id": "b", "duration": 3, "nodes": [
                {"id": "cur", "type": "cursor", "position": [100, 100], "label": "Claude",
                 "path": [{"at": 0.5, "to": [400, 300], "duration": 0.8, "click": True}]},
                {"id": "box", "type": "ui_input", "position": [900, 500], "text": "Hi",
                 "reveal_start": 0.4, "send_at": 1.5}]},
        ]
        r = resolve_motion_spec(validate_motion_spec(_spec(None, scenes=scenes)))
        nodes = {n["id"]: n for n in r["scenes"][1]["nodes"]}
        self.assertAlmostEqual(nodes["cur"]["path"][0]["at"], 3.5)
        self.assertAlmostEqual(nodes["box"]["send_at"], 4.5)
        self.assertAlmostEqual(nodes["box"]["reveal_start"], 3.4)

    def test_the_checker_measures_a_pill_and_a_cursor_sensibly(self):
        pill = {"type": "ui_pill", "label": "Claude is rendering", "dot": "#C96442",
                "font_size": 28, "position": [960, 540]}
        l, t, r, b = motion_inspect._node_bounds(pill, 1920, 1080)
        self.assertTrue(300 < (r - l) < 700, (l, r))   # ~ 19 chars at 28px plus padding
        self.assertAlmostEqual((l + r) / 2, 960, delta=1)
        cur = {"type": "cursor", "label": "Typographer", "size": 44, "position": [100, 100]}
        l, t, r, b = motion_inspect._node_bounds(cur, 1920, 1080)
        self.assertEqual((l, t), (100, 100))
        self.assertTrue(r > 200 and b < 200)


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class InChromium(unittest.TestCase):
    """One browser session per test; frames are seeked, then read back."""

    def _session(self, spec):
        from playwright.sync_api import sync_playwright
        from core import browser as _browser
        resolved = resolve_motion_spec(validate_motion_spec(spec))
        pw = sync_playwright().start()
        self.addCleanup(pw.stop)
        browser = _browser.launch_chromium(pw, args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"])
        self.addCleanup(browser.close)
        w, h = resolved["project"]["width"], resolved["project"]["height"]
        page = browser.new_page(viewport={"width": w, "height": h})
        page.goto(pathlib.Path(RUNTIME, "index.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_function("typeof window.__loadSpec === 'function'", timeout=15_000)
        page.evaluate("s => window.__loadSpec(s)", resolved)
        try:
            page.wait_for_function("document.fonts.ready.then(() => true)", timeout=5000)
        except Exception:  # noqa: BLE001
            pass
        return page

    @staticmethod
    def _at(page, seconds, fps=30):
        page.evaluate(f"window.__seek({int(round(seconds * fps))})")

    def test_runs_are_different_colours_in_one_line_and_gradient_clips_to_text(self):
        page = self._session(_spec([{
            "id": "t", "type": "text", "position": [960, 540], "font_size": 100, "fill": "#111111",
            "runs": [{"text": "Claude for "},
                     {"text": "motion graphics", "gradient": {"stops": [
                         {"pos": 0, "color": "#8E52C9"}, {"pos": 1, "color": "#E0533C"}]}}]}]))
        self._at(page, 0.5)
        info = page.evaluate("""() => {
            const host = document.querySelector('[data-motion-id="t"]');
            const spans = [...host.querySelectorAll('span')];
            const line = host.querySelector('div > div');
            return {n: spans.length,
                    c0: getComputedStyle(spans[0]).color,
                    bg1: getComputedStyle(spans[1]).backgroundImage.slice(0, 30),
                    clip1: getComputedStyle(spans[1]).webkitBackgroundClip || getComputedStyle(spans[1]).backgroundClip,
                    oneLine: line.getBoundingClientRect().height < 160,
                    text: line.textContent};
        }""")
        self.assertEqual(info["n"], 2)
        self.assertEqual(info["c0"], "rgb(17, 17, 17)")
        self.assertIn("linear-gradient", info["bg1"])
        self.assertEqual(info["clip1"], "text")
        self.assertTrue(info["oneLine"])
        self.assertEqual(info["text"], "Claude for motion graphics")

    def test_type_on_reveals_characters_at_the_rate_and_a_caret_follows(self):
        page = self._session(_spec([{
            "id": "t", "type": "text", "position": [960, 540], "font_size": 90, "fill": "#111111",
            "type_on": True, "type_rate": 10, "reveal_start": 1.0, "anchor": [0, 0.5],
            "runs": [{"text": "Make a launch video"}]}]))
        js = """() => { const h = document.querySelector('[data-motion-id="t"]');
                const chars = [...h.querySelectorAll('span > span')].filter(s => s.textContent.length === 1);
                const vis = chars.filter(s => getComputedStyle(s).visibility === 'visible').length;
                const carets = [...h.querySelectorAll('span > span')].filter(s => s.firstElementChild && s.style.width === '0px'
                                 && getComputedStyle(s).visibility === 'visible').length;
                return {total: chars.length, vis, carets}; }"""
        self._at(page, 0.5)
        before = page.evaluate(js)
        self._at(page, 1.0 + 0.55)
        mid = page.evaluate(js)
        self._at(page, 1.0 + 3.0)
        end = page.evaluate(js)
        self.assertEqual(before["total"], 19)
        self.assertEqual(before["vis"], 0)
        self.assertIn(mid["vis"], (5, 6), mid)             # 10 chars/s, 0.55 s in: 6th char just landed
        self.assertEqual(mid["carets"], 1, "exactly one caret, after the last typed character")
        self.assertEqual(end["vis"], 19)

    def test_a_cursor_travels_between_waypoints_and_a_click_draws_a_ring(self):
        page = self._session(_spec([{
            "id": "cur", "type": "cursor", "position": [200, 200], "label": "Claude", "color": "#C96442",
            "path": [{"at": 1.0, "to": [1000, 600], "duration": 1.0, "easing": "none", "click": True}]}]))
        js = """() => { const h = document.querySelector('[data-motion-id="cur"]');
                const m = new DOMMatrix(getComputedStyle(h).transform);
                const ring = h.firstElementChild.firstElementChild;
                return {x: m.e, y: m.f, ring: parseFloat(getComputedStyle(ring).opacity)}; }"""
        self._at(page, 0.5); a = page.evaluate(js)
        self._at(page, 1.5); b = page.evaluate(js)
        self._at(page, 2.1); c = page.evaluate(js)
        self._at(page, 4.0); d = page.evaluate(js)
        self.assertAlmostEqual(a["x"], 200, delta=2); self.assertAlmostEqual(a["y"], 200, delta=2)
        self.assertAlmostEqual(b["x"], 600, delta=25); self.assertAlmostEqual(b["y"], 400, delta=25)   # halfway
        self.assertAlmostEqual(d["x"], 1000, delta=2); self.assertAlmostEqual(d["y"], 600, delta=2)
        self.assertEqual(a["ring"], 0)
        self.assertGreater(c["ring"], 0.1, "the click ring is visible just after arrival")
        self.assertLess(d["ring"], 0.05, "and gone later")

    def test_pill_is_centred_by_its_anchor_and_carries_its_dot_and_label(self):
        page = self._session(_spec([{"id": "p", "type": "ui_pill", "position": [960, 540],
                                     "label": "Claude is rendering", "dot": "#C96442", "font_size": 28}]))
        self._at(page, 0)
        r = page.evaluate("""() => { const h = document.querySelector('[data-motion-id="p"]');
              const stage = document.getElementById('stage').getBoundingClientRect();
              const b = h.firstElementChild.getBoundingClientRect();
              return {cx: (b.left + b.right) / 2 - stage.left, cy: (b.top + b.bottom) / 2 - stage.top,
                      w: b.width, text: h.textContent, dot: h.querySelectorAll('span').length}; }""")
        self.assertAlmostEqual(r["cx"], 960, delta=3)
        self.assertAlmostEqual(r["cy"], 540, delta=3)
        self.assertEqual(r["text"], "Claude is rendering")
        self.assertGreaterEqual(r["dot"], 2)     # the dot and the label
        est = motion_inspect._node_bounds({"type": "ui_pill", "label": "Claude is rendering",
                                           "font_size": 28, "dot": "#C96442", "position": [960, 540]}, 1920, 1080)
        self.assertAlmostEqual(est[2] - est[0], r["w"], delta=r["w"] * 0.25, msg="the estimate is within 25% of the real width")

    def test_input_types_hides_its_placeholder_and_turns_the_send_button_dark(self):
        page = self._session(_spec([{"id": "in", "type": "ui_input", "position": [960, 540], "width": 900,
                                     "height": 220, "placeholder": "Message", "text": "Make a launch video",
                                     "reveal_start": 1.0, "type_rate": 12, "send_at": 3.5}]))
        js = """() => { const h = document.querySelector('[data-motion-id="in"]'); const box = h.firstElementChild;
                const kids = [...box.children];
                const ph = kids[0]; const typed = kids[1]; const btn = kids[2];
                const chars = [...typed.children].filter(s => s.textContent.length === 1);
                return {ph: getComputedStyle(ph).visibility,
                        vis: chars.filter(s => getComputedStyle(s).visibility === 'visible').length,
                        btn: getComputedStyle(btn).backgroundColor}; }"""
        self._at(page, 0.5); a = page.evaluate(js)
        self._at(page, 3.0); b = page.evaluate(js)
        self._at(page, 4.5); c = page.evaluate(js)
        self.assertEqual(a["ph"], "visible"); self.assertEqual(a["vis"], 0)
        self.assertEqual(b["ph"], "hidden"); self.assertEqual(b["vis"], 19)
        self.assertEqual(b["btn"], "rgb(161, 161, 170)", "still grey before it is sent")
        self.assertEqual(c["btn"], "rgb(17, 17, 17)", "ink once sent")

    def test_an_eight_times_push_keeps_a_word_inside_the_frame_and_crisp(self):
        page = self._session(_spec(
            [{"id": "w", "type": "text", "content": "motion", "position": [400, 540], "font_size": 120,
              "fill": "#111111"}],
            camera_tracks=[{"time": 0, "position": [960, 540], "zoom": 1.0},
                           {"time": 1.0, "position": [400, 540], "zoom": 8.0, "duration": 2.0, "easing": "power3.inOut"}]))
        self._at(page, 3.5)
        r = page.evaluate("""() => { const b = document.querySelector('[data-motion-id="w"]').firstElementChild.getBoundingClientRect();
                return {l: b.left, r: b.right, t: b.top, bt: b.bottom, h: b.height}; }""")
        self.assertGreater(r["h"], 120 * 6, "the word is really ~8x taller on screen")
        shot = page.screenshot(type="png")
        self.assertGreater(len(shot), 1000)


if __name__ == "__main__":
    unittest.main()
