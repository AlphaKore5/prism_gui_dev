"""Email — sending from your own account, to one person or to a list.

GUI equivalent of the CLI's /email setup and /email <goal>, rebuilt so the
form reads like a letter: To, Subject, Message, top to bottom, all visible
from the moment the window opens. The old window opened on a free-text box
("What email do you want to send?") and folded the address list away under
"Edit the recipient list (optional)" — an owner who wanted to write to one
supplier could not find where the address went.

Recipients come from the To line (typed, any separator), from a CSV
(name, email), or from an attached CSV handed over by the workbench. The
CSV is parsed on this machine and never shown to any AI. Drafting stays
optional: a one-line brief and "Write it for me" runs the same pipeline
stage as before through an ordinary AutomationWorker.
"""
from __future__ import annotations
import os
import re
import time
from PySide6.QtCore import QDateTime, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDateTimeEdit, QDialog,
    QDoubleSpinBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSizePolicy, QSpinBox, QStyle, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QFrame,
)

import core_bridge as CB
import email_config
import i18n
from widgets.loader import Loader, busy_button
from addons.email import sent_log
from addons.email.panel import linkify, pillify
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from workers import AutomationWorker, SendWorker, VerifyWorker

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A clock format, not copy: kept out of every i18n.t() call so the string
# extractor does not offer "%d %b %H:%M" to a translator.
_WHEN_FMT = "%d %b %H:%M"


