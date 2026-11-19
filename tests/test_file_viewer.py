"""The in-app file viewer: every produced or attached file is shown INSIDE
Prism (dialogs/file_viewer.py, viewer_data.py, viewer.py), and the operating
system's own opener is reached from exactly one button.

Real files, real offscreen widgets. Workers are run inline (`start` calls
`run`) because tests may not spin an event loop; the tests assert the worker
class is the one doing the reading.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PySide6.QtGui import QImage                                    # noqa: E402
from PySide6.QtWidgets import (QApplication, QLabel, QPlainTextEdit, QTabWidget,  # noqa: E402
                               QTableView, QTextBrowser, QTextEdit)

import paths                                                        # noqa: E402
import viewer                                                       # noqa: E402
import viewer_data as VD                                            # noqa: E402
from dialogs import file_viewer as FV                               # noqa: E402

_app = QApplication.instance() or QApplication([])
TMP = tempfile.mkdtemp(prefix="prism-viewer-")


def _p(name):
    return os.path.join(TMP, name)


def make_files() -> dict:
    f = {}
    big = _p("big.csv")
    with open(big, "w", encoding="utf-8") as fh:
        fh.write("id,name,qty\n")
        for i in range(VD.MAX_ROWS + 500):
            fh.write(f"{i},item {i},{i * 3}\n")
    f["bigcsv"] = big
    small = _p("small.csv")
    with open(small, "w", encoding="utf-8-sig") as fh:
        fh.write("name;qty\nbolt;10\nnut;2\nwasher;100\n")
    f["csv"] = small
    evil = _p("evil.csv")
    with open(evil, "w", encoding="utf-8") as fh:
        fh.write("a,b\n=cmd|' /C calc'!A0,<script>alert(1)</script>\n")
    f["evil"] = evil
    from openpyxl import Workbook
    wb = Workbook()
    wb.active.title = "Items"
    wb.active.append(["part", "qty"])
    wb.active.append(["bolt", 4])
    wb.active.append(["formula", "=SUM(B2:B2)"])
    ws2 = wb.create_sheet("Totals")
    ws2.append(["total"])
    ws2.append([99])
    wb.save(_p("book.xlsx"))
    f["xlsx"] = _p("book.xlsx")
    from docx import Document
    d = Document()
    d.add_heading("Quotation", 1)
    d.add_paragraph("Dear customer, <script>alert(1)</script> prices below.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "item", "price"
    t.cell(1, 0).text, t.cell(1, 1).text = "valve", "120"
    d.save(_p("quote.docx"))
    f["docx"] = _p("quote.docx")
    from PIL import Image
    from PIL import ImageDraw
    pages = [Image.new("RGB", (480, 620), "white") for _ in range(3)]
    for n, pg in enumerate(pages, 1):
        draw = ImageDraw.Draw(pg)
        draw.rectangle((40, 40, 440, 90), outline="black", width=3)
        draw.text((60, 55), f"Quotation page {n}", fill="black")
        for y in range(130, 560, 40):
            draw.line((40, y, 440, y), fill="#888", width=2)
    pages[0].save(_p("three.pdf"), save_all=True, append_images=pages[1:])
    f["pdf"] = _p("three.pdf")
    with open(_p("notes.md"), "w", encoding="utf-8") as fh:
        fh.write("# Title\n\n- one\n- two\n\n[local](file:///etc/passwd) <b>raw</b>\n")
    f["md"] = _p("notes.md")
    with open(_p("plain.txt"), "w", encoding="utf-8") as fh:
        fh.write("first line\nneedle in a haystack\nlast line\n")
    f["txt"] = _p("plain.txt")
    img = QImage(80, 60, QImage.Format_RGB32)
    img.fill(0x2266CC)
    img.save(_p("pic.png"))
    f["png"] = _p("pic.png")
    import ezdxf
    doc = ezdxf.new()
    doc.modelspace().add_line((0, 0), (100, 50))
    doc.modelspace().add_circle((50, 25), 20)
    doc.saveas(_p("plan.dxf"))
    f["dxf"] = _p("plan.dxf")
    with open(_p("blob.bin"), "wb") as fh:
        fh.write(b"\x00\x01\x02\xff" * 64)
    f["bin"] = _p("blob.bin")
    return f


FILES = make_files()


def _inline(cls):
    """Run a worker's body inline instead of starting a thread."""
    return mock.patch.object(cls, "start", lambda self, *a, **k: self.run())


