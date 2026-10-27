"""Settings, as a grouped section list in a focused modal.

The design folds the rail's old WORKSPACE and CONFIGURE groups — nine separate
rows, each opening the same dialog scrolled to a different place — into a single
page. This is that page.

Editing happens right here, not in a second dialog. There used to be a
SetupDialog with its own left-hand index of the same eight-ish sections, under
different names and a different order, that every "Change…" button on this
page opened — so a customer browsed one nav to find the fact, then landed in a
second, disagreeing nav to change it, then had to Save/Cancel back out to see
whether it took. That dialog is gone; every field it owned (the Groq key, the
agent picks, both languages, the Chrome pin, the workspace root, the
designation key, the team roster) now lives inline in the matching section
below, each with its own small Save so one field's mistake can't block
another's. The one thing still genuinely a separate flow is entering a new
licence key — LicenseDialog validates and activates in a way this page has no
reason to duplicate, so the licence section still opens it, directly, with no
detour through a scrolled-to section first.

What this screen owns outright, because nothing else offers it:

* **The licence in full** — who it is for, which plan, what that plan includes
  and what it does not, and the two irreversible actions (change the key,
  release this computer's seat), quarantined in their own red group.
* **Privacy & data** — where a member's work is actually written, who else can
  read it, and every folder Prism keeps, with doors to open them.
* **Diagnostics** — what this machine can and cannot do, the licence lease
  state, and the tail of the log, plus the export a support call needs. All of
  it was reachable only from a button in the Setup dialog's footer.
* **Login tabs** and the **"Set your name"** flow — an action rather than a
  setting, but Settings is where you go when something is not connected, and a
  solo install has no other route to a display name at all.

Sections that are NOT here, and why: there is no notification system in the
product (nothing schedules, raises or stores one), so a Notifications page
would be a page of dead switches. Appearance has exactly one honest control —
card shadows — which is folded into Diagnostics beside the other
renderer-dependent facts rather than given a page of its own.
"""
from __future__ import annotations
import os
import platform
import sys
from datetime import datetime

from PySide6.QtCore import QSize, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

import app_meta
import core_bridge as CB
import i18n
import identity
import licensing
import paths
import theme
import updater
import workspace
from widgets import controls as C
from widgets.agents_picker import AgentsPicker
from widgets.controls import Card, Pill

# Lifted out of the rail (see widgets/sidebar.SECONDARY). These are screens,
# not settings, so they are listed here as doors rather than restated as
# controls — Settings is simply where the rail now keeps the things it used to
# spend a permanent row on each.
MORE_LINKS = [
    ("runs", "History", "Every past run, re-rendered from its record"),
    ("catalog", "AI tools", "Every tool Prism can drive, and whether you're "
     "signed in to it"),
    ("guide", "How to use Prism", "What Prism can do, and what to type"),
    ("support", "Lumi", "Prism help, answers and a route to our team"),
]

# The glyph each door wears, kept out of MORE_LINKS so that table stays the
# three-column shape tests/test_support.py reads.
MORE_ICONS = {"runs": "clock", "catalog": "grid", "guide": "book",
              "support": "help"}

# (key, label, group, blurb). The group is the kicker the section sits under
# in the list; the key is what show_section() and the rail's direct-jump
# shortcuts address. "status" keeps its name because main_window maps both
# "key" and "chrome" onto it before calling us.
#
# All four strings live in ONE table on purpose: devtools/extract_strings.py
# scans module-level tables by name, and `SECTIONS` is on its list — a second
# dict beside it called SECTION_BLURB would ship untranslatable.
SECTIONS = [
    ("licence", "Licence", "Your copy",
     "What this copy is licensed for, which add-ons come with it, and until "
     "when."),
    ("profile", "Profile", "Your copy",
     "Who this copy files its work under, and where that work is kept."),
    ("agents", "Agents", "Configure",
     "Your Groq key and one tool per kind of step — the router suggests, "
     "you decide — plus where each one signs in."),
    ("language", "Language", "Configure",
     "Prism's own words, and — separately — what the AI tools write back in."),
    ("status", "Connections", "Configure",
     "Everything else Prism has to be able to reach: your browser, your "
     "team folder."),
    ("appearance", "Appearance", "Configure",
     "Dark or light mode, background wallpaper, card glassmorphism and visual effects."),
    ("privacy", "Privacy & data", "Configure",
     "Where your work is written, who else can read it, and every folder "
     "Prism keeps."),
    ("more", "Help & contact", "Support",
     "Get help, contact Alphakore, or read the legal terms."),
]

_SECTION_SEARCH = {
    "licence": "license activate activation plan seat subscription expiry",
    "profile": "name company team workspace folder shared designation",
    "agents": "ai api key groq tools models login credentials",
    "language": "translation output language hindi gujarati",
    "status": "connection browser chrome drive sync login",
    "appearance": "theme dark light wallpaper display",
    "privacy": "data files storage privacy folders",
    "more": "help meeting contact email phone legal support",
}

# (config key, name, what it is for). The e-mail keys Prism brings its own way
# of using: the free verifier waterfall confirms an address Prism already
# guessed, and a finder is asked only when that fails (prospector/verify.py).
# The order is the order they are tried, free-first, so the card reads as the
# waterfall it configures. Apollo sits with the finders because that is what it
# is here — and the same key is what Leads searches Apollo's database with, so
# it is entered once, in the one place the other e-mail keys already live.
_VERIFIER_ROWS = [
    ("verifalia_api_key", "Verifalia",
     "A browser-app credential pair, username:password. ~25 checks a day."),
    ("reoon_api_key", "Reoon", "~600 checks a month on the free tier."),
    ("zerobounce_api_key", "ZeroBounce", "100 checks a month, free."),
    ("abstractapi_api_key", "AbstractAPI", "100 checks a month, free."),
    ("kickbox_api_key", "Kickbox", "50 checks a month, free."),
    ("tomba_key", "Tomba",
     "Finds the real address when a guess won't verify. The pair "
     "key:secret. ~25 a month, free."),
    ("apollo_api_key", "Apollo",
     "The same key Leads searches Apollo's database with — searching is "
     "free, revealing a person costs about one Apollo credit."),
    ("hunter_api_key", "Hunter",
     "Finding only, so all ~50 free credits a month go to recovering an "
     "address the free checks could not confirm."),
]

# How each licence status reads to a customer. Named STATUS_COPY because that
# is one of the table names extract_strings.py scans; a status word rendered
# through str.title() would be untranslatable and would also print the
# engine's spelling ("tampered") at somebody who has done nothing wrong.
STATUS_COPY = {
    licensing.NONE: ("Not activated", "neutral"),
    licensing.VALID: ("Active", "ok"),
    licensing.GRACE: ("Payment overdue", "warn"),
    licensing.STALE: ("Not checked recently", "warn"),
    licensing.EXPIRED: ("Expired", "err"),
    licensing.TAMPERED: ("Needs re-checking", "err"),
}


# Feature keys arrive from the licence server in lower case. str.title() turns
# "boq" into "Boq" and "bom" into "Bom" — and BOQ is the word this product is
# sold on. Getting a customer's own vocabulary wrong, on the screen that proves
# what they paid for, reads as carelessness however small it is.
_ACRONYMS = {"boq": "BOQ", "bom": "BOM", "gst": "GST", "ai": "AI",
             "crm": "CRM", "erp": "ERP", "pdf": "PDF", "dxf": "DXF"}


def _amp(text: str) -> str:
    """Escape a literal ampersand for a QAbstractButton label.

    Qt reads "&" in button text as a mnemonic marker, so "Privacy & data"
    renders as "Privacy _data" with the d underlined and Alt+D silently bound
    to it. Every label that reaches a button goes through here; labels that
    reach a QLabel must not, because there the escape would print.
    """
    return (text or "").replace("&", "&&")


def feature_name(key: str) -> str:
    """A licence feature key as a person would write it."""
    key = (key or "").strip()
    if not key:
        return ""
    if key.lower() in _ACRONYMS:
        return _ACRONYMS[key.lower()]
    return key.replace("_", " ").replace("-", " ").title()


