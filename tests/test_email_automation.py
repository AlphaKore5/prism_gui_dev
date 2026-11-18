"""Several mailboxes, one register, and the purchase-order stop.

tests/test_mailflow.py holds the engine to its promises for ONE mailbox;
tests/test_inquiry_ui.py holds the screen to its promises for one. These
defend what the Email inquiry automation umbrella added on top, and each property is
one that would fail silently:

  · **Every mailbox keeps its own bookmark.** Two accounts sharing one
    last-UID would skip or re-import each other's mail, and the symptom —
    an inquiry that never appeared — is indistinguishable from a quiet week.
  · **The walk survives one dead mailbox and stops for one locked register.**
    Opposite responses on purpose: a dead server is that account's problem,
    a locked register would refuse every account after it identically.
  · **The register says which mailbox an inquiry came to.** With sales@,
    info@ and the owner's own address feeding one file, "who is this
    customer talking to" is the first question the sheet gets asked.
  · **A password being refused stops THAT mailbox being hammered — not the
    others being read.**
  · **The PO stop is a person.** Reading the order needs a button, accepting
    it needs a button, and the privacy switch keeps the order's text on this
    computer even though that costs the automatic reading.

Same harness rules as test_inquiry_ui: config.save is refused module-wide
unless a test takes it over, and CONFIG_PATH points at scratch — a suite that
writes the developer's real ~/.prism/config.json has happened here once
already.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import core_bridge as CB  # noqa: E402
from core import inbox, mailflow, quoting, register, triage  # noqa: E402
from addons.inquiry import dialog as UI  # noqa: E402
from addons.inquiry.setup import (  # noqa: E402
    InquirySetupDialog, accounts_of, is_ready)

_app = QApplication.instance() or QApplication([])

_REAL_SAVE = CB.config.save
_REAL_CONFIG_PATH = CB.config.CONFIG_PATH
_SCRATCH = tempfile.mkdtemp(prefix="prism-test-emailauto-")


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


def two_mailbox_cfg(folder: str) -> dict:
    return {"api_key": "gsk_test", "inquiry": {
        "accounts": [
            {"address": "sales@acme.co.in", "password": "p1",
             "host": "mail.acme.co.in", "port": 993, "folder": "INBOX",
             "state": {"uidvalidity": 1, "last_uid": 10}},
            {"address": "info@acme.co.in", "password": "p2",
             "host": "mail.acme.co.in", "port": 993, "folder": "INBOX",
             "state": {"uidvalidity": 2, "last_uid": 20}},
        ],
        "folder": folder, "rate_list": "", "cost_sheet": "",
        "company": "Acme Springs", "signature": "Sales",
        "terms": {"gst_percent": 18, "validity_days": 15,
                  "payment": "advance", "delivery": "3 weeks"},
        "followup_days": 3, "local_only": True,
        "knowledge": {"own_domains": ["acme.co.in"], "customers": [],
                      "vendors": [], "learned": {}},
    }}


class _Signal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in list(self._slots):
            slot(*args)


class _FakeCheckWorker:
    """Stands in for InboxCheckWorker: records what the dialog handed it,
    answers synchronously from a script keyed by address."""

    results: dict = {}
    seen: list = []

    def __init__(self, cfg, root, *, state=None, knowledge=None, **kwargs):
        self.address = (cfg.get("inbox") or {}).get("address", "")
        _FakeCheckWorker.seen.append(
            (self.address, int(getattr(state, "last_uid", 0) or 0),
             dict(getattr(knowledge, "learned", {}) or {})))
        self.done = _Signal()
        self.failed = _Signal()
        self.progress = _Signal()       # the real worker reports per-mail progress

    def start(self):
        result = _FakeCheckWorker.results.get(self.address)
        if result is None:
            result = mailflow.Result()
        self.done.emit(result)

    def isRunning(self):
        return False


def _result(*, error="", fetched=0, last_uid=0, uidvalidity=1, learned=None,
            new_rows=(), orders=()):
    out = mailflow.Result(error=error, fetched=fetched)
    out.state = inbox.State(uidvalidity=uidvalidity, last_uid=last_uid)
    out.knowledge = triage.Knowledge(learned=dict(learned or {}))
    for number in new_rows:
        out.new_inquiries.append(
            mailflow.Item("inquiry", None, {"Inquiry no": number}))
    for number in orders:
        out.orders.append(
            mailflow.Item("order", None, {"Inquiry no": number},
                          note="a purchase order may be attached"))
    return out


# ════════════════════════════════════════════════════════════════════════════
class TheAccountsList(unittest.TestCase):
    def test_a_legacy_config_reads_as_one_account_with_its_bookmark(self):
        """An existing customer's first multi-mailbox check must carry on
        from where their last single-mailbox check stopped — not re-import a
        month of mail."""
        cfg = {"inquiry": {
            "account": {"address": "a@b.c", "password": "p", "host": "h"},
            "state": {"uidvalidity": 7, "last_uid": 900}}}
        accounts = accounts_of(cfg)
        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["address"], "a@b.c")
        self.assertEqual(accounts[0]["state"]["last_uid"], 900)

    def test_the_list_wins_over_the_legacy_mirror(self):
        cfg = {"inquiry": {
            "accounts": [{"address": "new@b.c", "password": "p", "host": "h"}],
            "account": {"address": "old@b.c", "password": "p", "host": "h"}}}
        self.assertEqual([a["address"] for a in accounts_of(cfg)], ["new@b.c"])

    def test_copies_come_back_not_references(self):
        cfg = {"inquiry": {"accounts": [
            {"address": "a@b.c", "password": "p", "host": "h", "state": {}}]}}
        accounts_of(cfg)[0]["address"] = "changed@b.c"
        self.assertEqual(cfg["inquiry"]["accounts"][0]["address"], "a@b.c")

    def test_is_ready_understands_both_shapes(self):
        folder = tempfile.mkdtemp(prefix="prism-test-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        legacy = {"inquiry": {
            "account": {"address": "a@b.c", "password": "p", "host": "h"},
            "folder": folder}}
        listed = two_mailbox_cfg(folder)
        self.assertTrue(is_ready(legacy))
        self.assertTrue(is_ready(listed))
        self.assertFalse(is_ready({}))


class SetupKeepsSeveralMailboxes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)

    def test_adding_a_second_mailbox_saves_both(self):
        dialog = InquirySetupDialog({})
        dialog.addr.setText("sales@acme.co.in")
        dialog.password.setText("p1")
        dialog._add_mailbox()
        dialog.addr.setText("info@acme.co.in")
        dialog.password.setText("p2")
        dialog.work_folder.edit.setText(self.folder)
        with _NoSave():
            dialog._save()
        saved = dialog.cfg["inquiry"]
        self.assertEqual([a["address"] for a in saved["accounts"]],
                         ["sales@acme.co.in", "info@acme.co.in"])
        for account in saved["accounts"]:
            self.assertTrue(account["host"], account["address"])

    def test_the_legacy_keys_mirror_the_first_mailbox(self):
        """A config written here still opens in a Prism from before the list
        — and in every reader that has not learned the list yet."""
        cfg = two_mailbox_cfg(self.folder)
        dialog = InquirySetupDialog(cfg)
        with _NoSave():
            dialog._save()
        saved = dialog.cfg["inquiry"]
        self.assertEqual(saved["account"]["address"], "sales@acme.co.in")
        self.assertNotIn("state", saved["account"])
        self.assertEqual(saved["state"]["last_uid"], 10)

    def test_each_mailbox_keeps_its_own_saved_password(self):
        """Blank means "keep what is saved" — per mailbox, not per screen.
        Losing info@'s password because sales@'s box was left blank is the
        kind of loss nobody can diagnose."""
        dialog = InquirySetupDialog(two_mailbox_cfg(self.folder))
        self.assertEqual(dialog.mailboxes.count(), 2)
        dialog.mailboxes.setCurrentRow(1)
        with _NoSave():
            dialog._save()
        saved = dialog.cfg["inquiry"]["accounts"]
        self.assertEqual(saved[0]["password"], "p1")
        self.assertEqual(saved[1]["password"], "p2")

    def test_every_bookmark_survives_a_visit_to_setup(self):
        dialog = InquirySetupDialog(two_mailbox_cfg(self.folder))
        with _NoSave():
            dialog._save()
        saved = dialog.cfg["inquiry"]["accounts"]
        self.assertEqual(saved[0]["state"]["last_uid"], 10)
        self.assertEqual(saved[1]["state"]["last_uid"], 20)

    def test_removing_a_mailbox_keeps_the_others(self):
        dialog = InquirySetupDialog(two_mailbox_cfg(self.folder))
        dialog.mailboxes.setCurrentRow(1)
        with mock.patch.object(QMessageBox, "question",
                               return_value=QMessageBox.Yes):
            dialog._remove_mailbox()
        with _NoSave():
            dialog._save()
        self.assertEqual([a["address"]
                          for a in dialog.cfg["inquiry"]["accounts"]],
                         ["sales@acme.co.in"])

    def test_a_list_of_one_hides_itself(self):
        """One mailbox above a form asking for that same mailbox reads as two
        steps where there is only one thing to do — and one mailbox is every
        existing customer on the day they update."""
        alone = InquirySetupDialog({})
        self.assertFalse(alone.mailboxes.isVisibleTo(alone))
        several = InquirySetupDialog(two_mailbox_cfg(self.folder))
        self.assertTrue(several.mailboxes.isVisibleTo(several))


class TheWalkAcrossMailboxes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.cfg = two_mailbox_cfg(self.folder)
        _FakeCheckWorker.results = {}
        _FakeCheckWorker.seen = []
        patcher = mock.patch.object(UI, "InboxCheckWorker", _FakeCheckWorker)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dialog = UI.InquiryDialog(self.cfg)
        self.dialog._explain = lambda message: self.explained.append(message)
        self.explained = []

    def tearDown(self):
        self.dialog._auto.stop()

    def test_every_mailbox_is_read_with_its_own_bookmark(self):
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(fetched=1, last_uid=11),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2),
        }
        with _NoSave():
            self.dialog.check_now()
        self.assertEqual([(a, uid) for a, uid, _k in _FakeCheckWorker.seen],
                         [("sales@acme.co.in", 10), ("info@acme.co.in", 20)])

    def test_each_bookmark_is_banked_against_its_own_mailbox(self):
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(fetched=1, last_uid=11),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2),
        }
        with _NoSave():
            self.dialog.check_now()
        accounts = self.dialog.cfg["inquiry"]["accounts"]
        self.assertEqual(accounts[0]["state"]["last_uid"], 11)
        self.assertEqual(accounts[1]["state"]["last_uid"], 21)
        # The legacy mirror follows the first mailbox.
        self.assertEqual(self.dialog.cfg["inquiry"]["state"]["last_uid"], 11)

    def test_what_one_check_learned_the_next_already_knows(self):
        """The sorter's knowledge is shared: a sender corrected on sales@ is
        the same sender on info@, and teaching Prism twice is a chore."""
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(fetched=1, last_uid=11,
                                        learned={"spam@x.y": "promotion"}),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2),
        }
        with _NoSave():
            self.dialog.check_now()
        second = _FakeCheckWorker.seen[1]
        self.assertEqual(second[2].get("spam@x.y"), "promotion")

    def test_one_dead_mail_server_does_not_stop_the_other_mailbox(self):
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(error="The mail server didn't answer."),
            "info@acme.co.in": _result(fetched=2, last_uid=22, uidvalidity=2),
        }
        with _NoSave():
            self.dialog.check_now()
        self.assertEqual(len(_FakeCheckWorker.seen), 2,
                         "the walk stopped at the dead mailbox")
        self.assertEqual(
            self.dialog.cfg["inquiry"]["accounts"][1]["state"]["last_uid"], 22)
        # The failure names the mailbox it belongs to — "the mail server
        # didn't answer" is only half a sentence when there are two servers.
        self.assertTrue(self.explained)
        self.assertIn("sales@acme.co.in", self.explained[0])

    def test_a_locked_register_stops_the_walk(self):
        """The same locked file would refuse every account after it, and no
        bookmark has moved — so nothing is lost by stopping, and the owner is
        spared one identical sentence per mailbox."""
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(
                error="The inquiry register is open in Excel — close it "
                      "there and check again."),
            "info@acme.co.in": _result(fetched=2, last_uid=22),
        }
        with _NoSave():
            self.dialog.check_now()
        self.assertEqual(len(_FakeCheckWorker.seen), 1)
        # info@'s bookmark is exactly where it was.
        self.assertEqual(
            self.dialog.cfg["inquiry"]["accounts"][1]["state"]["last_uid"], 20)

    def test_the_register_says_which_mailbox_an_inquiry_came_to(self):
        rows = [dict(register.blank_row(), **{"Inquiry no": "INQ/26-27/0001"}),
                dict(register.blank_row(), **{"Inquiry no": "INQ/26-27/0002"})]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(fetched=1, last_uid=11,
                                        new_rows=("INQ/26-27/0001",)),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2,
                                       orders=("INQ/26-27/0002",)),
        }
        with _NoSave():
            self.dialog.check_now()
        saved = {row["Inquiry no"]: row.get("Mailbox", "")
                 for row in register.load(
                     mailflow.Paths(self.folder).register_csv)}
        self.assertEqual(saved["INQ/26-27/0001"], "sales@acme.co.in")
        self.assertEqual(saved["INQ/26-27/0002"], "info@acme.co.in")

    def test_a_stamp_never_rewrites_where_an_inquiry_arrived(self):
        """A purchase order landing on a different address later must not
        move the inquiry — where the customer first wrote is a fact."""
        rows = [dict(register.blank_row(),
                     **{"Inquiry no": "INQ/26-27/0001",
                        "Mailbox": "sales@acme.co.in"})]
        register.save(rows, mailflow.Paths(self.folder).register_csv)
        _FakeCheckWorker.results = {
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2,
                                       orders=("INQ/26-27/0001",)),
        }
        with _NoSave():
            self.dialog.check_now()
        saved = register.load(mailflow.Paths(self.folder).register_csv)
        self.assertEqual(saved[0]["Mailbox"], "sales@acme.co.in")

    def test_a_refused_password_sidelines_that_mailbox_only(self):
        rejection = "[AUTHENTICATIONFAILED] Invalid credentials"
        self.assertTrue(inbox.is_auth_failure(rejection),
                        "the fixture must read as a rejected sign-in")
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(error=rejection),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2),
        }
        with _NoSave():
            for _ in range(3):
                self.dialog.check_now(quiet=True)
        _FakeCheckWorker.seen = []
        with _NoSave():
            self.dialog.check_now(quiet=True)
        self.assertEqual([a for a, _uid, _k in _FakeCheckWorker.seen],
                         ["info@acme.co.in"],
                         "the healthy mailbox stopped being read too")

    def test_pressing_check_now_lets_every_mailbox_try_again(self):
        """A person pressing the button is asserting the credentials are
        right — which is also how they get going after fixing a password."""
        rejection = "[AUTHENTICATIONFAILED] Invalid credentials"
        _FakeCheckWorker.results = {
            "sales@acme.co.in": _result(error=rejection),
            "info@acme.co.in": _result(fetched=1, last_uid=21, uidvalidity=2),
        }
        with _NoSave():
            for _ in range(3):
                self.dialog.check_now(quiet=True)
        _FakeCheckWorker.seen = []
        with _NoSave():
            self.dialog.check_now(quiet=False)
        self.assertIn("sales@acme.co.in",
                      [a for a, _uid, _k in _FakeCheckWorker.seen])


class TheSentQuotationReadsBack(unittest.TestCase):
    """The PO comparison is only as honest as the quotation it compares
    against — which is the CSV written at send time, not today's rate list."""

    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.quote = quoting.Quotation(
            number="QTN/26-27/0042", date=date(2026, 8, 11),
            customer="Shakti Auto", inquiry_no="INQ/26-27/0087",
            lines=[quoting.QuoteLine("Compression spring 2mm",
                                     Decimal(5000), "nos",
                                     Decimal("28.50"), "7320")],
            terms=quoting.Terms(gst_percent=Decimal(18)))
        self.path = os.path.join(self.folder, "QTN-26-27-0042.csv")
        quoting.write_csv(self.quote, self.path)
        self.row = {"Folder": self.folder, "Quotation no": "QTN/26-27/0042"}

    def test_what_was_written_reads_back_to_the_paisa(self):
        read = UI._read_sent_quotation(self.row)
        self.assertIsNotNone(read)
        self.assertEqual(read.total, self.quote.total)
        self.assertEqual(len(read.lines), 1)
        self.assertEqual(read.lines[0].rate, Decimal("28.50"))

    def test_a_file_that_does_not_add_up_is_refused(self):
        """A hand-edited or misparsed file must produce NO comparison, never
        a wrong one — differences the customer never made would be flagged
        at them."""
        with open(self.path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(text.replace("28.50", "29.50", 1))
        self.assertIsNone(UI._read_sent_quotation(self.row))

    def test_a_missing_file_is_none_not_an_error(self):
        self.assertIsNone(UI._read_sent_quotation(
            {"Folder": self.folder, "Quotation no": "QTN/26-27/9999"}))

    def test_the_comparison_flags_the_reduced_rate(self):
        po = CB.get_po()
        order = po.PurchaseOrder(
            number="SAC/PO/4471", buyer="Shakti Auto",
            lines=[po.POLine("spring", Decimal(5000), "nos",
                             Decimal("27.60"), Decimal(0)).settled()])
        read = UI._read_sent_quotation(self.row)
        differences = po.compare(order, read)
        money = [d for d in differences if d.kind == po.MONEY]
        self.assertTrue(money, "ninety paise on five thousand walked past")


class ThePurchaseOrderStop(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="prism-test-")
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        self.cfg = two_mailbox_cfg(self.folder)
        self.dialog = UI.InquiryDialog(self.cfg)

    def tearDown(self):
        self.dialog._auto.stop()

    def _register_with_quoted_row(self) -> dict:
        row = dict(register.blank_row(), **{
            "Inquiry no": "INQ/26-27/0087", "Customer": "Shakti Auto",
            "Email": "purchase@shaktiauto.in", "Status": register.ACCEPTED,
            "Quotation no": "QTN/26-27/0042",
            "Quotation value": "168150.00"})
        register.save([row], mailflow.Paths(self.folder).register_csv)
        self.dialog._refresh_register()
        return self.dialog._register_rows[0]

    def test_accepting_writes_converted_with_the_po_number_and_value(self):
        row = self._register_with_quoted_row()
        self.dialog._po_accepted(row, "SAC/PO/4471", "1,38,000/-",
                                 "20-08-2026")
        saved = register.load(mailflow.Paths(self.folder).register_csv)[0]
        self.assertEqual(saved["Status"], register.CONVERTED)
        self.assertEqual(saved["PO number"], "SAC/PO/4471")
        self.assertEqual(saved["PO date"], "20-08-2026")
        self.assertEqual(register.money(saved["Order value"]),
                         Decimal("138000.00"))

    def test_the_privacy_switch_keeps_the_po_on_this_computer(self):
        """local_only means every AI call on mail content — a purchase order
        is mail content. The reading is handed to the person, never silently
        skipped and never silently sent out anyway."""
        row = self._register_with_quoted_row()
        item = mailflow.Item("order", UI_MESSAGE(), row, self.folder)
        self.dialog._orders = [item]
        self.dialog.orders_table.setRowCount(1)
        self.dialog.orders_table.setCurrentCell(0, 0)

        shown = {}
        self.dialog._show_po = (
            lambda order, target, advice="", differences=None:
            shown.update(order=order, advice=advice))
        with mock.patch.object(UI, "POReadWorker",
                               side_effect=AssertionError(
                                   "the PO text left the computer")):
            self.dialog._review_po()
        self.assertIsNone(shown["order"])
        self.assertIn("computer", shown["advice"].lower())

    def test_a_po_file_asks_the_shared_consent_once_and_cancel_sends_nothing(self):
        """Stage 25: a PO FILE leaving the computer goes through the same
        'Send to Prism AI?' question as every drawing; Cancel reads nothing."""
        from widgets import send_to_ai
        from dialogs.send_consent import SendConsentDialog as SCD
        send_to_ai.reset_session()
        pdf = os.path.join(self.folder, "PO 4471.pdf")
        with open(pdf, "wb") as f:
            f.write(b"%PDF-1.4 fake")
        self.dialog.cfg["api_key"] = "k"
        self.dialog.cfg["inquiry"]["local_only"] = False
        row = self._register_with_quoted_row()
        item = mailflow.Item("order", UI_MESSAGE(), row, self.folder)
        self.dialog._orders = [item]
        self.dialog.orders_table.setRowCount(1)
        self.dialog.orders_table.setCurrentCell(0, 0)
        shown = {}
        self.dialog._show_po = (
            lambda order, target, advice="", differences=None:
            shown.update(order=order, advice=advice))
        fake_po = mock.Mock()
        fake_po.text_from.return_value = "PO text"
        with mock.patch.object(SCD, "exec", return_value=SCD.Rejected) as ex, \
                mock.patch.object(self.dialog, "_po_file", return_value=pdf), \
                mock.patch.object(UI.CB, "get_po", return_value=fake_po), \
                mock.patch.object(UI, "POReadWorker",
                                  side_effect=AssertionError("sent after Cancel")):
            self.dialog._review_po()
        ex.assert_called_once()
        self.assertIsNone(shown["order"])
        self.assertIn("Nothing was sent", shown["advice"])
        # Yes: the question is asked, the worker starts, the 'sending' card is up.
        worker = mock.MagicMock()
        with mock.patch.object(SCD, "exec", return_value=SCD.Accepted) as ex, \
                mock.patch.object(self.dialog, "_po_file", return_value=pdf), \
                mock.patch.object(UI.CB, "get_po", return_value=fake_po), \
                mock.patch.object(UI, "POReadWorker", return_value=worker):
            self.dialog._review_po()
            self.dialog._review_po()
        ex.assert_called_once()                       # remembered for the session
        self.assertTrue(worker.start.called)
        self.assertIsNotNone(self.dialog._po_sending)
        self.assertEqual(self.dialog._po_sending.preview.name.text(), "PO 4471.pdf")
        self.dialog._po_read_failed("x", row)
        self.assertIsNone(self.dialog._po_sending)

    def test_the_review_refuses_to_accept_without_number_and_value(self):
        dialog = UI._POReviewDialog({"Inquiry no": "INQ/26-27/0087"})
        with mock.patch.object(QMessageBox, "information") as told:
            dialog._accept()
        self.assertTrue(told.called)
        self.assertEqual(dialog.result(), 0, "accepted with nothing to file")


def UI_MESSAGE():
    """A minimal order mail: a body and no attachments, so the review path
    exercises the body fallback."""
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "PO for spring"
    msg["From"] = "purchase@shaktiauto.in"
    msg["Date"] = "Thu, 20 Aug 2026 09:14:00 +0530"
    msg["Message-ID"] = "<po-1@x>"
    msg.set_content("Please find our order: 5000 nos at Rs.27.60.")
    return inbox.parse_message(msg.as_bytes(), uid=9)


class TheRailStillSellsIt(unittest.TestCase):
    def test_the_shelf_says_email_automation_and_the_gate_is_unchanged(self):
        """The name moved with the customer's own words; the licence feature
        underneath did not move at all — a renamed SKU would strand every
        existing key."""
        from widgets.sidebar import ADDONS
        entry = next(e for e in ADDONS if e[0] == "inquiry")
        self.assertEqual(entry[1], "Email inquiry automation")
        self.assertEqual(entry[4], "inbox")


if __name__ == "__main__":
    unittest.main(verbosity=2)