class _Viewer:
    """Open a FileViewer with its workers inline, and record that they ran."""

    def open(self, path):
        self.started = []
        real = FV._ReadWorker.run

        def run(w):
            self.started.append(type(w).__name__)
            return real(w)
        with mock.patch.object(FV._ReadWorker, "start", lambda w, *a, **k: w.run()), \
                mock.patch.object(FV._ReadWorker, "run", run), \
                mock.patch.object(FV._PageWorker, "start", lambda w, *a, **k: w.run()):
            return FV.FileViewer(path)


class TheDataLayerReadsFilesAsData(unittest.TestCase):
    def test_every_kind_is_classified(self):
        want = {"bigcsv": "csv", "xlsx": "xlsx", "docx": "docx", "pdf": "pdf",
                "md": "markdown", "txt": "text", "png": "image", "dxf": "dxf",
                "bin": "other"}
        for key, kind in want.items():
            self.assertEqual(VD.classify(FILES[key]), kind, key)
        self.assertEqual(VD.classify(TMP), "folder")

    def test_a_big_csv_is_capped_and_says_so(self):
        sheet = VD.read(FILES["bigcsv"])["sheets"][0]
        self.assertEqual(len(sheet["rows"]), VD.MAX_ROWS)
        self.assertTrue(sheet["truncated"])
        self.assertIsNone(sheet["rows_total"])
        self.assertEqual(sheet["columns"], ["id", "name", "qty"])

    def test_a_semicolon_csv_with_a_bom_is_split_right(self):
        sheet = VD.read(FILES["csv"])["sheets"][0]
        self.assertEqual(sheet["columns"], ["name", "qty"])
        self.assertEqual(sheet["rows"][1], ["nut", "2"])
        self.assertFalse(sheet["truncated"])

    def test_xlsx_gives_both_sheets_and_an_uncalculated_formula_is_computed(self):
        # Was "formulas stay text". 19 Nov 2026: Prism's own priced BOQ showed
        # =SUM(...) where the totals belong, so simple formulas are now computed
        # by viewer_data's own calculator (never eval); the rest stay text
        # (tests/test_viewer_xlsx_formulas.py).
        data = VD.read(FILES["xlsx"])
        self.assertEqual([s["name"] for s in data["sheets"]], ["Items", "Totals"])
        self.assertEqual(data["sheets"][1]["rows"], [["99"]])
        self.assertEqual(data["sheets"][0]["rows"][1], ["formula", "4"])
        self.assertFalse(data["sheets"][0]["cols_cut"])

    def test_docx_blocks_in_order(self):
        blocks = VD.read(FILES["docx"])["blocks"]
        self.assertEqual(blocks[0], ("heading", 1, "Quotation"))
        self.assertEqual(blocks[1][0], "para")
        self.assertEqual(blocks[2][0], "table")

    def test_pdf_page_count_and_a_rendered_page(self):
        self.assertEqual(VD.read(FILES["pdf"])["pages"], 3)
        w, h, raw = VD.render_pdf_page(FILES["pdf"], 1)
        self.assertGreater(w, 100)
        self.assertEqual(len(raw), w * h * 4)

    def test_dxf_renders_a_png(self):
        self.assertTrue(VD.read(FILES["dxf"])["png"].startswith(b"\x89PNG"))

    def test_a_missing_or_broken_file_gives_a_plain_reason_not_a_traceback(self):
        gone = VD.read(_p("nope.csv"))
        self.assertIn("no longer where Prism saved it", gone["error"])
        broken = _p("broken.xlsx")
        with open(broken, "wb") as fh:
            fh.write(b"this is not a zip")
        err = VD.read(broken)["error"]
        self.assertTrue(err)
        self.assertNotIn("Traceback", err)

    def test_an_unknown_binary_is_not_read_at_all(self):
        data = VD.read(FILES["bin"])
        self.assertEqual(data["kind"], "other")
        self.assertEqual(data["error"], "")
        self.assertNotIn("text", data)


