"""The Email add-on's front door — addons/email/panel.py::EmailPanel.

Before this, EmailSetupDialog only ever opened itself the first time, from
MainWindow._open_email_dialog(), which is guarded by
`not CB.mailer.is_configured(self.cfg)`. Once an account was configured there
was no button, menu, or gesture anywhere on screen that reopened it — a wrong
password or a mailbox change had no way in short of hand-editing the config
file. This defends the fix: a standing "Change account" action that opens the
same dialog regardless of whether one is already set up.
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest import mock  # noqa: E402

from PySide6.QtWidgets import QApplication  # noqa: E402

import plans  # noqa: E402
from addons.email.dialog import EmailSetupDialog  # noqa: E402
from addons.email.panel import EmailPanel  # noqa: E402
from test_gates import GateTest  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _labels(panel: EmailPanel) -> list[str]:
    return [action.text() for action in panel.header_actions()]


class TheChangeAccountDoor(unittest.TestCase):

    def test_it_is_offered_with_no_account_configured(self):
        panel = EmailPanel({})
        self.assertIn("Change account", _labels(panel))

    def test_it_is_still_offered_once_an_account_is_configured(self):
        panel = EmailPanel({"email": {"address": "sales@acme.co.in"}})
        self.assertIn("Change account", _labels(panel))

    def test_clicking_it_asks_to_open_setup_rather_than_start_a_draft(self):
        """It must be its own action, not a relabelled "Start a draft" —
        otherwise pressing it drops the owner into composing mail instead of
        into the account form they actually asked for."""
        panel = EmailPanel({})
        seen = []
        panel.change_account.connect(lambda: seen.append("setup"))
        panel.opened.connect(lambda: seen.append("draft"))
        actions = panel.header_actions()
        change = next(a for a in actions if a.text() == "Change account")
        change.click()
        self.assertEqual(seen, ["setup"])

class MainWindowActuallyWiresIt(GateTest):
    """This was a SOURCE CHECK -- it read main_window.py as text and grepped
    for "email_panel.change_account.connect(self._open_email_setup)".

    Its own docstring gave the reason: "constructing a real MainWindow pulls
    in the licence client for a test that is really about one signal
    connection." That was true when it was written and is not any more --
    test_gates.GateTest exists precisely to stub the licence client and build
    a real window.

    A source check tests how code is SPELLED. It passes if the line exists
    and nothing connects it; it fails on a refactor that changes nothing
    about behaviour; and it cannot see whether the signal actually arrives.
    All three of those matter more than usual right now, because Email's
    panel and dialog have just moved packages.
    """

    def test_change_account_opens_setup(self):
        import main_window
        self.grant(tuple(plans.FEATURES))
        win = self._window()
        with mock.patch.object(main_window.MainWindow,
                               "_open_email_setup") as opened:
            win.email_panel.change_account.emit()
        self.assertTrue(
            opened.called,
            "the panel's Change account signal is not connected to the "
            "window, so the button does nothing")

    def test_setup_opens_even_when_an_account_is_already_configured(self):
        """The bug this whole file defends. EmailSetupDialog used to open
        only from the compose route, behind `not is_configured(cfg)` -- so
        once an account was saved there was no way back in short of editing
        the config file by hand. A wrong password had no door."""
        import main_window
        self.grant(tuple(plans.FEATURES))
        win = self._window()
        win.cfg = {"email": {"address": "sales@acme.co.in", "password": "p"}}
        with mock.patch("addons.email.dialog.EmailSetupDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            win._open_email_setup()
        self.assertTrue(
            dialog.called,
            "_open_email_setup did not open the dialog when an account was "
            "already configured -- the door has closed again")


class ThePasswordNeverReadsAsLost(unittest.TestCase):
    """EmailSetupDialog is now reachable at any time via "Change account", so
    the same fix made on the Inquiry Automation side — a loud, standing
    confirmation that a blank box means "kept", not "deleted" — belongs here
    too, or the very door just added recreates the report that started this:
    opening setup makes the saved app password look like it vanished."""

    def test_a_saved_password_says_so_loudly(self):
        dialog = EmailSetupDialog({"email": {"address": "sales@acme.co.in",
                                              "password": "p"}})
        self.assertEqual(dialog.pass_edit.text(), "")
        self.assertTrue(dialog.password_status.isVisibleTo(dialog))
        self.assertIn("already saved", dialog.password_status.text())

    def test_the_notice_goes_quiet_once_a_new_password_is_typed(self):
        dialog = EmailSetupDialog({"email": {"address": "sales@acme.co.in",
                                              "password": "p"}})
        dialog.pass_edit.setText("a-new-app-password")
        self.assertFalse(dialog.password_status.isVisibleTo(dialog))

    def test_no_notice_when_nothing_has_ever_been_saved(self):
        dialog = EmailSetupDialog({})
        self.assertNotIn("already saved", dialog.password_status.text())


if __name__ == "__main__":
    unittest.main()