class EmailSetupDialog(PrismDialog):
    """The sending accounts (mirrors CLI's /email setup).

    Several addresses, not one. A firm sends its quotations from sales@ and
    its payment chasers from accounts@, and until this screen took a list the
    whole product sent everything from whichever single address had been
    typed in first.

    The list is `cfg["email"]["accounts"]`; the account at the top is the
    default sender and is mirrored into the old top-level keys, so a config
    written here still opens in a Prism from before the list, and the
    engine's own `is_configured()` keeps answering about the account that
    will actually be used. `email_config.account_block()` owns that rule.

    The list hides itself at one account -- which is every existing customer
    on the day they update, and for them this is the screen it always was.
    """

    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("Email account"),
            i18n.t("Send from your own account, one copy per recipient."),
            icon="mail", parent=parent, closable=False)
        self.setWindowTitle("Email account setup")
        self.setMinimumWidth(560)
        self.cfg = dict(cfg)
        self._verify_worker = None
        # Working copies. Edited freely and written only on Save, so Cancel
        # genuinely cancels -- including the removal of an account.
        self._accounts = email_config.sending_accounts_of(cfg) or [{}]
        self._current = 0
        self._loading = False
        root = self.body
        # Kept verbatim. Rewording it would orphan the Hindi and Gujarati
        # translations of this exact sentence — the packs key off the English
        # string — so the chrome around it moved and the words did not.
        note = QLabel(
            "Prism sends through YOUR account via SMTP — nothing is stored "
            "anywhere but ~/.prism/config.json.\n\nGmail: this needs an APP "
            "PASSWORD, not your real one — create one at "
            "myaccount.google.com/apppasswords")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"color: {theme.MUTE}; background: #F6F5F2;"
            f" border-radius: 12px;"
            f" padding: {theme.SPACE_2}px {theme.SPACE_3}px; font-size: 13px;")
        root.addWidget(note)

        # ── the account list ─────────────────────────────────────────────
        # Above the form rather than beside it, and hidden at one account,
        # for the reason InquirySetupDialog gives about its mailbox list: a
        # list of one, above a form asking for that same one, reads as two
        # steps where there is only one thing to do.
        self.senders = QListWidget()
        self.senders.setFixedHeight(84)
        self.senders.currentRowChanged.connect(self._sender_picked)
        root.addWidget(self.senders)

        list_row = QHBoxLayout()
        list_row.setSpacing(10)
        self.add_sender_btn = QPushButton(i18n.t("Add another address"))
        self.add_sender_btn.setToolTip(i18n.t(
            "sales@, accounts@, your own — you pick which one a message goes "
            "out from when you send it"))
        self.add_sender_btn.clicked.connect(self._add_sender)
        list_row.addWidget(pillify(self.add_sender_btn))
        self.remove_sender_btn = QPushButton(i18n.t("Remove this address"))
        self.remove_sender_btn.clicked.connect(self._remove_sender)
        list_row.addWidget(pillify(self.remove_sender_btn))
        self.default_btn = QPushButton(i18n.t("Send from this one by default"))
        self.default_btn.clicked.connect(self._make_default)
        list_row.addWidget(pillify(self.default_btn))
        list_row.addStretch(1)
        root.addLayout(list_row)

        form = QFormLayout()
        self._saved_password = self._accounts[0].get("password", "")
        self.addr_edit = QLineEdit()
        self.addr_edit.textChanged.connect(self._autofill_server)
        self.addr_edit.textChanged.connect(self._address_changed)
        form.addRow("Your email address:", self.addr_edit)
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        self.pass_edit.textChanged.connect(self._update_password_status)
        C.add_password_visibility(self.pass_edit)
        form.addRow("Password:", self.pass_edit)
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText("auto-detected for Gmail/Outlook/Yahoo")
        form.addRow("SMTP host:", self.host_edit)
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("465 = SSL, 587 = STARTTLS")
        form.addRow("SMTP port:", self.port_edit)
        # The dialog sizes itself from size hints taken BEFORE the stylesheet's
        # 6px/11px padding applies, so with no explicit size the four fields
        # were squeezed to 22 px and their text clipped at the bottom (seen in
        # the real window, 1 Oct 2026; Compose avoids it by calling resize()).
        # A real minimum makes the dialog grow to fit instead.
        for edit in (self.addr_edit, self.pass_edit, self.host_edit, self.port_edit):
            edit.setMinimumHeight(theme.BTN_HEIGHT_MD)
        for edit in (self.addr_edit, self.pass_edit, self.host_edit, self.port_edit):
            lbl = form.labelForField(edit)      # the preview's quiet 400-weight field label
            if lbl is not None:
                lbl.setStyleSheet(f"font-weight: 400; color: {theme.INK};")
        root.addLayout(form)

        # The placeholder alone reads as "empty" to anyone who has not
        # stopped to read the grey text — the same misreading that, on the
        # Inquiry Automation side, turned "the password is always shown
        # blank" into a belief that Prism deletes it. See
        # InquirySetupDialog._update_password_status() for the original.
        self.password_status = QLabel("")
        self.password_status.setWordWrap(True)
        root.addWidget(self.password_status)

        # Park an address without losing its password. Offered only once
        # there is more than one: switching off your only sending account
        # stops every outgoing message, and a checkbox is far too quiet a
        # way to do that.
        self.active_box = QCheckBox(i18n.t("Use this address for sending"))
        self.active_box.setToolTip(i18n.t(
            "Unticked, Prism keeps the account and its password but never "
            "sends from it."))
        self.active_box.toggled.connect(self._active_toggled)
        root.addWidget(self.active_box)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        root.addStretch(1)
        # Better to find out the password is wrong here than half way through a
        # blast to fifty people — so Test is a real, findable utility rather
        # than an ActionRole button Qt lays out wherever the platform prefers.
        self.test_btn = self.button(i18n.t("Test connection"), "secondary",
                                    icon_name="check", small=True,
                                    on_click=self._test)
        self.footer.add_utility(self.test_btn)
        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", on_click=self._save))
        self.tab_chain(self.addr_edit, self.pass_edit, self.host_edit,
                       self.port_edit)
        self._load_form(0)
        self._refresh_senders()

    # ── the account list ─────────────────────────────────────────────────
    def _refresh_senders(self):
        """Redraw the list to match the working copies, without re-entering
        the selection handler on the way past."""
        self._loading = True
        self.senders.clear()
        default = self._default_index()
        for index, account in enumerate(self._accounts):
            address = account.get("address", "").strip()
            label = address or i18n.t("(new address — type it below)")
            if not email_config.is_active(account):
                label = i18n.t("{who} — not in use").replace("{who}", label)
            elif index == default:
                label = i18n.t("{who} — sends by default").replace(
                    "{who}", label)
            self.senders.addItem(QListWidgetItem(label))
        self.senders.setCurrentRow(self._current)
        several = len(self._accounts) > 1
        self.senders.setVisible(several)
        self.remove_sender_btn.setVisible(several)
        self.default_btn.setVisible(several and self._current != default)
        self.active_box.setVisible(several)
        self._loading = False

    def _default_index(self) -> int:
        """Which entry sends unless somebody picks another — the first one
        switched on and filled in. Position IS the default, so there is no
        second setting to fall out of step with the order on screen."""
        for index, account in enumerate(self._accounts):
            if (email_config.is_active(account)
                    and email_config.is_complete(account)):
                return index
        return 0

    def _commit_form(self):
        """Fold whatever is typed into the account being edited.

        Lenient on purpose: an entry can sit half-filled while another is
        edited — Save is where completeness is checked, with the same
        messages this dialog has always shown.
        """
        account = self._accounts[self._current]
        account["address"] = self.addr_edit.text().strip()
        password = (CB.mailer.clean_password(self.pass_edit.text())
                    or self._saved_password)
        if password:
            account["password"] = password
        account["host"] = self.host_edit.text().strip() or account.get("host", "")
        port_txt = self.port_edit.text().strip()
        if port_txt:
            try:
                account["port"] = int(port_txt)
            except ValueError:
                # Left as typed so _account() reports it in the words this
                # dialog already uses, rather than being silently dropped.
                account["port"] = port_txt
        account["active"] = self.active_box.isChecked()

    def _load_form(self, index: int):
        """Show one account in the form. The password box is always cleared —
        a saved password is kept by leaving it blank, never displayed."""
        self._loading = True
        account = self._accounts[index]
        self._saved_password = account.get("password", "")
        self.addr_edit.setText(account.get("address", ""))
        self.pass_edit.clear()
        # Re-opening setup to fix a typo'd port shouldn't cost you a trip to
        # Google's app-password page — blank means "keep the saved one".
        self.pass_edit.setPlaceholderText(
            "leave blank to keep the saved password" if self._saved_password
            else "16-character app password — spaces are fine, paste as shown")
        self.host_edit.setText(account.get("host", ""))
        self.port_edit.setText(str(account.get("port", "") or ""))
        self.active_box.setChecked(email_config.is_active(account))
        self.status.setText("")
        # Explicit, not relied on via pass_edit.clear()'s textChanged: Qt does
        # not emit that signal when the box was already empty, which is
        # exactly the case switching between two unfilled-password rows — and
        # that is the one case where a stale "already saved" from the row left
        # behind would be believed most easily.
        self._update_password_status()
        self._loading = False

    def _sender_picked(self, row: int):
        if self._loading or row < 0 or row == self._current:
            return
        self._commit_form()
        self._current = row
        self._load_form(row)
        self._refresh_senders()

    def _add_sender(self):
        self._commit_form()
        if not self._accounts[self._current].get("address"):
            # Two blank entries help nobody — finish this one first.
            self.addr_edit.setFocus()
            self.status.setText(i18n.t(
                "Type this address first, then add the next one."))
            return
        self._accounts.append({})
        self._current = len(self._accounts) - 1
        self._load_form(self._current)
        self._refresh_senders()
        self.addr_edit.setFocus()

    def _remove_sender(self):
        account = self._accounts[self._current]
        address = account.get("address", "").strip()
        if address:
            answer = QMessageBox.question(
                self, i18n.t("Email account"),
                i18n.t("Remove {who}?\n\nPrism stops sending from that "
                       "address and forgets its password. Nothing already "
                       "sent is touched.").replace("{who}", address),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if len(self._accounts) == 1:
            self._accounts[0] = {}
        else:
            self._accounts.pop(self._current)
            self._current = max(0, self._current - 1)
        self._load_form(self._current)
        self._refresh_senders()

    def _make_default(self):
        """Move this account to the top, which is what being the default IS."""
        self._commit_form()
        account = self._accounts.pop(self._current)
        # A default that is switched off is not a default; asking to send
        # from it by default is also asking for it to be in use.
        account["active"] = True
        self._accounts.insert(0, account)
        self._current = 0
        self._load_form(0)
        self._refresh_senders()

    def _active_toggled(self, _on: bool):
        if self._loading:
            return
        self._accounts[self._current]["active"] = self.active_box.isChecked()
        self._refresh_senders()

    def _address_changed(self, _text: str):
        """Keep the list label in step with the box, so an address being
        typed is visible in the list it will be saved into."""
        if self._loading:
            return
        self._accounts[self._current]["address"] = self.addr_edit.text().strip()
        self._refresh_senders()

    def _update_password_status(self):
        """Say, in words nobody can miss, whether the password box being
        blank means "nothing saved" or "already saved, and staying that
        way." Silent once something new has actually been typed — at that
        point the box speaks for itself."""
        if self.pass_edit.text():
            self.password_status.setText("")
            self.password_status.setVisible(False)
            return
        if self._saved_password:
            self.password_status.setText(i18n.t(
                "✓ A password is already saved for this account. Leave this "
                "box blank and it stays exactly as it is — nothing is "
                "removed by opening or saving this screen. Type a new one "
                "here only if you want to replace it."))
            self.password_status.setStyleSheet(
                f"color: {theme.OK_INK}; font-size: 12.5px;")
        else:
            self.password_status.setText(i18n.t(
                "No password saved yet for this account."))
            self.password_status.setStyleSheet(
                f"color: {theme.NEUTRAL[600]}; font-size: 12.5px;")
        self.password_status.setVisible(True)

    def _autofill_server(self, address: str):
        """Fill host/port the moment the domain is recognisable, so the two
        fields most people can't answer are usually already answered."""
        if self._loading:
            return
        known = CB.mailer.smtp_for(address.strip())
        if not known:
            return
        if not self.host_edit.text().strip():
            self.host_edit.setText(known[0])
        if not self.port_edit.text().strip():
            self.port_edit.setText(str(known[1]))

    def _account(self) -> dict | None:
        """Validate the form into an email config block, or complain and
        return None."""
        address = self.addr_edit.text().strip()
        if not address or "@" not in address:
            QMessageBox.warning(self, "Email setup", "That doesn't look like an email address.")
            return None
        password = CB.mailer.clean_password(self.pass_edit.text()) or self._saved_password
        if not password:
            QMessageBox.warning(self, "Email setup", "Enter your app password.")
            return None
        known = CB.mailer.smtp_for(address)
        host = self.host_edit.text().strip() or (known[0] if known else "")
        port_txt = self.port_edit.text().strip() or (str(known[1]) if known else "587")
        if not host:
            QMessageBox.warning(self, "Email setup", "Enter an SMTP host — couldn't auto-detect one.")
            return None
        try:
            port = int(port_txt)
        except ValueError:
            QMessageBox.warning(self, "Email setup", "Port must be a number.")
            return None
        return {"address": address, "password": password, "host": host, "port": port}

    def _test(self):
        account = self._account()
        if not account:
            return
        busy_button(self.test_btn, True, i18n.t("Signing in"))
        self.status.setText(f"Signing in to {account['host']}…")
        self._verify_worker = VerifyWorker({"email": account})
        self._verify_worker.done.connect(self._on_verified)
        self._verify_worker.start()

    def _on_verified(self, error: str):
        busy_button(self.test_btn, False)
        if error:
            self.status.setText(f"✗  {error}")
        else:
            self.status.setText("✓  Signed in — this account can send.")
        self.status.setStyleSheet(
            f"color: {theme.BRAND_ERR if error else theme.BRAND_OK}; font-weight: 500;")

    def _save(self):
        """Check the account on screen the way this dialog always has, then
        every other one in the list, then write the list and its mirror."""
        account = self._account()
        if not account:
            return
        self._commit_form()
        accounts = [a for a in self._accounts if a.get("address")]
        incomplete = next(
            (a for a in accounts if not email_config.is_complete(a)), None)
        if incomplete is not None:
            QMessageBox.warning(
                self, "Email setup",
                i18n.t("{who} still needs a password and a server before "
                       "Prism can send from it.").replace(
                    "{who}", incomplete.get("address", "")))
            self._current = self._accounts.index(incomplete)
            self._load_form(self._current)
            self._refresh_senders()
            return
        if not any(email_config.is_active(a) for a in accounts):
            QMessageBox.warning(
                self, "Email setup",
                i18n.t("At least one address has to be in use, or Prism has "
                       "nothing left to send from."))
            return
        self.cfg["email"] = email_config.account_block(self.cfg, accounts)
        CB.config.save(self.cfg)
        self.accept()

    def closeEvent(self, event):
        """Wind up the sign-in test before this dialog is destroyed.

        "Check this works" starts a VerifyWorker in a blocking SMTP sign-in;
        closing the dialog while it runs would destroy a live QThread and Qt
        qFatal()s on that. VerifyWorker has no stop(), so bounded-wait then
        terminate the overrun.
        """
        w = self._verify_worker
        if w is not None:
            try:
                if w.isRunning():
                    if not w.wait(3000):
                        w.terminate()
                        w.wait(1000)
            except RuntimeError:
                pass
        super().closeEvent(event)


class _NoFocusDelegate(QStyledItemDelegate):
    """Suppresses cell focus outline rectangles while keeping clean row selection."""

    def initStyleOption(self, option, index):
        super().initStyleOption(option, index)
        option.state &= ~QStyle.State_HasFocus


class EmailComposeDialog(PrismDialog):
    """To, Subject, Message — then Send. Everything else is optional and
    says so.

    `mode` is "one" (the default) or "list": the same window either way; a
    list opens straight into the CSV picker so the second click the owner
    made on the launcher is honoured.
    """

    def __init__(self, cfg: dict, attachments: list, parent=None,
                 mode: str = "one"):
        address = email_config.default_sender(cfg).get("address", "")
        super().__init__(
            i18n.t("Send an email"),
            i18n.t("From {address}. Fill in To, Subject and Message, then "
                   "press Send. Nothing goes out until you press it."
                   ).format(address=address or i18n.t("your account")),
            icon="mail", parent=parent, closable=False, scrollable=True)
        self.setWindowTitle(i18n.t("Send an email"))
        self.resize(860, 880)
        self.setMinimumSize(640, 620)
        self.cfg = cfg
        self.mode = mode
        self._list: list[dict] = []          # recipients from a CSV
        self._list_name = ""
        self.source_files: list[dict] = []   # attached to every email
        self._worker = None
        self._send_worker = None
        self._draft_stage = ""
        self._last_run: dict = {}
        self._sent_ok: list[str] = []
        self._sent_bad: list[tuple] = []
        self._sending_as: dict = {}
        self._subject = self._body = ""
        self._held_back: list[dict] = []     # kept in the list for next time

        self.header.add_action(pillify(C.button(
            i18n.t("Change account"), "secondary", icon_name="key",
            small=True, on_click=self._change_account)))

        root = self.body
        root.setSpacing(theme.ROW_GAP)

        # ── the letter: To / Subject / Message ────────────────────────────
        form = QGridLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(theme.SPACE_3)
        form.setVerticalSpacing(theme.SPACE_2)
        form.setColumnMinimumWidth(0, 78)
        form.setColumnStretch(1, 1)

        # Which address this goes out from. Hidden at one sending account
        # -- the subtitle already names it, and a chooser with one entry is
        # a decision the customer does not have.
        self.from_box = QComboBox()
        self.from_box.currentIndexChanged.connect(self._from_picked)
        self.from_label = self._field_label(i18n.t("From"))
        form.addWidget(self.from_label, 0, 0)
        form.addWidget(self.from_box, 0, 1)

        to_row = QHBoxLayout()
        to_row.setContentsMargins(0, 0, 0, 0)
        to_row.setSpacing(theme.SPACE_2)
        self.to_edit = QLineEdit()
        self.to_edit.setPlaceholderText(i18n.t(
            "rajesh@acme.in — for more than one, separate with commas"))
        self.to_edit.textChanged.connect(self._sync)
        to_row.addWidget(self.to_edit, stretch=1)
        self.list_btn = pillify(C.button(i18n.t("Add a list (CSV)"), "secondary",
                                         icon_name="list", small=True,
                                         on_click=self._add_list))
        to_row.addWidget(self.list_btn)
        form.addWidget(self._field_label(i18n.t("To")), 1, 0)
        form.addLayout(to_row, 1, 1)

        # Who this is going to, in words, right under the To line — and the
        # list itself when there is one, so nobody has to open a panel to
        # see who "42 people" are.
        who_row = QHBoxLayout()
        who_row.setContentsMargins(0, 0, 0, 0)
        who_row.setSpacing(theme.SPACE_3)
        self.who_label = C.label("", level="SUPPORT", wrap=True)
        who_row.addWidget(self.who_label, stretch=1)
        self.search_btn = linkify(C.button(
            i18n.t("Don't know the address? Search the web"),
            "tertiary", icon_name="search", small=True,
            on_click=self._discover_recipient))
        who_row.addWidget(self.search_btn, alignment=Qt.AlignTop | Qt.AlignRight)
        form.addLayout(who_row, 2, 1)

        self.list_box = QWidget()
        list_col = QVBoxLayout(self.list_box)
        list_col.setContentsMargins(0, 0, 0, 0)
        list_col.setSpacing(theme.SPACE_2)
        self.list_table = QTableWidget(0, 2)
        self.list_table.setObjectName("emailRecipientsTable")
        self.list_table.setHorizontalHeaderLabels([i18n.t("Name"), i18n.t("Email")])
        self.list_table.verticalHeader().setVisible(False)
        self.list_table.verticalHeader().setDefaultSectionSize(30)
        self.list_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_table.setAlternatingRowColors(True)
        self.list_table.setShowGrid(False)
        self.list_table.setFocusPolicy(Qt.NoFocus)
        self.list_table.setItemDelegate(_NoFocusDelegate(self.list_table))
        self.list_table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        head = self.list_table.horizontalHeader()
        head.setHighlightSections(False)
        head.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        head.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        head.setSectionResizeMode(1, QHeaderView.Stretch)
        # Four rows visible, always; more scroll. A table that shows only
        # its header is a table nobody can read.
        row_h = self.list_table.verticalHeader().defaultSectionSize()
        head_h = head.sizeHint().height()
        self.list_table.setMinimumHeight(head_h + 4 * row_h + 6)
        self.list_table.setMaximumHeight(head_h + 6 * row_h + 6)
        list_col.addWidget(self.list_table)
        list_btns = QHBoxLayout()
        list_btns.setContentsMargins(0, 0, 0, 0)
        list_btns.setSpacing(theme.SPACE_2)
        self.remove_btn = pillify(C.button(i18n.t("Remove selected"), "secondary",
                                           small=True, on_click=self._remove_selected))
        list_btns.addWidget(self.remove_btn)
        self.clear_list_btn = linkify(C.button(i18n.t("Clear the list"), "tertiary",
                                               small=True, on_click=self._clear_list), 13)
        list_btns.addWidget(self.clear_list_btn)
        list_btns.addStretch(1)
        list_col.addLayout(list_btns)
        self.list_box.setVisible(False)
        form.addWidget(self.list_box, 3, 1)

        self.subject_edit = QLineEdit()
        self.subject_edit.setPlaceholderText(i18n.t("What the email is about"))
        self.subject_edit.textChanged.connect(self._sync)
        form.addWidget(self._field_label(i18n.t("Subject")), 4, 0)
        form.addWidget(self.subject_edit, 4, 1)

        self.body_edit = C.PlainPasteTextEdit()
        self.body_edit.setAcceptRichText(False)
        self.body_edit.setPlaceholderText(i18n.t(
            "Type the message here, or ask Prism to write it below.\n"
            "Write {name} anywhere and each person gets their own name."))
        self.body_edit.setMinimumHeight(160)
        self.body_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body_edit.textChanged.connect(self._sync)
        form.addWidget(self._field_label(i18n.t("Message")), 5, 0,
                       alignment=Qt.AlignTop)
        form.addWidget(self.body_edit, 5, 1)
        form.setRowStretch(5, 1)

        files_row = QHBoxLayout()
        files_row.setContentsMargins(0, 0, 0, 0)
        files_row.setSpacing(theme.SPACE_2)
        self.attach_btn = pillify(C.button(i18n.t("Attach a file"), "secondary",
                                           icon_name="paperclip", small=True,
                                           on_click=self._attach))
        files_row.addWidget(self.attach_btn)
        self.files_label = C.label(i18n.t("No files attached."), level="SUPPORT",
                                   wrap=True)
        files_row.addWidget(self.files_label, stretch=1)
        self.clear_files_btn = linkify(C.button(i18n.t("Remove files"), "tertiary",
                                                small=True, on_click=self._clear_files), 13)
        self.clear_files_btn.setVisible(False)
        files_row.addWidget(self.clear_files_btn)
        form.addWidget(self._field_label(i18n.t("Files")), 6, 0)
        form.addLayout(files_row, 6, 1)
        root.addLayout(form, stretch=1)

        # ── pace and limits ───────────────────────────────────────────────
        # A list is not a blast. How many go, how far apart, and when it
        # starts are decisions the person pressing Send should be making --
        # and were being made for them, silently, as "all of them, two
        # seconds apart, right now". The numbers persist (email_config's
        # send policy) so they are set once, and the daily cap is counted
        # off the sent log, so it holds across windows and across days.
        #
        # Folded by default. Most sends are one letter to one person and
        # need none of this; the card then costs one line -- the title, the
        # current setting in words, and Change -- and the letter keeps its
        # room. It opens on its own when a saved setting is not the default,
        # because a cap somebody set last week should not be invisible.
        self._policy = email_config.send_policy(cfg)
        pace = QFrame()                     # the preview's soft `.stripe`
        pace.setObjectName("paceStripe")
        pace.setStyleSheet("#paceStripe { background: #F6F5F2; border: none;"
                           " border-radius: 12px; }")
        pace_col = QVBoxLayout(pace)
        pace_col.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                    theme.SPACE_4, theme.SPACE_3)
        pace_col.setSpacing(theme.SPACE_2)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.label(i18n.t("Pace and limits"), level="BODY", weight=500,
                               colour=theme.INK))
        self.pace_summary = C.label("", level="MONO", wrap=True, colour=theme.MUTE)
        self.pace_summary.setStyleSheet(self.pace_summary.styleSheet()
                                        + " font-size: 11px; font-weight: 400;")
        head.addWidget(self.pace_summary, stretch=1)
        self.pace_toggle = linkify(C.button(i18n.t("Change"), "tertiary", small=True,
                                            on_click=self._toggle_pace), 13)
        head.addWidget(self.pace_toggle, alignment=Qt.AlignTop)
        pace_col.addLayout(head)

        self.pace_details = QWidget()
        details = QFormLayout(self.pace_details)
        details.setContentsMargins(0, theme.SPACE_2, 0, 0)
        details.setHorizontalSpacing(theme.SPACE_3)
        details.setVerticalSpacing(theme.SPACE_2)
        details.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        details.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        def _row(*widgets):
            lay = QHBoxLayout()
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(theme.SPACE_2)
            for w in widgets:
                lay.addWidget(w)
            lay.addStretch(1)
            return lay

        self.gap_spin = QDoubleSpinBox()
        self.gap_spin.setRange(0.5, 3600.0)
        self.gap_spin.setDecimals(1)
        self.gap_spin.setSingleStep(0.5)
        self.gap_spin.setSuffix(" " + i18n.t("s"))
        self.gap_spin.setMinimumWidth(96)
        self.gap_spin.setValue(self._policy["gap_seconds"])
        self.gap_spin.setToolTip(i18n.t(
            "How long Prism waits after one email before sending the next."))
        self.jitter_spin = QDoubleSpinBox()
        self.jitter_spin.setRange(0.0, 3600.0)
        self.jitter_spin.setDecimals(1)
        self.jitter_spin.setSingleStep(0.5)
        self.jitter_spin.setSuffix(" " + i18n.t("s"))
        self.jitter_spin.setMinimumWidth(96)
        self.jitter_spin.setValue(self._policy["jitter_seconds"])
        self.jitter_spin.setToolTip(i18n.t(
            "A random extra wait added to every gap, so the emails do not "
            "leave like clockwork. 0 = the same gap every time."))
        details.addRow(self._field_label(i18n.t("Gap between emails")),
                       _row(self.gap_spin, QLabel(i18n.t("plus up to")),
                            self.jitter_spin, QLabel(i18n.t("at random"))))

        self.per_run_spin = QSpinBox()
        self.per_run_spin.setRange(0, 100000)
        self.per_run_spin.setSpecialValueText(i18n.t("everyone"))
        self.per_run_spin.setMinimumWidth(118)
        self.per_run_spin.setValue(self._policy["max_per_run"])
        self.per_run_spin.setToolTip(i18n.t(
            "Send to at most this many people each time you press Send. "
            "The rest stay in the list for the next press."))
        details.addRow(self._field_label(i18n.t("Each press sends")),
                       _row(self.per_run_spin,
                            QLabel(i18n.t("people — the rest stay in the list"))))

        self.per_day_spin = QSpinBox()
        self.per_day_spin.setRange(0, 100000)
        self.per_day_spin.setSpecialValueText(i18n.t("no limit"))
        self.per_day_spin.setMinimumWidth(118)
        self.per_day_spin.setValue(self._policy["max_per_day"])
        self.per_day_spin.setToolTip(i18n.t(
            "Send at most this many from one address per day, counted "
            "across every send from this computer."))
        self.today_label = QLabel("")
        details.addRow(self._field_label(i18n.t("Per day")),
                       _row(self.per_day_spin,
                            QLabel(i18n.t("from this address")), self.today_label))

        self.later_check = QCheckBox(i18n.t("Send later, at"))
        self.later_check.toggled.connect(self._sync)
        self.later_edit = QDateTimeEdit()
        self.later_edit.setDisplayFormat("dd MMM yyyy  HH:mm")
        self.later_edit.setCalendarPopup(True)
        self.later_edit.setMinimumWidth(190)
        soon = QDateTime.currentDateTime().addSecs(3600)
        soon = soon.addSecs(-soon.time().second())
        self.later_edit.setDateTime(soon)
        self.later_edit.setMinimumDateTime(QDateTime.currentDateTime())
        self.later_edit.setEnabled(False)
        self.later_check.toggled.connect(self.later_edit.setEnabled)
        self.later_edit.dateTimeChanged.connect(self._sync)
        details.addRow(self._field_label(i18n.t("When")),
                       _row(self.later_check, self.later_edit))
        # Said once, always visible, not only after the box is ticked: the
        # sending happens from this computer, so a scheduled send needs
        # Prism -- and this window -- open until it has gone out.
        self.keep_open_note = C.label(i18n.t(
            "Prism does the sending from this computer, so it has to stay "
            "open — and this window with it — until the emails have gone. "
            "Closing it cancels a scheduled send."), level="SUPPORT", wrap=True)
        details.addRow("", self.keep_open_note)

        # The engine files a copy of every send into the account's Sent
        # folder (core/mailer, 10 Sep 2026) so the mail shows in Outlook and
        # webmail. It was on with no way to see it or turn it off; this is
        # both. Install-wide, remembered with the pace.
        self.sent_copy_check = QCheckBox(i18n.t(
            "Keep a copy of each email in the account's Sent folder"))
        self.sent_copy_check.setChecked(email_config.save_to_sent(self.cfg))
        self.sent_copy_check.setToolTip(i18n.t(
            "Filed over IMAP after each send, so it shows in Outlook and "
            "webmail. A mailbox that refuses the copy still sends."))
        self.sent_copy_check.toggled.connect(self._sync)
        details.addRow(self._field_label(i18n.t("Sent folder")), self.sent_copy_check)

        self.pace_note = C.label("", level="SUPPORT", wrap=True)
        details.addRow("", self.pace_note)
        pace_col.addWidget(self.pace_details)
        for w in (self.gap_spin, self.jitter_spin, self.per_run_spin,
                  self.per_day_spin):
            w.valueChanged.connect(self._sync)
        self._show_pace(self._policy != email_config.send_policy({})
                        or not email_config.save_to_sent(self.cfg))
        root.addWidget(pace)

        # ── optional: let Prism write it ──────────────────────────────────
        card = QFrame()                     # the preview's hairline `.group`
        card.setObjectName("draftGroup")
        card.setStyleSheet("#draftGroup { background: #ffffff; border: 1px solid"
                           " #E6E5E1; border-radius: 14px; }")
        card_col = QVBoxLayout(card)
        card_col.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                    theme.SPACE_4, theme.SPACE_3)
        card_col.setSpacing(theme.SPACE_2)
        card_col.addWidget(C.kicker(
            i18n.t("Want Prism to write the message for you? (optional)")))
        brief_row = QHBoxLayout()
        brief_row.setContentsMargins(0, 0, 0, 0)
        brief_row.setSpacing(theme.SPACE_2)
        self.brief_edit = QLineEdit()
        self.brief_edit.setPlaceholderText(i18n.t(
            "Say what it should say — e.g. introduce our spring range and "
            "ask for a meeting next week"))
        self.brief_edit.returnPressed.connect(self._write_for_me)
        brief_row.addWidget(self.brief_edit, stretch=1)
        self.write_btn = pillify(C.button(i18n.t("Write it for me"), "secondary",
                                          icon_name="pencil", small=True,
                                          on_click=self._write_for_me))
        brief_row.addWidget(self.write_btn)
        card_col.addLayout(brief_row)
        card_col.addWidget(C.label(i18n.t(
            "Attached files are read for the draft. The draft lands in the "
            "Message box above; change anything before you send."),
            level="SUPPORT", wrap=True, colour=theme.MUTE))
        root.addWidget(card)

        self.status = QLabel("")
        self.status.setObjectName("dim")
        self.status.setWordWrap(True)
        self.status.setOpenExternalLinks(True)
        # Waiting on an AI tool: Prism's own orb, with the words beside it.
        self.thinking = Loader("orb")
        self.thinking.setVisible(False)
        root.addWidget(self.thinking)
        root.addWidget(self.status)

        self.footer.add_secondary(
            self.button(i18n.t("Close"), on_click=self.reject))
        self.send_btn = self.button(i18n.t("Send"), "primary",
                                    on_click=self._send)
        self.footer.set_primary(self.send_btn)
        self.tab_chain(self.to_edit, self.subject_edit, self.body_edit,
                       self.brief_edit)

        # What the workbench handed over: a CSV is the list, the rest ride
        # along as attachments.
        if attachments:
            self._take_attachments(attachments)
        self._fill_from_box()
        self._sync()
        if mode == "list" and not self._list:
            QTimer.singleShot(0, self._add_list)
        else:
            self.to_edit.setFocus()

    # ── pace and limits ─────────────────────────────────────────────────
    def _show_pace(self, open_: bool):
        self.pace_details.setVisible(open_)
        self.pace_toggle.setText(i18n.t("Done") if open_ else i18n.t("Change"))

    def _toggle_pace(self):
        self._show_pace(not self.pace_details.isVisible())

    def _pace_summary(self) -> str:
        """The setting in a few words, for the folded card."""
        p = self.policy()
        gap = (i18n.t("{a:g}–{b:g} s apart").format(
                   a=p["gap_seconds"], b=p["gap_seconds"] + p["jitter_seconds"])
               if p["jitter_seconds"] > 0
               else i18n.t("{a:g} s apart").format(a=p["gap_seconds"]))
        per_run = (i18n.t("{n} per press").format(n=p["max_per_run"])
                   if p["max_per_run"] else i18n.t("everyone at once"))
        per_day = (i18n.t("{n} a day").format(n=p["max_per_day"])
                   if p["max_per_day"] else i18n.t("no daily limit"))
        start = self.start_at()
        when = (i18n.t("sends {when}").format(
                    when=time.strftime(_WHEN_FMT, time.localtime(start)))
                if start else i18n.t("sends now"))
        copy = (i18n.t("copy kept in Sent") if self.save_to_sent()
                else i18n.t("no copy in Sent"))
        return " · ".join([gap, per_run, per_day, when, copy])

    def policy(self) -> dict:
        """The four numbers as the controls show them right now."""
        return {
            "gap_seconds": float(self.gap_spin.value()),
            "jitter_seconds": float(self.jitter_spin.value()),
            "max_per_run": int(self.per_run_spin.value()),
            "max_per_day": int(self.per_day_spin.value()),
        }

    def save_to_sent(self) -> bool:
        """Whether this send files a copy in the account's Sent folder."""
        return self.sent_copy_check.isChecked()

    def start_at(self) -> float:
        """When the send begins, as time.time(); 0 = the moment Send is
        pressed. A time already past is "now" -- the box was filled in and
        then the person read the letter over for ten minutes."""
        if not self.later_check.isChecked():
            return 0.0
        when = self.later_edit.dateTime().toSecsSinceEpoch()
        return float(when) if when > time.time() else 0.0

    def _sent_today(self) -> int:
        try:
            return sent_log.sent_today(
                self.cfg, self._sender().get("address", ""))
        except Exception:                                   # noqa: BLE001
            return 0

    def plan(self) -> tuple[int, list[str]]:
        """How many of the recipients go on this press, and why not all."""
        return email_config.plan_send(
            self.policy(), len(self.recipients), self._sent_today())

    def _pace_words(self) -> str:
        p = self.policy()
        if p["jitter_seconds"] > 0:
            gap = i18n.t("{a:g} to {b:g} seconds apart").format(
                a=p["gap_seconds"], b=p["gap_seconds"] + p["jitter_seconds"])
        else:
            gap = i18n.t("{a:g} seconds apart").format(a=p["gap_seconds"])
        words = [gap]
        allowed, reasons = self.plan()
        n = len(self.recipients)
        today = self._sent_today()
        if p["max_per_day"]:
            words.append(i18n.t("{n} of {cap} sent today from this address").format(
                n=today, cap=p["max_per_day"]))
        if n and allowed < n:
            words.append(i18n.t("{k} of {n} will go on this press ({why}); "
                                "the rest stay in the list").format(
                k=allowed, n=n, why="; ".join(reasons)))
        start = self.start_at()
        if start:
            words.append(i18n.t("Starts {when} — keep Prism open until then").format(
                when=time.strftime(_WHEN_FMT, time.localtime(start))))
        return ". ".join(words) + "."

    def _remember_policy(self):
        """The numbers persist: set once, kept for the next window. The
        Sent-folder switch travels with them."""
        new = self.policy()
        copy = self.save_to_sent()
        if (new == email_config.send_policy(self.cfg)
                and copy == email_config.save_to_sent(self.cfg)):
            return
        self.cfg = email_config.with_send_policy(self.cfg, new)
        self.cfg = email_config.with_save_to_sent(self.cfg, copy)
        try:
            CB.config.save(self.cfg)
        except Exception:                                   # noqa: BLE001
            pass                    # a pace that did not persist still sends

    def _drop_sent(self, sent: list[str]):
        """Take the ones that went out of the To line and the list, so what
        remains on screen is exactly who has not been written to yet."""
        gone = {e.lower() for e in sent}
        self._list = [r for r in self._list if r["email"].lower() not in gone]
        if not self._list:
            self._list_name = ""
        kept = [r["email"] for r in self._typed() if r["email"] not in gone]
        self.to_edit.setText(", ".join(kept))
        self._fill_list_table()
        self._sync()

    # ── small builders ──────────────────────────────────────────────────
    @staticmethod
    def _field_label(text: str) -> QLabel:
        lbl = C.label(text, level="BODY", weight=400, colour=theme.INK)
        lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return lbl

    # ── recipients ──────────────────────────────────────────────────────
    def _typed(self) -> list[dict]:
        """Addresses in the To line, in order, deduplicated."""
        seen, out = set(), []
        for email in _EMAIL_RE.findall(self.to_edit.text()):
            key = email.lower()
            if key not in seen:
                seen.add(key)
                out.append({"email": key, "name": ""})
        return out

    @property
    def recipients(self) -> list[dict]:
        """The list first (it carries names), then the typed ones; one entry
        per address."""
        seen, out = set(), []
        for r in list(self._list) + self._typed():
            key = r["email"].lower()
            if key not in seen:
                seen.add(key)
                out.append({"email": key, "name": (r.get("name") or "").strip()})
        return out

    def _add_list(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose the list of addresses"), "",
            "CSV (*.csv);;All files (*)")
        if path:
            self._load_list(path)

    def _load_list(self, path: str):
        """Read a CSV of recipients on this machine. Adds to any list already
        loaded; the first entry per address wins, so a name from the CSV is
        never replaced by a bare address."""
        try:
            found = CB.mailer.parse_recipients(path)
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t("Could not read {name}: {error}").format(
                name=os.path.basename(path), error=e))
            return
        if not found:
            self.status.setText(i18n.t(
                "{name} has no email addresses in it.").format(
                name=os.path.basename(path)))
            return
        have = {r["email"].lower() for r in self._list}
        for r in found:
            if r["email"].lower() not in have:
                have.add(r["email"].lower())
                self._list.append({"email": r["email"].lower(),
                                   "name": (r.get("name") or "").strip()})
        self._list_name = os.path.basename(path)
        self._fill_list_table()
        self.status.setText(i18n.t("{n} addresses read from {name}.").format(
            n=len(found), name=self._list_name))
        self._sync()

    def _fill_list_table(self):
        self.list_table.setRowCount(0)
        for r in self._list:
            row = self.list_table.rowCount()
            self.list_table.insertRow(row)
            self.list_table.setItem(row, 0, QTableWidgetItem(r.get("name") or ""))
            self.list_table.setItem(row, 1, QTableWidgetItem(r["email"]))
        self.list_box.setVisible(bool(self._list))

    def _remove_selected(self):
        rows = sorted({i.row() for i in self.list_table.selectedIndexes()},
                      reverse=True)
        if not rows:
            self.status.setText(i18n.t("Click a row in the list first."))
            return
        for row in rows:
            if 0 <= row < len(self._list):
                del self._list[row]
        if not self._list:
            self._list_name = ""
        self._fill_list_table()
        self._sync()

    def _clear_list(self):
        self._list, self._list_name = [], ""
        self._fill_list_table()
        self._sync()

    def _discover_recipient(self):
        """No address to hand: ask the research/leads tool to find the
        public one, from the description in the brief box."""
        goal = self.brief_edit.text().strip()
        if not goal:
            self.status.setText(i18n.t(
                "Say who they are in the box at the bottom (for example "
                "\"purchase manager at Acme Forgings, Rajkot\"), then press "
                "this again."))
            self.brief_edit.setFocus()
            return
        agents = CB.config.active_agents(self.cfg)
        finder = next((s for s in ("leads", "research", "brains")
                       if agents.get(s)), None)
        if not finder:
            self.status.setText(i18n.t(
                "No research tool is set up, so Prism cannot search. Type "
                "the address in To instead."))
            return
        routing = {finder: {"needed": True, "questions": [
            "Your ONLY task is: find the official, public contact email address for "
            f"the recipient described here: {goal}. Search the web. Reply with the "
            "1-3 best addresses, one per line, each followed by a dash and what it "
            "is for (e.g. partnerships, support, general). Prefer official domains "
            "over aggregator sites. If none can be found, reply exactly NONE."
        ]}}
        self.status.setText(i18n.t("Searching with {tool}…").format(tool=agents[finder]))
        self._worker = AutomationWorker(routing, self.cfg, [], goal)
        self._worker.done.connect(self._on_discovery_done)
        self._worker.failed.connect(
            lambda e: self.status.setText(i18n.t("Search failed: {error}").format(error=e)))
        self._worker.start()

    def _on_discovery_done(self, responses: dict, links: dict):
        text = "\n".join(t for ts in responses.values() for t in ts)
        found = list(dict.fromkeys(_EMAIL_RE.findall(text)))
        found = [e for e in found if not e.lower().endswith("example.com")][:5]
        if not found:
            self.status.setText(i18n.t(
                "No address found — type one in To instead."))
            return
        current = self.to_edit.text().strip()
        joined = ", ".join(found)
        self.to_edit.setText(f"{current}, {joined}" if current else joined)
        self.status.setText(i18n.t(
            "Found {n} address(es) and put them in To — delete any you do "
            "not want.").format(n=len(found)))

    # ── files ───────────────────────────────────────────────────────────
    def _attach(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, i18n.t("Attach to every email"), "", "All files (*)")
        if paths:
            self._on_files_added(paths)

    def _on_files_added(self, paths: list):
        """A CSV is the list; anything else is attached to every email."""
        atts = []
        for p in paths:
            try:
                atts.append(CB.files.attach(p))
            except Exception:                                 # noqa: BLE001
                continue
        self._take_attachments(atts)

    def _take_attachments(self, attachments: list):
        csvs, others = CB.mailer.split_attachments(attachments)
        for a in csvs:
            self._load_list(a["path"])
        known = {f["path"] for f in self.source_files}
        self.source_files += [f for f in others if f["path"] not in known]
        self._sync()

    def _clear_files(self):
        self.source_files = []
        self._sync()

    # ── the one place the screen is kept truthful ─────────────────────────
    def _sync(self, *_args):
        recipients = self.recipients
        n = len(recipients)
        if n == 0:
            who = ""
        elif n == 1:
            r = recipients[0]
            who = i18n.t("Going to {who}.").format(
                who=f"{r['name']} <{r['email']}>" if r["name"] else r["email"])
        elif self._list_name:
            who = i18n.t("Going to {n} people — {m} from {name}{extra}.").format(
                n=n, m=len(self._list), name=self._list_name,
                extra=(i18n.t(", the rest typed above")
                       if n > len(self._list) else ""))
        else:
            who = i18n.t("Going to {n} people.").format(n=n)
        self.who_label.setText(who)
        self.who_label.setVisible(bool(who))

        names = ", ".join(f["name"] for f in self.source_files)
        self.files_label.setText(
            i18n.t("Attached to every email: {names}").format(names=names)
            if names else i18n.t("No files attached."))
        self.clear_files_btn.setVisible(bool(self.source_files))

        missing = []
        if n == 0:
            missing.append(i18n.t("an address in To"))
        if not self.subject_edit.text().strip():
            missing.append(i18n.t("a subject"))
        if not self.body_edit.toPlainText().strip():
            missing.append(i18n.t("the message"))
        if hasattr(self, "pace_note"):
            self.pace_note.setText(self._pace_words())
            self.pace_summary.setText(self._pace_summary())
            self.today_label.setText(
                i18n.t("({n} sent today)").format(n=self._sent_today()))
        sending = bool(self._send_worker and self._send_worker.isRunning())
        if sending:
            return
        if missing:
            self.send_btn.setText(i18n.t("Send"))
            self.send_btn.setEnabled(False)
            self.send_btn.setToolTip(i18n.t("Still needed: {what}").format(
                what=", ".join(missing)))
        else:
            self.send_btn.setEnabled(True)
            self.send_btn.setToolTip("")
            allowed, _why = self.plan()
            later = bool(self.start_at())
            if allowed == 0:
                self.send_btn.setEnabled(False)
                self.send_btn.setToolTip(i18n.t(
                    "Today's limit for this address is used up. Raise it in "
                    "Pace and limits, or send tomorrow."))
                self.send_btn.setText(i18n.t("Daily limit reached"))
            elif n == 1:
                self.send_btn.setText(
                    (i18n.t("Send to {who} later") if later
                     else i18n.t("Send to {who}")).format(
                        who=recipients[0]["email"]))
            elif allowed < n:
                self.send_btn.setText(
                    (i18n.t("Send to {k} of {n} people later") if later
                     else i18n.t("Send to {k} of {n} people")).format(
                        k=allowed, n=n))
            else:
                self.send_btn.setText(
                    (i18n.t("Send to {n} people later") if later
                     else i18n.t("Send to {n} people")).format(n=n))

    # ── draft ───────────────────────────────────────────────────────────
    def _write_for_me(self):
        goal = self.brief_edit.text().strip()
        if not goal:
            self.status.setText(i18n.t(
                "Say what the email should say in the box first."))
            self.brief_edit.setFocus()
            return
        agents = CB.config.active_agents(self.cfg)
        avail = [s for s in ("research", "brains", "content") if agents.get(s)]
        if not avail:
            self.status.setText(i18n.t(
                "No writing tool is set up (Settings → AI tools), so Prism "
                "cannot write this. Type the message yourself instead."))
            return
        draft_stage = avail[-1]
        self._draft_stage = draft_stage
        routing = {draft_stage: {
            "needed": True,
            "reason": "write the email draft — and ONLY the draft",
            "expect": "SUBJECT:",
            "questions": [CB.mailer.draft_question(goal)]}}
        self._last_run = {"routing": routing, "agent": agents[draft_stage]}
        busy_button(self.write_btn, True, i18n.t("Writing"))
        wait = i18n.t("Writing with {tool}… this takes a minute or "
                      "two.").format(tool=agents[draft_stage])
        self.status.setText("")
        self.thinking.set_message(wait)
        self.thinking.setVisible(True)
        self._worker = AutomationWorker(routing, self.cfg, self.source_files,
                                        f"write an email: {goal}")
        self._worker.done.connect(self._on_draft_done)
        self._worker.failed.connect(self._on_draft_failed)
        self._worker.start()

    def _on_draft_failed(self, error: str):
        self.thinking.setVisible(False)
        busy_button(self.write_btn, False)
        self.status.setText(i18n.t("Could not write it: {error}").format(error=error))

    def _on_draft_done(self, responses: dict, links: dict):
        self.thinking.setVisible(False)
        busy_button(self.write_btn, False)
        texts = responses.get(self._draft_stage) or []
        self._last_run.update({"responses": responses, "links": links})
        usable = [t for t in texts if not CB.mailer.is_prompt_echo(t)]
        draft = CB.mailer.parse_draft(usable[0] if usable else "")
        if not draft:
            url = (links or {}).get(self._draft_stage, "")
            note = i18n.t("Could not read a finished draft back — the tool may "
                          "still be writing it. ")
            if url:
                note += (f'<a href="{url}" style="color:{theme.ACCENT_RAMP[700]}">'
                         + i18n.t("Open it in the tool") + "</a> "
                         + i18n.t("and paste the text into Message."))
            else:
                note += i18n.t("Type the message yourself instead.")
            self.status.setText(note)
            return
        subject, body = draft
        self.subject_edit.setText(subject)
        self.body_edit.setPlainText(body)
        self.status.setText(i18n.t(
            "Draft ready — read it, change anything, then press Send."))

    # ── send ────────────────────────────────────────────────────────────
    # ── which address it goes out from ───────────────────────────────────
    def _fill_from_box(self):
        """Offer every account that is switched on, default first.

        Rebuilt rather than patched whenever the accounts change, because the
        setup dialog can add, remove, reorder and park them in one visit and
        a chooser that tried to track that incrementally would eventually
        offer an address that is no longer there.
        """
        self._senders = email_config.active_senders(self.cfg)
        self._loading_senders = True
        self.from_box.clear()
        for account in self._senders:
            self.from_box.addItem(account.get("address", ""))
        if self._senders:
            self.from_box.setCurrentIndex(0)
        several = len(self._senders) > 1
        self.from_box.setVisible(several)
        self.from_label.setVisible(several)
        self._loading_senders = False

    def _sender(self) -> dict:
        """The account this message goes out from.

        Falls back to the default, and then to {} -- which `cfg_for_sender()`
        reads as "change nothing", so a chooser that has somehow lost its
        selection sends what it would have sent before rather than nothing.
        """
        senders = getattr(self, "_senders", None) or []
        index = self.from_box.currentIndex()
        if 0 <= index < len(senders):
            return senders[index]
        return email_config.default_sender(self.cfg)

    def _from_picked(self, _index: int):
        if getattr(self, "_loading_senders", False):
            return
        self.header.set_subtitle(i18n.t(
            "From {address}. Fill in To, Subject and Message, then press "
            "Send. Nothing goes out until you press it.").format(
            address=self._sender().get("address", "")))

    def _change_account(self):
        dlg = EmailSetupDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg = dlg.cfg
            self._fill_from_box()
            address = self._sender().get("address", "")
            self.header.set_subtitle(i18n.t(
                "From {address}. Fill in To, Subject and Message, then press "
                "Send. Nothing goes out until you press it.").format(address=address))

    def _send(self):
        # Second press while a blast is running means stop, not send again.
        if self._send_worker and self._send_worker.isRunning():
            self._send_worker.stop()
            self.send_btn.setEnabled(False)
            self.send_btn.setText(i18n.t("Stopping…"))
            return
        if not email_config.can_send(self.cfg):
            dlg = EmailSetupDialog(self.cfg, self)
            if dlg.exec() != QDialog.Accepted:
                return
            self.cfg = dlg.cfg
            self._fill_from_box()
        # Resolved once, here, and carried through the confirmation, the
        # worker and any error message -- so what the customer was asked to
        # confirm is provably the account the mail actually left from.
        sender = self._sender()
        recipients = self.recipients
        subject = self.subject_edit.text().strip()
        body = self.body_edit.toPlainText().strip()
        if not recipients or not subject or not body:
            self._sync()
            return
        policy = self.policy()
        allowed, reasons = self.plan()
        if allowed <= 0:
            QMessageBox.information(
                self, i18n.t("Daily limit"),
                i18n.t("{n} emails have already left {address} today, and "
                       "the limit is {cap}. Raise the limit under Pace and "
                       "limits, or send tomorrow.").format(
                    n=self._sent_today(), address=sender.get("address", ""),
                    cap=policy["max_per_day"]))
            return
        self._held_back = recipients[allowed:]
        recipients = recipients[:allowed]
        start = self.start_at()
        files = ", ".join(f["name"] for f in self.source_files) or i18n.t("none")
        if len(recipients) == 1:
            question = i18n.t(
                "Send this email to {to}?\n\nSubject: {subject}\n"
                "Files: {files}\nFrom: {sender}").format(
                to=recipients[0]["email"], subject=subject, files=files,
                sender=sender.get("address", ""))
        else:
            shown = ", ".join(r["email"] for r in recipients[:5])
            more = ", …" if len(recipients) > 5 else ""
            question = i18n.t(
                "Send to {n} people?\n\nTo: {to}\nSubject: {subject}\n"
                "Files: {files}\nFrom: {sender}\n\nEach person gets their own "
                "copy. This cannot be undone.").format(
                n=len(recipients), to=f"{shown}{more}", subject=subject,
                files=files, sender=sender.get("address", ""))
        question += "\n\n" + i18n.t("Pace: {pace}").format(pace=self._pace_words())
        if self._held_back:
            question += "\n" + i18n.t(
                "{k} more stay in the list for next time.").format(
                k=len(self._held_back))
        confirm = QMessageBox.question(
            self, i18n.t("Send"), question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No)   # nobody should send a blast by pressing Enter
        if confirm != QMessageBox.Yes:
            return
        self._remember_policy()

        self._sent_ok, self._sent_bad = [], []
        self._subject, self._body = subject, body
        self._recipients_sent = recipients
        self._set_sending(True)
        self._sending_as = sender
        self.status.setText(i18n.t("Signing in to {host}…").format(
            host=sender.get("host", "")))
        self._send_worker = SendWorker(
            email_config.cfg_for_sender(
                email_config.with_save_to_sent(self.cfg, self.save_to_sent()), sender),
            list(recipients), subject, body, self.source_files,
            delay=policy["gap_seconds"], jitter=policy["jitter_seconds"],
            start_at=start)
        self._send_worker.progress.connect(self._on_send_progress)
        self._send_worker.done.connect(self._on_send_done)
        self._send_worker.failed.connect(self._on_send_failed)
        if hasattr(self._send_worker, "waiting"):
            self._send_worker.waiting.connect(self._on_send_waiting)
        if start:
            self.status.setText(i18n.t(
                "Scheduled for {when}. Keep this window open; Stop sending "
                "cancels it.").format(
                when=time.strftime(_WHEN_FMT, time.localtime(start))))
        self._send_worker.start()

    def _on_send_waiting(self, seconds_left: int):
        m, s = divmod(max(0, int(seconds_left)), 60)
        h, m = divmod(m, 60)
        left = (f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s")
        self.status.setText(i18n.t(
            "Scheduled — sending begins in {left}. Keep this window open; "
            "Stop sending cancels it.").format(left=left))

    def _set_sending(self, sending: bool):
        """A list takes minutes. Everything that would change what is being
        sent is locked while it runs, and Send becomes the way to stop."""
        for w in (self.to_edit, self.subject_edit, self.body_edit,
                  self.brief_edit, self.list_btn, self.attach_btn,
                  self.remove_btn, self.clear_list_btn, self.write_btn,
                  self.gap_spin, self.jitter_spin, self.per_run_spin,
                  self.per_day_spin, self.later_check):
            w.setEnabled(not sending)
            if isinstance(w, QPushButton):      # a disabled button says why
                w.setToolTip(i18n.t("Locked while the emails are going out.")
                             if sending else "")
        self.later_edit.setEnabled(not sending and self.later_check.isChecked())
        self.send_btn.setEnabled(True)
        if sending:
            self.send_btn.setText(i18n.t("Stop sending"))
        else:
            self._sync()

    def _on_send_progress(self, i: int, total: int, email: str, ok: bool, error: str):
        (self._sent_ok if ok else self._sent_bad).append(
            email if ok else (email, error))
        tail = "" if ok else f" — {error[:60]}"
        line = i18n.t("{i}/{total} · {state} {email}").format(
            i=i, total=total, email=email,
            state=i18n.t("sent") if ok else i18n.t("FAILED")) + tail
        if self._sent_bad and ok:
            line += "  " + i18n.t("({n} failed so far)").format(n=len(self._sent_bad))
        self.status.setText(line)

    def _on_send_done(self, sent: list, failed: list):
        self._set_sending(False)
        stopped = bool(self._send_worker and self._send_worker.stopped)
        recipients = getattr(self, "_recipients_sent", self.recipients)
        try:
            sent_log.record(
                self.cfg, to=recipients, subject=self._subject, body=self._body,
                sent=sent, failed=failed,
                attachments=[f["name"] for f in self.source_files],
                list_name=self._list_name, stopped=stopped,
                sender=self._sending_as.get("address", ""))
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t(
                "Sent, but could not write it down in {path}: {error}").format(
                path=sent_log.path(self.cfg), error=e))
        self._save_run(sent, failed)
        if len(recipients) == 1 and sent and not failed:
            title = i18n.t("Sent to {who}.").format(who=sent[0])
            body = ""
        else:
            title = i18n.t("Sent to {n} of {total}.").format(
                n=len(sent), total=len(recipients))
        held = list(self._held_back)
        if stopped:
            body = i18n.t("Stopped early — the rest were not attempted.")
        elif failed:
            shown = ", ".join(email for email, _ in failed[:3])
            body = i18n.t("{n} failed ({shown})").format(n=len(failed), shown=shown)
        elif held and not stopped:
            body = i18n.t("{k} people held back by limit.").format(k=len(held))
        elif sent and not failed:
            body = i18n.t("All messages delivered successfully.")

        self.status.setText(title)

        # Show modern, sleek floating Toast notification instead of tiny native modal box
        tone = "warn" if (failed or stopped) else "ok"
        parent_win = self.parent()
        top_win = parent_win.window() if (parent_win and hasattr(parent_win, "window")) else parent_win

        if held and not stopped:
            # What went is gone from the screen; what stayed is the list.
            self._held_back = []
            self._drop_sent(sent)
            self.status.setText(i18n.t(
                "{k} still to send — held back by the limit.").format(k=len(held)))
            C.show_toast(self, title=title, body=body, tone=tone, duration=3500)
            return

        if sent and not failed and not stopped:
            self.send_btn.setEnabled(False)
            self.send_btn.setText(i18n.t("Sent"))
            # Toast belongs on the host window (MainWindow) which stays alive after dialog closes
            if top_win:
                C.show_toast(top_win, title=title, body=body, tone=tone, duration=4000)
            else:
                C.show_toast(self, title=title, body=body, tone=tone, duration=1700)
            # Close dialog cleanly after brief confirmation
            QTimer.singleShot(1800, self.accept)
        else:
            C.show_toast(self, title=title, body=body, tone=tone, duration=4000)

    def _on_send_failed(self, error: str):
        """Login or connection died — nothing went out at all."""
        self._set_sending(False)
        hint = CB.mailer.explain_error(
            error, self._sending_as.get("address", ""))
        self.status.setText(i18n.t("Could not send: {hint}").format(hint=hint))
        again = QMessageBox.question(
            self, i18n.t("Send failed"),
            i18n.t("{hint}\n\nThe server said: {error}\n\n"
                   "Open account setup now?").format(hint=hint, error=error))
        if again == QMessageBox.Yes:
            self._change_account()

    def _save_run(self, sent: list, failed: list):
        """The same record the CLI's /email writes, so the send also shows
        in History. The "/email " prefix is what History and the old front
        door key on — keep it."""
        goal = self.brief_edit.text().strip() or self._subject
        record = {
            "query": f"/email {goal}",
            "routing": self._last_run.get("routing") or {},
            "responses": self._last_run.get("responses") or {},
            "links": self._last_run.get("links") or {},
            "attachments": [f["name"] for f in self.source_files],
            "email": {"subject": self._subject, "sent": sent, "failed": failed,
                      "recipients": len(getattr(self, "_recipients_sent", []))},
        }
        if self._draft_stage and self._last_run.get("agent"):
            record["agents"] = {self._draft_stage: self._last_run["agent"]}
        try:
            CB.config.save_run(record)
        except Exception as e:                                # noqa: BLE001
            self.status.setText(i18n.t(
                "Sent, but could not save to History: {error}").format(error=e))

    def _cleanup_workers(self):
        """Wind up every worker before this dialog is destroyed — a QThread
        destroyed while running aborts the whole process."""
        for worker in (self._worker, self._send_worker):
            if worker is None:
                continue
            try:
                if not worker.isRunning():
                    continue
                if hasattr(worker, "stop"):
                    worker.stop()
                if not worker.wait(4000):
                    worker.terminate()
                    worker.wait(500)
            except Exception:
                pass

    def accept(self):
        self._cleanup_workers()
        super().accept()

    def closeEvent(self, event):
        """Wind up every worker before this dialog is destroyed — a QThread
        destroyed while running aborts the whole process."""
        if self._send_worker and self._send_worker.isRunning():
            leave = QMessageBox.question(
                self, i18n.t("Still sending"),
                i18n.t("Emails are still going out. Stop and close?"))
            if leave != QMessageBox.Yes:
                event.ignore()
                return
        self._cleanup_workers()
        super().closeEvent(event)
