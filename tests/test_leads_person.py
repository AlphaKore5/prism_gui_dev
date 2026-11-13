"""The person panel — Apollo's contact profile (addons/leads/person.py).

knowledge.apollo.io "View and Edit Contacts" (read 23-Sep-2026): on the left,
Contact information · Record details · Tasks · Account · Notes; tabs on the
right, Prospect · Activities · Sequences · Enrichment · All Fields; "…" > Edit
contact info / Flag as inaccurate / Delete contact. The panel only SHOWS a
PersonView and says what the owner asked by a signal — these tests hand it
records and read what it draws and what it asks for, with no store and no
modal box.
"""
from __future__ import annotations

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QSize                                    # noqa: E402
from PySide6.QtGui import QResizeEvent                              # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel      # noqa: E402

from prospector.models import Dimension, Dossier, Lead              # noqa: E402
from addons.leads import person as PP                               # noqa: E402
from addons.leads.accounts import Account                           # noqa: E402
from addons.leads.contacts import Contact                           # noqa: E402
from addons.leads.pool import UNQUALIFIED, Person                   # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


def _lead(**kw):
    base = dict(name="Asha Rao", title="Owner", company="Rao Precision Works",
                email="asha@raoprecision.example", fit_score=72,
                fit_reason="owner of a machine shop")
    base.update(kw)
    lead = Lead(**base)
    lead.extra.update({"location": "Pune, India",
                       "linkedin": "linkedin.com/in/asha-rao-example",
                       "custom": {"Lead Quality": "A"}})
    return lead


def _contact(lead, **kw):
    base = dict(saved_at="2026-09-20T10:00:00+05:30", stage="Interested",
                lists=["Expo leads"],
                notes=[{"at": "2026-09-21T09:00:00+05:30", "text": "Met at the expo"}],
                tasks=[{"id": "t1", "at": "2026-09-21T09:05:00+05:30",
                        "text": "Send the brochure", "due": "2026-09-30", "done": False}],
                history=[{"at": "2026-09-20T10:00:00+05:30", "kind": "saved", "text": "import"},
                         {"at": "2026-09-22T11:00:00+05:30", "kind": "stage",
                          "text": "Cold → Interested"},
                         {"at": "2026-09-22T12:00:00+05:30", "kind": "call",
                          "text": "Wants a quote"},
                         {"at": "2026-09-22T13:00:00+05:30", "kind": "sent",
                          "text": "Your second plant"}])
    base.update(kw)
    return Contact(lead=lead, **base)


def _texts(widget) -> list:
    return [w.text() for w in widget.findChildren(QLabel)]


class _Recorder:
    def __init__(self, panel):
        self.got = []
        for name in ("saveRequested", "stageRequested", "accountStageRequested",
                     "accountSaveRequested", "noteRequested", "taskRequested",
                     "taskDoneRequested", "logRequested", "editRequested",
                     "flagRequested", "deleteRequested", "listRequested",
                     "sequenceRequested", "enrichRequested", "personPicked"):
            getattr(panel, name).connect(lambda *a, n=name: self.got.append((n,) + a))


