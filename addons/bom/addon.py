"""BOM — Bill of Materials, the parts list to fabricate a drawing or spec."""
from __future__ import annotations

from addons import manifest, names
from addons.manifest import ACCENT, RAIL, HOME, Addon, Offer

MANIFEST = Addon(
    key="bom",
    # "BOM & Stock" is the name on Home and the one a customer recognises;
    # the SKU they bought is "BOQ & BOM" (plans.FEATURES["boq"]). The rail
    # said just "BOM", a fourth drift on the same add-on. The fuller name wins.
    #
    # Safe on the shelf despite the ampersand, because AddonRow draws its name
    # through an _Elided QLabel rather than through the button's own setText,
    # and QLabel does not read "&" as an accelerator. sidebar._amp() is for the
    # rows that DO use setText.
    label="BOM & Stock",
    chip="BOM",                 # the history pill, where there is no room
    # SWITCHED OFF 2026-11-16 (owner: "remove BOM and Stock for now from
    # UI"). Off every shelf, out of Help and Lumi, and the shell opens
    # nothing for it; code, licence key, past runs and tests are untouched.
    # To bring it back, change OFF to LIVE on the next line. That is all.
    status=manifest.OFF,
    # Rides "boq" by design: BOQ and BOM are ONE add-on ("BOQ & BOM" in
    # plans.FEATURES), and BOM ships as a mode inside the BOQ dialog, so
    # BOQ's route is the one that has to be guarded. There is no "bom"
    # licence key any more -- one used to be declared and nothing gated on
    # it, so a licence carrying it unlocked nothing.
    feature="boq",
    tip="Bill of Materials — the parts list to fabricate it, measured from "
        "a CAD drawing or a written spec",
    # DRIFT RESOLVED HERE, and this one was user-facing. BOM shipped: it is
    # routed, gated, has its own screen index and opens a real dialog. The
    # rail shows it in the accent colour. Home still described it as "Coming
    # soon" in grey, because that string was written when BOM was a SOON
    # placeholder and nothing made the two tables change together. Anyone
    # working from Home has been told a shipped add-on does not exist yet.
    blurb="The parts list, off a drawing",
    icon="list",
    tone=ACCENT,
    # Last on both shelves. One `order` reproduces the rail AND Home exactly,
    # because the rail is simply Home with reel and motion filtered out --
    # which is a fact neither table could express while there were two.
    order=70,
    shelves=(RAIL, HOME),
    screen="bom",
    # Not its own dialog: BOQ's, in a different mode. Exactly the kind of
    # implementation detail an intent name is supposed to hide -- and the
    # clearest illustration of why the add-on split is worth doing, since
    # today "a whole new add-on" means "a mode flag in someone else's file".
    dialog="addons.boq.dialog:BoqDialog",
    panel="addons.bom.panel:BomPanel",
    # Declared, not smuggled. See manifest.Addon.provided_by.
    provided_by="boq",
    probe="core_bridge:boq_available",
    kind="bom",
    # "Bill of Materials — " for records written before the fix; see the
    # matching note in addons/boq/addon.py.
    run_prefixes=("BOM — ", "Bill of Materials — ", "/bom "),
    engine=("boq",),
    offers=(Offer(names.LIST_PARTS,
                  "addons.bom.contract:open_with_files",
                  "List the parts"),),
)