class TheViewerShowsTheRightWidgets(unittest.TestCase):
    def setUp(self):
        self.v = _Viewer()

    def test_csv_is_a_sortable_table_and_the_cap_is_stated(self):
        dlg = self.v.open(FILES["bigcsv"])
        self.assertEqual(self.v.started, ["_ReadWorker"])         # read on a worker
        table = dlg.findChild(QTableView)
        self.assertTrue(table.isSortingEnabled())
        self.assertEqual(table.model().rowCount(), VD.MAX_ROWS)
        note = [l.text() for l in dlg.findChildren(QLabel) if "first 2,000 rows" in l.text()]
        self.assertTrue(note, "the row cap is said on screen")

    def test_csv_sorts_numbers_as_numbers_and_filters(self):
        dlg = self.v.open(FILES["csv"])
        view = dlg._sheet_views[0]
        view.table.sortByColumn(1, __import__("PySide6.QtCore", fromlist=["Qt"]).Qt.AscendingOrder)
        order = [view.proxy.index(r, 0).data() for r in range(view.proxy.rowCount())]
        self.assertEqual(order, ["nut", "bolt", "washer"])        # 2 < 10 < 100, not text order
        dlg.search.setText("bol")
        self.assertEqual(view.proxy.rowCount(), 1)

    def test_xlsx_has_a_tab_per_sheet(self):
        dlg = self.v.open(FILES["xlsx"])
        tabs = dlg.findChild(QTabWidget)
        self.assertEqual([tabs.tabText(i) for i in range(tabs.count())], ["Items", "Totals"])
        dlg._tabs.setCurrentIndex(1)
        self.assertIn("99", dlg.text_for_copy())

    def test_docx_is_plain_text_and_a_table_never_html(self):
        dlg = self.v.open(FILES["docx"])
        edit = dlg.findChild(QTextEdit)
        text = edit.toPlainText()
        self.assertIn("Quotation", text)
        self.assertIn("<script>alert(1)</script>", text)           # shown as characters
        self.assertNotIn("<script", edit.toHtml().replace("&lt;script", ""))
        self.assertTrue(edit.document().rootFrame().childFrames())  # the table

    def test_pdf_pages_paging_and_zoom(self):
        dlg = self.v.open(FILES["pdf"])
        self.assertEqual(dlg.page_label.text(), "Page 1 of 3")
        self.assertFalse(dlg.prev_btn.isEnabled())
        self.assertTrue(dlg.prev_btn.toolTip())                    # says why
        self.assertFalse(dlg._pdf_view.image.isNull())
        with _inline(FV._PageWorker):
            dlg.next_btn.click()
            dlg.next_btn.click()
        self.assertEqual(dlg.page_label.text(), "Page 3 of 3")
        self.assertFalse(dlg.next_btn.isEnabled())
        before = dlg._pdf_view.image.width()
        with _inline(FV._PageWorker):
            dlg.zoom_in.click()
        self.assertGreater(dlg._pdf_view.image.width(), before)

    def test_markdown_is_rendered_text_and_a_file_link_is_not_followed(self):
        dlg = self.v.open(FILES["md"])
        view = dlg.findChild(QTextBrowser)
        self.assertIn("Title", view.toPlainText())
        self.assertIn("<b>raw</b>", view.toPlainText())            # not interpreted
        self.assertFalse(view.openExternalLinks())
        self.assertFalse(view.openLinks())

    def test_text_has_search(self):
        dlg = self.v.open(FILES["txt"])
        edit = dlg.findChild(QPlainTextEdit)
        dlg.search.setText("needle")
        self.assertEqual(edit.textCursor().selectedText(), "needle")

    def test_image_and_dxf_are_pictures(self):
        for key in ("png", "dxf"):
            dlg = self.v.open(FILES[key])
            self.assertFalse(dlg._pic_view.image.isNull(), key)
            self.assertFalse(dlg.copy_btn.isEnabled())
            self.assertTrue(dlg.copy_btn.toolTip())                # disabled says why

    def test_unknown_binary_shows_name_size_type_and_the_other_app_button(self):
        dlg = self.v.open(FILES["bin"])
        texts = " ".join(l.text() for l in dlg.findChildren(QLabel))
        self.assertIn("blob.bin", texts)
        self.assertIn("256 B", texts)
        self.assertTrue(dlg.other_btn.isEnabled())

    def test_a_deleted_file_disables_the_buttons_with_a_reason(self):
        path = _p("soon-gone.txt")
        open(path, "w").write("x")
        os.remove(path)
        dlg = self.v.open(path)
        self.assertIn("no longer where Prism saved it",
                      " ".join(l.text() for l in dlg.findChildren(QLabel)))
        for b in (dlg.save_btn, dlg.reveal_btn, dlg.other_btn):
            self.assertFalse(b.isEnabled())
            self.assertTrue(b.toolTip())

    def test_malicious_looking_cells_are_just_text(self):
        dlg = self.v.open(FILES["evil"])
        rows = dlg._sheet_views[0].sheet["rows"]
        self.assertEqual(rows[0][0], "=cmd|' /C calc'!A0")
        self.assertEqual(rows[0][1], "<script>alert(1)</script>")


