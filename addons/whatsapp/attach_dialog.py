"""Connect a number that is already live on Meta by typing its ids and an access token, instead of using Meta's pop-up.

For an account whose owner already has the ids and a token (a system user in Meta Business settings with the WhatsApp account assigned and the Prism app
chosen). The token is typed into a hidden box, goes to Prism's server over the app's usual secure call, and is kept there encrypted; it is never saved on this
computer and the box is emptied once it has been sent.
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLineEdit

import i18n
from addons.whatsapp import ui
from dialogs.base import PrismDialog
from widgets import controls as C


class AttachDialog(PrismDialog):
    def __init__(self, parent=None):
        super().__init__(i18n.t("Connect with an access token"),
                         i18n.t("For a number that is already working on WhatsApp's cloud. You need three things from Meta's Business settings."),
                         icon="plus", parent=parent)
        self.number_edit = QLineEdit()
        self.number_edit.setPlaceholderText("e.g. 1234567890123456")
        self.number_edit.setMinimumHeight(38)
        self.number_edit.setAccessibleName(i18n.t("Phone number ID"))
        self.body.addWidget(ui.field(i18n.t("Phone number ID"), self.number_edit, i18n.t("Not the phone number itself: the long id Meta shows beside it.")))
        self.waba_edit = QLineEdit()
        self.waba_edit.setPlaceholderText("e.g. 9876543210987654")
        self.waba_edit.setMinimumHeight(38)
        self.waba_edit.setAccessibleName(i18n.t("WhatsApp Business Account ID"))
        self.body.addWidget(ui.field(i18n.t("WhatsApp Business Account ID"), self.waba_edit))
        self.token_edit = QLineEdit()
        self.token_edit.setEchoMode(QLineEdit.Password)
        self.token_edit.setMinimumHeight(38)
        self.token_edit.setAccessibleName(i18n.t("Access token"))
        self.body.addWidget(ui.field(i18n.t("Access token"), self.token_edit,
                                     i18n.t("From a system user that has this WhatsApp account, with the Prism app and the whatsapp_business_management and "
                                            "whatsapp_business_messaging permissions.")))
        self.phone_app = QCheckBox(i18n.t("This number is also used in the WhatsApp Business app on the phone"))
        self.body.addWidget(self.phone_app)
        self.note = ui.note()
        self.body.addWidget(self.note)
        self.body.addStretch(1)
        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.footer.set_primary(self.button(i18n.t("Connect"), "primary", on_click=self._accept))
        self.resize(560, 620)                                           # the window's own minimum is about 528 x 562

    def _accept(self, _checked: bool = False):
        if not (self.value()["phone_number_id"] and self.value()["waba_id"] and self.value()["access_token"]):
            self.note.set(i18n.t("Fill in all three boxes first."), "error")
            return
        self.accept()

    def value(self) -> dict:
        return {"phone_number_id": "".join(self.number_edit.text().split()), "waba_id": "".join(self.waba_edit.text().split()),
                "access_token": "".join(self.token_edit.text().split()), "coexistence": self.phone_app.isChecked()}
