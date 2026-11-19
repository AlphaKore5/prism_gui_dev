"""The inquiry detail panel that slides over the board.

A small copy of the Leads drawer pattern (addons/leads/cockpit.py _Reveal and
its float/slide/Esc handling) — add-ons may not import each other. It is a
child of InquiryDialog, never of the board, so a board re-render cannot
destroy it; it holds the inquiry NUMBER, not the row dict, and re-finds the
live row in host._register_rows on every render (the same re-anchoring
InquiryDialog._current_row does).

Every button calls host.act_on(row, key) — the drawer opens no modal of its
own and starts no worker. While one of the dialog's workers is sending or
reading, the drawer's action buttons are disabled.

Reads only what is already on disk: the register row, the worklist, the
inquiry folder and its history.txt. No AI call.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRect, QRectF, QTimer, Qt,
    Signal,
)
from PySide6.QtGui import (
    QKeySequence, QLinearGradient, QPainter, QShortcut,
)
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
    QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
import inquiry_config
from widgets import controls as C
from widgets import icons
from addons.inquiry import board as B

_SHADOW = 18          # px of painted shadow to the drawer's left
_MS = 160


def _motion_ok() -> bool:
    if os.environ.get("QT_QPA_PLATFORM", "") == "offscreen":
        return False
    return os.environ.get("PRISM_EFFECTS", "1") != "0"


# ── which buttons a row gets, by stage and sub-state (pure) ───────────────
def drawer_actions(stage: str, sub: str, row: dict, p: dict,
                   has_drawing: bool = False) -> dict:
    """{"primary": key|None, "secondary": [keys], "warn": bool,
    "pricebox": bool, "think": bool} — the approved design's actions()."""
    steps = p.get("steps") or {}
    out = {"primary": None, "secondary": [], "warn": False,
           "pricebox": False, "think": False}
    S = out["secondary"]
    if stage == "inquiry" and sub == "them":
        out["primary"] = "chase_details"
        S += ["prepare", "phone"]
    elif stage == "inquiry":
        out["primary"] = "prepare"
        if steps.get("details", True):
            S.append("ask_details")
        S.append("already_quoted")
        if has_drawing:
            S.append("boq")
        # The mail check thought their mail may be a PO but left the row
        # an inquiry: "They sent a PO" is the owner's confirmation, so it
        # comes first.
        if CB.get_register().maybe_po(row):
            S.insert(0, "got_po")
        else:
            S.append("got_po")
    elif stage == "quoted" and sub != "countered":
        maxed = B.reminders_sent(row) >= int(p.get("max_reminders") or 3)
        if maxed:
            out["warn"] = True
            out["primary"] = "phone"
            S.append("remind")
        else:
            out["primary"] = "remind"
            S.append("phone")
        S += ["revise", "countered", "said_yes"]
    elif stage == "nego" or (stage == "quoted" and sub == "countered"):
        out["pricebox"] = out["think"] = True
        out["primary"] = "revise"
        S += ["hold", "said_yes", "phone", "win_back"]
    elif stage == "po" and sub == "check":
        out["primary"] = "read_po"
        S += ["record_po", "not_order"]
    elif stage == "po" and sub == "nopo":
        out["primary"] = "price_po"
        S += ["read_po", "not_order"]
    elif stage == "po" and sub == "yes":
        out["primary"] = "record_po"
        S += ["chase_po", "phone"]
    elif stage == "po" and sub == "proforma" and CB.get_register().proforma_due(row):
        out["primary"] = "send_proforma"
        S += ["advance"]
    elif stage == "po" and sub == "proforma":
        out["primary"] = "advance"
        S += ["chase_advance"]
    elif stage == "won":
        out["primary"] = "open_po"
        if has_drawing:
            S.append("boq")
    elif stage == "lost":
        out["primary"] = "win_back"
        S.append("reopen")
    if stage not in ("won", "lost"):
        S.append("lost")
    return out


MORE_KEYS = ("edit", "folder", "history", "delete")


