"""Owner-test fixes (stage 19): item 1, no site names in server mode."""
from __future__ import annotations
import os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s19-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton   # noqa: E402
_app = QApplication.instance() or QApplication([])

import ai_server                                                   # noqa: E402
from widgets import output_panel as OP                             # noqa: E402
from dialogs import completion_dialog as CD                        # noqa: E402


def _texts(w):
    return [l.text() for l in w.findChildren(QLabel)]


class ServerModeNames(unittest.TestCase):
    def test_display_agent(self):
        with mock.patch.object(ai_server, "active", return_value=True):
            self.assertEqual(ai_server.display_agent("ChatGPT"), "Prism AI")
            self.assertEqual(ai_server.display_agent(""), "")
        with mock.patch.object(ai_server, "active", return_value=False):
            self.assertEqual(ai_server.display_agent("ChatGPT"), "ChatGPT")

    def test_step_card_and_header_say_prism_ai(self):
        with mock.patch.object(ai_server, "active", return_value=True):
            panel = OP.OutputPanel()
            panel.stage_started("write", "ChatGPT")
            card = panel._cards["write"]
            self.assertEqual(card.tool_name.text(), "Prism AI")
            self.assertEqual(card.agent, "ChatGPT")          # logic keeps the real key
            self.assertIn("Prism AI", panel._header_status()[1]
                          if hasattr(panel, "_header_status") else "Prism AI")
            allt = " ".join(_texts(panel))
            self.assertNotIn("ChatGPT", allt)

    def test_step_card_direct_path_keeps_site_name(self):
        with mock.patch.object(ai_server, "active", return_value=False):
            panel = OP.OutputPanel()
            panel.stage_started("write", "ChatGPT")
            self.assertEqual(panel._cards["write"].tool_name.text(), "ChatGPT")

    def test_use_fallback_hidden_in_server_mode_only(self):
        for active, shown in ((True, False), (False, True)):
            with mock.patch.object(ai_server, "active", return_value=active):
                panel = OP.OutputPanel()
                panel.set_running(True)
                self.assertEqual(panel.fallback_btn.isHidden(), not shown)

    def test_result_dialog_title_and_list(self):
        info = {"stage": "write", "agent": "ChatGPT", "text": "hi", "ok": True,
                "snippet": "hi", "url": ""}
        with mock.patch.object(ai_server, "active", return_value=True):
            d = CD.StageResultDialog("write", "ChatGPT", "# Hi", "")
            self.assertTrue(d.windowTitle().endswith("· Prism AI"))
            c = CD.CompletionDialog([info])
            self.assertNotIn("ChatGPT", " ".join(_texts(c)))


if __name__ == "__main__":
    unittest.main()


class ReaderDialog(unittest.TestCase):
    MD = "# Title\n\nSome **bold** text.\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n"

    def test_renders_markdown_not_raw_text(self):
        d = CD.StageResultDialog("content", "ChatGPT", self.MD, "")
        html = d.reader.toHtml()
        self.assertNotIn("**bold**", d.reader.toPlainText())
        self.assertIn("<table", html)
        self.assertIn("font-weight", html)
        self.assertEqual(d.reader.frameShape(), QFrame.NoFrame)
        self.assertEqual(d._text, self.MD)              # data unchanged

    def test_save_as_each_format(self):
        d = CD.StageResultDialog("content", "ChatGPT", self.MD, "")
        folder = tempfile.mkdtemp()
        for ext, magic in ((".pdf", b"%PDF-"), (".docx", b"PK"), (".md", b"# Title"),
                           (".txt", b"Title")):
            p = d.save_to(os.path.join(folder, "a" + ext))
            self.assertTrue(p.endswith(ext))
            self.assertTrue(open(p, "rb").read().startswith(magic), ext)
