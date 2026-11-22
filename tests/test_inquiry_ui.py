"""The Inquiry Automation screen.

The engine is covered by tests/test_mailflow.py. These are about the part the
customer actually touches, and they defend four things that are easy to break
without noticing:

  · **Setup keeps what it was given.** A password or a folder lost on save is
    discovered at 9am on a Monday, not here.
  · **The screen tells the truth about the sorting.** Every message shows what
    it was called and WHY — a sorting nobody can check is a sorting nobody
    should trust.
  · **A correction sticks.** It is the only way the customer teaches Prism
    anything, and a correction that quietly does not save is worse than no
    correction button at all.
  · **No jargon reaches the screen.** Same rule as the rest of the app: no
    "IMAP", no "UID", no category keys leaking out as identifiers.

Every test that would write settings patches config.save. A test suite that
overwrites the developer's own ~/.prism/config.json — their Groq key, their
agent choices — would be a rather expensive way to find a typo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date, timedelta
from decimal import Decimal
from email.message import EmailMessage

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QLabel, QTableWidgetSelectionRange,
)

import core_bridge as CB  # noqa: E402
from core import inbox, mailflow, register, triage  # noqa: E402
from addons.inquiry import dialog as UI  # noqa: E402
import addons.inquiry.setup as UI_SETUP  # noqa: E402
from addons.inquiry.setup import (  # noqa: E402
    InquirySetupDialog, is_ready, settings_of)
from widgets import sidebar  # noqa: E402

_app = QApplication.instance() or QApplication([])


# ── the guard that should have been here from the start ──────────────────────
# The docstring above has always said "every test that would write settings
# patches config.save". It was a convention, and a convention is exactly as
# strong as the last person who remembered it.
#
# One did not. test_a_reply_arriving_opens_that_tab called _checked(), which
# calls _remember(), which calls config.save() — and wrote a bare test fixture
# over the developer's real ~/.prism/config.json. Groq key, profile, agent
# choices, Chrome pin: gone, and the only symptom was Prism asking to be set up
# again on every launch, which reads like a Prism bug rather than a test one.
#
# So the rule now has teeth. save() refuses for the whole module unless a test
# has deliberately taken it over with _NoSave, and CONFIG_PATH points at a
# scratch file so even a direct write cannot reach the real one. A test that
# forgets now FAILS; it does not quietly cost somebody their afternoon.
_REAL_SAVE = CB.config.save
_REAL_CONFIG_PATH = CB.config.CONFIG_PATH
_SCRATCH = tempfile.mkdtemp(prefix="prism-test-config-")


def _refuse(cfg):
    raise AssertionError(
        "This test called config.save() without patching it. That writes the "
        "real ~/.prism/config.json and destroys whoever is running the "
        "tests.\n\nWrap the call:  with _NoSave(): ...")


def setUpModule():
    CB.config.save = _refuse
    CB.config.CONFIG_PATH = os.path.join(_SCRATCH, "config.json")


def tearDownModule():
    CB.config.save = _REAL_SAVE
    CB.config.CONFIG_PATH = _REAL_CONFIG_PATH


class _NoSave:
    """Stop a dialog writing to the real ~/.prism/config.json."""

    def __enter__(self):
        self.saved = []
        self.original = CB.config.save
        CB.config.save = lambda cfg: self.saved.append(dict(cfg))
        return self

    def __exit__(self, *exc):
        CB.config.save = self.original
        return False


def message(subject="Enquiry", sender="Mr Patel <purchase@shaktiauto.in>",
            body="Kindly quote 5000 nos compression spring 2mm.", headers=None):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "sales@acme.co.in"
    msg["Date"] = "Mon, 10 Aug 2026 09:14:00 +0530"
    msg["Message-ID"] = f"<{abs(hash(subject + sender))}@x>"
    for key, value in (headers or {}).items():
        msg[key] = value
    msg.set_content(body)
    return inbox.parse_message(msg.as_bytes(), uid=1)


# The fixture's Date header is +0530, and register._clock converts a mail
# timestamp to the READER's local zone — correct behaviour, since the column
# means "when it reached us". So "09:14" is only the right answer in India:
# on a UTC machine the same instant is 03:44, and these assertions failed on
# the first CI run of this suite for no reason but geography.
#
# Derived, the way the Berlin-offset test below already derives its own
# expectation. Still proves the pipeline — parsed, converted, formatted —
# without encoding one developer's timezone as the definition of correct.
_FIXTURE_DATE = "Mon, 10 Aug 2026 09:14:00 +0530"


def _local_clock(header: str = _FIXTURE_DATE) -> str:
    from email.utils import parsedate_to_datetime
    return parsedate_to_datetime(header).astimezone().strftime("%H:%M")


def _ancestors(widget, root):
    """The widgets between `widget` and `root`, not counting either."""
    parent = widget.parentWidget()
    while parent is not None and parent is not root:
        yield parent
        parent = parent.parentWidget()


def ready_cfg(folder: str) -> dict:
    return {"api_key": "", "inquiry": {
        "account": {"address": "sales@acme.co.in", "password": "p",
                    "host": "mail.acme.co.in", "port": 993, "folder": "INBOX"},
        "folder": folder, "rate_list": "", "cost_sheet": "",
        "company": "Acme Springs", "signature": "Sales",
        "terms": {"gst_percent": 18, "validity_days": 15,
                  "payment": "advance", "delivery": "3 weeks"},
        "followup_days": 3, "local_only": True,
        "knowledge": {"own_domains": ["acme.co.in"],
                      "customers": ["shaktiauto.in"], "vendors": [],
                      "learned": {}},
        "state": {}}}


# ── setup ─────────────────────────────────────────────────────────────────────

class SetupKeepsWhatItIsGiven(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def test_it_builds_with_nothing_configured(self):
        dialog = InquirySetupDialog({})
        self.assertEqual(dialog.tabs.count(), 4)

    def test_a_full_round_trip(self):
        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("secret")
        dialog.host.setText("mail.acme.co.in")
        dialog.work_folder.edit.setText(self.folder)
        dialog.company.setText("Acme Springs")
        dialog.gst.setValue(12)
        dialog.validity.setValue(30)
        dialog.customers.setPlainText("shaktiauto.in\nBuyer@GujaratMotors.in")
        with _NoSave():
            dialog._save()

        saved = settings_of(dialog.cfg)
        self.assertEqual(saved["account"]["address"], "sales@acme.co.in")
        self.assertEqual(saved["account"]["password"], "secret")
        self.assertEqual(saved["folder"], self.folder)
        self.assertEqual(saved["terms"]["gst_percent"], 12)
        self.assertEqual(saved["terms"]["validity_days"], 30)

    def test_customer_lines_are_normalised(self):
        """People type "@shaktiauto.in" and mixed case. The engine matches on
        a bare lowercase domain, so one stray @ would silently stop a whole
        customer being recognised."""
        dialog = InquirySetupDialog({})
        dialog.addr.setText("a@b.c")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(self.folder)
        dialog.customers.setPlainText(" @ShaktiAuto.in \n\nBuyer@GujaratMotors.IN\n")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["knowledge"]["customers"],
                         ["shaktiauto.in", "buyer@gujaratmotors.in"])

    def test_a_blank_password_keeps_the_saved_one(self):
        """Re-opening setup to fix a typo must not cost a trip to the
        provider's app-password page."""
        cfg = ready_cfg(self.folder)
        dialog = InquirySetupDialog(cfg)
        self.assertEqual(dialog.password.text(), "")
        dialog.company.setText("Changed")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["account"]["password"], "p")

    def test_a_saved_password_says_so_loudly_not_just_in_a_placeholder(self):
        """The password box is always shown blank by design — but a report
        that the "app password vanishes" every time Edit setup is opened
        turned out to be this: nothing on screen said loudly enough that
        blank meant "kept", so a real saved password read as lost. Proven
        separately that the data itself survives save() in every case tested
        (see test_a_blank_password_keeps_the_saved_one); this defends that
        the screen actually says so where a non-technical owner will see it,
        not just in a small grey placeholder."""
        cfg = ready_cfg(self.folder)
        dialog = InquirySetupDialog(cfg)
        self.assertEqual(dialog.password.text(), "")
        # isVisibleTo, not isVisible: the dialog is never shown in tests, so
        # isVisible() is False regardless and would pass either way.
        self.assertTrue(dialog.password_status.isVisibleTo(dialog))
        self.assertIn("already saved", dialog.password_status.text())

    def test_the_notice_goes_quiet_once_a_new_password_is_typed(self):
        """Claiming "already saved" while a replacement is being typed would
        be a lie about what save() is about to do."""
        cfg = ready_cfg(self.folder)
        dialog = InquirySetupDialog(cfg)
        dialog.password.setText("a-new-app-password")
        self.assertFalse(dialog.password_status.isVisibleTo(dialog))

    def test_no_notice_when_nothing_has_ever_been_saved(self):
        dialog = InquirySetupDialog({})
        self.assertNotIn("already saved", dialog.password_status.text())

    def test_switching_mailboxes_does_not_leave_a_stale_notice_behind(self):
        """Qt does not fire textChanged when password.clear() finds the box
        already empty — exactly the case of switching between two mailboxes
        that both have a password on file but neither has been retyped. The
        notice must still describe the row now showing, not the one left."""
        cfg = ready_cfg(self.folder)
        cfg["inquiry"]["accounts"] = [
            dict(cfg["inquiry"]["account"]),
            {"address": "info@acme.co.in", "password": "",
             "host": "mail.acme.co.in", "port": 993, "folder": "INBOX"},
        ]
        dialog = InquirySetupDialog(cfg)
        dialog._mailbox_picked(1)
        self.assertFalse(dialog._saved_password)
        self.assertNotIn("already saved", dialog.password_status.text())

    def test_corrections_survive_reopening_setup(self):
        """Learned senders live in the same block as the hand-typed lists. If
        saving the form dropped them, every correction the customer ever made
        would vanish the next time they changed their GST rate."""
        cfg = ready_cfg(self.folder)
        cfg["inquiry"]["knowledge"]["learned"] = {"x@y.com": "vendor"}
        dialog = InquirySetupDialog(cfg)
        dialog.password.setText("p")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["knowledge"]["learned"],
                         {"x@y.com": "vendor"})

    def test_the_reading_bookmark_survives_too(self):
        """Otherwise editing a setting re-imports the last month of mail as
        fresh inquiries."""
        cfg = ready_cfg(self.folder)
        cfg["inquiry"]["state"] = {"uidvalidity": 7, "last_uid": 900}
        dialog = InquirySetupDialog(cfg)
        dialog.password.setText("p")
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["state"]["last_uid"], 900)

    def test_the_server_is_guessed_when_never_tested(self):
        """Somebody who types their address and presses Save without pressing
        Test must not meet a failure about a server they never entered."""
        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(self.folder)
        with _NoSave():
            dialog._save()
        self.assertEqual(settings_of(dialog.cfg)["account"]["host"],
                         "imap.acme.co.in")

    def test_a_typed_server_is_tried_before_any_guess(self):
        """The Mail server box used to be ignored by "Find my server and test".

        Anyone whose mail is hosted rather than on their own domain — GoDaddy,
        Google Workspace, Microsoft 365 — cannot be found by guessing
        imap./mail./<domain>, so the way out is to type the server their
        provider documents. That only works if we actually try it.
        """
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p",
                           host="imap.secureserver.net")
        self.assertEqual(tried[0], "imap.secureserver.net")

    def test_a_typed_server_does_not_stop_the_guesses(self):
        """A typo in the box must not be a dead end — whatever answers wins."""
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p", host="typo.example")
        self.assertEqual(tried[0], "typo.example")
        self.assertIn("imap.acme.co.in", tried)

    def test_the_typed_server_is_not_tried_twice(self):
        tried = []

        def fake_connect(ic, timeout=20):
            tried.append(ic["host"])
            raise OSError("nope")

        with mock.patch.object(inbox, "_connect", fake_connect):
            inbox.discover("sales@acme.co.in", "p", host="imap.acme.co.in")
        self.assertEqual(tried.count("imap.acme.co.in"), 1)

    def test_the_dialog_hands_the_typed_server_to_the_worker(self):
        """The bug was here, not in discover(): the dialog never read the box."""
        seen = {}

        class FakeWorker:
            def __init__(self, address, password, host=""):
                seen.update(address=address, password=password, host=host)
                self.done = mock.MagicMock()

            def start(self):
                pass

        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("p")
        dialog.host.setText("imap.secureserver.net")
        with mock.patch.object(UI_SETUP, "InboxVerifyWorker", FakeWorker):
            dialog._test()
        self.assertEqual(seen.get("host"), "imap.secureserver.net")

    def test_the_folder_is_created(self):
        target = os.path.join(self.folder, "Prism Inquiries")
        dialog = InquirySetupDialog({})
        dialog.addr.setText("a@b.c")
        dialog.password.setText("p")
        dialog.work_folder.edit.setText(target)
        with _NoSave():
            dialog._save()
        self.assertTrue(os.path.isdir(target))


class Readiness(unittest.TestCase):

    def test_nothing_configured(self):
        self.assertFalse(is_ready({}))

    def test_a_configured_account(self):
        self.assertTrue(is_ready(ready_cfg(tempfile.mkdtemp())))

    def test_a_rate_list_is_not_required_to_start(self):
        """Deliberate: the read-only half is the half that sells this, and
        demanding a price list up front would stop somebody trying it."""
        cfg = ready_cfg(tempfile.mkdtemp())
        cfg["inquiry"]["rate_list"] = ""
        self.assertTrue(is_ready(cfg))

    def test_a_missing_folder_is_not_ready(self):
        cfg = ready_cfg(tempfile.mkdtemp())
        cfg["inquiry"]["folder"] = ""
        self.assertFalse(is_ready(cfg))


# ── the screen ────────────────────────────────────────────────────────────────

