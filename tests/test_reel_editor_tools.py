"""The layout editor's tools beyond move/scale/retype/delete.

Asked for on 2026-09-07: "edit colour, fonts and all, add images and other
things needed for editing". Four record kinds now travel in spec["edits"]
— an element's style, an added text/picture/shape, a scene's length and
background, the reel's palette and typeface — and one apply script serves
the editor and the renderer. Everything the browser sends is user input and
is checked field by field; the last class films the page and reads back
what actually rendered.
"""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_edit as E  # noqa: E402
from core import reel_web  # noqa: E402

PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlE"
       "QVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _spec() -> dict:
    return {"design": {"css": ":root{--accent:#5A8B50;--ink:#111}"},
            "scenes": [
                {"type": "hook", "seconds": 3,
                 "html": "<div class='safe'><h1>Hello</h1><p>World</p></div>"},
                {"type": "endcard", "seconds": 3, "html": "<h2>Bye</h2>"},
            ]}


def _playwright_ready() -> bool:
    return reel_web.available()[0]


class AnElementsStyle(unittest.TestCase):

    def test_the_whitelist_and_its_bounds(self):
        out = E.clean_edits([{"scene": 0, "path": [0, 0], "style": {
            "color": "#ff0000", "backgroundColor": "rgba(0,0,0,.5)",
            "fontFamily": "Libre Baskerville; url(x)", "fontSize": 9999,
            "fontWeight": "700", "fontStyle": "italic", "textAlign": "center",
            "textTransform": "uppercase", "letterSpacing": 2.25,
            "lineHeight": 1.1, "opacity": 3, "zIndex": 5, "borderRadius": 12,
            "rotate": -400, "position": "fixed", "content": "x"}}])
        st = out[0]["style"]
        self.assertEqual(st["color"], "#ff0000")
        self.assertEqual(st["fontFamily"], "Libre Baskerville")   # cut at the ';'
        self.assertEqual(st["fontSize"], 400)          # clamped
        self.assertEqual(st["opacity"], 1)
        self.assertEqual(st["rotate"], -360)
        self.assertEqual(st["zIndex"], 5)
        self.assertNotIn("position", st)
        self.assertNotIn("content", st)

    def test_a_bad_colour_or_enum_is_dropped_not_the_edit(self):
        out = E.clean_edits([{"scene": 0, "path": [0], "style": {
            "color": "red; background:url(evil)", "textAlign": "sideways",
            "fontWeight": "800"}}])
        self.assertEqual(out[0]["style"], {"fontWeight": "800"})

    def test_an_empty_value_means_back_to_the_design(self):
        out = E.clean_edits([{"scene": 0, "path": [0], "style": {"color": ""}}])
        self.assertEqual(out[0]["style"], {"color": ""})

    def test_a_style_alone_makes_the_edit_worth_keeping(self):
        self.assertEqual(len(E.clean_edits([{"scene": 0, "path": [0],
                                             "style": {"color": "#000"}}])), 1)
        self.assertEqual(E.clean_edits([{"scene": 0, "path": [0],
                                         "style": {"nope": 1}}]), [])


class SomethingAdded(unittest.TestCase):

    def test_text_picture_and_shape(self):
        out = E.clean_edits([
            {"scene": 0, "add": "text", "id": "a1", "x": 120.6, "y": 880,
             "text": "Hello", "style": {"fontSize": 72}},
            {"scene": 0, "add": "image", "id": "a2", "x": 0, "y": 0, "w": 600,
             "src": PNG},
            {"scene": 1, "add": "box", "id": "a3", "x": 10, "y": 10, "w": 400,
             "h": 300, "scale": 1.5, "hidden": True},
        ])
        self.assertEqual([e["add"] for e in out], ["text", "image", "box"])
        self.assertEqual(out[0]["x"], 121)
        self.assertEqual(out[0]["style"]["fontSize"], 72)
        self.assertEqual(out[1]["src"], PNG)
        self.assertEqual(out[2]["h"], 300)
        self.assertEqual(out[2]["scale"], 1.5)
        self.assertTrue(out[2]["hidden"])

    def test_a_picture_must_be_an_image_data_uri(self):
        for src in ("http://evil/x.png", "data:text/html;base64,PGI+", "",
                    "data:image/png;base64,not*base64"):
            self.assertEqual(E.clean_edits([{"scene": 0, "add": "image",
                                             "id": "a", "x": 0, "y": 0,
                                             "src": src}]), [], src)

    def test_an_oversized_picture_is_refused(self):
        big = "data:image/png;base64," + "A" * (E._MAX_IMAGE + 8)
        self.assertEqual(E.clean_edits([{"scene": 0, "add": "image", "id": "a",
                                         "x": 0, "y": 0, "src": big}]), [])

    def test_a_bad_id_or_kind_is_dropped(self):
        for rec in ({"scene": 0, "add": "video", "id": "a", "x": 0, "y": 0},
                    {"scene": 0, "add": "text", "id": "a b", "x": 0, "y": 0},
                    {"scene": 0, "add": "text", "id": "", "x": 0, "y": 0},
                    {"scene": 0, "add": "text", "id": "a", "x": 99999, "y": 0}):
            self.assertEqual(E.clean_edits([rec]), [], rec)


