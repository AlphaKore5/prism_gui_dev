"""Reading Email inquiry automation's settings out of the config dict.

Pure functions over a plain dict. No Qt, no engine, no widgets -- which is
the point: they were trapped inside a 1,100-line Qt setup dialog, and
everything that needed to ask "is the mailbox set up?" had to import that
dialog to find out.

That inverted the layering in two places that matter:

  dashboard_data.py           a root DATA module, feeding Home, importing
                              a dialog
  the inquiry panel           a widget importing a dialog, six times over

Both worked only because every one of those eight imports is inside a
function rather than at module scope -- a deferred import is a circular
dependency you have agreed not to look at. It also meant Email inquiry automation
could not be extracted into an add-on without dragging Home along with it,
since Home reads the register through dashboard_data.

The dialog now imports these from here and re-exports them, so nothing that
already said `from addons.inquiry.setup import is_ready` breaks.

────────────────────────────────────────────────────────────────────────────
Several mailboxes, one register
────────────────────────────────────────────────────────────────────────────
`cfg["inquiry"]["accounts"]` is a list, and each entry carries its own
`state` (the read bookmark), because two mailboxes sharing one bookmark
would skip or re-import each other's mail. The old single-mailbox keys --
`account` and `state` -- are still written, mirroring the first entry, so a
config saved by this version opens cleanly in the previous one.
`accounts_of()` is the one reader that understands both.
"""
from __future__ import annotations

import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

import paths
DEFAULT_FOLDER = paths.user_folder("Prism Inquiries")

# ── the working screen's tabs ────────────────────────────────────────────
# Here rather than in addons/inquiry/dialog.py because addons/inquiry/panel.py
# needs them and was importing a 4,313-line dialog AT MODULE SCOPE to get
# them -- the one widget->dialog import in the tree that is not a deferred
# "open this modal", and therefore a real load-order dependency rather than a
# navigational one.
#
# Still translated at render time, never here. `TABS` is in
# devtools/extract_strings.py's COPY_TABLES and this file is scanned, so the
# labels remain translatable exactly as they were.
TABS = [
    ("to_quote", "1 · To quote"),
    ("waiting", "2 · No answer yet"),
    ("replies", "3 · They answered"),
    ("orders", "4 · Order came"),
    ("register", "5 · All inquiries"),
    ("arrived", "6 · All mail"),
]
TAB_INDEX = {key: index for index, (key, _label) in enumerate(TABS)}
# Tabs whose title carries a live count. The reference tabs do not: "All
# inquiries (312)" is not a number anybody acts on.
COUNTED_TABS = ("to_quote", "waiting", "replies", "orders")


def settings_of(cfg: dict) -> dict:
    return dict(cfg.get("inquiry") or {})


def accounts_of(cfg: dict) -> list[dict]:
    """Every configured mailbox, in the order they were added.

    Reads the list form first; a config from before mailboxes were a list is
    wrapped on the way out — the legacy `account` becomes entry one and
    brings the legacy `state` bookmark with it, so an existing customer's
    first multi-mailbox check carries on from where their last single-mailbox
    check stopped instead of re-importing a month of mail.

    Copies, not references: callers edit these freely and save what they
    mean to save.
    """
    s = settings_of(cfg)
    accounts = [dict(a) for a in (s.get("accounts") or []) if a]
    if not accounts and s.get("account"):
        legacy = dict(s["account"])
        legacy["state"] = dict(s.get("state") or {})
        accounts = [legacy]
    return accounts


def is_complete(account: dict) -> bool:
    """Enough of a mailbox to attempt a connection.

    Named `_complete` while it lived in the dialog, and imported under that
    name from addons/inquiry/panel.py anyway -- a private name with an
    outside caller is just a public name nobody renamed. `_complete` stays
    available as an alias so no existing import breaks.
    """
    return bool(account.get("address") and account.get("password")
                and account.get("host"))


def is_active(account: dict) -> bool:
    """Whether Prism reads this mailbox.

    Absent means active, so a config written before there was a switch reads
    as "keep checking it". The other reading -- a missing key meaning off --
    would silently stop an existing customer's mail being read, and they
    would find out by a customer asking why nobody replied.
    """
    return bool((account or {}).get("active", True))


def active_accounts_of(cfg: dict) -> list[dict]:
    """The mailboxes the check should actually walk: named, and switched on.

    A parked mailbox keeps its password and its read bookmark, so switching
    it back on carries on from where it stopped rather than re-importing
    everything since.
    """
    return [a for a in accounts_of(cfg) if a.get("address") and is_active(a)]


