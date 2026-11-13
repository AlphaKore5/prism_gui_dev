"""UI port, stage 5 (Email inquiries), on the real widgets offscreen under the
real stylesheet: the shared rail fix, the configured front page, the pipeline
board, and the working window's message bar."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor                                   # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton    # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

import core_bridge as CB                                           # noqa: E402
from core import register as REG, mailflow as MAILFLOW             # noqa: E402
from widgets import controls as C                                  # noqa: E402
from widgets.sidebar import Sidebar                                # noqa: E402
from addons.inquiry import board as BOARD                          # noqa: E402
from addons.inquiry.panel import InquiryPanel                      # noqa: E402


def _row(no, status, **kw):
    row = dict.fromkeys(REG.COLUMNS, "")
    row.update({"Inquiry no": no, "Customer": "Customer " + no, "Status": status,
                "Date received": date.today().isoformat(), "Product asked": "Item"})
    row.update(kw)
    return row


def _cfg(folder, accounts=2):
    paths = MAILFLOW.Paths(folder)
    paths.ensure()
    REG.save([_row("INQ-1", REG.NEW), _row("INQ-2", REG.NEW),
              _row("INQ-3", REG.QUOTED, **{"Quotation no": "Q3", "Quotation value": "1000",
                                           "Quotation date": "2020-01-01"})],
             paths.register_csv)
    mail = [{"address": f"box{i}@example.com", "password": "x", "host": "imap.example.com",
             "port": 993, "folder": "INBOX"} for i in range(accounts)]
    mail[-1]["password"] = ""            # one mailbox that cannot sign in yet
    return {"inquiry": {"folder": folder, "accounts": mail}}


class TheRailAtShortHeights(unittest.TestCase):
    def _rail(self, height):
        rail = Sidebar()
        rail.resize(258, height)
        rail.show()
        _app.processEvents()
        return rail

    def _settings_bottom(self, rail):
        btn = rail._nav["config"]
        return btn.mapTo(rail._inner, btn.rect().bottomLeft()).y() + 1

    def test_settings_row_clears_the_viewport_at_768(self):
        rail = self._rail(718)                 # the rail's height in a 768px window
        self.assertLessEqual(self._settings_bottom(rail),
                             rail._scroll.viewport().height())

    def test_rows_above_settings_do_not_move_when_the_gaps_tighten(self):
        short, roomy = self._rail(718), self._rail(900)
        for key in ("home", "inquiry", "bom"):
            if key in short._nav:
                self.assertEqual(short._nav[key].y(), roomy._nav[key].y(), key)

    def test_roomy_height_keeps_the_normal_gaps(self):
        rail = self._rail(900)
        self.assertEqual([i.sizeHint().height() for i, _n, _t in rail._gaps],
                         [n for _i, n, _t in rail._gaps])

    def test_growing_the_window_gives_the_gaps_back(self):
        rail = self._rail(718)
        rail.resize(258, 900)
        _app.processEvents()
        self.assertEqual([i.sizeHint().height() for i, _n, _t in rail._gaps],
                         [n for _i, n, _t in rail._gaps])


class ThePrimaryPillUnderTheAppSheet(unittest.TestCase):
    def test_it_keeps_its_painted_height_where_no_header_rule_sizes_it(self):
        from PySide6.QtWidgets import QVBoxLayout, QWidget
        host = QWidget()
        QVBoxLayout(host).addWidget(C.button("Update the register", "primary"))
        host.resize(300, 200)
        host.show()
        _app.processEvents()
        pill = host.findChild(C.DarkPill)
        self.assertEqual((pill.minimumHeight(), pill.maximumHeight(), pill.height()),
                         (33, 33, 33))                 # the sheet's 48px minimum is gone


class TheConfiguredFrontPage(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.panel = InquiryPanel(_cfg(self._tmp.name))
        self.panel.resize(1000, 700)
        self.panel.show()
        _app.processEvents()

    def tearDown(self):
        self.panel.close()
        self._tmp.cleanup()

    def _labels(self):
        return {w.text() for w in self.panel.findChildren(QLabel)}

    def test_kickers_name_the_three_blocks(self):
        shown = self._labels()
        for text in ("WHAT NEEDS YOU TODAY", "MAILBOXES PRISM READS"):
            self.assertIn(text, shown)
        self.assertTrue(any(t.startswith("THIS MONTH") for t in shown))

    def test_needs_you_and_this_month_sit_side_by_side(self):
        cards = [c for c in self.panel.findChildren(C.Card)
                 if c.parentWidget() is self.panel._host]
        self.assertEqual(len(cards), 2)
        a, b = sorted(cards, key=lambda c: c.x())
        self.assertLess(a.geometry().right(), b.x())
        self.assertAlmostEqual(a.y(), b.y(), delta=2)
        self.assertGreater(a.width(), b.width())        # 1.25 : 1

    def test_cards_carry_no_ink_stripe(self):
        for card in self.panel.findChildren(C.Card):
            self.assertFalse(card._stripe)

    def test_action_buttons_are_the_light_pill_and_still_open_the_tab(self):
        fired = []
        self.panel.open_dialog.connect(fired.append)
        quote = next(b for b in self.panel.findChildren(QPushButton)
                     if b.text() == "Quote them")
        self.assertEqual(quote.objectName(), "smallBtn")
        self.assertEqual(quote.height(), 33)             # the preview's .btn.sm
        quote.click()
        self.assertEqual(fired, [0])

    def test_figures_are_mono_and_a_zero_row_has_no_button(self):
        figures = {w.text(): w for w in self.panel.findChildren(QLabel)
                   if w.objectName() == "needsFigure"}
        self.assertEqual(set(figures), {"2", "1", "0"})
        self.assertIn(theme.FONT_MONO_STACK, figures["2"].styleSheet())
        self.assertIn(theme.FAINT, figures["0"].styleSheet())
        buttons = [b.text() for b in self.panel.findChildren(QPushButton)]
        self.assertNotIn("Read the answer", buttons)
        self.assertNotIn("Open the order", buttons)

    def test_mailboxes_wear_the_ready_pills(self):
        pills = [(p.text(), p._tone_name) for p in self.panel.findChildren(C.Pill)]
        self.assertIn(("Ready", "st_ok"), pills)
        self.assertIn(("Needs a password", "st_warn"), pills)

    def test_header_keeps_both_actions(self):
        buttons = [b.text() for b in self.panel._header.findChildren(QPushButton)]
        self.assertIn("Edit setup", buttons)
        self.assertIn("Open Email inquiry automation", buttons)


class TheBoard(unittest.TestCase):
    def test_a_card_has_no_stripe_on_its_left_edge(self):
        card = BOARD.BoardCard(_row("INQ-9", REG.NEW), head="INQ-9", pill=("New", "new"),
                               product="Item", tone="new")
        card.resize(220, 90)
        img = card.grab().toImage()
        self.assertEqual(QColor(img.pixel(2, 45)).name(), "#ffffff")

    def test_pill_is_mono_caps_with_a_small_radius(self):
        pill = BOARD.TonePill("overdue", "lost")
        self.assertEqual(pill.text(), "OVERDUE")
        self.assertIn("border-radius: 6px", pill.styleSheet())
        self.assertIn(theme.FONT_MONO_STACK, pill.styleSheet())

    def test_column_header_is_a_soft_panel_not_a_tint(self):
        col = BOARD.Column("quoted", 2, "Quoted", "Sent", 4)
        self.assertIn("#F6F5F2", col.styleSheet())
        self.assertNotIn(BOARD._tone("quoted")[0], col.styleSheet())

    def test_kpi_tile_has_no_coloured_left_border(self):
        kpi = BOARD._Kpi("inquiry")
        self.assertNotIn("border-left", kpi.styleSheet())


class TheWorkingWindowsMessageBar(unittest.TestCase):
    def test_the_status_line_takes_the_width_it_is_given(self):
        from addons.inquiry import dialog as UI
        with tempfile.TemporaryDirectory() as tmp:
            dlg = UI.InquiryDialog(_cfg(tmp))
            dlg.resize(1100, 700)
            dlg.show()
            dlg.status.setText("Ready. Press Check my mail now.")
            _app.processEvents()
            self.assertGreater(dlg.status.width(), 300)
            self.assertLess(dlg.status.height(), 30)        # one line, not wrapped
            dlg.close()


if __name__ == "__main__":
    unittest.main()
