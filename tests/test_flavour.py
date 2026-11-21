"""Build flavours (gate G1 of the module split): which add-ons each build has.

flavour.FLAVOUR is baked in at build time and never read from the environment,
so these tests set it inside a SUBPROCESS before addons.registry is imported,
which is exactly what a flavour build does. HOME is a sandbox throughout.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import flavour  # noqa: E402

ALL = ("inquiry", "boq", "gerber", "step", "bom", "email", "leads",
       "whatsapp", "reel", "motion")

# Pinned explicitly (not derived from flavour.py) so that editing the table
# alone cannot change what a customer's build contains.
EXPECTED = {
    "complete": set(ALL),
    "studio": {"reel", "motion"},
    "sales": {"inquiry", "email", "leads", "whatsapp"},
    "engineering": {"boq", "bom", "step", "gerber"},
}

# The complete build's shelves and registry order, exactly as before flavours
# (the order is (manifest order, key); bom is status OFF so it is on neither).
COMPLETE_ORDER = ["inquiry", "boq", "gerber", "step", "email", "leads",
                  "whatsapp", "reel", "motion", "bom"]
COMPLETE_RAIL = ["inquiry", "boq", "gerber", "step", "email", "leads",
                 "whatsapp"]
COMPLETE_HOME = COMPLETE_RAIL + ["reel", "motion"]

# prism.spec's `excludes` as it was at ade955a, before flavours (recorded from
# `git show ade955a:packaging/prism.spec`). For "complete" it must not change.
GOLDEN_COMPLETE_EXCLUDES = [
    'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.Qt3DCore',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
    'PySide6.QtWebEngine', 'PySide6.QtCharts', 'PySide6.QtDataVisualization',
    'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning',
    'PySide6.QtSensors', 'PySide6.QtSerialPort', 'PySide6.QtTest',
    'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtSql',
    'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPdf',
    'PySide6.QtPdfWidgets', 'PySide6.QtSpatialAudio',
    'PySide6.QtTextToSpeech', 'shiboken6.support', 'tkinter', 'scipy',
    'pandas', 'IPython', 'pytest', 'notebook']

_WINDOW = r"""
import json, sys
from unittest import mock
import flavour
flavour.FLAVOUR = {flav!r}
import main_window
import widgets.sidebar as sidebar
import widgets.home_panel as home_panel
from PySide6.QtWidgets import QApplication
app = QApplication.instance() or QApplication([])
with mock.patch.object(main_window.MainWindow, "_first_run"):
    win = main_window.MainWindow()