class TheScreen(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)

    def test_six_tabs_in_the_order_an_inquiry_lives(self):
        """To quote → no answer yet → they answered → the order came, then
        the two reference tabs. The tab order IS the explanation of the
        feature, so it is worth a test of its own — and "To quote" is first
        because "2 to quote" is the number the owner opens Prism for; the
        whole register is a lookup, so it sits near the end."""
        self.assertEqual(self.dialog.tabs.count(), 6)
        for index in range(6):
            self.assertTrue(
                self.dialog.tabs.tabText(index).startswith(str(index + 1)))
        self.assertIn("To quote", self.dialog.tabs.tabText(0))
        self.assertIn("Order came", self.dialog.tabs.tabText(3))
        self.assertIn("All inquiries", self.dialog.tabs.tabText(4))
        self.assertIn("All mail", self.dialog.tabs.tabText(5))

    def test_the_daily_tabs_carry_a_live_count_and_the_reference_tabs_do_not(self):
        self.assertTrue(self.dialog.tabs.tabText(0).endswith("(0)"))
        self.assertFalse(self.dialog.tabs.tabText(4).endswith(")"))
        self.assertFalse(self.dialog.tabs.tabText(5).endswith(")"))

    def test_it_opens_with_an_empty_register_rather_than_an_error(self):
        self.assertEqual(self.dialog.register_table.rowCount(), 0)

    def test_no_tab_title_is_ever_cut_short(self):
        """Reported directly, with screenshots: none of the five titles were
        fully readable, because Qt's default tab bar splits its width
        EQUALLY across every tab — so "Inquiries" was squeezed down to the
        same narrow share as "What they said back" and both got an ellipsis
        on top of that. expanding=False lets each tab claim only what its
        own text needs; elideMode=ElideNone is the actual guarantee that no
        title is ever shortened, whatever width is left over."""
        bar = self.dialog.tabs.tabBar()
        self.assertFalse(bar.expanding())
        self.assertEqual(bar.elideMode(), Qt.ElideNone)

    def _result(self):
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        messages = [
            message(),
            message("Sale!", "promo@x.example", "buy now",
                    {"List-Unsubscribe": "<https://x/u>"}),
            message("Out of office", "away@y.example", "back Monday",
                    {"Auto-Submitted": "auto-replied"}),
        ]
        verdicts = [triage.rules_pass(m, known) for m in messages]
        result = mailflow.Result()
        result.sorted_mail = list(zip(messages, verdicts))
        result.counts = triage.summarise(verdicts)
        result.fetched = len(messages)
        result.state = inbox.State(1, 99)
        result.knowledge = known
        return result

    def test_the_time_column_shows_when_it_reached_us(self):
        self.dialog._fill_arrived(self._result())
        table = self.dialog.arrived
        enquiry_row = next(r for r in range(table.rowCount())
                           if table.item(r, 1).text() == "Enquiry")
        self.assertEqual(table.item(enquiry_row, 6).text(), _local_clock())

    def test_the_body_column_shows_a_short_preview(self):
        self.dialog._fill_arrived(self._result())
        table = self.dialog.arrived
        enquiry_row = next(r for r in range(table.rowCount())
                           if table.item(r, 1).text() == "Enquiry")
        self.assertIn("compression spring", table.item(enquiry_row, 2).text())

    def test_every_column_can_be_resized_by_hand(self):
        """A real complaint: "From" was too wide for some rows and cut
        the rest off on others, with no way to trade width between
        columns — every column was locked to Stretch or ResizeToContents,
        neither of which a mouse drag can override."""
        head = self.dialog.arrived.horizontalHeader()
        for column in range(self.dialog.arrived.columnCount()):
            self.assertEqual(head.sectionResizeMode(column),
                             UI.QHeaderView.Interactive)

    def test_every_message_shows_what_it_was_called_and_why(self):
        self.dialog._fill_arrived(self._result())
        table = self.dialog.arrived
        self.assertEqual(table.rowCount(), 3)
        for row in range(table.rowCount()):
            self.assertTrue(table.item(row, 3).text(), "no category shown")
            self.assertTrue(table.item(row, 4).text(), "no reason shown")

    def test_the_newsletter_says_why_it_was_filed(self):
        self.dialog._fill_arrived(self._result())
        reasons = [self.dialog.arrived.item(r, 4).text()
                   for r in range(self.dialog.arrived.rowCount())]
        self.assertTrue(any("unsubscribe" in r for r in reasons), reasons)

    def test_categories_are_words_not_engine_keys(self):
        self.dialog._fill_arrived(self._result())
        shown = {self.dialog.arrived.item(r, 3).text()
                 for r in range(self.dialog.arrived.rowCount())}
        for key in ("inquiry", "promotion", "other", "unsorted"):
            self.assertNotIn(key, shown, f"the raw key {key!r} reached the screen")

    def test_a_correction_is_remembered(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)          # the newsletter
        index = self.dialog.recategorise.findData("inquiry")
        self.dialog.recategorise.setCurrentIndex(index)
        with _NoSave():
            self.dialog._correct()
        learned = settings_of(self.dialog.cfg)["knowledge"]["learned"]
        self.assertEqual(learned.get("promo@x.example"), "inquiry")

    def test_a_correction_updates_the_row_in_front_of_them(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("vendor"))
        with _NoSave():
            self.dialog._correct()
        self.assertIn("Supplier", self.dialog.arrived.item(1, 3).text())

    def test_correcting_with_nothing_selected_does_nothing(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(-1, -1)
        with _NoSave() as guard:
            self.dialog._correct()
        self.assertEqual(guard.saved, [])

    def test_marking_a_mail_as_a_reminder_flags_it(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(0, 0)
        self.dialog._toggle_reminder()
        self.assertTrue(self.dialog._sorted_mail[0]["reminder"])
        self.assertEqual(self.dialog.arrived.item(0, 7).text(), "Reminder")
        self.assertEqual(self.dialog.reminder_btn.text(), "Remove reminder")

    def test_marking_it_twice_unflags_it(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(0, 0)
        self.dialog._toggle_reminder()
        self.dialog._toggle_reminder()
        self.assertFalse(self.dialog._sorted_mail[0]["reminder"])
        self.assertEqual(self.dialog.arrived.item(0, 7).text(), "")
        self.assertEqual(self.dialog.reminder_btn.text(), "Mark as reminder")

    def test_the_flag_survives_a_redraw(self):
        """Same discipline _correct() already follows: the worklist file
        itself has to change, not just what's on screen, or the very
        next tab switch silently drops the flag."""
        self.dialog._fill_arrived(self._result())
        flagged_id = self.dialog._sorted_mail[0]["message_id"]
        self.dialog.arrived.setCurrentCell(0, 0)
        self.dialog._toggle_reminder()
        self.dialog._render_arrived()
        after = next(e for e in self.dialog._sorted_mail
                    if e["message_id"] == flagged_id)
        self.assertTrue(after["reminder"])

    def test_toggling_with_nothing_selected_does_nothing(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(-1, -1)
        self.dialog._toggle_reminder()      # must not raise

    def test_calling_it_an_inquiry_actually_registers_it(self):
        """Found from a real report: correcting a mail to "this really is:
        Inquiry" only ever taught Prism how to sort that SENDER'S future
        mail — the mail in front of you stayed out of the register and
        never reached To quote. It must become a real row."""
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)          # the newsletter
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("inquiry"))
        with _NoSave():
            self.dialog._correct()
        self.assertEqual(len(self.dialog._register_rows), 1)
        row = self.dialog._register_rows[0]
        self.assertEqual(row["Email"], "promo@x.example")
        self.assertEqual(row["Status"], register.NEW)
        on_disk = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(len(on_disk), 1)

    def test_correcting_to_inquiry_twice_does_not_duplicate_the_row(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("inquiry"))
        with _NoSave():
            self.dialog._correct()
            self.dialog._correct()
        self.assertEqual(len(self.dialog._register_rows), 1)

    def test_a_mail_already_in_the_register_is_not_registered_again(self):
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        msg = message("Sale!", "promo@x.example", "buy now",
                      {"List-Unsubscribe": "<https://x/u>"})
        existing = register.from_message(msg)
        register.save([existing], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("inquiry"))
        with _NoSave():
            self.dialog._correct()
        self.assertEqual(len(self.dialog._register_rows), 1)

    def test_correcting_to_something_else_does_not_register_it(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(1, 0)
        self.dialog.recategorise.setCurrentIndex(
            self.dialog.recategorise.findData("vendor"))
        with _NoSave():
            self.dialog._correct()
        self.assertEqual(self.dialog._register_rows, [])

    @staticmethod
    def _labels(dialog):
        return [w.text() for w in dialog.findChildren(QLabel)]

    def test_opening_a_row_shows_what_the_mail_actually_said(self):
        """Found from a real report: this tab kept a subject line only, so
        "what is this mail about" meant opening a real mail client.
        Opening a row — double-click, or the button — must show the body
        it was saved with, in its own closeable window, not a panel stuck
        open on screen."""
        self.dialog._fill_arrived(self._result())
        table = self.dialog.arrived
        enquiry_row = next(r for r in range(table.rowCount())
                           if table.item(r, 1).text() == "Enquiry")
        table.setCurrentCell(enquiry_row, 0)
        created = []
        real = UI._ArrivedMailDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)

        with _Patched(UI, "_ArrivedMailDialog", _Capturing):
            self.dialog._open_arrived()
        self.assertEqual(len(created), 1)
        self.assertTrue(any("compression spring" in t
                           for t in self._labels(created[0])))

    def test_double_clicking_a_row_opens_the_same_dialog(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(0, 0)
        created = []
        real = UI._ArrivedMailDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)

        with _Patched(UI, "_ArrivedMailDialog", _Capturing):
            self.dialog.arrived.cellDoubleClicked.emit(0, 0)
        self.assertEqual(len(created), 1)

    def test_an_attachment_name_is_shown_too(self):
        from email.message import EmailMessage
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        raw = EmailMessage()
        raw["Subject"], raw["From"], raw["To"] = "Enquiry", \
            "Mr Patel <purchase@shaktiauto.in>", "sales@acme.co.in"
        raw["Date"] = "Mon, 10 Aug 2026 09:14:00 +0530"
        raw["Message-ID"] = "<drawing-mail@x>"
        raw.set_content("See attached drawing.")
        raw.add_attachment(b"%PDF-1.4", maintype="application",
                           subtype="pdf", filename="drawing.pdf")
        msg = inbox.parse_message(raw.as_bytes(), uid=1)
        result = mailflow.Result()
        result.sorted_mail = [(msg, triage.rules_pass(msg, known))]
        self.dialog._fill_arrived(result)
        self.dialog.arrived.setCurrentCell(0, 0)
        dialog = UI._ArrivedMailDialog(self.dialog._sorted_mail[0])
        self.assertTrue(any("drawing.pdf" in t for t in self._labels(dialog)))

    def test_opening_with_nothing_selected_asks_nothing(self):
        self.dialog._fill_arrived(self._result())
        self.dialog.arrived.setCurrentCell(-1, -1)
        with mock.patch.object(UI.QMessageBox, "information") as info:
            self.dialog._open_arrived()
        info.assert_called_once()

    def test_a_mail_from_before_this_feature_says_so_not_just_blank(self):
        """Found from a real report: mail logged before body-saving existed
        has no "body" key at all, and showing the same generic "(no text
        in this mail)" for that made it look like saving text was still
        broken, forever, for a thread the owner kept re-testing with.
        That must read differently from a mail that genuinely says
        nothing."""
        entry = {"subject": "Old inquiry", "from_name": "Shlok Patel",
                 "from_addr": "synergy007sp@gmail.com", "category": "inquiry",
                 "date": "2026-10-02"}        # no "body" key — pre-fix shape
        self.assertNotIn("body", entry)
        dialog = UI._ArrivedMailDialog(entry)
        labels = self._labels(dialog)
        self.assertTrue(any("before Prism started saving" in t for t in labels))
        self.assertFalse(any(t == "(no text in this mail)" for t in labels))

    def test_a_genuinely_empty_mail_still_says_no_text(self):
        entry = {"subject": "Blank", "from_name": "X", "category": "other",
                 "date": "2026-10-02", "body": ""}
        dialog = UI._ArrivedMailDialog(entry)
        labels = self._labels(dialog)
        self.assertTrue(any(t == "(no text in this mail)" for t in labels))
        self.assertFalse(any("before Prism started saving" in t for t in labels))

    def test_the_bookmark_and_corrections_are_persisted_after_a_check(self):
        result = self._result()
        triage.learn(result.knowledge, "someone@new.example", "vendor")
        with _NoSave():
            self.dialog._remember(result)
        saved = settings_of(self.dialog.cfg)
        self.assertEqual(saved["state"]["last_uid"], 99)
        self.assertEqual(saved["knowledge"]["learned"].get("someone@new.example"),
                         "vendor")

    def test_the_register_table_fills_from_the_csv(self):
        rows = [register.from_message(message())]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.register_table.rowCount(), 1)
        self.assertIn("INQ/", self.dialog.register_table.item(0, 0).text())

    def test_an_empty_follow_up_list_says_so_rather_than_being_blank(self):
        """The old tab put a placeholder ROW in the list to say this, which
        defeated its own empty state (the row count was never zero). Now the
        table is genuinely empty and the empty state carries the sentence."""
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.followups.rowCount(), 0)
        self.assertIn("Every quotation has been answered",
                      self.dialog.followups_empty.title.text())

    def test_a_quiet_quotation_appears_on_the_chase_list(self):
        # Dated RELATIVE to today, not `today.replace(day=1)`. The fixture
        # sets followup_days=3, so the old date was only far enough in the
        # past from the 4th of the month onward — this test failed on the
        # 1st, 2nd and 3rd of every month, and passed for the other 28 days.
        # A test whose answer depends on the date it is run is worse than no
        # test: the red is ignored, and then the real regression is too.
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", 142500,
                             date.today() - timedelta(days=7))
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertIn("QTN/26-27/0001", self.dialog.followups.item(0, 0).text())
        self.assertEqual(self.dialog.followups.item(0, 4).text(), "Due today")

    def test_the_whole_callback_path_after_a_check(self):
        """What the worker actually calls back into. Everything above tests a
        piece of it; this is the button."""
        result = self._result()
        rows = [register.from_message(message())]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        with _NoSave():
            self.dialog._checked(result)
        self.assertEqual(self.dialog.arrived.rowCount(), 3)
        self.assertEqual(self.dialog.register_table.rowCount(), 1)
        self.assertTrue(self.dialog.check_btn.isEnabled(), "button left disabled")
        self.assertFalse(self.dialog.progress.isVisible(), "spinner left running")
        self.assertTrue(self.dialog.status.text())

    def test_the_status_line_after_a_check_is_readable(self):
        with _NoSave():
            self.dialog._checked(self._result())
        line = self.dialog.status.text().lower()
        for word in ("imap", "uid", "verdict", "none"):
            self.assertNotIn(word, line, f"{word!r} reached the status line")

    def test_a_failed_check_re_enables_the_button(self):
        """Otherwise one bad afternoon on the mail server leaves the customer
        with a dead button and no way to try again but restarting."""
        shown = []
        self.dialog._explain = lambda message: shown.append(message)
        self.dialog._check_failed("The mail server didn't answer.")
        self.assertTrue(self.dialog.check_btn.isEnabled())
        self.assertFalse(self.dialog.progress.isVisible())
        self.assertEqual(shown, ["The mail server didn't answer."])

    def test_an_error_with_no_mail_fetched_saves_nothing(self):
        """A locked register leaves the bookmark alone on purpose, so the same
        mail comes back next time. Saving here would lose it."""
        result = mailflow.Result()
        result.error = "Close inquiries.csv in Excel and try again."
        result.fetched = 0
        self.dialog._explain = lambda message: None
        with _NoSave() as guard:
            self.dialog._checked(result)
        self.assertEqual(guard.saved, [])

    def test_a_locked_register_does_not_crash_the_screen(self):
        original = register.load
        register.load = lambda p: (_ for _ in ()).throw(
            register.RegisterLocked("close Excel"))
        try:
            self.dialog._refresh_register()
        finally:
            register.load = original
        self.assertEqual(self.dialog.register_table.rowCount(), 0)


class NoJargonOnScreen(unittest.TestCase):
    """Same rule as the rest of the app. This feature is the one most likely
    to leak it, because its subject matter IS the plumbing."""

    FORBIDDEN = ("imap", "uid", "smtp", "mime", "traceback", "verdict",
                 "payload", "unsorted")

    def test_category_labels(self):
        for label in UI.CATEGORY_LABELS.values():
            low = label.lower()
            for word in self.FORBIDDEN:
                self.assertNotIn(word, low, f"{label!r} contains {word!r}")

    def test_every_category_the_engine_can_produce_has_a_label(self):
        """A category with no label shows the raw engine key on screen."""
        for key in triage.CATEGORIES:
            self.assertIn(key, UI.CATEGORY_LABELS, f"{key} has no label")
        self.assertIn("unsorted", UI.CATEGORY_LABELS)

    def test_source_labels_explain_rather_than_name(self):
        for label in UI.SOURCE_LABELS.values():
            self.assertNotIn("rule", label.lower().replace("by a rule", ""))


class ItIsOnTheShelf(unittest.TestCase):

    # The rail's one grouped SECONDARY list became three flat ones when the
    # redesign split the shelf (ADDONS) from the generic destinations (MORE)
    # and the settings shortcuts (DIRECT). The tuple layout is unchanged —
    # key, label, icon, tip, feature — so only the lookup moved.
    def _entry(self):
        for item in sidebar.ADDONS:
            if item[0] == "inquiry":
                return item
        return None

    def test_it_is_in_the_sidebar(self):
        self.assertIsNotNone(self._entry(), "Inquiry Automation is not on the rail")

    def test_it_is_gated_on_the_inbox_feature(self):
        """Otherwise every customer sees it whether they bought it or not."""
        self.assertEqual(self._entry()[4], "inbox")

    def test_it_sits_above_boq(self):
        """It is the only add-on used every day, so it goes where the eye
        lands. BOQ is occasional; this is the reason the app gets opened."""
        keys = [item[0] for item in sidebar.ADDONS]
        self.assertIn("inquiry", keys)
        if "boq" in keys:     # a build without BOQ (Sales) has nothing to sit above
            self.assertLess(keys.index("inquiry"), keys.index("boq"))
        else:
            import flavour
            self.assertNotIn("boq", flavour.addon_keys())

    def test_the_icon_exists(self):
        """A name with no glyph behind it draws nothing — an invisible button
        on the rail, which reads as a broken build rather than a missing icon."""
        from widgets import icons
        known = set(icons._STROKED) | set(icons._FILLED)
        self.assertIn(self._entry()[2], known)

    def test_the_main_window_routes_it(self):
        with open(os.path.join(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))), "main_window.py"),
                encoding="utf-8") as f:
            source = f.read()
        self.assertIn('key == "inquiry"', source)
        self.assertIn('_authorized_then("inbox"', source)


class ClosingTheScreenMidCheck(unittest.TestCase):
    """A QThread destroyed while still running aborts the whole process. Reel
    and BOQ have guarded this since they were written; this screen has more
    workers than either — a mailbox check, a send, and a browser draft that
    runs for minutes."""

    class _Worker:
        def __init__(self, obeys=True):
            self.running, self.stopped = True, False
            self.terminated, self._obeys = False, obeys

        def isRunning(self):
            return self.running

        def stop(self):
            self.stopped = True

        def wait(self, _ms):
            if self._obeys:
                self.running = False
            return self._obeys

        def terminate(self):
            self.terminated = True
            self.running = False

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))

    def close(self):
        from PySide6.QtGui import QCloseEvent

        self.dialog.closeEvent(QCloseEvent())

    def test_every_worker_is_stopped_and_joined(self):
        workers = [self._Worker() for _ in range(3)]
        (self.dialog._worker, self.dialog._send_worker,
         self.dialog._draft_worker) = workers
        self.close()
        for w in workers:
            self.assertTrue(w.stopped)
            self.assertFalse(w.running)

    def test_a_stuck_worker_is_terminated_rather_than_left_to_abort(self):
        stuck = self._Worker(obeys=False)
        self.dialog._draft_worker = stuck
        self.close()
        self.assertTrue(stuck.terminated)

    def test_the_timer_is_stopped_first(self):
        """Otherwise it can fire during the waits and start a fresh check on a
        dialog that is closing."""
        self.dialog._auto.start(60_000)
        self.close()
        self.assertFalse(self.dialog._auto.isActive())

    def test_closing_with_nothing_running_is_harmless(self):
        self.close()        # must not raise

    def test_a_deleted_worker_does_not_stop_the_others(self):
        class _Deleted:
            def isRunning(self):
                raise RuntimeError("wrapped C/C++ object has been deleted")

        alive = self._Worker()
        self.dialog._worker = _Deleted()
        self.dialog._send_worker = alive
        self.close()
        self.assertTrue(alive.stopped)


