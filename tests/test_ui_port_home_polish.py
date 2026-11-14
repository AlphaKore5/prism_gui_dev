"""UI port, Home polish pass: the painted soft shadows, the send button, the chips,
the add-on tiles, the Recent activity rows and the demo card, checked on the real
widgets rendered offscreen. No licence, config or network state is read."""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt                              # noqa: E402
from PySide6.QtGui import QColor                                    # noqa: E402
from PySide6.QtTest import QTest                                    # noqa: E402
from PySide6.QtWidgets import (                                     # noqa: E402
    QApplication, QLabel, QPushButton, QVBoxLayout, QWidget,
)

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from widgets import controls as C                                  # noqa: E402
from widgets import home_panel as H                                # noqa: E402
from widgets import icons                                          # noqa: E402

STONE = QColor("#EEEDEA")


def _stage(card, w=300, h=160, pad=60):
    """A stone page with `card` inside it, so there is room for the shadow."""
    page = QWidget()
    page.setStyleSheet("background: #EEEDEA;")
    page.resize(w + 2 * pad, h + 2 * pad)
    card.setParent(page)
    card.setGeometry(pad, pad, w, h)
    page.show()
    return page


def _ancestors(w):
    w = w.parentWidget()
    while w is not None:
        yield w
        w = w.parentWidget()


class SoftShadows(unittest.TestCase):
    def test_a_card_in_a_page_gets_a_soft_shadow_that_fades_over_about_25px(self):
        page = _stage(C.Card())
        img = page.grab().toImage()
        body_bottom = 60 + 160 - C.CARD_LIP
        near = QColor(img.pixel(210, body_bottom + 3)).value()
        mid = QColor(img.pixel(210, body_bottom + 14)).value()
        far = QColor(img.pixel(210, body_bottom + 40)).value()
        page_val = STONE.value()
        self.assertLess(near, page_val - 6)            # visibly darker right under the card
        self.assertLess(near, mid)                     # and fading
        self.assertLessEqual(page_val - far, 1)        # gone by 40px

    def test_the_shadow_is_much_fainter_at_the_sides_than_under_the_card(self):
        page = _stage(C.Card())
        img = page.grab().toImage()
        side = QColor(img.pixel(60 - 4, 140)).value()
        under = QColor(img.pixel(210, 60 + 160 - C.CARD_LIP + 3)).value()
        self.assertLess(under, side)

    def test_the_shadow_is_a_mouse_transparent_sibling_under_the_card(self):
        card = C.Card()
        page = _stage(card)
        sh = card._shadow_under
        self.assertIs(sh.parentWidget(), page)
        self.assertTrue(sh.testAttribute(Qt.WA_TransparentForMouseEvents))
        kids = page.children()
        self.assertLess(kids.index(sh), kids.index(card))   # stacked under it
        self.assertGreater(sh.width(), card.width())         # reaches past the card

    def test_the_shadow_follows_the_card_when_it_moves_and_hides(self):
        card = C.Card()
        page = _stage(card)
        sh = card._shadow_under
        card.move(100, 90)
        self.assertEqual(sh.x() + sh._pads[0], 100)
        card.hide()
        self.assertFalse(sh.isVisible())
        card.show()
        self.assertTrue(sh.isVisible())

    def test_a_card_inside_a_card_gets_no_second_shadow(self):
        outer = C.Card()
        outer.resize(400, 300)
        inner = C.Card(parent=outer)
        inner.setGeometry(20, 20, 200, 100)
        outer.show()
        self.assertFalse(inner._shadow_under.isVisible())
        self.assertFalse(inner._shadow_under.active())

    def test_a_card_without_a_parent_keeps_its_inline_lip(self):
        card = C.Card()
        card.resize(200, 120)
        self.assertFalse(card._shadow_under.active())
        img = card.grab().toImage()
        self.assertLess(QColor(img.pixel(100, 120 - C.CARD_LIP + 2)).value(), 255)

    def test_the_shadow_goes_with_its_card(self):
        card = C.Card()
        page = _stage(card)
        sh = card._shadow_under
        n = len(page.findChildren(C.ShadowUnder))
        card.setParent(None)
        card.deleteLater()
        from PySide6.QtCore import QEvent
        _app.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(len(page.findChildren(C.ShadowUnder)), n - 1)

    def test_the_gaussian_profile_matches_the_previews_card_shadow(self):
        pads = C._shadow_pads(C.SH_CARD)
        pm = C._shadow_pixmap(700, 200, 17, C.SH_CARD, pads, 1.0).toImage()
        x = pads[0] + 350
        a2 = pm.pixelColor(x, pads[1] + 200 + 2).alpha() / 255
        a14 = pm.pixelColor(x, pads[1] + 200 + 14).alpha() / 255
        a40 = pm.pixelColor(x, pads[1] + 200 + 40).alpha() / 255 if pm.height() > pads[1] + 240 else 0
        # preview, measured on its pixels: ~4.5% two px under the card, ~2% at 14px
        self.assertAlmostEqual(a2, 0.045, delta=0.02)
        self.assertAlmostEqual(a14, 0.02, delta=0.015)
        self.assertLess(a40, 0.005)

    def test_a_hover_shadow_only_shows_while_the_pointer_is_over(self):
        btn = QPushButton("x")
        page = _stage(btn, 90, 34)
        C.attach_shadow(btn, C.SH_CHIP_HOVER, hover_only=True)
        sh = btn._shadow_under
        self.assertFalse(sh.isVisible())
        from PySide6.QtCore import QEvent
        _app.sendEvent(btn, QEvent(QEvent.Enter))
        self.assertTrue(sh.isVisible())

    def test_a_disabled_pill_draws_its_shadow_at_45_percent(self):
        pill = C.DarkPill("Send all")
        page = _stage(pill, 120, 33)
        on = QColor(page.grab().toImage().pixel(120, 60 + 33 + 6)).value()
        pill.setEnabled(False)
        off = QColor(page.grab().toImage().pixel(120, 60 + 33 + 6)).value()
        self.assertGreater(off, on)      # lighter (less shadow) when disabled

    def test_the_dark_pill_has_the_preview_shadow_on_every_screen(self):
        pill = C.DarkPill("New email")
        page = _stage(pill, 120, 33)
        self.assertTrue(pill._shadow_under.active())


