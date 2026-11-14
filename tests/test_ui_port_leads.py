"""UI port, stage 7 (Leads & Outreach): the real workspace, result rows and credits donut offscreen under the real stylesheet.
Hermetic: temp folders, no licence file, nothing reaches a gateway (a gateway stand-in answers the one call the workspace makes)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton       # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                          # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from addons.leads import cockpit as CK                                # noqa: E402
from addons.leads import credits_page as CP                           # noqa: E402
from addons.leads import result_rows as RR                            # noqa: E402
from prospector import gateway                                        # noqa: E402
from widgets import controls as C                                     # noqa: E402


def _workspace():
    with mock.patch.object(gateway, "pooled", return_value=True):
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
    w.resize(1040, 640)
    w.show()
    _app.processEvents()
    return w


class TheTabStrip(unittest.TestCase):
    def setUp(self):
        self.w = _workspace()

    def test_tabs_are_44px_14px_and_the_active_one_is_ink_underlined(self):
        tab = self.w._tabs[0]
        self.assertGreaterEqual(tab.height(), 43)
        self.assertLessEqual(tab.height(), 45)
        self.assertIn("font-size:14px", tab.styleSheet())
        self.assertTrue(tab._on)
        self.assertFalse(self.w._tabs[1]._on)

    def test_the_underline_is_painted_as_wide_as_the_text_not_the_button(self):
        tab = self.w._tabs[0]
        img = tab.grab().toImage()
        y = img.height() - 1
        ink = [x for x in range(img.width()) if img.pixelColor(x, y).name().lower() == theme.INK.lower()]
        self.assertTrue(ink)
        self.assertEqual((min(ink), max(ink)), (10, tab.width() - 11))
        other = self.w._tabs[1].grab().toImage()
        self.assertFalse([x for x in range(other.width()) if other.pixelColor(x, other.height() - 1).name().lower() == theme.INK.lower()])

    def test_every_tab_still_switches_the_page(self):
        for i, b in enumerate(self.w._tabs):
            b.click()
            self.assertEqual(self.w._stack.currentIndex(), i)

    def test_the_credits_chip_is_mono_stone_and_not_clipped(self):
        chip = [l for l in self.w.findChildren(QLabel) if l.text() == "Your credits · your inbox"]
        self.assertEqual(len(chip), 1)
        self.assertIn("Geist Mono", chip[0].styleSheet())
        self.assertIn("#EFEEEA", chip[0].styleSheet())
        self.assertGreaterEqual(chip[0].width(), chip[0].sizeHint().width())

    def test_the_tabs_fit_the_strip_at_1040(self):
        last = self.w._tabs[-1]
        chip = [l for l in self.w.findChildren(QLabel) if l.text() == "Your credits · your inbox"][0]
        self.assertLessEqual(last.geometry().right(), chip.geometry().left())


class TheToolbarChips(unittest.TestCase):
    def setUp(self):
        self.ck = _workspace().leads

    def test_chips_are_soft_33px_pills_with_a_radius_qt_will_draw(self):
        for b in (self.ck._views_btn, self.ck._filters_btn, self.ck._research_btn, self.ck._save_search_btn):
            self.assertEqual(b.height(), 33, b.text())
            sheet = b.styleSheet() or self.ck._toolbar.styleSheet()
            self.assertIn(theme.WELL, sheet)
            self.assertIn("border-radius:16px", sheet)          # 33px tall: 16 is the most Qt will honour

    def test_a_chip_is_painted_soft_not_white(self):
        img = self.ck._save_search_btn.grab().toImage()
        c = img.pixelColor(img.width() // 2, 4)
        self.assertEqual(c.name().upper(), theme.WELL.upper())

    def test_save_search_still_emits(self):
        got = []
        self.ck.saveSearchRequested.connect(lambda: got.append(1))
        self.ck._save_search_btn.click()
        self.assertEqual(got, [1])

    def test_search_box_is_33px(self):
        self.assertEqual(self.ck._search.height(), 33)


class TheResultRows(unittest.TestCase):
    def _row(self, pills, actions=()):
        spec = RR.RowSpec(key=1, name="Rakesh Mehta", company="Vraj Infra", subline="Purchase Manager",
                          pills=pills, actions=list(actions))
        r = RR.ResultRow(spec)
        r.resize(900, 60)
        r.show()
        _app.processEvents()
        return r

    def test_avatar_is_an_ink_disc_with_the_same_initials(self):
        a = RR.avatar("Rakesh Mehta")
        self.assertEqual(a.text(), "RM")
        self.assertIn(theme.INK, a.styleSheet())

    def test_status_pills_are_the_shared_mono_caps_pill_with_the_same_words(self):
        r = self._row([("Verified", "ok"), ("Risky", "warn"), ("Invalid", "err")])
        self.assertTrue(all(isinstance(p, C.Pill) for p in r.pills))
        self.assertEqual([p.text() for p in r.pills], ["Verified", "Risky", "Invalid"])
        self.assertEqual([p._tone_name for p in r.pills], ["st_ok", "st_warn", "st_err"])

    def test_saved_style_outline_pill_is_mono_caps(self):
        p = RR.pill("Saved", "outline")
        self.assertEqual(p.text(), "Saved")
        self.assertIn("Geist Mono", p.styleSheet())

    def test_buttons_are_28px_pills_and_still_call_through(self):
        hits = []
        r = self._row([], [("Open", True, lambda: hits.append("open")), ("Save", False, lambda: hits.append("save"))])
        for b in r.buttons:
            self.assertEqual(b.height(), 28)
            self.assertIn("border-radius:14px", b.styleSheet())
        r.buttons[0].click()
        r.buttons[1].click()
        self.assertEqual(hits, ["open", "save"])

    def test_the_list_has_no_card_border(self):
        self.assertIn("border:none", RR.ResultList().styleSheet())


class TheCreditsDonut(unittest.TestCase):
    def test_slices_are_the_brand_palette_not_blue_or_purple(self):
        banned = {"#4480bb", "#7c3aed", "#0891b2", "#db2777"}
        self.assertFalse(banned & set(CP._SLICES))
        self.assertEqual(CP._SLICES[0], theme.INK)
        self.assertEqual(CP._SLICES[1], theme.BRAND_RED)


class TheFilterRail(unittest.TestCase):
    def test_facet_titles_are_500_ink_and_the_count_badge_is_not_blue(self):
        from addons.leads import filter_panel as FP
        sheet = FP._sheet()
        self.assertIn(f"QLabel#fheadText{{color:{theme.INK};font-size:13px;font-weight:500;}}", sheet)
        self.assertNotIn("QLabel#ffacetCount{background:" + theme.INFO_BG, sheet)

    def test_people_tabs_band_is_stone_with_a_white_active_tile(self):
        ck = _workspace().leads
        sheet = ck._tabs_frame.styleSheet()
        self.assertIn("#EFEEEA", sheet)
        self.assertIn("QPushButton:checked{background:" + theme.CARD, sheet)
        ck._tab_btns["net_new"].click()
        self.assertEqual(ck.tab(), "net_new")


class TheOtherTabsAndPager(unittest.TestCase):
    def setUp(self):
        self.w = _workspace()

    def test_the_credits_chip_fits_beside_ten_tabs_at_1366(self):
        self.w.resize(1000, 640)                      # the card inside a 1366 window
        _app.processEvents()
        chip = [l for l in self.w.findChildren(QLabel) if l.text() == "Your credits · your inbox"][0]
        self.assertGreaterEqual(chip.width(), chip.sizeHint().width())
        self.assertAlmostEqual(chip.font().letterSpacing(), 0.2, delta=0.05)

    def test_the_page_picker_and_arrows_are_the_same_32px(self):
        ck = self.w.leads
        hs = {n: getattr(ck, n).sizeHint().height() for n in ("_prev_btn", "_page_box", "_next_btn")}
        self.assertEqual(set(hs.values()), {32}, hs)

    def test_lists_buttons_are_soft_pills_and_the_cards_keep_their_height(self):
        d = tempfile.mkdtemp()
        for n in ("a.csv", "b.csv"):
            open(os.path.join(d, n), "w").write("name\nx\n")
        tab = CK._ListsTab(d) if hasattr(CK, "_ListsTab") else None
        self.assertIsNotNone(tab)
        tab.resize(900, 700)
        tab.show()
        _app.processEvents()
        btns = {b.text(): b for b in tab.findChildren(QPushButton)}
        for t in ("Refresh", "Open folder"):
            self.assertIn("border-radius:16px", btns[t].styleSheet())
            self.assertIn("font-size:13px;font-weight:500", btns[t].styleSheet())
        self.assertIn("border-radius:15px", btns["Open"].styleSheet())
        card = btns["Open"].parentWidget()
        self.assertLess(card.height(), 200)

    def test_the_deals_move_button_is_a_white_ringed_pill(self):
        from addons.leads import deals_page as DP
        from addons.leads import deals as DL
        deal = DL.Deal(**{k: v for k, v in dict(id="d1", title="Panel order", company="Patel", value=1000.0).items()
                          if k in DL.Deal.__dataclass_fields__})
        card = DP._Card(deal, 0, [("Proposal", "Proposal", lambda: None)])
        sheet = card.move_btn.styleSheet()
        self.assertIn(f"background:{theme.CARD}", sheet)
        self.assertIn(f"border:1px solid {theme.HAIRLINE}", sheet)
        self.assertIn("border-radius:12px", sheet)
        self.assertEqual(card.move_btn.maximumHeight(), 24)


if __name__ == "__main__":
    unittest.main()
