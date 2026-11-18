"""Stage 26 (1): no ChatGPT / agent-site wording in server mode.

Real widgets, offscreen. `ai_server.active` is the only double. The direct
switch (PRISM_AI_DIRECT) keeps the old names, so each check has the other side.
"""
from __future__ import annotations
import os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s26a-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QLabel                 # noqa: E402
_app = QApplication.instance() or QApplication([])

import ai_server                                                   # noqa: E402
import core_bridge as CB                                           # noqa: E402
from widgets import output_panel as OP                             # noqa: E402
from widgets.agents_panel import AgentsPanel                       # noqa: E402


def _texts(w):
    return " | ".join(l.text() for l in w.findChildren(QLabel))


def server(on=True):
    return mock.patch.object(ai_server, "active", return_value=on)


class RoleLabels(unittest.TestCase):
    def test_label_names_the_role(self):
        with server():
            self.assertEqual(ai_server.display_agent("ChatGPT", "content"), "Prism AI · writer")
            self.assertEqual(ai_server.display_agent("ChatGPT", "brains"), "Prism AI · thinker")
            self.assertEqual(ai_server.display_agent("Perplexity", "research"), "Prism AI · research")
            self.assertEqual(ai_server.display_agent("ChatGPT", "visual"), "Prism AI · pictures")
            self.assertEqual(ai_server.display_agent("ChatGPT"), "Prism AI")
        with server(False):
            self.assertEqual(ai_server.display_agent("ChatGPT", "content"), "ChatGPT")

    def test_step_card_carries_the_role(self):
        with server():
            panel = OP.OutputPanel()
            panel.stage_started("content", "ChatGPT")
            card = panel._cards["content"]
            self.assertEqual(card.tool_name.text(), "Prism AI · writer")
            self.assertEqual(card.agent, "ChatGPT")
            self.assertNotIn("ChatGPT", _texts(panel))

    def test_failover_sentence_has_no_site_names(self):
        with server():
            panel = OP.OutputPanel()
            panel.stage_started("content", "ChatGPT")
            panel.stage_failover("content", "ChatGPT", "Claude", reason="x")
            card = panel._cards["content"]
            self.assertNotIn("ChatGPT", card.note.text())
            self.assertNotIn("Claude", card.note.text())
            self.assertEqual(card.agent, "Claude")      # logic keeps the real key


class PlanPickers(unittest.TestCase):
    def _panel(self):
        panel = AgentsPanel()
        panel.set_content(
            routing={"content": {"needed": True, "questions": ["Write it"]}},
            agents_cfg={"content": "ChatGPT"}, query="write an essay")
        return panel

    def test_chip_says_prism_ai_and_has_no_menu(self):
        with server():
            panel = self._panel()
            row = panel._rows[0]
            self.assertEqual(row.chip.shown(), "Prism AI · writer")
            self.assertEqual(row.chip.current(), "ChatGPT")       # run logic unchanged
            self.assertNotIn("waits up to", row.engine_meta.text())
            self.assertNotIn("ChatGPT", row.chip.toolTip())
            with mock.patch("widgets.agents_panel.QMenu") as menu:
                row.chip._open_menu()
                menu.assert_not_called()

    def test_direct_mode_keeps_site_and_menu(self):
        with server(False):
            row = self._panel()._rows[0]
            self.assertEqual(row.chip.shown(), "ChatGPT")
            with mock.patch("widgets.agents_panel.QMenu") as menu:
                menu.return_value.exec.return_value = None
                row.chip._open_menu()
                menu.assert_called()


class RunScreen(unittest.TestCase):
    def test_completed_chip_is_just_the_time(self):
        with server():
            panel = OP.OutputPanel()
            panel.stage_started("content", "ChatGPT")
            panel.stage_waiting("content", 300)
            card = panel._cards["content"]
            self.assertNotIn("up to", card.status_text())
            panel.stage_done("content", ["hello"], "")
            self.assertNotIn("up to", card.status_text())

    def test_direct_mode_completed_chip_drops_the_budget_too(self):
        with server(False):
            panel = OP.OutputPanel()
            panel.stage_started("content", "ChatGPT")
            panel.stage_waiting("content", 300)
            self.assertIn("up to 300s", panel._cards["content"].status_text())
            panel.stage_done("content", ["hello"], "")
            self.assertNotIn("up to", panel._cards["content"].status_text())


class LogLines(unittest.TestCase):
    def test_server_words(self):
        with server():
            self.assertEqual(ai_server.server_words(
                "   ⏳  waiting up to 600s for Claude to finish…"),
                "   ⏳  Prism AI is working on this step…")
            self.assertEqual(ai_server.server_words(
                "ChatGPT will search the web and make up to 6 images"),
                "Prism AI will search the web and make up to 6 images")
        with server(False):
            line = "waiting up to 600s for Claude to finish"
            self.assertEqual(ai_server.server_words(line), line)

    def test_engine_log_goes_through_the_rewriter(self):
        ui = CB.get_ui()
        got = []
        ui.set_sink(lambda lvl, txt: got.append(txt))
        try:
            with server():
                ui.set_rewriter(ai_server.server_words)
                ui.info("   waiting up to 300s for ChatGPT to finish…")
        finally:
            ui.set_rewriter(None)
            ui.set_sink(None)
        self.assertEqual(got, ["Prism AI is working on this step…"])


if __name__ == "__main__":
    unittest.main()
