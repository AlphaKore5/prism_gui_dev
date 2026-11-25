"""Home's "Try:" chips offer only tools this build has. A Sales or Engineering
build used to show "Create a reel" (and Studio "Analyze this BOQ"); a click
only produced "not in this build of Prism". Real HomePanel, offscreen."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
_HOME = tempfile.mkdtemp(prefix="prism-try-chips-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QPushButton   # noqa: E402

_app = QApplication.instance() or QApplication([])

import festivals                                          # noqa: E402
from addons import registry                               # noqa: E402
from flavour import ADDONS_BY_FLAVOUR                     # noqa: E402
from widgets import home_panel as H                       # noqa: E402

# chip label -> the add-on it opens (None: not an add-on, always offered)
CHIPS = {"Summarize a PDF": "inquiry", "Create a reel": "reel",
         "Analyze this BOQ": "boq", "Clean up artifacts": None}


def _chips_in(flavour: str) -> set[str]:
    """The chip labels Home draws when the build holds only `flavour`'s add-ons."""
    have = set(ADDONS_BY_FLAVOUR[flavour])
    everything = set(ADDONS_BY_FLAVOUR["complete"])
    with mock.patch.object(registry, "is_absent",
                           lambda key: key in everything and key not in have), \
         mock.patch.object(H.DATA, "recent_runs", lambda cfg, n: []), \
         mock.patch.object(festivals, "upcoming", lambda n, today=None: []):
        p = H.HomePanel({})
        p.resize(1076, 668); p.show(); _app.processEvents()
        return {b.text() for b in p.findChildren(QPushButton, "tryChip")}


class TryChipsMatchTheBuild(unittest.TestCase):
    def test_each_flavour_shows_exactly_the_chips_whose_tool_it_has(self):
        for flavour in ("complete", "studio", "sales", "engineering"):
            want = {label for label, key in CHIPS.items()
                    if key is None or key in ADDONS_BY_FLAVOUR[flavour]}
            self.assertEqual(_chips_in(flavour), want, flavour)

    def test_the_complete_build_keeps_all_four(self):
        self.assertEqual(_chips_in("complete"), set(CHIPS))


if __name__ == "__main__":
    unittest.main()
