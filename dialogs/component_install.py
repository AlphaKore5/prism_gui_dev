"""One plain question, then the download: "Prism needs X to do this (about N MB).
Install it now?" Opened from Settings > Components and from the first press of
a feature whose part is missing (offer_for_feature)."""
from __future__ import annotations

from PySide6.QtWidgets import QProgressBar

import deps
import i18n
from deps_worker import ComponentInstallWorker
from dialogs.base import PrismDialog
from widgets import controls as C


class ComponentInstallDialog(PrismDialog):
    """ask -> downloading -> done / failed. `ready` is True once the part is here."""

    def __init__(self, key: str, parent=None, why: str = ""):
        self.component = deps.BY_KEY[key]
        c = self.component
        size = (i18n.t("about {n} MB").format(n=c.size_mb) if c.size_mb
                else i18n.t("a small download"))
        lead = (i18n.t("Prism needs {name} to do this ({size}). Install it now?")
                .format(name=c.name, size=size))
        super().__init__(i18n.t("Get {name}").format(name=c.name), lead,
                         icon="download", parent=parent, closable=False)
        self.key = key
        self.ready = False
        self.worker = None
        self._body = C.label(
            (why + "\n\n" if why else "") + deps.consent_line(key),
            level="SUPPORT", wrap=True)
        self.body.addWidget(self._body)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.body.addWidget(self.bar)
        self.status = C.label("", level="SUPPORT", wrap=True)
        self.status.hide()
        self.body.addWidget(self.status)
        self.close_btn = self.button(i18n.t("Not now"), "secondary",
                                     on_click=self._not_now)
        self.go_btn = self.button(i18n.t("Install"), "primary",
                                  on_click=self.start)
        self.footer.add_utility(self.close_btn)
        self.footer.set_primary(self.go_btn)

    # the one place a download can begin, and only from the button
    def start(self):
        self.go_btn.setEnabled(False)
        self.go_btn.setToolTip(i18n.t("Downloading"))
        self.close_btn.setText(i18n.t("Cancel"))
        self.bar.setValue(0)
        self.bar.show()
        self.status.setText(i18n.t("Starting the download…"))
        self.status.show()
        self.worker = ComponentInstallWorker(self.key, True, self)
        self.worker.progress.connect(self._moved)
        self.worker.note.connect(self._noted)
        self.worker.done.connect(self._finished)
        self.worker.failed.connect(self._broke)
        self.worker.start()

    def _not_now(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.close_btn.setEnabled(False)
            self.status.setText(i18n.t("Stopping…"))
            return
        self.reject()

    def _moved(self, done: int, total: int):
        if total:
            self.bar.setRange(0, 100)
            self.bar.setValue(int(100 * done / total))
            self.status.setText(i18n.t("Downloading… {mb} MB of {total} MB")
                                .format(mb=f"{done / 1e6:.0f}",
                                        total=f"{total / 1e6:.0f}"))
        else:
            self.bar.setRange(0, 0)

    def _noted(self, line: str):
        if "download" in line.lower():
            self.status.setText(i18n.t("Downloading…"))

    def _finished(self, result: str):
        self.close_btn.setEnabled(True)
        self.close_btn.setText(i18n.t("Close"))
        if result == "cancelled":
            self.status.setText(i18n.t("Stopped. Nothing was installed."))
            self.go_btn.setEnabled(True)
            self.go_btn.setText(i18n.t("Try again"))
            self.go_btn.setToolTip("")
            self.bar.hide()
            return
        self.ready = True
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.status.setText(i18n.t("Done. You can use it now."))
        self.go_btn.setText(i18n.t("Done"))
        self.go_btn.setEnabled(True)
        self.go_btn.clicked.disconnect()
        self.go_btn.clicked.connect(self.accept)

    def _broke(self, message: str):
        self.close_btn.setEnabled(True)
        self.close_btn.setText(i18n.t("Close"))
        self.bar.hide()
        self.status.setText(message)
        self.go_btn.setEnabled(True)
        self.go_btn.setText(i18n.t("Try again"))
        self.go_btn.setToolTip("")


def offer_for_feature(parent, feature: str, why: str = "") -> bool:
    """Called when a feature is pressed. For each missing, fetchable part ask
    once; True when nothing the feature needs is still missing. A declined or
    unfetchable part returns False and the caller falls back as before."""
    for c in deps.missing_for(feature):
        if not c.install:
            return False
        dlg = ComponentInstallDialog(c.key, parent, why)
        dlg.exec()
        if not dlg.ready:
            return False
    return True