def action_text(key: str, p: dict, row: dict) -> str:
    """The button's words, in the client's own wording."""
    q = B.word_text(p, "quote")
    po = B.word_text(p, "po")
    register = CB.get_register()
    rev = (register.next_revision(row) if (row.get("Quotation no") or "").strip()
           else register.revision_of(row) + 1)
    texts = {
        "chase_details": i18n.t("Remind them about the details"),
        "prepare": i18n.t("Prepare a {quote}").replace("{quote}", q.lower()),
        "phone": i18n.t("They replied by phone…"),
        "ask_details": i18n.t("Ask for details"),
        "already_quoted": i18n.t("Already quoted by phone"),
        "boq": i18n.t("Count quantities from the drawing"),
        "got_po": i18n.t("They sent a {po}").replace("{po}", po),
        "remind": i18n.t("Send a reminder"),
        "revise": i18n.t("Send a revised {quote} (Rev {n})")
        .replace("{quote}", q.lower()).replace("{n}", str(rev)),
        "countered": i18n.t("They countered"),
        "said_yes": i18n.t("They said yes"),
        "hold": i18n.t("Hold the price — reply"),
        "win_back": i18n.t("Write a reply to win them back"),
        "read_po": i18n.t("Read the {po} and compare").replace("{po}", po),
        "record_po": i18n.t("Record the {po} by hand").replace("{po}", po),
        "not_order": i18n.t("Not an order — remove it"),
        "price_po": i18n.t("Price it from the rate list"),
        "chase_po": i18n.t("Remind them for the {po}").replace("{po}", po),
        "advance": i18n.t("Advance received — confirm the order"),
        "chase_advance": i18n.t("Remind about the advance"),
        "send_proforma": i18n.t("Send the proforma"),
        "open_po": i18n.t("Open the {po}").replace("{po}", po),
        "reopen": i18n.t("Reopen it"),
        "lost": i18n.t("Mark as lost"),
        "edit": i18n.t("Edit details"),
        "folder": i18n.t("Open this inquiry's folder"),
        "history": i18n.t("See the whole story"),
        "delete": i18n.t("Delete this inquiry"),
        "update": i18n.t("Update the register"),
    }
    return texts.get(key, key)


ICONS = {"prepare": "file-text", "revise": "file-text", "remind": "bell",
         "chase_details": "bell", "chase_po": "bell", "chase_advance": "bell",
         "send_proforma": "send",
         "phone": "phone", "ask_details": "send", "hold": "send",
         "win_back": "send", "said_yes": "check", "advance": "check",
         "countered": "message-circle", "read_po": "file", "record_po": "file",
         "not_order": "x", "price_po": "file-text", "open_po": "file",
         "reopen": "arrow-right", "lost": "x", "got_po": "file",
         "already_quoted": "phone", "boq": "grid"}

# What the "Prism thinks" box offers, in order.
INTENTS = ("negotiating", "needs_info", "accepted", "rejected", "unclear")


class _Surface(QFrame):
    """Opaque white card with a painted soft shadow on its left edge (no
    QGraphicsEffect — those smear on Windows high-DPI)."""

    def paintEvent(self, _event):                       # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        g = QLinearGradient(0, 0, _SHADOW, 0)
        g.setColorAt(0, theme.qcolor("#00000000"))
        g.setColorAt(1, theme.qcolor("#22000000"))
        p.fillRect(QRectF(0, 0, _SHADOW, r.height()), g)
        body = QRectF(_SHADOW, 0, r.width() - _SHADOW, r.height())
        p.setPen(theme.qcolor(theme.NEUTRAL[200]))
        p.setBrush(theme.qcolor("#ffffff"))
        p.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5), 14, 14)


class _Scrim(QWidget):
    """The board under the drawer: a click there closes it."""
    clicked = Signal()

    def mousePressEvent(self, event):                   # noqa: N802
        self.clicked.emit()
        event.accept()

    def paintEvent(self, _event):                       # noqa: N802
        QPainter(self).fillRect(self.rect(), theme.qcolor("#0f000000"))


