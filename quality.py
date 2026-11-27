"""Best / Balanced / Fast: what the customer chooses, and what it means.

Customers never see a model list. They see three words, plus "Auto" (the
default). Auto sends nothing: the server starts on the best quality the plan
allows and steps down as the weekly bar fills. A customer may pin a LOWER
quality than that, never a higher one than the plan's top (the server clamps
too; the app just never offers it).

The words, the plan's ceiling and the dates are here so the Settings card, the
run summary and the notice all say the same thing.
"""
from __future__ import annotations

from datetime import datetime

import i18n

LEVELS = ("fast", "balanced", "best")           # worst to best
AUTO = "auto"
_WORDS = {"best": "Best", "balanced": "Balanced", "fast": "Fast"}
_BLURB = {
    AUTO: "Prism starts on the best quality your plan allows and lowers it "
          "as your week fills up.",
    "best": "The strongest AI your plan has, every time, until your week runs out.",
    "balanced": "A good middle: strong results that make your week last longer.",
    "fast": "The quickest and lightest. Your week lasts the longest.",
}


def word(level: str) -> str:
    return i18n.t(_WORDS.get(str(level or "").lower(), ""))


def blurb(level: str) -> str:
    return i18n.t(_BLURB.get(level, ""))


def pinned(cfg: dict) -> str:
    """"auto" or a level, from the saved setting."""
    v = str((cfg or {}).get("quality") or AUTO).lower()
    return v if v in LEVELS else AUTO


def plan_max(status: dict | None) -> str:
    """The best quality this plan allows. The server says it on its status
    answer; unknown means no limit is known, and the server clamps anyway."""
    status = status or {}
    v = str(status.get("max_level")
            or (status.get("plan") or {}).get("max_level") or "best").lower()
    return v if v in LEVELS else "best"


def allowed(level: str, status: dict | None) -> bool:
    return LEVELS.index(level) <= LEVELS.index(plan_max(status))


def effective(cfg: dict, status: dict | None = None) -> str | None:
    """What the engine is told: None for Auto, else the pin, never above the
    plan's top quality."""
    pin = pinned(cfg)
    if pin == AUTO:
        return None
    top = plan_max(status)
    return pin if LEVELS.index(pin) <= LEVELS.index(top) else top


def apply(cfg: dict, status: dict | None = None) -> None:
    """Tell the engine the pin. Safe to call often."""
    import core_bridge as CB
    CB.ai_client.set_level(effective(cfg, status))


def weekday(epoch) -> str:
    """"Monday" for the moment the week resets; "" when not known."""
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%A")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def resets_words(epoch) -> str:
    day = weekday(epoch)
    if not day:
        return i18n.t("Resets when your week ends.")
    return i18n.t("Resets {day}.").format(day=i18n.t(day))


def stepdown_notice(level: str, epoch=None) -> str:
    """The one plain sentence shown when the quality steps down."""
    return i18n.t("Quality moved to {level} to make your week last. {resets}"
                  ).format(level=word(level), resets=resets_words(epoch))


def run_line(summary: dict) -> str:
    """"Made with Balanced quality (model-name)" for the run summary."""
    w = word((summary or {}).get("level_used", ""))
    model = (summary or {}).get("model") or ""
    if not w:
        return ""
    if model:
        return i18n.t("Made with {level} quality ({model})").format(
            level=w, model=model)
    return i18n.t("Made with {level} quality").format(level=w)
