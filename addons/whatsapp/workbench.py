"""The WhatsApp workspace — the whole surface, full-window, in the panel.

Same shape as Leads & Outreach: an underlined tab strip over a stacked page,
each page built the first time it is opened so an unopened tab costs nothing.

    Inbox · Contacts · Templates · Campaigns · Automations · Ads · Shop · Forms · Analytics · Settings

The strip's right edge carries the one thing worth glancing at without a click:
whether this is live, demo data, or unreachable.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

import i18n
import theme
from addons.whatsapp import demo
from widgets import controls as C

_INBOX, _CONTACTS, _TEMPLATES, _CAMPAIGNS, _AUTOMATIONS, _ADS, _SHOP, _FORMS, _ANALYTICS, _SETTINGS = range(10)
# The plan feature a whole tab is about. A tab the plan does not include shows a lock and says which plan has it
# (the owner, 27-Nov-2026: plans "like aisensy"); it still opens, and anything locked in it offers the upgrade.
_TAB_FEATURE = {_CAMPAIGNS: "broadcast", _SHOP: "commerce", _FORMS: "forms"}


def _tab_names() -> tuple:
    # Literal i18n.t calls, not a loop over a tuple of names: the string
    # extractor only sees literals, and a tab it cannot see is one that stays
    # in English for every translated install.
    return (i18n.t("Inbox"), i18n.t("Contacts"), i18n.t("Templates"), i18n.t("Campaigns"), i18n.t("Automations"),
            i18n.t("Ads"), i18n.t("Shop"), i18n.t("Forms"), i18n.t("Analytics"), i18n.t("Settings"))


class WhatsAppWorkbench(QWidget):
    unreadChanged = Signal(int)

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg if isinstance(cfg, dict) else {}
        self._pages: dict = {}
        self._unread = 0
        self._current = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._tabstrip())
        self._stack = QStackedWidget()
        self._stack.setStyleSheet("QStackedWidget { background: transparent; }")
        for _ in range(len(_tab_names())):
            self._stack.addWidget(QWidget())        # placeholders, replaced on first open
        # What a tab the plan does not include shows instead of its page (plan_compare.LockedTab).
        from addons.whatsapp.plan_compare import LockedTab
        self._locked_page = LockedTab()
        self._stack.addWidget(self._locked_page)
        self._locked_tabs: list = []
        self._plan_reply: dict = {}
        root.addWidget(self._stack, 1)
        self._signing_in = False
        from addons.whatsapp import sso_state
        sso_state.NOTIFY.required.connect(self._on_sign_in_required)  # the workspace asks everyone to sign in with the company account
        self._select(_INBOX)
        from addons.whatsapp import ui
        ui.call(self, "usage/plan", {}, done=self._apply_plan, failed=lambda _m, _d: None)

    def _apply_plan(self, reply: dict) -> None:
        """Lock the tabs this plan does not include: a lock icon, and a tooltip naming the plan that has it."""
        from addons.whatsapp.plan_compare import lowest_plan_label
        from widgets import icons
        have = set((reply or {}).get("features") or [])
        cat = (reply or {}).get("catalogue") or {}
        self._plan_reply = dict(reply or {})
        was_locked = self._current in self._locked_tabs
        self._locked_tabs = []
        for idx, feature in _TAB_FEATURE.items():
            b = self._tab_buttons[idx]
            if feature in have:
                b.setIcon(QIcon())
                b.setToolTip("")
                continue
            self._locked_tabs.append(idx)
            b.setIcon(icons.icon("lock", 13, theme.NEUTRAL[500]))
            where = lowest_plan_label(feature, cat)
            b.setToolTip(i18n.t("Part of {p} — your plan does not include it.").format(p=where) if where
                         else i18n.t("Not part of your plan."))
        if self._current >= 0 and (was_locked or self._current in self._locked_tabs):
            self._select(self._current)             # the tab on screen just became locked, or unlocked

    def _sign_in_dialog(self):
        from addons.whatsapp.settings_sso import SignInDialog
        return SignInDialog(self, required=True)

    def _on_sign_in_required(self):
        if self.isVisible():                                        # only the workspace on screen asks, never one that is hidden or gone
            self._ask_sign_in()

    def _ask_sign_in(self):
        if self._signing_in:
            return
        self._signing_in = True
        try:
            if self._sign_in_dialog().exec():
                page = self._pages.get(self._current)
                if page is not None:
                    page.activate()
        finally:
            self._signing_in = False

    # ── tab strip ────────────────────────────────────────────────────────────
    def _tabstrip(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("waTabs")
        bar.setAttribute(Qt.WA_StyledBackground, True)
        bar.setStyleSheet(
            f"QFrame#waTabs {{ background: {theme.CARD}; border: none;"
            f" border-bottom: 1px solid {theme.HAIRLINE}; }}")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(theme.SPACE_4, 0, theme.SPACE_4, 0)
        lay.setSpacing(theme.SPACE_5)
        self._tab_buttons: list[QPushButton] = []
        for i, name in enumerate(_tab_names()):
            b = QPushButton(name)
            b.setCursor(Qt.PointingHandCursor)
            b.setFlat(True)
            b.clicked.connect(lambda _=False, k=i: self._select(k))
            self._tab_buttons.append(b)
            lay.addWidget(b)
        lay.addStretch(1)
        self.conn = C.Pill("", "quiet")
        lay.addWidget(self.conn)
        self._set_connection("checking")
        return bar

    def _style_tab(self, b: QPushButton, active: bool):
        # border-radius 0 on purpose: the app-wide QPushButton radius would curl
        # the ends of the 2px underline up into a bracket (same fix Leads uses).
        if active:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid {theme.ACCENT};color:{theme.TEXT};"
                f"padding:12px 4px;margin-bottom:-1px;font-size:13px;font-weight:600;}}")
        else:
            b.setStyleSheet(
                f"QPushButton{{background:transparent;border:none;border-radius:0px;"
                f"border-bottom:2px solid transparent;color:{theme.NEUTRAL[600]};"
                f"padding:12px 4px;font-size:13px;font-weight:500;}}"
                f"QPushButton:hover{{color:{theme.TEXT};}}")

    def _set_connection(self, state: str):
        if demo.enabled():
            state = "demo"
        text, tone = {"checking": (i18n.t("Connecting…"), "quiet"),
                      "live": (i18n.t("Live"), "ok"),
                      "demo": (i18n.t("Demo data"), "warn"),
                      "offline": (i18n.t("Can't reach WhatsApp data"), "err")}[state]
        self.conn.setText(text)
        self.conn.set_tone(tone)

    # ── pages, built lazily ──────────────────────────────────────────────────
    def _page(self, index: int) -> QWidget:
        if index in self._pages:
            return self._pages[index]
        if index == _INBOX:
            from addons.whatsapp.inbox import InboxPage
            page = InboxPage(self.cfg)
            page.unreadChanged.connect(self._on_unread)
            page.statusChanged.connect(
                lambda msg, err: self._set_connection("offline" if err else "live"))
            page.orderRequested.connect(self._order_for)
            page.formRequested.connect(self._form_for)
        elif index == _CONTACTS:
            from addons.whatsapp.contacts import ContactsPage
            page = ContactsPage(self.cfg)
            page.broadcastRequested.connect(self._broadcast_to)
            page.manageRequested.connect(self._open_settings_section)
            page.orderRequested.connect(self._order_for)
            page.formRequested.connect(self._form_for)
        elif index == _TEMPLATES:
            from addons.whatsapp.templates_page import TemplatesPage
            page = TemplatesPage(self.cfg)
            page.useTemplate.connect(self._use_template)
        elif index == _CAMPAIGNS:
            from addons.whatsapp.campaigns_page import CampaignsPage
            page = CampaignsPage(self.cfg)
            page.openTemplates.connect(lambda: self._select(_TEMPLATES))
        elif index == _AUTOMATIONS:
            from addons.whatsapp.automations_page import AutomationsPage
            page = AutomationsPage(self.cfg)
        elif index == _ADS:
            from addons.whatsapp.ads_page import AdsPage
            page = AdsPage(self.cfg)
        elif index == _SHOP:
            from addons.whatsapp.shop_page import ShopPage
            page = ShopPage(self.cfg)
        elif index == _FORMS:
            from addons.whatsapp.forms_page import FormsPage
            page = FormsPage(self.cfg)
        elif index == _ANALYTICS:
            from addons.whatsapp.analytics_page import AnalyticsPage
            page = AnalyticsPage(self.cfg)
            page.openSettings.connect(self._open_settings_section)
        else:
            from addons.whatsapp.settings import SettingsPage
            page = SettingsPage(self.cfg)
        old = self._stack.widget(index)
        self._stack.removeWidget(old)
        old.deleteLater()
        self._stack.insertWidget(index, page)
        self._pages[index] = page
        return page

    def _select(self, index: int):
        prev = self._pages.get(self._current)
        if prev is not None and hasattr(prev, "deactivate"):
            prev.deactivate()                  # a page that refreshes itself stops when it is left
        self._current = index
        for k, b in enumerate(self._tab_buttons):
            self._style_tab(b, k == index)
        if index in self._locked_tabs:              # not on this plan: say so, and the way there, instead of the page
            self._locked_page.show_for(_tab_names()[index], _TAB_FEATURE[index], self._plan_reply)
            self._stack.setCurrentWidget(self._locked_page)
            return
        page = self._page(index)
        self._stack.setCurrentIndex(index)
        page.activate()

    def _use_template(self, name: str):
        """'Use in a campaign' on an approved template: open Campaigns with it chosen."""
        self._select(_CAMPAIGNS)
        page = self._pages.get(_CAMPAIGNS)
        if page is not None:
            page.choose_template(name)

    def _broadcast_to(self, target: dict):
        """'Broadcast' on a selection in Contacts: open Campaigns with exactly those people as the audience."""
        self._select(_CAMPAIGNS)
        page = self._pages.get(_CAMPAIGNS)
        if page is not None and hasattr(page, "use_audience"):
            page.use_audience(target)

    def _order_for(self, contact: dict):
        """'New order' on a person in the Inbox or Contacts: open the Shop's order form with them chosen."""
        self._select(_SHOP)
        page = self._pages.get(_SHOP)
        if page is not None:
            page.start_order_for(contact)

    def _form_for(self, contact: dict):
        """'Send a form…' on a person: open Forms and ask which published form to send them."""
        self._select(_FORMS)
        page = self._pages.get(_FORMS)
        if page is not None:
            page.send_to(contact)

    def _open_settings_section(self, key: str):
        self._select(_SETTINGS)
        page = self._pages.get(_SETTINGS)
        if page is not None:
            page.show_section(key)

    def show_tab(self, index: int):
        self._select(index)

    # ── unread badge ─────────────────────────────────────────────────────────
    def _on_unread(self, n: int):
        self._unread = n
        base = _tab_names()[_INBOX]
        self._tab_buttons[_INBOX].setText(f"{base}  ({n})" if n else base)
        self.unreadChanged.emit(n)

    # ── lifecycle, driven by the panel ───────────────────────────────────────
    def activate(self):
        page = self._pages.get(self._current)
        if page is not None:
            page.activate()

    def deactivate(self):
        page = self._pages.get(self._current)
        if page is not None and hasattr(page, "deactivate"):
            page.deactivate()

    def refresh(self, cfg: dict):
        """The panel re-read settings; hand them on."""
        self.cfg = cfg
        for page in self._pages.values():
            page.cfg = cfg
