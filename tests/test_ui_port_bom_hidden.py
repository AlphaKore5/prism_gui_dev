"""BOM & Stock is switched off (addons/bom/addon.py status=OFF, 2026-11-16).

Real widgets, offscreen, sandbox HOME. Three things are proved:
  1. nothing in the UI draws a way to BOM (rail, Home, Help, Lumi, search),
     and anything that still asks for it opens nothing and says so;
  2. flipping the one status back to LIVE brings every one of those back;
  3. nothing else moved (shelf order, screen indices, BOM's code and gate).
"""
from __future__ import annotations

import dataclasses
import importlib
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-stage13-bom-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QLabel, QPushButton   # noqa: E402

_app = QApplication.instance() or QApplication([])

import flavour                                                     # noqa: E402
import support_kb                                                  # noqa: E402
from addons import manifest, registry                             # noqa: E402
from test_gates import GateTest                                    # noqa: E402

import plans                                                       # noqa: E402

EVERYTHING = tuple(plans.FEATURES)
# What the complete build's rail holds besides BOM; a flavour keeps its own
# subset, in the same order.
OTHERS_RAIL = [k for k in ["inquiry", "boq", "gerber", "step", "email", "leads",
                           "whatsapp"] if k in flavour.addon_keys()]
HAS_BOM = "bom" in flavour.addon_keys()


def _switched_on():
    """The registry exactly as it is, except BOM's status is LIVE: what the
    one-word change in addons/bom/addon.py produces."""
    live = dataclasses.replace(registry.by_key("bom"), status=manifest.LIVE)
    table = tuple(live if a.key == "bom" else a for a in registry.REGISTRY)
    return mock.patch.multiple(registry, REGISTRY=table,
                               _BY_KEY={a.key: a for a in table})


def _no_bom_in_this_build(test):
    """In a flavour without BOM there is nothing to switch back on. What that
    build must prove instead is that BOM is not in the registry at all."""
    if HAS_BOM:
        return False
    test.assertIsNone(registry.by_key("bom"))
    test.assertNotIn("bom", registry.keys())
    return True


def _rail():
    from widgets.sidebar import Sidebar
    rail = Sidebar()
    rail.resize(258, 900)
    rail.show()
    _app.sendPostedEvents()
    return rail


def _boq_dialog():
    """Patch the BOQ dialog class where the build has one; a flavour without
    BOQ has no such class, so a bare mock stands in (it can never be called)."""
    if "boq" in flavour.addon_keys():
        return mock.patch("addons.boq.dialog.BoqDialog")
    return mock.MagicMock()


def _lumi_chips(reply):
    """The "take me there" chips the real Lumi panel draws for an answer."""
    from widgets.support_panel import SupportPanel
    p = SupportPanel({})
    drawn = []
    with mock.patch.object(p, "_options", lambda chips: drawn.extend(chips)):
        p._ai_answered(reply)
    return [c.text().strip() for c in drawn]


def _guide_titles():
    from dialogs.guide_dialog import GuideDialog
    d = GuideDialog()
    return [l.text() for l in d.findChildren(QLabel)]


class TheSwitchItself(unittest.TestCase):
    def test_bom_is_off_and_still_registered_whole(self):
        if not HAS_BOM:
            # A flavour without BOM is stronger than "switched off": the
            # add-on is not in the build at all, and nothing can ask for it.
            self.assertIsNone(registry.by_key("bom"))
            self.assertFalse(registry.is_off("bom"))
            self.assertEqual(registry.EXPECTED, len(registry.REGISTRY))
            self.assertEqual(registry.kind_of("BOM — parts for a crusher"), "")
            return
        bom = registry.by_key("bom")
        self.assertEqual(bom.status, manifest.OFF)
        self.assertTrue(registry.is_off("bom"))
        self.assertIn(bom, registry.REGISTRY)           # selftest count holds
        self.assertEqual(registry.EXPECTED, len(registry.REGISTRY))
        # code, licence key and history attribution are untouched
        self.assertEqual(bom.feature, "boq")
        for dotted in (bom.panel, bom.dialog, bom.probe):
            self.assertIsNotNone(registry.resolve(dotted), dotted)
        self.assertEqual(registry.kind_of("BOM — parts for a crusher"), "bom")

    def test_unknown_and_live_keys_are_not_off(self):
        for key in ("boq", "step", "gerber", "config", "", "no-such"):
            self.assertFalse(registry.is_off(key), key)

    def test_the_switch_is_one_line_in_the_bom_manifest(self):
        src = open(os.path.join(ROOT, "addons", "bom", "addon.py"),
                   encoding="utf-8").read()
        self.assertEqual(src.count("status="), 1)
        self.assertIn("status=manifest.OFF,", src)


