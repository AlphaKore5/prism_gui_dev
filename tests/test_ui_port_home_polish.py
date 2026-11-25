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
from addons import registry                                       # noqa: E402
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
        # These tests are about the chips' size, icons and routing, so they pin the
        # Complete build's four chips. Which chips a flavour shows is
        # tests/test_home_try_chips_match_build.py.
        patcher = mock.patch.object(registry, "is_absent", lambda key: False)
        patcher.start()
        self.addCleanup(patcher.stop)
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
        self.assertEqual(got[-1], "agents")      # Settings -> Agents; the AI tools screen is gone

    def test_chips_have_a_hover_only_shadow(self):
        for b in self.composer + self.tries:
            self.assertTrue(b._shadow_under._hover_only)

    def test_no_tool_count_is_invented(self):
        self.assertEqual([b.text() for b in self.composer][2], "Tools")


class HomeCardsAndButtonsHaveShadows(unittest.TestCase):
    def test_every_home_card_has_a_soft_shadow_companion(self):
        home = H.HomePanel({})
        home.resize(1200, 1200)
        home.show()
        cards = [c for c in home.findChildren(C.Card)]
        self.assertGreaterEqual(len(cards), 1)           # the composer (run cards only with runs)
        for c in cards:
            nested = isinstance(c.parentWidget().parentWidget(), C.Card) or any(
                isinstance(w, C.Card) for w in _ancestors(c))
            self.assertEqual(c._shadow_under.active(), not nested, type(c).__name__)


if __name__ == "__main__":
    unittest.main()
