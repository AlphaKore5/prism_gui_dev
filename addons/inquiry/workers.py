"""item 56 (4 Nov 2026) -- the inquiry add-on's own background threads.
Every add-on keeps its own (CONTRIBUTING.md rule 4: every background
thread subclasses workers._Worker) -- this one holds AIMatchWorker, the
only one this add-on has needed off the GUI thread so far.
"""
from __future__ import annotations

from PySide6.QtCore import Signal

from addons.inquiry import ai_match
from workers import _Worker


class AIMatchWorker(_Worker):
    """One DeepSeek completion, matching a free-text inquiry against the
    rate list -- addons/inquiry/quotation.py's own _start_ai_match(). On
    its own thread for the same reason every network call in this app is:
    a quotation screen that freezes for several seconds while a mail is
    matched reads as broken, not as busy."""

    done = Signal(list, list)      # (requests, unmatched)
    failed = Signal(str)

    def __init__(self, api_key: str, inquiry_text: str, items: list):
        super().__init__()
        self.api_key = api_key
        self.inquiry_text = inquiry_text
        self.items = items

    def run(self):
        try:
            requests, unmatched = ai_match.match(
                self.api_key, self.inquiry_text, self.items)
            self.done.emit(requests, unmatched)
        except Exception as e:                           # noqa: BLE001
            self.failed.emit(str(e))