class NothingDrawsAWayToBom(unittest.TestCase):
    def test_not_on_the_rail_or_home_shelf(self):
        self.assertNotIn("bom", [a.key for a in registry.shelf(manifest.RAIL)])
        self.assertNotIn("bom", [a.key for a in registry.shelf(manifest.HOME)])
        import widgets.home_panel as H
        import widgets.sidebar as S
        self.assertNotIn("bom", [r[0] for r in S.ADDONS])
        self.assertNotIn("bom", [r[0] for r in H.ADDONS])

    def test_the_real_rail_has_no_bom_row(self):
        rail = _rail()
        self.assertNotIn("bom", rail._nav)
        labels = [l.text() for l in rail.findChildren(QLabel)]
        self.assertFalse([t for t in labels if "BOM" in t], labels)

    def test_home_try_chips_do_not_open_bom(self):
        from widgets import home_panel as H
        home = H.HomePanel({})
        home.show()
        _app.sendPostedEvents()
        got = []
        home.open_addon.connect(got.append)
        for b in home.findChildren(QPushButton, "tryChip"):
            b.click()
        self.assertTrue(got)
        self.assertNotIn("bom", got)

    def test_help_guide_has_no_bom_card(self):
        self.assertNotIn("BOM & Stock", _guide_titles())

    def test_help_search_and_lumi_context_have_no_bom_answer(self):
        self.assertIsNone(support_kb.question("bom-shortage"))
        hits = [q.qid for q in support_kb.search(
            "check parts list stock shortages")]
        self.assertNotIn("bom-shortage", hits)
        self.assertEqual(support_kb.question("boq-file").related,
                         ("boq-dwg", "boq-blank-columns"))
        for q in support_kb.all_questions():
            self.assertNotEqual(q.answer.action, "bom", q.qid)
            self.assertNotIn("bom-shortage", q.related, q.qid)
        self.assertNotIn("stock shortages with BOM",
                         support_kb.as_context("bom parts list"))

    def test_lumi_offers_no_take_me_there_chip_for_bom(self):
        self.assertEqual(_lumi_chips("Here is how. [ACTION:bom]"), [])
        # the keyword fallback that used to pick "bom" draws nothing either
        self.assertEqual(_lumi_chips("Check the stock shortage list."), [])
        # and a live add-on still gets its chip
        # (a build without BOQ offers no chip for it either)
        self.assertEqual(_lumi_chips("Open it here. [ACTION:boq]"),
                         ["Open BOQ Extractor"]
                         if "boq" in flavour.addon_keys() else [])

    def test_nothing_offers_bom_work_to_another_add_on(self):
        from addons import names
        owner, handler = registry.offering(names.LIST_PARTS)
        self.assertIsNone(owner)
        self.assertEqual(handler, "")


class AskingAnywayOpensNothing(GateTest):
    def test_the_command_and_the_screen_stay_put_with_a_note(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        win._show_screen("home")
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, f, a, then: then()), \
             _boq_dialog() as dialog:
            win._handle_command("bom")
            win._show_screen("bom")
        self.assertEqual(win.screens.currentIndex(), main_window.HOME)
        self.assertFalse(dialog.called)
        self.assertIn("isn't available", win.statusBar().currentMessage())

    def test_an_unlicensed_ask_still_hits_the_gate_first(self):
        """The licence gate is unchanged: asking without BOQ shows the pitch."""
        import main_window
        self.grant([f for f in EVERYTHING if f != "boq"])
        win = self._window()
        with mock.patch.object(main_window.MainWindow, "_show_screen") as shown:
            win._handle_command("bom")
        self.assertIn("boq", self.paywalled)
        self.assertFalse(shown.called)

    def test_other_add_ons_still_open(self):
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(main_window.MainWindow, "_authorized_then",
                               lambda self, f, a, then: then()):
            # (the STEP rail row lands straight on its workbench)
            for key, idx in (("boq", main_window.BOQ),
                             ("gerber", main_window.GERBER),
                             ("step", main_window.STEP_WORK)):
                if key not in flavour.addon_keys():
                    # not in this build: it has no screen to open
                    self.assertIsNone(registry.by_key(key), key)
                    continue
                win._handle_command(key)
                self.assertEqual(win.screens.currentIndex(), idx, key)