def is_ready(cfg: dict) -> bool:
    """Enough set up to run a check. Deliberately only a mailbox and the
    folder — a rate list matters at quoting time, not at reading time, and
    demanding one up front would stop somebody trying the read-only half."""
    s = settings_of(cfg)
    return bool(any(is_complete(a) for a in active_accounts_of(cfg))
                and s.get("folder"))


# Back-compat alias. See is_complete's docstring.
_complete = is_complete


# ── the pipeline: each client's words, optional steps, money ─────────────
# Many businesses use Email inquiries. What each STAGE means is fixed (the
# mail check moves cards by it — see register.stage_of in the engine); what
# a client CALLS each stage, whether they use the optional steps, how often
# they chase and what money looks like are theirs, kept at
# cfg["inquiry"]["pipeline"]. Nothing here names one company's products,
# rates or terms. The defaults reproduce Prism as it was before the
# pipeline, so a config that has never seen this key behaves as it did.
#
# Stage keys: inquiry, quoted, nego, po, won. Step keys: negotiation,
# details (ask for details before quoting), acknowledgement (order
# acknowledgement on accepting a PO), proforma (proforma + advance before
# the order is confirmed). register.STEP_DEFAULTS holds the same step
# defaults on the engine side; tests/test_inquiry_pipeline.py keeps the two
# from drifting.
PIPELINE_DEFAULTS = {
    "labels": {"inquiry": "Inquiry", "quoted": "Quoted",
               "nego": "Negotiation", "po": "PO received", "won": "Won"},
    "words": {"quote": "Quotation", "po": "PO"},
    "steps": {"negotiation": True, "details": True,
              "acknowledgement": True, "proforma": False},
    "remind_days": 2,
    "max_reminders": 3,
    "currency": "₹",
    "tax_label": "GST",
    "tax_percent": 18,
}

# Currencies written with lakh/crore grouping: 1,10,000 not 110,000.
_INDIAN_CURRENCIES = {"₹", "inr", "rs", "rs."}


# A stage name or word longer than this blows a board column up to its
# full text width (review R12); the setup dialog caps typing at the same.
LABEL_MAX = 24


def _text(value, default: str, limit: int | None = None) -> str:
    text = value.strip() if isinstance(value, str) and value.strip() else default
    if limit and len(text) > limit:
        text = text[:limit].rstrip()
    return text


# The words and currency/tax pairs Pipeline & wording offers. Copy tables
# (devtools/extract_strings.COPY_TABLES), so every offered word reaches the
# translation catalogue, and a word picked from the list is shown
# translated, like the default (review R14).
WORDS = {"quote": ["Quotation", "Offer", "Proposal", "Estimate"],
         "po": ["PO", "Order", "Work order", "Purchase order"]}
TAXES = [("₹", "GST", 18), ("$", "Sales tax", 0), ("€", "VAT", 20),
         ("AED", "VAT", 5), ("£", "VAT", 20)]


def _number(value, default, *, low=0, high=None):
    """A number from a config value that may be missing, text or nonsense.
    Out of range or unreadable is the default, never an exception: a
    hand-edited config.json must not stop the inquiry screen opening."""
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    if number != number or number < low or (high is not None and number > high):
        return default
    return int(number) if number == int(number) else number


def _switch(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str) and value.strip():
        return value.strip().lower() not in ("0", "false", "no", "off")
    return default


def pipeline_of(cfg: dict) -> dict:
    """The client's pipeline settings, complete: every key present, every
    value readable. Missing or partial config falls back key by key — to
    the inquiry settings Prism already had (followup_days, max_reminders,
    terms.gst_percent) and then to PIPELINE_DEFAULTS. A fresh dict each
    call; callers may edit it and save what they mean to save."""
    s = settings_of(cfg or {})
    raw = s.get("pipeline")
    raw = raw if isinstance(raw, dict) else {}
    d = PIPELINE_DEFAULTS
    labels = raw.get("labels") if isinstance(raw.get("labels"), dict) else {}
    words = raw.get("words") if isinstance(raw.get("words"), dict) else {}
    steps = raw.get("steps") if isinstance(raw.get("steps"), dict) else {}
    terms = s.get("terms") if isinstance(s.get("terms"), dict) else {}
    remind = _number(s.get("followup_days"), d["remind_days"], low=1, high=365)
    chases = _number(s.get("max_reminders"), d["max_reminders"], low=0, high=50)
    tax = _number(terms.get("gst_percent"), d["tax_percent"], low=0, high=100)
    return {
        "labels": {k: _text(labels.get(k), v, LABEL_MAX)
                   for k, v in d["labels"].items()},
        "words": {k: _text(words.get(k), v, LABEL_MAX)
                  for k, v in d["words"].items()},
        "steps": {k: _switch(steps.get(k), v) for k, v in d["steps"].items()},
        "remind_days": _number(raw.get("remind_days"), remind, low=1, high=365),
        "max_reminders": _number(raw.get("max_reminders"), chases, low=0, high=50),
        "currency": _text(raw.get("currency"), d["currency"]),
        "tax_label": _text(raw.get("tax_label"), d["tax_label"]),
        "tax_percent": _number(raw.get("tax_percent"), tax, low=0, high=100),
    }