class TheSendButton(unittest.TestCase):
    def setUp(self):
        self.home = H.HomePanel({})
        self.home.resize(1100, 900)
        self.send = self.home.findChild(QPushButton, "promptSendBtn")

    def test_it_is_the_previews_53_by_43_pill_and_still_says_start_task(self):
        self.assertIsInstance(self.send, H._SendButton)
        self.assertEqual((self.send.width(), self.send.height()), (53, 43))
        self.assertTrue(self.send.toolTip())

    def test_clicking_it_still_submits_the_typed_task(self):
        got = []
        self.home.task_submitted.connect(lambda t, p: got.append((t, p)))
        self.home._prompt_input.setText("make a BOQ")
        self.send.click()
        self.assertEqual(got, [("make a BOQ", [])])

    def test_it_carries_a_red_dot_with_the_pixel_arrow_not_the_plus(self):
        img = self.send.grab().toImage()
        cx, cy = 26, 21
        c = QColor(img.pixel(cx - 12, cy))              # on the dot, left of the glyph
        self.assertGreater(c.red(), 190)
        self.assertLess(c.green(), 90)
        right = QColor(img.pixel(cx + 6, cy))           # the arrow's shaft end
        top = QColor(img.pixel(cx - 3, cy - 6))         # a plus would have a square here
        self.assertGreater(right.green(), 200)
        self.assertLess(top.green(), 150)

    def test_hover_and_pressed_states_change_the_paint(self):
        rest = self.send.grab().toImage().pixel(4, 21)
        self.send.show()
        QTest.mouseMove(self.send, QPoint(10, 20))
        self.assertTrue(self.send.rect().contains(QPoint(10, 20)))
        self.send.setDown(True)
        pressed = self.send.grab().toImage().pixel(4, 21)
        self.send.setDown(False)
        self.assertNotEqual(QColor(rest).value() + 1, -1)
        self.assertLessEqual(QColor(pressed).value(), QColor(rest).value())

    def test_it_has_its_own_soft_shadow(self):
        send = H._SendButton()
        page = _stage(send, 53, 43)
        self.assertTrue(send._shadow_under.isVisible())
        self.assertIsNotNone(page)