class SettingsPanel(QDialog):
    login_tabs = Signal()
    navigate = Signal(str)           # a rail command key — see MORE_LINKS
    rename_requested = Signal()      # set the display name on a solo copy
    tour_requested = Signal()
    licence_changed = Signal()       # seat released, or a version check landed
    wallpaper_changed = Signal(str)  # emitted when custom background changes
    # "Check for updates" finished its round trip. Emitted FROM the licensing
    # worker thread (licensing.refresh's on_done); Qt queues it back to this
    # thread, which is the whole reason it is a Signal and not a callback.
    _update_checked = Signal()

    # The modal is deliberately compact: the category list is a navigation
    # aid, not a second page competing with the details beside it.
    NAV_W = 210

    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(i18n.t("Settings"))
        self.setObjectName("settingsDialog")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setWindowModality(Qt.ApplicationModal)
        self.setMinimumSize(720, 520)
        self.resize(920, 680)
        self.setStyleSheet(
            f"#settingsDialog {{ background: #ffffff;"
            f" border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_MODAL}px; }}")
        self.cfg = cfg
        self._section = "licence"
        self._claims_height = False
        self._update_check = ""          # "" | "checking" | "done"
        self._update_checked.connect(self._after_update_check)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = C.PageHeader(
            i18n.t("Settings"), i18n.t("Manage your Prism experience"))
        self._header.add_action(C.icon_button(
            "x", i18n.t("Close settings"), self.reject))
        root.addWidget(self._header)

        body = QHBoxLayout()
        body.setContentsMargins(theme.SPACE_4, theme.SPACE_3,
                                theme.SPACE_4, theme.SPACE_4)
        body.setSpacing(theme.SPACE_3)

        self._nav_host = C.Card(radius=16)
        self._nav_host.setFixedWidth(self.NAV_W)
        self._nav = self._nav_host.body((theme.SPACE_3, theme.SPACE_4,
                                         theme.SPACE_3, theme.SPACE_4),
                                        spacing=2)
        self._settings_search = C.SearchField(i18n.t("Search settings"))
        self._settings_search.setAccessibleName(i18n.t("Search settings"))
        self._settings_search.changed.connect(self._settings_search_changed)
        body.addWidget(self._nav_host)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll.verticalScrollBar().valueChanged.connect(lambda _: self._scroll.viewport().update())
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }")
        self._page = QWidget()
        self._page.setObjectName("settingsPage")
        self._page.setAttribute(Qt.WA_StyledBackground, True)
        
        outer = QHBoxLayout(self._page)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        
        self._container = QWidget()
        self._container.setMaximumWidth(740)
        
        self._col = QVBoxLayout(self._container)
        self._col.setContentsMargins(0, theme.SPACE_3, 0, 56)
        self._col.setSpacing(theme.CARD_GAP)
        
        outer.addWidget(self._container)
        outer.addStretch(1)
        
        self._scroll.setWidget(self._page)
        body.addWidget(self._scroll, stretch=1)

        root.addLayout(body, stretch=1)
        self.refresh()

    def show_section(self, key: str):
        """Jump straight to a section inside the open settings dialog."""
        if key == "diagnostics":
            key = "more"
        keys = {k for k, _l, _g, _b in SECTIONS}
        self._section = key if key in keys else "licence"
        self.refresh()

    def open_section(self, key: str):
        """Refresh, centre and present Settings over the current workspace."""
        self.show_section(key)
        host = self.parentWidget()
        # The settings panel is kept in the window's screen registry so older
        # command routing continues to recognise it.  A QStackedWidget turns
        # child widgets into ordinary in-place widgets though, so promote it
        # back to a dialog the first time someone opens Settings.
        if host is not None and not self.isWindow():
            host = host.window()
            self.setParent(host, Qt.Dialog | Qt.FramelessWindowHint)
            self.setWindowModality(Qt.ApplicationModal)
        if host is not None:
            centre = host.mapToGlobal(host.rect().center())
            self.move(centre.x() - self.width() // 2,
                      centre.y() - self.height() // 2)
        self.open()

    # ── build ─────────────────────────────────────────────────────────────
    def refresh(self):
        self._clear_nav()
        self._drop(self._col)
        self._build_nav()
        # The concise dialog subtitle remains stable while the content below
        # changes. The licence page itself states the current plan in full.

        page = {
            "licence": self._licence,
            "profile": self._profile,
            "agents": self._agents,
            "language": self._language,
            "status": self._connections,
            "appearance": self._appearance,
            "privacy": self._privacy,
            "more": self._more,
        }[self._section]
        label, blurb = next((l, b) for k, l, _g, b in SECTIONS
                            if k == self._section)
        self._col.addWidget(self._head(i18n.t(label), i18n.t(blurb)))
        # A page that hands its slack to an EmptyState sets this, and then the
        # trailing stretch below must NOT be added — two competing stretches
        # is what leaves an empty state floating a third of the way down.
        self._claims_height = False
        page(self._col)
        if not self._claims_height:
            self._col.addStretch(1)
        self._scroll.verticalScrollBar().setValue(0)

    def _who(self) -> str:
        """The line under the page title: whose copy this is, and on what
        plan. Every part of it is read, never assumed — an unactivated copy
        says so rather than showing a blank."""
        state = licensing.state()
        name = identity.display_name(self.cfg) or i18n.t("This computer")
        plan = (state.plan or "").strip()
        if not plan:
            return i18n.t("{name} · not activated on this computer").format(
                name=name)
        return i18n.t("{name} · {plan} plan").format(
            name=name, plan=self._plan_label(plan))

    @staticmethod
    def _plan_label(plan_key: str) -> str:
        try:
            import plans
            found = plans.PLANS.get((plan_key or "").strip().lower())
            if found:
                return found.label
        except Exception:                            # noqa: BLE001
            pass
        return (plan_key or "").strip().title()

    def _build_nav(self):
        query = self._settings_search.text().strip().casefold()
        group = ""
        matched = [item for item in SECTIONS
                   if not query or query in " ".join((
                       i18n.t(item[1]), i18n.t(item[2]), i18n.t(item[3]),
                       _SECTION_SEARCH.get(item[0], ""))).casefold()]
        for key, label, section_group, _blurb in matched:
            if section_group != group:
                group = section_group
                self._nav.addSpacing(theme.SPACE_3 if self._nav.count()
                                     else 0)
                self._nav.addWidget(C.kicker(i18n.t(group), muted=True))
                self._nav.addSpacing(theme.SPACE_1)
            btn = QPushButton(_amp(i18n.t(label)))
            btn.setObjectName("secBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(C.MIN_TARGET)
            btn.setProperty("cur", key == self._section)
            btn.clicked.connect(lambda _=False, k=key: self.show_section(k))
            self._nav.addWidget(btn)
        if query and not matched:
            self._nav.addWidget(C.label(
                i18n.t("No settings sections match."), level="META", wrap=True))
        self._nav.addStretch(1)
        self._nav.addWidget(C.hairline())
        self._nav.addSpacing(theme.SPACE_3)
        self._nav.addWidget(C.label(
            i18n.t("Prism {version}").format(version=app_meta.VERSION),
            level="META"))
        support = C.label(app_meta.SUPPORT_EMAIL, level="META",
                          colour=theme.ACCENT_RAMP[700])
        support.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._nav.addWidget(support)
        self._nav.addSpacing(theme.SPACE_2)
        meeting = C.button(
            i18n.t("Request a meeting"), "secondary", small=True,
            on_click=self._request_meeting)
        meeting.setToolTip(i18n.t(
            "Opens an email to arrange a time with Alphakore."))
        self._nav.addWidget(meeting)

    def _settings_search_changed(self, _query: str):
        self._clear_nav()
        self._build_nav()

    def _clear_nav(self):
        while self._nav.count():
            item = self._nav.takeAt(0)
            widget = item.widget()
            if widget is self._settings_search:
                continue
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())
        self._nav.addWidget(self._settings_search)

    def _request_meeting(self):
        from urllib.parse import quote

        subject = quote("Book a meeting with Alphakore")
        body = quote("Hello Alphakore team,\n\nI would like to book a meeting. "
                     "Please let me know what times are available.\n")
        QDesktopServices.openUrl(QUrl(
            f"mailto:{app_meta.SUPPORT_EMAIL}?subject={subject}&body={body}"))

    def _drop(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Hide BEFORE unparenting: setParent(None) on a visible widget
                # promotes it to a top-level OS window for the instant before
                # deleteLater() lands — on Windows that's a real titled window
                # plus DWM's open animation, seen as a ghost-window flash on
                # every Settings navigation. A hidden widget promotes silently.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout():
                self._drop(item.layout())

    # ── shared pieces ─────────────────────────────────────────────────────
    def _facts(self, pairs) -> Card:
        """A card of label / value rows split by hairlines. `value` is either
        a string or an already-built widget."""
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (name, value) in enumerate(pairs):
            if i:
                col.addWidget(C.hairline())
            line = QHBoxLayout()
            line.setContentsMargins(0, theme.SPACE_3 - 1, 0, theme.SPACE_3 - 1)
            line.setSpacing(theme.SPACE_5)
            # Minimum width plus elide, never a fixed width: Hindi and
            # Gujarati run longer than English and a fixed column clips them.
            key_label = C.label(name, level="SUPPORT",
                                colour=theme.NEUTRAL[600], wrap=True)
            key_label.setMinimumWidth(150)
            line.addWidget(key_label, stretch=0)
            if isinstance(value, QWidget):
                line.addStretch(1)
                line.addWidget(value, alignment=Qt.AlignRight)
            else:
                # A long value — the licence's feature list is ten words — has
                # to wrap inside the card instead of running off its right
                # edge, where it was being clipped mid-word.
                text = C.label(str(value), level="SUPPORT",
                               colour=theme.TEXT, weight=500, wrap=True)
                text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                line.addWidget(text, stretch=1)
            col.addLayout(line)
        return card

    @staticmethod
    def _head(title: str, subtitle: str = "") -> C.SectionHeader:
        """A SectionHeader whose subtitle WRAPS.

        controls.SectionHeader builds its subtitle as a plain QLabel, so a
        two-clause explanation becomes one unbreakable 950px line and pushes
        the whole page wider than the viewport — which, with the horizontal
        scrollbar off, silently clips every status pill off the right edge.
        The label is public, so this wraps it without touching the shared
        component.
        """
        header = C.SectionHeader(title, subtitle)
        header.subtitle.setWordWrap(True)
        return header

    def _note(self, text: str, tone: str = "", kicker: str = "") -> Card:
        """A card carrying one paragraph — the explanations that are the
        difference between a fact and an answer."""
        card = Card()
        if tone == "info":
            card.setStyleSheet(
                f"#card {{ background: {theme.INFO_BG};"
                f" border-radius: {theme.R_CARD}px;"
                f" border: 1px solid {theme.ACCENT_RAMP[200]}; }}")
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        if kicker:
            col.addWidget(C.kicker(kicker))
            col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(
            text, level="SUPPORT",
            colour=theme.INFO_INK if tone == "info" else theme.NEUTRAL[700],
            wrap=True))
        return card

    @staticmethod
    def _buttons(widgets) -> QWidget:
        wrap = QWidget()
        wrap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        for widget in widgets:
            if isinstance(widget, QPushButton):
                widget.setMinimumHeight(theme.BTN_HEIGHT_MD)
            row.addWidget(widget)
        row.addStretch(1)
        return wrap

    @staticmethod
    def _row(widgets) -> QWidget:
        """Two or three controls on one line — a field beside its "Choose…"
        or "Detect" button — as opposed to _buttons(), which is a row of
        buttons under something. The first widget stretches; the rest (a
        button, a second combo) size to their own content."""
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_2)
        for i, widget in enumerate(widgets):
            if isinstance(widget, QPushButton):
                widget.setMinimumHeight(theme.BTN_HEIGHT_MD)
            row.addWidget(widget, stretch=1 if i == 0 else 0)
        return wrap

    def _field_card(self, title: str, blurb: str, field: QWidget, on_save,
                    extra_buttons=None) -> Card:
        """One editable setting: a kicker, what it's for, the field itself,
        then Save — every inline editor on this page (the Groq key, the
        workspace folder, both languages, the Chrome pin) is built from this
        one shape, so a customer learns it once. `extra_buttons` sits to
        Save's left — "Choose…", "Detect" — never competing with it."""
        # `title`/`blurb` arrive already translated — every other helper on
        # this page (_head, _danger, _note) takes the same contract, so a
        # caller wraps once with i18n.t() rather than this method silently
        # wrapping an already-wrapped string a second time.
        card = Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        col.addWidget(C.kicker(title))
        if blurb:
            col.addWidget(C.label(blurb, level="META", wrap=True))
        col.addWidget(field)
        buttons = list(extra_buttons or [])
        buttons.append(C.button(i18n.t("Save"), "primary", on_click=on_save))
        col.addWidget(self._buttons(buttons))
        return card

    def _after_save(self, message: str):
        """The common tail of every inline Save: persist, say so somewhere
        the customer is actually looking (the status bar, not a modal that
        would interrupt the next field they're about to edit), then rebuild
        the page so every section reads back what was just written."""
        CB.config.save(self.cfg)
        # Settings is a modal over the window, so the window's status bar —
        # where this used to speak — is hidden behind it: a Save looked like
        # nothing happened. Say it here, inside the dialog.
        self.show_toast(message)
        window = self.window()
        if window is not self and hasattr(window, "statusBar"):
            window.statusBar().showMessage(message, 3000)
        self.refresh()

    # ── a confirmation you can actually see ────────────────────────────────
    def show_toast(self, text: str, tone: str = "ok", ms: int = 3500):
        """A pill at the foot of the dialog: green for done, amber for a
        warning, red for a failure. Lives on the dialog, so refresh() (which
        rebuilds the page) does not take it away."""
        if getattr(self, "_toast", None) is None:
            self._toast = QLabel(self)
            self._toast.setAlignment(Qt.AlignCenter)
            self._toast.setWordWrap(True)
            self._toast.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._toast_timer = QTimer(self)
            self._toast_timer.setSingleShot(True)
            self._toast_timer.timeout.connect(self._toast.hide)
        bg, ink, edge = {
            "ok": (theme.OK_BG, theme.OK_INK, theme.OK),
            "warn": (theme.WARN_BG, theme.WARN_INK, theme.WARN),
            "err": (theme.ERR_BG, theme.ERR_INK, theme.ERR),
        }.get(tone, (theme.OK_BG, theme.OK_INK, theme.OK))
        mark = {"ok": "✓", "warn": "!", "err": "✕"}.get(tone, "✓")
        self._toast.setStyleSheet(
            f"background: #ffffff; color: {ink}; border: 1.5px solid {edge};"
            " border-radius: 12px; padding: 10px 18px; font-size: 13.5px;"
            " font-weight: 600;")
        self._toast.setText(f"{mark}  {text}")
        self._place_toast()
        self._toast.show()
        self._toast.raise_()
        self._toast_timer.start(ms)

    def _place_toast(self):
        t = getattr(self, "_toast", None)
        if t is None:
            return
        width = min(max(self.width() - 80, 240), 560)
        t.setFixedWidth(width)
        t.adjustSize()
        t.move((self.width() - t.width()) // 2, self.height() - t.height() - 22)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._place_toast()

    def _danger(self, title: str, blurb: str, buttons) -> Card:
        """The quarantine. Everything irreversible lives in one red-bordered
        card at the foot of its page, never inline beside a Save."""
        card = Card()
        card.setStyleSheet(
            f"#card {{ background: {theme.ERR_BG};"
            f" border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.ERR_LINE}; }}")
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        col.addWidget(C.label(title, level="CARD_TITLE", colour=theme.ERR_INK))
        col.addWidget(C.label(blurb, level="SUPPORT",
                              colour=theme.ERR_INK, wrap=True))
        col.addSpacing(theme.SPACE_1)
        col.addWidget(self._buttons(buttons))
        return card

    # ── licence ───────────────────────────────────────────────────────────
    def _licence(self, col):
        state = licensing.state()
        plan = (state.plan or "").strip()
        tone, word = self._licence_tone(state)

        rows = [(i18n.t("Licensed to"), state.customer or "—"),
                (i18n.t("Plan"), self._plan_label(plan) if plan else "—"),
                (i18n.t("Seats"), str(state.seats) if state.seats else "—"),
                (word, self._renews(state)),
                (i18n.t("Status"), Pill(i18n.t(STATUS_COPY.get(
                    state.status, ("Not activated", "neutral"))[0]), tone))]
        col.addWidget(self._facts(rows))

        who = self._plan_who(plan)
        if who:
            col.addWidget(self._note(who, kicker=i18n.t("Who this plan is for")))

        col.addWidget(self._head(
            i18n.t("What's included"),
            i18n.t("The add-ons and features your current licence plan covers.")))
        features = self._features(state)
        if features:
            col.addWidget(self._features_card(features))
        else:
            col.addWidget(self._note(i18n.t("No add-ons or features are registered for this licence.")))



        col.addWidget(self._danger(
            i18n.t("Careful with these"),
            i18n.t("Both actions stop Prism working on this computer until a "
                   "licence key is entered again. Your settings, your history "
                   "and your files are untouched by either."),
            [C.button(i18n.t("Change licence key"), "secondary",
                      on_click=self._open_license_dialog),
             C.button(i18n.t("Release this computer's seat"), "destructive",
                      on_click=self._release_seat)]))

    def _open_license_dialog(self):
        """Straight to the key-entry dialog — no detour through a settings
        section first. LicenseDialog is its own validated, multi-step flow
        (paste a key, confirm, activate) that this page has no reason to
        re-implement; everything else here edits a config value in place."""
        from dialogs.license_dialog import LicenseDialog
        if LicenseDialog(self.window(), mode="change").exec() == QDialog.Accepted:
            self.licence_changed.emit()
            self.refresh()

    @staticmethod
    def _licence_tone(state) -> tuple[str, str]:
        """The pill tone, and the word above the date.

        Semantic tones only — `ok` / `warn` / `err` sit outside the accent
        ramp and never rotate, so a valid licence stays green in a green
        profile and an expired one stays red. That is the one thing this pill
        exists for.

        The date beside it is ALWAYS the licence end the customer was quoted,
        never the token's — somebody told "expires in 4 days" on day 3 of a
        10-day trial will phone you, and be right to.
        """
        tone = STATUS_COPY.get(state.status, ("", "neutral"))[1]
        if state.status in (licensing.VALID, licensing.STALE, licensing.NONE):
            word = (i18n.t("Trial ends") if state.kind == "trial"
                    else i18n.t("Renews"))
        else:
            word = i18n.t("Ended")
        return tone, word

    def _renews(self, state) -> str:
        when = self._when(state.license_ends)
        if state.usable and state.days_left >= 0:
            return i18n.t("{date} · {n} days left").format(
                date=when, n=state.days_left)
        return when

    @staticmethod
    def _plan_who(plan_key: str) -> str:
        try:
            import plans
            found = plans.PLANS.get((plan_key or "").strip().lower())
            return found.who if found else ""
        except Exception:                            # noqa: BLE001
            return ""

    @staticmethod
    def _features(state) -> list[tuple[str, str, str, bool]]:
        """Every add-on Prism sells that this licence covers."""
        try:
            import plans
            table = plans.FEATURES
        except Exception:                            # noqa: BLE001
            table = {}
        
        out = []
        # Only show what the user actually has to avoid cluttering settings
        # with locked upgrades they might not need.
        for key in sorted(state.features):
            entry = table.get(key)
            out.append((key,
                        entry.label if entry else feature_name(key),
                        entry.blurb if entry else "",
                        True))
        return out

    def _features_card(self, features: list[tuple[str, str, str, bool]]) -> Card:
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (key, name, blurb, have) in enumerate(features):
            if i:
                col.addWidget(C.hairline())
            row = QHBoxLayout()
            row.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
            row.setSpacing(theme.SPACE_3)

            if have:
                icon = C.IconPad("check", theme.OK, 28, theme.R_CONTROL, 14)
                pill = Pill(i18n.t("Included"), "ok")
            else:
                icon = C.IconPad("lock", theme.NEUTRAL[400], 28, theme.R_CONTROL, 14)
                pill = Pill(i18n.t("Not in plan"), "quiet")

            row.addWidget(icon, alignment=Qt.AlignTop)

            text_box = QVBoxLayout()
            text_box.setSpacing(2)
            title_lbl = C.label(i18n.t(name), level="CARD_TITLE", wrap=True)
            text_box.addWidget(title_lbl)
            if blurb:
                desc_lbl = C.label(i18n.t(blurb), level="META", wrap=True)
                text_box.addWidget(desc_lbl)
            row.addLayout(text_box, stretch=1)

            row.addWidget(pill, alignment=Qt.AlignTop)
            col.addLayout(row)
        return card

    def _feature_card(self, key: str, name: str, blurb: str,
                      have: bool) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad("check", theme.OK, 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(i18n.t(name), level="CARD_TITLE", wrap=True),
                       stretch=1)
        head.addWidget(Pill(i18n.t("Included"), "ok"), alignment=Qt.AlignTop)
        col.addLayout(head)
        if blurb:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.label(i18n.t(blurb), level="META", wrap=True))
        return card

    def _release_seat(self):
        """Free this machine's seat, behind a confirmation — a seat released
        by accident costs a support call and a re-activation."""
        if QMessageBox.question(
                self, i18n.t("Release this computer's seat"),
                i18n.t("This frees the seat so the licence can be used on "
                       "another computer.\n\nPrism on THIS computer will stop "
                       "until you enter the key again. Your settings, your "
                       "history and your files stay exactly where they are."),
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        try:
            licensing.deactivate()
        except Exception as error:                   # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Licence"), i18n.t(
                "Couldn't release the seat: {error}").format(error=error))
            return
        self.licence_changed.emit()
        self.refresh()
        QMessageBox.information(
            self, i18n.t("Licence"),
            i18n.t("This computer's seat has been released."))

    # ── profile ───────────────────────────────────────────────────────────
    def _profile(self, col):
        me = identity.current()
        import roles as R
        role = R.get(me.get("role") or "") if me.get("role") else None
        shown = identity.display_name(self.cfg)

        col.addWidget(self._facts([
            (i18n.t("Name"), shown or i18n.t("Not set — this computer")),
            (i18n.t("Role"), role.label if role else i18n.t("Personal copy")),
            (i18n.t("Member folder"), self._mono(me.get("mid") or "—")),
        ]))
        if not (me.get("name") or "").strip():
            # A team member's name comes from their signed designation key
            # and is not theirs to type; a solo copy has no key, so without
            # this there is no way to be called anything but "This computer".
            col.addWidget(self._buttons([C.button(
                i18n.t("Set your name"), "primary",
                on_click=self.rename_requested.emit)]))

        if role and role.blurb:
            col.addWidget(self._note(i18n.t(role.blurb)))



        # ── what you do — edited right where it's shown ────────────────────
        profile_edit = QLineEdit(self.cfg.get("profile", ""))
        profile_edit.setPlaceholderText(
            i18n.t("e.g. indie game dev, startup marketer…"))
        col.addWidget(self._field_card(
            i18n.t("What you do"),
            i18n.t("One line. Prism uses it to pitch every prompt at the "
                   "right audience."),
            profile_edit,
            lambda: self._save_profile_line(profile_edit)))

        # ── the designation key ──────────────────────────────────────────
        key_edit = QLineEdit()
        key_edit.setPlaceholderText(
            i18n.t("PRSD1.… — paste your designation key"))
        key_row = self._row([key_edit])
        key_buttons = [C.button(i18n.t("Apply"), "primary",
                                on_click=lambda: self._apply_designation(
                                    key_edit))]
        if role:
            key_buttons.append(C.button(
                i18n.t("Remove"), "destructive",
                on_click=self._clear_designation))
        card = Card()
        kcol = card.body((theme.CARD_PAD, theme.CARD_PAD,
                          theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        kcol.addWidget(C.kicker(i18n.t("Company designation key")))
        kcol.addWidget(C.label(
            i18n.t("If your company gave you a designation key, paste it "
                   "here to switch this copy to your job's setup. It only "
                   "works alongside your company licence key.")
            if not role else
            i18n.t("Paste a new key to switch roles, or remove this one to "
                   "turn this back into a personal copy."),
            level="META", wrap=True))
        kcol.addWidget(key_row)
        kcol.addWidget(self._buttons(key_buttons))
        col.addWidget(card)

        # ── team workspace — where the shared folder lives ─────────────────
        workspace_edit = QLineEdit(self.cfg.get("workspace_root", ""))
        workspace_edit.setPlaceholderText(workspace.default_root())
        browse = C.button(i18n.t("Choose…"), "secondary",
                          on_click=lambda: self._pick_workspace(workspace_edit))
        col.addWidget(self._field_card(
            i18n.t("Team workspace"),
            i18n.t("Point this at a folder every member's computer can "
                   "reach — a Google Drive, OneDrive or Dropbox folder, or a "
                   "network share — and the manager can see the whole "
                   "team's work. Leave it blank to keep everything on this "
                   "computer only."),
            self._row([workspace_edit]),
            lambda: self._save_workspace(workspace_edit),
            extra_buttons=[browse]))

        members = self._safe(lambda: workspace.load_team(self.cfg)) or []
        if members:
            col.addWidget(self._head(
                i18n.t("Team members"),
                i18n.t("Everyone this copy has a designation key for.")))
            col.addWidget(self._members_card(members))

        if me.get("admin"):
            member_name = QLineEdit()
            member_name.setPlaceholderText(i18n.t("Name, e.g. Ravi Patel"))
            member_role = QComboBox()
            for entry in R.ordered():
                member_role.addItem(entry.label, entry.key)
            col.addWidget(self._field_card(
                i18n.t("Add a team member"),
                i18n.t("Tell us the names and jobs and we issue one "
                       "designation key each — add them here so their work "
                       "is labelled with a name instead of a folder id."),
                self._row([member_name, member_role]),
                lambda: self._add_member(member_name, member_role)))



    def _dev_import_card(self, col):
        import dev_import
        boxes = {}
        card = Card()
        body = card.body((theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        body.addWidget(C.kicker(i18n.t("Bring my settings from my normal Prism")))
        body.addWidget(C.label(
            i18n.t("This is a development build, so it has its own empty settings: no Groq key (the "
                   "microphone and every AI step need one), no browser logins, no History. Copy what you "
                   "want from your normal Prism. Your normal Prism is only read, never changed."),
            level="META", wrap=True))
        for key, (label, _files, _folders) in dev_import.CHOICES.items():
            box = QCheckBox(i18n.t(label))
            box.setChecked(key == "settings")
            boxes[key] = box
            body.addWidget(box)
        body.addWidget(self._buttons([C.button(i18n.t("Copy now"), "primary",
                                               on_click=lambda: self._run_dev_import(boxes))]))
        col.addWidget(card)

    def _run_dev_import(self, boxes):
        import dev_import
        import output_folders
        chosen = [key for key, box in boxes.items() if box.isChecked()]
        if not chosen:
            QMessageBox.information(self, i18n.t("Nothing chosen"), i18n.t("Tick what you want to copy."))
            return
        try:
            result = dev_import.copy(chosen)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, i18n.t("Could not copy"), str(error))
            return
        fresh = CB.config.load()
        self.cfg.clear()
        self.cfg.update(fresh)
        output_folders.apply(self.cfg)
        done = ", ".join(result["copied"]) or i18n.t("nothing")
        note = i18n.t("Copied: {done}. Restart Prism so everything picks it up.").format(done=done)
        if result["missing"]:
            note += " " + i18n.t("Not found in your normal Prism: {names}.").format(names=", ".join(result["missing"]))
        self._after_save(note)

    def _open_uninstall(self):
        """Open the uninstall window. Refused while a task is running: the window
        quits the app, and a half-made file is not worth losing."""
        import main_window as _mw
        window = self.window()
        if window is not self and _mw._is_running(getattr(window, "_active_run", None)):
            QMessageBox.information(
                self, i18n.t("Uninstall Prism"),
                i18n.t("A task is still running. Let it finish, or stop it, then uninstall."))
            return
        import output_folders
        engine = getattr(CB.config, "ARTIFACTS_DIR", "")
        candidates = [output_folders.chosen(self.cfg, "artifacts", engine),
                      output_folders.chosen(self.cfg, "step"),
                      output_folders.chosen(self.cfg, "gerber"),
                      paths.user_folder("Prism Email"), paths.user_folder("Prism Inquiries"),
                      paths.user_folder("Documents", "Prism Leads")]
        from dialogs.uninstall_dialog import UninstallDialog
        UninstallDialog(candidates, self).exec()

    # ── where Prism saves what it makes ───────────────────────────────────
    _OUTPUT_ROWS = (
        ("artifacts", "Generated files",
         "Reel videos, images, documents and everything else Prism makes for a task."),
        ("step", "STEP files",
         "Measurements, drawings and sheets made from your STEP models."),
        ("gerber", "Gerber reports",
         "Cleaned layers, comparison pages and reports made from Gerber jobs."),
    )

    def _output_folder_cards(self, col):
        import output_folders
        engine_default = {"artifacts": getattr(CB.config, "ARTIFACTS_DIR", ""), "step": "", "gerber": ""}
        for kind, title, blurb in self._OUTPUT_ROWS:
            field = QLineEdit(output_folders.configured(self.cfg, kind))
            field.setPlaceholderText(output_folders.chosen({}, kind, engine_default.get(kind, "")))
            field.setObjectName(f"outputFolder_{kind}")
            browse = C.button(i18n.t("Choose…"), "secondary",
                              on_click=lambda _=False, k=kind, f=field: self._pick_output_folder(k, f))
            col.addWidget(self._field_card(
                i18n.t(title), i18n.t(blurb), self._row([field]),
                lambda k=kind, f=field: self._save_output_folder(k, f),
                extra_buttons=[browse]))

    def _pick_output_folder(self, kind: str, field: QLineEdit):
        import output_folders
        start = field.text().strip() or field.placeholderText() or paths.picker_start_dir()
        chosen = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose a folder"), start if os.path.isdir(start) else paths.picker_start_dir())
        if chosen:
            field.setText(chosen)

    def _save_output_folder(self, kind: str, field: QLineEdit):
        import output_folders
        text = field.text().strip()
        ok, why = output_folders.check_folder(text)
        if not ok:
            QMessageBox.warning(self, i18n.t("That folder will not work"), i18n.t(why))
            return
        self.cfg[output_folders.KEY[kind]] = text
        output_folders.apply(self.cfg)
        self._after_save(i18n.t("Saved."))

    def _save_profile_line(self, field: QLineEdit):
        self.cfg["profile"] = field.text().strip()
        self._after_save(i18n.t("Saved."))

    def _pick_workspace(self, field: QLineEdit):
        chosen = QFileDialog.getExistingDirectory(
            self, i18n.t("Choose the team workspace folder"),
            field.text().strip() or workspace.default_root())
        if chosen:
            field.setText(chosen)

    def _save_workspace(self, field: QLineEdit):
        self.cfg["workspace_root"] = field.text().strip()
        self._after_save(i18n.t("Saved."))

    def _apply_designation(self, field: QLineEdit):
        import roles as R
        key = field.text().strip()
        if not key:
            QMessageBox.information(
                self, i18n.t("Designation key"),
                i18n.t("Paste the designation key we sent you for this "
                       "person."))
            return
        try:
            me = identity.activate(key)
        except licensing.TokenError as error:
            QMessageBox.warning(self, i18n.t("Designation key"), str(error))
            return
        workspace.ensure_member(me["mid"], self.cfg)
        QMessageBox.information(
            self, i18n.t("Designation key"),
            i18n.t("This copy is now set up for {name} — {role}.\n\nRestart "
                   "Prism to pick up the role's colours and default tools."
                   ).format(name=me.get("name") or i18n.t("this member"),
                            role=R.label(me.get("role") or "")))
        self.licence_changed.emit()
        self.refresh()

    def _clear_designation(self):
        if QMessageBox.question(
                self, i18n.t("Remove role"),
                i18n.t("Turn this back into a personal copy?\n\nWork already "
                       "saved in the team workspace stays where it is."),
                QMessageBox.Yes | QMessageBox.Cancel) != QMessageBox.Yes:
            return
        identity.clear()
        QMessageBox.information(self, i18n.t("Removed"),
                                i18n.t("Restart Prism to finish switching "
                                       "back."))
        self.licence_changed.emit()
        self.refresh()

    def _add_member(self, name_field: QLineEdit, role_combo: QComboBox):
        name = name_field.text().strip()
        role_key = role_combo.currentData()
        if not name:
            QMessageBox.information(self, i18n.t("Team"),
                                    i18n.t("Enter the person's name."))
            return
        # The member id is derived the same way the minting tool derives it,
        # so the roster entry and the key we issue agree on the folder name
        # without anyone having to copy an id between the two.
        workspace.upsert_member(self.cfg, workspace.member_id(role_key, name),
                                name, role_key)
        self._after_save(i18n.t("{name} added.").format(name=name))

    def _members_card(self, members: list[dict]) -> Card:
        import roles as R
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, member in enumerate(members):
            if i:
                col.addWidget(C.hairline())
            role = R.get(member.get("role") or "")
            line = QHBoxLayout()
            line.setContentsMargins(0, theme.SPACE_3 - 1, 0, theme.SPACE_3 - 1)
            line.setSpacing(theme.SPACE_3)
            name = member.get("name") or member.get("mid") or "—"
            line.addWidget(C.Avatar(name, 32))
            stack = QVBoxLayout()
            stack.setSpacing(2)
            stack.addWidget(C.label(name, level="CARD_TITLE", colour=theme.TEXT,
                                    weight=600))
            stack.addWidget(C.label(role.label if role else
                                    (member.get("role") or "—"), level="META"))
            line.addLayout(stack, stretch=1)
            col.addLayout(line)
        return card

    def _member_card(self, member: dict) -> Card:
        import roles as R
        role = R.get(member.get("role") or "")
        card = Card()
        row = card.body((theme.SPACE_4, theme.SPACE_3,
                         theme.SPACE_4, theme.SPACE_3), spacing=0)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_3)
        name = member.get("name") or member.get("mid") or "—"
        line.addWidget(C.Avatar(name, 30))
        stack = QVBoxLayout()
        stack.setSpacing(0)
        stack.addWidget(C.label(name, level="SUPPORT", colour=theme.TEXT,
                                weight=500))
        stack.addWidget(C.label(role.label if role else
                                (member.get("role") or "—"), level="META"))
        line.addLayout(stack, stretch=1)
        row.addLayout(line)
        return card

    def _visibility(self, me: dict) -> str:
        """Said plainly, because finding it out later is a much worse day."""
        if me.get("admin"):
            return i18n.t("You are set up as a manager, so you can open any "
                          "member's profile and history from the History "
                          "screen.")
        if workspace.is_shared(self.cfg):
            return i18n.t("Your work is saved in the shared team workspace, "
                          "so your manager can see what you have run. Other "
                          "members cannot.")
        return i18n.t("Your work stays in your own folder on this computer. "
                      "Nobody else on the team can see it.")

    # ── agents ────────────────────────────────────────────────────────────
    def _agents(self, col):
        chosen = dict(self.cfg.get("agents") or {})
        categories = CB.agents.CATEGORIES
        premium = set(self.cfg.get("premium") or [])

        # The Groq key and the agent picks are one job — "change my AI
        # setup" — even though they used to live on two different nav
        # destinations (this section and Connections).
        key_edit = QLineEdit(self.cfg.get("api_key", ""))
        key_edit.setEchoMode(QLineEdit.Password)
        C.add_password_visibility(key_edit)
        key_edit.setPlaceholderText("gsk_…")
        col.addWidget(self._field_card(
            i18n.t("Groq key"),
            i18n.t("Free at console.groq.com — API Keys, then Create API "
                   "Key. It starts with gsk_. Prism cannot route anything "
                   "without one."),
            key_edit, lambda: self._save_key(key_edit)))

        col.addWidget(self._agents_editor(chosen, premium))
        # Leads & Outreach runs on the credit pool: the licence server holds every
        # e-mail verifier and finder key, so a customer has none to bring
        # (prospector/gateway.py). The card stays for the developer's direct mode.
        from prospector import gateway
        if not gateway.pooled():
            col.addWidget(self._verifier_card())

        picked = [(stage, chosen.get(stage))
                  for stage in CB.agents.PIPELINE_ORDER
                  if stage != "summary" and stage in categories]
        if not any(tool for _stage, tool in picked):
            return   # nothing saved yet — the editor above is the whole page

        col.addWidget(self._head(i18n.t("Currently active")))
        col.addWidget(self._agents_list_card(picked, categories, premium))

        # "Which tools you'll sign into" is a direct consequence of which
        # tools you picked, so it belongs beside the pick rather than on the
        # separate Connections page.
        sites = self._login_sites()
        if sites:
            col.addWidget(self._head(
                i18n.t("Where 'Open login tabs' will take you"),
                i18n.t("One tab per tool you have picked, opened in Prism's "
                       "own Chrome profile so the sign-in sticks.")))
            col.addWidget(self._sites_card(sites))

        col.addWidget(self._buttons([
            C.button(i18n.t("Open the AI tools screen"), "secondary",
                     on_click=lambda: self.navigate.emit("catalog")),
            C.button(i18n.t("Open login tabs"), "secondary",
                     on_click=self.login_tabs.emit)]))

    def _agents_editor(self, chosen: dict, premium: set) -> Card:
        """The picker and its premium tick-boxes, one editable card. Picking
        a specialist changes which premium checkbox can even exist for it, so
        the two rebuild together and save together — splitting them into two
        cards would let one save land without the other and leave a premium
        tick pointing at a tool nobody picked."""
        picker = AgentsPicker(chosen)
        premium_layout = QVBoxLayout()
        premium_layout.setContentsMargins(0, 0, 0, 0)
        premium_layout.setSpacing(6)
        premium_boxes: dict[str, QCheckBox] = {}

        def rebuild_premium():
            while premium_layout.count():
                item = premium_layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            premium_boxes.clear()
            names = sorted(set(picker.current_agents().values()))
            if not names:
                premium_layout.addWidget(C.label(
                    i18n.t("Pick at least one specialist above."),
                    level="META"))
                return
            for name in names:
                box = QCheckBox(name)
                box.setChecked(name in premium)
                box.setCursor(Qt.PointingHandCursor)
                premium_boxes[name] = box
                premium_layout.addWidget(box)

        picker.picked_changed.connect(rebuild_premium)
        rebuild_premium()

        card = Card()
        acol = card.body((theme.CARD_PAD, theme.CARD_PAD,
                          theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_3)
        acol.addWidget(C.kicker(i18n.t("Your specialists")))
        acol.addWidget(C.label(
            i18n.t("One tool per kind of step. Pick one per category, or "
                   "skip categories you won't use."), level="META",
            wrap=True))
        acol.addWidget(picker)
        acol.addWidget(C.hairline())
        acol.addWidget(C.kicker(i18n.t("Premium plans"), muted=True))
        acol.addWidget(C.label(
            i18n.t("Tick the tools you pay for — Prism routes the bulk of "
                   "the work to those and keeps the free ones for the short "
                   "steps."), level="META", wrap=True))
        acol.addLayout(premium_layout)
        acol.addWidget(self._buttons([C.button(
            i18n.t("Save"), "primary",
            on_click=lambda: self._save_agents(picker, premium_boxes))]))
        return card

    def _verifier_card(self) -> Card:
        """Every e-mail key in one card, in the order they are tried. One Save
        for the lot, unlike the single-field editors above: these are entered
        in a sitting, from a page of sign-ups, and eight separate Saves would
        be eight chances to lose the one that was not pressed."""
        card = Card()
        col = card.body((theme.CARD_PAD, theme.CARD_PAD,
                         theme.CARD_PAD, theme.CARD_PAD), theme.SPACE_2)
        col.addWidget(C.kicker(i18n.t("E-mail verification and finding")))
        col.addWidget(C.label(
            i18n.t("Bring your own keys. Prism asks the free tiers first, so "
                   "most checks cost nothing, and a key you have not set is "
                   "simply skipped."), level="META", wrap=True))
        edits: dict[str, QLineEdit] = {}
        for key, name, blurb in _VERIFIER_ROWS:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(C.label(i18n.t(name), level="SUPPORT",
                                  colour=theme.TEXT, weight=500))
            col.addWidget(C.label(i18n.t(blurb), level="META", wrap=True))
            field = QLineEdit(self.cfg.get(key, ""))
            field.setEchoMode(QLineEdit.Password)
            C.add_password_visibility(field)
            edits[key] = field
            col.addWidget(field)
        col.addSpacing(theme.SPACE_1)
        col.addWidget(self._buttons([C.button(
            i18n.t("Save"), "primary",
            on_click=lambda: self._save_verifier_keys(edits))]))
        return card

    def _save_verifier_keys(self, edits: dict):
        """Write every e-mail key at once. An emptied field clears its key —
        that is how a customer takes a key back off this machine."""
        for key, field in edits.items():
            self.cfg[key] = field.text().strip()
        self._after_save(i18n.t("Saved."))

    def _save_key(self, field: QLineEdit):
        key = field.text().strip()
        if key and not (key.startswith("gsk_") and len(key) > 20):
            QMessageBox.warning(self, i18n.t("API key"), i18n.t(
                "That doesn't look like a Groq key — it should start with "
                "'gsk_'."))
            return
        self.cfg["api_key"] = key
        self._after_save(i18n.t("Saved."))
        if key:
            self._check_groq_key(key)

    def _check_groq_key(self, key: str):
        """Saved — now find out whether Groq accepts it, and say so."""
        from workers import GroqKeyWorker
        self.show_toast(i18n.t("Saved — checking the key with Groq…"), "warn", 15000)
        worker = GroqKeyWorker(key, self.cfg.get("model", ""))

        def finished(why: str, key=key):
            if self.cfg.get("api_key") != key:
                return                       # replaced since — not this one's news
            if not why:
                self.show_toast(i18n.t("Saved — Groq accepts this key."), "ok")
            elif why.startswith("The key is valid") or why.startswith("The key works"):
                self.show_toast(why, "warn", 8000)
            else:
                self.show_toast(i18n.t("Saved, but ") + why[0].lower() + why[1:],
                                "err", 12000)
        worker.done.connect(finished)
        self._key_worker = worker
        worker.start()

    def _save_agents(self, picker: AgentsPicker, boxes: dict):
        agents = picker.current_agents()
        if not agents:
            QMessageBox.warning(self, i18n.t("Specialists"),
                                i18n.t("Pick at least one specialist."))
            return
        self.cfg["agents"] = agents
        self.cfg["premium"] = [name for name, box in boxes.items()
                               if box.isChecked()]
        self._after_save(i18n.t("Saved."))

    def _agents_list_card(self, picked, categories, premium) -> Card:
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (stage, tool) in enumerate(picked):
            if i:
                col.addWidget(C.hairline())
            meta = categories.get(stage, {})
            paid = tool in premium
            row = QHBoxLayout()
            row.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
            row.setSpacing(theme.SPACE_3)
            if tool:
                row.addWidget(C.ToolBadge(tool, 28), alignment=Qt.AlignTop)
            stack = QVBoxLayout()
            stack.setSpacing(2)
            stack.addWidget(C.label(tool or i18n.t("Not picked"), level="CARD_TITLE"))
            stack.addWidget(C.kicker(i18n.t(meta.get("label", stage.title()))))
            if meta.get("desc"):
                stack.addWidget(C.label(i18n.t(meta["desc"]), level="META", wrap=True))
            row.addLayout(stack, stretch=1)
            row.addWidget(Pill(i18n.t("Paid") if paid else i18n.t("Free"),
                               "accent" if paid else "quiet")
                          if tool else Pill(i18n.t("Skipped"), "quiet"),
                          alignment=Qt.AlignTop)
            col.addLayout(row)
        return card

    def _agent_card(self, meta: dict, stage: str, tool: str | None,
                    paid: bool) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        if tool:
            head.addWidget(C.ToolBadge(tool, 28))
        head.addWidget(C.label(tool or i18n.t("Not picked"),
                               level="CARD_TITLE"), stretch=1)
        head.addWidget(Pill(i18n.t("Paid") if paid else i18n.t("Free"),
                            "accent" if paid else "quiet")
                       if tool else Pill(i18n.t("Skipped"), "quiet"))
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.kicker(i18n.t(meta.get("label", stage.title()))))
        if meta.get("desc"):
            col.addSpacing(theme.SPACE_1)
            col.addWidget(C.label(i18n.t(meta["desc"]), level="META",
                                  wrap=True))
        return card

    # ── language ──────────────────────────────────────────────────────────
    def _language(self, col):
        packs = self._safe(i18n.available) or []
        current = i18n.current()
        out = (self.cfg.get("output_language") or "").strip()

        lang_combo = QComboBox()
        for code, name, native in packs:
            done, total = self._safe(lambda c=code: i18n.coverage(c)) or (0, 0)
            shown = native if native == name else f"{native} — {name}"
            if code != "en" and total and done < total:
                shown += f"  ({done * 100 // total}%)"
            lang_combo.addItem(shown, code)
        self._select_code(lang_combo, current)

        out_combo = QComboBox()
        out_combo.addItem(i18n.t("Same as I asked in"), "")
        for code, (name, native, _rtl) in i18n.LANGUAGES.items():
            if code == i18n.DEFAULT:
                continue
            out_combo.addItem(f"{native} — {name}", code)
        out_combo.insertItem(1, i18n.t("English"), "en")
        self._select_code(out_combo, out)
        out_combo.setToolTip(i18n.t(
            "Adds one line to every prompt asking the tool to answer in "
            "this language. Email addresses, links, file names and code are "
            "left alone."))

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(theme.SPACE_3)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        form.addRow(C.icon_label("globe", i18n.t("Prism's language")),
                    lang_combo)
        form.addRow(C.icon_label("pencil", i18n.t("AI writes back in")),
                    out_combo)
        form_widget = QWidget()
        form_widget.setLayout(form)

        col.addWidget(self._field_card(
            i18n.t("Language"),
            i18n.t("These are two different wishes. An owner who wants "
                   "Prism in Gujarati may still want the proposal it "
                   "produces in English, so changing one never changes the "
                   "other. A new interface language applies from the next "
                   "start."),
            form_widget,
            lambda: self._save_language(lang_combo, out_combo)))

        if packs:
            col.addWidget(self._head(
                i18n.t("Language packs on this copy"),
                i18n.t("A pack that is not finished falls back to English "
                       "line by line, so the gaps never look like a fault.")))
            rows = []
            for code, label, native in packs:
                done, total = self._safe(lambda c=code: i18n.coverage(c)) \
                    or (0, 0)
                shown = label if native == label else f"{native} — {label}"
                if total and done < total:
                    value = i18n.t("{percent}% translated").format(
                        percent=done * 100 // total)
                    tone = "warn"
                else:
                    value = i18n.t("Complete")
                    tone = "ok"
                if code == current:
                    tone = "accent"
                    value = i18n.t("In use")
                rows.append((shown, Pill(value, tone)))
            col.addWidget(self._facts(rows))

    def _save_language(self, lang_combo: QComboBox, out_combo: QComboBox):
        changed = (lang_combo.currentData() or i18n.DEFAULT) != i18n.current()
        self.cfg["language"] = lang_combo.currentData() or i18n.DEFAULT
        self.cfg["output_language"] = out_combo.currentData() or ""
        self._after_save(
            i18n.t("Saved — restart Prism for the new language to take "
                   "effect.") if changed else i18n.t("Saved."))

    @staticmethod
    def _select_code(combo: QComboBox, code: str):
        """Select by data, not by label — the labels are translated."""
        index = combo.findData(code)
        combo.setCurrentIndex(index if index >= 0 else 0)

    # ── connections ───────────────────────────────────────────────────────
    def _connections(self, col):
        """Chrome + browser automation + team-folder reachability — what's
        left once the Groq key and the login-site grid moved to Agents (they
        were never really "connections" so much as "your AI setup," which is
        one nav destination, not two)."""
        chrome = (self.cfg.get("chrome_version") or "").strip()
        offline = workspace.unreachable(self.cfg)
        ok, why = self._safe(CB.automation_available) or (False, "")

        col.addWidget(self._facts([
            (i18n.t("Chrome"), chrome or i18n.t("Auto-detect")),
            (i18n.t("Browser automation"),
             Pill(i18n.t("Ready") if ok else i18n.t("Unavailable"),
                  "ok" if ok else "err")),
            (i18n.t("Team folder"),
             Pill(i18n.t("Unreachable") if offline else i18n.t("Reachable"),
                  "err" if offline else "ok")),
        ]))
        if not ok and why:
            col.addWidget(self._note(str(why).splitlines()[0]))
        if offline:
            col.addWidget(self._note(offline))

        col.addWidget(self._head(
            i18n.t("Your browser"),
            i18n.t("Prism drives your own Chrome, signed in as you. It keeps "
                   "a separate profile so those logins survive between "
                   "runs — which is also why a login done in your everyday "
                   "Chrome does not reach it.")))
        col.addWidget(self._facts(self._browser_rows()))

        chrome_edit = QLineEdit(self.cfg.get("chrome_version", ""))
        chrome_edit.setPlaceholderText(i18n.t("blank = auto-detect"))
        detect_btn = C.button(i18n.t("Detect"), "secondary",
                              on_click=lambda: self._detect_chrome(chrome_edit))
        col.addWidget(self._field_card(
            i18n.t("Chrome version"),
            i18n.t("Leave blank to auto-detect. Only pin this if automation "
                   "keeps failing to attach."),
            self._row([chrome_edit]),
            lambda: self._save_chrome(chrome_edit),
            extra_buttons=[detect_btn]))

        col.addWidget(self._buttons([
            C.button(i18n.t("Copy my Chrome logins again"), "secondary",
                     on_click=self._reseed_profile),
            C.button(i18n.t("Close Prism's browser"), "secondary",
                     on_click=self._close_browser),
        ]))

    def _detect_chrome(self, field: QLineEdit):
        try:
            automation = CB.get_automation()
            version = automation.detect_chrome_version()
        except Exception as error:                     # noqa: BLE001
            QMessageBox.warning(self, i18n.t("Chrome detection"), i18n.t(
                "Couldn't detect Chrome: {error}").format(error=error))
            return
        field.setText(str(version) if version else "")

    def _save_chrome(self, field: QLineEdit):
        ok, _why = self._safe(CB.automation_available) or (False, "")
        parsed = ok and CB.get_automation().parse_chrome_version(field.text())
        self.cfg["chrome_version"] = str(parsed) if parsed else ""
        self._after_save(i18n.t("Saved."))

    def _close_browser(self):
        """Shut Prism's browser, including one left behind by a crash.

        Prism leaves its Chrome open on purpose between runs — a slow tool
        often finishes in its tab after Prism stops watching. The cost is
        that a crash, or a Login-tabs window somebody left open, leaves a
        Chrome holding the profile, and Chrome allows only one browser per
        profile folder: the next run's launch hands over to that one and
        exits, and chromedriver reports "cannot connect to chrome".

        Runs recover from this by themselves now (automation._release_profile
        clears it before launching), so this is the manual escape hatch
        KNOWN_ISSUES #11 asked for — the thing to press when something is
        wrong and nobody wants to reason about why. Both halves: the driver
        this session owns, and any orphan holding the profile.
        """
        ok, err = self._safe(CB.automation_available) or (False, "")
        if not ok:
            QMessageBox.warning(self, i18n.t("Chrome"), i18n.t(
                "Automation isn't available: {error}").format(error=err))
            return
        automation = CB.get_automation()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            automation.shutdown()
            closed = automation._release_profile()
        except Exception as error:                     # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, i18n.t("Chrome"), i18n.t(
                "Couldn't close the browser: {error}").format(error=error))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, i18n.t("Chrome"),
            i18n.t("Prism's browser is closed. The next run will open a fresh "
                   "one — your logins are kept.")
            if closed else
            i18n.t("Prism's browser was not running. Nothing to close, and "
                   "your logins are untouched."))

    def _reseed_profile(self):
        """Re-copies cookies from the customer's everyday Chrome into Prism's
        own profile — the fix for "I signed in but Prism still asks.\""""
        ok, err = self._safe(CB.automation_available) or (False, "")
        if not ok:
            QMessageBox.warning(self, i18n.t("Chrome"), i18n.t(
                "Automation isn't available: {error}").format(error=err))
            return
        automation = CB.get_automation()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            automation.seed_profile(force=True)
        except Exception as error:                     # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, i18n.t("Chrome"), i18n.t(
                "Couldn't copy the profile: {error}").format(error=error))
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, i18n.t("Chrome"),
            i18n.t("Copied your Chrome logins into Prism's profile.\n\nIf a "
                   "tool still asks you to sign in, sign in inside the "
                   "window Prism opens — that sticks."))
        self.refresh()

    def _login_sites(self) -> list[tuple[str, str]]:
        """The tools this copy is set up to drive, and the address each one
        signs in at — reads core_bridge.resolved_agents(), the one shared
        implementation of this lookup (also used by MainWindow's Login tabs
        and the wizard)."""
        return CB.resolved_agents(dict(self.cfg.get("agents") or {}))

    def _sites_card(self, sites: list[tuple[str, str]]) -> Card:
        card = Card()
        col = card.body((theme.CARD_PAD, theme.SPACE_2,
                         theme.CARD_PAD, theme.SPACE_2), spacing=0)
        for i, (tool, url) in enumerate(sites):
            if i:
                col.addWidget(C.hairline())
            row = QHBoxLayout()
            row.setContentsMargins(0, theme.SPACE_3, 0, theme.SPACE_3)
            row.setSpacing(theme.SPACE_3)
            row.addWidget(C.ToolBadge(tool, 28), alignment=Qt.AlignTop)
            stack = QVBoxLayout()
            stack.setSpacing(2)
            stack.addWidget(C.label(tool, level="CARD_TITLE"))
            if url:
                stack.addWidget(self._path(url))
            row.addLayout(stack, stretch=1)
            col.addLayout(row)
        return card

    def _site_card(self, tool: str, url: str) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.ToolBadge(tool, 28))
        head.addWidget(C.label(tool, level="CARD_TITLE"), stretch=1)
        col.addLayout(head)
        if url:
            col.addSpacing(theme.SPACE_2)
            col.addWidget(self._path(url))
        return card

    def _browser_rows(self) -> list:
        rows = []
        automation = self._safe(CB.get_automation)
        if automation is None:
            rows.append((i18n.t("Prism's browser profile"),
                         i18n.t("Not created yet")))
            return rows
        folder = getattr(automation, "PROFILE_DIR", "") or ""
        rows.append((i18n.t("Prism's browser profile"),
                     self._path(folder) if folder else "—"))
        seeded = self._safe(automation.profile_is_seeded)
        rows.append((i18n.t("Your logins copied in"),
                     Pill(i18n.t("Yes") if seeded else i18n.t("Not yet"),
                          "ok" if seeded else "quiet")))
        return rows

    # ── appearance ────────────────────────────────────────────────────────
    # Bundled wallpapers shipped with Prism. Resolved relative to this file so
    # they work regardless of where the user launches the app from.
    _BUNDLED_WALLS: list[tuple[str, str]] = [
        ("prism_wall_1.jpg",  "Wallpaper 1"),
        ("prism_wall_2.jpg",  "Wallpaper 2"),
        ("prism_wall_3.jpg",  "Wallpaper 3"),
        ("prism_wall_4.jpg",  "Wallpaper 4"),
        ("prism_wall_5.png",  "Wallpaper 5"),
        ("prism_wall_6.png",  "Wallpaper 6"),
    ]

    @staticmethod
    def _bundled_wall_dir() -> str:
        """Absolute path to assets/wallpapers/ next to this package."""
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.dirname(here), "assets", "wallpapers")

    def _appearance(self, col):
        card_wall = Card()
        cw = card_wall.body(
            (theme.CARD_PAD, theme.SPACE_4, theme.CARD_PAD, theme.SPACE_4),
            spacing=theme.SPACE_3,
        )

        # ── header ──
        head_w = QHBoxLayout()
        head_w.setSpacing(theme.SPACE_3)
        head_w.addWidget(
            C.IconPad("image", theme.ACCENT, 34, theme.R_CONTROL, 17)
        )
        w_col = QVBoxLayout()
        w_col.addWidget(
            C.label(i18n.t("Dashboard wallpaper"), level="CARD_TITLE")
        )
        w_col.addWidget(
            C.label(
                i18n.t("Choose one of the Prism wallpapers, upload your own image, or keep the clean default."),
                level="META",
            )
        )
        head_w.addLayout(w_col, stretch=1)
        cw.addLayout(head_w)

        # ── active wallpaper label ──
        current_bg = (self.cfg.get("custom_bg") or "").strip()
        wall_dir = self._bundled_wall_dir()

        def _same_path(p1: str, p2: str) -> bool:
            if not p1 or not p2:
                return False
            return os.path.normcase(os.path.normpath(p1)) == os.path.normcase(os.path.normpath(p2))

        is_bundled = any(
            _same_path(current_bg, os.path.join(wall_dir, fname))
            for fname, _ in self._BUNDLED_WALLS
        ) if current_bg else False

        if current_bg and os.path.exists(current_bg):
            if is_bundled:
                matched_label = next(
                    (lbl for fname, lbl in self._BUNDLED_WALLS
                     if _same_path(current_bg, os.path.join(wall_dir, fname))),
                    os.path.basename(current_bg),
                )
                status_text = matched_label
            else:
                status_text = f"{os.path.basename(current_bg)} ({i18n.t('Custom')})"
        else:
            status_text = i18n.t("Default (Light)")

        cw.addWidget(
            C.label(f"{i18n.t('Active')}: {status_text}", level="META")
        )

        # ── thumbnail grid ──
        # 3 columns: each tile is 190x116 px with a label underneath.
        THUMB_W, THUMB_H = 190, 116
        RADIUS = 10
        COLS = 3

        def _tile_border(active: bool) -> str:
            if active:
                return f"3px solid {theme.ACCENT}"
            return "2px solid rgba(0,0,0,0.12)"

        grid_widget = QWidget()
        grid_widget.setStyleSheet("background: transparent;")
        grid_rows = QVBoxLayout(grid_widget)
        grid_rows.setContentsMargins(0, 0, 0, 0)
        grid_rows.setSpacing(theme.SPACE_3)

        all_options: list[tuple[str, str]] = [("default", i18n.t("Default (Light)"))] + [
            (os.path.join(wall_dir, fname), label)
            for fname, label in self._BUNDLED_WALLS
        ]

        if current_bg and os.path.exists(current_bg) and not is_bundled:
            all_options.append((current_bg, f"{i18n.t('Custom')}: {os.path.basename(current_bg)}"))

        rows_of = [all_options[i:i + COLS] for i in range(0, len(all_options), COLS)]

        for row_items in rows_of:
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(theme.SPACE_3)

            for path, label in row_items:
                is_active = (
                    (path == "default" and not current_bg)
                    or (path != "default" and _same_path(current_bg, path))
                )

                # Each tile: image button + text label below
                tile_col = QVBoxLayout()
                tile_col.setContentsMargins(0, 0, 0, 0)
                tile_col.setSpacing(5)

                btn = QPushButton()
                btn.setFixedSize(THUMB_W, THUMB_H)
                btn.setToolTip(label)
                btn.setCursor(Qt.PointingHandCursor)
                btn.setFlat(True)

                border = _tile_border(is_active)

                if path == "default":
                    btn.setStyleSheet(
                        f"QPushButton {{ border: {border}; border-radius: {RADIUS}px;"
                        " background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                        "stop:0 #e8eaf0, stop:0.5 #f0f2f7, stop:1 #dde1ea);"
                        " color: #555; font-size: 13px; font-weight: 600; }"
                    )                                   # plain string: ONE brace
                    btn.setText("Default\n(Light)")
                else:
                    pix = QPixmap(path)
                    if not pix.isNull():
                        scaled = pix.scaled(
                            THUMB_W, THUMB_H,
                            Qt.KeepAspectRatioByExpanding,
                            Qt.SmoothTransformation,
                        )
                        sx = max(0, (scaled.width() - THUMB_W) // 2)
                        sy = max(0, (scaled.height() - THUMB_H) // 2)
                        cropped = scaled.copy(sx, sy, THUMB_W, THUMB_H)
                        btn.setIcon(QIcon(cropped))
                        btn.setIconSize(QSize(THUMB_W, THUMB_H))
                    btn.setStyleSheet(
                        f"QPushButton {{ border: {border};"
                        f" border-radius: {RADIUS}px;"
                        "  padding: 0; margin: 0;"
                        "  background: transparent; }"      # not an f-string: ONE brace
                    )

                # Active tick badge
                if is_active:
                    ck = QLabel("✓", btn)
                    ck.setStyleSheet(
                        f"background: {theme.ACCENT}; color: white;"
                        " font-size: 13px; font-weight: bold;"
                        " border-radius: 10px; padding: 2px 5px; border: none;"
                    )
                    ck.adjustSize()
                    ck.move(THUMB_W - ck.width() - 6, 6)
                    ck.raise_()

                btn.clicked.connect(
                    lambda checked=False, p=path: self._apply_preset_wallpaper(p)
                )
                tile_col.addWidget(btn)

                # Name label under the tile
                display_label = label
                if len(display_label) > 24:
                    display_label = display_label[:21] + "…"
                lbl_name = C.label(display_label, level="META")
                lbl_name.setAlignment(Qt.AlignCenter)
                lbl_name.setFixedWidth(THUMB_W)
                lbl_name.setToolTip(label)
                tile_col.addWidget(lbl_name)

                row_layout.addLayout(tile_col)

            row_layout.addStretch()
            grid_rows.addLayout(row_layout)

        cw.addWidget(grid_widget)

        # ── custom wallpaper button ──
        cw.addWidget(self._buttons([
            C.button(
                i18n.t("Choose custom wallpaper…"),
                "secondary",
                icon_name="image",
                on_click=self._choose_wallpaper,
            ),
        ]))

        col.addWidget(card_wall)

    def _choose_wallpaper(self):
        current_bg = (self.cfg.get("custom_bg") or "").strip()
        if current_bg and os.path.exists(os.path.dirname(current_bg)):
            suggested = os.path.dirname(current_bg)
        else:
            suggested = paths.picker_start_dir()
        path, _ = QFileDialog.getOpenFileName(
            self,
            i18n.t("Select dashboard wallpaper"),
            suggested,
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if path:
            self._apply_preset_wallpaper(path)

    def _apply_preset_wallpaper(self, path: str):
        """Apply one of the Prism bundled wallpapers (or '' for white default)."""
        effective = "" if path == "default" else path
        self.wallpaper_changed.emit(effective)
        target = self.parent() or self.window()
        if hasattr(target, "set_wallpaper") and target is not self:
            target.set_wallpaper(effective)
        self.cfg["custom_bg"] = effective
        try:
            CB.config.save(self.cfg)
        except Exception:
            pass
        self.refresh()

    # ── privacy & data ────────────────────────────────────────────────────
    def _privacy(self, col):
        me = identity.current()
        root = workspace.root(self.cfg)
        shared = workspace.is_shared(self.cfg)
        prism_dir = self._safe(paths.user_dir) or ""
        logs = self._safe(self._log_dir) or ""
        artifacts_dir = self._safe(CB.config.artifacts_root) or CB.config.ARTIFACTS_DIR

        col.addWidget(self._facts([
            (i18n.t("Your work is written to"), self._path(root or "—")),
            (i18n.t("This folder is"),
             Pill(i18n.t("Shared with the team") if shared
                  else i18n.t("On this computer only"),
                  "accent" if shared else "quiet")),
            (i18n.t("Filed under"), self._mono(me.get("mid") or "—")),
            (i18n.t("Prism's own folder"), self._path(prism_dir or "—")),
            (i18n.t("Generated files (Reel, images, documents)"),
             self._path(artifacts_dir)),
            (i18n.t("Logs"), self._path(logs or "—")),
            (i18n.t("Log files on disk"), self._safe(self._log_size) or "—"),
        ]))

        # ── where Prism saves the files it makes ──────────────────────────
        col.addWidget(self._head(
            i18n.t("Where Prism saves your files"),
            i18n.t("Leave a box empty to use the usual folder on your Desktop. "
                   "A folder you choose is created if it does not exist.")))
        self._output_folder_cards(col)

        # A development build starts as a brand-new install; offer to bring the
        # normal Prism's settings across (read-only on the normal one).
        import dev_import
        if dev_import.applicable():
            self._dev_import_card(col)

        # Everything irreversible lives in the red card at the foot of the page.
        col.addWidget(self._danger(
            i18n.t("Uninstall Prism"),
            i18n.t("Remove Prism from this computer. You choose whether to keep your settings, "
                   "History and files, or remove everything. Nothing is removed until you confirm."),
            [C.button(i18n.t("Uninstall…"), "destructive", on_click=self._open_uninstall)]))



    def _redacted_card(self, label: str) -> Card:
        """One thing diagnostics._scrub() removes. The list is short and it is
        the answer to the only question a customer has before emailing a log
        file to a supplier."""
        card = Card()
        row = card.body((theme.SPACE_4, theme.SPACE_3,
                         theme.SPACE_4, theme.SPACE_3), spacing=0)
        line = QHBoxLayout()
        line.setSpacing(theme.SPACE_3)
        line.addWidget(C.IconPad("lock", theme.OK, 30, theme.R_CONTROL, 15))
        line.addWidget(C.label(i18n.t(label), level="SUPPORT",
                               colour=theme.TEXT, wrap=True), stretch=1)
        row.addLayout(line)
        return card

    @staticmethod
    def _log_dir() -> str:
        import diagnostics
        return diagnostics.log_dir()

    @staticmethod
    def _log_size() -> str:
        """How much disk the rolling log is actually using, and the ceiling it
        cannot pass. Read off diagnostics' own constants, so a change to the
        rotation policy cannot leave this page describing the old one."""
        import diagnostics
        total = 0
        for index in range(diagnostics.KEEP):
            path = (diagnostics.log_path() if index == 0
                    else f"{diagnostics.log_path()}.{index}")
            try:
                total += os.path.getsize(path)
            except OSError:
                pass
        cap = diagnostics.MAX_BYTES * diagnostics.KEEP
        return i18n.t("{used} KB of at most {cap} KB").format(
            used=total // 1024, cap=cap // 1024)

    def _open_folder(self, path: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _open_artifacts_folder(self, path: str):
        """Unlike _open_folder's other callers, this one may not exist yet —
        nothing has necessarily been generated this session — so it is made
        first rather than failing silently on a folder nobody has seen."""
        os.makedirs(path, exist_ok=True)
        self._open_folder(path)

    # ── updates (Phase 0 — a check, a line, a link; see updater.py) ───────
    def _version_row(self) -> QWidget:
        """The running version, and the button that asks whether it is the
        newest. The ten-minute lease timer asks the same question on its own;
        this is for the customer who has just read our release email."""
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(theme.SPACE_3)
        row.addWidget(C.label(app_meta.VERSION, level="SUPPORT",
                              colour=theme.TEXT, weight=500))
        if self._update_check == "checking":
            row.addWidget(C.label(i18n.t("Checking…"), level="META"))
        else:
            row.addWidget(C.button(i18n.t("Check for updates"), small=True,
                                   on_click=self._check_for_updates))
        return box

    def _update_card(self) -> Card | None:
        """What the last answer from the server means for this build, or
        nothing at all when there is nothing to say — a settings page must
        not carry a permanent "you are up to date" pat on the back."""
        state = licensing.state()
        if updater.required(state):
            return self._action_card(
                i18n.t("Update needed"),
                i18n.t("This version of Prism can no longer start new work. "
                       "Download Prism {version} to continue — your history, "
                       "settings and files are untouched.").format(
                           version=updater.target(state)),
                download=True)
        newer = updater.available(state)
        if newer:
            return self._action_card(
                i18n.t("Update available"),
                i18n.t("Prism {version} is available. You have {current}. "
                       "Download it, close Prism, and run the new one — your "
                       "settings and history carry over.").format(
                           version=newer, current=app_meta.VERSION),
                download=True)
        if self._update_check == "done":
            return self._note(
                i18n.t("You have the latest version of Prism."), "info")
        return None

    def _action_card(self, kicker: str, text: str, download: bool) -> Card:
        card = Card()
        card.setStyleSheet(
            f"#card {{ background: {theme.INFO_BG};"
            f" border-radius: {theme.R_CARD}px;"
            f" border: 1px solid {theme.ACCENT_RAMP[200]}; }}")
        col = card.body((theme.CARD_PAD, theme.SPACE_4,
                         theme.CARD_PAD, theme.SPACE_4), spacing=0)
        col.addWidget(C.kicker(kicker))
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(text, level="SUPPORT", colour=theme.INFO_INK,
                              wrap=True))
        if download:
            col.addSpacing(theme.SPACE_3)
            col.addWidget(self._buttons([
                C.button(i18n.t("Download"), "primary",
                         on_click=self._open_download)]))
        return card

    def _check_for_updates(self):
        """Ask the server now rather than at the next ten-minute tick.

        licensing.refresh() does its round trip on a worker thread; the
        answer comes back through _update_checked, which Qt delivers on this
        thread. Until then the row says "Checking…" and the button is gone,
        so a second click cannot start a second thread.
        """
        if self._update_check == "checking":
            return
        self._update_check = "checking"
        licensing.refresh(on_done=self._update_checked.emit)
        self.refresh()

    def _after_update_check(self):
        self._update_check = "done"
        licensing.reload()
        # The main window listens to this and redraws its banner, so the
        # answer shows in both places at once.
        self.licence_changed.emit()
        self.refresh()

    @staticmethod
    def _open_download():
        try:
            QDesktopServices.openUrl(QUrl(updater.download_url()))
        except Exception:                            # noqa: BLE001
            pass



    # ── help & more ───────────────────────────────────────────────────────
    def _more(self, col):
        # Lumi's ordinary answers are bundled; live error diagnosis is an
        # explicit opt-in that uses the customer's saved Groq key.
        col.addWidget(self._buttons([
            C.button(i18n.t("Open Lumi"), "primary",
                    on_click=lambda: self.navigate.emit("support")),
        ]))
        
        # Book a meeting card
        meeting_card = Card()
        mc = meeting_card.body((theme.SPACE_4, theme.SPACE_4, theme.SPACE_4, theme.SPACE_4), spacing=theme.SPACE_3)
        mc_head = QHBoxLayout()
        mc_head.setSpacing(theme.SPACE_3)
        mc_head.addWidget(C.IconPad("clock", theme.ACCENT, 34, theme.R_CONTROL, 17))
        mc_head_text = QVBoxLayout()
        mc_head_text.addWidget(C.label(i18n.t("Book a meeting with AlphaKore"), level="CARD_TITLE"))
        mc_head_text.addWidget(C.label(i18n.t("Schedule a 1-on-1 session with our team"), level="META"))
        mc_head.addLayout(mc_head_text, stretch=1)
        mc.addLayout(mc_head)
        mc.addWidget(C.label(
            i18n.t("Need help with complex workflows or customizing Prism for your team? "
                   "Book a meeting directly with us."),
            level="SUPPORT", wrap=True))
        mc.addWidget(self._buttons([
            C.button(i18n.t("Book a meeting"), "primary",
                     on_click=self._book_meeting)]))
        col.addWidget(meeting_card)

        # Contact facts
        col.addWidget(self._facts([
            (i18n.t("Email us"), app_meta.SUPPORT_EMAIL),
            (i18n.t("Call us"), app_meta.SUPPORT_PHONE),
            (i18n.t("Website"), app_meta.WEBSITE),
            (i18n.t("Version"), self._version_row()),
        ]))
        update_card = self._update_card()
        if update_card is not None:
            col.addWidget(update_card)
        
        # Legal links
        col.addWidget(self._buttons([
            C.button(i18n.t("Terms of Use"), "secondary", small=True,
                     on_click=lambda: self._open_legal(
                         i18n.t("Terms of Use"), "TERMS_OF_USE.md")),
            C.button(i18n.t("Privacy Policy"), "secondary", small=True,
                     on_click=lambda: self._open_legal(
                         i18n.t("Privacy Policy"), "PRIVACY_POLICY.md")),
        ]))

    def _book_meeting(self):
        """Open the AlphaKore meeting booking link in the browser."""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl("https://alphakore.in/book"))

    def _open_legal(self, title: str, resource_name: str):
        # Local import, same convention support_panel.py's _open_contact()
        # uses for ContactDialog: dialogs/ imports from widgets/ (controls,
        # icons), so a widgets/ module importing a dialogs/ class at module
        # scope risks a circular import — importing at point-of-use avoids it.
        from dialogs.legal_dialog import LegalDialog
        LegalDialog(title, resource_name, self.window()).exec()

    def _door_card(self, key: str, label: str, blurb: str) -> Card:
        card = Card()
        col = card.body((theme.SPACE_4, theme.SPACE_4,
                         theme.SPACE_4, theme.SPACE_4), spacing=0)
        head = QHBoxLayout()
        head.setSpacing(theme.SPACE_3)
        head.addWidget(C.IconPad(MORE_ICONS.get(key, "grid"), theme.ACCENT,
                                 30, theme.R_CONTROL, 15))
        head.addWidget(C.label(i18n.t(label), level="CARD_TITLE"), stretch=1)
        col.addLayout(head)
        col.addSpacing(theme.SPACE_2)
        col.addWidget(C.label(i18n.t(blurb), level="META", wrap=True))
        col.addSpacing(theme.SPACE_3)
        col.addWidget(self._buttons([
            C.button(i18n.t("Open"), "secondary", small=True,
                     on_click=lambda _=False, k=key: self.navigate.emit(k))]))
        return card

    # ── bits ──────────────────────────────────────────────────────────────
    @staticmethod
    def _safe(fn, default=None):
        """Run a probe, or hand back `default`. Settings is a screen a stuck
        customer opens; a section that raises because a shared drive is down
        is the one moment it must not."""
        try:
            return fn()
        except Exception:                            # noqa: BLE001
            return default

    @staticmethod
    def _when(stamp: int) -> str:
        if not stamp or stamp >= 2**31 - 1:
            return "—"
        try:
            return datetime.fromtimestamp(stamp).strftime("%d %B %Y")
        except (OSError, ValueError, OverflowError):
            return "—"

    @staticmethod
    def _mono(text: str) -> QLabel:
        label = C.label(str(text), level="MONO")
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label

    @staticmethod
    def _path(text: str) -> QLabel:
        """Elided from the left — the tail of a path is what identifies it,
        and a shared-drive prefix is the same on every row."""
        text = str(text)
        label = C.label(text if len(text) <= 46 else "…" + text[-45:],
                        level="MONO", tooltip=text)
        label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        return label