def stage_label(cfg: dict, stage: str) -> str:
    """What this client calls a stage. "lost" is not a column on the board
    and has no client wording; it reads "Lost"."""
    return pipeline_of(cfg)["labels"].get(stage, "Lost" if stage == "lost" else stage)


def word(cfg: dict, key: str) -> str:
    """The client's word for "quote" (Quotation, Offer, ...) or "po"."""
    return pipeline_of(cfg)["words"].get(key, key)


def step_enabled(cfg: dict, step: str) -> bool:
    return bool(pipeline_of(cfg)["steps"].get(step, False))


def remind_days(cfg: dict) -> int:
    return int(pipeline_of(cfg)["remind_days"])


def max_reminders(cfg: dict) -> int:
    """Reminders sent before the card says "call them"."""
    return int(pipeline_of(cfg)["max_reminders"])


def currency_of(cfg: dict) -> str:
    return pipeline_of(cfg)["currency"]


def tax_of(cfg: dict) -> tuple[str, float]:
    """("GST", 18) — the tax's name and percentage."""
    p = pipeline_of(cfg)
    return p["tax_label"], p["tax_percent"]


# A hand-typed money cell: currency words and "/-" are dropped as whole
# tokens first ("Rs. 1,25,000" must not keep the dot of "Rs."), then what
# is left must be one plain or comma-grouped number. Anything else —
# "1e6", "abc", NaN — is unreadable, never a guessed figure (review R7).
_MONEY_TOKENS = re.compile(
    r"(?i)(?:₹|\$|€|£|\brs\b\.?|\binr\b|\busd\b|\beur\b|\bgbp\b|\baed\b|/-)")
_PLAIN_AMOUNT = re.compile(
    r"^-?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d+)?$")


def _read_amount(value) -> Decimal | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        if isinstance(value, (int, Decimal)):
            amount = Decimal(value)
        elif isinstance(value, float):
            amount = Decimal(repr(value))
        else:
            text = re.sub(r"\s+", "", _MONEY_TOKENS.sub(" ", str(value)))
            if not _PLAIN_AMOUNT.match(text):
                return None
            amount = Decimal(text.replace(",", ""))
        if not amount.is_finite():
            return None
        return amount.quantize(Decimal("0.01"), ROUND_HALF_UP)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def format_money(value, currency: str = "₹") -> str:
    """"₹1,10,000", "$110,000", "AED 110,000.50" — for display only; the
    register keeps plain digits (register.money_str).

    Lakh grouping for rupees — the same grouping as the engine's
    quoting.indian_currency(), repeated here because this module stays
    engine-free — and groups of three for every other currency. Paise only
    when there are some. Unreadable is "", never "₹0", which would read as
    a real price of nothing.
    """
    amount = _read_amount(value)
    if amount is None:
        return ""
    symbol = currency if isinstance(currency, str) else "₹"
    negative = amount < 0
    whole, _, paise = f"{abs(amount):.2f}".partition(".")
    if symbol.strip().lower() in _INDIAN_CURRENCIES:
        if len(whole) > 3:
            head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", whole[:-3])
            whole = f"{head},{whole[-3:]}"
    else:
        whole = f"{int(whole):,}"
    text = whole if paise == "00" else f"{whole}.{paise}"
    # A word-like symbol ("AED", "Rs") needs a space before the digits.
    if symbol and symbol[-1:].isalpha():
        symbol += " "
    return f"{'-' if negative else ''}{symbol}{text}"


def money_of(cfg: dict, value) -> str:
    """format_money() in this client's currency."""
    return format_money(value, currency_of(cfg))
