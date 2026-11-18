"""'To read a DWG drawing Prism needs a free converter.' The in-app way to get one."""
from __future__ import annotations

import os
import platform

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QLabel,
                               QProgressBar)

import i18n
from addons.boq import converter_setup as CS
from dialogs.base import PrismDialog


def open_url(url: str) -> None:                 # a seam: tests never open a browser
    QDesktopServices.openUrl(QUrl(url))


def open_folder(path: str) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(path))


class ConverterDialog(PrismDialog):
    """outcome: "ready" (a converter is now found), "dxf" (use a DXF instead) or ""."""

    POLL_MS = 2000

    def __init__(self, cfg: dict, parent=None):
        super().__init__(
            i18n.t("A free helper is needed"),
            i18n.t("To read a DWG drawing Prism needs a free converter."),
            icon="file", parent=parent, closable=True)
        self.cfg = cfg
        self.outcome = ""
        self.converter = ""
        self._installer = ""
        self._proc = None
        self._worker = None
        self._waited_ms = 0

        text = QLabel(i18n.t(
            "A DWG is a drawing that only some programs can open. Prism uses a free one, "
            "ODA File Converter, to turn it into a DXF file that Prism can measure. It is made "
            "by the Open Design Alliance, not by AlphaKore, and it runs on your own computer."))
        text.setWordWrap(True)
        self.body.addWidget(text)

        self.can_install = CS.installer_url() is not None
        self.accept_terms = QCheckBox()
        if self.can_install:
            row = QHBoxLayout()
            row.addWidget(self.accept_terms, 0)
            terms = QLabel(i18n.t(
                'I accept the converter\'s own terms: <a href="{url}">Open Design Alliance '
                'Community User Agreement</a>.').format(url=CS.TERMS_URL))
            terms.setOpenExternalLinks(False)
            terms.linkActivated.connect(lambda u: open_url(u))
            terms.setWordWrap(True)
            row.addWidget(terms, 1)
            self.body.addLayout(row)
            self.accept_terms.toggled.connect(self._refresh)

        self.bar = QProgressBar()
        self.bar.setFixedHeight(8)
        self.bar.setTextVisible(False)
        self.bar.hide()
        self.body.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.body.addWidget(self.status)

        self.page_btn = self.button(i18n.t("Open the download page"), "secondary",
                                    on_click=self._open_page, small=True)
        self.installed_btn = self.button(i18n.t("I installed it"), "secondary",
                                         on_click=self._recheck, small=True)
        self.choose_btn = self.button(i18n.t("Choose the converter file…"), "secondary",
                                      on_click=self._choose, small=True)
        row2 = QHBoxLayout()
        for b in (self.page_btn, self.installed_btn, self.choose_btn):
            row2.addWidget(b)
        row2.addStretch(1)
        self.body.addLayout(row2)

        self.dxf_btn = self.button(i18n.t("Use a DXF file instead"), "secondary",
                                   on_click=self._use_dxf)
        self.footer.add_secondary(self.dxf_btn)
        self.install_btn = self.button(i18n.t("Install it from Prism"), "primary",
                                       on_click=self._install)
        if self.can_install:
            self.footer.set_primary(self.install_btn)
        else:
            self.install_btn.hide()
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._refresh()

    # ── state ─────────────────────────────────────────────────────────────
    def _refresh(self):
        busy = self._worker is not None and self._worker.isRunning()
        ok = self.accept_terms.isChecked()
        self.install_btn.setEnabled(ok and not busy)
        self.install_btn.setToolTip(
            "" if ok else i18n.t("Tick the box above to accept the converter's terms first."))

    def _say(self, msg: str):
        self.status.setText(msg)

    def _done(self, path: str):
        self._timer.stop()
        self.converter, self.outcome = path, "ready"
        self.accept()

    # ── buttons ───────────────────────────────────────────────────────────
    def _open_page(self):
        open_url(CS.PAGE_URL)
        self._say(i18n.t("Download and install it, then press \"I installed it\"."))

    def _recheck(self) -> bool:
        found = CS.detect(self.cfg)
        if found:
            self._done(found)
            return True
        self._say(i18n.t("Prism still cannot find it. If you put it somewhere unusual, use "
                         "\"Choose the converter file…\"."))
        return False

    def _choose(self):
        exe = "ODAFileConverter.exe" if platform.system() == "Windows" else "ODAFileConverter"
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Choose the converter file"), os.path.expanduser("~"), exe + ";;*")
        if not path:
            return
        if CS.remember(self.cfg, path):
            self._done(path)
        else:
            self._say(i18n.t("That is not a file Prism can use."))

    def _use_dxf(self):
        self.outcome = "dxf"
        self.reject()

    def _install(self):
        url = CS.installer_url()
        if not url or not self.accept_terms.isChecked():
            return
        self.bar.setRange(0, 0)
        self.bar.show()
        self._say(i18n.t("Downloading the converter from the Open Design Alliance…"))
        self._start_download(url)

    def _start_download(self, url: str):
        self._worker = CS.DownloadWorker(url)
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_downloaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._refresh)
        self._worker.start()
        self._refresh()

    def _on_progress(self, got: int, total: int):
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(got)
            self._say(i18n.t("Downloading… {got:.0f} of {total:.0f} MB").format(
                got=got / 1e6, total=total / 1e6))

    def _on_failed(self, message: str):
        self.bar.hide()
        self._say(i18n.t("The download did not work ({why}). Use \"Open the download page\" "
                         "instead.").format(why=message))

    def _on_downloaded(self, path: str):
        self.bar.hide()
        self._installer = path
        try:
            self._proc = CS.launch_installer(path)
        except OSError as e:
            self._say(i18n.t("Could not start the installer ({why}). It is saved at {p}.")
                      .format(why=e, p=path))
            return
        if self._proc is None:                          # Linux: needs an admin password
            open_folder(os.path.dirname(path))
            self._say(i18n.t("Downloaded. To install it, open a terminal and run:\n{cmd}\n"
                             "Then press \"I installed it\".").format(cmd=CS.linux_command(path)))
        else:
            self._say(i18n.t("The installer is open. Finish it, and Prism will carry on by itself."))
        self._waited_ms = 0
        self._timer.start()

    def _poll(self):
        """While the installer runs, look again now and then; carry on as soon as it is found."""
        self._waited_ms += self.POLL_MS
        found = CS.detect(self.cfg)
        if found:
            self._done(found)
        elif self._waited_ms > 15 * 60 * 1000:
            self._timer.stop()

    def done(self, result):
        self._timer.stop()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancelled = True
        super().done(result)


def ask_for_converter(parent, cfg: dict) -> str:
    """Open the window; returns "ready", "dxf" or ""."""
    dlg = ConverterDialog(cfg, parent)
    dlg.exec()
    return dlg.outcome
