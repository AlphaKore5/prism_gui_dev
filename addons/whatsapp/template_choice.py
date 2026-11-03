"""Choose an approved template and say what goes in each of its blanks.

Used wherever a message that is not a reply is set up ahead of time — a birthday message, a reminder, each step of a drip. `value()` is
{"name", "language", "variables": {"1": {"source": ..., ...}}} — the same shape a flow's template step and a campaign use, so the server checks it with the same rules.
A blank can be the person's first name, any of their details, or fixed words; a tracked link needs a campaign and is not offered here.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

import i18n
import theme
from addons.whatsapp.campaigns_page import _sources, variable_spec
from addons.whatsapp.template_editor import variables_of
from widgets import controls as C


def body_text(template: dict) -> str:
    for comp in (template or {}).get("components") or []:
        if comp.get("type") == "BODY":
            return comp.get("text", "")
    return ""


class TemplateChoice(QWidget):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.templates: list = []
        self._spec: dict = {}
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(theme.SPACE_1)
        self.combo = QComboBox()
        self.combo.setMinimumHeight(36)
        self.combo.setAccessibleName(i18n.t("Template"))
        self.combo.activated.connect(self._chosen)
        col.addWidget(self.combo)
        self.preview = C.label("", level="META", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.preview)
        self.rows_col = QVBoxLayout()
        self.rows_col.setSpacing(theme.SPACE_1)
        col.addLayout(self.rows_col)
        self.note = C.label("", level="META", colour=theme.WARN_INK, wrap=True)
        self.note.setVisible(False)
        col.addWidget(self.note)
        self.set_templates([])

    # ── what can be chosen ───────────────────────────────────────────────────
    def set_templates(self, templates: list):
        self.templates = [t for t in templates or [] if str(t.get("status")).upper() == "APPROVED"]
        self._fill()

    def _fill(self):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem(i18n.t("Choose a template"), None)
        for t in self.templates:
            self.combo.addItem("%s · %s" % (t.get("name"), t.get("language")), t)
        i = next((k for k in range(1, self.combo.count()) if self.combo.itemData(k).get("name") == self._spec.get("name")
                  and self.combo.itemData(k).get("language") == (self._spec.get("language") or "en_US")), 0)
        if i == 0 and self._spec.get("name"):                            # chosen earlier but not approved (any more): keep showing it, flagged
            self.combo.addItem(i18n.t("{n} (not approved)").format(n=self._spec["name"]), {"name": self._spec["name"], "language": self._spec.get("language") or "en_US", "components": []})
            i = self.combo.count() - 1
        self.combo.setCurrentIndex(i)
        self.combo.blockSignals(False)
        self._rebuild()

    def set_value(self, spec: dict):
        self._spec = {"name": (spec or {}).get("name") or "", "language": (spec or {}).get("language") or "en_US", "variables": dict((spec or {}).get("variables") or {})}
        self._fill()

    def value(self) -> dict:
        return {"name": self._spec.get("name") or "", "language": self._spec.get("language") or "en_US", "variables": dict(self._spec.get("variables") or {})}

    def _chosen(self, _i=None):
        t = self.combo.currentData() or {}
        self._spec = {"name": t.get("name") or "", "language": t.get("language") or "en_US", "variables": {}}
        self._rebuild()
        self.changed.emit()

    # ── the blanks ───────────────────────────────────────────────────────────
    def _rebuild(self):
        while self.rows_col.count():
            item = self.rows_col.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().setParent(None)
                item.widget().deleteLater()
        t = self.combo.currentData() or {}
        text = body_text(t)
        self.preview.setText(text)
        self.preview.setVisible(bool(text))
        approved = any(x.get("name") == t.get("name") and x.get("language") == t.get("language") for x in self.templates)
        self.note.setVisible(bool(t) and not approved)
        self.note.setText(i18n.t("This template is not approved, so nothing can be sent until it is."))
        mapping = self._spec.setdefault("variables", {})
        for n in variables_of(text):
            row = QHBoxLayout()
            tag = C.label("{{%d}}" % n, level="SUPPORT", weight=700)
            tag.setMinimumWidth(48)
            row.addWidget(tag)
            src = QComboBox()
            src.setMinimumHeight(34)
            src.setAccessibleName(i18n.t("Blank {n}").format(n=n))
            for k, label, _needs, _ph in _sources():
                if k != "tracked_link":
                    src.addItem(label, k)
            edit = QLineEdit()
            edit.setMinimumHeight(34)
            edit.setPlaceholderText(i18n.t("The text"))
            spec = mapping.get(str(n)) or {}
            current = {"attribute": "attribute", "static": "static"}.get(spec.get("source"), spec.get("field") if spec.get("source") == "field" else "first_name")
            src.setCurrentIndex(max(src.findData(current), 0))
            edit.setText(str(spec.get("key") or spec.get("value") or ""))

            def sync(*_, n=n, src=src, edit=edit):
                needs = next((nd for k, _l, nd, _p in _sources() if k == src.currentData()), False)
                edit.setVisible(needs)
                mapping[str(n)] = variable_spec(src.currentData(), edit.text())
                self.changed.emit()
            src.activated.connect(sync)
            edit.textChanged.connect(sync)
            edit.setVisible(next((nd for k, _l, nd, _p in _sources() if k == src.currentData()), False))
            mapping.setdefault(str(n), variable_spec(src.currentData(), edit.text()))
            row.addWidget(src, 2)
            row.addWidget(edit, 2)
            box = QWidget()
            box.setLayout(row)
            self.rows_col.addWidget(box)
