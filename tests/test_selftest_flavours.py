"""The frozen self-test (main.py, PRISM_SELFTEST) runs only the checks that
belong to what the build contains (flavour.SELFTEST_NEEDS).

The lists below are pinned literally. COMPLETE_SOURCE was recorded by running
the self-test of the commit before this one (d17e6a6) and must never change
for "complete". Frozen-only checks cannot run from source, so their list per
flavour is derived from the same table and pinned here too.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import flavour  # noqa: E402

COMMON_HEAD = [
    "HTTPS trust store", "stylesheet", "fonts", "logo",
    "line icons (sliders, top+bottom rows)", "engine", "engine notes",
    "config path", "mailer", "browser automation", "licence verification"]
COMMON_TAIL = [
    "video and audio player (QtMultimedia)", "main window", "sidebar"]
SKILLS = ["add-on entry points resolve", "skills (12, 9 with checkers)",
          "voice input", "reading text from pictures (RapidOCR)"]

COMPLETE_SOURCE = (
    COMMON_HEAD + ["BOQ add-on (ezdxf)", "Reel add-on (Pillow + renderer)",
                   "bundled dependencies",
                   "Studio editor + Motion runtime files"]
    + COMMON_TAIL + ["add-ons registered (10)"] + SKILLS
    + ["Prism Studio browser", "Reel encoding"])

SOURCE = {
    "complete": COMPLETE_SOURCE,
    "sales": COMMON_HEAD + ["Reel add-on (Pillow + renderer)",
                            "bundled dependencies",
                            "Studio editor + Motion runtime files"]
             + COMMON_TAIL + ["add-ons registered (6)"] + SKILLS
             + ["Prism Studio browser", "Reel encoding"],
    "engineering": COMMON_HEAD + ["BOQ add-on (ezdxf)",
                                  "Reel add-on (Pillow + renderer)",
                                  "bundled dependencies",
                                  "Studio editor + Motion runtime files"]
             + COMMON_TAIL + ["add-ons registered (6)"] + SKILLS
             + ["Prism Studio browser", "Reel encoding"],
    "studio": COMMON_HEAD + ["Reel add-on (Pillow + renderer)",
                             "bundled dependencies",
                             "Studio editor + Motion runtime files"]
             + COMMON_TAIL + ["add-ons registered (2)"] + SKILLS
             + ["Prism Studio browser", "Reel encoding"],
}

# What a FROZEN build adds, in main.py's order (Chromium, FFmpeg, then the
# availability probes), per flavour.
FROZEN_EXTRAS = {
    "complete": ["Prism Studio browser (Chromium)", "Reel encoding (FFmpeg)",
                 "Motion Graphics available", "STEP available",
                 "Gerber available"],
    "sales": ["Prism Studio browser (Chromium)", "Reel encoding (FFmpeg)",
              "Motion Graphics available"],
    "engineering": ["Prism Studio browser (Chromium)", "Reel encoding (FFmpeg)",
                    "Motion Graphics available", "STEP available",
                    "Gerber available"],
    "studio": ["Prism Studio browser (Chromium)", "Reel encoding (FFmpeg)",
               "Motion Graphics available"],
}
FROZEN_CANDIDATES = ["Prism Studio browser (Chromium)",
                     "Reel encoding (FFmpeg)", "Motion Graphics available",
                     "STEP available", "Gerber available"]


def _names(stdout):
    out = []
    for line in stdout.splitlines():
        m = re.match(r"\s+[✓✗!] (.*)$", line)
        if m:
            out.append(re.sub(r"  \(.*$", "", re.sub(r" — .*$", "", m.group(1))))
    return out


class WhichChecksEachFlavourRuns(unittest.TestCase):
    def test_complete_runs_every_check_it_ran_before(self):
        self.assertEqual(SOURCE["complete"], COMPLETE_SOURCE)
        for check in flavour.SELFTEST_NEEDS:
            self.assertTrue(flavour.selftest_runs(check, "complete"), check)

    def test_the_table_names_real_addons(self):
        for check, need in flavour.SELFTEST_NEEDS.items():
            for key in need:
                self.assertIn(key, flavour.ADDONS_BY_FLAVOUR["complete"], check)

    def test_frozen_only_checks_per_flavour(self):
        for flav, expected in FROZEN_EXTRAS.items():
            with self.subTest(flavour=flav):
                got = [c for c in FROZEN_CANDIDATES
                       if flavour.selftest_runs(c, flav)]
                self.assertEqual(got, expected)

    def test_unlisted_checks_run_in_every_flavour(self):
        for flav in flavour.FLAVOURS:
            for check in ("reading text from pictures available",
                          "Google Drive available", "dep:rapidocr",
                          "dep:openpyxl", "OS credential store available"):
                self.assertTrue(flavour.selftest_runs(check, flav), check)

    def test_the_real_selftest_prints_exactly_these_checks(self):
        code = ("import flavour, sys, runpy; flavour.FLAVOUR = {f!r};"
                "sys.argv = ['main.py'];"
                "runpy.run_path('main.py', run_name='__main__')")
        for flav, expected in SOURCE.items():
            with self.subTest(flavour=flav):
                with tempfile.TemporaryDirectory() as home:
                    env = dict(os.environ, HOME=home, USERPROFILE=home,
                               QT_QPA_PLATFORM="offscreen", PRISM_SELFTEST="1")
                    r = subprocess.run(
                        [sys.executable, "-c", code.format(f=flav)], cwd=ROOT,
                        env=env, capture_output=True, text=True, timeout=300)
                self.assertEqual(r.returncode, 0, (r.stdout + r.stderr)[-1500:])
                self.assertEqual(_names(r.stdout), expected)


if __name__ == "__main__":
    unittest.main()
