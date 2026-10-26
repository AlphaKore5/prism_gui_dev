"""Activation must make the local legal notice a real customer decision."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import licensing  # noqa: E402
from dialogs import license_dialog as LD  # noqa: E402

_app = QApplication.instance() or QApplication([])
KEY = "PRSM-TZQ57-XJ8VA-9R60N-ZJZCG"


class LegalAcknowledgement(unittest.TestCase):
    def _dialog(self):
        state = mock.Mock(license_id="", features=[], usable=False,
                          message="", kind="", license_ends=0)
        with mock.patch.object(licensing, "state", return_value=state):
            return LD.LicenseDialog(mode="activate")

    def test_key_cannot_activate_until_both_documents_are_read_and_accepted(self):
        dialog = self._dialog()
        dialog.key_edit.setText(KEY)
        self.assertFalse(dialog.activate_btn.isEnabled())
        self.assertFalse(dialog.terms_check.isEnabled())
        self.assertFalse(dialog.privacy_check.isEnabled())

        # Exercise the acknowledgement state without opening a modal document
        # viewer in the test; _read_terms/_read_privacy are the UI paths that
        # set these flags after showing the bundled documents.
        dialog._terms_opened = True
        dialog.terms_check.setEnabled(True)
        dialog.terms_check.setChecked(True)
        self.assertFalse(dialog.activate_btn.isEnabled())

        dialog._privacy_opened = True
        dialog.privacy_check.setEnabled(True)
        dialog.privacy_check.setChecked(True)
        self.assertTrue(dialog.activate_btn.isEnabled())

    def test_each_document_has_a_clear_local_open_action(self):
        dialog = self._dialog()
        self.assertEqual(dialog.terms_btn.text(), "Read Terms of Use")
        self.assertEqual(dialog.privacy_btn.text(), "Read Privacy Policy")
        self.assertFalse(dialog._legal_acknowledged())

        with mock.patch.object(dialog, "_open_legal") as open_legal:
            dialog._read_terms()
            dialog._read_privacy()
        self.assertEqual(open_legal.call_count, 2)
        self.assertTrue(dialog.terms_check.isEnabled())
        self.assertTrue(dialog.privacy_check.isEnabled())


class WhyActivateIsOff(unittest.TestCase):
    """A greyed Activate button with no reason reads as a broken app. A customer
    sent a key copied one character short; the button stayed off and nothing said
    why. These pin the explanation for each way the button can be off."""

    def _dialog(self):
        return LegalAcknowledgement._dialog(self)

    def _acknowledge(self, dialog):
        dialog._terms_opened = dialog._privacy_opened = True
        dialog.terms_check.setEnabled(True)
        dialog.privacy_check.setEnabled(True)
        dialog.terms_check.setChecked(True)
        dialog.privacy_check.setChecked(True)

    def test_a_key_one_character_short_says_so(self):
        dialog = self._dialog()
        self._acknowledge(dialog)
        dialog.key_edit.setText(KEY[:-1])
        self.assertFalse(dialog.activate_btn.isEnabled())
        self.assertFalse(dialog.key_hint.isHidden())
        self.assertIn("19 of 20", dialog.key_hint.text())

    def test_a_complete_but_wrong_key_says_to_check_each_group(self):
        dialog = self._dialog()
        self._acknowledge(dialog)
        dialog.key_edit.setText(KEY[:-1] + ("H" if KEY[-1] != "H" else "J"))
        self.assertFalse(dialog.activate_btn.isEnabled())
        self.assertIn("does not look right", dialog.key_hint.text())

    def test_a_good_key_waiting_on_the_documents_says_that(self):
        dialog = self._dialog()
        dialog.key_edit.setText(KEY)
        self.assertFalse(dialog.activate_btn.isEnabled())
        self.assertIn("both documents", dialog.key_hint.text())

    def test_nothing_is_said_when_there_is_nothing_to_say(self):
        dialog = self._dialog()
        self.assertTrue(dialog.key_hint.isHidden(), "empty field")
        self._acknowledge(dialog)
        dialog.key_edit.setText(KEY)
        self.assertTrue(dialog.activate_btn.isEnabled())
        self.assertTrue(dialog.key_hint.isHidden(), "Activate is on")

    def test_a_short_key_pasted_without_dashes_counts_the_same(self):
        dialog = self._dialog()
        dialog.key_edit.setText(KEY.replace("-", "")[:-1])
        self.assertIn("19 of 20", dialog.key_hint.text())


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheLegalReaderKeepsEveryWord(unittest.TestCase):
    def test_title_notice_and_date_are_lifted_out_not_dropped(self):
        from dialogs.legal_dialog import split_document
        parts = split_document(
            "# T\n\n> **Status: DRAFT.** Not reviewed.\n\n"
            "**Effective date:** [x] · **Last updated:** 1\n\n---\n\n## 1. A\n\ntext\n")
        self.assertEqual(parts["title"], "T")
        self.assertIn("DRAFT", parts["notice"])
        self.assertIn("Last updated", parts["meta"])
        self.assertTrue(parts["body"].startswith("## 1. A"))

    def test_both_real_documents_give_a_contents_list_of_every_section(self):
        from dialogs.legal_dialog import LegalDialog
        for name, n in (("TERMS_OF_USE.md", 12), ("PRIVACY_POLICY.md", 12)):
            d = LegalDialog("x", name)
            self.assertEqual(d.toc.count(), n)
            self.assertIn("Alphakore", d.view.toPlainText())
