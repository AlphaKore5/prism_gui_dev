"""Contact the team — the last tier of Help & support: an actual person.

No ticketing system and no web form on purpose. Email is the one channel
every customer already has open, that works from a factory office with a
strict firewall, and that leaves them holding a copy of what they sent.

Why the conversation becomes the email: by the time somebody reaches this
sheet they have already told the help screen what is wrong, what they tried
and what did not work. Making them type it a second time into an empty mail
window is how a support request turns into "it doesn't work" plus a
screenshot, which costs two more round trips to unpick. So the sheet arrives
pre-filled with the transcript and the version and licence details, and they
can delete whatever they do not want to send.

Three ways out, because `mailto:` is not reliable everywhere — a machine
with no mail client configured silently does nothing, and a customer who
presses a button that appears to do nothing concludes the whole feature is
broken. Copy and Save always work.
"""
from __future__ import annotations

import time
from urllib.parse import quote

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

import app_meta
import i18n
import theme
from dialogs.base import PrismDialog
from widgets import icons
from widgets.controls import heading


class ContactDialog(PrismDialog):

    def __init__(self, transcript: str = "", parent=None):
        super().__init__(
            i18n.t("Send this to our team"),
            i18n.t("Everything you've already told the help screen is below — "
                   "edit or delete anything you'd rather not send."),
            icon="mail", parent=parent, closable=False)
        self.sent = False
        self._transcript = transcript
        self.setWindowTitle(i18n.t("Contact the team"))
        self.setMinimumWidth(560)
        self.resize(660, 680)

        root = self.body

        who = QHBoxLayout()
        who.setSpacing(theme.SPACE_2)
        self._name = QLineEdit()
        self._name.setPlaceholderText(i18n.t("Your name"))
        self._name.setMinimumHeight(36)
        self._email = QLineEdit()
        self._email.setPlaceholderText(i18n.t("Your email address"))
        self._email.setMinimumHeight(36)
        try:
            import identity
            self._name.setText(identity.current().get("name", "") or "")
        except Exception:                   # noqa: BLE001
            pass
        who.addWidget(self._name)
        who.addWidget(self._email)
        root.addLayout(who)

        self._body = QPlainTextEdit()
        self._body.setPlainText(self._draft())
        self._body.setMinimumHeight(240)
        root.addWidget(self._body, stretch=1)

        told = QLabel(i18n.t(
            "Your licence key, your password and the key Prism plans with are "
            "not included in this and never will be."))
        told.setObjectName("meta")
        told.setWordWrap(True)
        root.addWidget(told)

        where = QLabel(f"{app_meta.SUPPORT_EMAIL}   ·   {app_meta.SUPPORT_PHONE}"
                      f"   ·   {app_meta.WEBSITE}")
        where.setTextInteractionFlags(Qt.TextSelectableByMouse)
        where.setStyleSheet(
            f"color: {theme.ACCENT_RAMP[700]}; font-size: 13px;"
            f"font-weight: 600;")
        root.addWidget(where)

        # Copy and Save are the two that always work — `mailto:` silently does
        # nothing on a machine with no mail client configured — so they stay
        # visible as utilities rather than being folded away behind the
        # primary.
        self._copy = self.button(i18n.t("Copy it all"), "secondary",
                                 icon_name="copy", small=True,
                                 on_click=self._copy_all)
        self.footer.add_utility(self._copy)
        self.footer.add_utility(self.button(
            i18n.t("Save as a file"), "secondary", icon_name="file",
            small=True, on_click=self._save,
            tooltip=i18n.t("Writes this plus a description of your "
                           "installation, with your key and passwords "
                           "stripped out, so you can attach it.")))
        self.footer.add_secondary(
            self.button(i18n.t("Not now"), on_click=self.reject))
        self.footer.set_primary(self.button(
            i18n.t("Open my email app"), "primary", icon_name="mail",
            on_click=self._send))

        self.tab_chain(self._name, self._email, self._body)

    def _draft(self) -> str:
        # Hyphens, not a box-drawing rule. Barlow has no U+2500, so the tidy
        # line rendered as a row of question marks inside the edit box — which
        # looks like the app has mangled their message before they have even
        # sent it.
        lines = [i18n.t("What's happening:"), "", "", "",
                 "-" * 52,
                 i18n.t("From the help screen — please leave this in, it "
                        "saves us asking:"), ""]
        lines.append(f"Prism {app_meta.VERSION}")
        try:
            import sys
            lines.append(f"Computer: {sys.platform}")
        except Exception:                   # noqa: BLE001
            pass
        try:
            import licensing
            state = licensing.state()
            lines.append(f"Licence: {state.status}")
            if getattr(state, "plan", ""):
                lines.append(f"Plan: {state.plan}")
            # The device code, because "free the seat on the laptop that died"
            # is unanswerable without it and is one of the commonest asks.
            lines.append(f"Device code: {licensing.device_fingerprint()}")
        except Exception:                   # noqa: BLE001
            pass
        if self._transcript:
            lines += ["", i18n.t("What I asked the help screen:"), "",
                      self._transcript]
        return "\n".join(lines)

    def _full_text(self) -> str:
        who = self._name.text().strip()
        mail = self._email.text().strip()
        header = []
        if who:
            header.append(f"{i18n.t('Name')}: {who}")
        if mail:
            header.append(f"{i18n.t('Email')}: {mail}")
        return ("\n".join(header) + "\n\n" if header else "") \
            + self._body.toPlainText()

    def _copy_all(self):
        QApplication.clipboard().setText(self._full_text())
        self._copy.setText(i18n.t("Copied"))
        QTimer.singleShot(1600,
                          lambda: self._copy.setText(i18n.t("Copy it all")))

    def _send(self):
        """Hand it to their mail app, with the whole thing on the clipboard.

        A `mailto:` body has a length limit that varies by platform and mail
        client, and a long transcript will silently overrun it — so the full
        text goes to the clipboard FIRST and they are told so. Nothing they
        wrote can be lost by pressing this, even where the mail app truncates.
        """
        from PySide6.QtWidgets import QMessageBox
        text = self._full_text()
        QApplication.clipboard().setText(text)
        subject = quote(f"{app_meta.NAME} {app_meta.VERSION} — "
                        f"{i18n.t('help please')}")
        QDesktopServices.openUrl(
            f"mailto:{app_meta.SUPPORT_EMAIL}?subject={subject}"
            f"&body={quote(text[:1400])}")
        QMessageBox.information(
            self, i18n.t("Contact the team"),
            i18n.t("Your email app should be opening now, with this already "
                   "written in it.\n\nThe whole message is also on your "
                   "clipboard — if the email looks short, paste over it "
                   "before sending.\n\nIf nothing opened, email us at "
                   "{address} and paste it in.").replace(
                       "{address}", app_meta.SUPPORT_EMAIL))
        self.sent = True
        self.accept()

    def _save(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        import os
        import paths
        suggested = os.path.join(
            paths.picker_start_dir(),
            f"prism-help-{time.strftime('%Y%m%d-%H%M')}.txt")
        target, _ = QFileDialog.getSaveFileName(
            self, i18n.t("Save this"), suggested, "Text (*.txt)")
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8") as f:
                f.write(self._full_text())
                f.write("\n\n" + "=" * 60 + "\n\n")
                try:
                    import diagnostics
                    f.write(diagnostics.report())
                except Exception as e:      # noqa: BLE001
                    f.write(f"(couldn't include the installation details: {e})")
        except OSError as e:
            QMessageBox.warning(self, i18n.t("Prism"), i18n.t(
                "Couldn't write the file: {error}").replace("{error}", str(e)))
            return
        QMessageBox.information(self, i18n.t("Prism"), i18n.t(
            "Saved to {path}\n\nEmail it to {address} and we'll be able to "
            "see exactly what happened.").replace("{path}", target).replace(
                "{address}", app_meta.SUPPORT_EMAIL))
        self.sent = True
