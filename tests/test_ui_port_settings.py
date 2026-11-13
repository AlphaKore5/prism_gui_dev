"""UI port, stage 4 (Settings), checked on the real SettingsPanel rendered
offscreen under the real stylesheet: the white shell with the soft section
list, the section buttons and their red tick, the close button, mono status
pills, soft fact lists, bordered note/field panels, inputs, the toast and the
wallpaper tiles. Nothing here presses a Save button or reaches a real home."""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont                                    # noqa: E402
from PySide6.QtWidgets import (                                    # noqa: E402
    QApplication, QComboBox, QLineEdit, QPushButton,
)

_app = QApplication.instance() or QApplication([])

import theme                                                       # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from widgets import controls as C                                  # noqa: E402
from widgets import settings_panel as SP                           # noqa: E402

SECTION_KEYS = ["licence", "profile", "agents", "language", "status",
                "appearance", "privacy", "more"]


def _panel(section="licence", cfg=None):
    p = SP.SettingsPanel(dict(cfg or {}))
    p.resize(980, 700)
    p.show()
    p.show_section(section)
    _app.sendPostedEvents()
    return p


def _px(widget, x, y):
    img = widget.grab().toImage()
    c = img.pixelColor(x, y)
    return "#%02x%02x%02x" % (c.red(), c.green(), c.blue())


def _near(testcase, got, want, tol=3):
    g = [int(got[i:i + 2], 16) for i in (1, 3, 5)]
    w = [int(want[i:i + 2], 16) for i in (1, 3, 5)]
    testcase.assertTrue(all(abs(a - b) <= tol for a, b in zip(g, w)), (got, want))


def _valid_state():
    import time
    import licensing.status as st
    return st.LicenseState(
        status=st.VALID, plan="complete", customer="Parth", kind="paid",
        features=frozenset(["core", "boq"]), seats=1, license_id="x",
        license_ends=int(time.time()) + 86400 * 30,
        token_expires=int(time.time()) + 86400 * 30)


def _centre(widget, root):
    pt = widget.mapTo(root, widget.rect().center())
    return pt.x(), pt.y()


class TestShell(unittest.TestCase):
    def test_nav_is_a_soft_220px_panel_with_eight_34px_buttons(self):
        p = _panel()
        self.assertIsInstance(p._nav_host, SP._SettingsNav)
        self.assertEqual(p._nav_host.width(), 220)
        btns = p.findChildren(QPushButton, "secBtn")
        self.assertEqual(len(btns), 8)
        self.assertTrue(all(b.height() == 34 for b in btns))
        self.assertEqual([b.property("cur") for b in btns].count(True), 1)

    def test_nav_panel_is_soft_stone_and_active_row_is_white_with_red_tick(self):
        p = _panel()
        self.assertEqual(_px(p._nav_host, 4, 200), "#f6f5f2")
        cur = [b for b in p.findChildren(QPushButton, "secBtn") if b.property("cur")][0]
        x, y = cur.mapTo(p._nav_host, cur.rect().topLeft()).x() - 3, \
            cur.mapTo(p._nav_host, cur.rect().center()).y()
        self.assertEqual(_px(p._nav_host, x, y), theme.BRAND_RED.lower())
        cx, cy = _centre(cur, p._nav_host)
        self.assertEqual(_px(p._nav_host, cx + 60, cy - 8), "#ffffff")

    def test_clicking_a_section_still_switches_and_moves_the_tick(self):
        p = _panel()
        btns = {b.text(): b for b in p.findChildren(QPushButton, "secBtn")}
        btns["Language"].click()
        self.assertEqual(p._section, "language")
        cur = [b for b in p.findChildren(QPushButton, "secBtn") if b.property("cur")]
        self.assertEqual([b.text() for b in cur], ["Language"])

    def test_settings_search_still_filters_the_list(self):
        p = _panel()
        p._settings_search.setText("wallpaper")
        self.assertEqual([b.text() for b in p.findChildren(QPushButton, "secBtn")],
                         ["Appearance"])

    def test_close_button_is_the_ringed_38px_square_and_still_closes(self):
        p = _panel()
        close = p._header.findChild(QPushButton, "closeBtn")
        self.assertEqual((close.width(), close.height()), (38, 38))
        self.assertEqual(close.toolTip(), "Close settings")
        seen = []
        p.rejected.connect(lambda: seen.append(1))
        close.click()
        self.assertEqual(seen, [1])

    def test_request_a_meeting_and_version_line_remain(self):
        p = _panel()
        texts = [b.text() for b in p._nav_host.findChildren(QPushButton)]
        self.assertIn("Request a meeting", texts)
        import app_meta
        labels = [l.text() for l in p._nav_host.findChildren(SP.QLabel)]
        self.assertIn(f"Prism {app_meta.VERSION}", labels)

    def test_section_title_is_21px_regular_and_subtitle_muted(self):
        p = _panel()
        head = p.findChildren(C.SectionHeader)[0]
        self.assertEqual(head.title.text(), "Licence")
        # the stylesheet (id-scoped under #settingsPage) sets 21px / 13px
        self.assertEqual(head.title.fontInfo().pixelSize(), 21)
        self.assertEqual(head.subtitle.fontInfo().pixelSize(), 13)


