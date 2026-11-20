"""The shell must not need any add-on that its build leaves out.

Prism is becoming three builds (Studio, Sales, Engineering) from one codebase.
Until now main_window.py imported every add-on's panel and dialog by name at
the top of the file, so a build that did not contain BOQ could not even start,
in a windowed app with no console. These tests build the REAL main window with
a registry that holds only some add-ons and prove it starts, keeps every screen
number where it was, and refuses politely when asked for something absent.

Gate G0 of the module split (modules/1-STUDIO-CORE-AND-FLAVOURS.md).
"""
from __future__ import annotations

import ast
import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

_app = QApplication.instance() or QApplication([])

import main_window  # noqa: E402
from addons import registry  # noqa: E402

ADDON_PACKAGES = {"boq", "bom", "step", "gerber", "leads", "whatsapp",
                  "inquiry", "email", "reel", "motion"}


def _only(*keys):
    kept = tuple(a for a in registry.REGISTRY if a.key in keys)
    return mock.patch.multiple(registry, REGISTRY=kept,
                               _BY_KEY={a.key: a for a in kept})


class TheShellNamesNoAddOn(unittest.TestCase):
    def test_main_window_imports_no_addon_package(self):
        """AST, not grep: docstrings quote these imports while explaining the
        rule. Only the registry may know which add-ons exist."""
        tree = ast.parse(open(os.path.join(ROOT, "main_window.py"),
                              encoding="utf-8").read())
        bad = []
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module]
            elif isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            for m in mods:
                parts = m.split(".")
                if parts[0] == "addons" and len(parts) > 1 and parts[1] in ADDON_PACKAGES:
                    bad.append((node.lineno, m))
        self.assertEqual([], bad, "main_window.py imports an add-on by name; "
                         "go through addons.registry (_addon_class) instead")


class AWindowWithOnlyStudioTools(unittest.TestCase):
    def _window(self):
        with _only("reel", "motion"):
            return main_window.MainWindow()

    def test_it_starts_and_every_screen_keeps_its_number(self):
        with _only("reel", "motion"):
            win = main_window.MainWindow()
            self.assertEqual(len(main_window.SCREENS), win.screens.count(),
                             "a missing add-on must still hold its slot, or "
                             "every later screen number shifts")
            for name in ("boq", "gerber", "step", "leads", "whatsapp", "inquiry",
                         "email", "bom", "inquiry_work"):
                panel = getattr(win, f"{name}_panel", "absent")
                if name in ("bom",):
                    panel = win.bom_panel
                self.assertIsNone(panel, name)
                page = win.screens.widget(main_window._INDEX[name])
                self.assertIs(type(page), QWidget, name)

    def test_the_core_screens_still_work(self):
        with _only("reel", "motion"):
            win = main_window.MainWindow()
            for name in ("home", "workbench", "config", "guide", "runs", "support"):
                win._show_screen(name)
                self.assertEqual(main_window._INDEX[name], win.screens.currentIndex(), name)

    def test_asking_for_an_absent_addon_says_so_and_changes_nothing(self):
        with _only("reel", "motion"):
            win = main_window.MainWindow()
            shown = []
            with mock.patch.object(QMessageBox, "information",
                                   lambda *a, **k: shown.append(a[-1])):
                for opener in ("_open_boq_dialog", "_open_bom_dialog",
                               "_open_gerber_dialog", "_open_leads_dialog",
                               "_open_whatsapp_dialog", "_open_email_setup",
                               "_open_inquiry_dialog", "_open_inquiry_setup"):
                    getattr(win, opener)()
            self.assertEqual(8, len([m for m in shown if "isn't available" in m]),
                             shown)

    def test_the_full_build_is_unchanged(self):
        win = main_window.MainWindow()
        self.assertEqual(len(main_window.SCREENS), win.screens.count())
        for name in ("boq", "gerber", "step", "leads", "whatsapp", "inquiry", "email", "bom"):
            self.assertIsNotNone(getattr(win, f"{name}_panel"), name)
        self.assertIsNotNone(win.inquiry_work_panel)


if __name__ == "__main__":
    unittest.main()
