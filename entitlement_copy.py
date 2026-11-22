"""Words for "you own this add-on, but this build does not contain it".

A licence can include add-ons (Leads, BOQ ...) that the build in front of the
customer leaves out: Prism Engineering has no Leads, Prism Sales has no BOQ.
The customer owns the tool; they need to be told which Prism opens it, not
that "it isn't available". This module is only the sentence and the table
behind it (data, stdlib only, no Qt) so the shell's download card (Studio R8)
and the read-only history note use one wording, and a test can pin it.

The owner of an add-on is derived from flavour.ADDONS_BY_FLAVOUR, never typed
in twice, so a new add-on cannot be left without a home.
"""
from __future__ import annotations

import flavour

EDITION_NAMES = {"studio": "Prism Studio", "sales": "Prism Sales",
                 "engineering": "Prism Engineering"}


def owner_edition(addon_key: str) -> str:
    """Flavour that contains `addon_key` (studio, sales or engineering), or
    "" for a key that belongs to no edition."""
    for fl in EDITION_NAMES:
        if addon_key in flavour.ADDONS_BY_FLAVOUR[fl]:
            return fl
    return ""


def absent_message(addon_key: str, tool_name: str) -> str:
    """Card text for an add-on the licence includes but this build lacks.
    "" when there is nothing to say (the key belongs to no edition)."""
    edition = EDITION_NAMES.get(owner_edition(addon_key))
    if not edition:
        return ""
    return ("%s is part of %s. Your licence includes it; it just isn't in "
            "this version. Open %s to use it." % (tool_name, edition, edition))


def read_only_note(addon_key: str) -> str:
    """One line for the history screen over a saved run whose add-on this
    build lacks: the record can be read, but not continued here."""
    edition = EDITION_NAMES.get(owner_edition(addon_key))
    if not edition:
        return ""
    return "This run was made with a tool that opens in %s. You can read it here." % edition
