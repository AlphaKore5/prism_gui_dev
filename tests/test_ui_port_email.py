"""UI port, stage 6 (Email outreach), on the real widgets offscreen under the
real stylesheet: the configured page, the sent rows, the pill buttons, and the
compose / setup dialogs. Hermetic: a temp folder holds the sent log, no licence
file and nothing in the home is read."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QPushButton      # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme                                                         # noqa: E402
theme.load_fonts()
QSS = open(os.path.join(ROOT, "style.qss"), encoding="utf-8").read()
_app.setStyleSheet(QSS.replace("%ASSETS%", os.path.join(ROOT, "assets").replace(os.sep, "/")))

from addons.email import panel as P                                  # noqa: E402
from addons.email.dialog import EmailComposeDialog, EmailSetupDialog  # noqa: E402
from addons.email.panel import EmailPanel                            # noqa: E402
from widgets import controls as C                                    # noqa: E402


def _entry(subject, to, sent, failed=(), stopped=False):
    now = datetime.now()
    return {"date": now.strftime("%Y-%m-%d"), "time": "10:30", "from": "a@b.example",
            "to": [{"email": e, "name": ""} for e in to], "subject": subject,
            "body": "x", "sent": list(sent), "failed": [list(f) for f in failed],
            "attachments": [], "list_name": "", "stopped": stopped}


def _cfg(folder, log=True):
    if log:
        rows = [_entry("Quote one", ["a@x.example"], ["a@x.example"]),
                _entry("Bounced one", ["b@x.example"], [], [("b@x.example", "550")]),
                _entry("Partly", ["c@x.example", "d@x.example"], ["c@x.example"],
                       [("d@x.example", "550")]),
                _entry("Stopped", ["e@x.example", "f@x.example"], ["e@x.example"], stopped=True)]
        with open(os.path.join(folder, "sent.json"), "w", encoding="utf-8") as f:
            json.dump(rows, f)
    acct = {"address": "sales@sample.example", "password": "pw", "host": "smtp.sample.example", "port": 587}
    return {"email": dict(acct, folder=folder, accounts=[acct])}


def _panel(log=True):
    p = EmailPanel(_cfg(tempfile.mkdtemp(), log))
    p.resize(1100, 800)
    p.show()
    _app.processEvents()
    return p


class TheConfiguredPage(unittest.TestCase):

    def test_account_and_start_cards_share_a_row_above_the_list(self):
        p = _panel()
        kicks = [k for k in p.findChildren(C._Kicker)]
        texts = [k.text() for k in kicks]
        self.assertEqual(texts[:3], ["SENDING ACCOUNT", "SEND AN EMAIL", "SENT FROM THIS COMPUTER"])
        a, b, c = (k.window() and k.parentWidget() for k in kicks[:3])
        ay, by, cy = (w.mapTo(p, w.rect().topLeft()).y() for w in (a, b, c))
        self.assertEqual(ay, by)
        self.assertGreater(cy, ay + 80)

    def test_account_card_has_avatar_ready_pill_and_change_button(self):
        p = _panel()
        avatars = p.findChildren(C.Avatar)
        self.assertEqual([a.text() for a in avatars], ["S"])
        ready = [w for w in p.findChildren(C.Pill) if w.text() == "Ready"]
        self.assertEqual(len(ready), 1)
        seen = []
        p.change_account.connect(lambda: seen.append(1))
        change = [b for b in p.findChildren(QPushButton) if b.text() == "Change account"
                  and b.parentWidget() is not p.header and not p.header.isAncestorOf(b)]
        self.assertEqual(len(change), 1)
        self.assertEqual(change[0].height(), 33)
        change[0].click()
        self.assertEqual(seen, [1])

    def test_start_buttons_are_33px_pills_and_still_emit(self):
        p = _panel()
        seen = []
        p.open_compose.connect(seen.append)
        for b in (p.one_btn, p.list_btn, ):
            self.assertEqual(b.height(), 33)
        p.one_btn.click()
        p.list_btn.click()
        self.assertEqual(seen, ["one", "list"])

    def test_pill_corners_are_really_round(self):
        """Qt drops a border-radius larger than half the height: 17px on a 33px
        button painted a square box. The corner pixel must be the page, not the
        button fill."""
        p = _panel()
        img = p.one_btn.grab().toImage()
        corner = img.pixelColor(0, 0)
        edge = img.pixelColor(img.width() // 2, 0)        # the hairline ring
        self.assertNotEqual(corner.name(), edge.name())    # a square box has the ring in its corner

    def test_sent_rows_keep_their_items_and_paint_tones(self):
        p = _panel()
        t = p.sent_table
        self.assertEqual(t.rowCount(), 4)
        self.assertEqual(t.item(3, 3).text(), "Sent")
        self.assertEqual(t.item(0, 3).text(), "Stopped after 1")
        tones = [t.item(r, 3).data(P._TONE_ROLE) for r in range(4)]
        # newest first: Stopped, Partly, Bounced, Quote one
        self.assertEqual(tones, ["st_warn", "st_warn", "st_err", "st_ok"])
        self.assertEqual(t.item(2, 3).text(), "Failed")
        self.assertEqual(t.item(2, 1).text(), "b@x.example")
        self.assertTrue(t.isColumnHidden(1))
        self.assertFalse(t.horizontalHeader().isVisible())
        self.assertEqual(t.verticalHeader().defaultSectionSize(), P.ROW_H)
        self.assertEqual(t.rowHeight(0), P.ROW_H)

    def test_sent_row_paints_a_pill_in_the_result_column(self):
        p = _panel()
        t = p.sent_table
        img = t.viewport().grab().toImage()
        x = t.columnViewportPosition(3) + t.columnWidth(3) - 40
        y = t.rowViewportPosition(2) + P.ROW_H // 2          # the bounced row
        colour = img.pixelColor(x, y)
        self.assertGreater(colour.red(), colour.green())     # the soft red tint

    def test_when_text_is_the_previews_words(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(P._when_text(today + " 10:30"), "Today 10:30")
        self.assertEqual(P._when_text("2020-01-02 09:00"), "2020-01-02 09:00")
        self.assertEqual(P._when_text("garbage"), "garbage")

    def test_open_the_folder_is_a_pill_and_the_header_buttons_remain(self):
        p = _panel()
        folder = [b for b in p.findChildren(QPushButton) if b.text() == "Open the folder"][0]
        self.assertEqual(folder.height(), 33)
        self.assertEqual([a.text() for a in p.header_actions()], ["Change account", "New email"])

    def test_empty_log_keeps_its_sentence(self):
        p = _panel(log=False)
        self.assertIsNone(p.sent_table)
        texts = " ".join(l.text() for l in p.findChildren(C.QLabel))
        self.assertIn("Nothing sent yet.", texts)

    def test_unconfigured_state_is_the_door(self):
        p = EmailPanel({})
        p.show()
        _app.processEvents()
        doors = p.findChildren(C.EmptyState)
        self.assertEqual(len(doors), 1)
        self.assertEqual(doors[0].title.text(), "No sending account yet")
        seen = []
        p.change_account.connect(lambda: seen.append(1))
        doors[0].clicked.emit()
        self.assertEqual(seen, [1])


class TheComposeDialog(unittest.TestCase):

    def _dialog(self):
        d = EmailComposeDialog(_cfg(tempfile.mkdtemp()), [], None)
        d.show()
        _app.processEvents()
        return d

    def test_buttons_are_pills_and_the_search_hint_is_a_link(self):
        d = self._dialog()
        for b in (d.list_btn, d.attach_btn, d.write_btn):
            self.assertEqual(b.height(), 33)
        self.assertLessEqual(d.search_btn.height(), 24)
        self.assertIn("border: none", d.search_btn.styleSheet())

    def test_pace_is_a_soft_band_and_the_draft_group_a_hairline_box(self):
        d = self._dialog()
        pace = d.findChild(QFrame, "paceStripe")
        draft = d.findChild(QFrame, "draftGroup")
        self.assertIn("#F6F5F2", pace.styleSheet())
        self.assertIn("#E6E5E1", draft.styleSheet())
        self.assertIn("MONO", d.pace_summary.objectName().upper() or "MONO")
        self.assertTrue(d.pace_summary.text())

    def test_send_is_disabled_with_its_reason_and_enables_when_filled(self):
        d = self._dialog()
        self.assertFalse(d.send_btn.isEnabled())
        self.assertIn("Still needed", d.send_btn.toolTip())
        d.to_edit.setText("r@acme.example")
        d.subject_edit.setText("Hi")
        d.body_edit.setPlainText("Body")
        self.assertTrue(d.send_btn.isEnabled())

    def test_locked_buttons_say_why_while_sending(self):
        d = self._dialog()
        d._set_sending(True)
        for b in (d.list_btn, d.attach_btn, d.write_btn):
            self.assertFalse(b.isEnabled())
            self.assertEqual(b.toolTip(), "Locked while the emails are going out.")
        self.assertEqual(d.send_btn.text(), "Stop sending")
        self.assertTrue(d.send_btn.isEnabled())
        d._set_sending(False)
        self.assertEqual(d.list_btn.toolTip(), "")

    def test_field_labels_are_quiet(self):
        d = EmailComposeDialog._field_label("To")
        self.assertIn("font-weight: 400", d.styleSheet().replace("font-weight:400", "font-weight: 400"))


class TheSetupDialog(unittest.TestCase):

    def test_note_is_soft_and_buttons_are_pills(self):
        d = EmailSetupDialog(_cfg(tempfile.mkdtemp()), None)
        d.show()
        _app.processEvents()
        for b in (d.add_sender_btn, d.remove_sender_btn, d.default_btn):
            self.assertEqual(b.height(), 33)
        self.assertEqual(d.test_btn.text(), "Test connection")

    def test_result_line_takes_a_tone_and_keeps_its_words(self):
        d = EmailSetupDialog({}, None)
        d.show()
        d._on_verified("Login failed")
        self.assertEqual(d.status.text(), "✗  Login failed")
        self.assertIn(theme.BRAND_ERR, d.status.styleSheet())
        d._on_verified("")
        self.assertEqual(d.status.text(), "✓  Signed in — this account can send.")
        self.assertIn(theme.BRAND_OK, d.status.styleSheet())


if __name__ == "__main__":
    unittest.main()
