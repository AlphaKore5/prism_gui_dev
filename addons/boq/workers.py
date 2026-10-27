"""BOQ's own background workers.

A PDF-takeoff extraction (addons/boq/industries.py's `extract`) reads and
OCRs a real tender PDF -- seconds on a small sheet, real time on a large,
multi-page one -- so it runs off the GUI thread the same way every other
blocking call in this app does (see workers.py's own docstring: "every
worker's job is ONLY to call into [its target] and turn the result into a
Qt signal; no decision-making lives here").
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from addons.boq import industries
from workers import _Worker


class HvacTakeoffWorker(_Worker):
    """Runs one industry's PDF-takeoff extraction (today, only HVAC has
    one) off the GUI thread. `industry` is threaded through rather than
    hardcoded so a second industry's own extractor plugs into this same
    worker later, not a copy of it."""

    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, industry: str, pdf_path: str, layer_map: dict,
                 pt_per_ft: float, use_ocr: bool = True):
        super().__init__()
        self.industry = industry
        self.pdf_path = pdf_path
        self.layer_map = layer_map
        self.pt_per_ft = pt_per_ft
        self.use_ocr = use_ocr

    def run(self):
        try:
            result = industries.extract(
                self.industry, self.pdf_path, self.layer_map, self.pt_per_ft,
                use_ocr=self.use_ocr)
            self.done.emit(result)
        except Exception as e:                           # noqa: BLE001
            self.failed.emit(str(e))
