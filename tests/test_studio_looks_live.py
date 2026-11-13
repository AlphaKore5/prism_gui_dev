"""Findings from the live Studio films of 13 Nov 2026 (no network; one test drives the real browser)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402
from core import reel_web as RW  # noqa: E402

SPEC = {"design": {"css": ""}, "scenes": [
    {"seconds": 4, "html": "<div class='b'>A</div>", "css": ".b{position:absolute;left:100px;top:300px;width:880px;height:200px;"
                                                          "background:#c00;color:#fff;font-size:90px}"},
    {"seconds": 4, "html": "<div class='b'>B</div>", "css": ".b{position:absolute;left:100px;top:300px;width:880px;height:200px;"
                                                          "background:#c00;color:#fff;font-size:90px}"},
]}


class Camera(unittest.TestCase):
    """A reel whose designer holds every scene still after its entrances was measured at 82 % still
    frames; the harness itself now pushes every scene in or pulls it back."""

    def test_page_carries_the_camera(self):
        html = RW.build_html(SPEC)
        self.assertIn("var(--q, 0) * %s" % RW.CAMERA_PUSH, html)
        self.assertIn("#stage.nocam", html)       # the layout check looks at the scene at rest
        self.assertIn("--q", html)

    @unittest.skipUnless(RW.available()[0], "no browser")
    def test_scenes_travel_alternately_and_the_check_sees_them_at_rest(self):
        from playwright.sync_api import sync_playwright
        from core import browser as B
        with sync_playwright() as p:
            br = B.launch_chromium(p, args=["--hide-scrollbars"])
            try:
                page = br.new_page(viewport={"width": RW.W, "height": RW.H})
                page.set_content(RW.build_html(SPEC), wait_until="load")

                def width(t, sel):
                    page.evaluate("t => window.__seek(t)", t)
                    return page.evaluate("s => document.querySelector(s).getBoundingClientRect().width", sel)

                first = [width(t, "#s0 .b") for t in (0, 2000, 3900)]
                second = [width(t, "#s1 .b") for t in (4000 + 1, 6000, 7900)]
                self.assertLess(first[0], first[1]); self.assertLess(first[1], first[2])     # pushes in
                self.assertGreater(second[0], second[1]); self.assertGreater(second[1], second[2])   # pulls back
                self.assertAlmostEqual(first[0], 880, delta=1)
                self.assertAlmostEqual(first[2] / 880, 1 + RW.CAMERA_PUSH * 3900 / 4000, delta=0.005)
                # the check reads the scene at rest and puts the camera back afterwards
                page.evaluate("t => window.__seek(t)", 3900)
                page.evaluate("() => window.__check()")
                self.assertGreater(page.evaluate("() => document.querySelector('#s0 .b').getBoundingClientRect().width"), 880 * 1.05)
            finally:
                br.close()


def _spec(css, html):
    return {"design": {"css": ""}, "scenes": [{"seconds": 4, "html": html, "css": css}]}


@unittest.skipUnless(RW.available()[0], "no browser")
class EmptyBand(unittest.TestCase):
    """The live films left a third of the frame bare (soft: cards ending 64 % down; poster: nothing in the top half)."""

    def test_small_card_in_a_blank_frame_is_sent_back_and_a_full_layout_is_not(self):
        card = ".c{position:absolute;left:100px;width:880px;height:%dpx;top:%dpx;background:#fff;color:#000;font-size:90px}"
        small = RW.inspect(_spec(card % (300, 810), "<div class='c'>Wishing you</div>"))
        self.assertTrue(any("empty" in f and "percent" in f for f in small), small)
        top = [f for f in small if "empty" in f][0]
        self.assertIn("top 42 percent and the bottom 42 percent", top)       # centred: both ends named
        full = RW.inspect(_spec(card % (900, 400), "<div class='c'>Wishing you</div>"))
        self.assertFalse([f for f in full if "empty" in f], full)

    def test_a_full_bleed_ground_does_not_hide_the_gap(self):
        css = (".g{position:absolute;inset:0;background:#c00}"
               ".t{position:absolute;left:100px;top:700px;width:880px;height:600px;color:#fff;font-size:90px}")
        found = RW.inspect(_spec(css, "<div class='g'></div><div class='t'>Hello</div>"))
        self.assertTrue([f for f in found if "empty" in f], found)

    def test_prompt_no_longer_praises_negative_space(self):
        text = RW.design_instructions({"accent": "#C8161D"}, "x")
        self.assertNotIn("negative space carry", text)
        self.assertIn("bottom third", text)


class FontUrls(unittest.TestCase):
    def test_v1_weights_become_css2(self):
        self.assertEqual(RW.font_urls(["Anton:400"]), ["https://fonts.googleapis.com/css2?family=Anton&display=block"])
        self.assertIn("https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=block",
                      RW.font_urls(["Inter:400,700"]))


if __name__ == "__main__":
    unittest.main()
