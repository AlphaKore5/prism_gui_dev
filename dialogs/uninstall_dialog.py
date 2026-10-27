"""Remove Prism from this computer: choose what goes, read exactly what will be
deleted, then confirm. The deleting itself is uninstall.py; this window only
asks and shows.

Two choices, as the owner asked (2026-10-28):

  · Uninstall Prism                               the program only
  · Uninstall Prism and everything it stored      also its settings, licence, History,
                                                  logs and the folders Prism created

Nothing is removed until the person presses Remove, and the list on screen is
built from the same plan that will be run, so it cannot say one thing and do
another.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QLabel, QRadioButton,
                               QVBoxLayout)

import i18n
import theme
import uninstall
from dialogs.base import PrismDialog
from widgets import controls as C


class UninstallDialog(PrismDialog):
    def __init__(self, output_candidates: list[str] | None = None, parent=None,
                 *, protect: list[str] | None = None, plan_builder=None, starter=None, quitter=None):
        pad = C.IconPad("alert", theme.ERR, 38, theme.R_CONTROL, 19)
        super().__init__(i18n.t("Uninstall Prism"),
                         i18n.t("Choose what to remove from this computer."),
                         parent=parent, leading=pad, closable=True)
        self.setMinimumWidth(600)
        # Injected so the tests can run this window without deleting anything.
        self._build_plan = plan_builder or uninstall.build_plan
        self._start = starter or uninstall.start
        self._quit = quitter or (lambda: QApplication.instance().quit())
        self._outputs = list(output_candidates or [])
        self._protect = list(protect or [])
        self.plan = None

        body = self.body
        self.app_only = QRadioButton(i18n.t("Uninstall Prism"))
        self.app_only.setChecked(True)
        body.addWidget(self.app_only)
        body.addWidget(C.label(
            i18n.t("Removes the Prism program only. Your settings, licence, History, logs and every file "
                   "Prism made are kept, so installing Prism again picks up where you left off."),
            level="META", wrap=True))
        self.everything = QRadioButton(i18n.t("Uninstall Prism and everything it stored"))
        body.addWidget(self.everything)
        body.addWidget(C.label(
            i18n.t("Also removes Prism's settings, licence, History and logs, and the folders Prism created "
                   "(Prism Artifacts, Prism Step, Prism Gerber, Prism Email, Prism Inquiries, Prism Leads) "
                   "with the files in them. A folder you chose yourself with another name, and your team's "
                   "shared workspace, are never touched. This cannot be undone."), level="META", wrap=True))
        self.group = QButtonGroup(self)
        self.group.addButton(self.app_only)
        self.group.addButton(self.everything)

        box = QFrame()
        box.setObjectName("willRemove")
        box.setAttribute(Qt.WA_StyledBackground, True)
        box.setStyleSheet(f"QFrame#willRemove {{ background: {theme.WELL}; border: 1px solid "
                          f"{theme.HAIRLINE}; border-radius: {theme.R_CARD}px; }}")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(theme.CARD_PAD, theme.SPACE_3, theme.CARD_PAD, theme.SPACE_3)
        inner.addWidget(C.kicker(i18n.t("This will be removed")))
        self.list_label = QLabel()
        self.list_label.setWordWrap(True)
        self.list_label.setTextFormat(Qt.PlainText)
        self.list_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        inner.addWidget(self.list_label)
        body.addWidget(box)

        self.problem = C.label("", level="META", wrap=True, colour=theme.ERR_INK)
        body.addWidget(self.problem)
        body.addStretch(1)

        self.footer.add_secondary(self.button(i18n.t("Cancel"), on_click=self.reject))
        self.remove_btn = self.button(i18n.t("Remove"), "destructive", on_click=self._remove)
        self.footer.set_primary(self.remove_btn)

        self.app_only.toggled.connect(self._refresh)
        self._refresh()

    # ── what is chosen ──────────────────────────────────────────────────────
    def _scope(self) -> str:
        return uninstall.SCOPE_ALL if self.everything.isChecked() else uninstall.SCOPE_APP

    def _refresh(self):
        try:
            self.plan = self._build_plan(self._scope(), output_candidates=self._outputs,
                                         protect=self._protect)
        except uninstall.Refused as why:
            self.plan = None
            self.list_label.setText("")
            self.problem.setText(i18n.t(str(why)))
            self.remove_btn.setEnabled(False)
            return
        self.problem.setText("")
        lines = [f"{what}\n    {path}" for what, path in uninstall.describe(self.plan)]
        for path, why in self.plan.skipped:
            lines.append(i18n.t("Left alone: {path}\n    {why}").format(path=path, why=why))
        self.list_label.setText("\n".join(lines))
        self.remove_btn.setEnabled(True)

    # ── the one irreversible step ───────────────────────────────────────────
    def _remove(self):
        if self.plan is None:
            return
        try:
            self._start(self.plan)
        except uninstall.Refused as why:
            self.problem.setText(i18n.t(str(why)))
            return
        except OSError as error:
            self.problem.setText(i18n.t("Prism could not start the removal: {why}").format(why=error))
            return
        self.accept()
        self._quit()