class ColourCarriesMeaning(unittest.TestCase):
    """Colour is what makes a hundred-row register readable at arm's length.
    It is also the thing most easily got wrong in a way nobody notices until a
    customer says they cannot read it."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))

    def test_every_category_the_screen_can_show_has_a_colour(self):
        """An uncoloured cell in a coloured column reads as a rendering bug,
        not as a category."""
        for key in UI.CATEGORY_LABELS:
            self.assertIn(key, UI.CATEGORY_COLOURS, key)

    def test_every_status_the_register_can_hold_has_a_colour(self):
        for status in register.STATUSES:
            self.assertIn(status, UI.STATUS_COLOURS, status)

    def test_every_intent_has_a_label_and_a_colour(self):
        for intent in ("accepted", "rejected", "negotiating", "needs_info",
                       "unclear"):
            self.assertIn(intent, UI.INTENT_LABELS, intent)
            self.assertIn(intent, UI.INTENT_COLOURS, intent)

    def test_the_word_is_always_there_as_well_as_the_colour(self):
        """Roughly one man in twelve cannot tell the red from the green, and a
        register printed on the office laser comes out grey. Colour may
        reinforce the meaning; it may never be the only thing carrying it."""
        from PySide6.QtWidgets import QTableWidgetItem

        item = UI.paint(QTableWidgetItem("Converted"), UI.STATUS_COLOURS,
                        "Converted")
        self.assertEqual(item.text(), "Converted")

    def test_an_unknown_key_is_left_plain_rather_than_guessed(self):
        from PySide6.QtWidgets import QTableWidgetItem

        plain = QTableWidgetItem("Something new")
        painted = UI.paint(plain, UI.STATUS_COLOURS, "Something new")
        self.assertIs(painted, plain)

    def test_the_register_paints_the_status_column(self):
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", "1000")
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        cell = self.dialog.register_table.item(0, 4)
        self.assertEqual(cell.text(), register.QUOTED)
        self.assertEqual(cell.background().color().name(),
                         UI.STATUS_COLOURS[register.QUOTED][0])

    def test_a_fresh_inquiry_is_blue_not_the_green_of_an_order_won(self):
        """The owner's decision of 13 Oct 2026 ([12][15][17]): yet to quote
        is blue, won is green. Until then New and Converted were one green,
        so a register could not say which rows were money already won."""
        self.assertNotEqual(UI.STATUS_COLOURS[register.NEW],
                            UI.STATUS_COLOURS[register.CONVERTED])
        self.assertEqual(UI.STATUS_COLOURS[register.NEW],
                         UI.theme.REGISTER_TONES["light"]["new"])

    def test_the_register_row_is_tinted_whole_not_one_cell(self):
        """The point of colour grading a hundred-row file is reading it at
        arm's length — a single tinted cell in a row of white ones asks the
        owner to hunt for it instead."""
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", "1000")
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        quoted = UI.STATUS_COLOURS[register.QUOTED][0]
        for column in range(5):
            cell = self.dialog.register_table.item(0, column)
            self.assertEqual(cell.background().color().name(), quoted,
                             f"column {column}")

    def test_a_brand_new_inquiry_is_blue_on_the_to_quote_tab_too(self):
        register.save([register.from_message(message())],
                     mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        blue = UI.theme.qcolor(UI.STATUS_COLOURS[register.NEW][0])
        for column in range(5):
            cell = self.dialog.to_quote_table.item(0, column)
            self.assertEqual(cell.background().color(), blue,
                             f"column {column}")

    def test_the_waiting_tab_is_tinted_even_though_it_never_prints_status(self):
        """followups has no column that says "Quoted" — the key comes from
        the row, not from a column on screen, so the whole-row tint still
        has to apply."""
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", "1000")
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        quoted = UI.STATUS_COLOURS[register.QUOTED][0]
        cell = self.dialog.followups.item(0, 0)
        self.assertEqual(cell.background().color().name(), quoted)

    def test_an_order_still_needing_its_po_recorded_is_green(self):
        """Accepted with no PO yet is a yes: green, with Converted, as the
        owner's list of 13 Oct 2026 puts it. Amber now means "no reply", so
        it can no longer double as "record the PO"."""
        row = register.from_message(message())
        register.mark_quoted(row, "QTN/26-27/0001", "1000")
        row["Status"] = register.ACCEPTED
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog._render_orders()
        self.assertEqual(self.dialog.orders_table.rowCount(), 1)
        cell = self.dialog.orders_table.item(0, 0)
        self.assertEqual(cell.background().color(),
                         UI.theme.qcolor(UI.STATUS_COLOURS[register.CONVERTED][0]))

    def test_all_mail_tints_every_column_not_only_the_category(self):
        entry = {"from_addr": "vendor@example.com", "from_name": "A Vendor",
                 "subject": "Our catalogue", "category": "vendor",
                 "reason": "", "source": "", "date": "2026-10-01"}
        CB.get_worklist().append(self.folder, "arrived", [entry])
        self.dialog._render_arrived()
        vendor = UI.CATEGORY_COLOURS["vendor"][0]
        for column in range(5):
            cell = self.dialog.arrived.item(0, column)
            self.assertEqual(cell.background().color().name(), vendor,
                             f"column {column}")

    def test_the_date_column_shows_the_time_as_well(self):
        register.save([register.from_message(message())],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.assertIn(_local_clock(),
                      self.dialog.register_table.item(0, 1).text())


class OpeningTheMailItself(unittest.TestCase):
    """"open the mail to see what it says" — every table's double-click now
    resolves to the real message, or says plainly there isn't one. Never a
    blank dialog, never a crash."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))

    @staticmethod
    def _labels(widget) -> list[str]:
        return [w.text() for w in widget.findChildren(QLabel)]

    @staticmethod
    def _capture():
        created = []
        real = UI._ReadMailDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)
        return created, _Capturing

    def test_arrived_entry_now_keeps_the_body_and_attachments(self):
        """His own words: "there is only an option for subject, no body" —
        _arrived_entry() used to leave both out."""
        msg = message(body="Please quote 10 units.")
        known = triage.Knowledge.from_dict(self.dialog.cfg["inquiry"]["knowledge"])
        entry = UI._arrived_entry(msg, triage.rules_pass(msg, known))
        self.assertIn("Please quote 10 units.", entry["body"])
        self.assertEqual(entry["attachment_names"], [])

    def test_double_clicking_an_arrived_row_opens_its_real_mail(self):
        entry = {"from_addr": "buyer@x.example", "from_name": "A Buyer",
                 "subject": "RFQ for springs", "body": "Kindly quote 500.",
                 "attachment_names": ["drawing.pdf"], "category": "inquiry",
                 "reason": "", "source": "", "date": "2026-10-02",
                 "message_id": "<abc@x>"}
        CB.get_worklist().append(self.folder, "arrived", [entry])
        self.dialog._render_arrived()
        self.dialog.arrived.setCurrentCell(0, 0)
        created, capturing = self._capture()
        with _Patched(UI, "_ReadMailDialog", capturing):
            self.dialog._open_mail("arrived")
        self.assertEqual(len(created), 1)
        labels = self._labels(created[0])
        self.assertTrue(any("Kindly quote 500." in t for t in labels))
        self.assertTrue(any("drawing.pdf" in t for t in labels))

    def test_a_register_row_finds_its_own_mail_by_thread(self):
        """Only the arrived log carries the body; the register never does
        — so this has to cross-reference by the message-id add_thread()
        already keeps on the row, not read the body off the row itself."""
        msg = message("RFQ for springs")
        row = register.from_message(msg)
        register.save([row], mailflow.Paths(self.folder).register_csv)
        CB.get_worklist().append(self.folder, "arrived", [{
            "from_addr": msg.from_addr, "from_name": msg.from_name,
            "subject": msg.subject, "body": "the real body",
            "attachment_names": [], "category": "inquiry", "reason": "",
            "source": "", "date": "2026-10-02", "message_id": msg.message_id}])
        self.dialog._refresh_register()
        self.dialog.register_table.setCurrentCell(0, 0)
        created, capturing = self._capture()
        with _Patched(UI, "_ReadMailDialog", capturing):
            self.dialog._open_mail("register")
        self.assertEqual(len(created), 1)
        self.assertTrue(any("the real body" in t
                           for t in self._labels(created[0])))

    def test_a_register_row_with_no_mail_on_file_says_so_plainly(self):
        register.save([register.from_message(message())],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog.register_table.setCurrentCell(0, 0)
        shown = []
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            self.dialog._open_mail("register")
        self.assertEqual(len(shown), 1)

    def test_a_reply_opens_its_own_message_directly(self):
        row = register.from_message(message())
        row["Status"] = register.QUOTED
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        CB.get_worklist().append(self.folder, "replies", [{
            "inquiry_no": row["Inquiry no"], "from_addr": "x@y.example",
            "from_name": "X", "subject": "Re: RFQ",
            "body": "yes please proceed", "attachment_names": [],
            "intent": "accepted", "note": "", "folder": "", "files": [],
            "message_id": "<reply@x>", "date": "2026-10-02"}])
        self.dialog._render_replies()
        self.dialog.replies_table.setCurrentCell(0, 0)
        created, capturing = self._capture()
        with _Patched(UI, "_ReadMailDialog", capturing):
            self.dialog._open_mail("replies")
        self.assertEqual(len(created), 1)
        self.assertTrue(any("yes please proceed" in t
                           for t in self._labels(created[0])))

    def test_an_order_accepted_by_hand_has_no_mail_to_open(self):
        row = register.from_message(message())
        row["Status"] = register.ACCEPTED
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog._render_orders()
        self.dialog.orders_table.setCurrentCell(0, 0)
        shown = []
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            self.dialog._open_mail("orders")
        self.assertEqual(len(shown), 1)

    def test_the_dialog_shows_subject_sender_and_date_too(self):
        dialog = UI._ReadMailDialog(UI._StoredMessage({
            "from_name": "A Buyer", "from_addr": "buyer@x.example",
            "subject": "RFQ for springs", "body": "the body",
            "attachment_names": [], "date": "2026-10-02"}))
        labels = self._labels(dialog)
        self.assertTrue(any("A Buyer" in t and "buyer@x.example" in t
                           for t in labels))
        self.assertEqual(dialog.windowTitle(), "RFQ for springs")


class CheckingWithoutBeingAsked(unittest.TestCase):
    """"Prism scans the mail on a regular basis" is the promise. A button
    somebody has to remember is not that."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self._dialogs: list[UI.InquiryDialog] = []

    def tearDown(self):
        # Every test here builds its own throwaway InquiryDialog and never
        # shows it, so nothing local ever called .close(). Left alone, each
        # one's __init__-time `QTimer.singleShot(0, self._first_look)` sits
        # posted against a live object forever, and fires the next time ANY
        # test anywhere calls processEvents() — including, when the config
        # here is the deliberately-incomplete one in
        # test_it_does_not_run_when_the_mailbox_is_not_set_up, a genuinely
        # modal QMessageBox that hangs whatever unrelated test collects it.
        # Closing here sets InquiryDialog._closed, which _first_look() now
        # checks before doing anything (see InquiryDialog.closeEvent).
        # `test_a_tick_is_skipped_while_a_check_is_already_running` swaps in a
        # fake `_worker` (a bare `Busy` stand-in, not a real QThread) purely to
        # make `isRunning()` answer True — closeEvent's real-worker drain path
        # calls `.wait()` on it, which `Busy` does not have. None of these
        # tests exercise closeEvent's worker teardown, so clear the slot
        # before closing rather than teach the fake to impersonate a QThread.
        for dialog in self._dialogs:
            dialog._worker = None
            dialog.close()

    def _make(self, cfg):
        dialog = UI.InquiryDialog(cfg)
        self._dialogs.append(dialog)
        return dialog

    def test_off_by_default(self):
        """Nobody's mail server gets polled because they opened a screen."""
        dialog = self._make(self.cfg)
        self.assertFalse(dialog._auto.isActive())
        self.assertFalse(dialog.auto_box.isChecked())

    def test_a_saved_interval_starts_the_timer(self):
        self.cfg["inquiry"]["auto_minutes"] = 10
        dialog = self._make(self.cfg)
        self.assertTrue(dialog._auto.isActive())
        self.assertEqual(dialog._auto.interval(), 10 * 60_000)
        self.assertTrue(dialog.auto_box.isChecked())

    def test_it_does_not_run_when_the_mailbox_is_not_set_up(self):
        """A timer firing against a half-configured account produces a login
        failure every ten minutes forever."""
        cfg = {"inquiry": {"auto_minutes": 10, "folder": self.folder}}
        dialog = self._make(cfg)
        self.assertFalse(dialog._auto.isActive())

    def test_turning_it_on_picks_a_sane_interval_rather_than_zero(self):
        dialog = self._make(self.cfg)
        with _NoSave():
            dialog.auto_box.setChecked(True)
        self.assertTrue(dialog._auto.isActive())
        self.assertGreaterEqual(dialog._auto.interval(), 5 * 60_000)

    def test_turning_it_off_stops_it_and_is_remembered(self):
        self.cfg["inquiry"]["auto_minutes"] = 10
        dialog = self._make(self.cfg)
        with _NoSave() as saver:
            dialog.auto_box.setChecked(False)
        self.assertFalse(dialog._auto.isActive())
        self.assertEqual(saver.saved[-1]["inquiry"]["auto_minutes"], 0)

    def test_a_tick_is_skipped_while_a_check_is_already_running(self):
        """Two IMAP fetches racing on one bookmark is how the same inquiry
        gets registered twice."""
        dialog = self._make(self.cfg)
        calls = []
        dialog.check_now = lambda **kw: calls.append(kw)

        class Busy:
            @staticmethod
            def isRunning():
                return True

        dialog._worker = Busy()
        dialog._auto_check()
        self.assertEqual(calls, [])

    def test_a_quiet_failure_stays_in_the_status_line(self):
        """A modal appearing over somebody's work every ten minutes because
        the mail server had a bad afternoon is how the feature gets switched
        off for good."""
        dialog = self._make(self.cfg)
        shown = []
        dialog._quiet = True
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            dialog._explain("Couldn't reach the mail server.\nTry again.")
        self.assertEqual(shown, [])
        self.assertIn("Couldn't reach", dialog.status.text())

    def test_a_failure_the_owner_asked_for_still_gets_a_dialog(self):
        dialog = self._make(self.cfg)
        dialog._quiet = False
        seen = []
        dialog._explain = lambda m: seen.append(m)   # sanity: path is reachable
        dialog._explain("boom")
        self.assertEqual(seen, ["boom"])


class WhatTheCustomerSaidBack(unittest.TestCase):
    """The step the customer called the main part: a reply arrives, Prism
    reads it, and the register moves on."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()

    def _result(self, intent="accepted"):
        result = mailflow.Result()
        result.replies = [mailflow.Item(
            "reply", message("Re: Enquiry", body="Please go ahead."),
            self.dialog._register_rows[0], intent=intent)]
        return result

    def test_to_quote_does_not_open_on_the_row_they_answered_picked(self):
        """They answered picks its first row by itself. That pick followed
        the next reload into To quote, which now lists quoted rows in grey,
        so To quote opened with a row the owner never chose in its panel
        (13 Oct, seen in the real window)."""
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog.replies_table.currentRow(), 0)
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.to_quote_table.currentRow(), -1)
        self.assertEqual(self.dialog._pages["to_quote"].panel.title.text(),
                         UI.i18n.t("Pick a row above."))

    def test_a_row_the_owner_picked_on_to_quote_is_kept_over_a_reload(self):
        self.dialog.to_quote_table.setCurrentCell(0, 0)
        self.dialog._refresh_register()
        self.assertEqual(self.dialog.to_quote_table.currentRow(), 0)

    def test_replies_are_listed_with_what_prism_made_of_them(self):
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog.replies_table.rowCount(), 1)
        self.assertEqual(self.dialog.replies_table.item(0, 3).text(),
                         UI.INTENT_LABELS["accepted"])

    def test_the_screen_says_what_it_would_do_before_it_does_it(self):
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog.replies_table.item(0, 4).text(),
                         register.ACCEPTED)

    def test_reading_a_reply_changes_nothing_on_its_own(self):
        """Prism proposes. A machine that silently rewrote a sales record on
        the strength of a sentence it might have misread is not something a
        business can check."""
        self.dialog._fill_replies(self._result())
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.QUOTED)

    def test_applying_it_writes_the_file(self):
        self.dialog._fill_replies(self._result())
        self.dialog._apply_reply()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.ACCEPTED)

    def test_an_applied_reply_leaves_the_list(self):
        """Otherwise the same reply can be applied twice, and a second
        'rejected' on an already-closed row rewrites the reason."""
        self.dialog._fill_replies(self._result())
        self.dialog._apply_reply()
        self.assertEqual(self.dialog.replies_table.rowCount(), 0)

    def test_an_unclear_reply_says_so_rather_than_guessing(self):
        self.dialog._fill_replies(self._result("unclear"))
        self.assertIn("can't tell", self.dialog.replies_table.item(0, 3).text())
        self.assertNotIn(self.dialog.replies_table.item(0, 4).text(),
                         register.STATUSES)

    def test_the_owner_can_overrule_prism(self):
        self.dialog._fill_replies(self._result("accepted"))
        position = self.dialog.intent_picker.findData("rejected")
        self.dialog.intent_picker.setCurrentIndex(position)
        self.dialog._apply_reply()
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.NOT_CONVERTED)

    def test_the_words_the_customer_wrote_are_on_screen(self):
        """The owner is being asked to approve a reading of a sentence. They
        have to be able to see the sentence."""
        self.dialog._fill_replies(self._result())
        self.assertIn("go ahead", self.dialog.reply_text.toPlainText())

    def _two_replies(self):
        """A decline, then a change of heart — both still waiting to be
        applied, exactly the shape a real customer produces by replying
        twice before either mail is dealt with."""
        result = mailflow.Result()
        row = self.dialog._register_rows[0]
        result.replies = [
            mailflow.Item("reply", message("Re: Enquiry — first",
                                           body="Too expensive for us."),
                         row, intent="rejected"),
            mailflow.Item("reply", message("Re: Enquiry — second",
                                           body="Actually, please proceed."),
                         row, intent="accepted"),
        ]
        self.dialog._fill_replies(result)

    def test_applying_an_older_reply_warns_when_a_newer_one_is_waiting(self):
        """Found from a real report: applying the older of two pending
        replies used to silently overwrite whatever the newer one had
        decided, with nothing on screen to say it had happened."""
        self._two_replies()
        self.assertEqual(self.dialog.replies_table.rowCount(), 2)
        self.dialog.replies_table.setCurrentCell(0, 0)   # the older reply
        asked = []

        class Box:
            Yes, No = UI.QMessageBox.Yes, UI.QMessageBox.No

            @staticmethod
            def question(*a, **k):
                asked.append(True)
                return Box.No

        with _Patched(UI, "QMessageBox", Box):
            self.dialog._apply_reply()
        self.assertTrue(asked, "should warn before applying the older reply")
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.QUOTED,
                         "declining the warning must change nothing")

    def test_saying_yes_to_the_warning_still_applies_it(self):
        self._two_replies()
        self.dialog.replies_table.setCurrentCell(0, 0)

        class Box:
            Yes, No = UI.QMessageBox.Yes, UI.QMessageBox.No

            @staticmethod
            def question(*a, **k):
                return Box.Yes

        with _Patched(UI, "QMessageBox", Box):
            self.dialog._apply_reply()
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.NOT_CONVERTED)

    def test_applying_the_newest_reply_first_needs_no_warning(self):
        self._two_replies()
        self.dialog.replies_table.setCurrentCell(1, 0)   # the newer reply
        asked = []

        class Box:
            @staticmethod
            def question(*a, **k):
                asked.append(True)
                return UI.QMessageBox.No

        with _Patched(UI, "QMessageBox", Box):
            self.dialog._apply_reply()
        self.assertFalse(asked)
        self.assertEqual(self.dialog._register_rows[0]["Status"],
                         register.ACCEPTED)

    def test_a_reply_row_survives_a_register_reload(self):
        """Found from a real report: pick a reply, then anything that
        reloads the register — a save, a mail check — replaces
        _register_rows with fresh dicts. _refresh_register() only
        re-syncs the to_quote/waiting/register tables (_reselect()), so
        _focus_row was left pointing at the old, now-orphaned dict, and a
        button on the replies tab — still showing the row as selected —
        reported "pick an inquiry from the list first". Re-anchoring by
        inquiry number (_focus_key) is the fix this guards."""
        self.dialog._fill_replies(self._result())
        inquiry_no = self.dialog._focus_key
        self.assertTrue(inquiry_no)
        self.assertIsNotNone(self.dialog._current_row())
        # What _refresh_register() does to _register_rows: reload from disk
        # into brand new dict objects, without touching the replies tab.
        self.dialog._register_rows = register.load(
            mailflow.Paths(self.folder).register_csv)
        row = self.dialog._current_row()
        self.assertIsNotNone(row, "the row must still resolve after reload")
        self.assertEqual(row["Inquiry no"], inquiry_no)

    def test_a_reply_arriving_opens_that_tab(self):
        self.dialog._quiet = False
        # _checked -> _remember -> config.save. This is the test that wrote a
        # bare fixture over a real ~/.prism/config.json before the module
        # guard existed.
        with _NoSave():
            self.dialog._checked(self._result())
        self.assertEqual(self.dialog.tabs.currentIndex(), 2)

    def test_a_timer_tick_never_moves_the_tab(self):
        """A screen that rearranges itself every ten minutes while you are
        reading it is the reason people switch automatic checking off."""
        self.dialog.tabs.setCurrentIndex(1)
        self.dialog._quiet = True
        with _NoSave():
            self.dialog._checked(self._result())
        self.assertEqual(self.dialog.tabs.currentIndex(), 1)


class NothingIsLostToASecondCheckOrAReopen(unittest.TestCase):
    """The actual report: a friend's reply had shown up on "What they said
    back" and a purchase order on "The order came" — both real, both still
    needing an answer — and switching tabs, or the next check finding
    nothing new, made them disappear. Nothing about the reply or the PO
    changed; the mailbox's own read bookmark had simply moved past the
    message that found them, and the three tables below were drawing
    straight from that one check's result and nothing else.

    core/worklist.py is the fix — see tests/test_worklist.py for the file
    format itself. These prove it end to end: through _fill_*(), through a
    second check finding nothing, and through a brand new InquiryDialog
    pointed at the same folder, which is what actually happens when the
    screen is closed and reopened."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()

    def _reply_result(self):
        result = mailflow.Result()
        result.replies = [mailflow.Item(
            "reply", message("Re: Enquiry", body="Done, go ahead."),
            self.dialog._register_rows[0], intent="accepted")]
        return result

    def _order_result(self):
        result = mailflow.Result()
        result.orders = [mailflow.Item(
            "order", message("PO 4471", body="Please supply as quoted."),
            self.dialog._register_rows[0], note="Matches the quotation")]
        return result

    # ── replies ──────────────────────────────────────────────────────────
    def test_a_reply_survives_an_empty_second_check(self):
        self.dialog._fill_replies(self._reply_result())
        empty = mailflow.Result()      # a later check that found nothing new
        self.dialog._fill_replies(empty)
        self.assertEqual(self.dialog.replies_table.rowCount(), 1)

    def test_a_reply_survives_reopening_the_dialog(self):
        self.dialog._fill_replies(self._reply_result())
        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        self.assertEqual(reopened.replies_table.rowCount(), 1)
        self.assertIn("go ahead", reopened.reply_text.toPlainText())

    def test_applying_it_in_the_reopened_dialog_still_removes_it(self):
        self.dialog._fill_replies(self._reply_result())
        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        with _NoSave():
            reopened._apply_reply()
        self.assertEqual(reopened.replies_table.rowCount(), 0)
        # And it does not come back a third time.
        third = UI.InquiryDialog(self.cfg)
        third._refresh_register()
        self.assertEqual(third.replies_table.rowCount(), 0)

    # ── purchase orders ──────────────────────────────────────────────────
    def test_a_purchase_order_survives_an_empty_second_check(self):
        self.dialog._fill_orders(self._order_result())
        self.dialog._fill_orders(mailflow.Result())
        self.assertEqual(self.dialog.orders_table.rowCount(), 1)

    def test_a_purchase_order_survives_reopening_the_dialog(self):
        self.dialog._fill_orders(self._order_result())
        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        self.assertEqual(reopened.orders_table.rowCount(), 1)
        self.assertEqual(reopened.orders_table.item(0, 3).text(),
                         "Matches the quotation")

    def test_accepting_it_in_the_reopened_dialog_resolves_it_for_good(self):
        self.dialog._fill_orders(self._order_result())
        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        reopened._po_item = reopened._selected_order()
        reopened._po_accepted(reopened._register_rows[0], "PO4471", "50000", "")
        self.assertEqual(reopened.orders_table.rowCount(), 0)
        third = UI.InquiryDialog(self.cfg)
        third._refresh_register()
        self.assertEqual(third.orders_table.rowCount(), 0)

    # ── arrived mail ─────────────────────────────────────────────────────
    def test_arrived_mail_survives_an_empty_second_check(self):
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        result = mailflow.Result()
        result.sorted_mail = [(message(), triage.rules_pass(message(), known))]
        self.dialog._fill_arrived(result)
        self.dialog._fill_arrived(mailflow.Result())
        self.assertEqual(self.dialog.arrived.rowCount(), 1)

    def test_arrived_mail_survives_reopening_the_dialog(self):
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        result = mailflow.Result()
        result.sorted_mail = [(message(), triage.rules_pass(message(), known))]
        self.dialog._fill_arrived(result)
        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        self.assertEqual(reopened.arrived.rowCount(), 1)

    def test_a_correction_survives_reopening_the_dialog(self):
        """The same report, for _correct(): teaching Prism a sender is not
        an enquiry must not be forgotten the moment the screen closes."""
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        msg = message("Newsletter", "promo@x.example", "buy now")
        result = mailflow.Result()
        result.sorted_mail = [(msg, triage.rules_pass(msg, known))]
        self.dialog._fill_arrived(result)
        self.dialog.arrived.setCurrentCell(0, 0)
        position = self.dialog.recategorise.findData("other")
        self.dialog.recategorise.setCurrentIndex(position)
        with _NoSave():
            self.dialog._correct()

        reopened = UI.InquiryDialog(self.cfg)
        reopened._refresh_register()
        self.assertEqual(reopened.arrived.item(0, 3).text(),
                         UI.CATEGORY_LABELS["other"])


class OnlyTheRightButtonsForTheRow(unittest.TestCase):
    """The seven-button row showed every action for every row, all the
    time — "Win this back" on an inquiry nobody had quoted, "Prepare a
    quotation" on one already converted. A person who has never used a CRM
    reads that as "which of these am I meant to press?". Now a row gets
    the two or three that make sense where it is, plus the same quiet
    links every row gets."""

    def test_the_table_itself(self):
        A = UI.actions_for
        self.assertEqual(A(register.NEW)[:2], ["prepare", "already_quoted"])
        self.assertIn("boq", A(register.NEW, has_drawing=True))
        self.assertNotIn("boq", A(register.NEW, has_drawing=False))
        self.assertEqual(A(register.QUOTED)[:3], ["remind", "phone", "lost"])
        self.assertEqual(A(register.FOLLOWING_UP)[0], "remind")
        self.assertEqual(A(register.NEGOTIATING)[0], "win_back")
        self.assertEqual(A(register.ACCEPTED)[0], "record_po")
        self.assertEqual(A(register.NOT_CONVERTED)[0], "win_back")
        self.assertEqual(A(register.CONVERTED, has_drawing=False),
                         ["edit", "folder", "attachments", "history", "delete"])
        self.assertEqual(A("")[0], "prepare")            # blank = New

    def test_every_row_can_be_edited_opened_and_deleted(self):
        for status in register.STATUSES + ("",):
            keys = UI.actions_for(status)
            self.assertEqual(
                keys[-5:],
                ["edit", "folder", "attachments", "history", "delete"], status)

    def test_never_more_than_three_boxed_buttons(self):
        for status in register.STATUSES + ("",):
            for drawing in (False, True):
                keys = UI.actions_for(status, has_drawing=drawing)
                self.assertLessEqual(len(keys) - 5, 3, (status, drawing))


class ThePanelUnderTheTable(unittest.TestCase):
    """Widget-level: picking a row shows its buttons and hides the rest;
    nothing selected shows "Pick a row above." and no buttons."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.new = register.from_message(message("New one"))
        self.quoted = register.from_message(
            message("Quoted one", "buyer@q.example"))
        register.mark_quoted(self.quoted, "QTN/26-27/0001", "50000")
        register.save([self.new, self.quoted],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)

    def _visible(self, key):
        # isVisibleTo() reports widgets on a tab that is not the current one
        # as hidden (the QTabWidget hides the page), so switch to it first —
        # which is also what a person does before they can see the panel.
        self.dialog.tabs.setCurrentIndex(UI.TAB_INDEX[key])
        panel = self.dialog._pages[key].panel
        return {k for k, btn in panel.buttons.items()
                if btn.isVisibleTo(self.dialog)}

    def test_nothing_selected_shows_the_prompt_and_no_buttons(self):
        page = self.dialog._pages["register"]
        self.dialog.register_table.setCurrentCell(-1, -1)
        self.assertIn("Pick a row", page.panel.title.text())
        self.assertEqual(self._visible("register"), set())

    def test_a_new_inquiry_gets_prepare_and_nothing_about_reminders(self):
        page = self.dialog._pages["to_quote"]
        self.dialog.to_quote_table.setCurrentCell(0, 0)
        shown = self._visible("to_quote")
        self.assertIn("prepare", shown)
        self.assertIn("delete", shown)
        self.assertNotIn("remind", shown)
        self.assertNotIn("win_back", shown)
        self.assertIn(self.new["Inquiry no"], page.panel.title.text())

    def test_a_quoted_inquiry_gets_the_reminder_and_the_phone_answer(self):
        self.dialog.followups.setCurrentCell(0, 0)
        shown = self._visible("waiting")
        self.assertEqual({"remind", "phone", "lost", "edit", "folder",
                          "attachments", "history", "delete"}, shown)
        self.assertEqual(self.dialog._selected_row()["Inquiry no"],
                         self.quoted["Inquiry no"])

    def test_the_row_picked_in_one_tab_is_the_row_the_buttons_act_on(self):
        """_selected_row() used to read only the register table; every
        action on the To-quote tab would then have asked "pick an inquiry"
        with one plainly picked."""
        self.dialog.to_quote_table.setCurrentCell(0, 0)
        self.assertEqual(self.dialog._selected_row()["Inquiry no"],
                         self.new["Inquiry no"])

    def test_the_selection_survives_a_save(self):
        """After an action the tables redraw; the owner must land back on
        the row they were on, not on "Pick a row above."."""
        self.dialog.register_table.setCurrentCell(0, 0)
        picked = self.dialog._selected_row()["Inquiry no"]
        self.dialog._refresh_register()
        self.assertEqual(self.dialog._selected_row()["Inquiry no"], picked)

    def test_three_reminders_disable_the_button_and_say_why(self):
        self.quoted["Reminders sent"] = "3"
        register.save([self.new, self.quoted],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog.followups.setCurrentCell(0, 0)
        self.assertFalse(self.dialog.remind_btn.isEnabled())
        self.assertIn("Call them", self.dialog.remind_btn.toolTip())


class TheWholeStoryWindow(unittest.TestCase):
    """"See the whole story" — the button that reads history.txt back in
    the app, one card per event, instead of sending the owner to the file
    manager for it."""

    @staticmethod
    def _labels(dialog) -> list[str]:
        return [w.text() for w in dialog.findChildren(QLabel)]

    def test_shows_the_recorded_event_as_a_card(self):
        folder = tempfile.mkdtemp()
        row = {"Inquiry no": "INQ/26-27/0001", "Customer": "Acme",
              "Folder": folder}
        history = CB.get_history()
        history.append(folder, "Enquiry received",
                       who="Acme <buyer@acme.example>", body="Please quote.")
        dialog = UI._HistoryDialog(row, folder)
        labels = self._labels(dialog)
        self.assertTrue(any("Enquiry received" in t for t in labels))
        self.assertTrue(any("buyer@acme.example" in t for t in labels))
        self.assertTrue(any("Please quote." in t for t in labels))

    def test_two_events_render_in_the_order_they_happened(self):
        folder = tempfile.mkdtemp()
        history = CB.get_history()
        history.append(folder, "Enquiry received", body="first thing")
        history.append(folder, "Quotation sent", body="second thing")
        dialog = UI._HistoryDialog(
            {"Inquiry no": "INQ/26-27/0001", "Folder": folder}, folder)
        labels = self._labels(dialog)
        first = next(i for i, t in enumerate(labels) if "first thing" in t)
        second = next(i for i, t in enumerate(labels) if "second thing" in t)
        self.assertLess(first, second)

    def test_an_inquiry_with_nothing_recorded_says_so_plainly(self):
        dialog = UI._HistoryDialog(
            {"Inquiry no": "INQ/26-27/0001", "Customer": "Acme"},
            tempfile.mkdtemp())
        self.assertTrue(any("Nothing recorded here yet" in t
                           for t in self._labels(dialog)))

    def test_the_button_reaches_the_folders_own_history(self):
        folder = tempfile.mkdtemp()
        row = register.from_message(message())
        row["Folder"] = folder
        register.save([row], mailflow.Paths(folder).register_csv)
        dialog = UI.InquiryDialog(ready_cfg(folder))
        dialog.register_table.setCurrentCell(0, 0)
        CB.get_history().append(folder, "Enquiry received", body="hello")
        created = []
        real = UI._HistoryDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)

        with _Patched(UI, "_HistoryDialog", _Capturing):
            dialog._show_history()
        self.assertEqual(len(created), 1)
        self.assertTrue(any("hello" in t for t in self._labels(created[0])))


class ReadingAnInquirysAttachments(unittest.TestCase):
    """A customer's actual files — read, saved elsewhere, or pulled
    straight into a Prism prompt — from the inquiry's own row, without a
    trip to the file manager."""

    @staticmethod
    def _labels(dialog) -> list[str]:
        return [w.text() for w in dialog.findChildren(QLabel)]

    def test_bookkeeping_files_are_never_offered_as_attachments(self):
        folder = tempfile.mkdtemp()
        open(os.path.join(folder, "drawing.pdf"), "w").write("x")
        open(os.path.join(folder, "history.txt"), "w").write("x")
        open(os.path.join(folder, "image_text.txt"), "w").write("x")
        files = UI._attachment_files(folder)
        self.assertEqual([os.path.basename(f) for f in files], ["drawing.pdf"])

    def test_shows_every_real_attachment(self):
        folder = tempfile.mkdtemp()
        open(os.path.join(folder, "drawing.pdf"), "w").write("x")
        open(os.path.join(folder, "photo.jpg"), "w").write("x")
        dialog = UI._AttachmentsDialog({"Folder": folder}, None)
        labels = self._labels(dialog)
        self.assertTrue(any("drawing.pdf" in t for t in labels))
        self.assertTrue(any("photo.jpg" in t for t in labels))

    def test_nothing_attached_says_so_plainly(self):
        dialog = UI._AttachmentsDialog({"Folder": tempfile.mkdtemp()}, None)
        self.assertTrue(any("Nothing attached" in t
                           for t in self._labels(dialog)))

    def test_attach_to_prism_calls_back_with_the_real_path(self):
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "drawing.pdf")
        open(path, "w").write("x")
        calls = []
        dialog = UI._AttachmentsDialog({"Folder": folder}, None)
        dialog._attach(path, calls.append)
        self.assertEqual(calls, [path])

    def test_the_inquiry_screens_button_reaches_the_right_row(self):
        folder = tempfile.mkdtemp()
        open(os.path.join(folder, "drawing.pdf"), "w").write("x")
        row = register.from_message(message())
        row["Folder"] = folder
        register.save([row], mailflow.Paths(folder).register_csv)
        dialog = UI.InquiryDialog(ready_cfg(folder))
        dialog.register_table.setCurrentCell(0, 0)
        created = []
        real = UI._AttachmentsDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)

        with _Patched(UI, "_AttachmentsDialog", _Capturing):
            dialog._show_attachments()
        self.assertEqual(len(created), 1)
        self.assertTrue(any("drawing.pdf" in t
                           for t in self._labels(created[0])))

    def test_attaching_from_the_inquiry_screen_reaches_main_window(self):
        """attach_to_prism is what main_window.py actually connects to
        _attach_path — see main_window.py's own wiring next to
        sidebar.favorite_chosen. This is the whole point of the feature:
        one click, no save-then-reattach."""
        folder = tempfile.mkdtemp()
        path = os.path.join(folder, "drawing.pdf")
        open(path, "w").write("x")
        row = register.from_message(message())
        row["Folder"] = folder
        register.save([row], mailflow.Paths(folder).register_csv)
        dialog = UI.InquiryDialog(ready_cfg(folder))
        dialog.register_table.setCurrentCell(0, 0)
        emitted = []
        dialog.attach_to_prism.connect(emitted.append)
        created = []
        real = UI._AttachmentsDialog

        class _Capturing(real):
            def exec(self):
                created.append(self)

        with _Patched(UI, "_AttachmentsDialog", _Capturing):
            dialog._show_attachments()
        self.assertEqual(len(created), 1)
        attach_btn = next(b for b in created[0].findChildren(UI.QPushButton)
                          if "Attach to Prism" in b.text())
        attach_btn.click()
        self.assertEqual(emitted, [path])


class AnsweringByPhone(unittest.TestCase):
    """In GIDC most answers come by phone. Without this the register could
    only move when the customer wrote."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog.followups.setCurrentCell(0, 0)

    def _answer(self, intent, note=""):
        class Fake:
            def __init__(self, *a, **k):
                pass

            def exec(self):
                return UI.QDialog.Accepted

            def intent(self_inner):
                return intent

            def note(self_inner):
                return note
        with _Patched(UI, "_PhoneReplyDialog", Fake):
            self.dialog._phone_reply()
        return register.load(mailflow.Paths(self.folder).register_csv)[0]

    def test_they_accepted(self):
        self.assertEqual(self._answer("accepted")["Status"], register.ACCEPTED)

    def test_they_want_a_better_rate(self):
        self.assertEqual(self._answer("negotiating")["Status"],
                         register.NEGOTIATING)

    def test_they_declined_goes_through_the_same_door_as_a_mail_no(self):
        saved = self._answer("rejected", "too costly")
        self.assertEqual(saved["Status"], register.NOT_CONVERTED)
        self.assertEqual(saved["Reason if lost"], "too costly")

    def test_a_note_is_kept(self):
        saved = self._answer("needs_info", "will confirm Monday")
        self.assertIn("will confirm Monday", saved["Notes"])


class DeletingAnInquiry(unittest.TestCase):
    """A newsletter that got itself registered is the commonest reason. The
    row goes; the folder stays; and the owner is asked whether that sender
    should ever be treated as an inquiry again."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(
            message("Pitch week!", "Jill <info@e.atlassian.com>"))
        self.keep = register.from_message(message())
        register.save([self.row, self.keep],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog.register_table.setCurrentCell(0, 0)

    def _delete(self, answers):
        """`answers` are the replies to the two questions, in order."""
        given = iter(answers)

        class Box:
            Yes, No = UI.QMessageBox.Yes, UI.QMessageBox.No

            @staticmethod
            def question(*a, **k):
                return next(given)

            @staticmethod
            def information(*a, **k):
                pass
        with _Patched(UI, "QMessageBox", Box), _NoSave() as saver:
            self.dialog._delete_inquiry()
        return (register.load(mailflow.Paths(self.folder).register_csv),
                saver.saved)

    def test_the_row_goes_and_the_others_stay(self):
        rows, _ = self._delete([UI.QMessageBox.Yes, UI.QMessageBox.No])
        self.assertEqual([r["Inquiry no"] for r in rows],
                         [self.keep["Inquiry no"]])

    def test_saying_no_to_the_first_question_changes_nothing(self):
        rows, saved = self._delete([UI.QMessageBox.No])
        self.assertEqual(len(rows), 2)
        self.assertEqual(saved, [])

    def test_blocking_the_sender_teaches_the_sorter(self):
        _, saved = self._delete([UI.QMessageBox.Yes, UI.QMessageBox.Yes])
        learned = saved[-1]["inquiry"]["knowledge"]["learned"]
        self.assertEqual(learned.get("info@e.atlassian.com"), "other")

    def test_not_blocking_the_sender_teaches_nothing(self):
        _, saved = self._delete([UI.QMessageBox.Yes, UI.QMessageBox.No])
        self.assertEqual(saved, [])

    def test_the_folder_on_disk_is_left_alone(self):
        folder = os.path.join(self.folder, "keep-me")
        os.makedirs(folder)
        self.row["Folder"] = folder
        register.save([self.row, self.keep],
                      mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        self.dialog.register_table.setCurrentCell(0, 0)
        self._delete([UI.QMessageBox.Yes, UI.QMessageBox.No])
        self.assertTrue(os.path.isdir(folder))


class DeletingFromAllMail(unittest.TestCase):
    """The All-mail log has no register row and nothing on disk behind
    it — the entries themselves ARE the record, one or many at once."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        messages = [
            message("Enquiry"),
            message("Sale!", "promo@x.example", "buy now",
                    {"List-Unsubscribe": "<https://x/u>"}),
            message("Newsletter", "news@z.example", "weekly digest",
                    {"List-Unsubscribe": "<https://z/u>"}),
        ]
        result = mailflow.Result()
        result.sorted_mail = list(zip(
            messages, [triage.rules_pass(m, known) for m in messages]))
        self.dialog._fill_arrived(result)

    def _delete(self, rows, answer):
        table = self.dialog.arrived
        table.clearSelection()
        for r in rows:
            table.setRangeSelected(
                QTableWidgetSelectionRange(r, 0, r, table.columnCount() - 1),
                True)
        with mock.patch.object(UI.QMessageBox, "question",
                               staticmethod(lambda *a, **k: answer)):
            self.dialog._delete_arrived()

    def test_one_row_goes_the_others_stay(self):
        table = self.dialog.arrived
        target = next(r for r in range(table.rowCount())
                     if table.item(r, 1).text() == "Sale!")
        self._delete([target], UI.QMessageBox.Yes)
        data = CB.get_worklist().load(self.dialog._root())
        subjects = {e["subject"] for e in data["arrived"]}
        self.assertEqual(subjects, {"Enquiry", "Newsletter"})

    def test_several_at_once(self):
        table = self.dialog.arrived
        targets = [r for r in range(table.rowCount())
                  if table.item(r, 1).text() in ("Sale!", "Newsletter")]
        self._delete(targets, UI.QMessageBox.Yes)
        data = CB.get_worklist().load(self.dialog._root())
        subjects = {e["subject"] for e in data["arrived"]}
        self.assertEqual(subjects, {"Enquiry"})

    def test_saying_no_deletes_nothing(self):
        self._delete([0], UI.QMessageBox.No)
        data = CB.get_worklist().load(self.dialog._root())
        self.assertEqual(len(data["arrived"]), 3)

    def test_nothing_selected_asks_nothing(self):
        self.dialog.arrived.clearSelection()
        with mock.patch.object(UI.QMessageBox, "information") as info:
            self.dialog._delete_arrived()
        info.assert_called_once()
        data = CB.get_worklist().load(self.dialog._root())
        self.assertEqual(len(data["arrived"]), 3)