class TheSceneItself(unittest.TestCase):

    def test_length_and_background(self):
        out = E.clean_edits([{"scene": 1, "root": True, "seconds": 5.25,
                              "style": {"backgroundColor": "#fff8f0"}}])
        self.assertEqual(out, [{"scene": 1, "root": True, "seconds": 5.2,
                                "style": {"backgroundColor": "#fff8f0"}}])

    def test_a_length_outside_the_range_is_dropped(self):
        self.assertEqual(E.clean_edits([{"scene": 1, "root": True, "seconds": 40}]), [])
        self.assertEqual(E.clean_edits([{"scene": 1, "root": True}]), [])

    def test_timing_goes_into_the_spec_not_the_page(self):
        spec = _spec()
        timed = E.with_timing(spec, [{"scene": 1, "root": True, "seconds": 5.0},
                                     {"scene": 9, "root": True, "seconds": 5.0}])
        self.assertEqual(timed["scenes"][1]["seconds"], 5.0)
        self.assertEqual(spec["scenes"][1]["seconds"], 3, "the original is untouched")
        self.assertIs(E.with_timing(spec, []), spec)

    def test_the_editor_page_shows_the_saved_length(self):
        spec = _spec()
        spec["edits"] = [{"scene": 0, "root": True, "seconds": 6.0}]
        html = E.editable_html(spec)
        plan = json.loads(html.split("window.__SCENES__ = ")[1].split(";")[0])
        self.assertEqual(plan[0]["dur"], 6000)


class TheWholeReel(unittest.TestCase):

    def test_palette_variables_and_a_typeface_swap(self):
        out = E.clean_edits([{"design": True,
                              "vars": {"--accent": "#123456", "--ink": "rgb(1,2,3)",
                                       "accent": "#000", "--x": "url(evil)"},
                              "font": {"from": "Libre Baskerville", "to": "Inter;x"}}])
        self.assertEqual(out, [{"design": True,
                                "vars": {"--accent": "#123456", "--ink": "rgb(1,2,3)"},
                                "font": {"from": "Libre Baskerville", "to": "Inter"}}])

    def test_a_design_record_with_nothing_valid_is_dropped(self):
        self.assertEqual(E.clean_edits([{"design": True, "vars": {"x": "y"}}]), [])

    def test_the_apply_script_handles_every_kind(self):
        html = E.apply_edits("<html><body>r</body></html>",
                             [{"design": True, "vars": {"--accent": "#123456"}}])
        for marker in ("__edFont", "data-ed-id", "setProperty", "e.root",
                       "fonts.googleapis.com", '"--accent": "#123456"'):
            self.assertIn(marker, html)


