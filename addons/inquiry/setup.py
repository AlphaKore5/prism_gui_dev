"""Email inquiry automation — the settings that stay the same every day.

Asked once, at the start, and then never again. Everything here is a constant
of the business rather than of a particular inquiry: which mailboxes, which
rate list, what your terms are, who your customers are.

Laid out as four steps rather than one long form because the person filling it
in has never set up software before, and a screen with twenty boxes on it is
where they stop and telephone somebody.

The password is the one thing worth saying out loud: it goes into
~/.prism/config.json on this computer, the same file the sending account
already uses, and nowhere else. Prism has no server to send it to.

────────────────────────────────────────────────────────────────────────────
Several mailboxes, one register
────────────────────────────────────────────────────────────────────────────
The firms this is sold to do not have one inbox. Inquiries land on sales@,
info@ and the owner's own address, and today somebody copies all three into
one Excel sheet by hand. So the mailbox step takes a LIST, and every mailbox
feeds the same register in the same folder — point that folder at a shared
drive and the whole office reads one file, which is the system they already
run, minus the typing.

The config grew a shape for it: `cfg["inquiry"]["accounts"]` is the list,
and each entry carries its own `state` (the read bookmark), because two
mailboxes sharing one bookmark would skip or re-import each other's mail.
The old single-mailbox keys — `account` and `state` — are still written,
mirroring the first entry, so a config saved by this version opens cleanly
in the previous one and everything that still reads the old shape keeps
working. `accounts_of()` is the one reader that understands both.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
from widgets.loader import busy_button
from dialogs.base import PrismDialog
import theme
from widgets import controls as C
from widgets import icons
from workers import InboxVerifyWorker

# Moved to inquiry_config.py at the repo root, and re-exported here so that
# nothing which already imports them from this module has to change.
#
# They are pure functions over a dict -- no Qt, no engine -- and while they
# lived in this file, anything that needed to ask "is the mailbox set up?"
# had to import a 1,100-line Qt dialog to find out. dashboard_data.py (a root
# DATA module that feeds Home) and addons/inquiry/panel.py did exactly that,
# eight times between them, every one a deferred import inside a function
# because a module-level one would have been an obvious cycle.
#
# It also blocked the add-on split: Email inquiry automation could not move without
# taking Home with it.
from inquiry_config import (            # noqa: F401
    DEFAULT_FOLDER, accounts_of, active_accounts_of, is_active, is_complete,
    is_ready, settings_of,
)

# The old private spelling, still imported under that name from
# addons/inquiry/panel.py. See inquiry_config.is_complete.
_complete = is_complete


class _Picker(QWidget):
    """A read-only path box with a Browse button next to it."""

    def __init__(self, value: str = "", *, directory: bool = False,
                 filters: str = "", placeholder: str = "", parent=None):
        super().__init__(parent)
        self.directory, self.filters = directory, filters
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit(value)
        self.edit.setPlaceholderText(placeholder)
        row.addWidget(self.edit, stretch=1)
        browse = QPushButton(i18n.t("Browse…"))
        browse.clicked.connect(self._browse)
        row.addWidget(browse)

    def _browse(self):
        import paths
        start = self.edit.text().strip() or paths.picker_start_dir()
        if self.directory:
            # Captions are translated at the call site. QFileDialog's statics
            # are deliberately never patched — doing that once broke every
            # attachment in the app. See i18n.install().
            path = QFileDialog.getExistingDirectory(
                self, i18n.t("Choose a folder"), start)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, i18n.t("Choose a file"), start, self.filters)
        if path:
            self.edit.setText(path)

    def value(self) -> str:
        return self.edit.text().strip()


def _scrolled(page: QWidget) -> QScrollArea:
    """Let a step scroll rather than crush its own fields.

    Grouping the settings made each step taller than the dialog, and Qt's
    response to that is to compress the layouts until they fit: on "Your
    terms" the four quotation rows overlapped and their text was sliced in
    half. It also matters on a 1366x768 laptop — ordinary kit in a drawing
    office — where this dialog was already close to the ceiling.
    """
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.NoFrame)
    area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    area.setWidget(page)
    return area


def _group(title: str) -> tuple[QWidget, QFormLayout]:
    """A titled block with a form inside it, on the same rounded-card
    surface as the rest of the app.

    The three later steps were flat lists — nine boxes on "Your terms" with
    nothing to say that GST belongs with the quotation and "check every N
    minutes" does not. Grouping is the whole difference between a form you
    read and a form you survey. It was a bare QGroupBox before this pass —
    the one screen in Email inquiry automation not built from the shared Card, so it
    read as a generic native form bolted onto an otherwise designed app.
    """
    card = C.Card()
    col = card.body(margins=(16, 14, 16, 14), spacing=8)
    col.addWidget(C.kicker(title))
    form = QFormLayout()
    form.setContentsMargins(0, 4, 0, 0)
    form.setSpacing(9)
    col.addLayout(form)
    return card, form


class _Disclosure(QWidget):
    """A link-styled toggle with a body that folds away underneath it.

    Used for the long format explainers. They are genuinely useful — a cost
    sheet means a different document in every factory — but printed
    permanently they turned a five-field step into a page of grey prose, and
    the field somebody actually had to fill in scrolled off the bottom.
    """

    def __init__(self, label: str, body: str, parent=None, *, widget=None,
                 open_: bool = False):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(4)

        self.button = QPushButton(i18n.t(label))
        self.button.setObjectName("linkBtn")
        self.button.setCheckable(True)
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.setLayoutDirection(Qt.RightToLeft)
        icons.button_icon(self.button, "chevron-right", 13,
                          theme.ACCENT_RAMP[700])
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.button)
        row.addStretch(1)
        column.addLayout(row)

        # A body of prose, or -- for a field most people never need -- the
        # field itself, folded until the person says it applies to them.
        if widget is not None:
            self.body = widget
            self.body.setParent(self)
        else:
            self.body = QLabel(i18n.t(body), self)
            self.body.setWordWrap(True)
            self.body.setObjectName("meta")
        self.body.setVisible(False)
        column.addWidget(self.body)

        def toggle(is_open: bool):
            icons.button_icon(self.button,
                              "chevron-down" if is_open else "chevron-right",
                              13, theme.ACCENT_RAMP[700])
            self.body.setVisible(is_open)
        self.button.toggled.connect(toggle)
        if open_:
            self.button.setChecked(True)


class InquirySetupDialog(PrismDialog):

    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("Email inquiry automation — setup"),
            i18n.t("Set this up once. Prism then reads your inbox, sorts it, "
                   "and keeps your inquiry register without being asked "
                   "again."),
            icon="inbox", parent=parent, closable=False)
        self.setWindowTitle(i18n.t("Email inquiry automation — setup"))
        self.resize(760, 680)
        self.setMinimumSize(620, 520)
        self.cfg = dict(cfg)
        self._verify = None

        # Working copies of every configured mailbox, each carrying its own
        # read bookmark. One blank entry when nothing is configured yet, so
        # the first-run flow is still "type the address, type the password,
        # Save" with no list to understand first.
        self._accounts = accounts_of(cfg) or [{}]
        self._current = 0
        self._saved_password = self._accounts[0].get("password", "")

        # The intro moved into the header's subtitle — it is the sentence that
        # says what the whole window is for, which is exactly what a subtitle
        # is, and it was competing with the first tab for the top of the page.
        root = self.body
        self.tabs = QTabWidget()
        self.tabs.addTab(_scrolled(self._mail_tab()), i18n.t("1 · Mailbox"))
        self.tabs.addTab(_scrolled(self._folder_tab()), i18n.t("2 · Files"))
        self.tabs.addTab(_scrolled(self._terms_tab()), i18n.t("3 · Your terms"))
        self.tabs.addTab(_scrolled(self._people_tab()), i18n.t("4 · Who's who"))
        # Only the first two are needed to start reading mail — is_ready()
        # says so, and the customer had no way to know it. Somebody who
        # believes all four are compulsory stops at "Your terms" because they
        # have not decided their payment wording yet, and never gets to see
        # the thing work at all.
        for index, tip in ((0, i18n.t("Required — which mailbox to read")),
                           (1, i18n.t("Required — where to keep the register")),
                           (2, i18n.t("Optional — needed before you send a "
                                      "quotation, not before reading")),
                           (3, i18n.t("Optional — helps Prism tell customers "
                                      "from suppliers"))):
            self.tabs.setTabToolTip(index, tip)
        root.addWidget(self.tabs, stretch=1)
        self.work_folder.edit.textChanged.connect(self._update_tab_progress)
        self._update_tab_progress()

        self.step_hint = QLabel("")
        self.step_hint.setWordWrap(True)
        self.step_hint.setObjectName("meta")
        root.addWidget(self.step_hint)
        self.tabs.currentChanged.connect(self._describe_step)
        self._describe_step(0)

        self.footer.add_secondary(
            self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(
            self.button(i18n.t("Save"), "primary", icon_name="check",
                        on_click=self._save))

    def _describe_step(self, index: int):
        """Say what this step is for, and whether it can be skipped.

        Under the tabs rather than inside each one, so the sentence is in the
        same place every time and reads as guidance about the form rather than
        as one more instruction competing with the fields.
        """
        self.step_hint.setText({
            0: i18n.t("Required. Every mailbox your customers write to — "
                      "they all feed the same register."),
            1: i18n.t("Required. One folder holds the register and a folder "
                      "per inquiry — ordinary files that stay yours."),
            2: i18n.t("Optional for now. These go on quotations, so they are "
                      "needed before you send one — not before reading mail."),
            3: i18n.t("Optional. Listing your customers' domains helps Prism "
                      "tell an inquiry from a supplier's mail on day one."),
        }.get(index, ""))

    # ── 1. the mailboxes ──────────────────────────────────────────────────
    def _mail_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        note = C.label(i18n.t(
            "Prism only READS these mailboxes. It never marks anything as "
            "read, never moves anything and never deletes anything — "
            "everyone keeps using Outlook or their phone exactly as before."
            "\n\nPasswords are saved on this computer only. Prism has no "
            "server to send them to."), level="SUPPORT", wrap=True)
        layout.addWidget(note)

        # The list. Hidden while there is only the one mailbox: a list of one,
        # above a form asking for that same one, reads as two steps where the
        # customer has only one thing to do — and one mailbox is every
        # existing customer on the day they update.
        self.mailboxes = QListWidget()
        self.mailboxes.setFixedHeight(84)
        self.mailboxes.currentRowChanged.connect(self._mailbox_picked)
        layout.addWidget(self.mailboxes)

        list_row = QHBoxLayout()
        list_row.setSpacing(10)
        self.add_mailbox_btn = QPushButton(i18n.t("Add another mailbox"))
        self.add_mailbox_btn.setToolTip(i18n.t(
            "sales@, info@, the owner's own — inquiries from every one land "
            "in the same register"))
        self.add_mailbox_btn.clicked.connect(self._add_mailbox)
        list_row.addWidget(self.add_mailbox_btn)
        self.remove_mailbox_btn = QPushButton(i18n.t("Remove this mailbox"))
        self.remove_mailbox_btn.clicked.connect(self._remove_mailbox)
        list_row.addWidget(self.remove_mailbox_btn)
        list_row.addStretch(1)
        layout.addLayout(list_row)

        # Two questions, both of which the owner can answer without asking
        # anyone. Everything technical moved behind the disclosure below —
        # "Mail server" was the field that generated the support calls, and
        # asking for it up front contradicts this app's own rule that no
        # jargon reaches the screen.
        form = QFormLayout()
        form.setSpacing(10)
        self.addr = QLineEdit(self._accounts[0].get("address", ""))
        self.addr.setPlaceholderText("sales@yourcompany.co.in")
        self.addr.textChanged.connect(self._mail_input_changed)
        form.addRow(i18n.t("Email address:"), self.addr)

        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        C.add_password_visibility(self.password)
        self.password.setPlaceholderText(i18n.t(
            "leave blank to keep the saved password") if self._saved_password
            else i18n.t("your mail password"))
        self.password.textChanged.connect(self._mail_input_changed)
        # Enter in either box runs the check, rather than silently triggering
        # the dialog's default button and saving something untested.
        for box in (self.addr, self.password):
            box.returnPressed.connect(self._test)
        form.addRow(i18n.t("Password:"), self.password)
        layout.addLayout(form)

        # The placeholder alone was too quiet — a blank password box reads as
        # "empty" to anyone who has not memorised what the grey text says, and
        # that misreading is exactly what "the app password vanished" turned
        # out to be: the password was never lost, but nothing on screen said
        # so loudly enough to be believed. This is the loud version, and it is
        # kept in sync with _saved_password and what is actually typed rather
        # than shown once and forgotten.
        self.password_status = QLabel("")
        self.password_status.setWordWrap(True)
        layout.addWidget(self.password_status)
        self._update_password_status()

        # Park a mailbox without losing it. Somebody who stops watching an
        # address for a month should not have to delete the account and find
        # the app password again -- and deleting it would throw away the read
        # bookmark too, so switching it back on would re-import everything
        # since. Offered only with more than one mailbox: switching off your
        # only one stops the feature, and a checkbox is too quiet for that.
        self.read_box = QCheckBox(i18n.t("Read this mailbox"))
        # Seeded from the first account the way every other field on this tab
        # is, because _load_form() only runs when somebody SWITCHES mailbox.
        # Left to QCheckBox's own default it would start unticked, and
        # _commit_form() would then write active=False over a mailbox nobody
        # had touched -- switching off, on the first Save, the one mailbox a
        # single-mailbox customer has.
        self.read_box.setChecked(is_active(self._accounts[0]))
        self.read_box.setToolTip(i18n.t(
            "Unticked, Prism leaves this mailbox alone but keeps its "
            "password and remembers where it had read up to."))
        self.read_box.toggled.connect(self._read_toggled)
        layout.addWidget(self.read_box)

        layout.addSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(10)
        # Secondary, not primary. Save is this window's one solid accent
        # button and it sits in the footer; a second one inside the first tab
        # meant two competing calls to action were on screen at once, and the
        # louder of the two was the one that only checks a password.
        self.test_btn = QPushButton(i18n.t("Check this works"))
        self.test_btn.setCursor(Qt.PointingHandCursor)
        self.test_btn.setMinimumHeight(28)
        self.test_btn.clicked.connect(self._test)
        row.addWidget(self.test_btn)
        self.test_result = QLabel("")
        self.test_result.setWordWrap(True)
        row.addWidget(self.test_result, stretch=1)
        layout.addLayout(row)

        gmail = C.label(i18n.t(
            "Gmail and Outlook need an app password rather than your normal "
            "one. A mailbox on your own company domain usually takes the "
            "normal password."), role="meta", wrap=True)
        layout.addWidget(gmail)

        # The gap this fills: the note above NAMES the app-password
        # requirement but never says how to get one, which is exactly the
        # point a first-time, non-technical user gives up and phones
        # somebody. Same disclosure idiom as the format explainers below.
        layout.addWidget(_Disclosure(
            "How do I get an app password?",
            "Gmail: open myaccount.google.com on your phone or computer -> "
            "Security -> turn on 2-Step Verification if it isn't already on "
            "-> App passwords -> create one named \"Prism\" or \"Mail\" -> "
            "Google shows a 16-letter code. Paste that code into the "
            "Password box here — not your normal Gmail password.\n\n"
            "Outlook / Microsoft 365: open account.microsoft.com -> "
            "Security -> Advanced security options -> App passwords -> "
            "Create a new app password. Paste the code it shows into the "
            "Password box here.\n\n"
            "A mailbox on your own company domain (not Gmail or Outlook) "
            "almost always takes your everyday password instead — try that "
            "first."))

        # ── behind the disclosure ────────────────────────────────────────
        layout.addSpacing(6)
        self.advanced_btn = QPushButton(i18n.t("Server settings"))
        self.advanced_btn.setObjectName("linkBtn")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setCursor(Qt.PointingHandCursor)
        self.advanced_btn.setLayoutDirection(Qt.RightToLeft)
        self.advanced_btn.setToolTip(i18n.t(
            "Only needed if the check above cannot find your server"))
        icons.button_icon(self.advanced_btn, "chevron-right", 14,
                          theme.ACCENT_RAMP[700])
        # RightToLeft puts the chevron after the label, but it also mirrors
        # the alignment QBoxLayout would apply — passing AlignLeft pinned the
        # row to the right edge. The stretch does the aligning instead.
        adv_row = QHBoxLayout()
        adv_row.setContentsMargins(0, 0, 0, 0)
        adv_row.addWidget(self.advanced_btn)
        adv_row.addStretch(1)
        layout.addLayout(adv_row)

        self.advanced = QWidget(self)
        adv = QFormLayout(self.advanced)
        adv.setContentsMargins(0, 6, 0, 0)
        self.host = QLineEdit(self._accounts[0].get("host", ""))
        self.host.setPlaceholderText(i18n.t("found automatically — leave blank"))
        adv.addRow(i18n.t("Mail server:"), self.host)
        self.folder_name = QLineEdit(
            self._accounts[0].get("folder", "") or "INBOX")
        adv.addRow(i18n.t("Folder to read:"), self.folder_name)
        self.advanced.setVisible(False)
        layout.addWidget(self.advanced)

        def _toggle(open_: bool):
            icons.button_icon(self.advanced_btn,
                              "chevron-down" if open_ else "chevron-right",
                              14, theme.ACCENT_RAMP[700])
            self.advanced.setVisible(open_)
        self.advanced_btn.toggled.connect(_toggle)
        # Opened on arrival when a server was set by hand, so a setting that
        # is in force is never hidden from the person who set it.
        if self._accounts[0].get("host"):
            self.advanced_btn.setChecked(True)

        layout.addStretch(1)
        self._set_test_state("")
        self._loading = False
        self._refresh_mailboxes()
        return page

    # ── the mailbox list ──────────────────────────────────────────────────
    def _refresh_mailboxes(self):
        """Redraw the list to match the working copies, without re-entering
        the selection handler on the way past."""
        self._loading = True
        self.mailboxes.clear()
        for account in self._accounts:
            address = account.get("address", "").strip()
            host = account.get("host", "").strip()
            label = (f"{address}   ·   {host}" if address and host
                     else address or i18n.t("(new mailbox — type the address "
                                            "below)"))
            if not is_active(account):
                label = i18n.t("{who} — not being read").replace("{who}", label)
            self.mailboxes.addItem(QListWidgetItem(label))
        self.mailboxes.setCurrentRow(self._current)
        # A list of one, above a form asking for that same one, reads as two
        # steps where there is only one thing to do.
        several = len(self._accounts) > 1
        self.mailboxes.setVisible(several)
        self.remove_mailbox_btn.setVisible(several)
        self.read_box.setVisible(several)
        self._loading = False

    def _commit_form(self):
        """Fold whatever is typed into the mailbox being edited.

        Lenient on purpose: an entry can sit half-filled while another is
        edited — Save is where completeness is checked, with the same message
        it has always shown. The bookmark (`state`) is never touched here, so
        editing an address cannot cost the account its place in the mailbox;
        a genuinely different mailbox behind the same entry is caught by the
        server's own UIDVALIDITY and starts over safely.
        """
        account = self._accounts[self._current]
        account["address"] = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        if password:
            account["password"] = password
        account["host"] = self.host.text().strip() or account.get("host", "")
        account["folder"] = self.folder_name.text().strip() or "INBOX"
        account["active"] = self.read_box.isChecked()
        account.setdefault("port", 993)

    def _load_form(self, index: int):
        """Show one mailbox in the form. The password box is always cleared —
        a saved password is kept by leaving it blank, never displayed."""
        self._loading = True
        account = self._accounts[index]
        self._saved_password = account.get("password", "")
        self.addr.setText(account.get("address", ""))
        self.password.clear()
        self.password.setPlaceholderText(i18n.t(
            "leave blank to keep the saved password") if self._saved_password
            else i18n.t("your mail password"))
        self.host.setText(account.get("host", ""))
        self.folder_name.setText(account.get("folder", "") or "INBOX")
        self.read_box.setChecked(is_active(account))
        self._tested_ok = False
        self._set_test_state("")
        # Explicit, not relied on via password.clear()'s textChanged: Qt does
        # not emit that signal when the box was already empty, which is
        # exactly the case switching between two unfilled-password rows — and
        # that is the one case where a stale "already saved" from the row
        # left behind would be believed most easily.
        self._update_password_status()
        if account.get("host"):
            self.advanced_btn.setChecked(True)
        self._loading = False

    def _read_toggled(self, _on: bool):
        if self._loading:
            return
        self._accounts[self._current]["active"] = self.read_box.isChecked()
        self._refresh_mailboxes()

    def _mailbox_picked(self, row: int):
        if self._loading or row < 0 or row == self._current:
            return
        self._commit_form()
        self._current = row
        self._load_form(row)
        self._refresh_mailboxes()

    def _add_mailbox(self):
        self._commit_form()
        current = self._accounts[self._current]
        if not current.get("address"):
            # Two blank entries help nobody — finish this one first.
            self.addr.setFocus()
            self._set_test_state(i18n.t(
                "Type this mailbox's address first, then add the next one."))
            return
        self._accounts.append({})
        self._current = len(self._accounts) - 1
        self._load_form(self._current)
        self._refresh_mailboxes()
        self.addr.setFocus()

    def _remove_mailbox(self):
        account = self._accounts[self._current]
        address = account.get("address", "").strip()
        if address:
            answer = QMessageBox.question(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Stop reading {who}?\n\nPrism simply stops checking "
                       "that mailbox. Nothing already in the register is "
                       "touched.").replace("{who}", address),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        if len(self._accounts) == 1:
            self._accounts[0] = {}
        else:
            self._accounts.pop(self._current)
            self._current = max(0, self._current - 1)
        self._load_form(self._current)
        self._refresh_mailboxes()

    # ── the connection check ──────────────────────────────────────────────
    def _mail_input_changed(self):
        """Editing the address or password invalidates the last result. A
        green "Connected" left standing over changed details is a lie, and
        it is the one the customer would rely on."""
        if getattr(self, "_tested_ok", False):
            self._tested_ok = False
            self._set_test_state("")
        self._update_password_status()
        self._update_tab_progress()

    def _update_password_status(self):
        """Say, in words nobody can miss, whether the password box being
        blank means "nothing saved" or "already saved, and staying that
        way." Silent otherwise, once something new has actually been typed —
        at that point the box speaks for itself."""
        if self.password.text():
            self.password_status.setText("")
            self.password_status.setVisible(False)
            return
        if self._saved_password:
            self.password_status.setText(i18n.t(
                "✓ A password is already saved for this mailbox. Leave this "
                "box blank and it stays exactly as it is — nothing is "
                "removed by opening or saving this screen. Type a new one "
                "here only if you want to replace it."))
            self.password_status.setStyleSheet(
                f"color: {theme.OK_INK}; font-size: 12.5px;")
        else:
            self.password_status.setText(i18n.t(
                "No password saved yet for this mailbox."))
            self.password_status.setStyleSheet(
                f"color: {theme.NEUTRAL[600]}; font-size: 12.5px;")
        self.password_status.setVisible(True)

    def _update_tab_progress(self):
        """Mark a tab done once it has what it needs, so the wizard reads as
        "2 of 4 done" rather than four identical tabs. A hint only — Save's
        own validation (see _save) is still what actually enforces
        completeness; nothing here can let an incomplete setup through."""
        mail_done = bool(self.addr.text().strip()) and bool(
            self.password.text().strip() or self._saved_password)
        work_folder = getattr(self, "work_folder", None)
        files_done = bool(work_folder and work_folder.value())
        check = QIcon(icons.pixmap("check", 14, theme.OK))
        self.tabs.setTabIcon(0, check if mail_done else QIcon())
        self.tabs.setTabIcon(1, check if files_done else QIcon())

    def _set_test_state(self, text: str, tone: str = ""):
        """One place that paints the result, so success and failure cannot
        drift into looking alike."""
        colour = {"ok": theme.OK_INK, "err": theme.ERR,
                  "busy": theme.NEUTRAL[600]}.get(tone, theme.NEUTRAL[600])
        self.test_result.setText(text)
        self.test_result.setStyleSheet(
            f"color: {colour}; font-size: 12.5px;"
            f"{' font-weight: 600;' if tone == 'ok' else ''}")

    def _test(self):
        address = self.addr.text().strip()
        password = self.password.text() or self._saved_password
        # The Mail server box was being ignored entirely: someone who already
        # knew their server could type it in, press this, and get "the mail
        # server didn't answer" about three hosts they never named.
        typed_host = self.host.text().strip()
        if not address or not password:
            self._set_test_state(
                i18n.t("Enter the address and password first."), "err")
            return
        busy_button(self.test_btn, True, i18n.t("Testing"))
        self._set_test_state(
            i18n.t("Testing {host}…").replace("{host}", typed_host)
            if typed_host else i18n.t("Checking your mailbox…"), "busy")

        def finished(settings: dict, error: str):
            busy_button(self.test_btn, False)
            if error:
                self._tested_ok = False
                self._set_test_state(error, "err")
                # Detection genuinely could not place the server, so the box
                # for typing it stops being an advanced setting and becomes
                # the next thing to do. Opened rather than merely mentioned:
                # a disclosure nobody opens is a dead end.
                if not typed_host:
                    self.advanced_btn.setChecked(True)
                    self.host.setFocus()
                return
            self._tested_ok = True
            self.host.setText(settings.get("host", ""))
            self._accounts[self._current].update(settings)
            self._set_test_state(
                i18n.t("Connected to {host}. You can Save.").replace(
                    "{host}", settings.get("host", "")), "ok")

        self._verify = InboxVerifyWorker(address, password, typed_host)
        self._verify.done.connect(finished)
        self._verify.start()

    def closeEvent(self, event):
        """Wind up the connection test before this dialog is destroyed.

        "Check this works" starts an InboxVerifyWorker that sits in a blocking
        DNS/IMAP call — tens of seconds on a wrong host. Closing the dialog
        while it runs would destroy a live QThread, and Qt's ~QThread qFatal()s
        on that — a hard crash. The worker has no stop() (nothing to interrupt
        a socket mid-connect), so the only move is a bounded wait then
        terminate the overrun.
        """
        w = self._verify
        if w is not None:
            try:
                if w.isRunning():
                    if not w.wait(3000):
                        w.terminate()
                        w.wait(1000)
            except RuntimeError:
                pass        # already deleted; nothing to wait for
        super().closeEvent(event)

    # ── 2. where things are kept ──────────────────────────────────────────
    def _folder_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)

        note = C.label(i18n.t(
            "Everything Prism produces lands in one folder you choose — the "
            "inquiry register, and a folder per inquiry holding the mail and "
            "the drawings. They are ordinary files: the register opens in "
            "Excel, and it stays yours whatever happens to Prism."),
            level="SUPPORT", wrap=True)
        layout.addWidget(note)

        # The one thing this step actually requires, on its own. It used to sit
        # first in a flat list of five pickers, four of which are optional and
        # none of which said so — a client filled in all five or stopped.
        need, need_form = _group("The one folder Prism needs")
        self.work_folder = _Picker(saved.get("folder", "") or DEFAULT_FOLDER,
                                   directory=True)
        need_form.addRow(i18n.t("Keep everything in:"), self.work_folder)

        # The centralised half of the feature, said where the folder is
        # chosen: the register is one file, so putting the folder on the
        # shared drive IS the whole team seeing the same sheet. When a team
        # workspace is already set up, offer it in one click rather than a
        # sentence of directions.
        import workspace
        if workspace.is_shared(self.cfg):
            shared_row = QHBoxLayout()
            shared_note = C.label(i18n.t(
                "Your team workspace is set up — keep this folder in it and "
                "every member sees the same register."), role="meta",
                wrap=True)
            shared_row.addWidget(shared_note, stretch=1)
            use_shared = QPushButton(i18n.t("Use the team folder"))
            use_shared.clicked.connect(lambda: self.work_folder.edit.setText(
                os.path.join(workspace.company_dir(self.cfg), "inquiries")))
            shared_row.addWidget(use_shared)
            need_form.addRow(shared_row)
        else:
            shared_note = C.label(i18n.t(
                "Several people? Choose a folder on your shared drive and "
                "everyone opens the same register — the same sheet you keep "
                "by hand today, kept by Prism instead."), role="meta",
                wrap=True)
            need_form.addRow(shared_note)
        layout.addWidget(need)

        # Everything below is for QUOTING. Reading the inbox and building the
        # register works with none of it, and saying so is what lets somebody
        # finish setup today and add their price list next week.
        later, later_form = _group("Your price list — so Prism can quote")
        price_note = C.label(i18n.t(
            "Your catalogue, one row per product: the product code, its "
            "name, the unit and the price. Prism finds the code a customer "
            "wrote (or sent in a picture), takes the price from this list, "
            "and prepares the quotation. Excel, CSV, PDF or Word."),
            role="meta", wrap=True)
        later_form.addRow(price_note)
        self.rate_file = _Picker(
            saved.get("rate_list", ""),
            filters=i18n.t("Price lists (*.csv *.xlsx *.xlsm *.pdf *.docx *.txt);;"
                           "All files (*)"),
            placeholder=i18n.t("your catalogue with codes and prices"))
        later_form.addRow(i18n.t("Price list (catalogue):"), self.rate_file)

        # Quote by code, without a person. Off unless switched on: a price
        # going to a customer on its own is the owner's decision, and the
        # gate is deliberately strict -- every code in the mail must be on
        # the list and every line must carry a written quantity; anything
        # less is held in "To quote" with the reason on the row.
        self.auto_quote = QCheckBox(i18n.t(
            "Quote automatically when the mail names product codes from "
            "this list with quantities"))
        self.auto_quote.setChecked(bool(saved.get("auto_quote", False)))
        self.auto_quote.setToolTip(i18n.t(
            "Sent from your default account with the saved terms. A mail "
            "with a code Prism cannot find, or a code with no quantity, is "
            "held for you instead."))
        later_form.addRow("", self.auto_quote)

        # Only for a shop that has no fixed price per product and works a
        # price out from material, labour and overheads. A catalogue seller
        # never needs it, so it sits folded under the price list rather than
        # beside it as an equal -- side by side, half the people asked which
        # of the two their catalogue went into.
        self.cost_file = _Picker(
            saved.get("cost_sheet", ""),
            filters=i18n.t("Cost sheets (*.csv *.xlsx *.xlsm);;All files (*)"),
            placeholder=i18n.t("optional — only if you have no fixed prices"))
        cost_box = QWidget()
        cost_col = QVBoxLayout(cost_box)
        cost_col.setContentsMargins(0, 0, 0, 0)
        cost_col.setSpacing(theme.SPACE_1)
        cost_col.addWidget(C.label(i18n.t(
            "No fixed price per product? If you work a price out each time "
            "from material, labour and overheads, give Prism that working "
            "here instead. Most catalogue sellers skip this."),
            role="meta", wrap=True))
        cost_col.addWidget(self.cost_file)
        self.cost_disclosure = _Disclosure(
            "I don't have fixed prices — I work each price out",
            "", widget=cost_box, open_=bool(saved.get("cost_sheet")))
        later_form.addRow(self.cost_disclosure)

        # How far the owner will bend, in their own words. Only ever read when
        # they press "Win this back", and the negotiation prompt refuses to
        # offer anything at all when it is missing — the safe direction to
        # fail in is "no discount", not "some discount".
        self.policy_file = _Picker(
            saved.get("pricing_policy", ""),
            filters=i18n.t("Any document (*.pdf *.docx *.txt *.csv *.xlsx);;"
                           "All files (*)"),
            placeholder=i18n.t("optional — how much you can bargain"))
        later_form.addRow(i18n.t("Bargaining limits:"), self.policy_file)
        layout.addWidget(later)

        # The long format explainers, folded away. They are worth having —
        # "cost sheet" means a different document in every factory — but
        # printed permanently they pushed the fields off the bottom.
        layout.addWidget(_Disclosure(
            "What should a rate list look like?",
            "A rate list needs a heading row with at least a description and "
            "a rate — for example: Code, Description, Unit, Rate. A "
            "letterhead above it is fine. Columns like \"Rate @ 1000\" are "
            "read as quantity discounts. Excel and CSV read best; a PDF or "
            "Word file works when its table has real text (not a scan).\n\n"
            "Give every product its code and customers can order by it: "
            "\"1128K x 40\" in a mail is matched to the row exactly, and "
            "with the switch above on, quoted without you."))
        layout.addWidget(_Disclosure(
            "What should a cost sheet look like?",
            "A cost sheet is your own working, three columns wide: the name "
            "of the charge, how it is charged, and the rate. Prism does the "
            "arithmetic and shows every line — it never invents a rate.\n\n"
            "    Wire,          per_kg,     95\n"
            "    Coiling,       per_piece,  1.20\n"
            "    Tool setting,  per_lot,    800\n"
            "    Overheads,     percent,    12\n\n"
            "Percentages apply to the total of the lines above them, so the "
            "order of your rows is the order of your own calculation."))

        # A shop that has been trading for twenty years already keeps an
        # inquiry list. Starting them at row one would mean running two
        # registers side by side until they gave up on ours.
        already, already_form = _group("Your old inquiry list (optional)")
        already_form.addRow(C.label(i18n.t(
            "Been writing inquiries down in an Excel sheet until now? Give "
            "Prism that sheet once and it carries on from your last number, "
            "with your old inquiries in the register. This is NOT your price "
            "list — that goes above."), role="meta", wrap=True))
        self.existing_register = _Picker(
            "", filters=i18n.t("Inquiry lists (*.csv *.xlsx);;All files (*)"),
            placeholder=i18n.t("optional — the sheet you kept by hand"))
        already_form.addRow(i18n.t("Old inquiry sheet:"), self.existing_register)
        self.import_note = QLabel("")
        self.import_note.setWordWrap(True)
        self.import_note.setObjectName("meta")
        already_form.addRow(self.import_note)
        layout.addWidget(already)

        layout.addStretch(1)
        return page

    # ── 3. terms that go on every quotation ───────────────────────────────
    def _terms_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)
        terms = saved.get("terms") or {}

        # Three unrelated things used to sit in one nine-row list: who you
        # are, what your quotation says, and how often Prism does things by
        # itself. Nothing said which was which, so all nine read as equally
        # consequential — and the two that change Prism's *behaviour* were the
        # least visible of the lot.
        head, head_form = _group("Who the quotation comes from")
        self.company = QLineEdit(saved.get("company", ""))
        self.company.setPlaceholderText(i18n.t("as it should appear on the quotation"))
        head_form.addRow(i18n.t("Company name:"), self.company)

        self.signature = QLineEdit(saved.get("signature", ""))
        self.signature.setPlaceholderText(i18n.t("who quotations are signed by"))
        head_form.addRow(i18n.t("Sign off as:"), self.signature)
        layout.addWidget(head)

        quote, quote_form = _group("What goes on every quotation")
        self.gst = QSpinBox()
        self.gst.setRange(0, 100)
        self.gst.setSuffix(" %")
        self.gst.setValue(int(terms.get("gst_percent", 18) or 0))
        quote_form.addRow(i18n.t("GST:"), self.gst)

        self.validity = QSpinBox()
        self.validity.setRange(1, 365)
        self.validity.setSuffix(i18n.t(" days"))
        self.validity.setValue(int(terms.get("validity_days", 15) or 15))
        quote_form.addRow(i18n.t("Quotation valid for:"), self.validity)

        self.payment = QLineEdit(terms.get("payment", "") or
                                 "100% against proforma invoice")
        quote_form.addRow(i18n.t("Payment terms:"), self.payment)

        self.delivery = QLineEdit(terms.get("delivery", "") or
                                  "2–3 weeks from receipt of confirmed order")
        quote_form.addRow(i18n.t("Delivery:"), self.delivery)
        layout.addWidget(quote)

        # The two settings that make Prism act on its own. Grouped and named
        # so that "it emailed my customer without asking" can never be a
        # surprise — it is set here, in a box that says so.
        chase, chase_form = _group("When Prism chases a quiet quotation")
        self.followup_days = QSpinBox()
        self.followup_days.setRange(1, 60)
        self.followup_days.setSuffix(i18n.t(" days"))
        self.followup_days.setValue(int(saved.get("followup_days", 2) or 2))
        chase_form.addRow(i18n.t("Chase after:"), self.followup_days)

        self.max_reminders = QSpinBox()
        self.max_reminders.setRange(1, 6)
        self.max_reminders.setSuffix(i18n.t(" times"))
        self.max_reminders.setValue(int(saved.get("max_reminders", 3) or 3))
        chase_form.addRow(i18n.t("Then stop after:"), self.max_reminders)

        self.auto_minutes = QSpinBox()
        self.auto_minutes.setRange(0, 240)
        self.auto_minutes.setSuffix(i18n.t(" minutes"))
        self.auto_minutes.setSpecialValueText(i18n.t("only when I ask"))
        self.auto_minutes.setValue(int(saved.get("auto_minutes", 0) or 0))
        chase_form.addRow(i18n.t("Check the inbox every:"), self.auto_minutes)
        layout.addWidget(chase)

        auto_note = C.label(i18n.t(
            "Automatic checking only ever READS your mail. Ten minutes suits "
            "most offices; below five is more often than any mail server "
            "expects to be asked."), role="meta", wrap=True)
        layout.addWidget(auto_note)

        self.auto_followup = QCheckBox(i18n.t(
            "Send the reminders by themselves, without asking me each time"))
        self.auto_followup.setChecked(bool(saved.get("auto_followup", False)))
        layout.addWidget(self.auto_followup)

        chase_note = C.label(i18n.t(
            "With this ticked, a quotation nobody has replied to is chased on "
            "the schedule above and the register is updated — the whole thing "
            "runs without you. Every reminder is written afresh rather than "
            "the same sentence three times, and Prism stops the moment they "
            "reply.\n\n"
            "It is off to begin with because these are letters going out in "
            "your name. Leave it off for the first week, watch what the "
            "reminders say, then turn it on once you trust them."),
            role="meta", wrap=True)
        layout.addWidget(chase_note)
        layout.addStretch(1)
        return page

    # ── 4. who is who ─────────────────────────────────────────────────────
    def _people_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        saved = settings_of(self.cfg)
        known = saved.get("knowledge") or {}

        note = C.label(i18n.t(
            "Telling Prism who your customers and suppliers are makes the "
            "sorting right from day one instead of week three — and it keeps "
            "their mail on this computer, because a sender Prism already "
            "recognises never has to be looked at by an AI.\n\n"
            "One line each. A whole company works: type shaktiauto.in and "
            "everybody there is covered."), level="SUPPORT", wrap=True)
        layout.addWidget(note)

        def box(title: str, values, placeholder: str) -> QPlainTextEdit:
            card = C.Card()
            inner = card.body(margins=(16, 14, 16, 14), spacing=8)
            inner.addWidget(C.kicker(title))
            edit = QPlainTextEdit("\n".join(values or []))
            edit.setPlaceholderText(placeholder)
            edit.setFixedHeight(74)
            inner.addWidget(edit)
            layout.addWidget(card)
            return edit

        self.own = box(i18n.t("Your own company's addresses"),
                       known.get("own_domains"), "yourcompany.co.in")
        self.customers = box(i18n.t("Customers"), known.get("customers"),
                             "shaktiauto.in\nbuyer@gujaratmotors.in")
        self.vendors = box(i18n.t("Suppliers"), known.get("vendors"),
                           "steelsupply.co.in")

        # Its own titled block. This decides whether any of the customer's
        # mail ever leaves their machine, which makes it the most consequential
        # control in the whole dialog — and it was a bare tickbox under three
        # text areas, reading like a preference about notifications.
        privacy = C.Card()
        privacy_box = privacy.body(margins=(16, 14, 16, 14), spacing=8)
        privacy_box.addWidget(C.kicker(i18n.t("Privacy")))
        self.local_only = QCheckBox(i18n.t(
            "Keep everything on this computer — never send any mail to an AI"))
        self.local_only.setChecked(bool(saved.get("local_only", False)))
        privacy_box.addWidget(self.local_only)

        explain = C.label(i18n.t(
            "With this ticked, Prism sorts using only the rules above and "
            "anything it cannot place is listed for you to glance at. "
            "Nothing whatsoever leaves the machine. Untick it and only the "
            "few messages from senders Prism does not recognise are sent to "
            "be labelled."), role="meta", wrap=True)
        privacy_box.addWidget(explain)
        layout.addWidget(privacy)
        layout.addStretch(1)
        return page

    # ── bringing an existing register in ──────────────────────────────────
    def _import_register(self, folder: str) -> str:
        """Copy the customer's own inquiry list in, once.

        Rules, in the order they matter:

          · **Never overwrite a register that already has rows in it.** That
            file is the only copy of their order book. If one is already
            there, this does nothing and says so.
          · **Never rewrite their columns.** register.load/save keep unknown
            columns untouched, so their "Party Name" or "Remarks" survive
            exactly as typed and sit alongside Prism's.
          · **Say what was recognised.** A register whose columns Prism cannot
            read still imports, but the screen will show blanks in those
            columns, and finding that out on Monday is worse than being told
            now.

        Returns a sentence for the screen, or "" when there was nothing to do.
        """
        source = self.existing_register.value()
        if not source:
            return ""
        register = CB.get_register()
        destination = os.path.join(folder, register.FILENAME)

        if os.path.exists(destination):
            try:
                already = register.load(destination)
            except Exception:
                already = [None]        # unreadable, but present — leave it
            if already:
                return i18n.t(
                    "There is already an inquiry register in that folder with "
                    "{n} row(s), so it was left alone. Nothing was imported."
                ).replace("{n}", str(len(already)))

        try:
            rows = register.load(source)
        except Exception as e:
            return i18n.t("Couldn't read that register: {why}").replace(
                "{why}", str(e))
        if not rows:
            return i18n.t("That file has no rows in it, so nothing was imported.")

        try:
            register.save(rows, destination)
        except Exception as e:
            return i18n.t("Couldn't write the register: {why}").replace(
                "{why}", str(e))

        # Which of ours they already have. Reported rather than corrected: a
        # column-guessing importer that got it wrong would quietly mis-file
        # somebody's twenty-year order book.
        theirs = set(rows[0].keys())
        wanted = ("Inquiry no", "Date received", "Customer", "Status")
        missing = [c for c in wanted if c not in theirs]
        message = i18n.t("Imported {n} row(s) from your register.").replace(
            "{n}", str(len(rows)))
        if missing:
            message += " " + i18n.t(
                "Prism didn't find these columns in it — {cols} — so those "
                "boxes will be empty on the Inquiries screen until you fill "
                "them in. Everything you already had is untouched."
            ).replace("{cols}", ", ".join(missing))
        return message

    # ── saving ────────────────────────────────────────────────────────────
    @staticmethod
    def _lines(edit: QPlainTextEdit) -> list[str]:
        return [line.strip().lower().lstrip("@")
                for line in edit.toPlainText().splitlines() if line.strip()]

    def _save(self):
        self._commit_form()
        folder = self.work_folder.value()

        # Blank entries are scaffolding, not mistakes — somebody pressed "Add
        # another" and changed their mind. Dropped without comment.
        accounts = [dict(a) for a in self._accounts if a.get("address")]

        incomplete = next((a for a in accounts if not a.get("password")),
                          None)
        if not accounts or incomplete is not None:
            who = (incomplete or {}).get("address", "")
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Prism needs the email address and password of every "
                       "mailbox to read. Nothing else can start without "
                       "them.") + (f"\n\n{who}" if who else ""))
            self.tabs.setCurrentIndex(0)
            return
        if not any(is_active(a) for a in accounts):
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("At least one mailbox has to be read, or there is "
                       "nothing for Prism to check."))
            self.tabs.setCurrentIndex(0)
            return
        if not folder:
            QMessageBox.information(
                self, i18n.t("Email inquiry automation"),
                i18n.t("Choose a folder for the inquiry register and the "
                       "files that come with each inquiry."))
            self.tabs.setCurrentIndex(1)
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Email inquiry automation"), str(e))
            self.tabs.setCurrentIndex(1)
            return

        inbox = CB.get_inbox()
        for account in accounts:
            if not account.get("host"):
                # No Test run and no saved host — work it out now rather than
                # failing on the first check with a message about a server the
                # customer never typed.
                guesses = inbox.guess_hosts(account["address"])
                account["host"] = guesses[0] if guesses else ""
            account["port"] = int(account.get("port") or 993)
            account["folder"] = account.get("folder") or "INBOX"
            # Each mailbox keeps its own read bookmark. Two mailboxes sharing
            # one would skip or re-import each other's mail — see accounts_of.
            account["state"] = dict(account.get("state") or {})

        first = accounts[0]
        self.cfg["inquiry"] = {
            "accounts": accounts,
            # The single-mailbox keys, mirroring the first entry. Everything
            # that predates the list — including a Prism from before this
            # version reading the same config — keeps working; accounts_of()
            # prefers the list and never reads these when it is present.
            "account": {k: v for k, v in first.items() if k != "state"},
            "folder": folder,
            "rate_list": self.rate_file.value(),
            "auto_quote": self.auto_quote.isChecked(),
            "cost_sheet": self.cost_file.value(),
            "company": self.company.text().strip(),
            "signature": self.signature.text().strip(),
            "terms": {"gst_percent": self.gst.value(),
                      "validity_days": self.validity.value(),
                      "payment": self.payment.text().strip(),
                      "delivery": self.delivery.text().strip()},
            "pricing_policy": self.policy_file.value(),
            "followup_days": self.followup_days.value(),
            "max_reminders": self.max_reminders.value(),
            "auto_minutes": self.auto_minutes.value(),
            "auto_followup": self.auto_followup.isChecked(),
            "local_only": self.local_only.isChecked(),
            "knowledge": {"own_domains": self._lines(self.own),
                          "customers": self._lines(self.customers),
                          "vendors": self._lines(self.vendors),
                          # Corrections the customer makes as they go. Kept
                          # across saves so re-opening setup never forgets
                          # what Prism has learned about their senders.
                          # Shared across every mailbox on purpose: a sender
                          # is the same sender whichever address they wrote
                          # to, and teaching Prism twice would be a chore.
                          "learned": ((settings_of(self.cfg).get("knowledge")
                                       or {}).get("learned") or {})},
            # The first mailbox's bookmark, mirrored — see "account" above.
            "state": dict(first.get("state") or {}),
        }
        CB.config.save(self.cfg)

        # Last, and after the config is safely written: an import that fails
        # must not also cost them the settings they just typed in.
        imported = self._import_register(folder)
        if imported:
            self.import_note.setText(imported)
            QMessageBox.information(self, i18n.t("Inquiry register"), imported)
        self.accept()
