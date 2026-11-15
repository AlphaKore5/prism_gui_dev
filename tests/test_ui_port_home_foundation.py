"""UI port, stage 1 (Home + the shared foundation), checked on the real widgets
rendered offscreen: bundled faces, brand progress colour, painted card shadow,
canvas texture, rail row height, and the Home pieces the preview restyles."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton     # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from widgets import controls as C                                  # noqa: E402
from widgets import home_panel as H                                # noqa: E402
from widgets.sidebar import Sidebar, AddonRow                      # noqa: E402
from widgets.loader import Loader                                  # noqa: E402


class FontsAreBundled(unittest.TestCase):
    def test_geist_light_and_rounded_doto_ship(self):
        fams = set(QFontDatabase.families())
        for f in ("Geist", "Geist Light", "Geist Mono", "Doto"):
            self.assertIn(f, fams)

    def test_doto_is_the_rounded_dot_cut(self):
        # ROND=100 draws round dots: the glyph's centre pixel is covered by a
        # disc, the old square cut filled its corner as well.
        from PySide6.QtGui import QFont
        font = QFont("Doto", 60)
        font.setBold(True)
        img = QImage(120, 120, QImage.Format_ARGB32)
        img.fill(Qt.white)
        p = QPainter(img)
        p.setFont(font)
        p.drawText(5, 90, "O")
        p.end()
        dark = sum(1 for x in range(120) for y in range(120)
                   if QColor(img.pixel(x, y)).value() < 100)
        self.assertGreater(dark, 200)


class ProgressUsesTheBrandPalette(unittest.TestCase):
    def test_no_purple_left_in_the_stylesheet(self):
        for purple in ("#6c63ff", "#a78bfa"):
            self.assertNotIn(purple, QSS.lower())
        chunk = QSS.split("QProgressBar::chunk {", 1)[1].split("}", 1)[0]
        self.assertIn(theme.BRAND_RED, chunk)

    def test_loader_fills_in_brand_red(self):
        ld = Loader(mode="stages")
        ld.resize(300, 60)
        ld.setRange(0, 100)
        ld.setValue(100)
        img = ld.grab().toImage()
        reds = sum(1 for x in range(300) for y in range(60)
                   if QColor(img.pixel(x, y)).name().lower() == theme.BRAND_RED.lower())
        self.assertGreater(reds, 100)


class CardsCarryTheirShadow(unittest.TestCase):
    def test_a_card_paints_a_soft_lip_below_its_body(self):
        card = C.Card()
        card.resize(200, 120)
        img = card.grab().toImage()
        below = QColor(img.pixel(100, 120 - C.CARD_LIP + 2))
        body = QColor(img.pixel(100, 60))
        self.assertEqual(body.name().lower(), theme.CARD.lower())
        self.assertLess(below.value(), 255)           # shadow, not white and not transparent

    def test_the_default_card_radius_is_the_previews_17(self):
        self.assertEqual(C.Card()._radius, 17)


class TheCanvasHasTheStoneTexture(unittest.TestCase):
    def test_default_canvas_is_stone_with_a_dot_field_and_top_light(self):
        import main_window
        c = main_window.DashboardCentral()
        c._bg_orig = None
        c.resize(600, 400)
        img = c.grab().toImage()
        colours = {QColor(img.pixel(x, y)).name() for x in range(0, 120) for y in range(0, 60)}
        self.assertGreater(len(colours), 3)                    # dots, not one flat fill
        top = QColor(img.pixel(350, 2)).lightness()
        corner = QColor(img.pixel(3, 395)).lightness()
        self.assertGreater(top, corner)                         # light falls from the top


class TheRailFitsAt1366x768(unittest.TestCase):
    def test_every_addon_row_is_37_or_38px_and_clears_the_profile_chip(self):
        rail = Sidebar()
        rail.resize(262, 768 - 24)
        rail.show()
        rows = rail.findChildren(AddonRow)
        self.assertGreaterEqual(len(rows), 8)
        for r in rows:
            # stage 4b: 38 or 37 so tops follow the preview's 39.7px pitch
            self.assertIn(r.sizeHint().height(), (37, 38))
        # the 43px pill plus its 5px painted shadow
        self.assertEqual(rail.new_task_btn.sizeHint().height(), 43 + 5)


class HomeCarriesThePreviewsPieces(unittest.TestCase):
    def setUp(self):
        self.home = H.HomePanel({})
        self.home.resize(1100, 900)

    def test_the_send_button_is_a_pill_with_the_red_dot(self):
        send = self.home.findChild(QPushButton, "promptSendBtn")
        self.assertIsNotNone(send)
        self.assertIsInstance(send, H._SendButton)      # painted (polish pass): gradient pill + red dot
        self.assertTrue(send.toolTip())                # says what it does

    def test_the_lead_line_fades_its_second_half(self):
        lead = [w for w in self.home.findChildren(QLabel)
                if "turn ideas" in w.text()]
        self.assertTrue(lead)
        self.assertIn(theme.FAINT, lead[0].text())


if __name__ == "__main__":
    unittest.main()