class TheServerOnlyListensToItsOwnPage(unittest.TestCase):

    def setUp(self):
        self.saved = []
        self.url, self.stop = E.serve(_spec(), on_save=self.saved.append)

    def tearDown(self):
        self.stop()

    def _post(self, payload, headers=None):
        req = urllib.request.Request(
            self.url.rstrip("/") + "/save", method="POST",
            data=json.dumps(payload).encode() if isinstance(payload, dict) else payload,
            headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def test_its_own_origin_is_fine(self):
        self.assertEqual(self._post({"edits": []}, {"Origin": self.url.rstrip("/")}), 200)

    def test_another_origin_is_refused(self):
        # The server answers 403 without reading the request body. On Windows the close that follows can reach the
        # client as a reset (WinError 10053) before it has read the 403, so a reset is also a refusal: either way
        # nothing was saved, which is what this test is for (CI, 24-Nov-2026). The cleaner fix — draining the body
        # before the 403 — is in the engine's core/reel_edit.py, a separate repo, and is not part of this change.
        try:
            self.assertEqual(self._post({"edits": []}, {"Origin": "http://evil.test"}), 403)
        except (ConnectionError, urllib.error.URLError):
            pass
        self.assertEqual(self.saved, [])

    def test_a_body_without_edits_is_refused_rather_than_wiping_them(self):
        self.assertEqual(self._post(b"x=y"), 400)
        self.assertEqual(self._post({"other": 1}), 400)
        self.assertEqual(self.saved, [])


@unittest.skipUnless(_playwright_ready(), "playwright/browser not available")
class InARealBrowser(unittest.TestCase):

    def test_every_kind_of_edit_reaches_the_filmed_page(self):
        from playwright.sync_api import sync_playwright
        edits = E.clean_edits([
            {"scene": 0, "path": [0, 0], "style": {"color": "#ff0000", "fontSize": 90,
                                                   "fontFamily": "Georgia"}},
            {"scene": 0, "add": "text", "id": "t1", "x": 100, "y": 1200, "text": "Added line"},
            {"scene": 0, "add": "image", "id": "i1", "x": 100, "y": 100, "w": 300, "src": PNG},
            {"scene": 0, "root": True, "style": {"backgroundColor": "#112233"}},
            {"design": True, "vars": {"--accent": "#123456"}},
        ])
        html = E.apply_edits(reel_web.build_html(_spec()), edits)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1080, "height": 1920})
            page.set_content(html, wait_until="load")
            page.evaluate("t => window.__seek(t)", 1500)
            self.assertEqual(page.eval_on_selector("#s0 h1", "el => getComputedStyle(el).color"),
                             "rgb(255, 0, 0)")
            self.assertEqual(page.eval_on_selector("#s0 h1", "el => getComputedStyle(el).fontSize"),
                             "90px")
            self.assertIn("Georgia", page.eval_on_selector(
                "#s0 h1", "el => getComputedStyle(el).fontFamily"))
            self.assertEqual(page.eval_on_selector("#s0 [data-ed-id='t1']", "el => el.textContent"),
                             "Added line")
            self.assertTrue(page.eval_on_selector(
                "#s0 [data-ed-id='i1'] img", "el => el.src.startsWith('data:image/png')"))
            self.assertEqual(page.eval_on_selector("#s0", "el => getComputedStyle(el).backgroundColor"),
                             "rgb(17, 34, 51)")
            self.assertEqual(page.evaluate(
                "() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()"),
                "#123456")
            browser.close()

    def test_the_editor_adds_text_styles_it_and_saves_the_records(self):
        from playwright.sync_api import sync_playwright
        saved: list = []
        url, stop = E.serve(_spec(), on_save=saved.append)
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                page = browser.new_page(viewport={"width": 1200, "height": 800})
                page.goto(url, wait_until="load")
                page.wait_for_selector("#studio-timeline")
                page.click("#studio-add-text")
                page.wait_for_selector("#s0 [data-ed-id]")
                page.fill("#studio-size", "120")
                page.fill("#studio-text", "Fresh line")
                # The design's own headline: pick a typeface for it.
                page.click("#s0 h1")
                page.select_option("#studio-font", "Georgia")
                page.fill("#studio-seconds", "5")
                page.click("#studio-save")
                deadline = time.monotonic() + 5
                while not saved and time.monotonic() < deadline:
                    time.sleep(0.05)
                browser.close()
        finally:
            stop()
        self.assertTrue(saved)
        edits = saved[0]
        added = next(e for e in edits if e.get("add") == "text")
        self.assertEqual(added["text"], "Fresh line")
        self.assertEqual(added["style"]["fontSize"], 120)
        h1 = next(e for e in edits if e.get("element_id") == "el-1-2")
        self.assertEqual(h1["style"]["fontFamily"], "Georgia")
        scene = next(e for e in edits if e.get("root"))
        self.assertEqual(scene["seconds"], 5.0)


if __name__ == "__main__":
    unittest.main()