class OnlyOneButtonReachesTheOS(unittest.TestCase):
    def test_viewing_every_kind_never_touches_the_os(self):
        v = _Viewer()
        with mock.patch("subprocess.Popen") as popen, \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as qt, \
                mock.patch.object(paths, "open_in_other_app") as other, \
                mock.patch.object(paths, "reveal_result") as reveal:
            for key in FILES:
                dlg = v.open(FILES[key])
                dlg.copy_btn.click() if dlg.copy_btn.isEnabled() else None
            popen.assert_not_called()
            qt.assert_not_called()
            other.assert_not_called()
            reveal.assert_not_called()

    def test_the_secondary_button_goes_through_the_one_wrapper(self):
        dlg = _Viewer().open(FILES["csv"])
        self.assertIn("Leaves Prism", dlg.other_btn.toolTip())
        with mock.patch.object(paths, "open_in_other_app") as other:
            dlg.other_btn.click()
        other.assert_called_once_with(FILES["csv"])

    def test_show_in_file_manager_is_the_reveal_wrapper(self):
        dlg = _Viewer().open(FILES["csv"])
        with mock.patch.object(paths, "reveal_result") as reveal:
            dlg.reveal_btn.click()
        reveal.assert_called_once_with(FILES["csv"])

    def test_save_as_copies_the_file(self):
        dlg = _Viewer().open(FILES["csv"])
        dest = _p("copy-of-small")
        self.assertTrue(dlg.save_to(dest))
        self.assertTrue(os.path.isfile(dest + ".csv"))


