"""Which build flavour this is: the add-ons it contains, fixed at build time.

`FLAVOUR` is baked in when a build is made, exactly like `channel.CHANNEL`. It
is never read from the environment, a config file or a server, so a customer
cannot turn a Sales build into an Engineering one. "complete" is today's
product (all ten add-ons) and the default: every existing customer keeps it.

STDLIB ONLY and no imports of Prism code: packaging/prism.spec imports this in
a bare interpreter to decide what to exclude.

Why the add-on KEYS are listed here as well as imported in addons/flavours/:
the imports are what PyInstaller follows, this table is what tests and the
spec check them against. addons/registry.py refuses to start if the two
disagree, so a flavour module cannot quietly gain or lose an add-on.
"""
from __future__ import annotations

FLAVOUR = "engineering"      # "complete" | "studio" | "sales" | "engineering"

# add-on keys per flavour. Order does not matter here (registry sorts by
# manifest order). Feature keys are untouched: a licence still means the same.
ADDONS_BY_FLAVOUR: dict[str, tuple[str, ...]] = {
    "complete": ("inquiry", "boq", "gerber", "step", "bom", "email", "leads",
                 "whatsapp", "reel", "motion"),
    "studio": ("reel", "motion"),
    "sales": ("inquiry", "email", "leads", "whatsapp"),
    "engineering": ("boq", "bom", "step", "gerber"),
}

FLAVOURS = tuple(ADDONS_BY_FLAVOUR)


def addon_keys(flavour: str | None = None) -> tuple[str, ...]:
    return ADDONS_BY_FLAVOUR[flavour or FLAVOUR]


def excluded_addon_keys(flavour: str | None = None) -> tuple[str, ...]:
    """Add-ons a build of this flavour must NOT contain (for prism.spec)."""
    keep = set(addon_keys(flavour))
    return tuple(k for k in ADDONS_BY_FLAVOUR["complete"] if k not in keep)


def spec_excludes(flavour: str | None = None) -> list[str]:
    """Extra `excludes` for packaging/prism.spec. EMPTY for "complete", so the
    complete build's exclusion list is byte-for-byte what it was before
    flavours (the other flavours' tiny selection modules just ride along)."""
    flavour = flavour or FLAVOUR
    if flavour == "complete":
        return []
    return ([f"addons.{k}" for k in excluded_addon_keys(flavour)]
            + [f"addons.flavours.{f}" for f in FLAVOURS if f != flavour])
