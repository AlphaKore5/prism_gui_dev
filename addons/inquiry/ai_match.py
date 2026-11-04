"""item 56 (4 Nov 2026) -- matching a free-text, no-catalogue-code inquiry
against the rate list by AI, in place of core.quoting's own local
word-overlap scoring (find_free_text_requests(), item 55).

The owner's own words, asked for in so many words: "replace this with the
AI as i want this accurate... its ok if the token usage is more but the
answer should be accurate... no ask AI buttons needed." So this always
runs (no manual trigger) whenever find_requests() -- the exact-code path,
untouched by any of this -- finds fewer than two lines, and it is given
the WHOLE inquiry text and the WHOLE rate list, not a trimmed-down guess
at either.

What this module will NOT do, the same rule core.boq_price's own
docstring states for pricing a BOQ: no number of record comes from the
AI. DeepSeek is only ever asked to CHOOSE a catalogue CODE and read back
the QUANTITY the customer wrote next to it -- the description, the unit
and the rate that actually go into the quotation are always read back out
of the real, local RateItem the chosen code points to. A code DeepSeek
invents (not a code genuinely on the list) is never priced -- see
parse_response()'s own lookup, which can only ever return a RateItem this
process already had.
"""
from __future__ import annotations

import json
import re

import core_bridge as CB

MODEL = "deepseek/deepseek-v4.1-flash"

_PROMPT = """A customer sent an inquiry. Read it and match EVERY distinct
product they asked for against the catalogue below, as closely as the
wording allows.

Return ONLY a JSON object, no explanation, no markdown fences:
{{
  "items": [
    {{"requested": "the customer's own words for this item",
      "quantity": <number, exactly what the customer wrote, no unit>,
      "code": "<the single best matching code from the catalogue below,
               copied EXACTLY as it appears there>",
      "confidence": "high" | "low"}}
  ]
}}

Rules:
- One entry per DISTINCT product the customer asked for -- a list of 8
  items is 8 entries, never merged into one.
- "code" must be copied character-for-character from the catalogue below.
  If genuinely nothing in the catalogue is a reasonable match for an item,
  set "code" to null and "confidence" to "low" -- never invent a code or
  pick an unrelated one just to fill the field.
- "quantity" is only ever the number the customer actually wrote next to
  that item. Never invent one, never split a quantity across items.
- "confidence" is "high" only when you are genuinely sure which catalogue
  row this is -- a shared generic word ("locker", "SS") is not enough on
  its own if several rows share it.

CATALOGUE (code: description (unit)):
{catalogue}

INQUIRY:
{inquiry}
"""


def _catalogue_block(items: list) -> str:
    return "\n".join(f"{it.code}: {it.description} ({it.unit})"
                     for it in items if it.code)


def build_prompt(inquiry_text: str, items: list) -> str:
    return _PROMPT.format(catalogue=_catalogue_block(items),
                          inquiry=(inquiry_text or "").strip()[:6000])


def _json_from(text: str) -> dict:
    raw = re.sub(r"^```[a-z]*\s*|\s*```$", "", (text or "").strip(),
                flags=re.I | re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_response(text: str, items: list) -> tuple[list, list]:
    """(requests, unmatched) -- same shape core.quoting.
    find_free_text_requests() returns, so the dialog treats an AI match
    and a local one identically. `code` is looked up against the REAL
    local rate list -- a code DeepSeek names that isn't actually on it
    (hallucinated, or genuinely absent) is never turned into a Request;
    its own "requested" text goes to `unmatched` instead."""
    quoting = CB.get_quoting()
    by_code = {it.code: it for it in items if it.code}
    data = _json_from(text)
    entries = data.get("items") if isinstance(data, dict) else None
    requests: list = []
    unmatched: list = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        requested = str(entry.get("requested") or "").strip()
        code = str(entry.get("code") or "").strip()
        item = by_code.get(code)
        qty = quoting.to_decimal(entry.get("quantity"))
        if item is None or qty <= 0:
            if requested:
                unmatched.append(requested)
            continue
        requests.append(quoting.Request(
            item, qty, evidence=requested,
            # item 56: "we still have to keep check this" -- the owner's
            # own words. Every AI-matched row is flagged for a person to
            # check regardless of DeepSeek's own reported confidence;
            # "confidence" is read only for the tooltip, never to skip
            # the highlight.
            match_confident=False))
    return requests, unmatched


def match(api_key: str, inquiry_text: str, items: list) -> tuple[list, list]:
    """One DeepSeek completion, matching every item in `inquiry_text`
    against `items`. Raises RuntimeError with the real reason on failure
    (no key, a network error, a rejected key) -- caught by
    addons/inquiry/workers.py:AIMatchWorker, off the GUI thread."""
    text = CB.openrouter.openrouter_chat(
        api_key, MODEL, build_prompt(inquiry_text, items), temperature=0.0)
    return parse_response(text, items)
