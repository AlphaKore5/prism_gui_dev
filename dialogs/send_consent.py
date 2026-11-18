"""The one-time "Send to Prism AI?" question. Opened by widgets.send_to_ai.ask_consent."""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox

import i18n
from dialogs.base import PrismDialog
from widgets.send_to_ai import _Preview


class SendConsentDialog(PrismDialog):
    """Asked once: this file leaves your computer for Prism AI."""

    def __init__(self, path: str, what: str, parent=None, note: str = ""):
        super().__init__(i18n.t("Send to Prism AI?"),
                         i18n.t("This {what} will be sent to Prism AI so it can read it. "
                                "{note}").format(
                             what=what,
                             note=note or i18n.t("Nothing else leaves your computer.")),
                         icon="send", parent=parent, closable=False)
        self.preview = _Preview(path)
        self.body.addWidget(self.preview)
        self.remember = QCheckBox(i18n.t("Don't ask again"))
        self.body.addWidget(self.remember)
        self.cancel_btn = self.button(i18n.t("Cancel"), "secondary", on_click=self.reject)
        self.send_btn = self.button(i18n.t("Send to Prism AI"), "primary",
                                    on_click=self.accept)
        self.footer.add_utility(self.cancel_btn)
        self.footer.set_primary(self.send_btn)
