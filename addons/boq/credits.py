"""Credits in plain words for BOQ's AI steps (stdlib only).

The server counts in millicredits (1,000 mc = 1 credit). A person sees
"about 2 credits", or "less than 1 credit", never a raw number. These helpers
only word numbers they are given; the estimate itself comes from the server
(core/ai_client.estimate) and the charge from what the usage chip last heard.
"""
from __future__ import annotations

import math


def credits_words(mc) -> str:
    """'about 2 credits' for a typical cost in millicredits; '' when unknown."""
    try:
        mc = int(mc)
    except (TypeError, ValueError):
        return ""
    if mc <= 0:
        return ""
    if mc < 1000:
        return "less than 1 credit"
    n = math.ceil(mc / 1000)
    return f"about {n} credit" + ("" if n == 1 else "s")


def charge_words(before, after, run_cost=None) -> str:
    """What a step actually cost, from the balance before and after (credits),
    or the run's own cost when the balance did not move or is unknown."""
    try:
        spent = int(before) - int(after)
    except (TypeError, ValueError):
        spent = 0
    if spent <= 0 and run_cost:
        spent = int(run_cost)
    if spent <= 0:
        return ""
    return f"{spent} credit" + ("" if spent == 1 else "s")
