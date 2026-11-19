"""The OS launcher (paths.open_in_other_app, behind the viewer's "Open in
another app" button) must work on Mac and Windows, not only Linux; STEP's
picture clicks now show the picture in Prism's viewer (see test_file_viewer).

Original report: STEP's pictures must open from a click on Mac and Windows.

Reported 2026-10-17: clicking a picture in STEP's Files tab did nothing on a
Mac or a Windows machine. The cause was routing every open through Qt's
QDesktopServices; the fix is each platform's own opener (`open`,
os.startfile, xdg-open), which is also what Reel's Play uses."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import paths  # noqa: E402
from addons.step import workbench as WB  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _png() -> str:
    d = tempfile.mkdtemp(prefix="prism-open-")
    p = os.path.join(d, "block - drawing sheet.png")
    img = QImage(40, 30, QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    img.save(p)
    return p


def _click(widget):
    e = QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    widget.mousePressEvent(e)


class EachPlatformUsesItsOwnOpener(unittest.TestCase):
    def setUp(self):
        self.path = _png()

    def test_a_mac_uses_open(self):
        with mock.patch.object(paths.sys, "platform", "darwin"), \
                mock.patch("subprocess.Popen") as popen:
            self.assertTrue(paths.open_in_other_app(self.path))
        self.assertEqual(popen.call_args[0][0], ["open", os.path.normpath(self.path)])

    def test_windows_uses_startfile(self):
        with mock.patch.object(paths.sys, "platform", "win32"), \
                mock.patch.object(paths.os, "name", "nt"), \
                mock.patch.object(paths.os, "startfile", create=True) as start:
            self.assertTrue(paths.open_in_other_app(self.path))
        start.assert_called_once_with(os.path.normpath(self.path))

    def test_linux_uses_xdg_open_without_the_editors_library_path(self):
        with mock.patch.object(paths.sys, "platform", "linux"), \
                mock.patch.object(paths.os, "name", "posix"), \
                mock.patch.dict(os.environ, {"LD_LIBRARY_PATH": "/snap/x"}), \
                mock.patch("subprocess.Popen") as popen:
            self.assertTrue(paths.open_in_other_app(self.path))
        self.assertEqual(popen.call_args[0][0][0], "xdg-open")
        self.assertNotIn("LD_LIBRARY_PATH", popen.call_args[1]["env"])

    def test_a_missing_file_opens_nothing(self):
        with mock.patch("subprocess.Popen") as popen:
            self.assertFalse(paths.open_in_other_app("/nowhere/none.png"))
        popen.assert_not_called()

    def test_if_the_opener_fails_qt_is_the_last_resort(self):
        # Only subprocess.Popen was mocked here before -- on macOS/Linux CI
        # that IS the real opener, so the failure and the Qt fallback both
        # fired. On Windows the real opener is os.startfile, never touched
        # by this mock, so it quietly succeeded for real against the temp
        # PNG and the Qt fallback was never reached (0 calls) -- failing
        # only on the one platform this test didn't force a failure on.
        # os.startfile only exists on Windows, hence create=True.
        with mock.patch("subprocess.Popen", side_effect=OSError), \
                mock.patch.object(paths.os, "startfile", side_effect=OSError,
                                  create=True), \
                mock.patch("PySide6.QtGui.QDesktopServices.openUrl",
                           return_value=True) as qt:
            self.assertTrue(paths.open_in_other_app(self.path))
        qt.assert_called_once()


class ClickingAPictureOpensIt(unittest.TestCase):
    def test_a_files_row_opens_on_a_click_and_shows_the_picture(self):
        path = _png()
        row = WB.FilesPanel._row(path, "drawing")
        from PySide6.QtWidgets import QLabel
        thumbs = [l for l in row.findChildren(QLabel) if l.pixmap() and not l.pixmap().isNull()]
        self.assertTrue(thumbs, "a picture row shows the picture")
        with mock.patch.object(WB.paths, "open_file") as opened:
            _click(row)
        opened.assert_called_once_with(path)

    def test_the_open_and_show_links_use_the_same_opener(self):
        path = _png()
        row = WB.FilesPanel._row(path, "")
        with mock.patch.object(WB.paths, "open_file") as opened:
            links = row.findChildren(WB.Link)
            links[0].clicked.emit()
            links[1].clicked.emit()
        self.assertEqual([c[0][0] for c in opened.call_args_list],
                         [path, os.path.dirname(path)])

    def test_the_picture_in_a_chat_card_opens_on_a_real_click(self):
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel
        from addons.step import sessions as SES
        path = _png()
        turn = SES.live_turn("draft", "block.step", "")
        turn["sheet"] = path
        card = WB._Turn(turn, 1)
        card.resize(400, 400)
        card.show()
        card.set_open(True)
        thumbs = [l for l in card.findChildren(QLabel)
                  if l.pixmap() and not l.pixmap().isNull()]
        self.assertEqual(len(thumbs), 1)
        with mock.patch.object(WB.paths, "open_file") as opened:
            QTest.mouseClick(thumbs[0], Qt.LeftButton)   # through Qt, not a direct call
        opened.assert_called_once_with(path)

    def test_a_files_row_and_the_sheet_open_through_a_real_click_too(self):
        from PySide6.QtTest import QTest
        path = _png()
        row = WB.FilesPanel._row(path, "")
        row.resize(400, 70)
        row.show()
        sheet = WB._Sheet()
        sheet.set_image(path)
        sheet.resize(300, 200)
        sheet.show()
        with mock.patch.object(WB.paths, "open_file") as opened:
            QTest.mouseClick(row, Qt.LeftButton)
            QTest.mouseClick(sheet, Qt.LeftButton)
        self.assertEqual([c[0][0] for c in opened.call_args_list], [path, path])

    def test_the_drawing_sheet_opens_on_a_click(self):
        path = _png()
        sheet = WB._Sheet()
        self.assertTrue(sheet.set_image(path))
        with mock.patch.object(WB.paths, "open_file") as opened:
            _click(sheet)
        opened.assert_called_once_with(path)


if __name__ == "__main__":
    unittest.main()