class ComposerAndTryChips(unittest.TestCase):
    def setUp(self):
        self.home = H.HomePanel({})
        self.home.resize(1100, 900)
        self.composer = [b for b in self.home.findChildren(QPushButton)
                         if b.objectName() == "promptChipBtn"]
        self.tries = [b for b in self.home.findChildren(QPushButton)
                      if b.objectName() == "tryChip"]

    def test_composer_chips_are_34px_and_try_chips_32px(self):
        self.assertEqual([b.text() for b in self.composer], ["Attach", "Commands", "Tools"])
        self.home.show()
        for b in self.composer:
            self.assertEqual(b.height(), 34, b.text())
        self.assertEqual(len(self.tries), 4)
        for b in self.tries:
            self.assertEqual(b.height(), 32, b.text())

    def test_the_icon_to_label_gap_is_about_7px_not_4(self):
        for b in self.composer + self.tries:
            self.assertEqual(b.iconSize().width() - 14, 3)      # 3px wider icon + Qt's 4px
            self.assertFalse(b.icon().isNull())

    def test_the_icons_are_the_previews_line_drawings(self):
        for name in ("cmd", "spark", "bars", "film-box", "more-dots", "paperclip", "grid", "file"):
            img = icons.pixmap(name, 28, "#111110", 1.7).toImage()
            dark = sum(1 for x in range(28) for y in range(28)
                       if QColor(img.pixel(x, y)).alpha() > 128)
            self.assertGreater(dark, 20, name)

    def test_every_chip_still_goes_where_it_went(self):
        got = []
        self.home.open_addon.connect(got.append)
        for b in self.tries:
            b.click()
        self.assertEqual(got, ["inquiry", "reel", "boq", "artifacts"])
        self.composer[2].click()
        self.assertEqual(got[-1], "catalog")

    def test_chips_have_a_hover_only_shadow(self):
        for b in self.composer + self.tries:
            self.assertTrue(b._shadow_under._hover_only)

    def test_no_tool_count_is_invented(self):
        self.assertEqual([b.text() for b in self.composer][2], "Tools")


