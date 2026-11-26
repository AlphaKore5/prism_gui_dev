"""The Linux AppImage name carries the flavour (all three 2.0.0 flavours once
shipped the same Prism-2.0.0-x64.AppImage). Complete keeps its old name."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packaging"))

import build  # noqa: E402
import flavour  # noqa: E402


class AppImageName(unittest.TestCase):
    def test_complete_keeps_its_name(self):
        self.assertEqual(build.appimage_name("complete", "2.0.1", "x64"),
                         "Prism-2.0.1-x64.AppImage")

    def test_every_other_flavour_names_itself(self):
        for f in flavour.FLAVOURS:
            if f != "complete":
                self.assertEqual(build.appimage_name(f, "2.0.1", "x64"),
                                 f"Prism-{f}-2.0.1-x64.AppImage")

    def test_names_differ_per_flavour(self):
        names = {build.appimage_name(f, "2.0.1", "x64") for f in flavour.FLAVOURS}
        self.assertEqual(len(names), len(flavour.FLAVOURS))

    def test_build_uses_it_and_ci_still_globs_it(self):
        with open(os.path.join(ROOT, "packaging", "build.py"), encoding="utf-8") as f:
            self.assertIn("appimage_name(FLAVOUR_BUILT", f.read())
        with open(os.path.join(ROOT, ".github", "workflows", "build.yml"), encoding="utf-8") as f:
            self.assertIn("dist/*.AppImage", f.read())


if __name__ == "__main__":
    unittest.main()
