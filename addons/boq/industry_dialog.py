"""Add or edit your own industry for BOQ (see custom_industries.py for what it is).

Four plain questions: its name, what you measure in one line, the items and
units you usually count (optional), and notes the write-up must follow
(optional). It checks the form itself and says what to fix on the form, not in
a pop-up. It changes `cfg` only on Save; the caller writes the config.
"""
from __future__ import annotations

from PySide6.QtWidgets import QLabel, QLineEdit, QPlainTextEdit

import i18n
import theme
from dialogs.base import PrismDialog
from widgets import controls as C
from addons.boq import custom_industries as CI


class IndustryDialog(PrismDialog):
    def __init__(self, cfg: dict, entry: dict | None = None, parent=None):
        editing = entry is not None
        super().__init__(
            i18n.t("Edit your industry") if editing else i18n.t("Add your industry"),
            i18n.t("Tell Prism about your trade once. It measures your drawing the General "
                   "way and uses your words when it writes the BOQ."),
            icon="file", parent=parent, closable=False, scrollable=True)
        self.resize(560, 640)
        self.cfg = cfg
        self.entry = entry
        self._saved = None

        def field(label, hint, widget):
            self.body.addWidget(C.label(i18n.t(label), level="SUPPORT"))
            self.body.addWidget(widget)
            if hint:
                self.body.addWidget(C.label(i18n.t(hint), level="META", wrap=True))

        self.name_edit = QLineEdit(entry["name"] if editing else "")
        self.name_edit.setPlaceholderText(i18n.t("e.g. Fire fighting"))
        self.name_edit.setMaxLength(CI.MAX_NAME)
        field("Name of your industry", "", self.name_edit)
        self.what_edit = QLineEdit(entry["what"] if editing else "")
        self.what_edit.setPlaceholderText(i18n.t("e.g. Pipes, sprinklers, valves and pumps"))
        self.what_edit.setMaxLength(CI.MAX_WHAT)
        field("What do you measure? One line is enough.", "", self.what_edit)
        self.items_edit = QPlainTextEdit(CI.items_text(entry["items"]) if editing else "")
        self.items_edit.setPlaceholderText(i18n.t("One per line, with its unit if you like:\n"
                                                  "Sprinkler head, nos\nGI pipe 50 mm, m"))
        self.items_edit.setFixedHeight(110)
        field("Items you usually count (optional)",
              "Prism uses these names when it can. It will not invent a count for them.",
              self.items_edit)
        self.notes_edit = QPlainTextEdit(entry["notes"] if editing else "")
        self.notes_edit.setPlaceholderText(i18n.t("e.g. Group by floor. Show pipe length in metres."))
        self.notes_edit.setFixedHeight(90)
        field("Notes the write-up should follow (optional)",
              "Your notes are used as reference only. They cannot change Prism's own rules.",
              self.notes_edit)
        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet(f"color: {theme.ERR_INK};")
        self.error.setVisible(False)
        self.body.addWidget(self.error)
        self.body.addStretch(1)

        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.save_btn = self.button(i18n.t("Save my industry"), "primary", on_click=self._save)
        self.footer.set_primary(self.save_btn)

    def saved_entry(self) -> dict | None:
        return self._saved

    def _save(self):
        args = (self.name_edit.text(), self.what_edit.text(),
                self.items_edit.toPlainText(), self.notes_edit.toPlainText())
        try:
            self._saved = (CI.update(self.cfg, self.entry["id"], *args) if self.entry
                           else CI.add(self.cfg, *args))
        except CI.Invalid as e:
            self.error.setText(i18n.t(str(e)))
            self.error.setVisible(True)
            return
        self.accept()
