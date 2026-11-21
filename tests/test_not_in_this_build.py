"""Gate G6: asking for a tool this build does not contain gets a plain
"not in this build" answer, never an ImportError, a licence pitch or a
Reel/Motion probe. Run under every flavour (PRISM_TEST_FLAVOUR=...): the add-ons
the build lacks are asked for, the ones it has are left alone."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import flavour  # noqa: E402
import plans  # noqa: E402
import test_gates as TG  # noqa: E402

ALL = flavour.ADDONS_BY_FLAVOUR["complete"]
ABSENT = tuple(k for k in ALL if k not in flavour.addon_keys())
PRESENT = tuple(flavour.addon_keys())


class NotInThisBuild(TG.GateTest):

    def _win(self):
        self.grant(tuple(plans.FEATURES))
        return self._window()

    def _ask(self, win, key):
        import main_window
        with mock.patch.object(main_window.QMessageBox, "information") as info, \
             mock.patch.object(main_window.MainWindow, "_authorized_then") as auth, \
             mock.patch.object(main_window.MainWindow, "_show_screen") as shown, \
             mock.patch.object(main_window.MainWindow, "_open_reel_dialog") as rd, \
             mock.patch.object(main_window.MainWindow, "_open_motion_dialog") as md:
            win._handle_command(key)
        return info, auth, shown, rd, md

    def test_every_absent_add_on_says_so(self):
        win = self._win()
        for key in ABSENT:
            with self.subTest(addon=key):
                info, auth, shown, rd, md = self._ask(win, key)
                self.assertEqual(info.call_count, 1)
                text = info.call_args[0][2]
                self.assertIn(flavour.ADDON_NAMES[key], text)
                self.assertIn("not in this build", text)
                self.assertIn("Open " + flavour.owner_edition_name(key), text)
                self.assertFalse(auth.called)
                self.assertFalse(shown.called)
                self.assertFalse(rd.called or md.called)
                self.assertEqual(self.paywalled, [])

    def test_a_present_add_on_is_not_told_it_is_missing(self):
        win = self._win()
        for key in PRESENT:
            with self.subTest(addon=key):
                self.assertFalse(win._not_in_build(key))

    def test_reel_and_motion_commands(self):
        """The two the owner named, spelled out."""
        win = self._win()
        for key in ("reel", "motion"):
            info, auth, *_ = self._ask(win, key)
            if key in flavour.addon_keys():
                self.assertFalse(info.called and "not in this build"
                                 in info.call_args[0][2])
            else:
                self.assertEqual(info.call_count, 1)
                self.assertFalse(auth.called)

    def test_a_routed_media_step_is_stopped_before_anything_is_probed(self):
        import main_window
        win = self._win()
        for agent in ("Prism Reel", "Prism Studio", "Prism Motion"):
            key = flavour.addon_for_agent(agent)
            with self.subTest(agent=agent):
                if key in flavour.addon_keys():
                    continue
                win.routing = {"media": agent}
                with mock.patch.object(main_window.QMessageBox, "information") as info, \
                     mock.patch.object(win.agents_panel, "ensure_prompts"), \
                     mock.patch.object(win.agents_panel, "selected_agents",
                                       return_value={"media": agent}), \
                     mock.patch.object(win.agents_panel, "selected_steps",
                                       return_value=[("m", agent, [])]), \
                     mock.patch.object(win.agents_panel, "left_out_stages",
                                       return_value=[]), \
                     mock.patch.object(main_window.CB, "studio_available") as sa, \
                     mock.patch.object(main_window.CB, "motion_available") as ma, \
                     mock.patch.object(main_window.QMessageBox, "question") as q:
                    win._run_pipeline()
                self.assertEqual(info.call_count, 1)
                self.assertIn("not in this build", info.call_args[0][2])
                self.assertFalse(sa.called or ma.called or q.called)
                self.assertFalse(getattr(win, "_auto_run", False))


class DataMatchesTheManifests(unittest.TestCase):
    """Names and agents are copied into flavour.py (a build without an add-on
    cannot read its manifest). Under the complete build they must still agree."""

    @unittest.skipUnless(flavour.FLAVOUR == "complete", "needs every manifest")
    def test_agents_and_names_match_the_manifests(self):
        from addons import registry
        for a in registry.REGISTRY:
            self.assertEqual(flavour.ADDON_AGENTS.get(a.key, ()), a.agents, a.key)
            self.assertIn(a.key, flavour.ADDON_NAMES)
        self.assertEqual(set(flavour.ADDON_NAMES), set(flavour.ADDONS_BY_FLAVOUR["complete"]))
        self.assertEqual(flavour.addon_for_agent("Prism Studio"), "reel")
        self.assertEqual(flavour.addon_for_agent("ChatGPT"), "")
        self.assertEqual(flavour.owner_edition_name("reel"), "Prism Studio")
        self.assertEqual(flavour.owner_edition_name("boq"), "Prism Engineering")
        self.assertEqual(flavour.owner_edition_name("leads"), "Prism Sales")


if __name__ == "__main__":
    unittest.main()