class InquiryDrawer(QWidget):
    """The detail panel. `host` is the InquiryDialog."""
    closed = Signal()

    TABS = ("overview", "emails", "quotation", "files", "timeline")

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.no = ""
        self.order: list[str] = []
        self._buttons: list[QPushButton] = []
        self.setObjectName("inquiryDrawer")
        self.scrim = _Scrim(host)
        self.scrim.clicked.connect(self.close_drawer)
        self.scrim.hide()
        self.surface = _Surface(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.surface)
        lay = QVBoxLayout(self.surface)
        lay.setContentsMargins(_SHADOW + theme.SPACE_4, theme.SPACE_3,
                               theme.SPACE_4, theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)

        top = QHBoxLayout()
        self.number = QLabel()
        self.number.setFont(theme.font("CARD_TITLE", 700))
        top.addWidget(self.number)
        self.status_pill = QLabel()
        top.addWidget(self.status_pill)
        top.addStretch(1)
        self.prev_btn = C.icon_button("chevron-left", i18n.t("Previous inquiry"),
                                      on_click=lambda: self.step(-1))
        self.next_btn = C.icon_button("chevron-right", i18n.t("Next inquiry"),
                                      on_click=lambda: self.step(1))
        self.close_btn = C.icon_button("x", i18n.t("Close"),
                                       on_click=self.close_drawer)
        for b in (self.prev_btn, self.next_btn, self.close_btn):
            top.addWidget(b)
        lay.addLayout(top)
        self.customer = B.Elided("")
        self.customer.setFont(theme.font("CARD_TITLE", 700))
        lay.addWidget(self.customer)
        self.product = B.Elided("")
        self.product.setObjectName("meta")
        lay.addWidget(self.product)
        self.stepper_host = QWidget()
        self.stepper = C.FlowLayout(self.stepper_host, h_space=theme.SPACE_2,
                                    v_space=theme.SPACE_1)
        lay.addWidget(self.stepper_host)

        self.tabs = C.Tabs([i18n.t("Overview"), i18n.t("Emails"),
                            i18n.t("Quotation"), i18n.t("Files"),
                            i18n.t("Timeline")])
        self.tabs.changed.connect(self._tab_changed)
        lay.addWidget(self.tabs)
        self.pages = QStackedWidget()
        self._page_layouts = {}
        for key in self.TABS:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            inner = QWidget()
            inner.setObjectName("drawerPage")
            inner.setStyleSheet("QWidget#drawerPage { background: white; }")
            v = QVBoxLayout(inner)
            v.setContentsMargins(0, theme.SPACE_2, theme.SPACE_1, theme.SPACE_2)
            v.setSpacing(theme.SPACE_2)
            scroll.setWidget(inner)
            self.pages.addWidget(scroll)
            self._page_layouts[key] = v
        lay.addWidget(self.pages, 1)

        lay.addWidget(C.hairline())
        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE_1)
        self.foot_folder = C.button(i18n.t("Open folder"), "tertiary",
                                    icon_name="folder",
                                    on_click=lambda: self._act("folder"))
        self.foot_story = C.button(i18n.t("Whole story"), "tertiary",
                                   icon_name="list",
                                   on_click=lambda: self._go_tab("timeline"))
        self.foot_delete = C.button(i18n.t("Delete inquiry"), "destructive",
                                    icon_name="trash",
                                    on_click=lambda: self._act("delete"))
        foot.addWidget(self.foot_folder)
        foot.addWidget(self.foot_story)
        foot.addStretch(1)
        foot.addWidget(self.foot_delete)
        lay.addLayout(foot)

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self.close_drawer)
        self._esc = esc
        self._busy = QTimer(self)
        self._busy.setInterval(400)
        self._busy.timeout.connect(self._sync_busy)
        self._anim = None
        self.hide()

    # ── geometry ──────────────────────────────────────────────────────────
    def area(self) -> QRect:
        """Where the drawer may sit: over the dialog's view stack."""
        views = getattr(self.host, "views", None)
        if views is None or not views.isVisible():
            return QRect(0, 0, self.host.width(), self.host.height())
        rect = QRect(views.mapTo(self.host, QPoint(0, 0)), views.size())
        # From the view bar down, not the board's top: at the window's
        # minimum height (1090x640) the board area is ~416 px, and starting
        # below the view bar left the drawer's body ~75 px tall. The view
        # bar's controls act on the board, which the scrim covers anyway.
        bar = getattr(self.host, "view_bar", None)
        if bar is not None and bar.isVisible():
            top = bar.mapTo(self.host, QPoint(0, 0)).y()
            if 0 <= top < rect.top():
                rect.setTop(top)
        return rect

    def float_rect(self) -> QRect:
        a = self.area()
        fm = self.fontMetrics()
        want = fm.averageCharWidth() * 64 + _SHADOW
        floor = self.tabs.sizeHint().width() + _SHADOW + 2 * theme.SPACE_4 + 8
        # Keep clear of the strip the docked Ask-Lumi button can reach into
        # past the page padding, so it never sits on the drawer's scroll bar.
        reach = max(0, theme.LUMI_BUTTON_MAX + theme.LUMI_EDGE_GAP - theme.PAGE_PAD)
        width = min(a.width() - reach,
                    max(floor, min(want, int(a.width() * 0.6))))
        return QRect(a.right() - reach - width + 1, a.top(), width, a.height())

    def place(self):
        if not self.isVisible():
            return
        rect = self.float_rect()
        self.setGeometry(rect)
        a = self.area()
        self.scrim.setGeometry(QRect(a.left(), a.top(),
                                     max(0, rect.left() - a.left() + _SHADOW),
                                     a.height()))
        self.scrim.raise_()
        self.raise_()

    # ── open / close ──────────────────────────────────────────────────────
    def open_inquiry(self, no: str, order: list[str] | None = None,
                     tab: str = "overview"):
        self.no = no
        if order is not None:
            self.order = list(order)
        self.render()
        if not self.no:
            return
        self._go_tab(tab)
        was = self.isVisible()
        self.show()
        self.scrim.show()
        self.place()
        self.setFocus(Qt.OtherFocusReason)
        self._busy.start()
        if not was and _motion_ok():
            end = self.float_rect()
            self._anim = QPropertyAnimation(self, b"pos", self)
            self._anim.setDuration(_MS)
            self._anim.setStartValue(QPoint(end.left() + 60, end.top()))
            self._anim.setEndValue(end.topLeft())
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()

    def close_drawer(self):
        if not self.isVisible():
            return
        self.hide()
        self.scrim.hide()
        self._busy.stop()
        self.no = ""
        self.closed.emit()

    def step(self, delta: int):
        if self.no in self.order:
            i = (self.order.index(self.no) + delta) % len(self.order)
            self.open_inquiry(self.order[i])

    def row(self) -> dict | None:
        rows = getattr(self.host, "_register_rows", []) or []
        # self.no is the board's card key: the inquiry number, or a key of
        # its own for a row with no number or a shared one (review R9).
        return B.row_for_key(rows, self.no) if self.no else None

    # ── render ────────────────────────────────────────────────────────────
    def render(self):
        """Redraw for the live row; close with a line if it is gone."""
        row = self.row()
        if row is None:
            if self.isVisible():
                self.close_drawer()
                status = getattr(self.host, "status", None)
                if status is not None:
                    status.setText(i18n.t(
                        "That inquiry is no longer in the register."))
            self.no = ""
            return
        p = B.pipeline(self.host.cfg)
        stage, sub = CB.inquiry_stage(row, p)
        self._buttons = []
        self.number.setText(row.get("Inquiry no", ""))
        tone = B.STAGE_TONES.get(stage, "quoted")
        bg, ink = B._tone(tone)
        status = row.get("Status", "") or i18n.t("New")
        self.status_pill.setText(i18n.t(status).upper())
        self.status_pill.setStyleSheet(
            f"background: {bg}; color: {ink}; border-radius: 6px; "
            f"padding: 1px 6px; {theme.type_css('LABEL', ink)} font-weight: 700;")
        self.customer.setText(row.get("Customer", "") or row.get("Email", ""))
        prod = row.get("Product asked", "")
        if row.get("Quantity"):
            prod = f"{prod} · {row['Quantity']}"
        self.product.setText(prod)
        self.prev_btn.setEnabled(len(self.order) > 1)
        self.next_btn.setEnabled(len(self.order) > 1)
        self._render_stepper(row, stage, p)
        q_index = self.TABS.index("quotation")
        self.tabs._buttons[q_index].setText(B.word_text(p, "quote"))
        for key in self.TABS:
            _clear(self._page_layouts[key])
        self._overview(row, stage, sub, p)
        self._emails(row, p)
        self._quotation(row, p)
        self._files(row)
        self._timeline(row)
        for key in self.TABS:
            self._page_layouts[key].addStretch(1)
        self._sync_busy()

    def _render_stepper(self, row, stage, p):
        while self.stepper.count():
            item = self.stepper.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if stage == "lost":
            reason = row.get("Reason if lost", "")
            lab = QLabel("✕ " + i18n.t("Lost") + (f" — {reason}" if reason else ""))
            lab.setStyleSheet(f"color: {B._tone('lost')[1]}; font-weight: 700;")
            self.stepper.addWidget(lab)
            return
        stages = B.columns(p)
        idx = stages.index(stage) if stage in stages else -1
        for i, s in enumerate(stages):
            mark = "✓" if i < idx else ("●" if i == idx else str(i + 1))
            lab = QLabel(f"{mark} {B.stage_text(p, s)}"
                         + ("  —" if i < len(stages) - 1 else ""))
            weight = 700 if i == idx else 400
            colour = theme.NEUTRAL[900] if i <= idx else theme.NEUTRAL[500]
            lab.setStyleSheet(f"color: {colour}; font-weight: {weight};")
            lab.setObjectName(f"step_{s}")
            self.stepper.addWidget(lab)

    def _btn(self, key: str, p: dict, row: dict, variant: str = "secondary"):
        b = C.button(action_text(key, p, row), variant,
                     icon_name=ICONS.get(key, ""),
                     on_click=lambda _=False, k=key: self._act(k))
        b.setObjectName(b.objectName() or "secondaryBtn")
        b.setProperty("actionKey", key)
        self._buttons.append(b)
        return b

    def _overview(self, row, stage, sub, p):
        v = self._page_layouts["overview"]
        acts = drawer_actions(stage, sub, row, p, self._has_drawing(row))
        self.actions = acts
        if acts["warn"]:
            n = int(p.get("max_reminders") or 3)
            warn = QLabel(i18n.t("{n} reminders have gone. Call them.").replace(
                "{n}", str(n)))
            warn.setWordWrap(True)
            bg, ink = B._tone("lost")
            warn.setStyleSheet(f"background: {bg}; color: {ink}; padding: 6px 8px;"
                               " border-radius: 8px; font-weight: 600;")
            v.addWidget(warn)
        if acts["pricebox"]:
            v.addWidget(self._pricebox(row, p))
        if acts["think"]:
            v.addWidget(self._think(row))
        if acts["primary"]:
            v.addWidget(self._btn(acts["primary"], p, row, "primary"))
        if acts["secondary"]:
            grid = QGridLayout()
            grid.setSpacing(theme.SPACE_2)
            for i, key in enumerate(acts["secondary"]):
                b = self._btn(key, p, row)
                grid.addWidget(b, i // 2, i % 2)
            v.addLayout(grid)
        more = C.button(i18n.t("More"), "tertiary", icon_name="more-horizontal")
        menu = QMenu(more)
        for key in MORE_KEYS:
            menu.addAction(action_text(key, p, row),
                           lambda k=key: self._act(k))
        more.setMenu(menu)
        self.more_menu = menu
        mrow = QHBoxLayout()
        mrow.addWidget(more)
        mrow.addStretch(1)
        v.addLayout(mrow)
        v.addWidget(self._customer_section(row))
        v.addWidget(self._details_section(row, p))
        v.addWidget(self._read_section(row, p))
        tags_w = self._tags_section(row)
        if tags_w is not None:
            v.addWidget(tags_w)

    def _pricebox(self, row, p) -> QWidget:
        register = CB.get_register()
        box = QWidget()
        g = QHBoxLayout(box)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(theme.SPACE_2)
        money = lambda v: inquiry_config.format_money(v, p.get("currency", "₹"))  # noqa: E731
        ours = register.money(row.get("Quotation value", "") or 0)
        hist = register.price_history(row)
        ask = register.money(row.get(register.THEIR_ASK, "") or 0)
        q = B.word_text(p, "quote").lower()
        was = (i18n.t("was {list}").replace("{list}", ", ".join(money(h) for h in hist))
               if hist else "")
        lower = ""
        if ask and ours:
            lower = i18n.t("{n}% lower").replace(
                "{n}", str(round((1 - float(ask) / float(ours)) * 100)))
        policy = (self.host._settings().get("pricing_policy") or "").strip() \
            if hasattr(self.host, "_settings") else ""
        tiles = [
            (i18n.t("Your last {quote}").replace("{quote}", q),
             money(ours) if ours else "—", was, None),
            (i18n.t("They ask"), money(ask) if ask else "—", lower, None),
            (i18n.t("Your floor"), "—" if not policy else "", _clip(policy, 60),
             None if policy else "setup"),
        ]
        self.price_tiles = []
        for title, value, note, link in tiles:
            t = QFrame()
            t.setObjectName("drawerTile")
            t.setStyleSheet("QFrame#drawerTile { border: 1px solid %s;"
                            " border-radius: 10px; }" % theme.NEUTRAL[200])
            tl = QVBoxLayout(t)
            tl.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2,
                                  theme.SPACE_2)
            tl.setSpacing(0)
            tl.addWidget(C.label(title.upper(), "meta"))
            val = QLabel(value)
            val.setFont(theme.font("CARD_TITLE", 700))
            tl.addWidget(val)
            if note:
                tl.addWidget(C.label(note, "meta", wrap=True))
            if link:
                lb = C.button(i18n.t("set a pricing policy"), "tertiary",
                              small=True,
                              on_click=lambda: self.host.open_setup())
                tl.addWidget(lb)
            tl.addStretch(1)
            g.addWidget(t, 1)
            self.price_tiles.append((title, value, note))
        return box

    def _think(self, row) -> QWidget:
        from addons.inquiry import dialog as UI
        box = QFrame()
        box.setObjectName("drawerTile")
        box.setStyleSheet("QFrame#drawerTile { border: 1px solid %s;"
                          " border-radius: 10px; }" % theme.NEUTRAL[200])
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_2, theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2)
        lay.addWidget(C.label(i18n.t("Prism thinks").upper(), "meta"))
        r = QHBoxLayout()
        self.intent_box = QComboBox()
        for key in INTENTS:
            self.intent_box.addItem(i18n.t(UI.INTENT_LABELS[key]), key)
        reply = getattr(self.host, "board", None)
        entry = reply.latest_reply(row.get("Inquiry no", "")) if reply else None
        intent = (entry or {}).get("intent", "negotiating")
        i = self.intent_box.findData(intent)
        if i >= 0:
            self.intent_box.setCurrentIndex(i)
        r.addWidget(self.intent_box, 1)
        upd = C.button(i18n.t("Update the register"), "secondary",
                       icon_name="check",
                       on_click=lambda: self._act(
                           "update", intent=self.intent_box.currentData()))
        upd.setProperty("actionKey", "update")
        self._buttons.append(upd)
        r.addWidget(upd)
        lay.addLayout(r)
        return box

    def _section(self, title: str, lines: list) -> QWidget:
        box = QFrame()
        box.setObjectName("drawerTile")
        box.setStyleSheet("QFrame#drawerTile { border: 1px solid %s;"
                          " border-radius: 10px; }" % theme.NEUTRAL[200])
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                               theme.SPACE_2)
        lay.setSpacing(2)
        lay.addWidget(C.label(title.upper(), "meta"))
        for line in [x for x in lines if str(x or "").strip()]:
            lab = QLabel("• " + str(line))
            lab.setWordWrap(True)
            lay.addWidget(lab)
        return box

    def _customer_section(self, row: dict) -> QWidget:
        box = QFrame()
        box.setObjectName("drawerTile")
        box.setStyleSheet("QFrame#drawerTile { border: 1px solid %s;"
                          " border-radius: 10px; background: white; }" % theme.NEUTRAL[200])
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                               theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)

        head = QHBoxLayout()
        head.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("user", 14, theme.NEUTRAL[500]))
        head.addWidget(glyph)
        lbl = C.label(i18n.t("Customer").upper(), "meta")
        lbl.setFont(theme.font("LABEL", 600))
        head.addWidget(lbl)
        head.addStretch(1)
        lay.addLayout(head)

        who = QHBoxLayout()
        who.setSpacing(theme.SPACE_2)
        who.setAlignment(Qt.AlignTop)

        cu = row.get("Customer", "") or row.get("Email", "") or "—"
        initial = (cu[0] if cu else "?").upper()
        av = QLabel(initial)
        av.setFixedSize(36, 36)
        av.setAlignment(Qt.AlignCenter)
        av.setFont(theme.font("BODY", 700))
        av.setStyleSheet(f"background: {theme.NEUTRAL[100]}; color: {theme.NEUTRAL[700]}; "
                         f"border-radius: 18px;")
        who.addWidget(av)

        info = QVBoxLayout()
        info.setSpacing(2)
        name_lbl = QLabel(cu)
        name_lbl.setFont(theme.font("BODY", 700))
        name_lbl.setStyleSheet(f"color: {theme.NEUTRAL[900]};")
        name_lbl.setWordWrap(True)
        info.addWidget(name_lbl)

        ct = (row.get("Contact person") or "").strip()
        if ct:
            ct_lbl = QLabel(ct)
            ct_lbl.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 13px;")
            info.addWidget(ct_lbl)

        em = (row.get("Email") or "").strip()
        if em:
            em_lbl = QLabel(f"✉ {em}")
            em_lbl.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 13px;")
            info.addWidget(em_lbl)

        ph = (row.get("Phone") or "").strip()
        if ph:
            ph_lbl = QLabel(f"📞 {ph}")
            ph_lbl.setStyleSheet(f"color: {theme.NEUTRAL[600]}; font-size: 13px;")
            info.addWidget(ph_lbl)

        who.addLayout(info, 1)
        lay.addLayout(who)
        return box

    def _details_section(self, row: dict, p: dict) -> QWidget:
        register = CB.get_register()
        box = QFrame()
        box.setObjectName("drawerTile")
        box.setStyleSheet("QFrame#drawerTile { border: 1px solid %s;"
                          " border-radius: 10px; background: white; }" % theme.NEUTRAL[200])
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                               theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)

        head = QHBoxLayout()
        head.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("file-text", 14, theme.NEUTRAL[500]))
        head.addWidget(glyph)
        lbl = C.label(i18n.t("Details").upper(), "meta")
        lbl.setFont(theme.font("LABEL", 600))
        head.addWidget(lbl)
        head.addStretch(1)

        edit_btn = C.icon_button("edit", i18n.t("Edit details"),
                                 on_click=lambda: self._act("edit"))
        edit_btn.setToolTip(i18n.t("Edit details"))
        head.addWidget(edit_btn)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setHorizontalSpacing(theme.SPACE_2)
        grid.setVerticalSpacing(4)
        grid.setColumnMinimumWidth(0, 110)

        d = row.get("Date received", "")
        t = row.get("Time received", "")
        when = (f"{d}, {t}" if t else d) if d else "—"

        items = [
            (i18n.t("Inquiry no"), row.get("Inquiry no", "")),
            (i18n.t("Received"), when),
            (i18n.t("What they want"), row.get("Product asked", "") or "—"),
            (i18n.t("Quantity"), row.get("Quantity") or "—"),
        ]
        if row.get("Quotation no"):
            q_word = B.word_text(p, "quote")
            q_val = inquiry_config.format_money(row.get("Quotation value", ""), p.get("currency", "₹"))
            items.append((q_word, f"{register.quote_label(row)} · {q_val}"))
        if row.get("PO number"):
            po_word = B.word_text(p, "po")
            items.append((po_word, row.get("PO number", "")))
        if row.get("Reason if lost"):
            items.append((i18n.t("Why lost"), row.get("Reason if lost", "")))

        for r_idx, (dt_text, dd_text) in enumerate(items):
            dt = QLabel(dt_text)
            dt.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 13px;")
            dd = QLabel(str(dd_text))
            dd.setWordWrap(True)
            dd.setStyleSheet(f"color: {theme.NEUTRAL[900]}; font-size: 13px; font-weight: 500;")
            grid.addWidget(dt, r_idx, 0, Qt.AlignTop)
            grid.addWidget(dd, r_idx, 1, Qt.AlignTop)

        lay.addLayout(grid)
        return box

    def _read_section(self, row: dict, p: dict) -> QWidget:
        register = CB.get_register()
        box = QFrame()
        box.setObjectName("drawerRead")
        box.setStyleSheet("QFrame#drawerRead { border: 1px solid %s;"
                          " border-radius: 10px; background: %s; }"
                          % (theme.NEUTRAL[200], theme.NEUTRAL[100]))
        lay = QVBoxLayout(box)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                               theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)

        head = QHBoxLayout()
        head.setSpacing(6)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("zap", 14, theme.NEUTRAL[500]))
        head.addWidget(glyph)
        lbl = C.label(i18n.t("What Prism read").upper(), "meta")
        lbl.setFont(theme.font("LABEL", 600))
        head.addWidget(lbl)
        head.addStretch(1)

        jump_btn = C.button(i18n.t("Full mail →"), "tertiary", small=True,
                            on_click=lambda: self._go_tab("emails"))
        head.addWidget(jump_btn)
        lay.addLayout(head)

        read = []
        if row.get("Product asked"):
            read.append(row["Product asked"] + (f" — {row['Quantity']}"
                                                if row.get("Quantity") else ""))
        read += [n.strip() for n in (row.get("Notes") or "").split(" | ")
                 if n.strip()]
        if row.get("Quotation no"):
            read.append(f"{register.quote_label(row)}: "
                        f"{inquiry_config.format_money(row.get('Quotation value', ''), p.get('currency', '₹'))}"
                        f" — {row.get('Quotation date', '')}")

        for line in read:
            lab = QLabel("• " + str(line))
            lab.setWordWrap(True)
            lab.setStyleSheet(f"color: {theme.NEUTRAL[800]}; font-size: 13.5px;")
            lay.addWidget(lab)

        src = QLabel(i18n.t("From Prism's own reading when the mail arrived — "
                            "opening this costs no AI call."))
        src.setWordWrap(True)
        src.setStyleSheet(f"color: {theme.NEUTRAL[500]}; font-size: 12px; margin-top: 4px;")
        lay.addWidget(src)
        return box

    def _tags_section(self, row: dict) -> QWidget | None:
        prod = row.get("Product asked", "")
        qty = (row.get("Quantity") or "").strip()
        tags = []
        if prod:
            for w in re.split(r"[ ,()]+", prod):
                if re.match(r"^(SS|\d{2,}|spring|locker|cabinet|pass|trolley|cubicle|website|rack|air)", w, re.I):
                    if w not in tags and len(tags) < 4:
                        tags.append(w)
        if qty and qty not in tags:
            tags.append(qty)
        if not tags:
            return None

        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, theme.SPACE_1, 0, theme.SPACE_1)
        lay.setSpacing(theme.SPACE_1)
        glyph = QLabel()
        glyph.setPixmap(icons.pixmap("tag", 14, theme.NEUTRAL[400]))
        lay.addWidget(glyph)
        for t in tags:
            chip = QLabel(t)
            chip.setStyleSheet(
                f"background: {theme.NEUTRAL[100]}; color: {theme.NEUTRAL[700]}; "
                f"border-radius: 6px; padding: 2px 7px; font-size: 12px; font-weight: 500;")
            lay.addWidget(chip)
        lay.addStretch(1)
        return box

    def _emails(self, row, p):
        v = self._page_layouts["emails"]
        no = row.get("Inquiry no", "")
        root = self.host._root() if hasattr(self.host, "_root") else ""
        mails = []
        arrived = None
        try:
            arrived = self.host._arrived_for(row)
        except Exception:                               # noqa: BLE001
            arrived = None
        if arrived:
            mails.append(("in", arrived.get("from_name") or arrived.get(
                "from_addr", ""), arrived.get("subject", ""),
                arrived.get("body", ""), arrived.get("date", "")))
        if root:
            try:
                wl = CB.get_worklist()
                data = wl.load(root)
                for kind in ("replies", "orders"):
                    for e in wl.history(data, kind):
                        if e.get("inquiry_no") == no:
                            mails.append(("in", e.get("from_name") or e.get(
                                "from_addr", ""), e.get("subject", ""),
                                e.get("body", ""), e.get("date", "")))
                for e in wl.sent_for(data, no):
                    mails.append(("out", i18n.t("You"), e.get("subject", ""),
                                  i18n.t("Full text in Timeline"),
                                  e.get("date", "")))
            except Exception:                           # noqa: BLE001
                pass
        if not mails:
            v.addWidget(C.label(i18n.t("No mail stored for this inquiry yet."),
                                "meta", wrap=True))
        for direction, who, subject, body, when in sorted(
                mails, key=lambda m: str(m[4] or "")):
            box = QFrame()
            box.setObjectName("drawerMail")
            box.setStyleSheet("QFrame#drawerMail { border: 1px solid %s;"
                              " border-radius: 10px; background: %s; }"
                              % (theme.NEUTRAL[200], theme.NEUTRAL[100]
                                 if direction == "out" else "#ffffff"))
            bl = QVBoxLayout(box)
            bl.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                                  theme.SPACE_2)
            bl.setSpacing(2)
            head = QHBoxLayout()
            arrow = "➤ " if direction == "out" else "✉ "
            hl = QLabel(arrow + str(who or ""))
            hl.setFont(theme.font("SUPPORT", 700))
            head.addWidget(hl, 1)
            head.addWidget(C.label(str(when or "")[:10], "meta"))
            bl.addLayout(head)
            bl.addWidget(C.label(str(subject or ""), "meta", wrap=True))
            text = QLabel(_clip(body, 600))
            text.setWordWrap(True)
            bl.addWidget(text)
            v.addWidget(box)

    def _quotation(self, row, p):
        v = self._page_layouts["quotation"]
        register = CB.get_register()
        money = lambda x: inquiry_config.format_money(x, p.get("currency", "₹"))  # noqa: E731
        if not row.get("Quotation no"):
            v.addWidget(C.label(i18n.t("No {quote} has been sent for this "
                                       "inquiry yet.").replace(
                "{quote}", B.word_text(p, "quote").lower()), "meta", wrap=True))
            return
        v.addWidget(self._section(register.quote_label(row), [
            money(row.get("Quotation value", "")),
            row.get("Quotation date", "")]))
        try:
            from addons.inquiry import dialog as UI
            quote = UI._read_sent_quotation(row)
        except Exception:                               # noqa: BLE001
            quote = None
        if quote is not None:
            v.addWidget(self._section(i18n.t("Lines"), [
                f"{l.description} — {l.quantity} {l.unit} × {money(l.rate)}"
                for l in quote.lines]))
        else:
            v.addWidget(C.label(i18n.t(
                "The copy in the folder is the record."), "meta", wrap=True))
        hist = register.price_history(row)
        if hist:
            lines = [(i18n.t("First") if i == 0 else i18n.t("Rev {n}").replace(
                "{n}", str(i))) + f": {money(h)}" for i, h in enumerate(hist)]
            lines.append(i18n.t("Now") + f": {money(row.get('Quotation value', ''))}")
            ask = row.get(register.THEIR_ASK, "")
            if ask:
                lines.append(i18n.t("They ask") + f": {money(ask)}")
            v.addWidget(self._section(i18n.t("Price history"), lines))
        pdf = self._quote_pdf(row)
        if pdf:
            v.addWidget(C.button(i18n.t("Open the PDF"), "secondary",
                                 icon_name="file",
                                 on_click=lambda: _open_file(pdf)))

    def _quote_pdf(self, row) -> str:
        register = CB.get_register()
        folder = row.get("Folder", "")
        no = row.get("Quotation no", "")
        latest = max(register.revision_of(row),
                     register.revision_on_disk(folder, no))
        for rev in range(latest, -1, -1):
            path = os.path.join(folder, register.quote_file_name(no, rev))
            if folder and os.path.exists(path):
                return path
        return ""

    def _files(self, row):
        v = self._page_layouts["files"]
        from addons.inquiry import documents
        folder = row.get("Folder", "")
        try:
            names = sorted(os.listdir(folder)) if folder else []
        except OSError:
            names = []
        names = [n for n in names if os.path.isfile(os.path.join(folder, n))
                 and n != "history.txt"]
        if not names:
            v.addWidget(C.label(i18n.t("No files in this inquiry's folder yet."),
                                "meta", wrap=True))
        for name in names:
            r = QHBoxLayout()
            lab = QLabel(name)
            lab.setWordWrap(True)
            r.addWidget(lab, 1)
            r.addWidget(C.label(i18n.t("Prism wrote this") if documents.is_ours(name)
                                else i18n.t("From the customer"), "meta"))
            path = os.path.join(folder, name)
            r.addWidget(C.icon_button("external", i18n.t("Open"),
                                      on_click=lambda _=False, x=path:
                                      self._view(x)))
            v.addLayout(r)
        self.file_count = len(names)

    def _view(self, path: str):
        hook = getattr(self.host, "view_attachment", None)
        if hook is not None:
            hook(path)
        else:
            _open_file(path)

    def _timeline(self, row):
        v = self._page_layouts["timeline"]
        folder = row.get("Folder", "")
        try:
            entries = CB.get_history().entries(folder) if folder else []
        except Exception:                               # noqa: BLE001
            entries = []
        if not entries:
            v.addWidget(C.label(i18n.t("Nothing recorded yet."), "meta",
                                wrap=True))
        for e in entries:
            lab = QLabel(f"<b>{B._esc(e.get('event', ''))}</b><br>"
                         f"<span style='color:{theme.NEUTRAL[500]}'>"
                         f"{B._esc(e.get('when', ''))}"
                         f"{' · ' + B._esc(e.get('subject', '')) if e.get('subject') else ''}"
                         f"</span>")
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.RichText)
            v.addWidget(lab)

    def _has_drawing(self, row) -> bool:
        fn = getattr(self.host, "_has_drawing", None)
        try:
            return bool(fn(row)) if fn else False
        except Exception:                               # noqa: BLE001
            return False

    # ── tabs and actions ──────────────────────────────────────────────────
    def _tab_changed(self, index: int):
        self.pages.setCurrentIndex(index)

    def _go_tab(self, key: str):
        i = self.TABS.index(key) if key in self.TABS else 0
        self.tabs.set_current(i)
        self.pages.setCurrentIndex(i)

    def _act(self, key: str, **kw):
        row = self.row()
        if row is None:
            self.render()
            return
        self.host.act_on(row, key, **kw)
        if self.isVisible():
            self.render()

    def busy(self) -> bool:
        for name in ("_send_worker", "_po_worker", "_draft_worker"):
            w = getattr(self.host, name, None)
            try:
                if w is not None and w.isRunning():
                    return True
            except RuntimeError:
                continue
        return False

    def _sync_busy(self):
        busy = self.busy()
        for b in self._buttons:
            try:
                b.setEnabled(not busy)
            except RuntimeError:
                pass


def _clip(text, n):
    return B._clip(text, n)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            _clear(item.layout())


def _open_file(path: str):
    import paths
    paths.open_file(path)
