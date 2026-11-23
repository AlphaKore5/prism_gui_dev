"""UI port, stage 4b (the shared chrome), checked on the real widgets rendered
offscreen under the real stylesheet: the rail, the user chip, the status bar,
the page-header buttons and the preview's line icons."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                      # noqa: E402
from PySide6.QtGui import QColor                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow    # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

import flavour                                                     # noqa: E402
from widgets import controls as C                                  # noqa: E402
from widgets import icons                                          # noqa: E402
from widgets.sidebar import Sidebar, AddonRow, NavButton, row_height   # noqa: E402


def _rail():
    rail = Sidebar()
    rail.resize(258, 718)
    rail.show()
    return rail


def _px(img, x, y):
    return QColor(img.pixel(x, y))


class TheUserChip(unittest.TestCase):
    def test_exactly_one_avatar_even_after_the_name_changes(self):
        rail = _rail()
        for name in ("", "Parth", "Het", "Asha"):
            rail.set_profile(name)
        avatars = rail.findChildren(C.Avatar)
        self.assertEqual(len(avatars), 1)
        self.assertEqual(avatars[0].text(), "A")
        self.assertEqual((avatars[0].width(), avatars[0].height()), (31, 31))

    def test_avatar_is_the_ink_circle_with_a_white_initial(self):
        rail = _rail()
        rail.set_profile("Parth")
        av = rail.findChild(C.Avatar)
        self.assertIn("#111110", av.styleSheet())
        self.assertIn("border-radius: 15px", av.styleSheet())

    def test_one_divider_above_the_chip_and_the_plan_line_is_mono(self):
        rail = _rail()
        foot_rules = [w for w in rail._foot_col.parentWidget().findChildren(QLabel)
                      if w.objectName() == "railRule"]
        self.assertEqual(foot_rules, [])
        self.assertIn(theme.FONT_MONO, rail._profile_sub.styleSheet())
        self.assertIn("font-size: 11px", rail._profile_sub.styleSheet())

    def test_plan_line_keeps_the_warning_colour_when_the_licence_is_off(self):
        rail = _rail()
        rail.set_plan("Complete", "Ended", ok=False)
        self.assertIn(theme.WARN, rail._profile_sub.styleSheet())


class TheRail(unittest.TestCase):
    def test_width_and_the_brand_block(self):
        rail = _rail()
        self.assertEqual(rail.width(), 258)
        by = rail.findChild(QLabel, "brandBy")
        self.assertEqual(by.text(), "BY ALPHAKORE")
        self.assertFalse(icons.ak_mark_pixmap(14).isNull())
        self.assertEqual(rail.findChild(QLabel, "brand").text(), "Prism")

    def test_rows_follow_the_preview_pitch(self):
        # Tops stay within half a pixel of 157.4 + 39.7 n.
        top = 0
        for n in range(8):
            self.assertLess(abs((top) - round(39.7 * n)), 1)
            top += row_height(0, n) + 2

    def test_nav_rows_and_add_on_tiles_are_laid_out_as_the_preview(self):
        rail = _rail()
        home = rail._nav["home"]
        self.assertIsInstance(home, NavButton)
        self.assertEqual(home.iconSize().width(), 16)
        tops = [rail._nav[k].mapTo(rail, rail._nav[k].rect().topLeft()).y()
                for k in ("home", "runs", "artifacts")]
        self.assertEqual(tops[1] - tops[0], 40)
        # Studio (Reel, Motion) has no add-on rows on the rail, so there is no
        # tile to measure; every other build has at least one.
        rows = rail.findChildren(AddonRow)
        if not rows:
            self.assertEqual(flavour.addon_keys(), ("reel", "motion"))
            return
        row = rows[0]
        self.assertEqual(row._chip.width(), 26)
        self.assertEqual(row._label.styleSheet().count("font-size: 14px"), 1)

    def test_add_on_tiles_use_the_preview_glyph_names(self):
        rail = _rail()
        names = {r._icon_name for r in rail.findChildren(AddonRow)}
        # "box" (BOM & Stock) left the rail on 2026-11-16 with BOM
        # (addons/bom/addon.py status=OFF); it comes back with BOM.
        #
        # Only the add-ons the build contains have a row: Sales has no sheet,
        # chip or cube; Engineering no inbox, mail, user or message; Studio
        # (Reel, Motion) has no rail rows at all.
        glyph = {"inquiry": "inbox", "boq": "sheet", "gerber": "chip",
                 "step": "cube", "email": "mail", "leads": "user",
                 "whatsapp": "message"}
        expected = {g for k, g in glyph.items() if k in flavour.addon_keys()}
        missing = expected - names
        self.assertFalse(missing, "rail is missing %s of %s" % (missing, names))
        # and a glyph for an add-on this build lacks must not appear
        self.assertFalse(names & (set(glyph.values()) - expected), names)

    def test_new_task_is_a_tall_pill_with_the_dot_at_the_left(self):
        rail = _rail()
        btn = rail.new_task_btn
        self.assertEqual(btn.text(), "New task")
        self.assertEqual(btn.height(), 48)
        img = btn.grab().toImage()
        left = _px(img, 12, 21)                 # inside the 32px dot, left of the plus
        self.assertGreater(left.red(), 180)
        self.assertLess(left.green(), 120)
        body = _px(img, 150, 21)                # the dark body, right of the label
        self.assertLess(body.red(), 70)

    def test_new_task_still_emits_workbench(self):
        rail = _rail()
        seen = []
        rail.command_triggered.connect(seen.append)
        rail.new_task_btn.click()
        self.assertEqual(seen, ["workbench"])

    def test_the_rail_fades_from_white_to_warm_white(self):
        rail = _rail()
        img = rail.grab().toImage()
        top, bottom = _px(img, 129, 12), _px(img, 129, 700)
        self.assertGreaterEqual(top.red(), 253)
        self.assertLess(bottom.blue(), top.blue())

    def test_collapse_round_trip_restores_row_heights(self):
        rail = _rail()
        before = rail._nav["runs"].height()
        rail.toggle_collapsed(True)
        rail.toggle_collapsed(False)
        self.assertEqual(rail._nav["runs"].height(), before)
        self.assertEqual(rail.width(), 258)

    def test_section_labels_are_mono_with_the_red_square(self):
        rail = _rail()
        work = rail._work_lbl
        self.assertEqual(work.height(), 14)
        img = work.grab().toImage()
        sq = _px(img, 8 + 3, 7)
        self.assertGreater(sq.red(), 170)
        self.assertLess(sq.green(), 60)


class TheStatusBar(unittest.TestCase):
    def test_green_square_only_before_ready(self):
        win = QMainWindow()
        win.setStatusBar(C.PrismStatusBar())
        win.resize(400, 100)
        win.show()
        win.statusBar().showMessage("Ready.")
        img = win.statusBar().grab().toImage()
        sq = _px(img, 16, 12)
        self.assertGreater(sq.green(), 150)
        self.assertLess(sq.red(), 100)
        self.assertEqual(win.statusBar().height(), 24)
        win.statusBar().showMessage("Checking your licence…")
        img = win.statusBar().grab().toImage()
        self.assertLess(_px(img, 16, 12).green(), 60)
        self.assertEqual(win.statusBar().currentMessage(), "Checking your licence…")


class PageHeaderButtons(unittest.TestCase):
    def test_primary_is_the_dark_pill_and_clicks(self):
        hits = []
        btn = C.button("New task", "primary", icon_name="plus",
                       on_click=lambda: hits.append(1))
        self.assertIsInstance(btn, C.DarkPill)
        self.assertEqual(btn.height(), 33)
        btn.click()
        self.assertEqual(hits, [1])
        btn.setEnabled(False)
        btn.click()
        self.assertEqual(hits, [1])

    def test_light_and_danger_buttons_are_13px_pills_33px_tall(self):
        for variant, colour in (("secondary", "#111110"), ("destructive", "#a3141a")):
            b = C.button("Clear all", variant, icon_name="trash")
            b.show()
            self.assertEqual(b.sizeHint().height(), 33)
            self.assertEqual(b.styleSheet(), "")
        self.assertIn("font-size: 13px", QSS.split("light pill buttons", 1)[1])

    def test_header_is_flush_with_the_page_and_buttons_are_centred_on_the_card(self):
        hdr = C.PageHeader("History", "sub", [C.button("Go", "primary")])
        hdr.resize(1066, 86)
        hdr.show()
        m = hdr.layout().contentsMargins()
        self.assertEqual((m.left(), m.top(), m.right()), (24, 12, 16))
        btn = hdr.actions_row.itemAt(0).widget()
        centre = btn.mapTo(hdr, btn.rect().center()).y()
        self.assertLessEqual(abs(centre - 43), 2)


class PreviewIcons(unittest.TestCase):
    def test_every_new_glyph_draws_ink(self):
        for name in ("home", "clock", "folder", "inbox", "sheet", "chip", "cube",
                     "mail", "user", "message", "box", "grid", "search", "trash",
                     "x", "chevron-left", "chevron-down", "chevron-right",
                     "check", "sliders", "help", "list", "key", "external",
                     "lock", "pencil", "eye", "mic", "video", "paperclip"):
            img = icons.pixmap(name, 32, "#000000").toImage()
            ink = sum(1 for x in range(32) for y in range(32)
                      if QColor(img.pixel(x, y)).alpha() > 128)
            self.assertGreater(ink, 20, name)

    def test_the_magnifier_has_its_handle(self):
        img = icons.pixmap("search", 48, "#000000").toImage()
        # handle runs from (20,20) to (15.8,15.8) in 24 units: lower right
        ink = sum(1 for x in range(36, 46) for y in range(36, 46)
                  if QColor(img.pixel(x, y)).alpha() > 128)
        self.assertGreater(ink, 8)

    def test_strokes_are_1_7(self):
        self.assertEqual(icons.pixmap.__defaults__[-1], 1.7)


if __name__ == "__main__":
    unittest.main()
