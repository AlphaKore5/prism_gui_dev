"""Due today (addons/leads/due_today.py): what needs the owner, read only from the saved contacts. Nothing here sends anything, and every
store is an in-memory object: no real folder, key or network is touched."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication                  # noqa: E402

import core_bridge  # noqa: F401,E402
from prospector.models import Lead                          # noqa: E402
from addons.leads import contacts as CT                     # noqa: E402
from addons.leads import due_today as DT                    # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)
TODAY = date(2026, 11, 3)


def _contact(name, company="Acme", stage="Cold", tasks=(), history=(), notes=(), saved_at="2026-10-01T10:00:00+05:30"):
    c = CT.Contact(lead=Lead(name=name, company=company), saved_at=saved_at, stage=stage)
    c.tasks, c.history, c.notes = list(tasks), list(history), list(notes)
    return c


def _task(text, due, done=False, tid="t1"):
    return {"id": tid, "at": "2026-10-30T09:00:00+05:30", "text": text, "due": due, "done": done}


class WhatIsDue(unittest.TestCase):
    def test_a_late_task_a_task_due_today_and_a_future_one(self):
        items = DT.due_items([_contact("Anita", tasks=[_task("Send the rate list", "2026-10-31")]),
                              _contact("Vikram", tasks=[_task("Call about GST", "2026-11-03")]),
                              _contact("Meera", tasks=[_task("Later", "2026-11-09")])], TODAY)
        self.assertEqual([(i.name, i.pill, i.tone) for i in items], [("Anita", "Late 3 days", "warn"), ("Vikram", "Today", "quiet")])
        self.assertEqual(items[0].subline, "Send the rate list")

    def test_a_finished_task_is_not_due_and_the_most_late_comes_first(self):
        items = DT.due_items([_contact("Done", tasks=[_task("x", "2026-10-01", done=True)]),
                              _contact("A", tasks=[_task("x", "2026-10-30")]),
                              _contact("B", tasks=[_task("x", "2026-10-20")])], TODAY)
        self.assertEqual([i.name for i in items], ["B", "A"])

    def test_someone_marked_replied_with_nothing_done_since_is_due(self):
        replied = _contact("Ramesh", stage="Replied",
                           history=[{"at": "2026-11-02T09:14:00+05:30", "kind": "stage", "text": "Approaching → Replied"}])
        followed = _contact("Jignesh", stage="Replied",
                            history=[{"at": "2026-11-01T09:00:00+05:30", "kind": "stage", "text": "Approaching → Replied"},
                                     {"at": "2026-11-02T10:00:00+05:30", "kind": "call", "text": "Called back"}])
        items = DT.due_items([replied, followed], TODAY)
        self.assertEqual([(i.name, i.kind, i.pill) for i in items], [("Ramesh", "replied", "Replied")])
        self.assertIn("02 Nov", items[0].subline)

    def test_an_active_contact_with_nothing_for_a_week_has_gone_quiet(self):
        quiet = _contact("Kale", stage="Approaching", saved_at="2026-10-20T10:00:00+05:30")
        fresh = _contact("Fresh", stage="Approaching", saved_at="2026-11-01T10:00:00+05:30")
        cold = _contact("Cold", stage="Cold", saved_at="2026-09-01T10:00:00+05:30")             # silence in Cold is not news
        busy = _contact("Busy", stage="Interested", saved_at="2026-10-01T10:00:00+05:30", tasks=[_task("Follow up", "2026-11-20")])
        items = DT.due_items([quiet, fresh, cold, busy], TODAY)
        self.assertEqual([(i.name, i.kind, i.pill) for i in items], [("Kale", "quiet", "Quiet 14d")])

    def test_the_order_is_late_tasks_then_replies_then_the_quiet(self):
        items = DT.due_items([_contact("Quiet", stage="Interested", saved_at="2026-10-01T10:00:00+05:30"),
                              _contact("Reply", stage="Replied", history=[{"at": "2026-11-02T09:00:00+05:30", "kind": "stage", "text": "Cold → Replied"}]),
                              _contact("Late", tasks=[_task("x", "2026-10-30")])], TODAY)
        self.assertEqual([i.kind for i in items], ["task", "replied", "quiet"])

    def test_nobody_saved_means_nothing_is_due(self):
        self.assertEqual(DT.due_items([], TODAY), [])


class ThePage(unittest.TestCase):
    def setUp(self):
        self.page = DT.DueTodayPage()
        self.page.resize(900, 600)
        self.contacts = [_contact("Anita", "Shah Automation", tasks=[_task("Send the rate list", "2026-10-31")]),
                         _contact("Kale", "Kale Panels", stage="Approaching", saved_at="2026-10-20T10:00:00+05:30")]

    def test_it_opens_empty_and_says_so(self):
        self.assertEqual(self.page.count(), 0)
        self.assertFalse(self.page.empty.isHidden())
        self.assertTrue(self.page.list.isHidden())

    def test_it_lists_what_is_due_and_says_nothing_sends_by_itself(self):
        self.page.set_contacts(self.contacts, TODAY)
        self.assertEqual(self.page.count(), 2)
        self.assertTrue(self.page.empty.isHidden())
        self.assertIn("2 things need you", self.page.summary.text())
        self.assertIn("Nothing here sends by itself", self.page.summary.text())
        rows = self.page.list.rows()
        self.assertEqual(rows[0].name.full_text(), "Anita")
        self.assertFalse(rows[0].check.isVisibleTo(self.page))           # no tick box: nobody bulk-acts here

    def test_open_opens_the_person_and_done_ticks_the_task_off(self):
        opened, done = [], []
        self.page.openRequested.connect(opened.append)
        self.page.taskDoneRequested.connect(lambda *a: done.append(a))
        self.page.set_contacts(self.contacts, TODAY)
        rows = self.page.list.rows()
        self.assertEqual([b.text() for b in rows[0].buttons], ["Open", "Done"])      # a task can be finished here
        self.assertEqual([b.text() for b in rows[1].buttons], ["Open"])              # someone gone quiet cannot
        rows[0].buttons[0].click()
        rows[0].buttons[1].click()
        self.assertEqual(opened[0].name, "Anita")
        self.assertEqual((done[0][0].name, done[0][1], done[0][2]), ("Anita", "t1", True))


if __name__ == "__main__":
    unittest.main()
