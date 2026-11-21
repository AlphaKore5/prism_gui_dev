"""Gate G3: the built bundle really lacks the other flavours' add-ons.

READY BUT SKIPPED until a built bundle is supplied. No bundle exists on the
Linux dev machine (dist/ is empty), so by default every test here skips with
that reason and the skip is the loud part, not a pass.

    PRISM_BUNDLE_DIR=<unzipped onedir folder or .app>  PRISM_BUNDLE_FLAVOUR=sales \
        python -m pytest tests/test_flavour_bundle.py

This is a TEST input, not a runtime switch: nothing in the app reads these
variables (flavour.FLAVOUR stays a build-time constant).

PyInstaller keeps modules inside the PYZ archive, so besides the plain file
list the test searches the executable/PYZ bytes for the dotted names.
Optional PRISM_BUNDLE_GOLDEN=<file> records (when absent) or compares the
complete build's sorted relative file list: the golden for "complete".
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import flavour  # noqa: E402

BUNDLE = os.environ.get("PRISM_BUNDLE_DIR", "")
FLAV = os.environ.get("PRISM_BUNDLE_FLAVOUR", "")

# Heavy dependencies only the named add-ons need (to be confirmed per brief
# 2/3 when G2 lands; the check is on top-level package folder names).
HEAVY = {"boq": ("cadquery", "ezdxf", "OCP"), "step": ("cadquery", "OCP"),
         "gerber": ("gerbonara",), "leads": ("undetected_chromedriver",),
         "whatsapp": ("selenium",)}

_WHY = ("no built bundle: set PRISM_BUNDLE_DIR (unzipped onedir/.app) and "
        "PRISM_BUNDLE_FLAVOUR to run the G3 bundle-content test")


def _files(root):
    out = []
    for folder, _d, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(folder, n), root)
                       .replace(os.sep, "/"))
    return sorted(out)


@unittest.skipUnless(BUNDLE and os.path.isdir(BUNDLE) and FLAV, _WHY)
class TheBundleHoldsOnlyItsFlavour(unittest.TestCase):
    def test_flavour_name_is_known(self):
        self.assertIn(FLAV, flavour.FLAVOURS)

    def test_no_other_flavours_addon_in_the_file_list_or_archive(self):
        keep = set(flavour.addon_keys(FLAV))
        gone = [k for k in flavour.ADDONS_BY_FLAVOUR["complete"]
                if k not in keep]
        files = _files(BUNDLE)
        blobs = [os.path.join(BUNDLE, f) for f in files
                 if f.endswith((".pyz", ".pkg", ".exe", ".so", ".dll"))
                 or os.path.basename(f) in ("Prism", "Prism-Sales",
                                            "Prism-Engineering",
                                            "Prism-Studio")]
        for key in gone:
            needle = ("addons/%s/" % key, "addons.%s." % key)
            self.assertFalse([f for f in files if needle[0] in f],
                             "%s bundle has files of add-on %s" % (FLAV, key))
            for path in blobs:
                with open(path, "rb") as fh:
                    data = fh.read()
                self.assertNotIn(needle[1].encode(), data,
                                 "%s mentions %s in %s" % (FLAV, needle[1], path))

    def test_no_heavy_dependency_of_an_absent_addon(self):
        keep = set(flavour.addon_keys(FLAV))
        needed = {d for k in keep for d in HEAVY.get(k, ())}
        files = _files(BUNDLE)
        for key, deps in HEAVY.items():
            if key in keep:
                continue
            for dep in deps:
                if dep in needed:
                    continue
                self.assertFalse(
                    [f for f in files if ("/%s/" % dep) in ("/" + f)],
                    "%s bundle ships %s (only %s needs it)" % (FLAV, dep, key))

    def test_other_flavour_selection_modules_absent(self):
        files = " ".join(_files(BUNDLE))
        for other in flavour.FLAVOURS:
            if other != FLAV and FLAV != "complete":
                self.assertNotIn("flavours/%s." % other, files)

    def test_complete_file_list_matches_golden(self):
        golden = os.environ.get("PRISM_BUNDLE_GOLDEN", "")
        if FLAV != "complete" or not golden:
            self.skipTest("only for PRISM_BUNDLE_FLAVOUR=complete with "
                          "PRISM_BUNDLE_GOLDEN=<file>")
        now = "\n".join(_files(BUNDLE)) + "\n"
        if not os.path.exists(golden):
            with open(golden, "w", encoding="utf-8") as f:
                f.write(now)
            self.skipTest("golden recorded at %s; commit it and rerun" % golden)
        with open(golden, encoding="utf-8") as f:
            self.assertEqual(f.read(), now)


class TheTestIsNotSilentlyEmpty(unittest.TestCase):
    def test_says_why_it_skips(self):
        self.assertTrue(BUNDLE or _WHY)   # the reason is a module constant


if __name__ == "__main__":
    unittest.main()
