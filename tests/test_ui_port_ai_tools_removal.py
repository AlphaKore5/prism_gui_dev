"""UI port stage 11: the AI tools screen is gone and the doors that led to it
still land somewhere useful. Real widgets, offscreen, sandbox HOME."""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_HOME = tempfile.mkdtemp(prefix="prism-stage11-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import (                                    # noqa: E402
    QApplication, QLabel, QPushButton,
)

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
_app.setStyleSheet(open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
                   .replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from widgets import settings_panel as SP                           # noqa: E402
from tests.test_ui_port_settings import _valid_state               # noqa: E402

def _panel(cfg=None):
    with mock.patch.object(SP.licensing, "state", _valid_state):
        p = SP.SettingsPanel(dict(cfg or {}))
        p.resize(980, 700)
        p.show()
        p.show_section("agents")
        _app.sendPostedEvents()
    return p


def _texts(p):
    return [l.text() for l in p.findChildren(QLabel)]


class TheScreenIsGone(unittest.TestCase):
    def test_no_route_screen_or_module_named_catalog_remains(self):
        import main_window as MW
        self.assertNotIn("catalog", MW.SCREENS)
        self.assertFalse(hasattr(MW, "CATALOG"))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "widgets", "catalog_panel.py")))
        self.assertFalse(os.path.exists(os.path.join(ROOT, "dialogs", "ai_directory_dialog.py")))
        src = open(os.path.join(ROOT, "main_window.py"), encoding="utf-8").read()
        self.assertNotRegex(src, r"catalog_panel|CatalogPanel|AIDirectoryDialog|key == \"catalog\"")

    def test_nothing_in_the_ui_emits_or_lists_the_catalog_key(self):
        pat = re.compile(r"""["']catalog["']""")
        for sub in ("widgets", "dialogs"):
            for name in os.listdir(os.path.join(ROOT, sub)):
                if name.endswith(".py"):
                    text = open(os.path.join(ROOT, sub, name), encoding="utf-8").read()
                    self.assertIsNone(pat.search(text), f"{sub}/{name}")

    def test_settings_more_and_agents_no_longer_offer_the_screen(self):
        self.assertNotIn("catalog", [k for k, _l, _b in SP.MORE_LINKS])
        p = _panel()
        p.show_section("agents")
        _app.sendPostedEvents()
        self.assertNotIn("Open the AI tools screen",
                         [b.text() for b in p.findChildren(QPushButton)])


class HomeRoutesStillWork(unittest.TestCase):
    def test_tools_chip_and_manage_add_ons_reach_real_settings_sections(self):
        from widgets import home_panel as H
        with mock.patch.object(SP.licensing, "state", _valid_state):
            home = H.HomePanel({})
            home.show()
            got = []
            home.open_addon.connect(got.append)
            btns = home.findChildren(QPushButton)
            next(b for b in btns if b.text() == "Tools").click()
            next(b for b in btns if b.text().startswith("Manage add-ons")).click()
        self.assertEqual(got, ["agents", "licence"])
        # and main_window's own router maps both onto Settings sections
        src = open(os.path.join(ROOT, "main_window.py"), encoding="utf-8").read()
        self.assertIn('"language", "team", "config", "status")', src)
        self.assertIn('key in ("agents", "profile", "key", "chrome", "licence"', src)


if __name__ == "__main__":
    unittest.main()
