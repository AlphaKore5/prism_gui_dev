"""The preview's "Continue where you left off" on BOQ step 1 (boq-steps.html #bf-cont).

Up to five of this person's last BOQs, newest first, read from the same stored records as
History (`history.recent_boq_runs`). A row reopens that job on this screen. Hidden when there
are none. A quiet link says every BOQ is also in Artifacts.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout

import i18n
from addons.boq import history
from widgets import controls as C


def row_texts(record: dict) -> tuple[str, str]:
    """(title, "job kind · date · state") for one stored BOQ record."""
    title = (record.get("request") or record.get("query") or "").strip()
    for prefix in ("Bill of Quantities — ", "BOQ — "):
        if title.startswith(prefix):
            title = title[len(prefix):].strip()
    title = " ".join(title.split()) or i18n.t("Untitled BOQ")
    if len(title) > 70:
        title = title[:69].rstrip() + "…"
    industry = record.get("industry") or {}
    kind = industry.get("name") if isinstance(industry, dict) and industry.get("name") else "BOQ"
    if (record.get("error") or "").strip():
        state = i18n.t("did not finish")
    elif record.get("last_text"):
        state = i18n.t("finished")
    else:
        state = i18n.t("no result saved")
    return title, " · ".join(x for x in (kind, history.when_label(record.get("_path", "")), state) if x)


class ContinueList(QFrame):
    chosen = Signal(dict)
    artifacts = Signal()

    def __init__(self, parent=None, limit: int = 5):
        super().__init__(parent)
        self.limit = limit
        self.setObjectName("continueList")
        self._col = QVBoxLayout(self)
        self._col.setContentsMargins(0, 0, 0, 0)
        self._col.setSpacing(2)
        self.rows: list[QPushButton] = []
        self._records: list[dict] = []
        self.setVisible(False)

    def refresh(self) -> int:
        """Re-read the records; returns how many rows are showing (the widget hides at 0)."""
        while self._col.count():
            it = self._col.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.rows = []
        self._records = []
        try:
            runs = history.recent_boq_runs(self.limit)
        except Exception:                                    # noqa: BLE001
            runs = []
        if not runs:
            self.setVisible(False)
            return 0
        self._records = runs
        self._col.addWidget(C.label(i18n.t("Continue where you left off"), level="SUPPORT"))
        for rec in runs:
            title, meta = row_texts(rec)
            b = QPushButton(f"{title}   ·   {meta}")
            b.setObjectName("contRow")
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(i18n.t("Open this BOQ and carry on"))
            b.clicked.connect(lambda _=False, r=rec: self.chosen.emit(r))
            self._col.addWidget(b)
            self.rows.append(b)
        link = QPushButton(i18n.t("All your BOQs are in Artifacts"))
        link.setObjectName("linkBtn")
        link.setCursor(Qt.PointingHandCursor)
        link.clicked.connect(self.artifacts.emit)
        self.link = link
        row = QHBoxLayout()
        row.addWidget(link)
        row.addStretch(1)
        self._col.addLayout(row)
        return len(self.rows)
