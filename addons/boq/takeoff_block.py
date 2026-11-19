"""Step 1's block for a trade that has its own takeoff tool (HVAC, ELV).

Shows, in plain words and always for those trades:
  - the preview's "Is your HVAC drawing a PDF tender?" card with one button that
    opens Hitarth's tool (set the scale, map the line colours, extract);
  - when a DXF/DWG is already added: what Prism found in it BEFORE counting
    (drawing unit from the file header, the layers with entity counts, a small
    picture of the plan). Read-only: it never measures and never changes how
    measuring works. The existing "Drawing unit" field lives here for these trades.
"""
from __future__ import annotations

import i18n
import theme
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from widgets import controls as C

# Words in a layer name that mean "this carries air or water" (a hint from the name only).
_DUCT = ("duct", "supply", "return", "exhaust", "fresh", "sa-", "ra-", "ea-", "oa-", "dct")
_PIPE = ("pipe", "chw", "hw-", "cw-", "chilled", "hot water", "condens")

_UNIT_NAMES = {1: "inches", 2: "feet", 3: "miles", 4: "millimeters", 5: "centimeters",
               6: "meters", 8: "US survey feet"}


def layer_hint(name: str) -> str:
    low = name.lower()
    if any(w in low for w in _DUCT):
        return i18n.t("looks like ducts")
    if any(w in low for w in _PIPE):
        return i18n.t("looks like pipes")
    return ""


def unit_words(code: int) -> str:
    return _UNIT_NAMES.get(int(code or 0), "")


class TakeoffBlock(QFrame):
    open_tool = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("takeoffBlock")
        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)

        card = QFrame()
        card.setObjectName("evidenceBox")
        row = QHBoxLayout(card)
        row.setContentsMargins(12, 8, 12, 8)
        row.setSpacing(theme.SPACE_3)
        txt = QVBoxLayout()
        txt.setSpacing(2)
        self.title = QLabel("")
        self.title.setObjectName("rowTitle")
        self.sub = C.label("", level="SUPPORT", wrap=True)
        txt.addWidget(self.title)
        txt.addWidget(self.sub)
        row.addLayout(txt, 1)
        self.btn = C.button("", "secondary", small=True, on_click=self.open_tool.emit)
        row.addWidget(self.btn, 0, Qt.AlignVCenter)
        col.addWidget(card)

        self.cad_note = C.label("", level="SUPPORT", wrap=True)
        col.addWidget(self.cad_note)

        # What Prism found in the CAD file.
        self.peek = QWidget()
        pv = QHBoxLayout(self.peek)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(theme.SPACE_3)
        left = QVBoxLayout()
        left.setSpacing(4)
        self.unit_line = C.label("", level="BODY", wrap=True)
        left.addWidget(self.unit_line)
        self.unit_slot = QVBoxLayout()
        self.unit_slot.setContentsMargins(0, 0, 0, 0)
        left.addLayout(self.unit_slot)
        self.unit_warn = C.label("", level="SUPPORT", wrap=True, colour=theme.ERR_INK)
        left.addWidget(self.unit_warn)
        self.layers_head = C.label("", level="SUPPORT")
        left.addWidget(self.layers_head)
        self.layers_text = QLabel("")
        self.layers_text.setObjectName("meta")
        self.layers_text.setWordWrap(True)
        left.addWidget(self.layers_text)
        left.addStretch(1)
        pv.addLayout(left, 1)
        self.picture = QLabel("")
        self.picture.setFixedSize(220, 150)
        self.picture.setAlignment(Qt.AlignCenter)
        self.picture.setObjectName("meta")
        pv.addWidget(self.picture, 0, Qt.AlignTop)
        col.addWidget(self.peek)
        self.peek.setVisible(False)
        self.cad_note.setVisible(False)

    # -- content
    def set_trade(self, industry: str, has_cad: bool, ai_read: bool):
        if ai_read:                                    # ELV: its own PDF / picture reader
            self.title.setText(i18n.t("Is your {t} drawing a PDF or a picture?").format(t=industry))
            self.sub.setText(i18n.t("Prism can read the labels and symbols on it. It asks before "
                                    "anything is sent to AI."))
            self.btn.setText(i18n.t("Read the PDF or picture"))
            kind = i18n.t("Your file is a DXF/DWG: Prism reads its drawing units, layers and "
                          "symbols itself. Only a PDF or picture needs the reader.")
        else:
            self.title.setText(i18n.t("Is your {t} drawing a PDF tender?").format(t=industry))
            self.sub.setText(i18n.t("Prism can measure the ducts straight off the PDF. You set the "
                                    "scale, map the line colours, then extract."))
            self.btn.setText(i18n.t("Measure the PDF"))
            kind = i18n.t("Your file is a DXF/DWG: Prism reads its drawing units and layers "
                          "itself. Only a PDF tender needs the scale and colour steps.")
        self.cad_note.setText(kind)
        self.cad_note.setVisible(False)
        if has_cad:                                    # one sentence, in the card, not a second block
            self.sub.setText(kind)
        if not has_cad:
            self.peek.setVisible(False)

    def show_peek(self, info: dict):
        """`info` from CadPeekWorker. Nothing here is a measurement."""
        self.peek.setVisible(True)
        if info.get("error"):
            self.unit_line.setText(i18n.t("Prism will read this file when you press Next."))
            self.layers_head.setText("")
            self.layers_text.setText("")
            self.unit_warn.setText("")
            self.picture.setText("")
            return
        code = int(info.get("unit_code") or 0)
        if code:
            self.unit_line.setText(i18n.t("Drawing unit found in the file: {u}.").format(
                u=unit_words(code) or i18n.t("code {c}").format(c=code)))
            self.unit_warn.setText("")
        else:
            self.unit_line.setText(i18n.t("The file does not say what unit it is drawn in."))
            self.unit_warn.setText(i18n.t(
                "Unit not confirmed. Type it below (for example meters or millimeters) if you "
                "know it. If you leave it empty, every length is in the drawing's own units "
                "and you must check them before using them."))
        layers = (info.get("layers") or [])[:6]
        if layers:
            self.layers_head.setText(i18n.t("Layers in this file ({n}), with how many objects each:")
                                     .format(n=info.get("layer_total", len(layers))))
            lines = []
            for name, n in layers:
                h = layer_hint(name)
                lines.append(f"{name}: {n}" + (f"  ({h})" if h else ""))
            self.layers_text.setText("\n".join(lines))
        png = info.get("png") or ""
        pm = QPixmap(png) if png else QPixmap()
        if pm.isNull():
            self.picture.setText("")
        else:
            self.picture.setPixmap(pm.scaled(self.picture.size(), Qt.KeepAspectRatio,
                                             Qt.SmoothTransformation))