class ASavedContact(unittest.TestCase):
    def setUp(self):
        self.lead = _lead()
        self.row = Dossier(lead=self.lead, verdict="hot", score=88,
                           generated_at="2026-09-21T08:00:00+00:00",
                           dimensions=[Dimension(name="Fit", verdict="pass",
                                                 evidence="Runs a 60-person shop")])
        self.account = Account(name="Rao Precision Works", domain="raoprecision.example",
                               website="raoprecision.example", industry="Machinery",
                               headcount="60", stage="Current Client", lists=["Top 50"],
                               custom={"Tier": "Gold"})
        self.view = PP.PersonView(row=self.row, contact=_contact(self.lead),
                                  account=self.account,
                                  found_by=[("2026-09-19T10:00:00+05:30", "3 titles · India")])
        self.p = PP.PersonPanel()
        self.p.resize(760, 900)
        self.rec = _Recorder(self.p)
        self.p.show_person(self.view)

    def test_the_header_is_who_they_are(self):
        self.assertEqual(self.p.name.text(), "Asha Rao")
        self.assertEqual(self.p.role.text(), "Owner at Rao Precision Works · Pune, India")
        self.assertFalse(self.p._linkedin.isHidden())
        self.assertTrue(self.p._save_btn.isHidden())           # already a contact
        self.assertTrue(self.p._act_delete.isEnabled())

    def _resized(self, width, height):
        """The panel at a real size, with no event loop: resize, send the
        resize a hidden widget would only get on show, run the layout."""
        p = self.p
        p.resize(width, height)
        QApplication.sendEvent(p, QResizeEvent(p.size(), QSize()))
        p.layout().activate()
        return p

    def test_a_tall_panel_pins_its_header_a_short_one_scrolls_it_away(self):
        """Owner, 26-Sep-2026: "i cant see the contact's details properly". The
        header (name, role, the action buttons) is ~150px, pinned above the
        scroll; in a 340px drawer that left ~190px for the person, and on a
        laptop 57px. A panel shorter than _STICKY_H makes the header the first
        thing in the scroll instead, so the whole panel is the reading area."""
        p = self._resized(760, 900)
        self.assertTrue(p._head_sticky)
        self.assertIs(p._head_group.parentWidget(), p)
        self.assertEqual(p.layout().indexOf(p._head_group), 0)
        pinned = p._scroll.viewport().height()
        self.assertLess(pinned, 900 - p._head_group.height() + 2)   # the header takes its share

        p = self._resized(760, PP._STICKY_H - 60)
        self.assertFalse(p._head_sticky)
        self.assertIs(p._head_group.parentWidget(), p._scroll.widget())
        self.assertEqual(p.layout().indexOf(p._head_group), -1)
        self.assertGreaterEqual(p._scroll.viewport().height(), p.height() - 2)  # all of it

        p = self._resized(760, 900)                       # and back, with nothing lost
        self.assertTrue(p._head_sticky)
        self.assertIs(p._head_group.parentWidget(), p)
        self.assertEqual(p._scroll.viewport().height(), pinned)

    def test_the_header_and_its_buttons_survive_the_move(self):
        p = self._resized(760, PP._STICKY_H - 60)          # scrolling
        for button in (p._mail_btn, p._call_btn, p._task_btn, p._list_btn,
                       p._seq_btn, p._expand_btn):
            self.assertIs(button.window(), p.window())
            self.assertTrue(button.isVisibleTo(p), button.toolTip() or button.text())
        self.assertEqual(p.name.text(), "Asha Rao")       # still filled in
        self.assertFalse(p._head_group.isHidden())

    def test_the_left_widgets_apollos_order(self):
        heads = [w.text() for w in self.p._left.findChildren(QLabel)
                 if w.objectName() == "pHead"]
        # Apollo's five, plus the CRM mockup's Deal box (3-Nov-2026) after Record details: who it is with and a Create deal button.
        self.assertEqual(heads, ["CONTACT INFORMATION", "RECORD DETAILS", "DEAL", "TASKS",
                                 "ACCOUNT", "NOTES"])

    def test_contact_information_and_record_details(self):
        texts = _texts(self.p._left)
        self.assertIn("asha@raoprecision.example", texts)
        self.assertIn("Unverified", texts)                      # never verified
        self.assertIn(PP._PHONE_NOTE, texts)                    # no phone: says why
        self.assertEqual(self.p.stage.currentData(), "Interested")
        self.assertIn("Expo leads", texts)
        self.assertIn("22 Sep 2026", texts)                     # last activity

    def test_a_stage_picked_asks_for_it(self):
        self.p.stage.setCurrentIndex(self.p.stage.findData("Replied"))
        self.p.stage.activated.emit(self.p.stage.currentIndex())
        self.assertEqual(self.rec.got[-1], ("stageRequested", self.lead, "Replied"))

    def test_tasks_notes_and_the_account(self):
        [box] = self.p.task_boxes.values()
        self.assertIn("Send the brochure", self.p.task_labels["t1"].text())
        box.setChecked(True)
        self.assertEqual(self.rec.got[-1], ("taskDoneRequested", self.lead, "t1", True))
        self.p._task_form(True)
        self.p.task_text.setText("Call back")
        self.p.task_add.click()
        self.assertEqual(self.rec.got[-1], ("taskRequested", self.lead, "Call back", ""))
        self.p.note_edit.setPlainText("Prefers WhatsApp")
        self.p.note_btn.click()
        self.assertEqual(self.rec.got[-1], ("noteRequested", self.lead, "Prefers WhatsApp"))
        self.assertIn("Met at the expo", _texts(self.p._left))
        self.assertEqual(self.p.account_stage.currentData(), "Current Client")
        self.p.account_stage.setCurrentIndex(self.p.account_stage.findData("Dead Opportunity"))
        self.p.account_stage.activated.emit(0)
        self.assertEqual(self.rec.got[-1],
                         ("accountStageRequested", self.account, "Dead Opportunity"))

    def test_the_tabs_prospect_first(self):
        self.assertEqual([b.text() for b in self.p.tab_btns.values()],
                         ["Prospect", "Activities", "Sequences", "Enrichment", "All Fields"])
        self.assertEqual(self.p.tab(), "prospect")
        texts = _texts(self.p._stack.widget(0))
        self.assertIn("HOT", texts)
        self.assertIn("Runs a 60-person shop", texts)
        self.assertIn("Machinery", texts)                       # Account overview

    def test_activities_newest_first_and_by_type(self):
        lines = [a["text"] for a in PP.activities(self.view)]
        self.assertEqual(lines[0], "E-mail sent: Your second plant")
        self.assertIn("Call logged: Wants a quote", lines)
        self.assertIn("Stage changed from Cold to Interested", lines)
        self.assertIn("Qualified: HOT · 88 / 100", lines)
        # A search found her on the 19th, before the import on the 20th.
        self.assertEqual(lines[-2:], ["Imported from a CSV",
                                      "Found by a search: 3 titles · India"])
        # 08:00 UTC is 13:30 in Pune: after the 09:00 note, whatever the text says.
        self.assertLess(lines.index("Qualified: HOT · 88 / 100"),
                        lines.index("Note: Met at the expo"))
        self.p._filter_activities("calls")
        shown = [w.text() for w in self.p._stack.widget(1).findChildren(QLabel)
                 if w.objectName() == "pVal"]
        self.assertEqual(shown, ["Call logged: Wants a quote"])

    def test_log_activity(self):
        self.p._log_form("meeting")
        self.assertIn("meeting", self.p.log_title.text())
        self.p.log_text.setPlainText("Plant visit, Chakan")
        self.p.log_save.click()
        self.assertEqual(self.rec.got[-1],
                         ("logRequested", self.lead, "meeting", "Plant visit, Chakan"))

    def test_all_fields_people_and_company_with_search(self):
        fields = dict(PP.all_fields(self.view, "people"))
        self.assertEqual(fields["Lead Quality"], "A")           # the sheet's own column
        self.assertEqual(fields["Stage"], "Interested")
        company = dict(PP.all_fields(self.view, "company"))
        self.assertEqual((company["Account stage"], company["Tier"]), ("Current Client", "Gold"))
        self.p._fields_to("people")
        self.p.field_search.setText("quality")
        self.assertEqual(self.p.field_rows, [("Lead Quality", "A")])

    def test_edit_flag_and_delete_ask_first(self):
        self.p.ask_edit = lambda values: {"title": "MD"} if values["name"] == "Asha Rao" else None
        self.p._act_edit.trigger()
        self.assertEqual(self.rec.got[-1], ("editRequested", self.lead, {"title": "MD"}))
        self.p._act_flag.trigger()
        self.assertEqual(self.rec.got[-1], ("flagRequested", self.lead))
        self.p.confirm_delete = lambda name: False
        self.p._act_delete.trigger()
        self.assertEqual(self.rec.got[-1], ("flagRequested", self.lead))   # a No: nothing
        self.p.confirm_delete = lambda name: True
        self.p._act_delete.trigger()
        self.assertEqual(self.rec.got[-1], ("deleteRequested", self.lead))

    def test_the_real_delete_box_shows_a_name_as_text_never_as_markup(self):
        """`name` arrives from an imported sheet or a provider. The static
        QMessageBox helpers default to AutoText, so "<b>Admin</b>" in it
        rendered as markup in the box that confirms who is being deleted. The
        real box is built here (the seam is normally replaced) and only its
        format and text are read: exec() is intercepted, no modal opens."""
        from unittest import mock
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QMessageBox
        seen = []

        def fake_exec(box):
            seen.append((box.textFormat(), box.text(), box.defaultButton().text()))
            return QMessageBox.StandardButton.No

        name = "<b>Admin</b> <font color=red>Ravi</font>"
        with mock.patch.object(QMessageBox, "exec", fake_exec):
            self.assertFalse(PP.PersonPanel.confirm_delete(self.p, name))
        [(fmt, text, default)] = seen
        self.assertEqual(fmt, Qt.TextFormat.PlainText)
        self.assertIn(name, text)
        self.assertIn("No", default.replace("&", ""))

    def test_two_columns_when_wide_one_when_narrow(self):
        self.p._lay_out(True)
        self.assertEqual(self.p._left.maximumWidth(), PP._LEFT_W)
        self.p._lay_out(False)
        self.assertGreater(self.p._left.maximumWidth(), PP._LEFT_W)

    def test_the_tab_stays_when_the_record_is_drawn_again(self):
        self.p.set_tab("fields")
        self.p.show_person(self.view)
        self.assertEqual(self.p.tab(), "fields")


