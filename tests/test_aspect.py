"""The frame a client asks for is read, put in the storyboard prompt, and respected downstream."""
from __future__ import annotations

import importlib
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.aspect import requested_frame  # noqa: E402
from core.motion import generate, measure  # noqa: E402


class Reading(unittest.TestCase):
    def test_ratios_words_and_nothing(self):
        for text, want in (("A 16:9 launch video", (1920, 1080)), ("make it 9 : 16", (1080, 1920)),
                           ("a square post for instagram", (1080, 1080)), ("4:5 feed", (1080, 1350)),
                           ("a landscape film for YouTube", (1920, 1080)), ("a vertical reel", (1080, 1920)),
                           ("TikTok ad", (1080, 1920))):
            f = requested_frame(text)
            self.assertEqual((f[1], f[2]), want, text)
        for text in ("a launch film for a CNC shop", "", "founded in 1916, 22 years"):
            self.assertIsNone(requested_frame(text), text)

    def test_an_explicit_ratio_beats_a_word(self):
        f = requested_frame("a vertical reel but actually 16:9 please")
        self.assertEqual((f[1], f[2]), (1920, 1080))


class InThePrompt(unittest.TestCase):
    def _size(self, request, skeleton=None):
        t = generate.storyboard_instructions(request, skeleton=skeleton)
        m = re.search(r'"project": \{"width": (\d+), "height": (\d+)', t)
        return (int(m.group(1)), int(m.group(2))), "FRAME:" in t

    def test_the_template_and_a_frame_note_follow_the_request(self):
        self.assertEqual(self._size("A 16:9 launch video for a shop"), ((1920, 1080), True))
        self.assertEqual(self._size("a square post"), ((1080, 1080), True))
        self.assertEqual(self._size("a launch video for a shop"), ((1080, 1920), False))

    def test_the_cinematic_profile_keeps_its_own_vertical_frame(self):
        self.assertEqual(self._size("A 16:9 launch video", skeleton="cinematic_glass"), ((1080, 1920), False))

    def test_no_prompt_text_still_says_every_frame_is_1080x1920(self):
        self.assertNotIn("1080x1920 frame", generate._rulebook(None))


def _chromium() -> bool:
    try:
        return importlib.import_module("core.motion.render")._playwright_available()
    except Exception:  # noqa: BLE001
        return False


@unittest.skipUnless(_chromium(), "Playwright's Chromium is not installed")
class LandscapeDownstream(unittest.TestCase):
    def _film(self):
        node = {"id": "t", "type": "text", "content": "Precision turned parts, delivered", "position": [960, 120],
                "font_size": 210, "font_weight": 800, "fill": "#111111", "anchor": [0.5, 0.5]}
        return {"project": {"duration": 3, "fps": 30, "width": 1920, "height": 1080, "background": "#FAF9F6"},
                "scenes": [{"id": "a", "duration": 3, "nodes": [node]}]}

    def test_a_landscape_frame_has_no_phone_chrome_bands_but_still_fits_text_to_its_width(self):
        fixed, changes = measure.fit_to_frame(self._film())
        self.assertTrue(changes and "font_size" in changes[0], changes)
        node = fixed["scenes"][0]["nodes"][0]
        self.assertLess(node["font_size"], 210)
        faults = measure.inspect_rendered(fixed, moments=(0.35, 0.75, 0.95))
        self.assertEqual([f for f in faults if "platform" in f or "bottom band" in f], [],
                         "text near the top of a landscape frame is not under a phone's status bar")
        self.assertEqual([f for f in faults if "runs off the edge" in f], [])


if __name__ == "__main__":
    unittest.main()
