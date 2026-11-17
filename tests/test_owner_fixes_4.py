"""Owner-test fixes (stage 19), items 2 and 4: a follow-up that only asks for a file
format never re-asks the AI, and the file is a REAL PDF / DOCX / XLSX."""
from __future__ import annotations
import os, sys, tempfile, unittest, zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
_HOME = tempfile.mkdtemp(prefix="prism-s19-4-")
os.environ["HOME"] = _HOME
os.environ["USERPROFILE"] = _HOME

from PySide6.QtWidgets import QApplication                       # noqa: E402
_app = QApplication.instance() or QApplication([])

import docexport                                                  # noqa: E402
import core_bridge as CB                                          # noqa: E402

MD = ("# Essay\n\nSome **bold** words.\n\n- one\n- two\n\n"
      "| name | qty |\n|---|---|\n| bolt | 4 |\n\n```\ncode here\n```\n")


class RequestDetection(unittest.TestCase):
    def test_the_owners_sentence_is_a_pdf_request(self):
        self.assertEqual(docexport.requested_ext("give me in this pdf form"), ".pdf")
        self.assertTrue(docexport.is_pure_format_request("give me in this pdf form"))

    def test_summarising_a_pdf_is_not(self):
        self.assertEqual(docexport.requested_ext("summarise this pdf"), "")

    def test_a_change_plus_a_format_is_not_pure(self):
        self.assertTrue(docexport.requested_ext("make it shorter and give it as a pdf"))
        self.assertFalse(docexport.is_pure_format_request("make it shorter and give it as a pdf"))


class RealFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def test_pdf_is_a_real_pdf(self):
        path, note = docexport.export_answer(MD, ".pdf", self.d)
        self.assertTrue(path.endswith(".pdf"))
        data = open(path, "rb").read()
        self.assertEqual(data[:5], b"%PDF-")
        self.assertIn(b"%%EOF", data[-64:])
        self.assertGreater(len(data), 2000)
        self.assertNotIn("can't be made", note)

    def test_docx_opens(self):
        path, _ = docexport.export_answer(MD, ".docx", self.d)
        self.assertTrue(zipfile.is_zipfile(path))
        from docx import Document
        self.assertTrue(any("Essay" in p.text for p in Document(path).paragraphs))

    def test_xlsx_keeps_the_table(self):
        path, _ = docexport.export_answer(MD, ".xlsx", self.d)
        from openpyxl import load_workbook
        ws = load_workbook(path).worksheets[0]
        self.assertEqual([c.value for c in ws[2]], ["bolt", "4"])


class FollowupNeverReAsks(unittest.TestCase):
    def test_pure_format_followup_writes_a_file_and_runs_no_step(self):
        import main_window
        win = main_window.MainWindow.__new__(main_window.MainWindow)
        win._followup_text = "give me in this pdf form"
        win._followup_session = {"artifacts_dir": tempfile.mkdtemp()}
        win.statusBar = lambda: mock.Mock()
        responses = {"content": ["# Essay\n\nBody."]}
        shown = {}
        class Box:                       # stands in for the "file is ready" box
            def __init__(self, *a): pass
            def setWindowTitle(self, t): pass
            def setText(self, t): shown["text"] = t
            def addButton(self, *a): return object()
            def exec(self): pass
            def clickedButton(self): return None
            AcceptRole = ActionRole = RejectRole = 0
        with mock.patch.object(main_window.ai_server, "active", return_value=True), \
             mock.patch.object(main_window, "QMessageBox", Box), \
             mock.patch.object(main_window.QMessageBox, "AcceptRole", 0, create=True):
            self.assertTrue(win._followup_as_local_file(responses))
        self.assertIn(".pdf", shown["text"])
        pdfs = [f for f in os.listdir(win._followup_session["artifacts_dir"]) if f.endswith(".pdf")]
        self.assertEqual(len(pdfs), 1)

    def test_direct_mode_and_real_changes_still_go_to_the_ai(self):
        import main_window
        win = main_window.MainWindow.__new__(main_window.MainWindow)
        win._followup_text = "give me in this pdf form"
        with mock.patch.object(main_window.ai_server, "active", return_value=False):
            self.assertFalse(win._followup_as_local_file({"content": ["x"]}))
        win._followup_text = "make it shorter as a pdf"
        with mock.patch.object(main_window.ai_server, "active", return_value=True):
            self.assertFalse(win._followup_as_local_file({"content": ["x"]}))


if __name__ == "__main__":
    unittest.main()