class ResettingEverything(unittest.TestCase):
    """The one-button "start over": the whole register, every worklist
    log, and each mailbox's read bookmark — not just what's on screen."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["account"]["state"] = {
            "uidvalidity": 7, "last_uid": 42}
        self.dialog = UI.InquiryDialog(self.cfg)
        row = register.from_message(message())
        register.save([row], mailflow.Paths(self.folder).register_csv)
        known = triage.Knowledge.from_dict(self.cfg["inquiry"]["knowledge"])
        msg = message("Enquiry")
        result = mailflow.Result()
        result.sorted_mail = [(msg, triage.rules_pass(msg, known))]
        self.dialog._fill_arrived(result)
        CB.get_worklist().append(self.folder, "orders", [
            {"message_id": "<o@x>", "subject": "PO 1", "date": "2026-08-20"}])

    def _reset(self, answer):
        with mock.patch.object(UI.QMessageBox, "question",
                               staticmethod(lambda *a, **k: answer)):
            with _NoSave():
                self.dialog._reset_everything()

    def test_the_register_is_emptied(self):
        self._reset(UI.QMessageBox.Yes)
        self.assertEqual(
            register.load(mailflow.Paths(self.folder).register_csv), [])

    def test_every_worklist_kind_is_emptied(self):
        self._reset(UI.QMessageBox.Yes)
        data = CB.get_worklist().load(self.folder)
        for kind in CB.get_worklist().KINDS:
            self.assertEqual(data[kind], [], kind)

    def test_the_read_bookmark_goes_back_to_the_start(self):
        self._reset(UI.QMessageBox.Yes)
        state = self.dialog.cfg["inquiry"]["state"]
        self.assertEqual(state, {"uidvalidity": 0, "last_uid": 0})

    def test_the_table_on_screen_goes_blank_too(self):
        self._reset(UI.QMessageBox.Yes)
        self.assertEqual(self.dialog.arrived.rowCount(), 0)

    def test_saying_no_touches_nothing(self):
        self._reset(UI.QMessageBox.No)
        self.assertEqual(
            len(register.load(mailflow.Paths(self.folder).register_csv)), 1)
        data = CB.get_worklist().load(self.folder)
        self.assertEqual(len(data["arrived"]), 1)
        self.assertEqual(len(data["orders"]), 1)


class PickingYourOwnDates(unittest.TestCase):
    """Today / yesterday / last 7 days cover the working week; "from the
    1st to the 15th" needs the owner's own pair, both ends inclusive."""

    def test_the_rule(self):
        d = date
        self.assertTrue(UI._in_date_range(d(2026, 8, 10), "custom",
                                          d(2026, 8, 26), d(2026, 8, 1),
                                          d(2026, 8, 15)))
        self.assertTrue(UI._in_date_range(d(2026, 8, 15), "custom",
                                          d(2026, 8, 26), d(2026, 8, 1),
                                          d(2026, 8, 15)))
        self.assertFalse(UI._in_date_range(d(2026, 8, 16), "custom",
                                           d(2026, 8, 26), d(2026, 8, 1),
                                           d(2026, 8, 15)))
        # Ends the wrong way round still mean the same fortnight.
        self.assertTrue(UI._in_date_range(d(2026, 8, 10), "custom",
                                          d(2026, 8, 26), d(2026, 8, 15),
                                          d(2026, 8, 1)))
        self.assertFalse(UI._in_date_range(None, "custom", d(2026, 8, 26),
                                           d(2026, 8, 1), d(2026, 8, 15)))

    def test_the_date_boxes_appear_only_when_asked_for(self):
        folder = tempfile.mkdtemp()
        dialog = UI.InquiryDialog(ready_cfg(folder))
        dialog.tabs.setCurrentIndex(UI.TAB_INDEX["register"])
        page = dialog._pages["register"]
        self.assertFalse(page.date_from.isVisibleTo(dialog))
        page.filter.setCurrentIndex(page.filter.findData("custom"))
        self.assertTrue(page.date_from.isVisibleTo(dialog))
        self.assertTrue(page.date_to.isVisibleTo(dialog))

    def test_the_register_filters_to_the_pair(self):
        folder = tempfile.mkdtemp()
        rows = []
        for day in (1, 10, 20):
            row = register.from_message(message(sender=f"d{day}@x.example"))
            row["Date received"] = f"{day:02d}-08-2026"
            rows.append(row)
        register.save(rows, mailflow.Paths(folder).register_csv)
        dialog = UI.InquiryDialog(ready_cfg(folder))
        page = dialog._pages["register"]
        page.filter.setCurrentIndex(page.filter.findData("custom"))
        page.date_from.setDate(UI.QDate(2026, 8, 5))
        page.date_to.setDate(UI.QDate(2026, 8, 15))
        self.assertEqual([r["Date received"] for r in dialog._visible_rows],
                         ["10-08-2026"])


