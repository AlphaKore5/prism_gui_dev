"""What an add-on IS, as data.

One frozen dataclass, and every field on it exists to absorb a table that
is currently maintained by hand in more than one place. Before this file,
adding an add-on meant editing seven of them and the app diverged quietly
if you missed one -- which has already happened:

  · widgets/sidebar.py ADDONS         5 entries
  · widgets/home_panel.py ADDONS      7 entries  (+reel, +motion)
  · widgets/simple_panels.py ADDONS   6 entries  (no inquiry)

Three tables that must agree, three different memberships. And where they
DO overlap they still disagree: Gerber's icon is "file" on the rail and
"grid" on Home, and BOM -- which shipped, is routed, is gated and opens a
real dialog -- is still described on Home as "Coming soon" in grey, because
that string was written when BOM was a placeholder and nothing made the two
tables change together.

STDLIB ONLY. No Qt, no engine, no theme. packaging/prism.spec imports the
registry in a bare interpreter to compute hiddenimports; a Qt import here
would need a display on the build box. `tone` is therefore a colour TOKEN
resolved late, never a colour: widgets/sidebar.py freezes theme.ACCENT/OK/
WARN at import time, and theme.apply_role() rebinds ACCENT but not OK or
WARN -- which is exactly why that staleness is invisible today.

`status` is separate from `feature` on purpose. The old sidebar overloaded
the feature slot with a SOON = "__soon__" sentinel, but "not built yet" and
"not bought" are different facts about different systems, and conflating
them means the day a thing ships you edit a licence column. Note that
nothing uses SOON any more -- BOM outgrew it and only Home was not told.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── status ───────────────────────────────────────────────────────────────
# Whether the add-on EXISTS, which has nothing to do with whether it is paid
# for. LIVE registers and appears; SOON appears as a caption and cannot be
# opened; HIDDEN is reachable by command but has no shelf row (which is what
# reel and motion actually are today, whatever the two tables imply).
# OFF is built, licensed and tested but switched off for now: on no shelf,
# offered to no other add-on, and the shell opens nothing for it. Its code,
# data and runs stay exactly as they are; setting the status back to LIVE is
# the whole of turning it on again.
LIVE = "live"
SOON = "soon"
HIDDEN = "hidden"
OFF = "off"

# ── shelves ──────────────────────────────────────────────────────────────
# Where a row is drawn. An add-on can sit on several, and the difference
# between the rail and Home stops being an accident of two lists.
RAIL = "rail"
HOME = "home"

# ── tone tokens ──────────────────────────────────────────────────────────
# Resolved by theme.tone(name) at build time, never frozen here.
OK = "ok"
ACCENT = "accent"
WARN = "warn"
MUTED = "muted"


@dataclass(frozen=True)
class Offer:
    """Work this add-on will do for another one, named by intent.

    The whole point of the add-on model is that no add-on imports another.
    Inquiry used to import BoqDialog directly and therefore knew
    five things about BOQ: its module, its class, its constructor, how it
    shapes attachments, and implicitly that the user is entitled to it. An
    Offer replaces all five with one string from addons/names.py.
    """

    intent: str
    handler: str                      # "addons.boq.contract:open_with_files"
    label: str = ""                   # button copy, when the consumer draws one


@dataclass(frozen=True)
class Addon:
    """One add-on, declared once."""

    # ── identity ─────────────────────────────────────────────────────────
    key: str
    label: str
    status: str = LIVE

    # ── licence ──────────────────────────────────────────────────────────
    # A REFERENCE into plans.FEATURES, never a copy of it. Empty means the
    # add-on is not gated. Note this is not always the same word as `key`:
    # gerber rides "boq" because the licence server has no gerber key, and
    # bom rides "boq" because it ships as a mode inside the BOQ dialog. The
    # licence server is authoritative for what these words mean; plans.py is
    # presentation only.
    feature: str = ""

    # ── how it is drawn ──────────────────────────────────────────────────
    tip: str = ""                     # rail hover copy
    blurb: str = ""                   # Home summary row copy
    # The short form, for the width-constrained history pill. A real third
    # piece of copy, not a truncation: the shelf says "Reel / Studio" and
    # "Motion Graphics" where the pill has room only for "Reel" and "Motion".
    # Empty means "same as label", which is true of every other add-on.
    chip: str = ""
    icon: str = "file"
    tone: str = ACCENT
    order: int = 100
    shelves: tuple[str, ...] = (RAIL, HOME)

    # ── how it is opened ─────────────────────────────────────────────────
    # Dotted "module:attr" strings, resolved lazily by the registry. Strings
    # rather than imports so this module stays stdlib-only and so the shell
    # never imports an add-on to find out that it exists.
    screen: str = ""                  # the stack page's name
    panel: str = ""                   # "addons.gerber.panel:GerberPanel"
    dialog: str = ""                  # a modal
    entry: str = ""                   # anything else

    # The add-on whose package this one's `dialog` lives in.
    #
    # Normally empty, and the contract test requires it to be: an add-on
    # naming a module inside another add-on's package is the import ban
    # laundered through a string, and it is exactly the coupling this whole
    # structure exists to remove.
    #
    # BOM is the one honest exception in this build. It has its own rail row,
    # its own screen and its own front-door panel, but the thing it opens IS
    # BOQ's dialog with mode="bom" -- it was built that way, as a mode flag
    # inside somebody else's file, which is the clearest illustration in the
    # repository of why the add-on split is worth doing. Declaring the
    # dependency makes it visible and testable instead of hidden in a string;
    # it does not make it good. The fix is for BOM to own a dialog, or for
    # both to be one add-on with two front doors.
    provided_by: str = ""

    # ── whether it can run at all ────────────────────────────────────────
    probe: str = ""                   # "core_bridge:gerber_available"
    remedy: str = ""                  # offered when the probe says no

    # ── how its runs are recognised in shared history ────────────────────
    # These match f-strings that live in the dialogs. They must never be
    # translated: a translated prefix matches nothing and History silently
    # empties in Hindi.
    kind: str = ""
    run_prefixes: tuple[str, ...] = ()

    # ── what it needs from the engine ────────────────────────────────────
    # Declared so the build knows what to bundle, and so an add-on cannot
    # quietly grow a dependency prism.spec has never heard of.
    engine: tuple[str, ...] = ()

    # ── routed agents it owns ────────────────────────────────────────────
    # The one gate the rail cannot enforce, because the agent is reached by
    # name from the router rather than by a click.
    agents: tuple[str, ...] = ()

    # ── talking to other add-ons ─────────────────────────────────────────
    offers: tuple[Offer, ...] = ()
    wants: tuple[str, ...] = ()

    def chip_label(self) -> str:
        return self.chip or self.label

    def on_shelf(self, shelf: str) -> bool:
        return shelf in self.shelves and self.status not in (HIDDEN, OFF)

    def is_live(self) -> bool:
        return self.status == LIVE

    def is_off(self) -> bool:
        return self.status == OFF
