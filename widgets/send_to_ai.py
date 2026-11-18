"""Sending a drawing / PDF / picture to Prism AI: one consent, one "sending" panel.

The first send asks ONCE (Send to Prism AI / Cancel, with "Don't ask again" kept in the
user's config); every later send skips the question but still shows the panel, so the
person always sees what is leaving and that Prism is working."""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QVBoxLayout, QWidget)

import core_bridge as CB
import i18n
import theme

CONSENT_KEY = "ai_send_consent"          # config: True = "Don't ask again"
_session = {"ok": False}                 # said yes once in this run of the app


def reset_session() -> None:
    _session["ok"] = False


def needs_question(cfg: dict) -> bool:
    return not (cfg.get(CONSENT_KEY) or _session["ok"])


def human_size(path: str) -> str:
    try:
        n = os.path.getsize(path)
    except OSError:
        return ""
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


class _Preview(QWidget):
    """Thumbnail + file name + size: what is being sent."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_3)
        self.thumb = QLabel()
        self.thumb.setFixedSize(72, 72)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet(f"background: {theme.NEUTRAL[100]}; border-radius: 8px;")
        pm = QPixmap(path) if path and not path.lower().endswith(".pdf") else QPixmap()
        if not pm.isNull():
            self.thumb.setPixmap(pm.scaled(68, 68, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.thumb.setText((os.path.splitext(path)[1][1:] or "file").upper()[:4])
        row.addWidget(self.thumb)
        col = QVBoxLayout()
        self.name = QLabel(os.path.basename(path))
        self.name.setStyleSheet("font-weight: 600;")
        self.size = QLabel(human_size(path))
        col.addWidget(self.name)
        col.addWidget(self.size)
        row.addLayout(col, 1)


def ask_consent(parent, cfg: dict, path: str, what: str = "drawing", note: str = "") -> bool:
    """True when this file may be sent. Asks once; 'Don't ask again' is saved to
    the user's config. Cancel sends nothing and is not remembered."""
    if not needs_question(cfg):
        return True
    from dialogs.send_consent import SendConsentDialog  # a window to open: imported where it opens
    dlg = SendConsentDialog(path, what, parent, note=note)
    if dlg.exec() != SendConsentDialog.Accepted:
        return False
    _session["ok"] = True
    if dlg.remember.isChecked():
        cfg[CONSENT_KEY] = True
        try:
            CB.config.save(cfg)
        except Exception:                                   # noqa: BLE001
            pass
    return True


class SendingPanel(QFrame):
    """A compact card laid over its parent while the call runs."""

    def __init__(self, parent: QWidget, path: str, message: str = ""):
        super().__init__(parent)
        self.setObjectName("sendingPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#sendingPanel {{ background: {theme.CARD}; border: 1px solid "
            f"{theme.HAIRLINE}; border-radius: 12px; }}")
        col = QVBoxLayout(self)
        col.setContentsMargins(18, 16, 18, 16)
        col.setSpacing(theme.SPACE_3)
        head = QLabel(i18n.t("Sending to Prism AI"))
        head.setStyleSheet("font-weight: 600;")
        col.addWidget(head)
        self.preview = _Preview(path)
        col.addWidget(self.preview)
        self.message = QLabel(message or i18n.t("Reading your drawing…"))
        col.addWidget(self.message)
        self.bar = QProgressBar()
        self.bar.setRange(0, 0)                 # the moving "working" bar
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        col.addWidget(self.bar)
        self.setFixedWidth(340)
        self.adjustSize()
        self.hide()

    def show_over(self) -> None:
        p = self.parentWidget()
        self.move(max(0, (p.width() - self.width()) // 2), max(0, p.height() // 4))
        self.show()
        self.raise_()

    def finish(self) -> None:
        self.hide()
        self.deleteLater()


def show_panel(parent: QWidget, path: str, message: str = "") -> "SendingPanel":
    """Open the 'Sending to Prism AI' card over `parent`; pass it to hide_panel() when done."""
    panel = SendingPanel(parent, path, message)
    panel.show_over()
    return panel


def hide_panel(panel) -> None:
    if panel is not None:
        try:
            panel.finish()
        except RuntimeError:                    # already gone with its parent
            pass
