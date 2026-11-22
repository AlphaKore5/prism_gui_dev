"""S3b: main_window must not import email_config at module level, so a build
that does not ship the Email add-on still starts. Runs the real MainWindow in
a child interpreter with email_config (and its siblings) blocked."""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_CHILD = r"""
import sys
for m in ("email_config",):
    sys.modules[m] = None          # `import email_config` now raises ImportError
sys.path.insert(0, %(root)r)
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication([])
import main_window
from unittest import mock
from addons import registry
# a Studio-like window: no Email / Inquiry add-on, so nothing needs email_config
kept = tuple(a for a in registry.REGISTRY if a.key in ("reel", "motion"))
with mock.patch.multiple(registry, REGISTRY=kept, _BY_KEY={a.key: a for a in kept}):
    win = main_window.MainWindow()
    assert len(main_window.SCREENS) == win.screens.count()
    shown = []
    QMessageBox.information = lambda *a, **k: shown.append(a[-1])
    win._open_email_dialog()      # must say "not available", not import email_config
assert any("isn't available" in m for m in shown), shown
print("CHILD-OK")
"""


def test_main_window_has_no_module_level_email_config_import():
    tree = ast.parse(open(os.path.join(ROOT, "main_window.py"), encoding="utf-8").read())
    top = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            top += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            top.append(node.module)
    assert "email_config" not in top, top


def test_window_starts_and_email_dialog_refuses_with_email_config_blocked():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
               HOME=tempfile.mkdtemp(prefix="prism-s3b-"))
    r = subprocess.run([sys.executable, "-c", _CHILD % {"root": ROOT}],
                       env=env, capture_output=True, text=True, timeout=240)
    assert "CHILD-OK" in r.stdout, (r.stdout[-800:], r.stderr[-1500:])
