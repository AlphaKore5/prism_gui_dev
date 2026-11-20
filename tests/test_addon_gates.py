"""Every add-on stays behind its licence, whatever file it lives in.

The gate is a separate line of code from the thing it guards:

    def _open_gerber(self):
        self._authorized_then("boq", "addon", lambda: self._show_screen("gerber"))

Nothing about moving `gerber_dialog.py` into a package would break that line
loudly. Delete it, or reach the screen by another route, and the add-on simply
opens -- for everybody, including the customers who did not buy it. The suite
stays green, the app stays working, and the only signal is revenue.

So this file asserts the negative case once per feature key: with everything
granted EXCEPT the one feature, asking for that add-on must show the paywall and
must not open anything. It is deliberately written against `_handle_command`,
the rail's own entry point, rather than against `_open_<name>` directly -- the
point is that the ROUTE is gated, not that a particular method is.

The last test is the one that matters over time: it fails when somebody adds an
add-on to the rail without adding it here. A gate test nobody remembers to write
is the same as no gate test.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import plans                                            # noqa: E402
import widgets.sidebar as sidebar                       # noqa: E402
from test_gates import GateTest                         # noqa: E402

# Rail key -> the licence feature it must not open without.
#
# gerber and step each have their own key since 2026-09-10 -- they are sold
# as their own add-ons. They rode "boq" before that.
#
# reel and motion are not on the rail (Reel's row was given to Artifacts) but
# are reachable by command, which is exactly why they are tested here. Motion
# rides "reel": Reel, Studio and Motion are one purchase.
#
# bom rides "boq" by design: "BOQ & BOM" is one add-on and BOM ships as a mode
# inside the BOQ dialog, so the route it is reached by is BOQ's. The day BOM
# becomes its own purchase, this line and widgets/sidebar.py change together
# -- and test_the_rail_and_this_file_agree_on_which_feature_gates_what below
# is what makes "together" enforceable rather than remembered.
ADDON_FEATURES = {
    "inquiry": "inbox",
    "boq": "boq",
    "bom": "boq",
    "gerber": "gerber",
    "step": "step",
    "email": "email",
    "leads": "leads",
    "reel": "reel",
    "motion": "reel",
    # whatsapp is a rail add-on (like gerber/step) since 2026-09-17. It rides
    # "marketing" -- WhatsApp broadcast/outreach is the marketing channel and
    # no other add-on claims that key.
    "whatsapp": "marketing",
}

EVERYTHING = tuple(plans.FEATURES)


class AnUnlicensedAddOnDoesNotOpen(GateTest):

    def _deny(self, feature):
        """Grant every feature except one."""
        return self.grant([f for f in EVERYTHING if f != feature])

    def test_each_add_on_shows_the_paywall_instead_of_opening(self):
        import main_window
        for key, feature in sorted(ADDON_FEATURES.items()):
            with self.subTest(addon=key, feature=feature):
                self.paywalled.clear()
                self._deny(feature)
                win = self._window()
                with mock.patch.object(main_window.MainWindow,
                                       "_show_screen") as shown, \
                     mock.patch("addons.reel.dialog.ReelDialog") as reel, \
                     mock.patch("addons.motion.dialog.MotionDialog") as motion, \
                     mock.patch("addons.boq.dialog.BoqDialog") as boq, \
                     mock.patch("addons.gerber.dialog.GerberDialog") as gerber, \
                     mock.patch("addons.whatsapp.dialog.WhatsAppDialog") as whatsapp:
                    win._handle_command(key)

                self.assertIn(
                    feature, self.paywalled,
                    "asking for the %r add-on without the %r feature did not "
                    "show the paywall -- the gate on its route is missing"
                    % (key, feature))
                for name, opened in (("screen", shown), ("ReelDialog", reel),
                                     ("MotionDialog", motion),
                                     ("BoqDialog", boq),
                                     ("GerberDialog", gerber),
                                     ("WhatsAppDialog", whatsapp)):
                    self.assertFalse(
                        opened.called,
                        "the %r add-on opened its %s despite the %r feature "
                        "not being licensed" % (key, name, feature))

    def test_a_licensed_add_on_still_opens(self):
        """The other half. A gate that denies everybody passes the test above
        and is just as broken."""
        import main_window
        self.grant(EVERYTHING)
        win = self._window()
        with mock.patch.object(main_window.MainWindow,
                               "_authorized_then",
                               lambda self, feature, action, then: then()), \
             mock.patch.object(main_window.MainWindow, "_show_screen") as shown:
            win._handle_command("boq")
        self.assertTrue(shown.called,
                        "BOQ did not open even with every feature granted")


class TheGateListStaysHonest(unittest.TestCase):

    def test_every_rail_add_on_is_covered_by_a_gate_test(self):
        rail = {row[0]: row[4] for row in sidebar.ADDONS}
        missing = [key for key, feature in rail.items()
                   if feature and feature != sidebar.SOON
                   and key not in ADDON_FEATURES]
        self.assertEqual(
            missing, [],
            "these add-ons are on the rail but have no gate test: "
            + ", ".join(missing)
            + "\n\nAdd them to ADDON_FEATURES above. An add-on whose gate is "
              "never asserted is one refactor away from being free.")

    def test_every_gated_feature_is_a_real_licence_feature(self):
        """A feature key the licence server cannot mint padlocks the add-on for
        everyone, which looks like a bug in the add-on rather than in a table."""
        unknown = sorted({f for f in ADDON_FEATURES.values()
                          if f not in plans.FEATURES})
        self.assertEqual(unknown, [],
                         "not present in plans.FEATURES: " + ", ".join(unknown))

    def test_the_rail_and_this_file_agree_on_which_feature_gates_what(self):
        for row in sidebar.ADDONS:
            key, feature = row[0], row[4]
            if key in ADDON_FEATURES and feature and feature != sidebar.SOON:
                with self.subTest(addon=key):
                    self.assertEqual(
                        ADDON_FEATURES[key], feature,
                        "widgets/sidebar.py gates %r on %r, this file expects "
                        "%r" % (key, feature, ADDON_FEATURES[key]))


if __name__ == "__main__":
    unittest.main()