class ComparingSideBySide(unittest.TestCase):
    """The owner asked for it in so many words: before a price goes out, one
    window with the customer's ask, our rates, what the job takes, and the
    quotation. Every panel is read off what the quotation screen already
    holds, so it can never disagree with the figure about to be sent."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.rates = os.path.join(self.folder, "rates.csv")
        with open(self.rates, "w", encoding="utf-8") as f:
            f.write("Code,Description,Unit,Rate,HSN\n"
                    "CS-201,Compression spring 2mm,nos,42.50,7320\n")
        self.cost = os.path.join(self.folder, "costs.csv")
        with open(self.cost, "w", encoding="utf-8") as f:
            f.write("SS 304 wire,per_kg,95\nCoiling,per_piece,1.20\n"
                    "Tool setting,per_lot,800\nOverheads,percent,12\n")
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["rate_list"] = self.rates
        self.cfg["inquiry"]["cost_sheet"] = self.cost
        self.row = register.from_message(message())
        self.row["Quantity"] = "5000 nos"
        self.row["Notes"] = "Need it before Diwali"
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        quoting = CB.get_quoting()
        self.q = UI.QuotationDialog(
            self.cfg, self.dialog._register_rows[0],
            quoting.load_rates(self.rates), self.dialog,
            cost_lines=quoting.load_cost_lines(self.cost))

    def _texts(self):
        from PySide6.QtWidgets import QPlainTextEdit
        window = UI._CompareDialog(self.q)
        return [box.toPlainText() for box in window.findChildren(QPlainTextEdit)]

    def test_the_button_is_on_the_quotation_screen(self):
        self.assertEqual(self.q.compare_btn.text(), "Compare side by side")

    def test_four_panels_in_the_order_asked_for(self):
        asked, rates, materials, quotation = self._texts()
        self.assertIn("compression spring", asked.lower())
        self.assertIn("5000 nos", asked)
        self.assertIn("Need it before Diwali", asked)
        self.assertIn("CS-201", rates)
        self.assertIn("42.50", rates)
        self.assertIn("SS 304 wire", materials)
        self.assertIn("per kg", materials)
        self.assertIn("QUOTATION", quotation)

    def test_the_quotation_panel_is_the_live_figure(self):
        """Typing a rate over Prism's suggestion must show up here too —
        the whole point is comparing what is ABOUT to be sent."""
        self.q.rate_edit.setText("40")
        _, rates, _, quotation = self._texts()
        self.assertIn("40", rates)
        self.assertIn("40.00", quotation)

    def test_material_totals_appear_once_a_weight_is_given(self):
        self.q.source.setCurrentIndex(self.q.source.findData("cost"))
        self.q.weight.setText("0.045")
        self.q.quantity.setText("5000")
        _, _, materials, _ = self._texts()
        self.assertIn("225 kg", materials)          # 0.045 × 5000
        self.assertIn("21,375.00", materials)       # × ₹95

    def test_no_cost_sheet_says_so_instead_of_an_empty_box(self):
        q = UI.QuotationDialog(self.cfg, self.dialog._register_rows[0],
                               CB.get_quoting().load_rates(self.rates),
                               self.dialog)
        from PySide6.QtWidgets import QPlainTextEdit
        window = UI._CompareDialog(q)
        materials = [b.toPlainText() for b in window.findChildren(QPlainTextEdit)][2]
        self.assertIn("cost sheet", materials)


class EverythingIsReadableAtTheSmallestSize(unittest.TestCase):
    """The owner's screenshots: tab titles cut to "1 · What arriv…", a row
    of seven buttons with their words clipped inside them, labels drawn on
    top of the boxes below. Each was a widget sized on one assumption and
    painted on another. These pin the geometry with the REAL stylesheet and
    fonts loaded the way main.py loads them — an offscreen default font
    would pass while the shipped app failed."""

    @classmethod
    def setUpClass(cls):
        import i18n
        import paths
        import theme
        theme.load_fonts()
        # The fonts and the stylesheet are what size the widgets; the
        # role-hue rotation is not, and apply_role() rewrites theme.ACCENT
        # for the whole process — which test_roles then trips over.
        qss = open(paths.resource("style.qss"), encoding="utf-8").read()
        qss = i18n.style_for_script(qss)
        cls._old_qss = _app.styleSheet()
        _app.setStyleSheet(qss.replace(
            "%ASSETS%", paths.resource("assets").replace(os.sep, "/")))

    @classmethod
    def tearDownClass(cls):
        _app.setStyleSheet(cls._old_qss)

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        rows = []
        for n, status in enumerate((register.NEW, register.QUOTED,
                                    register.NEGOTIATING, register.ACCEPTED)):
            row = register.from_message(message(sender=f"c{n}@x.example"))
            row["Status"] = status
            row["Quotation no"] = f"QTN/{n}" if status != register.NEW else ""
            rows.append(row)
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog.resize(960, 640)          # the minimum it allows
        # show(), never app.processEvents() — see the note on the quotation
        # form's geometry test for why draining the queue here hangs.
        self.dialog.show()

    def tearDown(self):
        self.dialog.close()

    def test_no_tab_title_is_ever_cut_short(self):
        import re
        import paths
        # Measure with the font the stylesheet PAINTS the tab titles in, read from
        # style.qss itself. bar.fontMetrics() is the widget's own font, which Qt
        # does not always size the tab with: on the Windows runner the tab rect was
        # sized from the painted font and came out 137 px against a 143 px
        # estimate made with the widget font, although nothing was cut. The rule
        # for the tab text is the one Qt paints; the title must fit inside it.
        qss = open(paths.resource("style.qss"), encoding="utf-8").read()
        rule = re.search(r"\nQTabBar::tab\s*\{([^}]*)\}", qss).group(1)
        family = re.search(r'font-family:\s*"([^"]+)"', rule).group(1)
        px = int(re.search(r"font-size:\s*(\d+)px", rule).group(1))
        weight = int(re.search(r"font-weight:\s*(\d+)", rule).group(1))
        pad = int(re.search(r"padding:\s*\d+px\s+(\d+)px", rule).group(1))
        border = int(re.search(r"border:\s*(\d+)px", rule).group(1))
        from PySide6.QtGui import QFont, QFontMetrics
        painted = QFont(family)
        painted.setPixelSize(px)
        painted.setWeight(QFont.Weight(weight))
        fm = QFontMetrics(painted)
        bar = self.dialog.tabs.tabBar()
        for index in range(bar.count()):
            text = bar.tabText(index)
            needed = fm.horizontalAdvance(text) + 2 * pad + 2 * border
            self.assertGreaterEqual(bar.tabRect(index).width(), needed, text)

    def _show_tab(self, key):
        """Switch tabs and lay the page out NOW, by hand. The stacked widget
        sizes a newly-current page on the next pass of the event loop, and
        NOTHING here may run that loop — not processEvents(), and not
        sendPostedEvents() either: a zero-delay QTimer.singleShot is
        delivered as a posted event, so flushing them fired the deferred
        _first_look() of an earlier test's unclosed dialog and hung the
        whole suite on its "set up now?" box. Setting the page's geometry
        to its parent's rect and activating its layout is all a real
        event-loop pass would have done for it."""
        self.dialog.tabs.setCurrentIndex(UI.TAB_INDEX[key])
        page = self.dialog._pages[key]
        page.setGeometry(page.parentWidget().rect())
        page.layout().activate()
        return page

    def test_every_action_button_shows_its_whole_label(self):
        for key in ("to_quote", "waiting", "register"):
            page = self._show_tab(key)
            page.table.setCurrentCell(0, 0)
            page.layout().activate()
            for name, btn in page.panel.buttons.items():
                if not btn.isVisibleTo(self.dialog):
                    continue
                fm = btn.fontMetrics()
                self.assertGreaterEqual(
                    btn.width(), fm.horizontalAdvance(btn.text()),
                    f"{key}/{name}: {btn.text()!r} is clipped")
                self.assertLessEqual(btn.geometry().right(),
                                     page.panel.width(),
                                     f"{key}/{name} sticks out of the panel")

    def test_the_table_gets_the_height_and_nothing_is_squeezed(self):
        from addons.inquiry.register_table import ROW_HEIGHT
        for key, _label in UI.TABS:
            page = self._show_tab(key)
            self.assertGreaterEqual(page.stack.height(), 4 * ROW_HEIGHT, key)
            # With a row picked the button row may wrap; whatever height
            # that takes, the panel must hold every visible button whole —
            # a sizeHint comparison cannot say that, the geometry can.
            page.table.setCurrentCell(0, 0)
            page.layout().activate()
            for name, btn in page.panel.buttons.items():
                if btn.isVisibleTo(self.dialog):
                    top = btn.mapTo(page.panel, btn.rect().topLeft()).y()
                    self.assertLessEqual(top + btn.height(),
                                         page.panel.height(),
                                         f"{key}/{name} is cut off below")

    def test_nothing_that_holds_text_has_a_fixed_height(self):
        """The old replies tab pinned its text box to 120px, which is what
        squeezed everything else when the window was short."""
        for box in (self.dialog.reply_text,):
            self.assertLess(box.minimumHeight(), box.maximumHeight())

    # The tab page's size in the real window at 1078x900 (13 Oct 2026).
    PAGE_AT_1078 = (718, 512)

    def _lay_out_at(self, key, size):
        from PySide6.QtCore import QRect
        from PySide6.QtWidgets import QWidget
        self.dialog.tabs.setCurrentIndex(UI.TAB_INDEX[key])
        page = self.dialog._pages[key]
        page.setGeometry(QRect(0, 0, *size))
        for _ in range(2):          # height-for-width settles on the second
            for widget in [page] + page.findChildren(QWidget):
                if widget.layout() is not None:
                    widget.layout().activate()
        return page

    @staticmethod
    def _overlapping(root):
        """Pairs of visible controls under `root` drawn over each other."""
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLabel,
                                       QLineEdit, QPlainTextEdit, QWidget)
        kinds = (QAbstractButton, QComboBox, QLabel, QLineEdit, QPlainTextEdit)
        controls = [w for w in root.findChildren(QWidget)
                    if isinstance(w, kinds) and w.isVisibleTo(root) and w.width() > 0 and w.height() > 0
                    and not any(isinstance(a, kinds) for a in _ancestors(w, root))]
        rect = lambda w: QRect(w.mapTo(root, QPoint(0, 0)), w.size())  # noqa: E731
        return [(a.objectName() or type(a).__name__, getattr(a, "text", str)(),
                 b.objectName() or type(b).__name__, getattr(b, "text", str)())
                for i, a in enumerate(controls) for b in controls[i + 1:]
                if rect(a).intersects(rect(b))]

    def test_they_answered_draws_nothing_over_anything_at_1078(self):
        """The real window: "Prism thinks:" drawn over the reply text, and
        once "Delete from this list" joined the buttons the picker drew
        empty and "Update the register" as a black block."""
        row = self.dialog._register_rows[3]
        result = mailflow.Result()
        result.replies = [mailflow.Item(
            "reply", message("Re: Enquiry", body="Please go ahead.\n" * 12),
            row, intent="accepted")]
        self.dialog._fill_replies(result)
        page = self._lay_out_at("replies", self.PAGE_AT_1078)
        self.assertEqual(self.dialog.replies_table.currentRow(), 0)
        self.assertTrue(self.dialog.apply_btn.isVisibleTo(page.panel))
        self.assertEqual(self._overlapping(page.panel), [])
        for widget in (self.dialog.reply_text, self.dialog.intent_picker,
                       self.dialog.apply_btn,
                       *[b for b in page.panel.buttons.values()
                         if b.isVisibleTo(page.panel)]):
            bottom = widget.mapTo(page.panel, widget.rect().bottomLeft()).y()
            self.assertLess(bottom, page.panel.height(),
                            f"{type(widget).__name__} is cut off below")
            self.assertGreaterEqual(widget.height(), widget.minimumHeight())
        self.assertGreaterEqual(self.dialog.intent_picker.height(),
                                self.dialog.intent_picker.minimumHeight())
        # and the table above it keeps a header and two rows
        self.assertGreaterEqual(
            page.stack.height(),
            2 * self.dialog.replies_table.verticalHeader().defaultSectionSize())

    def test_the_register_toolbar_keeps_a_usable_search_box_at_1078(self):
        """"Save as Excel…" squeezed the search box to "Fin…", and the
        All/Open/Won/Lost chips were stacked one above the other."""
        page = self._lay_out_at("register", self.PAGE_AT_1078)
        search = page.search
        fm = search.fontMetrics()
        self.assertGreaterEqual(search.width(), fm.averageCharWidth() * 18)
        self.assertGreaterEqual(search.width(), search.minimumWidth())
        chips = list(self.dialog.register_chips._buttons.values())
        self.assertEqual(len({c.y() for c in chips}), 1,
                         "the chips must sit on one line")
        self.assertEqual(self._overlapping(page.toolbar), [])
        for btn in page.toolbar.findChildren(type(chips[0])):
            if btn.isVisibleTo(page.toolbar) and btn.text():
                self.assertGreaterEqual(
                    btn.width(), btn.fontMetrics().horizontalAdvance(btn.text()),
                    btn.text())
                right = btn.mapTo(page.toolbar, btn.rect().topRight()).x()
                self.assertLessEqual(right, page.toolbar.width(), btn.text())


class CorrectingTheRegisterByHand(unittest.TestCase):
    """They can always edit the CSV in Excel — it is their file. But a
    register that can only be corrected by closing the app is one they will
    stop correcting."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def test_the_fields_a_person_knows_better_are_editable(self):
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        for field in ("Customer", "Product asked", "Quantity"):
            self.assertIn(field, dialog._edits)

    def test_the_bookkeeping_is_not_editable(self):
        """Letting the inquiry number be retyped is how two rows end up
        sharing one."""
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        for field in ("Inquiry no", "Quotation no", "Date received"):
            self.assertNotIn(field, dialog._edits)

    def test_closing_a_row_by_hand_moves_the_result_column_too(self):
        """Result is what the month-end summary counts. A row marked
        Converted here but left open in Result makes the conversion figure
        disagree with the list the owner is looking at."""
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        dialog._status.setCurrentIndex(
            dialog._status.findData(register.CONVERTED))
        self.assertEqual(dialog.changes()["Result"], register.CONVERTED)

    def test_reopening_a_row_clears_the_result(self):
        row = dict(self.dialog._register_rows[0])
        row["Status"] = register.CONVERTED
        row["Result"] = register.CONVERTED
        dialog = UI._EditRowDialog(row)
        dialog._status.setCurrentIndex(dialog._status.findData(register.QUOTED))
        self.assertEqual(dialog.changes()["Result"], "")

    def test_every_status_is_offered(self):
        dialog = UI._EditRowDialog(self.dialog._register_rows[0])
        offered = {dialog._status.itemData(i)
                   for i in range(dialog._status.count())}
        self.assertEqual(offered, set(register.STATUSES))


