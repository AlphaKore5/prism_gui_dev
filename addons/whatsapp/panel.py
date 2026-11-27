"""The WhatsApp screen.

The whole workspace, in the window — not a launcher for a modal. The rail shows
this panel; the panel IS the surface: a page header over the tabbed workbench
(addons/whatsapp/workbench.py). The heavy widget is built the first time the
screen is shown, so it costs nothing at startup (MainWindow builds every screen
up front).

`opened` and `open_run` stay as signals because MainWindow wires them for every
add-on panel; this one only ever emits `navigate` (the "AI tools" shortcut).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

import i18n
from widgets import controls as C


class WhatsAppPanel(QWidget):
    TITLE = "WhatsApp"
    # One line, on purpose: PageHeader's subtitle does not wrap, so a long one
    # sets the window's minimum width and pushes a 1366px laptop sideways.
    BLURB = "Every conversation, contact and broadcast on your WhatsApp number."

    opened = Signal()               # kept for MainWindow's generic wiring
    navigate = Signal(str)          # "AI tools" → the agents screen
    open_run = Signal(str)          # kept for MainWindow's generic wiring

    def __init__(self, cfg: dict = None, parent=None):
        super().__init__(parent)
        self.cfg = cfg or {}
        self._workbench = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.broadcast_btn = C.button(i18n.t("New campaign"), "primary",
                                      on_click=self.new_broadcast)
        # The plan this workspace is on, one click from every tab (the owner, 27-Nov-2026: "add a upgrade option on
        # this part of the module.. so that he can directly see"): opens Compare plans.
        self.plan_btn = C.button(i18n.t("Plans"), "secondary", icon_name="sparkles", on_click=self.show_plans)
        self.plan_btn.setToolTip(i18n.t("See every plan and ask for a bigger one."))
        self.header = C.PageHeader(
            i18n.t(self.TITLE), i18n.t(self.BLURB), [
                self.plan_btn,
                C.button(i18n.t("AI tools"), "tertiary", icon_name="grid",
                         on_click=lambda: self.navigate.emit("agents")),
                self.broadcast_btn])
        root.addWidget(self.header)
        self._body = QWidget()
        self._body_lay = QVBoxLayout(self._body)
        self._body_lay.setContentsMargins(0, 0, 0, 0)
        self._body_lay.setSpacing(0)
        root.addWidget(self._body, stretch=1)

    # -- lifecycle --------------------------------------------------------------
    def showEvent(self, event):
        super().showEvent(event)
        # Re-read settings on every show. MainWindow swaps its cfg dict without
        # telling this panel, which it built once at startup; a stale copy,
        # saved back, would wipe whatever the other screens wrote meanwhile.
        try:
            import core_bridge as CB
            self.cfg = CB.config.load()
        except Exception:                                   # noqa: BLE001
            pass
        if self._workbench is None:
            self._build()                       # its first page activates itself
        else:
            self._workbench.refresh(self.cfg)
            self._workbench.activate()

    def hideEvent(self, event):
        super().hideEvent(event)
        if self._workbench is not None:
            self._workbench.deactivate()

    def _build(self):
        # Imported lazily so the workspace never loads on a startup where the
        # screen is not opened.
        from addons.whatsapp.workbench import WhatsAppWorkbench
        self._workbench = WhatsAppWorkbench(self.cfg, self)
        self._workbench.planChanged.connect(self._on_plan)
        self._body_lay.addWidget(self._workbench)

    def _on_plan(self, reply: dict) -> None:
        """"Free · Upgrade" while there is a bigger plan; the plan's name alone on the top one."""
        label = (reply or {}).get("label") or ""
        if not label:
            return
        self.plan_btn.setText(i18n.t("{p} · Upgrade").format(p=label) if (reply or {}).get("next_plan")
                              else i18n.t("{p} plan").format(p=label))

    def show_plans(self):
        if self._workbench is None:
            self._build()
        from addons.whatsapp.plan_compare import PlanCompareDialog
        self._plans_dlg = PlanCompareDialog(self._workbench.plan_reply(), parent=self.window())
        self._plans_dlg.open()

    def new_broadcast(self):
        if self._workbench is None:
            self._build()
        from addons.whatsapp.workbench import _CAMPAIGNS
        self._workbench.show_tab(_CAMPAIGNS)

    def refresh(self):
        if self._workbench is not None:
            self._workbench.activate()