class NothingElseMoved(unittest.TestCase):
    def test_screen_table_and_indices_are_unchanged(self):
        import main_window as MW
        self.assertEqual(MW.SCREENS.index("bom"), 13)
        self.assertEqual(MW.SCREENS.index("step"), 14)
        self.assertEqual(MW.SCREENS[-1], "step_work")
        # switched off in a build that has BOM; a build without it has no
        # BOM screen to switch off (its slot stays, held by a blank page)
        self.assertEqual(MW._SWITCHED_OFF, {"bom"} if HAS_BOM else set())

    def test_other_add_ons_keep_their_order_on_the_rail(self):
        self.assertEqual([a.key for a in registry.shelf(manifest.RAIL)],
                         OTHERS_RAIL)
        rail = _rail()
        ys = [rail._nav[k].y() for k in OTHERS_RAIL]
        self.assertEqual(ys, sorted(ys))

    def test_the_bom_front_door_and_bom_dialog_still_build(self):
        if _no_bom_in_this_build(self):
            return
        from addons.bom.panel import BomPanel
        from addons.boq.dialog import BoqDialog
        BomPanel({})
        d = BoqDialog({}, [], None, mode="bom")
        self.assertEqual(d._noun, "BOM")


class SwitchingItBackOn(unittest.TestCase):
    def tearDown(self):
        importlib.reload(support_kb)

    def test_shelves_come_back_with_bom_last(self):
        if _no_bom_in_this_build(self):
            return
        with _switched_on():
            self.assertFalse(registry.is_off("bom"))
            self.assertEqual([a.key for a in registry.shelf(manifest.RAIL)],
                             OTHERS_RAIL + ["bom"])
            self.assertEqual([a.key for a in registry.shelf(manifest.HOME)][-1],
                             "bom")

    def test_the_real_rail_draws_the_bom_row_again(self):
        if _no_bom_in_this_build(self):
            return
        with _switched_on():
            rail = _rail()
        self.assertIn("bom", rail._nav)
        labels = [l.text() for l in rail.findChildren(QLabel)]
        self.assertIn("BOM & Stock", labels)

    def test_help_search_and_guide_come_back(self):
        if _no_bom_in_this_build(self):
            return
        with _switched_on():
            kb = importlib.reload(support_kb)
            self.assertIsNotNone(kb.question("bom-shortage"))
            self.assertIn("bom-shortage", [q.qid for q in kb.search(
                "check parts list stock shortages")])
            self.assertIn("bom-shortage", kb.question("boq-file").related)
            self.assertIn("BOM & Stock", _guide_titles())

    def test_the_window_would_route_to_it_again(self):
        if _no_bom_in_this_build(self):
            return
        import main_window
        with _switched_on():
            self.assertEqual(
                {a.screen for a in registry.REGISTRY
                 if a.is_off() and a.screen}, set())
        # main_window derives _SWITCHED_OFF with exactly that expression
        src = open(os.path.join(ROOT, "main_window.py"), encoding="utf-8").read()
        self.assertIn("_SWITCHED_OFF = {addon.screen for addon in "
                      "registry.REGISTRY\n                 if addon.is_off() "
                      "and addon.screen}", src)
        self.assertIsNotNone(main_window)

    def test_lumi_and_the_offer_come_back(self):
        if _no_bom_in_this_build(self):
            return
        from addons import names
        with _switched_on():
            owner, _h = registry.offering(names.LIST_PARTS)
            self.assertEqual(owner.key, "bom")
            self.assertEqual(_lumi_chips("Here is how. [ACTION:bom]"),
                             ["Open BOM Analyzer"])


if __name__ == "__main__":
    unittest.main()
