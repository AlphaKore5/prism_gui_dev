"""Motion's is_available() answers for the same two paths render() has.

Study of 11 Nov 2026 (finding M5): a bare `node` on PATH made is_available()
say yes; render() then needed Playwright's Chromium or an Electron binary
and raised "No headless browser available" after the storyboard had been
written. The check must never pass a machine the render would fail on.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

import importlib  # noqa: E402

# core.motion exports render() the function; the module is reached by name.
render = importlib.import_module("core.motion.render")


class IsAvailableMatchesRender(unittest.TestCase):
    def setUp(self):
        self._ff = mock.patch("core.ffmpeg.locate", return_value=sys.executable)
        self._ff.start()
        self.addCleanup(self._ff.stop)

    def test_node_alone_is_not_a_renderer(self):
        with mock.patch.object(render, "_playwright_available", return_value=False), \
                mock.patch.object(render, "_find_electron_binary", return_value=None), \
                mock.patch.object(render.shutil, "which", return_value="/usr/bin/node"):
            ok, why = render.is_available()
        self.assertFalse(ok)
        self.assertIn("playwright install chromium", why)

    def test_playwright_chromium_is_enough(self):
        with mock.patch.object(render, "_playwright_available", return_value=True), \
                mock.patch.object(render, "_find_electron_binary", return_value=None):
            self.assertEqual(render.is_available(), (True, ""))

    def test_an_electron_binary_is_enough(self):
        with mock.patch.object(render, "_playwright_available", return_value=False), \
                mock.patch.object(render, "_find_electron_binary", return_value="/opt/electron"):
            self.assertEqual(render.is_available(), (True, ""))

    def test_no_ffmpeg_is_named_first(self):
        with mock.patch("core.ffmpeg.locate", return_value=""):
            ok, why = render.is_available()
        self.assertFalse(ok)
        self.assertIn("FFmpeg", why)


if __name__ == "__main__":
    unittest.main()