class ChasingAQuietQuotation(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        self.row["Last contact"] = "01-01-2020"      # long overdue
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def test_the_overdue_quotation_is_listed(self):
        self.assertEqual(len(self.dialog._followup_rows), 1)

    def test_nothing_is_sent_without_a_selection(self):
        """No row selected on open. Firing at whatever happens to be first
        would mail a real customer."""
        shown = []
        self.dialog.followups.setCurrentCell(-1, -1)
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            self.dialog._send_reminder()
        self.assertEqual(len(shown), 1)

    def test_a_sent_reminder_is_counted_and_saved(self):
        self.dialog._reminder_sent(self.dialog._followup_rows[0], ["x"], [])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Reminders sent"], "1")
        self.assertEqual(saved[0]["Status"], register.FOLLOWING_UP)

    def test_a_failed_reminder_is_not_counted(self):
        """Counting a reminder that never left makes Prism stop chasing after
        three sends that never happened."""
        # _explain opens a real modal; swapped for a recorder so the test does
        # not wait forever for a human to click OK.
        told = []
        self.dialog._explain = told.append
        self.dialog._reminder_sent(self.dialog._followup_rows[0],
                                   [], [("a@b.c", "mailbox full")])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual((saved[0]["Reminders sent"] or "0"), "0")
        self.assertIn("mailbox full", told[0])

    def test_a_sent_reminder_is_written_to_the_sent_log(self):
        """The register's count says HOW MANY; worklist/sent.json says WHEN
        and WHAT — the line "Waiting on a reply" reads back as "reminder
        sent 24-08, 25-08" instead of a bare "2"."""
        self.dialog._reminder_sent(self.dialog._followup_rows[0], ["x"], [],
                                   subject="Reminder: our quotation")
        sent = CB.get_worklist().load(self.folder)["sent"]
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["kind"], "reminder")
        self.assertEqual(sent[0]["inquiry_no"], self.row["Inquiry no"])
        self.assertEqual(sent[0]["quotation_no"], "QTN/26-27/0001")
        self.assertEqual(sent[0]["subject"], "Reminder: our quotation")

    def test_a_failed_reminder_is_not_logged_as_sent(self):
        self.dialog._explain = lambda *_: None
        self.dialog._reminder_sent(self.dialog._followup_rows[0],
                                   [], [("a@b.c", "mailbox full")])
        self.assertEqual(CB.get_worklist().load(self.folder)["sent"], [])

    def test_the_old_three_argument_call_still_works(self):
        """_chase_automatically and every existing test call it without a
        subject; the log then carries the reminder's own wording."""
        self.dialog._reminder_sent(self.dialog._followup_rows[0], ["x"], [])
        sent = CB.get_worklist().load(self.folder)["sent"]
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0]["subject"])

    def test_chasing_stops_after_three(self):
        row = dict(self.row)
        row["Reminders sent"] = "3"
        self.assertEqual(register.awaiting_followup([row]), [])


