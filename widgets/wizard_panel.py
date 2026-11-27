"""WizardPanel — the first-run walk: Groq key -> pick your specialists -> sign
into them -> straight into the task composer.

This replaces the old first-run path (a blocking "Welcome" popup, then the
same long settings page a returning user edits from). A returning user edits
those same values inline on the Settings screen (widgets/settings_panel.py)
— this is a separate, deliberately narrower surface for the one moment a
customer has never used Prism before. Three pages, forward-moving, one
focused thing per screen.

Structurally modelled on Workbench's own "1 Describe -> 2 Plan -> 3 Run"
breadcrumb (main_window.py's _workbench_header/_set_stage) — same #stepCur/
#stepOff styling, reused here rather than reinvented. Unlike Workbench this
is its own widget class, not built inline into MainWindow, because it owns no
live worker/routing state — it only reads cfg, walks three pages, and hands
the finished cfg back over a signal, which is the same shape every other
screen in main_window.py's stack (Home, Settings, ...) already takes.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout,
    QWidget,
)

import core_bridge as CB
import i18n
import theme
from widgets import controls as C
from widgets import icons
from widgets.agents_picker import AgentsPicker
from widgets.controls import Card, icon_label, kicker, label

KEY, AGENTS, LOGIN = 0, 1, 2
STEPS = ((KEY, "Groq key"), (AGENTS, "Specialists"), (LOGIN, "Sign in"))


class WizardPanel(QWidget):
    finished = Signal(dict)        # the finished cfg, once "Start using Prism" fires
    guide_requested = Signal()     # the quiet "How it works" link on page 1

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(self._header())

        self.stack = QStackedWidget()
        wrap = QVBoxLayout()
        wrap.setContentsMargins(theme.PAGE_PAD, theme.SPACE_5,
                                theme.PAGE_PAD, theme.SPACE_5)
        wrap.addWidget(self.stack, stretch=1)
        root.addLayout(wrap, stretch=1)

        self._page_key = self._build_key_page()
        self._page_agents = self._build_agents_page()
        self._page_login = self._build_login_page()
        for page in (self._page_key, self._page_agents, self._page_login):
            self.stack.addWidget(self._scrolling(page))

        root.addLayout(self._footer())
        self._go_to(KEY)

    @staticmethod
    def _scrolling(page: QWidget) -> QScrollArea:
        """Each page scrolls, so on a short laptop window it scrolls instead
        of clipping under the pinned Back/Next footer."""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    def start(self, cfg: dict):
        """Called once, by MainWindow._first_run(), each time this screen is
        about to be shown — resets to a fresh copy of cfg and page 1, rather
        than assuming the widget (built once, at app start) is still blank."""
        self.cfg = dict(cfg)
        self.key_edit.setText(self.cfg.get("api_key", ""))
        self.profile_edit.setText(self.cfg.get("profile", ""))
        self.key_error.setVisible(False)
        self._rebuild_agents_picker()
        self._go_to(KEY)

    # ── header: title + breadcrumb ──────────────────────────────────────────
    def _header(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setContentsMargins(theme.PAGE_PAD, theme.SPACE_6,
                               theme.PAGE_PAD, theme.SPACE_4)
        col.setSpacing(theme.SPACE_3)

        title = QLabel(i18n.t("Let's set up Prism"))
        title.setObjectName("h1")
        col.addWidget(title)

        self._crumb = {}
        row = QHBoxLayout()
        row.setSpacing(6)
        for i, (key, label_text) in enumerate(STEPS):
            if i:
                sep = QLabel()
                sep.setPixmap(icons.pixmap("chevron-right", 12,
                                           theme.NEUTRAL[300], stroke=2))
                row.addWidget(sep)
            step = QLabel(f"{i + 1} {i18n.t(label_text)}")
            step.setObjectName("stepOff")
            self._crumb[key] = step
            row.addWidget(step)
        row.addStretch(1)
        col.addLayout(row)
        return col

    def _light_step(self, index: int):
        for key, lbl in self._crumb.items():
            lbl.setObjectName("stepCur" if key == index else "stepOff")
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)

    # ── page 1: Groq key ─────────────────────────────────────────────────────
    def _build_key_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(theme.SPACE_4)

        head_row = QHBoxLayout()
        eyebrow = kicker(i18n.t("Step 1 of 3"))
        head_row.addWidget(eyebrow, stretch=1)
        how = C.button(i18n.t("How it works"), "tertiary",
                       on_click=lambda: self.guide_requested.emit())
        head_row.addWidget(how)
        col.addLayout(head_row)

        title = QLabel(i18n.t("Your AI") if CB.ai_client.active()
                       else i18n.t("Your Groq key"))
        title.setObjectName("h2")
        col.addWidget(title)
        if CB.ai_client.active():
            # AI runs through Prism's server: there is no key to ask for.
            import ai_server
            col.addWidget(label(
                i18n.t("There is no key to paste. Your tasks' research and "
                       "writing use your own AI accounts, which you pick and "
                       "sign in to next. Planning, pictures and video run on "
                       "your Prism plan.") if ai_server.browser_work() else
                i18n.t("Prism's AI runs through your Prism plan. There is no "
                       "key to paste and nothing to sign up for."),
                level="SUPPORT", wrap=True))
            self.key_edit = QLineEdit(CB.ai_client.AI_KEY)   # unseen; keeps the page's shape
            self.key_error = label("", wrap=True)
            self.key_error.setVisible(False)
            card = None
        else:
            card = self._groq_key_card(col)
        self._add_profile_card(col, card)
        return page

    def _groq_key_card(self, col):
        col.addWidget(label(
            i18n.t("Prism uses Groq (free) as its routing brain — it splits "
                   "your prompt into targeted tasks for each specialist AI."),
            level="SUPPORT", wrap=True))

        card = Card()
        body = card.body((theme.CARD_PAD, theme.CARD_PAD,
                          theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        body.addWidget(icon_label("lock", i18n.t("Groq API key")))
        self.key_edit = QLineEdit(self.cfg.get("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("gsk_…")
        self.key_edit.textChanged.connect(lambda: self.key_error.setVisible(False))
        C.add_password_visibility(self.key_edit)
        body.addWidget(self.key_edit)
        self.key_error = label(
            i18n.t("That doesn't look like a Groq key — it should start "
                   "with 'gsk_'."), colour=theme.ERR_INK, wrap=True)
        self.key_error.setVisible(False)
        body.addWidget(self.key_error)
        console = C.button(i18n.t("Open console.groq.com"), "secondary",
                           on_click=lambda: QDesktopServices.openUrl(
                               QUrl("https://console.groq.com")))
        body.addWidget(console)
        col.addWidget(card)
        return card

    def _add_profile_card(self, col, _key_card):
        profile_card = Card()
        pbody = profile_card.body((theme.CARD_PAD, theme.CARD_PAD,
                                   theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        pbody.addWidget(icon_label("user", i18n.t("What do you do? (optional)")))
        self.profile_edit = QLineEdit(self.cfg.get("profile", ""))
        self.profile_edit.setPlaceholderText(
            i18n.t("e.g. indie game dev, startup marketer…"))
        pbody.addWidget(self.profile_edit)
        pbody.addWidget(label(
            i18n.t("One line. Prism uses it to pitch every prompt at the "
                   "right audience."), level="META", wrap=True))
        col.addWidget(profile_card)

        col.addStretch(1)

    def _key_value(self) -> str:
        raw = self.key_edit.text().strip()
        return raw

    def _key_valid(self, key: str) -> bool:
        if CB.ai_client.is_server_key(key):
            return True
        return bool(key) and key.startswith("gsk_") and len(key) > 20

    # ── page 2: specialists ──────────────────────────────────────────────────
    def _build_agents_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(theme.SPACE_4)

        col.addWidget(kicker(i18n.t("Step 2 of 3")))
        title = QLabel(i18n.t("Pick your specialists"))
        title.setObjectName("h2")
        col.addWidget(title)
        col.addWidget(label(
            i18n.t("One tool per kind of step. Pick one per category, or "
                   "skip categories you won't use."), level="SUPPORT", wrap=True))

        card = Card()
        self._agents_card_body = card.body(
            (theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD),
            theme.SPACE_3)
        col.addWidget(card)
        col.addStretch(1)
        self._agents_picker = None   # built by _rebuild_agents_picker()
        return page

    def _rebuild_agents_picker(self):
        """Rebuilt on every start(), not just once — cfg's agent picks can
        differ between machines/launches, and this is the only page whose
        content depends on incoming data rather than being fixed chrome."""
        if self._agents_picker is not None:
            self._agents_card_body.removeWidget(self._agents_picker)
            self._agents_picker.deleteLater()
        self._agents_picker = AgentsPicker(
            self.cfg.get("agents"),
            file_reader=self.cfg.get("analysis_agent", ""))
        self._agents_picker.picked_changed.connect(self._refresh_next_enabled)
        self._agents_card_body.addWidget(self._agents_picker)
        self._refresh_next_enabled()

    def _refresh_next_enabled(self):
        if self.stack.currentIndex() == AGENTS:
            self.next_btn.setEnabled(bool(self._agents_picker.current_agents()))

    # ── page 3: sign in ──────────────────────────────────────────────────────
    def _build_login_page(self) -> QWidget:
        page = QWidget()
        col = QVBoxLayout(page)
        col.setSpacing(theme.SPACE_4)

        col.addWidget(kicker(i18n.t("Step 3 of 3")))
        import ai_server
        served = ai_server.active() and not ai_server.browser_work()
        title = QLabel(i18n.t("You're all set") if served
                       else i18n.t("Sign in to your tools"))
        title.setObjectName("h2")
        col.addWidget(title)
        col.addWidget(label(
            i18n.t("Prism's AI runs through your Prism plan, so there is "
                   "nothing to sign in to.") if served else
            i18n.t("Prism drives your REAL, logged-in Chrome — it stores no "
                   "passwords."), level="SUPPORT", wrap=True))
        if ai_server.browser_work():
            col.addWidget(label(
                i18n.t("No account yet? Click Open login tabs and sign up on "
                       "each site yourself, then sign in. Do it once."),
                level="META", wrap=True))

        self._sites_col = QVBoxLayout()
        self._sites_col.setSpacing(theme.SPACE_3)
        col.addLayout(self._sites_col)

        self.open_login_btn = C.button(
            i18n.t("Open login tabs"), "secondary", icon_name="lock",
            on_click=self._open_login_tabs)
        col.addWidget(self.open_login_btn)
        self.open_login_btn.setVisible(not served)
        col.addStretch(1)
        return page

    def _rebuild_login_page(self):
        """Rebuilt every time this page is entered — the tool list is
        whatever was picked on page 2, which can change if the customer went
        Back and repicked."""
        while self._sites_col.count():
            item = self._sites_col.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        import ai_server
        if ai_server.browser_work():
            sites = CB.resolved_agents(CB.default_work.sign_in_picks(
                self._agents_picker.current_agents(), self.cfg))
        elif ai_server.active():
            sites = []
        else:
            sites = CB.resolved_agents(self._agents_picker.current_agents())
        for name, url in sites:
            self._sites_col.addWidget(self._site_card(name, url))

    @staticmethod
    def _site_card(name: str, url: str) -> Card:
        card = Card()
        row = card.body((theme.CARD_PAD, theme.SPACE_3,
                         theme.CARD_PAD, theme.SPACE_3), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.ToolBadge(name, 28))
        head.addWidget(label(name, level="CARD_TITLE"), stretch=1)
        row.addLayout(head)
        if url:
            row.addWidget(label(url, level="MONO", colour=theme.NEUTRAL[600]))
        return card

    def _open_login_tabs(self):
        from PySide6.QtWidgets import QMessageBox
        from widgets.login_tabs import open_login_tabs
        # Saved first: the tabs to open follow the picks on page 2, the
        # file reader included.
        if self._agents_picker.current_file_reader():
            CB.config.save(self.cfg)
        open_login_tabs(self, self._agents_picker.current_agents(),
                        on_opened=lambda n: QMessageBox.information(
                            self, i18n.t("Login tabs"),
                            i18n.t("Opened {n} tab(s) in Chrome — sign in, then "
                                   "come back here.").format(n=n)))

    # ── footer: Back / Next / Start ──────────────────────────────────────────
    def _footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        # Lumi's edge button rests above this row (theme.LUMI_REST_FROM_BOTTOM),
        # so Next is never under it and no extra room is reserved.
        row.setContentsMargins(theme.PAGE_PAD, theme.SPACE_4,
                               theme.PAGE_PAD, theme.PAGE_PAD)
        row.setSpacing(theme.SPACE_3)
        self.back_btn = C.button(i18n.t("Back"), "secondary",
                                 on_click=self._go_back)
        row.addWidget(self.back_btn)
        row.addStretch(1)
        self.next_btn = C.button(i18n.t("Next"), "primary", on_click=self._go_next)
        row.addWidget(self.next_btn)
        return row

    def _go_to(self, index: int):
        self.stack.setCurrentIndex(index)
        self._light_step(index)
        self.back_btn.setVisible(index != KEY)
        if index == LOGIN:
            self._rebuild_login_page()
            self.next_btn.setText(i18n.t("Start using Prism"))
            self.next_btn.setEnabled(True)
        else:
            self.next_btn.setText(i18n.t("Next"))
            if index == AGENTS:
                self._refresh_next_enabled()
            else:
                self.next_btn.setEnabled(True)

    def _go_back(self):
        if self.stack.currentIndex() > KEY:
            self._go_to(self.stack.currentIndex() - 1)

    def _go_next(self):
        current = self.stack.currentIndex()
        if current == KEY:
            key = self._key_value()
            if not self._key_valid(key):
                self.key_error.setVisible(True)
                return
            self.cfg["api_key"] = key
            self.cfg["profile"] = self.profile_edit.text().strip()
            self._go_to(AGENTS)
        elif current == AGENTS:
            agents = self._agents_picker.current_agents()
            if not agents:
                return    # Next is disabled in this state; nothing to do
            self.cfg["agents"] = agents
            if self._agents_picker.current_file_reader():
                self.cfg["analysis_agent"] = (
                    self._agents_picker.current_file_reader())
            self._go_to(LOGIN)
        else:
            self._finish()

    def _finish(self):
        self.cfg["onboarded"] = True
        import ai_server
        if ai_server.browser_work():
            self.cfg["default_work_setup"] = True
        CB.config.save(self.cfg)
        self.finished.emit(self.cfg)
