"""Sequences (addons/leads/sequences.py + sequences_page.py): the definitions are kept with the store's rules, where each person stands is read from
stored history, and nothing here sends. Temp folders stand in for the member's; no real ~/.prism is read."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402

import core_bridge  # noqa: F401,E402
from addons.leads import cockpit as CK                      # noqa: E402
from addons.leads import contacts as CT                     # noqa: E402
from addons.leads import due_today as DT                    # noqa: E402
from addons.leads import sequences as SQ                    # noqa: E402
from addons.leads import sequences_page as SP               # noqa: E402
from prospector.models import Lead                          # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
TODAY = date(2026, 11, 4)


def _contact(name="Vikram Kale", stage="Approaching", sent=("2026-11-01",), via=("sequence",)):
    c = CT.Contact(lead=Lead(name=name, company="Kale Panels", title="Owner"), saved_at="2026-10-01T10:00:00+05:30", stage=stage, via=list(via))
    for d in sent:
        c.history.append({"at": f"{d}T10:00:00+05:30", "kind": "sent", "text": "Hello"})
    return c


class TheStore(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_a_new_sequence_starts_from_the_three_touch_default(self):
        seq = SQ.add(self.folder, "3-touch email")
        [back] = SQ.list_sequences(self.folder)
        self.assertEqual((back.id, back.name, [s.after_days for s in back.steps]), (seq.id, "3-touch email", [0, 3, 7]))

    def test_it_needs_a_name_and_a_touch_with_something_in_it(self):
        with self.assertRaises(SQ.SequenceError):
            SQ.add(self.folder, "  ")
        with self.assertRaises(SQ.SequenceError):
            SQ.add(self.folder, "x", steps=[])
        with self.assertRaises(SQ.SequenceError):
            SQ.add(self.folder, "x", steps=[SQ.Step(0, "", "")])
        self.assertEqual(SQ.list_sequences(self.folder), [])

    def test_update_replaces_the_touches_and_remove_deletes(self):
        seq = SQ.add(self.folder, "A")
        self.assertTrue(SQ.update(self.folder, seq.id, "B", [SQ.Step(0, "Hi", "x"), SQ.Step(5, "Again", "y")]))
        [back] = SQ.list_sequences(self.folder)
        self.assertEqual((back.name, [s.after_days for s in back.steps]), ("B", [0, 5]))
        self.assertFalse(SQ.update(self.folder, "nope", "C", [SQ.Step(0, "Hi", "")]))
        self.assertTrue(SQ.remove(self.folder, seq.id))
        self.assertEqual(SQ.list_sequences(self.folder), [])

    def test_a_damaged_file_is_forgiven_on_read_and_set_aside_on_write(self):
        with open(os.path.join(self.folder, SQ.FILE), "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(SQ.list_sequences(self.folder), [])
        SQ.add(self.folder, "A")
        self.assertEqual(len(SQ.list_sequences(self.folder)), 1)
        self.assertTrue([n for n in os.listdir(self.folder) if "damaged" in n])


class TheMessage(unittest.TestCase):
    def test_the_persons_details_are_filled_in(self):
        step = SQ.Step(0, "Quick question about {company}", "Hi {first_name}, you are {title}.")
        self.assertEqual(SQ.render(step, Lead(name="Ramesh Patel", company="Patel", title="Owner")),
                         ("Quick question about Patel", "Hi Ramesh, you are Owner."))

    def test_a_missing_detail_never_leaves_braces(self):
        subject, body = SQ.render(SQ.Step(0, "About {company}", "Hi {first_name}"), Lead(name="", company=""))
        self.assertEqual((subject, body), ("About your company", "Hi there"))


class TheStanding(unittest.TestCase):
    def setUp(self):
        self.seq = SQ.Sequence("s", "3-touch", SQ.default_steps())

    def test_after_touch_one_the_next_is_due_three_days_on(self):
        e = SQ.standing(_contact(sent=("2026-11-01",)), self.seq, TODAY)
        self.assertEqual((e.done, e.next_due, e.status, e.late_days), (1, date(2026, 11, 4), "Due", 0))

    def test_not_yet_due_is_waiting_and_a_late_one_counts_its_days(self):
        self.assertEqual(SQ.standing(_contact(sent=("2026-11-03",)), self.seq, TODAY).status, "Waiting")
        late = SQ.standing(_contact(sent=("2026-10-28",)), self.seq, TODAY)
        self.assertEqual((late.status, late.late_days), ("Due", 4))

    def test_every_touch_sent_is_finished(self):
        e = SQ.standing(_contact(sent=("2026-10-20", "2026-10-23", "2026-10-27")), self.seq, TODAY)
        self.assertEqual((e.status, e.next_due), ("Finished", None))

    def test_the_stages_that_stop_a_sequence_stop_it(self):
        for stage, why in (("Replied", "replied"), ("Interested", "replied"), ("Do Not Contact", "said stop"),
                           ("Bad Data", "bounced"), ("Unresponsive", "stage changed")):
            e = SQ.standing(_contact(stage=stage), self.seq, TODAY)
            self.assertEqual((e.status, e.next_due), (f"Stopped: {why}", None), stage)

    def test_only_people_added_from_add_to_sequence_are_enrolled(self):
        people = [_contact("In"), _contact("Out", via=("save",))]
        self.assertEqual([e.contact.lead.name for e in SQ.enrolments(people, self.seq, TODAY)], ["In"])


class ThePage(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.page = SP.SequencesPage()
        self.page.set_today(TODAY)
        self.page.set_folder(self.folder)

    def test_it_opens_on_an_empty_state_and_makes_the_default(self):
        self.assertFalse(self.page.empty.isHidden())
        self.assertTrue(self.page.editor_card.isHidden())
        seq = self.page.new_sequence()
        self.assertEqual([s.name for s in SQ.list_sequences(self.folder)], [seq.name])
        self.assertTrue(self.page.empty.isHidden())
        self.assertEqual(len(self.page._editors), 3)

    def test_every_real_button_works_when_clicked(self):
        # Buttons hand their slot a "checked" flag; clicking the real ones is what finds a slot that mistakes it for an argument.
        self.page.new_btn.click()
        self.assertEqual(len(SQ.list_sequences(self.folder)), 1)
        self.page.add_step_btn.click()
        self.assertEqual(len(self.page._editors), 4)
        self.page.save_btn.click()                                  # the new touch is empty: refused, with the reason shown
        self.assertEqual(len(SQ.list_sequences(self.folder)[0].steps), 3)
        self.assertFalse(self.page.status.isHidden())
        self.page._editors[3].subject.setText("One more nudge")
        self.page.save_btn.click()
        self.assertEqual(len(SQ.list_sequences(self.folder)[0].steps), 4)
        with mock.patch.object(self.page, "_confirm_delete", return_value=True):
            self.page.delete_btn.click()
        self.assertEqual(SQ.list_sequences(self.folder), [])

    def test_an_edited_touch_is_saved(self):
        self.page.new_sequence()
        self.page.name_edit.setText("Switchgear")
        self.page._editors[1].days.setValue(4)
        self.page._editors[1].subject.setText("Re: panels")
        self.assertTrue(self.page.save())
        [back] = SQ.list_sequences(self.folder)
        self.assertEqual((back.name, back.steps[1].after_days, back.steps[1].subject), ("Switchgear", 4, "Re: panels"))

    def test_a_refused_save_says_why_and_changes_nothing(self):
        self.page.new_sequence()
        self.page.name_edit.setText(" ")
        self.assertFalse(self.page.save())
        self.assertFalse(self.page.status.isHidden())
        self.assertNotEqual(SQ.list_sequences(self.folder)[0].name, " ")

    def test_touches_are_added_and_removed_but_never_the_last(self):
        self.page.new_sequence()
        self.page.add_step()
        self.assertEqual(len(self.page._editors), 4)
        for _ in range(5):
            self.page._remove_editor(self.page._editors[-1])
        self.assertEqual(len(self.page._editors), 1)
        self.assertFalse(self.page._editors[0].remove_btn.isEnabled())

    def test_delete_asks_first(self):
        self.page.new_sequence()
        with mock.patch.object(self.page, "_confirm_delete", return_value=False):
            self.assertFalse(self.page.delete_sequence())
        self.assertEqual(len(SQ.list_sequences(self.folder)), 1)
        with mock.patch.object(self.page, "_confirm_delete", return_value=True):
            self.assertTrue(self.page.delete_sequence())
        self.assertEqual(SQ.list_sequences(self.folder), [])

    def test_the_people_in_it_are_listed_with_where_they_stand(self):
        self.page.new_sequence()
        self.page.set_contacts([_contact("Vikram Kale", sent=("2026-11-01",)), _contact("Ramesh Patel", stage="Replied")])
        rows = self.page.people.rows()
        self.assertEqual([r.spec.name for r in rows], ["Vikram Kale", "Ramesh Patel"])     # the one that is due first
        self.assertEqual(rows[1].pills[0].text(), "Stopped: replied")
        self.assertIn("2 of 3", rows[0].spec.subline)

    def test_a_redraw_leaves_no_stray_window(self):
        self.page.show()
        self.page.new_sequence()
        for _ in range(3):
            self.page.set_contacts([_contact()])
        tops = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w is not self.page]
        self.assertEqual(tops, [])
        self.page.hide()


class TheDueTouches(unittest.TestCase):
    def test_a_touch_that_fell_due_is_listed(self):
        seq = SQ.Sequence("s", "3-touch", SQ.default_steps())
        c = _contact("Anita Shah", sent=("2026-10-28",))
        [item] = DT.due_items([c], TODAY, touches=SQ.enrolments([c], seq, TODAY))
        self.assertEqual((item.kind, item.pill), ("touch", "Late 4 days"))     # sent 28 Oct, touch 2 due 31 Oct
        self.assertIn("Touch 2 of 3", item.subline)

    def test_a_person_with_a_due_touch_is_not_also_listed_as_gone_quiet(self):
        seq = SQ.Sequence("s", "3-touch", SQ.default_steps())
        c = _contact("Anita Shah", sent=("2026-10-10",))
        c.updated_at = "2026-10-10T10:00:00+05:30"
        items = DT.due_items([c], TODAY, touches=SQ.enrolments([c], seq, TODAY))
        self.assertEqual([i.kind for i in items], ["touch"])

    def test_copy_touch_puts_the_filled_in_draft_on_the_clipboard(self):
        folder = tempfile.mkdtemp()
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        w.set_deals_folder(folder)
        w._sequences.new_sequence()
        c = _contact("Anita Shah", sent=("2020-01-01",))
        w.set_due_contacts([c])
        self.assertEqual(w.due.count(), 1)
        row = w.due.list.rows()[0]
        self.assertEqual([b.text() for b in row.buttons], ["Open", "Copy touch"])
        row.buttons[1].click()
        text = QApplication.clipboard().text()
        self.assertTrue(text.startswith("Subject: Re: Quick question about Kale Panels"))
        self.assertIn("Hi Anita", text)


class TheWorkspace(unittest.TestCase):
    def test_the_sequences_tab_is_the_editor(self):
        w = CK.LeadsWorkspace(leads_folder=tempfile.mkdtemp())
        self.assertIs(w._stack.widget(5), w._sequences)
        self.assertIsInstance(w._sequences, SP.SequencesPage)


if __name__ == "__main__":
    unittest.main()
