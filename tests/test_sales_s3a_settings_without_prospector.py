"""S3a: Settings -> AI tools must build in a build that has no prospector
package (Studio/Engineering), and must behave as before where it exists.
Run under PRISM_TEST_FLAVOUR=sales and complete."""
from __future__ import annotations

import os
import sys
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pytest
from PySide6.QtWidgets import QApplication, QLabel

_app = QApplication.instance() or QApplication([])

import licensing  # noqa: E402
from widgets import settings_panel as SP  # noqa: E402


def _agents_page(server_mode: bool):
    with mock.patch.object(SP.licensing, "state",
                           lambda: licensing.LicenseState(status=licensing.NONE)), \
         mock.patch.object(SP.CB.ai_client, "active", lambda: server_mode):
        p = SP.SettingsPanel({"onboarded": True})
        p.show_section("agents")
    return p


def _texts(p):
    return " | ".join(l.text() for l in p.findChildren(QLabel))


@pytest.mark.parametrize("server_mode", [True, False])
def test_agents_page_builds_with_prospector_blocked(server_mode):
    # None in sys.modules makes `import prospector` raise ImportError
    with mock.patch.dict(sys.modules, {"prospector": None,
                                       "prospector.gateway": None}):
        assert SP._verifier_card_wanted() is False
        p = _agents_page(server_mode)
    assert p is not None


@pytest.mark.parametrize("pooled", [True, False])
def test_with_prospector_present_the_card_follows_pooled(pooled):
    from prospector import gateway
    with mock.patch.object(gateway, "pooled", lambda: pooled):
        assert SP._verifier_card_wanted() is (not pooled)


def test_the_page_has_no_unguarded_prospector_import():
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "widgets", "settings_panel.py"),
                          encoding="utf-8").read())
    bad = []
    for fn in ast.walk(tree):
        if isinstance(fn, ast.ImportFrom) and fn.module and fn.module.split(".")[0] == "prospector":
            bad.append(fn.lineno)
    # the only import left is inside _verifier_card_wanted's try block
    assert len(bad) == 1, bad