print(json.dumps({{
    "rail": [r[0] for r in sidebar.ADDONS],
    "home": [r[0] for r in home_panel.ADDONS],
    "panels": sorted(k for k in {allkeys!r}
                     if getattr(win, k + "_panel", None) is not None),
    "loaded": sorted(m for m in sys.modules if m.startswith("addons.")),
}}))
"""

_PROBE = r"""
import json, sys
import flavour
flavour.FLAVOUR = {flav!r}
{tamper}
from addons import registry
print(json.dumps({{
    "keys": sorted(a.key for a in registry.REGISTRY),
    "expected": registry.EXPECTED,
    "loaded": sorted(m for m in sys.modules if m.startswith("addons.")),
    "walk": list(registry.addon_modules()),
}}))
"""


def _run(flav, tamper=""):
    with tempfile.TemporaryDirectory() as home:
        env = dict(os.environ, HOME=home, USERPROFILE=home,
                   QT_QPA_PLATFORM="offscreen")
        return subprocess.run(
            [sys.executable, "-c", _PROBE.format(flav=flav, tamper=tamper)],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)


class TheShippedConstant(unittest.TestCase):
    def test_the_repository_ships_complete(self):
        with open(os.path.join(ROOT, "flavour.py"), encoding="utf-8") as f:
            self.assertIn('\nFLAVOUR = "complete"', f.read())
        self.assertEqual(flavour.FLAVOUR, "complete")

    def test_flavour_table_matches_the_pinned_contents(self):
        self.assertEqual({k: set(v) for k, v in flavour.ADDONS_BY_FLAVOUR.items()},
                         EXPECTED)

    def test_flavour_is_not_read_from_the_environment(self):
        with open(os.path.join(ROOT, "flavour.py"), encoding="utf-8") as f:
            text = f.read()
        for needle in ("os.environ", "getenv", "import os"):
            self.assertNotIn(needle, text)


class EachFlavourContainsExactlyItsAddOns(unittest.TestCase):
    def test_registry_keys_and_nothing_else_loaded(self):
        for flav, keep in EXPECTED.items():
            with self.subTest(flavour=flav):
                r = _run(flav)
                self.assertEqual(r.returncode, 0, r.stderr[-800:])
                out = json.loads(r.stdout.strip().splitlines()[-1])
                self.assertEqual(set(out["keys"]), keep)
                self.assertEqual(out["expected"], len(keep))
                for key in set(ALL) - keep:
                    prefix = "addons." + key
                    self.assertFalse(
                        [m for m in out["loaded"]
                         if m == prefix or m.startswith(prefix + ".")],
                        "%s build imported the %s add-on" % (flav, key))
                    self.assertFalse(
                        [m for m in out["walk"]
                         if m == prefix or m.startswith(prefix + ".")],
                        "%s build would bundle the %s add-on" % (flav, key))
                for other in set(EXPECTED) - {flav}:
                    self.assertNotIn("addons.flavours." + other, out["walk"])
                self.assertIn("addons.flavours." + flav, out["walk"])


class CompleteIsExactlyToday(unittest.TestCase):
    def test_add_on_set_and_order(self):
        r = _run("complete")
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["keys"], sorted(COMPLETE_ORDER))
        self.assertEqual(out["expected"], 10)
        code = ("import flavour; flavour.FLAVOUR='complete';"
                "from addons import registry;"
                "print([a.key for a in registry.REGISTRY])")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(ast.literal_eval(r.stdout.strip()), COMPLETE_ORDER)

    def _spec_excludes_literal(self):
        with open(os.path.join(ROOT, "packaging", "prism.spec"),
                  encoding="utf-8") as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and getattr(node.targets[0], "id", "") == "excludes"):
                self.assertIsInstance(node.value, ast.BinOp)
                self.assertEqual(node.value.left.id, "_other_addons")
                return ast.literal_eval(node.value.right)
        self.fail("prism.spec has no `excludes = ...`")

    def test_spec_exclusion_list_for_complete_is_unchanged(self):
        """The spec builds `excludes = _other_addons + [literal]`. For
        complete, _other_addons is flavour.spec_excludes() == [] , so the list
        is the literal, which must equal the recorded pre-flavour list."""
        self.assertEqual(flavour.spec_excludes("complete"), [])
        self.assertEqual(flavour.spec_excludes(), [])   # shipped default
        self.assertEqual(self._spec_excludes_literal(),
                         GOLDEN_COMPLETE_EXCLUDES)
        with open(os.path.join(ROOT, "packaging", "prism.spec"),
                  encoding="utf-8") as f:
            self.assertIn("_other_addons = _flavour.spec_excludes()", f.read())

    def test_other_flavours_exclude_what_they_do_not_have(self):
        for flav, keep in EXPECTED.items():
            if flav == "complete":
                continue
            with self.subTest(flavour=flav):
                ex = flavour.spec_excludes(flav)
                for k in set(ALL) - keep:
                    self.assertIn("addons." + k, ex)
                for k in keep:
                    self.assertNotIn("addons." + k, ex)
                for other in set(EXPECTED) - {flav}:
                    # includes flavours.complete: it imports ALL ten add-ons,
                    # so a Sales bundle that kept it would contain BOQ.
                    self.assertIn("addons.flavours." + other, ex)
                self.assertNotIn("addons.flavours." + flav, ex)


class EachFlavourStartsAWindowWithOnlyItsAddOns(unittest.TestCase):
    def test_window_rail_home_and_panels(self):
        allkeys = [k for k in ALL if k != "bom"] + ["bom"]
        for flav, keep in EXPECTED.items():
            with self.subTest(flavour=flav):
                with tempfile.TemporaryDirectory() as home:
                    env = dict(os.environ, HOME=home, USERPROFILE=home,
                               QT_QPA_PLATFORM="offscreen")
                    env.pop("PRISM_SELFTEST", None)
                    r = subprocess.run(
                        [sys.executable, "-c",
                         _WINDOW.format(flav=flav, allkeys=allkeys)],
                        cwd=ROOT, env=env, capture_output=True, text=True,
                        timeout=300)
                self.assertEqual(r.returncode, 0, r.stderr[-1200:])
                out = json.loads(r.stdout.strip().splitlines()[-1])
                self.assertEqual(out["rail"],
                                 [k for k in COMPLETE_RAIL if k in keep])
                self.assertEqual(out["home"],
                                 [k for k in COMPLETE_HOME if k in keep])
                self.assertEqual(set(out["panels"]) - {"reel", "motion"},
                                 keep - {"reel", "motion"})
                for key in set(ALL) - keep:
                    self.assertFalse(
                        [m for m in out["loaded"]
                         if m == "addons." + key
                         or m.startswith("addons." + key + ".")],
                        "%s window imported add-on %s" % (flav, key))

    def test_packaged_style_selftest_passes_per_flavour(self):
        """main.py's PRISM_SELFTEST (what packaging/smoke_test.py runs against
        a built app) with the flavour baked, one subprocess each. It asserts
        the registered add-on count against the flavour table."""
        code = ("import flavour, sys, runpy; flavour.FLAVOUR = {f!r};"
                "sys.argv = ['main.py'];"
                "runpy.run_path('main.py', run_name='__main__')")
        for flav, keep in EXPECTED.items():
            with self.subTest(flavour=flav):
                with tempfile.TemporaryDirectory() as home:
                    env = dict(os.environ, HOME=home, USERPROFILE=home,
                               QT_QPA_PLATFORM="offscreen", PRISM_SELFTEST="1")
                    r = subprocess.run(
                        [sys.executable, "-c", code.format(f=flav)],
                        cwd=ROOT, env=env, capture_output=True, text=True,
                        timeout=300)
                self.assertEqual(r.returncode, 0,
                                 (r.stdout + r.stderr)[-1500:])
                self.assertIn("add-ons registered (%d)" % len(keep), r.stdout)
                self.assertNotIn("✗", r.stdout)


class AWrongFlavourFailsLoudly(unittest.TestCase):
    def test_unknown_flavour_raises(self):
        r = _run("bogus")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown build flavour", r.stderr)

    def test_a_flavour_module_that_disagrees_with_the_table_raises(self):
        tamper = ("flavour.ADDONS_BY_FLAVOUR = dict(flavour.ADDONS_BY_FLAVOUR, "
                  "sales=('inquiry', 'email'))")
        r = _run("sales", tamper)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("flavour 'sales'", r.stderr)


class OneMachineIsOneSeatWhateverTheFlavour(unittest.TestCase):
    """licensing/device.py must not look at the flavour at all."""

    def test_device_fingerprint_is_identical_across_flavours(self):
        code = ("import json, flavour; flavour.FLAVOUR = {f!r};"
                "from licensing import device;"
                "print(json.dumps(device.fingerprint({d!r})))")
        seen = set()
        with tempfile.TemporaryDirectory() as home, \
                tempfile.TemporaryDirectory() as user_dir:
            env = dict(os.environ, HOME=home, USERPROFILE=home,
                       QT_QPA_PLATFORM="offscreen")
            for flav in flavour.FLAVOURS:
                r = subprocess.run(
                    [sys.executable, "-c", code.format(f=flav, d=user_dir)],
                    cwd=ROOT, env=env, capture_output=True, text=True,
                    timeout=120)
                self.assertEqual(r.returncode, 0, r.stderr[-800:])
                seen.add(r.stdout.strip().splitlines()[-1])
        self.assertEqual(len(seen), 1, seen)

    def test_device_module_never_mentions_flavour(self):
        with open(os.path.join(ROOT, "licensing", "device.py"),
                  encoding="utf-8") as f:
            self.assertNotIn("flavour", f.read().lower())


if __name__ == "__main__":
    unittest.main()