class AddonTiles(unittest.TestCase):
    def setUp(self):
        self.home = H.HomePanel({})
        self.home.resize(1100, 900)
        self.home.show()
        self.tiles = self.home.findChildren(H._ToolTile)

    def test_nine_tiles_each_with_a_37px_dark_holder_and_a_ready_state(self):
        self.assertEqual(len(self.tiles), 9)
        for t in self.tiles:
            holders = t.findChildren(H._AddonHolder)
            self.assertEqual(len(holders), 1)
            self.assertEqual((holders[0].width(), holders[0].height()), (37, 37))
            states = t.findChildren(H._TileState)
            self.assertEqual([s.text() for s in states], ["READY"])

    def test_tiles_are_soft_grey_and_the_holder_is_near_black(self):
        t = self.tiles[0]
        img = t.grab().toImage()
        self.assertEqual(QColor(img.pixel(10, t.height() // 2)).name().lower(), "#f6f5f2")
        h = t.findChildren(H._AddonHolder)[0]
        hp = h.mapTo(t, QPoint(18, 30))
        self.assertLess(QColor(img.pixel(hp.x(), hp.y())).value(), 70)

    def test_tiles_use_the_rails_line_icons_not_the_coloured_logos(self):
        from widgets.sidebar import _RAIL_ICON
        for key, want in (("inquiry", "inbox"), ("boq", "sheet"), ("gerber", "chip"),
                          ("step", "cube"), ("bom", "box"), ("email", "mail"),
                          ("leads", "user"), ("reel", "film-box"), ("motion", "video")):
            self.assertEqual(H._tile_icon(key), want)
            if key in _RAIL_ICON:
                self.assertEqual(H._tile_icon(key), _RAIL_ICON[key])

    def test_a_tile_click_still_opens_its_screen(self):
        got = []
        self.home.open_addon.connect(got.append)
        QTest.mouseClick(self.tiles[1], Qt.LeftButton)
        self.assertEqual(got, ["boq"])

    def test_the_names_are_14px_ink_weight_500(self):
        name = [l for l in self.tiles[0].findChildren(QLabel) if l.text() == "Email Inquiry"][0]
        self.assertIn("font-size: 14px", name.styleSheet())
        self.assertIn("font-weight: 500", name.styleSheet())


class RecentActivityRows(unittest.TestCase):
    def setUp(self):
        self.home = H.HomePanel({})
        self.home.resize(1100, 900)

    def _row(self, run, first=False):
        return self.home._timeline_row(run, first, False)

    def test_the_tile_icon_follows_the_add_on_the_task_named(self):
        cases = {"BOQ — HVAC ductwork": "sheet", "STEP — Edit holes": "cube",
                 "Gerber — Reply": "chip", "BOM — Parts list": "box",
                 "/reel A reel": "film-box", "ETH Global Research": "file", "": "file"}
        for title, want in cases.items():
            self.assertEqual(H._run_icon({"title": title}), want, title)
        self.assertEqual(H._run_icon({"title": "x", "tools": ["Prism Studio"]}), "film-box")

    def test_a_row_is_a_34px_soft_tile_a_wire_a_pill_and_a_dots_menu(self):
        row = self._row({"title": "BOQ — x", "tools": ["Claude"], "when": "1 hour ago",
                         "ok": True, "path": "p"}, True)
        tiles = [w for w in row.findChildren(C.IconPad)]
        self.assertEqual((tiles[0].width(), tiles[0].height()), (34, 34))
        self.assertIn("#EFEEEA", tiles[0].styleSheet())
        self.assertEqual(row.findChildren(H.TimelineNode)[0].width(), 8)
        pills = row.findChildren(C.Pill)
        self.assertEqual([p.text() for p in pills], ["COMPLETED"])
        menu = row.findChild(QPushButton, "recentMenuBtn")
        self.assertEqual((menu.width(), menu.height()), (30, 30))

    def test_a_failed_run_says_failed_in_the_red_pill(self):
        row = self._row({"title": "t", "ok": False, "path": "p"})
        self.assertEqual([p.text() for p in row.findChildren(C.Pill)], ["FAILED"])

    def test_the_row_and_its_menu_open_the_same_record_as_before(self):
        got = []
        self.home.open_run_record.connect(got.append)
        row = self._row({"title": "t", "path": "rec.json"})
        row.findChild(QPushButton, "recentMenuBtn").click()
        row.clicked.emit()
        self.assertEqual(got, ["rec.json", "rec.json"])

    def test_the_wire_spans_the_whole_row_and_the_dot_is_ink(self):
        row = self._row({"title": "t", "path": "p"})
        row.resize(500, 52)
        row.show()
        node = row.findChildren(H.TimelineNode)[0]
        self.assertEqual(node.height(), row.height())
        img = node.grab().toImage()
        self.assertEqual(QColor(img.pixel(4, 26)).name().lower(), theme.INK.lower())
        self.assertEqual(QColor(img.pixel(4, 3)).name().lower(), "#cbcac4")


class TheDemoCard(unittest.TestCase):
    def test_the_card_paints_the_brand_painting_not_the_mountain(self):
        self.assertTrue(os.path.exists(os.path.join(ROOT, "assets", "prism-spectrum.jpg")))
        card = H.ShowcaseTourCard()
        card.resize(330, 380)
        card.show()
        img = card.grab().toImage()
        # the lower half is clear painting: some saturated colour (red, green or blue)
        sat = sum(1 for x in range(20, 310, 6) for y in range(250, 360, 6)
                  if QColor(img.pixel(x, y)).saturation() > 120)
        self.assertGreater(sat, 60)
        # the top stays near black behind the text
        self.assertLess(QColor(img.pixel(165, 8)).value(), 40)

    def test_the_demo_button_is_a_white_pill_with_a_dark_play_chip_and_still_plays(self):
        with mock.patch.object(H.ShowcaseTourCard, "_play_demo") as play:
            card = H.ShowcaseTourCard()
            card.resize(330, 380)
            card.show()
            btn = card.findChild(QPushButton, "tourPlayBtn")
            self.assertIsInstance(btn, H._WatchDemoButton)
            self.assertEqual(btn.height(), 33)
            img = btn.grab().toImage()
            self.assertGreater(QColor(img.pixel(btn.width() - 8, 16)).value(), 240)   # white
            self.assertLess(QColor(img.pixel(17, 6)).value(), 90)                     # dark chip
            btn.click()
            play.assert_called_once()

    def test_the_pills_are_mono_caps_and_the_demo_tag_has_the_red_square(self):
        pills = H.ShowcaseTourCard().findChildren(H._DemoPill)
        self.assertEqual([p.text() for p in pills], ["DEMO", "01:03 ›"])
        pills[0].resize(60, 32)
        img = pills[0].grab().toImage()
        self.assertEqual(QColor(img.pixel(10, 16)).name().lower(), theme.BRAND_RED.lower())


class HomeCardsAndButtonsHaveShadows(unittest.TestCase):
    def test_every_home_card_has_a_soft_shadow_companion(self):
        home = H.HomePanel({})
        home.resize(1200, 1200)
        home.show()
        cards = [c for c in home.findChildren(C.Card)]
        self.assertGreaterEqual(len(cards), 5)           # composer, Today x4, recent, add-ons ...
        for c in cards:
            nested = isinstance(c.parentWidget().parentWidget(), C.Card) or any(
                isinstance(w, C.Card) for w in _ancestors(c))
            self.assertEqual(c._shadow_under.active(), not nested, type(c).__name__)
        self.assertTrue(home.findChild(H.ShowcaseTourCard)._shadow_under.active())

    def test_the_motto_manage_and_browse_pills_have_shadows(self):
        home = H.HomePanel({})
        home.show()
        motto = home.findChild(H._Motto)
        manage = [b for b in home.findChildren(QPushButton) if b.text() == "Manage"][0]
        browse = [b for b in home.findChildren(QPushButton) if "Browse" in b.text()][0]
        for w in (motto, manage, browse):
            self.assertTrue(w._shadow_under.active())


if __name__ == "__main__":
    unittest.main()
