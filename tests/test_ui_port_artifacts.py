"""UI port, stage 3 (Artifacts), on the real ArtifactsPanel rendered offscreen
over a temporary artifacts folder (never the real one)."""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import core_bridge as CB                                            # noqa: E402

from PySide6.QtWidgets import QApplication, QPushButton             # noqa: E402

_app = QApplication.instance() or QApplication([])
import theme                                                        # noqa: E402
theme.load_fonts()
_app.setStyleSheet(open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
                   .replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from widgets import controls as C                                   # noqa: E402
from widgets.artifacts_panel import ArtifactsPanel, _THUMB          # noqa: E402


def _png(path):
    raw = b"".join(b"\x00" + b"\xc8\x5a\x3c" * 16 for _ in range(16))
    def ch(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    open(path, "wb").write(b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", 16, 16, 8, 2, 0, 0, 0))
                           + ch(b"IDAT", zlib.compress(raw)) + ch(b"IEND", b""))


class ArtifactsRestyle(unittest.TestCase):
    def setUp(self):
        self._real = CB.config.ARTIFACTS_DIR
        self._tmp = tempfile.TemporaryDirectory()
        CB.config.ARTIFACTS_DIR = self._tmp.name
        now = time.time()
        for i, n in enumerate(("a.xlsx", "b.pdf", "c.png")):
            p = os.path.join(self._tmp.name, n)
            _png(p) if n.endswith(".png") else open(p, "wb").write(b"x" * 2048)
            os.utime(p, (now - i * 60, now - i * 60))
        self.panel = ArtifactsPanel()
        self.panel.build()
        self.panel.resize(900, 700)
        self.panel.show()
        _app.processEvents()

    def tearDown(self):
        self.panel.close()
        CB.config.ARTIFACTS_DIR = self._real
        self._tmp.cleanup()

    def rows(self):
        return self.panel.findChildren(C.FileItem)

    def test_rows_are_flat_bands_in_one_card(self):
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r.objectName() == "rowFlat" for r in rows))
        self.assertEqual(len(self.panel.findChildren(C.Card)), 1)
        self.assertEqual(rows[0].height(), rows[1].height())
        self.assertGreaterEqual(rows[0].height(), C.MIN_TARGET + 22)

    def test_day_count_is_mono_caps(self):
        head = self.panel.findChildren(C.SectionHeader)[0]
        self.assertEqual(head.subtitle.text(), "3 FILES")
        self.assertTrue(head.subtitle.property("mono"))

    def test_name_and_meta_type(self):
        r = self.rows()[0]
        self.assertIn("font-weight: 400", r.name.styleSheet())
        self.assertIn("font-size: 14px", r.name.styleSheet())
        self.assertIn("font-size: 12px", r.detail.styleSheet())
        self.assertIn(theme.MUTE, r.detail.styleSheet())

    def test_tile_is_38_stone_square_and_thumbnail_matches(self):
        for r in self.rows():
            tile = r.layout().itemAt(0).widget()
            self.assertEqual((tile.width(), tile.height()), (38, 38))
        self.assertEqual(_THUMB, 38)
        plain = [r for r in self.rows() if "png" not in r._name][0]
        self.assertIn("#EFEEEA", plain.layout().itemAt(0).widget().styleSheet())

    def test_open_is_a_labelled_pill_that_still_opens(self):
        r = [x for x in self.rows() if x._name == "b.pdf"][0]
        btn = [b for b in r.findChildren(QPushButton) if b.text() == "Open"][0]
        self.assertTrue(btn.property("pill"))
        self.assertEqual(btn.toolTip(), "Open")
        opened = []
        import dialogs.preview_dialog as PD
        orig, PD.open_preview = PD.open_preview, lambda p, parent=None: opened.append(p)
        try:
            btn.click()
        finally:
            PD.open_preview = orig
        self.assertEqual(opened, [os.path.join(self._tmp.name, "b.pdf")])

    def test_header_button_gets_the_pill_style_and_open_folder_kept(self):
        self.assertEqual([b.text() for b in self.panel.header_actions()], ["Open the folder"])

    def test_empty_state_when_folder_is_empty(self):
        empty = tempfile.TemporaryDirectory()
        CB.config.ARTIFACTS_DIR = empty.name
        p = ArtifactsPanel(); p.build()
        self.assertEqual(len(p.findChildren(C.FileItem)), 0)
        self.assertEqual(len(p.findChildren(C.EmptyState)), 1)
        empty.cleanup()

    def test_flat_option_leaves_boxed_rows_alone(self):
        self.assertEqual(C.FileItem("x", "y").objectName(), "listRow")


if __name__ == "__main__":
    unittest.main()
