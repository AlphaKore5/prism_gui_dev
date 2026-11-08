"""ELV/CCTV industry drawing reader -- the GUI face of addons/boq/
drawing_reader.py's shared reader (item 63, generalized at item 64,
BOQ-CHANGES-TODO.md).

Deliberately its own dialog, not IndustryTakeoffDialog with ELV bolted on:
HVAC's dialog is built around a geometry Step 1 (which line colour is
which) that ELV has none of -- there is no layer map, no drawing scale, no
duct-run review table to show. Forcing ELV through that shape would be
showing controls for a measurement this industry does not make. This
dialog is the shared-reader's thin front-end: pick a file (PDF, DWG or
DXF), read it, hand the result back -- same final interface
IndustryTakeoffDialog exposes (measurements_text()), so addons/boq/
dialog.py's own _open_industry_takeoff() can treat either one the same way
once a result exists.

No reading-mode choice any more (item 64): drawing_reader.py decides
DXF-entities-first vs AI-tiled from the file itself. A DXF/DWG with real
text or block entities reads with zero AI and needs no consent prompt at
all -- nothing leaves this machine. Only a PDF (or a DXF with no real text
entities, which drawing_reader.py reports rather than guessing at) ever
reaches the AI-tiled path, and that is the one case this dialog still asks
consent for.
"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QTextBrowser,
    QVBoxLayout,
)

import i18n
from widgets import controls as C
from addons.boq import industries
from addons.boq.workers import ElvReadWorker

_DRAWING_FILTER = "Drawings (*.pdf *.dwg *.dxf)"


class ElvReadDialog(QDialog):
    """Pick a drawing, read it, review the result, then hand it back
    exactly like IndustryTakeoffDialog does -- a plain-text summary,
    treated from there on like any other external measurement
    (BoqDialog._use_external_measurements)."""

    def __init__(self, industry: str, parent=None, cfg: dict | None = None):
        super().__init__(parent)
        self.industry = industry
        self.cfg = cfg if cfg is not None else {}
        self.pdf_path = ""
        self.result: dict | None = None

        self.setWindowTitle(i18n.t("{industry} drawing reading").format(industry=industry))
        self.resize(640, 560)
        col = QVBoxLayout(self)
        col.addWidget(C.label(i18n.t(
            "Reads a PDF, DWG or DXF drawing. A DWG/DXF with real text or "
            "named blocks is read directly -- no AI, nothing leaves this "
            "machine. Only a PDF (or a DXF with no readable text) needs "
            "an AI vision model, cropped-tile by cropped-tile, and will "
            "ask first."), level="SUPPORT", wrap=True))

        pick_row = QHBoxLayout()
        self.pick_btn = C.button(i18n.t("Pick a drawing…"), "secondary",
                                 icon_name="paperclip", small=True,
                                 on_click=self._pick_pdf)
        pick_row.addWidget(self.pick_btn)
        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        pick_row.addWidget(self.path_label, stretch=1)
        col.addLayout(pick_row)

        self.read_btn = C.button(i18n.t("Read"), "primary", icon_name="check",
                                 small=True, on_click=self._read)
        self.read_btn.setEnabled(False)
        col.addWidget(self.read_btn, alignment=Qt.AlignLeft)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        col.addWidget(self.status)

        self.output = QTextBrowser()
        self.output.setVisible(False)
        col.addWidget(self.output, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(C.button(i18n.t("Cancel"), "secondary", on_click=self.reject))
        self.use_btn = C.button(i18n.t("Use this reading"), "primary",
                                on_click=self.accept)
        self.use_btn.setEnabled(False)
        btn_row.addWidget(self.use_btn)
        col.addLayout(btn_row)

    def _pick_pdf(self):
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("Drawing"), os.path.expanduser("~"),
            i18n.t(_DRAWING_FILTER))
        if not path:
            return
        self.pdf_path = path
        self.path_label.setText(os.path.basename(path))
        self.read_btn.setEnabled(True)

    def _is_pdf(self) -> bool:
        return os.path.splitext(self.pdf_path)[1].lower() == ".pdf"

    def _consent(self) -> bool:
        """Only ever asked for a PDF (or a DXF that turns out to have no
        real text, though this dialog cannot know that before reading --
        a DXF/DWG always attempts the zero-AI entities path first and this
        prompt is skipped for it; drawing_reader.py itself never calls
        `tag_reader` unless that path found nothing). The wording is true
        unconditionally: a drawing is read tile by tile, never as a whole
        -- a small page already collapses to one tile on its own."""
        answer = QMessageBox.question(
            self, i18n.t("Use AI to help read this drawing?"),
            i18n.t("Your drawing is NOT sent to AI as a whole -- only "
                   "small cropped pieces, to read tags and labels. "
                   "Continue?"),
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _read(self):
        if not self.pdf_path:
            return
        api_key = (self.cfg.get("openrouter_api_key") or "").strip()
        if self._is_pdf():
            # A DWG/DXF may read entirely from real entities, no AI, no
            # key needed at all -- only a PDF is guaranteed to need both.
            if not api_key:
                QMessageBox.information(self, i18n.t(
                    "{industry} drawing reading").format(industry=self.industry),
                    i18n.t("Reading a PDF drawing needs an OpenRouter key — "
                           "add one in Settings → AI tools."))
                return
            if not self._consent():
                return
        self.read_btn.setEnabled(False)
        self.status.setText(i18n.t("Reading the drawing — this can take a minute…"))
        self._worker = ElvReadWorker(self.industry, self.pdf_path, api_key=api_key)
        self._worker.done.connect(self._on_read)
        self._worker.failed.connect(self._on_read_failed)
        self._worker.start()

    def _on_read(self, result: dict):
        self.result = result
        self.read_btn.setEnabled(True)
        self.status.setText(i18n.t("Read."))
        self.output.setPlainText(self.measurements_text())
        self.output.setVisible(True)
        self.use_btn.setEnabled(True)

    def _on_read_failed(self, message: str):
        self.read_btn.setEnabled(True)
        self.status.setText("")
        QMessageBox.warning(self, i18n.t("{industry} drawing reading").format(
            industry=self.industry), message)

    def measurements_text(self) -> str:
        if self.result is None:
            return ""
        return industries.summary_text(self.industry, self.result)
