"""Artifacts now open inside Prism instead of being handed to the OS — see
dialogs/preview_dialog.py. Covers the kind classifier, that each viewer
actually constructs without crashing (a real bug this way: an unknown-icon
KeyError segfaulted the process on first commit of this file, because the
dialog header glyph registry has no "pdf"/"audio"/"text" icon), and that
open_preview() dispatches to the right dialog for a file vs. a folder.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

_app = QApplication.instance() or QApplication([])


class Classifying(unittest.TestCase):

    def test_kinds_are_recognised_case_insensitively(self):
        from dialogs.preview_dialog import _classify
        self.assertEqual(_classify("a.PNG"), "image")
        self.assertEqual(_classify("a.mp4"), "video")
        self.assertEqual(_classify("a.MP3"), "audio")
        self.assertEqual(_classify("a.pdf"), "pdf")
        self.assertEqual(_classify("a.py"), "text")

    def test_modern_office_files_open_inside_prism(self):
        from dialogs.preview_dialog import _classify
        self.assertEqual(_classify("a.DOCX"), "document")
        self.assertEqual(_classify("a.xlsx"), "spreadsheet")
        self.assertEqual(_classify("a.pptx"), "presentation")

    def test_legacy_office_and_archive_formats_are_not_renderable(self):
        from dialogs.preview_dialog import _classify
        for ext in (".zip", ".doc", ".xls", ".ppt", ".ods"):
            self.assertEqual(_classify(f"a{ext}"), "other")


# QtMultimedia imports a Qt module that dlopen()s the platform audio stack —
# libpulse on Linux. PySide6 being installed does NOT mean it can load: a
# headless runner without libpulse.so.0 raises ImportError from the import
# itself.
#
# The PRODUCT handles that: open_preview() wraps the construction in
# `except ImportError` and shows "open in the default app" instead. Since
# 19 Nov 2026 the shipped build INCLUDES QtMultimedia (video and audio play
# inside Prism); the fallback stays for a machine whose audio stack cannot
# load. These two tests construct PreviewDialog
# DIRECTLY, so they bypass the very guard that makes it safe, and failed on
# CI for a thing the product copes with.
try:
    from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401
    _HAVE_MULTIMEDIA, _WHY_NOT = True, ""
except Exception as _e:                             # noqa: BLE001
    _HAVE_MULTIMEDIA, _WHY_NOT = False, (
        f"Qt multimedia will not load here ({_e}) — open_preview() falls "
        "back rather than crashing")


class EveryViewerActuallyConstructs(unittest.TestCase):
    """Every kind PreviewDialog claims to handle must build without raising —
    a header-icon KeyError here previously crashed the whole process (a Qt
    paint-device abort), not just raised a catchable Python exception."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def _file(self, name: str, data: bytes) -> str:
        path = os.path.join(self._tmp.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_image(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.png", b"not a real png")
        dlg = PreviewDialog(path, "image")
        dlg.reject()

    @unittest.skipUnless(_HAVE_MULTIMEDIA, _WHY_NOT)
    def test_demo_video_is_a_plain_player_with_only_close(self):
        """The Home "Watch demo video" is a prospect watching a promo: a plain
        title, no raw file name, none of the file-handling buttons. (These
        tests used to pin a header layout with five action buttons that the
        dialog no longer has; seen in the real window, 1 Oct 2026.)"""
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("prism-creator-promo_2026-08-16_05-15-18.mp4",
                          b"constructor regression")
        # Exercise the actual demo layout without opening an audio device.
        with mock.patch.object(PreviewDialog, "_wire_player") as wire:
            dlg = PreviewDialog(path, "video", demo_mode=True)
            try:
                wire.assert_called_once()
                self.assertEqual(dlg.header.title.text(), "Prism demo")
                self.assertEqual(self._footer_labels(dlg), ["Close"])
            finally:
                dlg.reject()

    def test_a_normal_preview_keeps_the_file_name_and_its_buttons(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("header.txt", b"Preview regression")
        for demo_mode in (False, True):
            with self.subTest(demo_mode=demo_mode):
                dlg = PreviewDialog(path, "text", demo_mode=demo_mode)
                try:
                    labels = self._footer_labels(dlg)
                    self.assertEqual(dlg.header.title.text(),
                                     "Prism demo" if demo_mode else "header.txt")
                    self.assertEqual(
                        labels, ["Close"] if demo_mode
                        else ["Open in default app", "Close"])
                    # the real close button closes
                    self._press(dlg, "Close")
                    self.assertEqual(dlg.result(), dlg.DialogCode.Accepted)
                finally:
                    dlg.reject()

    @staticmethod
    def _footer_buttons(dlg):
        from PySide6.QtWidgets import QPushButton
        return [b for b in dlg.footer.findChildren(QPushButton)]

    def _footer_labels(self, dlg):
        return [b.text() for b in self._footer_buttons(dlg)
                if b.isVisibleTo(dlg) or not b.isHidden()]

    def _press(self, dlg, label):
        next(b for b in self._footer_buttons(dlg) if b.text() == label).click()

    def test_text(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.py", b"print('hi')")
        dlg = PreviewDialog(path, "text")
        dlg.reject()

    def test_docx(self):
        from docx import Document
        from dialogs.preview_dialog import PreviewDialog
        path = os.path.join(self._tmp.name, "brief.docx")
        doc = Document()
        doc.add_heading("Product brief", level=1)
        doc.add_paragraph("A readable in-app document preview.")
        doc.save(path)
        dlg = PreviewDialog(path, "document")
        dlg.reject()

    def test_xlsx(self):
        import openpyxl
        from dialogs.preview_dialog import PreviewDialog
        path = os.path.join(self._tmp.name, "brief.xlsx")
        book = openpyxl.Workbook()
        book.active.append(["Part", "Qty"])
        book.active.append(["Bracket", 4])
        book.save(path)
        dlg = PreviewDialog(path, "spreadsheet")
        dlg.reject()

    def test_pptx_text_preview_handles_a_bad_file_without_crashing(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("brief.pptx", b"not a real presentation")
        dlg = PreviewDialog(path, "presentation")
        dlg.reject()

    def test_pdf(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.pdf", b"%PDF-1.4 not a real pdf")
        dlg = PreviewDialog(path, "pdf")
        dlg.reject()

    @unittest.skipUnless(_HAVE_MULTIMEDIA, _WHY_NOT)
    def test_video(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.mp4", b"not a real mp4")
        dlg = PreviewDialog(path, "video")
        dlg.reject()

    @unittest.skipUnless(_HAVE_MULTIMEDIA, _WHY_NOT)
    def test_audio(self):
        from dialogs.preview_dialog import PreviewDialog
        path = self._file("a.mp3", b"not a real mp3")
        dlg = PreviewDialog(path, "audio")
        dlg.reject()

    def test_unsupported_offers_the_default_app_instead_of_crashing(self):
        from dialogs.preview_dialog import UnsupportedPreviewDialog
        path = self._file("a.xyz", b"not a real docx")
        dlg = UnsupportedPreviewDialog(path)
        dlg.reject()

    def test_folder_lists_a_row_per_entry_including_nested_subfolders(self):
        from dialogs.preview_dialog import FolderPreviewDialog
        os.makedirs(os.path.join(self._tmp.name, "sub"))
        self._file("keep.png", b"x")
        with open(os.path.join(self._tmp.name, "sub", "nested.txt"), "w") as f:
            f.write("x")
        dlg = FolderPreviewDialog(self._tmp.name)
        # One row per top-level entry (the file, the subfolder) plus the
        # trailing stretch — not zero, and not a crash on the mixed file+
        # dir listing.
        self.assertGreaterEqual(dlg.body.count(), 2)
        dlg.reject()

    def test_a_link_sidecar_does_not_get_its_own_row(self):
        from dialogs.preview_dialog import FolderPreviewDialog
        self._file("a.png", b"x")
        self._file("a.png.link.txt", b"https://chatgpt.com/c/abc")
        dlg = FolderPreviewDialog(self._tmp.name)
        # One row for a.png, not two.
        rows = [dlg.body.itemAt(i).widget() for i in range(dlg.body.count())
               if dlg.body.itemAt(i).widget() is not None]
        names = [getattr(w, "_name", None) for w in rows]
        self.assertEqual(names.count("a.png"), 1)
        dlg.reject()


class OpenPreviewDispatch(unittest.TestCase):
    """open_preview() picks the dialog and shows it — exec() is mocked so the
    test doesn't block on a real modal event loop."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_folder_opens_the_folder_dialog(self):
        from dialogs import preview_dialog as PD
        with mock.patch.object(PD.FolderPreviewDialog, "exec",
                               return_value=0) as m:
            PD.open_preview(self._tmp.name)
            m.assert_called_once()

    # Images, documents, spreadsheets, PDFs and unknown types now open in the
    # shared FileViewer (dialogs/file_viewer.py); PreviewDialog keeps only
    # video/audio (needs QtMultimedia) and the Home demo. See test_file_viewer.
    def _opens_in_the_file_viewer(self, name: str):
        from dialogs import preview_dialog as PD
        from dialogs import file_viewer as FV
        path = os.path.join(self._tmp.name, name)
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(FV.FileViewer, "exec", return_value=0) as m, \
                mock.patch.object(FV, "_ReadWorker"):
            PD.open_preview(path)
            m.assert_called_once()

    def test_a_renderable_file_opens_the_file_viewer(self):
        self._opens_in_the_file_viewer("a.png")

    def test_an_unknown_file_opens_the_file_viewer_card_not_the_os(self):
        self._opens_in_the_file_viewer("a.xyz")

    def test_a_docx_uses_the_in_app_viewer(self):
        self._opens_in_the_file_viewer("a.docx")

    def test_a_pdf_uses_the_in_app_viewer(self):
        self._opens_in_the_file_viewer("a.pdf")

    def test_a_video_still_uses_the_player_when_multimedia_exists(self):
        from dialogs import preview_dialog as PD
        path = os.path.join(self._tmp.name, "a.mp4")
        with open(path, "wb") as f:
            f.write(b"x")
        with mock.patch.object(PD, "PreviewDialog") as player:
            PD.open_preview(path)
        player.return_value.exec.assert_called_once()


class AViewerThatCannotLoadFallsBackInsteadOfCrashing(unittest.TestCase):
    """A machine whose audio stack cannot load: video/audio may not construct.

    Never covered: the class above builds PreviewDialog directly, which is
    the one path that has no guard. So the guard that every shipped build
    depends on was the untested one.
    """

    def test_an_importerror_becomes_the_file_viewer_card(self):
        import dialogs.preview_dialog as PD
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "a.mp4")
        with open(path, "wb") as f:
            f.write(b"not a real mp4")
        shown = []
        with mock.patch.object(PD, "PreviewDialog",
                               side_effect=ImportError("no libpulse")), \
             mock.patch("dialogs.file_viewer.FileViewer") as fallback, \
             mock.patch("dialogs.file_viewer._ReadWorker"):
            fallback.return_value.exec.side_effect = lambda: shown.append(path)
            PD.open_preview(path)
        self.assertEqual(shown, [path])


class TheBuildShipsThePlayer(unittest.TestCase):
    """Owner, 19 Nov 2026: video and audio open inside Prism. The player
    only exists in a build that keeps QtMultimedia, which prism.spec used to
    exclude "to halve the download". main.py's selftest proves it loads in
    the frozen app; this stops the exclusion coming back unnoticed."""

    def test_prism_spec_keeps_qtmultimedia(self):
        spec = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "packaging", "prism.spec"), encoding="utf-8").read()
        excludes = spec[spec.index("excludes = ["):]
        excludes = excludes[:excludes.index("]")]
        code = "\n".join(l.split("#", 1)[0] for l in excludes.splitlines())
        self.assertNotIn("QtMultimedia", code)
        self.assertIn('"PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets"', spec)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TheXlsxPreviewReleasesItsFile(unittest.TestCase):
    """A read-only openpyxl workbook holds its file open until closed. On
    Windows that locks the .xlsx (Excel cannot save it, Prism cannot overwrite
    or delete it) for as long as the preview is up — CI caught it as a
    PermissionError [WinError 32] when the test's temp folder was cleaned up."""

    def test_the_workbook_is_closed_after_the_preview_is_built(self):
        from unittest import mock
        import openpyxl
        import tempfile
        from dialogs.preview_dialog import PreviewDialog
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "sheet.xlsx")
        wb = openpyxl.Workbook()
        wb.active.append(["a", 1])
        wb.save(path)
        closed = []
        real = openpyxl.load_workbook

        def spy(*a, **k):
            book = real(*a, **k)
            original = book.close
            book.close = lambda: (closed.append(1), original())[1]
            return book

        with mock.patch("openpyxl.load_workbook", spy):
            dlg = PreviewDialog(path, "spreadsheet")
            dlg.reject()
        self.assertEqual(closed, [1])
        os.remove(path)          # would raise PermissionError on Windows if still open
