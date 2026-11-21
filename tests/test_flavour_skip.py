"""E6c: the per-file skip rule for running the suite under a flavour."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flavour_skip import absent_addons_imported, skip_reason  # noqa: E402

LEADS = "from addons.leads import panel\n"
INNER = "def t():\n    import addons.email.panel\n"
BOQ = "from addons import boq\n"


class TheSkipRule(unittest.TestCase):

    def test_complete_skips_nothing(self):
        for src in (LEADS, INNER, BOQ):
            self.assertEqual(skip_reason(src, "complete"), "")

    def test_a_file_importing_an_absent_addon_is_skipped_with_the_reason(self):
        r = skip_reason(LEADS, "engineering")
        self.assertIn("engineering", r)
        self.assertIn("leads", r)
        self.assertIn("email", skip_reason(INNER, "engineering"))
        self.assertIn("boq", skip_reason(BOQ, "sales"))

    def test_a_file_importing_only_present_addons_runs(self):
        self.assertEqual(skip_reason(BOQ, "engineering"), "")
        self.assertEqual(skip_reason("import os\n", "sales"), "")

    def test_a_flavour_aware_file_is_kept(self):
        self.assertEqual(skip_reason("import flavour\n" + LEADS, "engineering"), "")
        self.assertEqual(skip_reason("needs_addon\n" + LEADS, "engineering"), "")

    def test_lists_every_absent_addon_sorted(self):
        src = "from addons.whatsapp import x\nfrom addons.inquiry import y\n"
        self.assertEqual(absent_addons_imported(src, "engineering"),
                         ["inquiry", "whatsapp"])


if __name__ == "__main__":
    unittest.main()
