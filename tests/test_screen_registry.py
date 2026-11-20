"""The body stack's order is the screen table's order, and it is checked.

main_window.SCREENS declares the pages of the body stack. The integers, the
name->index lookup and the index->name lookup are all derived from it, so
those three can no longer disagree.

What a table cannot do by itself is guarantee that the pages were actually
ADDED in that order. `screens.addWidget(...)` assigns the index by call
position, and before this file the only thing keeping the calls in step with
the constants was a trailing comment on each line:

    self.screens.addWidget(self.gerber_panel)          # GERBER
    self.screens.addWidget(self.wizard_panel)          # WIZARD

Get that wrong -- insert a page rather than append one, or reorder two
during a refactor -- and every screen after it shifts by one. Nothing
raises. The rail lights the wrong row, clicking Gerber shows Support, and
the suite is perfectly green because no test ever asked which widget was on
which page.

That is the whole reason this file exists, and it matters more during the
add-ons migration than at any other time: panels are about to move between
modules, and a move is exactly when an addWidget call gets dropped or
re-ordered.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import main_window                                      # noqa: E402
import plans                                            # noqa: E402
from addons import manifest, registry                   # noqa: E402
from test_gates import GateTest                         # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVERYTHING = tuple(plans.FEATURES)


class TheTableIsSelfConsistent(unittest.TestCase):
    """No Qt needed for these -- they are facts about the table itself."""

    def test_no_screen_is_declared_twice(self):
        self.assertEqual(
            len(set(main_window.SCREENS)), len(main_window.SCREENS),
            "a duplicate name in SCREENS silently gives one screen two "
            "indices and hides the other page forever")

    def test_the_two_lookups_are_exact_inverses(self):
        """They used to be two hand-written dicts, the second typed out as the
        inverse of the first."""
        for name, index in main_window.SCREEN_INDEX.items():
            with self.subTest(screen=name):
                self.assertEqual(main_window.SCREEN_NAME[index], name)

    def test_the_unrouted_pages_are_not_reachable_by_name(self):
        """wizard is reached only from _first_run(); inquiry_work only by
        drilling in from the launcher panel. Both were simply absent from the
        old hand-written table, and asking for either must still fall back to
        HOME rather than suddenly becoming navigable."""
        for name in ("wizard", "inquiry_work"):
            with self.subTest(screen=name):
                self.assertNotIn(name, main_window.SCREEN_INDEX)

    def test_the_addwidget_calls_match_the_table(self):
        """Static half: the number of pages added must equal the number
        declared. Catches a page appended without a table entry, which would
        make every later index wrong."""
        with open(os.path.join(ROOT, "main_window.py"),
                  encoding="utf-8") as f:
            source = f.read()
        # Add-on pages are added through MainWindow._addon_page (so a build
        # without an add-on still holds its slot). That helper's own
        # addWidget is the mechanism, not a page: count each call to the
        # helper instead. Changed with the shell/add-on split (gate G0).
        helper = re.search(r"    def _addon_page\(.*?(?=\n    def )", source, re.S)
        self.assertIsNotNone(helper, "MainWindow._addon_page is gone")
        body = source.replace(helper.group(0), "")
        calls = (re.findall(r"self\.screens\.addWidget\(", body)
                 + re.findall(r"self\._addon_page\(", body))
        self.assertEqual(
            len(calls), len(main_window.SCREENS),
            "main_window.py adds %d pages to the body stack but SCREENS "
            "declares %d. Every screen after the mismatch is now on the wrong "
            "index, and nothing else will tell you."
            % (len(calls), len(main_window.SCREENS)))


class EveryAddOnWithAScreenHasOne(unittest.TestCase):

    def test_every_screen_an_addon_declares_exists_in_the_stack(self):
        """An add-on whose manifest names a screen the stack does not have
        would send the user to HOME on every click, silently."""
        for key, screen in registry.screens():
            with self.subTest(addon=key, screen=screen):
                self.assertIn(
                    screen, main_window.SCREEN_INDEX,
                    "addons/%s declares screen %r, which is not in "
                    "main_window.SCREENS" % (key, screen))


class TheStackIsInTheDeclaredOrder(GateTest):
    """The runtime half, and the one that actually catches a reordering: ask
    for each screen by name and check the page that comes up is the one whose
    panel we expect."""

    # name in SCREENS -> the MainWindow attribute holding that page. Only the
    # pages that ARE plain attributes; the workbench builds its own composite.
    PANELS = {
        "home": "home_panel",
        "inquiry": "inquiry_panel",
        "config": "settings_panel",
        "guide": "guide_panel",
        "runs": "history_panel",
        "boq": "boq_panel",
        "email": "email_panel",
        "support": "support_panel",
        "gerber": "gerber_panel",
        "artifacts": "artifacts_panel",
        "bom": "bom_panel",
        "step": "step_panel",
        "leads": "leads_panel",
        "whatsapp": "whatsapp_panel",
    }

    def test_the_page_at_each_index_is_the_panel_the_table_names(self):
        self.grant(EVERYTHING)
        win = self._window()
        self.assertEqual(
            win.screens.count(), len(main_window.SCREENS),
            "the body stack holds %d pages, SCREENS declares %d"
            % (win.screens.count(), len(main_window.SCREENS)))
        for name, attribute in self.PANELS.items():
            with self.subTest(screen=name):
                index = main_window.SCREEN_INDEX[name]
                self.assertIs(
                    win.screens.widget(index), getattr(win, attribute),
                    "index %d should hold %s (screen %r) but holds something "
                    "else -- the addWidget calls are out of step with "
                    "main_window.SCREENS, so this screen and every one after "
                    "it shows the wrong page" % (index, attribute, name))

    def test_asking_for_a_screen_by_name_lands_on_it(self):
        self.grant(EVERYTHING)
        win = self._window()
        for name, index in main_window.SCREEN_INDEX.items():
            with self.subTest(screen=name):
                before = win.screens.currentIndex()
                win._show_screen(name)
                if name in main_window._SWITCHED_OFF:
                    # A switched-off add-on's page (bom since 2026-11-16)
                    # keeps its index but is never shown: asking stays put.
                    self.assertEqual(win.screens.currentIndex(), before)
                    continue
                self.assertEqual(win.screens.currentIndex(), index)

    def test_an_unknown_screen_falls_back_to_home(self):
        """Unchanged behaviour, pinned because the fallback is what makes the
        unrouted pages unreachable."""
        self.grant(EVERYTHING)
        win = self._window()
        win._show_screen("no-such-screen")
        self.assertEqual(win.screens.currentIndex(), main_window.HOME)


if __name__ == "__main__":
    unittest.main()