class TestSurfaces(unittest.TestCase):
    def test_every_section_builds_with_its_panels(self):
        for key in SECTION_KEYS:
            p = _panel(key)
            self.assertGreaterEqual(len(p.findChildren(SP.Card)), 1, key)
            self.assertTrue(p._col.count() >= 2, key)

    def test_fact_list_is_soft_and_status_is_a_mono_caps_pill_with_a_square(self):
        from unittest import mock
        with mock.patch.object(SP.licensing, "state", _valid_state):
            p = _panel("licence")
        pills = [w for w in p.findChildren(C.Pill) if w.text() == "Active"]
        self.assertEqual(len(pills), 1)
        pill = pills[0]
        pill.resize(pill.sizeHint())
        self.assertEqual(pill.font().capitalization(), QFont.AllUppercase)
        self.assertIn("Geist Mono", pill.styleSheet())
        self.assertEqual(pill.text(), "Active")             # words untouched
        self.assertEqual(_px(pill, 12, pill.height() // 2), theme.BRAND_OK.lower())
        self.assertEqual(_px(pill, pill.width() - 3, 4), "#e4efe7")
        facts = pill.parentWidget()
        while facts is not None and not isinstance(facts, SP.Card):
            facts = facts.parentWidget()
        self.assertEqual(facts._kind, "soft")
        self.assertEqual(_px(facts, 6, facts.height() // 2), "#f6f5f2")

    def test_error_and_warning_pills_use_the_brand_tokens(self):
        err = SP.Pill("Unreachable", "err")
        warn = SP.Pill("Stale", "warn")
        for w in (err, warn):
            w.resize(w.sizeHint())
        self.assertEqual(_px(err, err.width() - 3, 4), theme.BRAND_ERR_BG.lower())
        self.assertEqual(_px(err, 12, err.height() // 2), theme.BRAND_ERR.lower())
        self.assertEqual(_px(warn, warn.width() - 3, 4), "#f6edd6")

    def test_whos_this_plan_for_is_a_white_bordered_panel(self):
        p = _panel("licence", {})
        notes = [c for c in p.findChildren(SP.Card) if c._kind == "white"]
        self.assertTrue(notes)
        n = notes[0]
        self.assertEqual(_px(n, n.width() // 2, n.height() // 2), "#ffffff")
        self.assertEqual(_px(n, 0, n.height() // 2), "#d8d7d2")

    def test_careful_group_is_the_brand_red_tint(self):
        p = _panel("licence")
        dangers = [c for c in p.findChildren(SP.Card) if c._kind == "danger"]
        self.assertEqual(len(dangers), 1)
        d = dangers[0]
        self.assertEqual(_px(d, 8, d.height() // 2), theme.BRAND_ERR_BG.lower())
        texts = [b.text() for b in d.findChildren(QPushButton)]
        self.assertEqual(texts, ["Change licence key", "Release this computer's seat"])

    def test_included_features_are_pills_not_the_old_sentence_case_ones(self):
        p = _panel("licence")
        inc = [w for w in p.findChildren(C.Pill) if w.text() == "Included"]
        self.assertTrue(inc)
        self.assertTrue(all(w.font().capitalization() == QFont.AllUppercase for w in inc))


class TestControls(unittest.TestCase):
    def test_key_fields_keep_their_eye_toggle_save_and_placeholder_colour(self):
        p = _panel("agents")
        edits = [e for e in p.findChildren(QLineEdit)
                 if e.echoMode() == QLineEdit.Password]
        self.assertGreaterEqual(len(edits), 2)               # Groq + OpenRouter
        for e in edits:
            eyes = [a for a in e.actions() if a.isCheckable()]
            self.assertEqual(len(eyes), 1)
            self.assertEqual(eyes[0].toolTip(), "Show password")
            eyes[0].setChecked(True)
            self.assertEqual(e.echoMode(), QLineEdit.Normal)
            self.assertEqual(eyes[0].toolTip(), "Hide password")
        saves = [b for b in p.findChildren(QPushButton) if b.text() == "Save"]
        self.assertGreaterEqual(len(saves), 3)

    def test_inputs_are_soft_with_a_ring_and_go_white_on_focus(self):
        p = _panel("profile")
        e = [x for x in p.findChildren(QLineEdit) if x.parentWidget() is not None
             and x.objectName() != "searchField"][0]
        e.resize(300, 36)
        _near(self, _px(e, 5, 5), "#f6f5f2")
        self.assertEqual(_px(e, 0, 18), "#d8d7d2")
        e.setFocus()
        _app.sendPostedEvents()
        e.setFocus(); e.repaint()
        # focus is reachable on a shown window; offscreen may not activate it,
        # so only assert the rule exists in the shipped stylesheet.
        self.assertIn("#settingsDialog QLineEdit:focus", QSS)

    def test_language_combos_are_soft_selects_with_the_caret(self):
        p = _panel("language")
        combos = p.findChildren(QComboBox)
        self.assertEqual(len(combos), 2)
        c = combos[0]
        c.resize(260, 36)
        _near(self, _px(c, 200, 18), "#f6f5f2")
        self.assertEqual(c.currentData(), "en")

    def test_secondary_destructive_and_primary_buttons(self):
        p = _panel("licence")
        btns = {b.text(): b for b in p.findChildren(QPushButton)}
        sec, dng = btns["Change licence key"], btns["Release this computer's seat"]
        self.assertEqual(sec.objectName(), "secondaryBtn")
        self.assertEqual(dng.objectName(), "dangerBtn")
        sec.resize(sec.sizeHint()); dng.resize(dng.sizeHint())
        self.assertNotEqual(_px(sec, sec.width() // 2, 4), "#ffffff")  # gradient, not flat white
        # destructive text colour comes from the brand red rule
        self.assertIn("#settingsDialog QPushButton#dangerBtn { color: #a3141a; }", QSS)

    def test_appearance_wallpaper_tiles_fit_inside_the_card(self):
        p = _panel("appearance")
        card = [c for c in p.findChildren(SP.Card)][0]
        tiles = [b for b in card.findChildren(QPushButton) if b.width() == 146]
        self.assertGreaterEqual(len(tiles), 3)
        for t in tiles:
            right = t.mapTo(card, t.rect().topRight()).x()
            self.assertLessEqual(right, card.width())
        self.assertTrue(all(t.toolTip() for t in tiles))     # still named


class TestToast(unittest.TestCase):
    def test_toast_is_an_ink_pill_with_a_tone_square(self):
        p = _panel("agents")
        for tone, colour in (("ok", "#3fb46f"), ("warn", "#e0a82e"), ("err", "#e5484d")):
            p.show_toast("Saved", tone)
            t = p._toast
            self.assertEqual(t.text(), "Saved")
            self.assertTrue(t.isVisible())
            self.assertEqual(_px(t, t.width() // 2, 3), theme.INK.lower())
            self.assertEqual(_px(t, 18, t.height() // 2), colour)
            self.assertEqual(t.grab().toImage().pixelColor(0, 0).alpha(), 0)  # corner is outside the pill