class EveryDoorRoutesThroughTheViewer(unittest.TestCase):
    def test_open_result_for_a_local_file_opens_the_viewer_not_the_os(self):
        with mock.patch.object(viewer, "open_file") as vf, \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as qt:
            paths.open_result(FILES["csv"])
        vf.assert_called_once()
        qt.assert_not_called()

    def test_open_result_for_a_web_address_still_uses_the_browser(self):
        with mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as qt:
            paths.open_result("https://example.com/x")
        qt.assert_called_once()

    def test_open_preview_builds_a_fileviewer_for_files_and_a_folder_dialog_for_folders(self):
        from dialogs import preview_dialog as PD
        with mock.patch.object(FV.FileViewer, "exec", return_value=0) as ex, \
                mock.patch.object(FV, "_ReadWorker"):
            PD.open_preview(FILES["xlsx"])
        ex.assert_called_once()
        with mock.patch.object(PD.FolderPreviewDialog, "exec", return_value=0) as ex:
            viewer.open_file(TMP)
        ex.assert_called_once()

    def test_a_file_card_opens_in_the_viewer(self):
        from widgets.file_card import FileCard
        card = FileCard(FILES["xlsx"])
        with mock.patch.object(viewer, "open_file") as vf:
            card.open_btn.click()
        vf.assert_called_once()

    def test_the_attachment_tray_opens_in_the_viewer(self):
        from widgets.files_panel import FilesPanel
        with mock.patch.object(viewer, "open_file") as vf:
            FilesPanel._open(FILES["png"])
        vf.assert_called_once()

    def test_inquiry_open_in_file_manager_shows_the_folder_in_prism(self):
        from addons.inquiry import quotation
        with mock.patch.object(viewer, "open_file") as vf:
            quotation.open_in_file_manager(TMP)
        vf.assert_called_once()

    def test_a_clicked_file_link_goes_to_the_viewer_and_junk_schemes_are_ignored(self):
        with mock.patch.object(viewer, "open_file") as vf, \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl") as qt:
            viewer.open_link("file:///etc/passwd")
            viewer.open_link("javascript:alert(1)")
            viewer.open_link("data:text/html,x")
            viewer.open_link("https://example.com")
        vf.assert_called_once()
        qt.assert_called_once()

    def test_routing_links_does_not_keep_the_browser_alive(self):
        """route_links must not make a reference cycle through the browser:
        a cycle is freed by the garbage collector at a random later moment,
        and on Windows that crashed test_chat_thread (ISS-026). Without the
        cycle, dropping the last reference frees the widget at once."""
        import gc
        import weakref
        from PySide6.QtWidgets import QTextBrowser
        gc.disable()
        try:
            browser = QTextBrowser()
            viewer.route_links(browser)
            alive = weakref.ref(browser)
            del browser
            self.assertIsNone(alive(), "the link handler still holds the browser")
        finally:
            gc.enable()

    def test_a_clicked_link_in_a_routed_browser_reaches_the_viewer(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QTextBrowser
        browser = QTextBrowser()
        viewer.route_links(browser)
        with mock.patch.object(viewer, "open_link") as ol:
            browser.anchorClicked.emit(QUrl("file:///tmp/x.csv"))
        ol.assert_called_once_with("file:///tmp/x.csv", browser)

    def test_the_answer_reader_does_not_hand_links_to_the_os(self):
        from dialogs.answer_dialog import AnswerDialog
        dlg = AnswerDialog("t", "s", "q", "[x](file:///etc/passwd)", "Groq")
        self.assertFalse(dlg.view.openExternalLinks())
        self.assertFalse(dlg.view.openLinks())


# Files allowed to start an OS program for a local file, each with the reason.
OS_LAUNCH_ALLOWED = {
    "paths.py": "the one wrapper (open_in_other_app / reveal_result)",
    "addons/boq/converter_setup.py": "starts the ODA File Converter INSTALLER, not a document",
    "hvac_takeoff/hvac_takeoff.py": "standalone Tk tool (no Qt, cannot show a Prism dialog)",
}
_PATTERNS = (
    re.compile(r"os\.startfile\("),
    re.compile(r"xdg-open"),
    re.compile(r"openUrl\(\s*QUrl\.fromLocalFile"),
    re.compile(r"Popen\(\s*\[\s*[\"'](open|explorer)[\"']"),
    re.compile(r"\.openUrl\(\s*QUrl\(\s*(path|folder|p|target|self\.path)\s*\)"),
)


class NoNewLocalFileLaunchOutsideTheWrapper(unittest.TestCase):
    def test_product_code_never_launches_the_os_for_a_local_file(self):
        offenders = []
        for base, dirs, names in os.walk(ROOT):
            rel_base = os.path.relpath(base, ROOT)
            dirs[:] = [d for d in dirs if d not in (
                "tests", ".venv", "devtools", "__pycache__", "prism_terminal", "wt",
                "packaging", ".git", "node_modules", "build", "dist")]
            for n in names:
                if not n.endswith(".py"):
                    continue
                rel = os.path.normpath(os.path.join(rel_base, n)).replace("\\", "/")
                if rel in OS_LAUNCH_ALLOWED:
                    continue
                with open(os.path.join(base, n), encoding="utf-8") as fh:
                    for i, line in enumerate(fh, 1):
                        if line.lstrip().startswith("#"):
                            continue
                        if any(p.search(line) for p in _PATTERNS):
                            offenders.append(f"{rel}:{i}: {line.strip()}")
        self.assertEqual(offenders, [], "\n".join(
            ["A local file is being handed to the OS instead of Prism's viewer."]
            + offenders + ["", "Call paths.open_file(path, parent) (viewer). The OS "
                           "launcher lives only in paths.open_in_other_app."]))

    def test_no_text_browser_hands_links_to_the_os(self):
        offenders = []
        for sub in ("dialogs", "widgets", "addons"):
            for base, _d, names in os.walk(os.path.join(ROOT, sub)):
                for n in names:
                    if n.endswith(".py"):
                        src = open(os.path.join(base, n), encoding="utf-8").read()
                        for m in re.finditer(r"(\w+(?:\.\w+)*)\.setOpenExternalLinks\(True\)", src):
                            who = m.group(1)
                            if "QTextBrowser" in src and who in ("self.view", "body", "self"):
                                offenders.append(f"{n}: {who}")
        # only QLabels with our own fixed links may keep it
        self.assertEqual([o for o in offenders if o.startswith(("answer_dialog", "history_dialog",
                                                                "chat_thread"))], [])


if __name__ == "__main__":
    unittest.main()
