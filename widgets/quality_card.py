"""Settings > Usage: the quality choice and the weekly bar.

Best / Balanced / Fast (plus Auto, the default), a percent bar for the week with
its reset day, "Quality now: Balanced", the one plain sentence when the server
has stepped the quality down, and at 100% the plain choice between asking
Alphakore for more and a simple Reel. Also the Reel style (full / simple / from my pictures).

Every control that is off says why, in its tooltip and in a line under the row.
Nothing here touches the network: the page hands it the server's usage answer
(`bar_pct`, `week_resets_at`, `quality_now`) through set_usage().
"""
from __future__ import annotations

from urllib.parse import quote

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QWidget

import ai_server
import app_meta
import i18n
import quality
import theme
from widgets import controls as C

REEL_STYLES = ("full", "simple", "own")


def reel_style(cfg: dict) -> str:
    v = str((cfg or {}).get("reel_style") or "full")
    return v if v in REEL_STYLES else "full"


class QualityCard(C.Card):
    changed = Signal()

    def __init__(self, cfg: dict, parent=None):
        super().__init__("soft", parent=parent)
        self.cfg = cfg
        self.usage: dict = {}
        col = self.body((theme.CARD_PAD,) * 4, theme.SPACE_2)
        col.addWidget(C.kicker(i18n.t("Quality")))
        self.blurb = C.label("", level="SUPPORT", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.blurb)

        self.chips = C.FilterChips(
            [(quality.AUTO, i18n.t("Auto")),
             ("best", quality.word("best")),
             ("balanced", quality.word("balanced")),
             ("fast", quality.word("fast"))], quality.pinned(cfg))
        self.chips.changed.connect(self._pick_quality)
        row = QHBoxLayout()
        row.addWidget(self.chips)
        row.addStretch(1)
        col.addLayout(row)
        self.why = C.label("", level="META", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.why)

        col.addWidget(C.hairline())
        self.week = C.label("", level="SUPPORT", colour=theme.TEXT)
        self.bar = C.ProgressBar(0.0)
        self.resets = C.label("", level="META", colour=theme.NEUTRAL[600])
        self.now = C.label("", level="SUPPORT", colour=theme.TEXT)
        self.notice = C.label("", level="SUPPORT", colour=theme.WARN_INK, wrap=True)
        for w in (self.week, self.bar, self.resets, self.now, self.notice):
            col.addWidget(w)

        self.full = QWidget()
        fcol = QHBoxLayout(self.full)
        fcol.setContentsMargins(0, 0, 0, 0)
        self.full_text = C.label("", level="SUPPORT", colour=theme.ERR_INK, wrap=True)
        fwrap = C.Card("soft")
        fbody = fwrap.body((theme.CARD_PAD,) * 4, theme.SPACE_2)
        fbody.addWidget(self.full_text)
        btns = QHBoxLayout()
        self.topup_btn = C.button(i18n.t("Ask Alphakore for more"), "secondary", small=True,
                                  on_click=self._ask_topup)
        self.simple_btn = C.button(i18n.t("Make Reels simple"), "secondary", small=True,
                                   on_click=self._choose_simple)
        btns.addWidget(self.topup_btn)
        btns.addWidget(self.simple_btn)
        btns.addStretch(1)
        fbody.addLayout(btns)
        fcol.addWidget(fwrap)
        col.addWidget(self.full)

        col.addWidget(C.hairline())
        col.addWidget(C.label(i18n.t("Reel style"), level="SUPPORT", colour=theme.TEXT))
        self.reels = C.FilterChips(
            [("full", i18n.t("Full design")), ("simple", i18n.t("Simple Reel")),
             ("own", i18n.t("From my pictures"))], reel_style(cfg))
        self.reels.changed.connect(self._pick_reel)
        rrow = QHBoxLayout()
        rrow.addWidget(self.reels)
        rrow.addStretch(1)
        col.addLayout(rrow)
        self.reel_note = C.label("", level="META", colour=theme.NEUTRAL[600], wrap=True)
        col.addWidget(self.reel_note)
        self.refresh_state()

    # ── data in ──────────────────────────────────────────────────────────
    def set_usage(self, data: dict | None):
        self.usage = dict(data or {})
        ai_server.note_week(self.usage.get("week_resets_at"))
        self.refresh_state()

    def refresh_state(self):
        status = ai_server.status_now()
        live = ai_server.quality_state()
        on = ai_server.active()
        top = quality.plan_max(status)

        # What may be chosen, and why not when it may not.
        for level in quality.LEVELS:
            btn = self.chips._buttons[level]
            ok = on and quality.allowed(level, status)
            btn.setEnabled(ok)
            btn.setToolTip("" if ok else (
                i18n.t("Quality is set by your Prism plan once AI runs through it.")
                if not on else i18n.t(
                    "Your plan's top quality is {level}.").format(
                    level=quality.word(top))))
        self.chips._buttons[quality.AUTO].setEnabled(on)
        self.chips._buttons[quality.AUTO].setToolTip(
            "" if on else i18n.t(
                "Quality is set by your Prism plan once AI runs through it."))
        if not on:
            self.why.setText(i18n.t(
                "These are off because AI is not running through your Prism plan."))
        elif top != "best":
            self.why.setText(i18n.t(
                "Your plan's top quality is {level}, so higher choices are off."
            ).format(level=quality.word(top)))
        else:
            self.why.setText("")
        self.why.setVisible(bool(self.why.text()))
        pin = quality.pinned(self.cfg)
        self.chips.set_current(pin)
        self.blurb.setText(quality.blurb(pin))

        # The week.
        pct = self.usage.get("bar_pct", status.get("bar_pct", live.get("bar_pct")))
        resets = self.usage.get("week_resets_at") or status.get("week_resets_at")
        # quality_now is null when the bar is full: there is no quality then.
        now = str(self.usage.get("quality_now") or (
            "" if pct is not None and float(pct) >= 100 else
            status.get("quality_now") or live.get("level_used")) or "").lower()
        if pct is None:
            self.week.setText(i18n.t("Your week: not shown yet"))
            self.bar.set_fraction(0.0)
        else:
            pct = max(0.0, min(100.0, float(pct)))
            self.week.setText(i18n.t("{pct}% of your week used").format(
                pct=f"{pct:.0f}"))
            self.bar.set_fraction(pct / 100.0)
        self.resets.setText(quality.resets_words(resets) if resets else "")
        self.resets.setVisible(bool(resets))
        self.now.setText(i18n.t("Quality now: {level}").format(
            level=quality.word(now)) if now in quality.LEVELS else "")
        self.now.setVisible(now in quality.LEVELS)
        # The server says whether the week lowered it; the account's default
        # being under the plan's top is not a step-down. A server that does not
        # say is judged as before, and only when there is a week to fill.
        if "stepped_down" in self.usage:
            lowered = bool(self.usage["stepped_down"])
        else:
            lowered = bool(live.get("stepped_down")) or (
                pct is not None and now in quality.LEVELS
                and quality.LEVELS.index(now) < quality.LEVELS.index(top))
        stepped = pin == quality.AUTO and now in quality.LEVELS and lowered
        self.notice.setText(quality.stepdown_notice(now, resets) if stepped else "")
        self.notice.setVisible(bool(self.notice.text()))

        # 100%: the plain choice.
        full = pct is not None and pct >= 100
        self.full.setVisible(full)
        if full:
            self.full_text.setText(i18n.t(
                "You have used this week's AI allowance. {resets} Nothing was "
                "charged. Until then you can ask Alphakore for more, or make "
                "Reels the simple way, which uses no AI.").format(resets=quality.resets_words(resets)))
        self.simple_btn.setEnabled(reel_style(self.cfg) != "simple")
        self.simple_btn.setToolTip(
            "" if reel_style(self.cfg) != "simple"
            else i18n.t("Your Reels are already simple."))

        # Reel style.
        self.reels.set_current(reel_style(self.cfg))
        self.reel_note.setText({
            "full": i18n.t("A full Reel: Prism writes it, draws the pictures and "
                           "directs the design."),
            "simple": i18n.t("A simple Reel is built from your script and pictures "
                             "with no AI art direction. It costs far less."),
            "own": i18n.t("Prism makes no pictures. It uses the pictures you attach; "
                          "with none attached, the Reel is type and colour only."),
        }[reel_style(self.cfg)])

    # ── choices out ──────────────────────────────────────────────────────
    def _save(self):
        import core_bridge as CB
        CB.config.save(self.cfg)
        quality.apply(self.cfg, ai_server.status_now())
        self.changed.emit()
        self.refresh_state()

    def _pick_quality(self, value: str):
        self.cfg["quality"] = value
        self._save()

    def _pick_reel(self, value: str):
        self.cfg["reel_style"] = value
        self._save()

    def _choose_simple(self):
        self.cfg["reel_style"] = "simple"
        self._save()

    def _ask_topup(self):
        subject = quote("More AI for my Prism week")
        body = quote("Hello Alphakore team,\n\nI have used this week's AI allowance "
                     "and would like more. Please let me know the options.\n")
        QDesktopServices.openUrl(QUrl(
            f"mailto:{app_meta.SUPPORT_EMAIL}?subject={subject}&body={body}"))