class SomeoneNotSavedYet(unittest.TestCase):
    def setUp(self):
        self.lead = Lead(name="Dev Net", title="Director", company="Das Forgings",
                         fit_score=40)
        self.row = Dossier(lead=self.lead, verdict="", generated_at="", status=UNQUALIFIED)
        colleague = Person(lead=Lead(name="Cy Das", title="CEO", company="Das Forgings"),
                           saved=True)
        self.p = PP.PersonPanel()
        self.rec = _Recorder(self.p)
        self.p.show_person(PP.PersonView(row=self.row, colleagues=[colleague]))
        self.colleague = colleague

    def test_it_says_so_and_offers_save(self):
        self.assertIn("Not saved yet", " ".join(_texts(self.p._left)))
        self.assertFalse(self.p._save_btn.isHidden())
        self.assertFalse(self.p._act_delete.isEnabled())       # nothing to delete
        self.assertEqual(self.p.stage.currentData(), "")        # no stage yet
        self.p._save_btn.click()
        self.assertEqual(self.rec.got[-1], ("saveRequested", self.lead))

    def test_not_qualified_offers_qualify_and_the_colleagues(self):
        texts = _texts(self.p._stack.widget(0))
        self.assertTrue(any("Not qualified yet" in t for t in texts))
        self.assertIn("PEOPLE AT DAS FORGINGS", texts)
        [link] = [b for b in self.p._stack.widget(0).findChildren(PP.QPushButton)
                  if b.text() == "Cy Das"]
        link.click()
        self.assertEqual(self.rec.got[-1], ("personPicked", self.colleague))

    def test_enrichment_offers_what_is_left_and_asks_for_it(self):
        boxes = self.p.enrich_boxes
        self.assertTrue(boxes["email"].isEnabled())             # no address yet
        self.assertTrue(boxes["qualify"].isEnabled())           # never qualified
        self.assertTrue(boxes["company"].isEnabled())
        self.assertTrue(boxes["phone"].isEnabled())             # a company to look a number up for
        boxes["email"].setChecked(True)
        boxes["qualify"].setChecked(True)
        self.p.enrich_btn.click()
        self.assertEqual(self.rec.got[-1], ("enrichRequested", self.row, ["email", "qualify"]))

    def test_no_draft_means_no_sequence_yet(self):
        self.assertIn("Not in a sequence", " ".join(_texts(self.p._stack.widget(2))))


if __name__ == "__main__":
    unittest.main()