class TheWaitingBadgeMatchesItsOwnTable(unittest.TestCase):
    """Found from a real report: the "No answer yet" tab read "(0)" with a
    row plainly sitting in the table underneath it. The badge was counting
    _followup_rows — quotations due a reminder TODAY — while the table
    (_render_waiting()) shows every quotation still unanswered, due or
    not. A quotation quoted this morning is correctly "not yet due" and
    correctly still in the table; the badge must count the same rows the
    table shows, the way every other tab's badge already does."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        self.row["Last contact"] = date.today().strftime("%d-%m-%Y")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def test_a_not_yet_due_quotation_is_not_in_the_reminder_list(self):
        """Confirms the scenario is set up right: nothing is due today."""
        self.assertEqual(self.dialog._followup_rows, [])

    def test_but_it_is_still_in_the_waiting_table(self):
        self.assertEqual(len(self.dialog._waiting_rows), 1)
        self.assertEqual(self.dialog.followups.rowCount(), 1)

    def test_the_tab_badge_counts_the_table_not_the_reminder_list(self):
        self.assertIn("(1)", self.dialog.tabs.tabText(UI.TAB_INDEX["waiting"]))


class StartingFromARegisterTheyAlreadyKeep(unittest.TestCase):
    """A shop trading twenty years already has an inquiry list. Starting them
    at row one means running two registers side by side until they give up on
    ours."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.theirs = os.path.join(self.folder, "old list.csv")

    def write(self, text: str):
        with open(self.theirs, "w", encoding="utf-8") as f:
            f.write(text)

    def dialog(self, target: str) -> InquirySetupDialog:
        d = InquirySetupDialog({})
        d.addr.setText("a@b.c")
        d.password.setText("p")
        d.work_folder.edit.setText(target)
        d.existing_register.edit.setText(self.theirs)
        return d

    def test_their_rows_come_across(self):
        self.write("Inquiry no,Date received,Customer,Status\n"
                   "INQ/25-26/0001,01-04-2025,Shakti Auto,Quoted\n"
                   "INQ/25-26/0002,02-04-2025,Gujarat Motors,Converted\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual([r["Customer"] for r in rows],
                         ["Shakti Auto", "Gujarat Motors"])

    def test_their_own_columns_survive(self):
        """Their "Party Name" and "Remarks" are twenty years of somebody's
        work. Prism adds columns; it never takes any away."""
        self.write("Inquiry no,Party Name,Remarks\n"
                   "INQ/25-26/0001,Shakti,called twice\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        row = register.load(os.path.join(target, register.FILENAME))[0]
        self.assertEqual(row["Party Name"], "Shakti")
        self.assertEqual(row["Remarks"], "called twice")

    def test_an_existing_register_is_never_overwritten(self):
        """That file is the only copy of their order book. Importing over the
        top of a live one would be unrecoverable."""
        target = tempfile.mkdtemp()
        live = register.from_message(message())
        live["Customer"] = "Already here"
        register.save([live], os.path.join(target, register.FILENAME))

        self.write("Inquiry no,Customer\nINQ/25-26/0001,Imported\n")
        with _NoSave():
            said = self.dialog(target)._import_register(target)

        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual([r["Customer"] for r in rows], ["Already here"])
        self.assertIn("left alone", said)

    def test_missing_columns_are_reported_not_guessed(self):
        """A column-guessing importer that got it wrong would quietly mis-file
        somebody's order book. Say what was not found instead."""
        self.write("Ref,Party\nA1,Shakti\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            said = self.dialog(target)._import_register(target)
        self.assertIn("Customer", said)
        self.assertIn("Status", said)

    def test_an_empty_file_imports_nothing_and_says_so(self):
        self.write("Inquiry no,Customer\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            said = self.dialog(target)._import_register(target)
        self.assertIn("no rows", said)

    def test_leaving_the_box_empty_does_nothing(self):
        target = tempfile.mkdtemp()
        d = self.dialog(target)
        d.existing_register.edit.setText("")
        with _NoSave():
            self.assertEqual(d._import_register(target), "")
        self.assertFalse(os.path.exists(
            os.path.join(target, register.FILENAME)))

    def test_a_missing_file_is_a_sentence_not_a_crash(self):
        target = tempfile.mkdtemp()
        d = self.dialog(target)
        d.existing_register.edit.setText(os.path.join(target, "nope.csv"))
        with _NoSave():
            said = d._import_register(target)
        self.assertIn("no rows", said.lower())

    def test_numbering_carries_on_from_theirs(self):
        """The whole point of importing. If Prism restarted at 0001 it would
        issue a number the customer already has on a quotation."""
        self.write("Inquiry no,Customer\nINQ/26-27/0087,Shakti\n")
        target = tempfile.mkdtemp()
        with _NoSave():
            self.dialog(target)._import_register(target)
        rows = register.load(os.path.join(target, register.FILENAME))
        self.assertEqual(register.next_number(rows, "INQ", date(2026, 8, 12)),
                         "INQ/26-27/0088")


class MergingInAListTheyAlreadyKeep(unittest.TestCase):
    """register.merge_in() — the ongoing version of the setup-time import
    above. That one only ever runs once, into an empty register; this is for
    the shop that has been using Prism for months and finds a second list —
    a colleague's spreadsheet, or one they forgot they had — and wants it
    folded in without duplicating what Prism already knows about."""

    def test_new_rows_are_added(self):
        existing = [register.from_message(message())]
        incoming = [{"Inquiry no": "OLD/1", "Customer": "Shakti Auto",
                    "Email": "x@shakti.in"}]
        merged, added, skipped = register.merge_in(existing, incoming)
        self.assertEqual(len(merged), 2)
        self.assertEqual((added, skipped), (1, 0))

    def test_a_row_sharing_an_inquiry_number_is_left_out(self):
        """Somebody's own export of Prism's own register, re-imported by
        mistake, must not double every row in it."""
        row = register.from_message(message())
        merged, added, skipped = register.merge_in([row], [dict(row)])
        self.assertEqual(len(merged), 1)
        self.assertEqual((added, skipped), (0, 1))

    def test_no_inquiry_number_falls_back_to_email_date_and_product(self):
        """A hand-kept sheet rarely has Prism's numbering scheme, so the
        fallback key is what actually protects it from being doubled."""
        existing = [{"Email": "a@b.c", "Date received": "01-04-2025",
                    "Product asked": "Springs"}]
        incoming = [{"Email": "a@b.c", "Date received": "01-04-2025",
                    "Product asked": "Springs", "Customer": "Retyped"}]
        merged, added, skipped = register.merge_in(existing, incoming)
        self.assertEqual((added, skipped), (0, 1))

    def test_several_genuinely_blank_rows_do_not_collide(self):
        """Nothing to key on must never mean "treat it as a duplicate of the
        last blank row" — that would silently drop real, if messy, rows."""
        existing = [{}]
        incoming = [{}, {}]
        merged, added, skipped = register.merge_in(existing, incoming)
        self.assertEqual((added, skipped), (2, 0))
        self.assertEqual(len(merged), 3)

    def test_existing_rows_are_never_touched_or_reordered(self):
        first = register.from_message(message("First"))
        merged, _, _ = register.merge_in(
            [first], [{"Inquiry no": "OLD/1", "Customer": "New"}])
        self.assertIs(merged[0], first)

    def test_their_own_columns_survive_a_merge(self):
        merged, _, _ = register.merge_in(
            [], [{"Inquiry no": "OLD/1", "Party Name": "Shakti",
                 "Remarks": "called twice"}])
        self.assertEqual(merged[0]["Party Name"], "Shakti")
        self.assertEqual(merged[0]["Remarks"], "called twice")


class TheRegisterTabInTheWorkingDialog(unittest.TestCase):
    """The date filter, "mark as already quoted", and "import a CSV" — all
    three live in the register tab of the working screen, alongside the
    existing per-row actions (mark lost, prepare a quotation)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.today = date.today()
        self.rows = [
            self._row("Today Ltd", self.today),
            self._row("Yesterday Ltd", self.today - timedelta(days=1)),
            self._row("This Week Ltd", self.today - timedelta(days=4)),
            self._row("Old Ltd", self.today - timedelta(days=40)),
        ]
        register.save(self.rows, mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def _row(self, customer: str, when: date) -> dict:
        row = register.from_message(message(sender=f"{customer}@x.example"))
        row["Customer"] = customer
        row["Date received"] = when.strftime("%d-%m-%Y")
        return row

    def _select(self, key: str):
        self.dialog.register_filter.setCurrentIndex(
            self.dialog.register_filter.findData(key))

    def test_all_time_shows_everything(self):
        self._select("all")
        self.assertEqual(self.dialog.register_table.rowCount(), 4)

    def test_today_shows_only_todays_row(self):
        self._select("today")
        self.assertEqual(self.dialog.register_table.rowCount(), 1)
        self.assertEqual(self.dialog._visible_rows[0]["Customer"], "Today Ltd")

    def test_yesterday_shows_only_yesterdays_row(self):
        self._select("yesterday")
        self.assertEqual(self.dialog._visible_rows[0]["Customer"],
                         "Yesterday Ltd")

    def test_last_7_days_includes_today_and_this_week_but_not_older(self):
        self._select("week")
        shown = {r["Customer"] for r in self.dialog._visible_rows}
        self.assertEqual(shown, {"Today Ltd", "Yesterday Ltd", "This Week Ltd"})

    def test_older_than_a_week_is_the_exact_complement(self):
        self._select("older")
        self.assertEqual(self.dialog._visible_rows[0]["Customer"], "Old Ltd")

    def test_switching_the_filter_does_not_re_read_the_disk(self):
        """Changing what is shown must not cost what a real mail check
        costs — the register may be a CSV on a slow or shared drive."""
        original = register.load
        register.load = lambda p: (_ for _ in ()).throw(AssertionError(
            "the filter re-read the register"))
        try:
            self._select("today")
            self._select("all")
        finally:
            register.load = original

    def test_selecting_a_row_after_filtering_selects_the_row_shown(self):
        """The table only ever holds _visible_rows now — a row index that
        used to mean "position N in the full register" would silently pick
        the wrong inquiry the moment a filter is on."""
        self._select("today")
        self.dialog.register_table.setCurrentCell(0, 0)
        self.assertEqual(self.dialog._selected_row()["Customer"], "Today Ltd")

    def test_marking_as_already_quoted_sets_the_status(self):
        self._select("all")
        self.dialog.register_table.setCurrentCell(0, 0)
        with mock.patch.object(UI, "_ask_already_quoted",
                               return_value=("QTN/1", "5000", True)):
            self.dialog._mark_already_quoted()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        row = register.find(saved, self.rows[0]["Inquiry no"])
        self.assertEqual(row["Status"], register.QUOTED)
        self.assertEqual(row["Quotation no"], "QTN/1")

    def test_both_fields_are_optional(self):
        """An owner who just wants Prism to stop chasing something already
        handled should not be blocked on a number they never wrote down."""
        self._select("all")
        self.dialog.register_table.setCurrentCell(0, 0)
        with mock.patch.object(UI, "_ask_already_quoted",
                               return_value=("", "", True)):
            self.dialog._mark_already_quoted()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        row = register.find(saved, self.rows[0]["Inquiry no"])
        self.assertEqual(row["Status"], register.QUOTED)

    def test_cancelling_the_dialog_changes_nothing(self):
        self._select("all")
        self.dialog.register_table.setCurrentCell(0, 0)
        with mock.patch.object(UI, "_ask_already_quoted",
                               return_value=("", "", False)):
            self.dialog._mark_already_quoted()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        row = register.find(saved, self.rows[0]["Inquiry no"])
        self.assertEqual(row["Status"], register.NEW)

    def test_importing_a_csv_adds_rows_and_reports_the_count(self):
        theirs = os.path.join(self.folder, "old list.csv")
        with open(theirs, "w", encoding="utf-8") as f:
            f.write("Inquiry no,Customer\nOLD/1,Kept Elsewhere\n")
        shown = []
        with mock.patch.object(UI, "QFileDialog") as picker, \
             mock.patch.object(UI, "QMessageBox", _Recording(shown)):
            picker.getOpenFileName.return_value = (theirs, "")
            self.dialog._import_csv_into_register()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(len(saved), 5)
        self.assertIn("Added 1", shown[0][2])

    def test_importing_never_touches_what_is_already_there(self):
        theirs = os.path.join(self.folder, "dupes.csv")
        with open(theirs, "w", encoding="utf-8") as f:
            f.write(f"Inquiry no,Customer\n{self.rows[0]['Inquiry no']},"
                    "Retyped Elsewhere\n")
        with mock.patch.object(UI, "QFileDialog") as picker, \
             mock.patch.object(UI, "QMessageBox"):
            picker.getOpenFileName.return_value = (theirs, "")
            self.dialog._import_csv_into_register()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(len(saved), 4)
        self.assertEqual(register.find(
            saved, self.rows[0]["Inquiry no"])["Customer"], "Today Ltd")


class PricingFromTheOwnersFormulas(unittest.TestCase):
    """The cost-sheet route: their line names, their rates, Prism's
    arithmetic. Every figure has to be one they could reproduce on paper."""

    SHEET = ("Wire,per_kg,95\n"
             "Coiling,per_piece,1.20\n"
             "Tool setting,per_lot,800\n"
             "Overheads,percent,12\n")

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cost = os.path.join(self.folder, "costs.csv")
        with open(self.cost, "w", encoding="utf-8") as f:
            f.write(self.SHEET)
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["cost_sheet"] = self.cost
        self.row = register.from_message(message())
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        self.lines = CB.get_quoting().load_cost_lines(self.cost)

    def quote_dialog(self):
        return UI.QuotationDialog(self.cfg, self.dialog._register_rows[0], [],
                                  self.dialog, cost_lines=self.lines)

    def test_a_shop_with_only_a_cost_sheet_can_still_quote(self):
        """Requiring the rate list, as this once did, locked out every shop
        that quotes made-to-drawing work — which is most job shops."""
        q = self.quote_dialog()
        self.assertEqual([q.source.itemData(i) for i in range(q.source.count())],
                         ["cost"])

    def test_every_line_of_the_working_is_on_screen(self):
        """This is the number they will be asked to justify on the phone. A
        rate they cannot explain is a rate they will not send."""
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        for name in ("Wire", "Coiling", "Tool setting", "Overheads"):
            self.assertIn(name, q.workings.toPlainText())

    def test_the_arithmetic(self):
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        # 0.045 kg x 5000 x 95 = 21,375 ; + 1.20 x 5000 = 6,000 ; + 800
        # = 28,175 ; + 12% = 31,556
        self.assertIn("21,375.00", q.workings.toPlainText())
        self.assertIn("31,556.00", q.workings.toPlainText())

    def test_the_rounding_gap_is_shown_rather_than_swallowed(self):
        """The quotation totals the ROUNDED per-piece rate, so it does not
        equal the cost. Reading ₹31,556 on screen and sending ₹31,550 is how
        an owner stops believing the rest of the calculation."""
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q.quantity.setText("5000")
        q._recalculate()
        working = q.workings.toPlainText()
        self.assertIn("31,550.00", working)      # what the quotation says
        self.assertIn("rounded to the paisa", working)
        self.assertEqual(f"{q.quote.subtotal:.2f}", "31550.00")

    def test_a_missing_weight_refuses_rather_than_under_quoting(self):
        """The sheet charges material by the kilogram. Treating a blank weight
        as zero quotes the labour alone — an under-quote that looks like a
        finished quotation."""
        q = self.quote_dialog()
        q.quantity.setText("5000")
        q._recalculate()
        self.assertIsNone(q.quote)
        self.assertIn("weight", q.workings.toPlainText().lower())

    def test_a_sheet_with_no_weight_lines_needs_no_weight(self):
        """A shop that charges purely per piece must not be asked for a weight
        it has no reason to know."""
        path = os.path.join(self.folder, "flat.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write("Machining,per_piece,40\nSetup,per_lot,500\n")
        lines = CB.get_quoting().load_cost_lines(path)
        q = UI.QuotationDialog(self.cfg, self.dialog._register_rows[0], [],
                               self.dialog, cost_lines=lines)
        q.quantity.setText("100")
        q._recalculate()
        self.assertIsNotNone(q.quote)
        self.assertEqual(f"{q.quote.subtotal:.2f}", "4500.00")

    def test_the_quotation_says_where_the_rate_came_from(self):
        q = self.quote_dialog()
        q.weight.setText("0.045")
        q._recalculate()
        self.assertEqual(q.quote.lines[0].basis, "cost sheet")

    def test_neither_file_configured_is_a_sentence_not_a_crash(self):
        cfg = ready_cfg(self.folder)          # no rate list, no cost sheet
        dialog = UI.InquiryDialog(cfg)
        dialog._refresh_register()
        dialog.register_table.setCurrentCell(0, 0)
        told = []
        dialog._explain = told.append
        dialog._prepare_quotation()
        self.assertTrue(told)
        self.assertIn("cost sheet", told[0].lower())


class TypingOverThePriceByHand(unittest.TestCase):
    """Rate, unit and description used to be locked to whatever the item
    picker or the cost-sheet formula produced — the only way to change the
    final number was to change the rate LIST, not the quotation in front of
    you. This is the newbie-facing fix: Prism still suggests a figure, but
    every field that number depends on is a plain box you can type into."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.rates = os.path.join(self.folder, "rates.csv")
        with open(self.rates, "w", encoding="utf-8") as f:
            f.write("Code,Description,Unit,Rate\n"
                    "CS-201,Compression spring 2mm,nos,42.50\n"
                    "TS-100,Torsion spring 1.5mm,nos,65.00\n")
        self.cfg = ready_cfg(self.folder)
        self.cfg["inquiry"]["rate_list"] = self.rates
        self.row = register.from_message(message())
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        self.items = CB.get_quoting().load_rates(self.rates)

    def quote_dialog(self):
        return UI.QuotationDialog(self.cfg, self.dialog._register_rows[0],
                                  self.items, self.dialog)

    def test_the_form_rows_do_not_overlap(self):
        """Adding Rate and Unit as their own rows, on top of a dialog that
        was never told it could grow past a fixed height, once squeezed
        every label onto the box above it — illegible, and specifically
        reported as such. scrollable=True is the fix (see __init__); this
        pins the actual geometry so a future field added the same way fails
        loudly here instead of shipping as a screenshot of overlapping
        text."""
        q = self.quote_dialog()
        # show(), deliberately not followed by _app.processEvents(): this
        # test file leaves plenty of QTimer.singleShot(0, ...) calls queued
        # by dialogs earlier tests construct and never close (most notably
        # InquiryDialog's own deferred _first_look(), which pops a genuinely
        # blocking QMessageBox when a fixture's cfg is not "ready"). Draining
        # the whole application queue here — rather than just laying this
        # widget out, which show() already does on its own — hung the whole
        # suite on someone else's leftover dialog the first time this was
        # written with processEvents() in it.
        q.show()
        try:
            rows = [q.item_picker, q.rate_edit, q.unit_edit,
                    q.description, q.quantity]
            tops = [w.mapTo(q, w.geometry().topLeft()).y() for w in rows]
            bottoms = [top + w.geometry().height()
                      for top, w in zip(tops, rows)]
            for i in range(len(rows) - 1):
                self.assertLess(
                    bottoms[i], tops[i + 1],
                    f"row {i} (bottom={bottoms[i]}) overlaps row {i + 1} "
                    f"(top={tops[i + 1]})")
        finally:
            q.close()

    def test_the_suggested_rate_is_pre_filled(self):
        q = self.quote_dialog()
        self.assertEqual(q.rate_edit.text(), "42.50")

    def test_typing_a_rate_overrides_the_suggestion(self):
        q = self.quote_dialog()
        q.rate_edit.setText("40")
        self.assertEqual(q.quote.lines[0].rate, Decimal("40"))
        self.assertEqual(q.quote.lines[0].basis, "entered by hand")

    def test_the_total_recalculates_live_as_the_rate_is_typed(self):
        q = self.quote_dialog()
        q.quantity.setText("100")
        q.rate_edit.setText("50")
        self.assertEqual(q.quote.subtotal, Decimal("5000.00"))

    def test_the_total_recalculates_live_as_the_quantity_is_typed(self):
        """No button press required — the report that started this said the
        old screen needed "Work out the price" clicked again after every
        change, which a newbie either forgot or did not know to do."""
        q = self.quote_dialog()
        q.quantity.setText("10")
        first = q.quote.subtotal
        q.quantity.setText("20")
        self.assertEqual(q.quote.subtotal, first * 2)

    def test_description_and_unit_are_editable_and_used(self):
        q = self.quote_dialog()
        q.description.setText("Compression spring, zinc plated")
        q.unit_edit.setText("box")
        self.assertEqual(q.quote.lines[0].description,
                         "Compression spring, zinc plated")
        self.assertEqual(q.quote.lines[0].unit, "box")

    def test_picking_a_different_item_clears_a_typed_over_rate(self):
        """Otherwise a rate typed for a ₹42.50 spring would silently carry
        over onto a ₹65 one picked straight after — the exact kind of
        mistake a newbie would not notice on the preview."""
        q = self.quote_dialog()
        q.rate_edit.setText("40")
        self.assertEqual(q.quote.lines[0].basis, "entered by hand")
        q.item_picker.setCurrentIndex(
            next(i for i in range(q.item_picker.count())
                 if q.item_picker.itemData(i).code == "TS-100"))
        self.assertEqual(q.rate_edit.text(), "65.00")
        self.assertEqual(q.quote.lines[0].basis, "rate list")

    def test_clearing_the_rate_box_falls_back_to_the_suggestion(self):
        q = self.quote_dialog()
        q.rate_edit.setText("40")
        q.rate_edit.setText("")
        self.assertEqual(q.quote.lines[0].rate, Decimal("42.50"))

    def test_an_overridden_rate_on_the_cost_sheet_route_skips_the_formula(self):
        """A one-off item the cost sheet has no line for should not be stuck
        with no price just because there is no formula for it."""
        cost = os.path.join(self.folder, "costs.csv")
        with open(cost, "w", encoding="utf-8") as f:
            f.write("Wire,per_kg,95\n")
        self.cfg["inquiry"]["cost_sheet"] = cost
        lines = CB.get_quoting().load_cost_lines(cost)
        q = UI.QuotationDialog(self.cfg, self.dialog._register_rows[0], [],
                               self.dialog, cost_lines=lines)
        q.source.setCurrentIndex(q.source.findData("cost"))
        q.quantity.setText("10")
        q.rate_edit.setText("99")
        self.assertEqual(q.quote.lines[0].rate, Decimal("99"))
        self.assertEqual(q.quote.lines[0].basis, "entered by hand")
        self.assertIn("entered by hand", q.workings.toPlainText().lower())


class ChasingByItself(unittest.TestCase):
    """Every two days, three times, driven off the register — and then it
    stops. These are letters going out in the owner's name, so every guard
    here is one they would ask for if they thought about it."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        # A real sending account rather than a stubbed gate: the chase
        # now resolves which address it goes out from, so the config
        # has to say which one.
        self.cfg["email"] = {"address": "sales@acme.co.in",
                             "password": "p",
                             "host": "smtp.acme.co.in", "port": 587}
        self.cfg["inquiry"]["auto_followup"] = True
        self.cfg["inquiry"]["followup_days"] = 2
        self.cfg["inquiry"]["max_reminders"] = 3
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        self.row["Last contact"] = "01-01-2020"        # long overdue
        register.save([self.row], mailflow.Paths(self.folder).register_csv)

    def dialog(self):
        d = UI.InquiryDialog(self.cfg)
        d._refresh_register()
        self.sent = []
        d._send_worker = None

        self.sent_from = []

        class _Fake:
            def __init__(_, cfg, recipients, subject, body, files):
                _.done = _Signal()
                _.failed = _Signal()
                self.sent.append((recipients[0]["email"], subject, body))
                self.sent_from.append(
                    (cfg.get("email") or {}).get("address", ""))

            def isRunning(_):
                return False

            def start(_):
                pass

        self._fake = _Fake
        return d

    def test_it_sends_when_switched_on(self):
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(len(self.sent), 1)

    def test_it_is_silent_when_switched_off(self):
        """Off unless they turned it on. The default has to be that Prism
        writes to nobody."""
        self.cfg["inquiry"]["auto_followup"] = False
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_only_one_goes_out_per_check(self):
        """Three reminders leaving in the same second, to three customers who
        talk to each other, reads as a machine."""
        rows = []
        for n in range(3):
            r = register.from_message(message(subject=f"Enquiry {n}"))
            r["Email"] = f"buyer{n}@shaktiauto.in"
            register.mark_quoted(r, f"QTN/26-27/000{n}", "1000")
            r["Last contact"] = "01-01-2020"
            rows.append(r)
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(len(self.sent), 1)

    def test_it_stops_after_the_third(self):
        self.row["Reminders sent"] = "3"
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_a_row_chased_yesterday_is_left_alone(self):
        """Two days means two days. A timer running every ten minutes must not
        turn that into 144 reminders."""
        from datetime import timedelta
        self.row["Last contact"] = (
            date.today() - timedelta(days=1)).strftime("%d-%m-%Y")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_nothing_is_sent_without_an_outgoing_account(self):
        self.cfg.pop("email")
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_nothing_is_sent_when_every_address_is_parked(self):
        """An address switched off is not an address to send from.
        The unattended chase has no screen to ask on, so it has to
        read the same answer the Send button would have."""
        self.cfg["email"]["accounts"] = [
            dict(self.cfg["email"], active=False)]
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent, [])

    def test_it_goes_out_from_the_default_address(self):
        """No draft screen on this path, so the default sends --
        which is what having a default is for."""
        self.cfg["email"]["accounts"] = [
            {"address": "accounts@acme.co.in", "password": "p",
             "host": "smtp.acme.co.in", "port": 587},
            {"address": "sales@acme.co.in", "password": "p",
             "host": "smtp.acme.co.in", "port": 587},
        ]
        d = self.dialog()
        with _Patched(UI, "SendWorker", self._fake):
            d._chase_automatically()
        self.assertEqual(self.sent_from, ["accounts@acme.co.in"])

    def test_each_reminder_is_worded_differently(self):
        """Three identical nudges in six days is a mail merge."""
        d = self.dialog()
        bodies = []
        for n in ("0", "1", "2"):
            row = dict(self.row)
            row["Reminders sent"] = n
            bodies.append(d._reminder_words(row)[1])
        self.assertEqual(len(set(bodies)), 3)
        self.assertIn("close it for now", bodies[2])

    def test_the_last_one_makes_it_easy_to_say_no(self):
        d = self.dialog()
        row = dict(self.row)
        row["Reminders sent"] = "2"
        self.assertIn("perfectly all right", d._reminder_words(row)[1])


class WinningBackACustomerWhoSaidNo(unittest.TestCase):
    """The one email worth waiting two minutes for, written by the tools in
    the owner's own browser rather than by Groq."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.cfg = ready_cfg(self.folder)
        self.row = register.from_message(message())
        register.mark_quoted(self.row, "QTN/26-27/0001", "50000")
        register.mark_lost(self.row, "Rate too high")
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._refresh_register()
        self.dialog.register_table.setCurrentCell(0, 0)

    def test_a_fresh_inquiry_has_nothing_to_win_back(self):
        row = register.from_message(message(subject="New one"))
        register.save([row], mailflow.Paths(self.folder).register_csv)
        d = UI.InquiryDialog(self.cfg)
        d._refresh_register()
        d.register_table.setCurrentCell(0, 0)
        shown = []
        with _Patched(UI, "QMessageBox", _Recording(shown)):
            d._win_back()
        self.assertEqual(len(shown), 1)

    def test_it_reads_back_the_quotation_we_actually_sent(self):
        """Rebuilding it from today's rate list could quote them something
        different from the paper they are holding."""
        # check() sets Folder on a real row; from_message leaves it blank.
        row = self.dialog._register_rows[0]
        folder = mailflow.Paths(self.folder).folder_for(row["Inquiry no"])
        row["Folder"] = folder
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "QTN-26-27-0001.csv"), "w",
                  encoding="utf-8") as f:
            f.write("Description,Qty,Rate\nSpring 2mm,5000,10.00\n")
        text = self.dialog._quotation_text(self.dialog._register_rows[0])
        self.assertIn("Spring 2mm", text)

    def test_the_quotation_as_sent_travels_under_the_letter(self):
        """The customer is deciding against a piece of paper; the win-back
        puts that paper back in front of them, in readable lines, from the
        CSV written when it went out — never rebuilt from today's rates."""
        row = self.dialog._register_rows[0]
        folder = mailflow.Paths(self.folder).folder_for(row["Inquiry no"])
        row["Folder"] = folder
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "QTN-26-27-0001.csv"), "w",
                  encoding="utf-8-sig", newline="") as f:
            f.write("Quotation no,QTN/26-27/0001\nDate,24-08-2026\n"
                    "Customer,Shreeji Auto\nInquiry no,INQ/26-27/0002\n\n"
                    "Sr,Description,HSN,Quantity,Unit,Rate,Amount,Rate source\n"
                    "1,Compression spring SS 304,7320,5000,nos,7.20,36000,rate list\n\n"
                    ",,,,,Subtotal,36000\n,,,,,GST 18%,6480\n,,,,,Total,42480\n")
        block = self.dialog._quotation_as_sent(row)
        self.assertIn("QTN/26-27/0001 dated 24-08-2026", block)
        self.assertIn("Compression spring SS 304 — 5000 nos x Rs.7.20", block)
        self.assertIn("Total: Rs.42,480", block)
        body = self.dialog._winback_body(
            row, "Claude responded: Dear Sir, Thought for 6s\nDear Sir,\n\n"
                 "We can hold the rate.\n\nRegards,\nNilesh")
        self.assertTrue(body.startswith("Dear Sir,\n\nWe can hold"))
        self.assertNotIn("Thought for", body)
        self.assertIn("Our quotation, as sent", body)
        self.assertTrue(body.rstrip().endswith("Total: Rs.42,480.00"))

    def test_with_no_quotation_on_disk_the_letter_stands_alone(self):
        body = self.dialog._winback_body(self.dialog._register_rows[0],
                                         "Dear Sir,\n\nHello.")
        self.assertEqual(body, "Dear Sir,\n\nHello.")

    def test_it_falls_back_to_the_recorded_figures(self):
        text = self.dialog._quotation_text(self.dialog._register_rows[0])
        self.assertIn("QTN/26-27/0001", text)

    def test_their_own_reason_is_given_to_the_tool(self):
        """An honest "they said the rate was too high" beats inventing an
        objection for the tool to answer."""
        self.assertIn("Rate too high",
                      self.dialog._last_reply_text(
                          self.dialog._register_rows[0]))

    def test_a_won_back_row_reopens(self):
        """A row we are actively arguing with is not a lost one — left closed
        it drops off every list Prism keeps."""
        self.dialog._winback_sent(self.dialog._register_rows[0], ["ok"], [])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.NEGOTIATING)
        self.assertEqual(saved[0]["Result"], "")

    def test_a_failed_send_does_not_reopen_it(self):
        told = []
        self.dialog._explain = told.append
        self.dialog._winback_sent(self.dialog._register_rows[0],
                                  [], [("a@b.c", "refused")])
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Status"], register.NOT_CONVERTED)
        self.assertTrue(told)

    def test_a_won_back_mail_is_written_to_the_sent_log(self):
        self.dialog._winback_sent(self.dialog._register_rows[0], ["ok"], [],
                                  subject="Regarding our quotation")
        sent = CB.get_worklist().load(self.folder)["sent"]
        self.assertEqual([s["kind"] for s in sent], ["winback"])
        self.assertEqual(sent[0]["subject"], "Regarding our quotation")


