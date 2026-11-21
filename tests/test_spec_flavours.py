"""prism.spec's flavour logic, proven WITHOUT a PyInstaller build.

The spec is executed in a subprocess with PyInstaller's classes replaced by
recorders (and flavour.FLAVOUR set first, as a flavour build does). What the
spec hands to Analysis(): its `excludes`, `hiddenimports` and `datas`, and
whether it refused to build, are the things a customer's bundle is made from.
A real build is NOT run here: nothing below says a frozen app starts.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import flavour  # noqa: E402

_DRIVER = r"""
import json, os, sys, types, importlib.util
import flavour
flavour.FLAVOUR = {flav!r}
calls = {{"data": [], "sub": []}}
hooks = types.ModuleType("PyInstaller.utils.hooks")
def cdf(pkg, *a, **k):
    calls["data"].append(pkg); return [("<%s>/f" % pkg, pkg)]
def csm(pkg, *a, **k):
    calls["sub"].append(pkg); return [pkg + ".sub"]
def call(pkg, *a, **k):
    calls["data"].append(pkg); return [], [], []
hooks.collect_data_files, hooks.collect_submodules, hooks.collect_all = cdf, csm, call
for n in ("PyInstaller", "PyInstaller.utils"):
    sys.modules[n] = types.ModuleType(n)
sys.modules["PyInstaller.utils.hooks"] = hooks

MISSING = set({missing!r})
_real = importlib.util.find_spec
def find_spec(name, *a, **k):
    if name.split(".")[0] in MISSING:
        return None
    return _real(name, *a, **k)
importlib.util.find_spec = find_spec

seen = {{}}
class A:
    def __init__(self, *args, **kw):
        seen.update(kw)
        self.datas, self.binaries, self.pure = [], [], []
        self.zipped_data, self.scripts = [], []
class Stub:
    def __init__(self, *a, **k): pass
g = {{"SPEC": os.path.join({root!r}, "packaging", "prism.spec"),
     "Analysis": A, "PYZ": Stub, "EXE": Stub, "COLLECT": Stub, "BUNDLE": Stub,
     "__name__": "spec"}}
os.environ["PRISM_UNLICENSED_TEST_BUILD"] = "1"
status = "built"
try:
    exec(compile(open(g["SPEC"], encoding="utf-8").read(), g["SPEC"], "exec"), g)
except SystemExit as e:
    status = "refused: %s" % (e,)
print(json.dumps({{"status": status, "excludes": seen.get("excludes"),
                  "hidden": seen.get("hiddenimports"),
                  "collected": calls["data"], "submodules": calls["sub"]}}))
"""


def _spec(flav, missing=()):
    with __import__("tempfile").TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home,
                   QT_QPA_PLATFORM="offscreen")
        r = subprocess.run(
            [sys.executable, "-c",
             _DRIVER.format(flav=flav, root=ROOT, missing=list(missing))],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-1500:]
    return json.loads(r.stdout.strip().splitlines()[-1])


# package -> what proves the spec collected it
def _collected(out, pkg):
    return pkg in out["collected"] or pkg in out["submodules"]


class DataIsConsistent(unittest.TestCase):

    def test_complete_excludes_nothing_new(self):
        self.assertEqual(flavour.package_excludes("complete"), [])
        self.assertEqual(flavour.spec_excludes("complete"), [])

    def test_always_bundled_packages_are_never_dropped(self):
        for flav in flavour.FLAVOURS:
            ex = set(flavour.spec_excludes(flav))
            for pkg in flavour.ALWAYS_BUNDLED:
                self.assertNotIn(pkg, ex, "%s drops %s" % (flav, pkg))
                self.assertTrue(flavour.bundles(pkg, flav))
        self.assertFalse(set(flavour.ALWAYS_BUNDLED) & set(flavour.PACKAGE_NEEDS))

    def test_every_need_names_a_real_add_on(self):
        for pkg, needs in flavour.PACKAGE_NEEDS.items():
            self.assertTrue(needs)
            self.assertTrue(set(needs) <= set(flavour.ADDONS_BY_FLAVOUR["complete"]))

    def test_the_owners_decisions_2026_11_21(self):
        pe = {f: set(flavour.package_excludes(f)) for f in flavour.FLAVOURS}
        # Chromium: kept in Studio and Engineering, dropped from Sales.
        self.assertIn("playwright", pe["sales"])
        self.assertNotIn("playwright", pe["studio"])
        self.assertNotIn("playwright", pe["engineering"])
        # Video encoding: dropped from Sales and Engineering, kept in Studio.
        self.assertIn("imageio_ffmpeg", pe["sales"])
        self.assertIn("imageio_ffmpeg", pe["engineering"])
        self.assertNotIn("imageio_ffmpeg", pe["studio"])
        # Engineering-only libraries: dropped from Sales and Studio only.
        eng_only = {"cadquery", "OCP", "vtkmodules", "llvmlite", "numba", "shapely"}
        self.assertTrue(eng_only <= pe["sales"])
        self.assertTrue(eng_only <= pe["studio"])
        self.assertFalse(eng_only & pe["engineering"])
        # av stays everywhere: faster_whisper imports it.
        for f in flavour.FLAVOURS:
            self.assertNotIn("av", pe[f])


class TheSpecFollowsTheData(unittest.TestCase):

    def test_each_flavour(self):
        for flav in flavour.FLAVOURS:
            with self.subTest(flavour=flav):
                # A runner that lacks exactly what this flavour drops must
                # still be allowed to build it.
                out = _spec(flav, missing=flavour.package_excludes(flav))
                self.assertEqual(out["status"], "built")
                ex = out["excludes"]
                for pkg in flavour.package_excludes(flav):
                    self.assertIn(pkg, ex)
                    self.assertFalse(_collected(out, pkg),
                                     "%s collected %s" % (flav, pkg))
                for pkg in ("playwright", "imageio_ffmpeg", "cadquery", "OCP"):
                    if flavour.bundles(pkg, flav):
                        self.assertTrue(_collected(out, pkg),
                                        "%s lost %s" % (flav, pkg))
                for pkg in flavour.ALWAYS_BUNDLED:
                    self.assertNotIn(pkg, ex)

    def test_complete_excludes_are_the_literal_and_nothing_else(self):
        out = _spec("complete")
        import test_flavour
        self.assertEqual(out["excludes"], test_flavour.GOLDEN_COMPLETE_EXCLUDES)

    def test_a_flavour_still_refuses_when_a_package_it_ships_is_missing(self):
        out = _spec("studio", missing=["playwright"])
        self.assertTrue(out["status"].startswith("refused"), out["status"])
        self.assertIn("playwright", out["status"])
        out = _spec("sales", missing=["ezdxf"])
        self.assertTrue(out["status"].startswith("refused"), out["status"])


if __name__ == "__main__":
    unittest.main()