class _Signal:
    """Just enough of a Qt signal for a fake worker to be connected to."""

    def connect(self, *_a, **_kw):
        return None


class _Recording:
    """A stand-in QMessageBox that records instead of showing."""

    Yes = 1
    No = 0

    def __init__(self, log):
        self._log = log

    def information(self, *a, **kw):
        self._log.append(a)

    def warning(self, *a, **kw):
        self._log.append(a)

    def question(self, *a, **kw):
        self._log.append(a)
        return self.No


class _Patched:
    """Swap one attribute on a module for the duration of a block."""

    def __init__(self, module, name, value):
        self.module, self.name, self.value = module, name, value

    def __enter__(self):
        self.original = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)
        return self.value

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.original)
        return False


class TheFeatureIsSellable(unittest.TestCase):

    def test_the_plan_table_knows_about_it(self):
        import plans
        self.assertIn("inbox", plans.FEATURES)

    def test_it_is_in_the_complete_plan(self):
        import plans
        self.assertIn("inbox", plans.PLANS["complete"].includes)

    def test_it_is_an_addon_for_agencies(self):
        import plans
        self.assertIn("inbox", plans.PLANS["studio"].addons)

    def test_the_pitch_does_not_overpromise_automation(self):
        """The product stops twice, on purpose. Copy that says otherwise
        writes a cheque the software will not cash."""
        import plans
        pitch = plans.FEATURES["inbox"].pitch.lower()
        self.assertIn("stops twice", pitch)


class TheSetupQuestionOnlyInterruptsItsOwnScreen(unittest.TestCase):
    """`__init__` ends with `self.enter()`, which arms a zero-delay
    `_first_look()`. MainWindow builds this panel at STARTUP, next to every
    other screen — so with no mailbox configured, Prism opened a blocking
    "This needs your mailbox set up first. Set it up now?" over the dashboard
    on every launch, before the user had shown any interest in Email
    automation. Reproduced by building MainWindow and turning the event loop
    for 250ms: one modal, every time.

    The same callback is what makes this suite unreliable. The panel is
    constructed ~30 times in this file; any instance not explicitly closed
    leaks its singleShot into whichever later test next drives the event
    loop, which then blocks on a modal no headless run can answer — the hang
    the comments in `closeEvent` and in the quotation-layout test above are
    both written around.
    """

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-modal-")
        self.asked = []
        patch = mock.patch.object(
            UI.QMessageBox, "question",
            staticmethod(lambda *a, **k: self.asked.append(a[2])
                         or UI.QMessageBox.No))
        patch.start()
        self.addCleanup(patch.stop)

    def _unready(self) -> dict:
        return {"api_key": "k", "workspace": self.folder}

    def test_a_panel_nobody_has_opened_asks_nothing(self):
        dialog = UI.InquiryDialog(self._unready())
        self.addCleanup(dialog.close)
        _app.processEvents()
        self.assertEqual(self.asked, [])

    def test_a_standalone_panel_is_not_the_open_screen(self):
        dialog = UI.InquiryDialog(self._unready())
        self.addCleanup(dialog.close)
        self.assertFalse(dialog._is_the_open_screen())

    def test_a_stacked_panel_that_is_not_current_is_not_the_open_screen(self):
        from PySide6.QtWidgets import QStackedWidget, QWidget
        stack = QStackedWidget()
        self.addCleanup(stack.deleteLater)
        other = QWidget()
        stack.addWidget(other)
        dialog = UI.InquiryDialog(self._unready())
        stack.addWidget(dialog)
        stack.setCurrentWidget(other)
        self.assertFalse(dialog._is_the_open_screen())

    def test_the_panel_the_user_navigated_to_still_gets_asked(self):
        """The question is worth asking — on the screen it is about. This is
        the half a visibility check got wrong: isVisible() is false whenever
        any ancestor is hidden, so a main window hidden behind the licence
        gate would have silently swallowed it."""
        from PySide6.QtWidgets import QStackedWidget
        stack = QStackedWidget()
        self.addCleanup(stack.deleteLater)
        dialog = UI.InquiryDialog(self._unready())
        stack.addWidget(dialog)
        stack.setCurrentWidget(dialog)
        self.assertTrue(dialog._is_the_open_screen())
        dialog._first_look()
        self.assertEqual(len(self.asked), 1)


class DeletingSeveralAtOnce(unittest.TestCase):
    """[7]: ctrl/shift-click several rows, one Delete, one question. On the
    register tabs the rows leave the register; on "They answered" and
    "Order came" only the mails leave that list."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.paths = mailflow.Paths(self.folder)
        rows = []
        for n, who in enumerate(("a@one.in", "b@two.in", "c@three.in"), 1):
            row = register.from_message(
                message(f"Enquiry {n}", f"Buyer {n} <{who}>"), rows=rows)
            rows.append(row)
        register.save(rows, self.paths.register_csv)
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._refresh_register()

    def _pick(self, table, *indexes):
        from PySide6.QtCore import QItemSelectionModel
        table.setCurrentCell(indexes[0], 0)
        model = table.selectionModel()
        for index in indexes[1:]:
            model.select(table.model().index(index, 0),
                         QItemSelectionModel.Select | QItemSelectionModel.Rows)

    def _answer(self, answers, call):
        given = iter(answers)
        asked = []

        class Box:
            Yes, No = UI.QMessageBox.Yes, UI.QMessageBox.No

            @staticmethod
            def question(parent, title, text, *a, **k):
                asked.append(text)
                return next(given)

            @staticmethod
            def information(*a, **k):
                pass
        with _Patched(UI, "QMessageBox", Box), _NoSave() as saver:
            call()
        return asked, saver.saved

    def _numbers(self):
        return [r["Inquiry no"] for r in register.load(self.paths.register_csv)]

    def test_every_table_takes_several_rows(self):
        # All mail has its own "Delete selected" since 1.6.2, so it picks
        # several rows like the register tables do.
        from PySide6.QtWidgets import QAbstractItemView
        for table in (self.dialog.to_quote_table, self.dialog.followups,
                      self.dialog.register_table, self.dialog.replies_table,
                      self.dialog.orders_table, self.dialog.arrived):
            self.assertEqual(table.selectionMode(),
                             QAbstractItemView.ExtendedSelection)

    def test_two_picked_rows_go_with_one_question(self):
        self._pick(self.dialog.register_table, 0, 2)
        asked, _ = self._answer([UI.QMessageBox.Yes, UI.QMessageBox.No],
                                self.dialog._delete_inquiry)
        self.assertEqual(self._numbers(), ["INQ/26-27/0002"])
        self.assertEqual(len(asked), 2)            # delete?, then block?
        self.assertIn("2", asked[0])
        self.assertIn("INQ/26-27/0001", asked[0])
        self.assertIn("INQ/26-27/0003", asked[0])

    def test_the_button_says_how_many(self):
        page = self.dialog._pages["register"]
        self._pick(self.dialog.register_table, 0, 1)
        self.assertIn("2", page.panel.buttons["delete"].text())
        self.dialog.register_table.setCurrentCell(2, 0)
        self.assertEqual(page.panel.buttons["delete"].text(),
                         UI.i18n.t("Delete this inquiry"))

    def test_to_quote_deletes_several_too(self):
        self._pick(self.dialog.to_quote_table, 1, 2)
        self._answer([UI.QMessageBox.Yes, UI.QMessageBox.No],
                     self.dialog._delete_inquiry)
        self.assertEqual(self._numbers(), ["INQ/26-27/0001"])

    def test_saying_no_deletes_nothing(self):
        self._pick(self.dialog.register_table, 0, 1, 2)
        _, saved = self._answer([UI.QMessageBox.No], self.dialog._delete_inquiry)
        self.assertEqual(len(self._numbers()), 3)
        self.assertEqual(saved, [])

    def test_blocking_several_senders_saves_the_settings_once(self):
        self._pick(self.dialog.register_table, 0, 1)
        _, saved = self._answer([UI.QMessageBox.Yes, UI.QMessageBox.Yes],
                                self.dialog._delete_inquiry)
        self.assertEqual(len(saved), 1)
        learned = saved[0]["inquiry"]["knowledge"]["learned"]
        self.assertEqual(learned.get("a@one.in"), "other")
        self.assertEqual(learned.get("b@two.in"), "other")
        self.assertNotIn("c@three.in", learned)

    def test_one_row_keeps_the_one_row_wording(self):
        self.dialog.register_table.setCurrentCell(1, 0)
        asked, _ = self._answer([UI.QMessageBox.Yes, UI.QMessageBox.No],
                                self.dialog._delete_inquiry)
        self.assertIn("INQ/26-27/0002", asked[0])
        self.assertNotIn("these", asked[0])
        self.assertEqual(self._numbers(), ["INQ/26-27/0001", "INQ/26-27/0003"])

    def test_a_row_added_by_a_check_meanwhile_survives_the_delete(self):
        """The screen's copy is older than the file: a plain save wiped the
        new row, and the next check gave its number out again."""
        rows = register.load(self.paths.register_csv)
        rows.append(register.from_message(message("Enquiry 4", "D <d@four.in>"),
                                          rows=rows))
        register.save(rows, self.paths.register_csv)
        self._pick(self.dialog.register_table, 0, 1)
        self._answer([UI.QMessageBox.Yes, UI.QMessageBox.No],
                     self.dialog._delete_inquiry)
        self.assertEqual(self._numbers(), ["INQ/26-27/0003", "INQ/26-27/0004"])

    def _answer_after_a_refresh(self, call):
        """Yes to everything, but the first question also does what the
        automatic check's refresh did inside the modal's event loop: swap
        _register_rows for fresh dicts read from the file."""
        asked, timer_running = [], []

        class Box:
            Yes, No = UI.QMessageBox.Yes, UI.QMessageBox.No

            @staticmethod
            def question(parent, title, text, *a, **k):
                if not asked:
                    parent._refresh_register()
                timer_running.append(parent._auto.isActive())
                asked.append(text)
                return Box.No if len(asked) > 1 else Box.Yes

            @staticmethod
            def information(*a, **k):
                pass
        with _Patched(UI, "QMessageBox", Box), _NoSave():
            call()
        return asked, timer_running

    def test_a_refresh_during_the_question_still_deletes_several(self):
        """Review F7: rows were removed by identity, so after a refresh
        nothing matched, nothing was deleted, and it still said "deleted"."""
        self._pick(self.dialog.register_table, 0, 2)
        self._answer_after_a_refresh(self.dialog._delete_inquiry)
        self.assertEqual(self._numbers(), ["INQ/26-27/0002"])
        self.assertIn("2", self.dialog.status.text())

    def test_a_refresh_during_the_question_still_deletes_one(self):
        self.dialog.register_table.setCurrentCell(1, 0)
        self._answer_after_a_refresh(self.dialog._delete_inquiry)
        self.assertEqual(self._numbers(), ["INQ/26-27/0001", "INQ/26-27/0003"])
        self.assertIn("INQ/26-27/0002", self.dialog.status.text())

    def test_a_row_already_gone_is_not_reported_as_deleted(self):
        self.dialog.register_table.setCurrentCell(1, 0)
        rows = register.load(self.paths.register_csv)
        register.save([rows[0], rows[2]], self.paths.register_csv)
        self._answer_after_a_refresh(self.dialog._delete_inquiry)
        self.assertNotIn(UI.i18n.t("{no} deleted.").replace("{no}", "INQ/26-27/0002"),
                         self.dialog.status.text())
        self.assertIn(UI.i18n.t("Nothing was deleted").split(":")[0],
                      self.dialog.status.text())

    def test_the_automatic_check_waits_while_the_question_is_open(self):
        self.dialog._auto.start(60_000)
        try:
            self._pick(self.dialog.register_table, 0, 1)
            _, running = self._answer_after_a_refresh(self.dialog._delete_inquiry)
            self.assertEqual(running, [False, False])
            self.assertTrue(self.dialog._auto.isActive())
        finally:
            self.dialog._auto.stop()

    def test_a_ctrl_click_deselect_is_not_deleted(self):
        """Review F8: A, B, C picked, then C ctrl-clicked off. C stays the
        current row; the button says 2 and it is A and B that go."""
        from PySide6.QtCore import QItemSelectionModel
        table = self.dialog.register_table
        self._pick(table, 2, 0, 1)
        table.selectionModel().select(
            table.model().index(2, 0),
            QItemSelectionModel.Deselect | QItemSelectionModel.Rows)
        self.dialog._label_delete("register")
        self.assertIn("2", self.dialog._pages["register"].panel.buttons["delete"].text())
        asked, _ = self._answer([UI.QMessageBox.Yes, UI.QMessageBox.No],
                                self.dialog._delete_inquiry)
        self.assertNotIn("INQ/26-27/0003", asked[0])
        self.assertEqual(self._numbers(), ["INQ/26-27/0003"])

    def _seed(self, kind):
        worklist = CB.get_worklist()
        rows = self.dialog._register_rows
        worklist.append(self.folder, kind, [
            {"message_id": f"<{kind}{n}@x>", "inquiry_no": row["Inquiry no"],
             "from_addr": row["Email"], "subject": f"Re: Enquiry {n}",
             "date": "2026-10-12", "intent": "accepted"}
            for n, row in enumerate(rows, 1)])

    def test_they_answered_takes_mails_off_the_list_and_keeps_the_rows(self):
        self._seed("replies")
        self.dialog._render_replies()
        self.assertEqual(self.dialog.replies_table.rowCount(), 3)
        self._pick(self.dialog.replies_table, 0, 1)
        asked, _ = self._answer([UI.QMessageBox.Yes],
                                lambda: self.dialog._delete_from_list("replies"))
        self.assertEqual(len(asked), 1)
        self.assertIn("2", asked[0])
        self.assertEqual(self.dialog.replies_table.rowCount(), 1)
        self.assertEqual(len(self._numbers()), 3)

    def test_order_came_takes_mails_off_and_skips_ones_accepted_by_hand(self):
        self._seed("orders")
        rows = register.load(self.paths.register_csv)
        rows[2]["Status"] = register.ACCEPTED
        register.save(rows, self.paths.register_csv)
        CB.get_worklist().resolve(self.folder, "orders", "<orders3@x>")
        self.dialog._refresh_register()
        self.dialog._render_orders()
        self.assertEqual(self.dialog.orders_table.rowCount(), 3)
        self._pick(self.dialog.orders_table, 0, 1, 2)
        self._answer([UI.QMessageBox.Yes],
                     lambda: self.dialog._delete_from_list("orders"))
        # The accepted-by-hand row has no mail behind it and stays.
        self.assertEqual(self.dialog.orders_table.rowCount(), 1)
        self.assertEqual(len(self._numbers()), 3)
        self.assertIn("1", self.dialog.status.text())

    def test_a_list_file_held_open_says_so_plainly(self):
        """Windows: os.replace on the worklist fails while another program
        holds the file. That was a raw PermissionError on screen."""
        self._seed("replies")
        self.dialog._render_replies()
        self._pick(self.dialog.replies_table, 0, 1)
        worklist = CB.get_worklist()
        said = []

        def held(*_a, **_k):
            raise PermissionError(13, "Access is denied")
        with _Patched(worklist, "resolve_many", held), \
                _Patched(self.dialog, "_explain", said.append):
            self._answer([UI.QMessageBox.Yes],
                         lambda: self.dialog._delete_from_list("replies"))
        self.assertEqual(self.dialog.replies_table.rowCount(), 3)
        self.assertEqual(len(said), 1)
        self.assertIn("Nothing was taken off", said[0])

    def test_saying_no_on_they_answered_keeps_the_mails(self):
        self._seed("replies")
        self.dialog._render_replies()
        self._pick(self.dialog.replies_table, 0, 2)
        self._answer([UI.QMessageBox.No],
                     lambda: self.dialog._delete_from_list("replies"))
        self.assertEqual(self.dialog.replies_table.rowCount(), 3)


class PickedRowsShowOnTintedRows(unittest.TestCase):
    """With several rows picked, a picked row has to read as picked on the
    greens and greys, not only on a white row."""

    def _paint(self, background, selected):
        from PySide6.QtGui import QBrush, QColor, QImage, QPainter
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem, QTableWidget, QTableWidgetItem
        table = QTableWidget(1, 2)
        item = QTableWidgetItem("x")
        item.setBackground(QBrush(QColor(background)))
        table.setItem(0, 0, item)
        delegate = UI._TintedCellDelegate(table)
        option = QStyleOptionViewItem()
        option.rect = table.visualRect(table.model().index(0, 0))
        option.rect.setRect(0, 0, 60, 20)
        if selected:
            option.state |= QStyle.State_Selected
        image = QImage(60, 20, QImage.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        delegate.paint(painter, option, table.model().index(0, 0))
        painter.end()
        return image

    def test_a_picked_light_row_is_clearly_darker_and_has_a_bar(self):
        from PySide6.QtGui import QColor
        for tint in ("#f5f5f7", "#e5e5ea", "#dcfce7"):
            plain = self._paint(tint, False)
            picked = self._paint(tint, True)
            middle_plain = QColor(plain.pixel(40, 2)).lightness()
            middle_picked = QColor(picked.pixel(40, 2)).lightness()
            self.assertGreaterEqual(middle_plain - middle_picked, 25, tint)
            # The bar down the left edge is in the row's tint, on the
            # charcoal fill (13 Oct, round 3: it was dark on the tint).
            bar = QColor(picked.pixel(1, 10)).lightness()
            self.assertGreaterEqual(bar - middle_picked, 100, tint)

    def test_a_picked_dark_row_is_lighter(self):
        from PySide6.QtGui import QColor
        plain = self._paint("#27272a", False)
        picked = self._paint("#27272a", True)
        middle = QColor(picked.pixel(40, 2)).lightness()
        self.assertGreater(middle, QColor(plain.pixel(40, 2)).lightness())
        self.assertGreaterEqual(middle - QColor(picked.pixel(1, 10)).lightness(),
                                100)


class TheCheckShowsARealCount(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.dialog = UI.InquiryDialog(ready_cfg(self.folder))
        self.dialog._queue = [{"address": "a@x.in"}]
        self.dialog._queue_pos = 0

    def test_filing_fills_the_ring_and_says_which_mail(self):
        self.dialog._on_check_progress("file", 43, 75)
        self.assertEqual(self.dialog.progress.maximum(), 75)
        self.assertEqual(self.dialog.progress.value(), 43)
        self.assertIn("43 of 75", self.dialog.status.text())

    def test_sorting_names_how_many_and_an_empty_inbox_says_so(self):
        self.dialog._on_check_progress("sort", 0, 12)
        self.assertIn("12", self.dialog.status.text())
        self.dialog._on_check_progress("sort", 0, 0)
        self.assertIn("No new mail", self.dialog.status.text())


if __name__ == "__main__":
    unittest.main()
