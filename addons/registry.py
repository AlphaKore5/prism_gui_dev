"""Every add-on this build contains, and the only file that knows them all.

THE SINGLE MOST IMPORTANT RULE IN THIS DESIGN
─────────────────────────────────────────────
The imports below are STATIC and they must stay that way. A dynamic
registry --

    for name in os.listdir("addons"):
        importlib.import_module("addons.%s.addon" % name)

-- is shorter, prettier, needs no edit when an add-on is added, and is
COMPLETELY INVISIBLE to PyInstaller's analyser. Development would be
perfect. The frozen build would ship an empty shelf, in a windowed build
with no console to print the error, and the first person to find out would
be a customer. packaging/prism.spec already records this exact class of
accident happening once.

So: adding an add-on means adding a line here. That is the cost, it is one
line, and its merge conflicts are one line. It is the only shared file an
add-on touches at all -- which is the entire point, because the reason this
package exists is that every feature used to have to edit main_window.py,
workers.py, sidebar.py and simple_panels.py, and four people cannot do that
at once.

STDLIB ONLY, like the rest of the manifest layer: prism.spec imports this
module in a bare interpreter to compute hiddenimports.
"""
from __future__ import annotations

import os

from addons import manifest
from addons.manifest import Addon

# ── the registry ─────────────────────────────────────────────────────────
# Static, explicit, never importlib. Which add-ons this build contains is
# decided by flavour.FLAVOUR (baked at build time); each flavour module has
# plain `from addons.x.addon import MANIFEST` lines. The if-chain below is
# static on purpose: the analyser sees every branch, and packaging/prism.spec
# EXCLUDES the other flavours' add-on packages so they are not bundled.
from flavour import ADDONS_BY_FLAVOUR, FLAVOUR, addon_keys                      # noqa: E402

if FLAVOUR == "complete":
    from addons.flavours.complete import MANIFESTS as _MANIFESTS    # noqa: E402
elif FLAVOUR == "studio":
    from addons.flavours.studio import MANIFESTS as _MANIFESTS      # noqa: E402
elif FLAVOUR == "sales":
    from addons.flavours.sales import MANIFESTS as _MANIFESTS       # noqa: E402
elif FLAVOUR == "engineering":
    from addons.flavours.engineering import MANIFESTS as _MANIFESTS # noqa: E402
else:
    raise RuntimeError("unknown build flavour %r" % (FLAVOUR,))

REGISTRY: tuple[Addon, ...] = tuple(sorted(
    _MANIFESTS, key=lambda a: (a.order, a.key)))

# A flavour module and flavour.ADDONS_BY_FLAVOUR must name the same add-ons.
if {a.key for a in REGISTRY} != set(addon_keys()):
    raise RuntimeError(
        "flavour %r: addons/flavours imports %s but flavour.py lists %s"
        % (FLAVOUR, sorted(a.key for a in REGISTRY), sorted(addon_keys())))

# What the selftest asserts it can see. A count rather than a list, so that
# adding an add-on does not mean editing main.py too -- but a count all the
# same, because "the shelf is empty" and "the shelf is fine" must not look
# alike to a smoke test.
# Counted from the flavour table, not from REGISTRY itself: len(REGISTRY) ==
# len(REGISTRY) can never fail, so the selftest would not notice a shelf that
# came up short.
EXPECTED = len(addon_keys())

_BY_KEY = {a.key: a for a in REGISTRY}


# ── lookups ──────────────────────────────────────────────────────────────
def by_key(key: str) -> Addon | None:
    return _BY_KEY.get(key)


def is_off(key: str) -> bool:
    """True when `key` is an add-on that is switched off (manifest.OFF).
    Anything else, including a key that is not an add-on at all, is False."""
    a = _BY_KEY.get(key)
    return bool(a and a.is_off())


def is_absent(key: str) -> bool:
    """True when `key` is an add-on this build's flavour does not contain.
    Always False for "complete". Help and Lumi use it, with is_off, so they
    never describe a tool the build has not got."""
    return key in ADDONS_BY_FLAVOUR["complete"] and key not in _BY_KEY


def keys() -> tuple[str, ...]:
    return tuple(a.key for a in REGISTRY)


def shelf(name: str) -> tuple[Addon, ...]:
    """Everything drawn on one shelf, in order. The rail and Home now read
    the same table and can no longer disagree about membership, icons or
    copy -- which they did, in all three ways, for as long as there were
    two tables."""
    return tuple(a for a in REGISTRY if a.on_shelf(name))


def screens() -> tuple[tuple[str, str], ...]:
    """(key, screen name) for every add-on that owns a screen."""
    return tuple((a.key, a.screen) for a in REGISTRY if a.screen)


def kind_of(title: str) -> str:
    """Which add-on produced a run, from its recorded title.

    Replaces widgets/simple_panels._RUN_PREFIXES, whose own comment had to
    list the four other files whose f-strings it was matching against --
    with nothing tying them together and no test that would notice if one
    changed.
    """
    for a in REGISTRY:
        for prefix in a.run_prefixes:
            if title.startswith(prefix):
                return a.kind or a.key
    return ""


def feature_of_agent(agent: str) -> str:
    """The licence feature a routed agent needs. Replaces
    main_window.AGENT_FEATURES."""
    for a in REGISTRY:
        if agent in a.agents:
            return a.feature
    return ""


def offering(intent: str) -> tuple[Addon, str]:
    """Who does `intent`, and through which handler. ("", "") if nobody."""
    for a in REGISTRY:
        if a.is_off():
            continue
        for offer in a.offers:
            if offer.intent == intent:
                return a, offer.handler
    return None, ""


def engine_modules() -> tuple[str, ...]:
    """Every engine module any add-on declares it needs, deduplicated.

    packaging/prism.spec uses this so that an add-on cannot depend on part
    of the engine the build has never heard of. core/motion/* is the live
    example: it is a subpackage, the spec's enumeration filters *.py over
    core/ non-recursively, and so it has never been in a frozen build.
    """
    found = []
    for a in REGISTRY:
        for name in a.engine:
            if name not in found:
                found.append(name)
    return tuple(found)


def addon_modules() -> tuple[str, ...]:
    """Every module under addons/, as dotted names, for hiddenimports.

    Walks the directory RECURSIVELY. Belt and braces beside the static
    imports above: the imports are what the analyser follows, this is what
    catches a module that only the manifest's dotted strings refer to.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    from flavour import FLAVOURS, excluded_addon_keys
    skip_dirs = set(excluded_addon_keys())
    skip_files = {f + ".py" for f in FLAVOURS if f != FLAVOUR}
    found = []
    for folder, dirs, files in os.walk(here):
        dirs[:] = [d for d in dirs if d != "__pycache__"
                   and not (folder == here and d in skip_dirs)]
        for name in files:
            if not name.endswith(".py"):
                continue
            if os.path.basename(folder) == "flavours" and name in skip_files:
                continue
            rel = os.path.relpath(os.path.join(folder, name), root)
            dotted = rel[:-3].replace(os.sep, ".")
            if dotted.endswith(".__init__"):
                dotted = dotted[:-len(".__init__")]
            if dotted not in found:
                found.append(dotted)
    return tuple(sorted(found))


def resolve(dotted: str):
    """"module:attr" -> the attribute. The price of trading static analysis
    for strings, paid in one place and checked by a contract test that
    resolves every dotted reference in the registry."""
    if not dotted:
        return None
    module_name, _, attr = dotted.partition(":")
    module = __import__(module_name, fromlist=["*"])
    return getattr(module, attr) if attr else module


__all__ = ["REGISTRY", "EXPECTED", "by_key", "is_off", "keys", "shelf", "screens",
           "kind_of", "feature_of_agent", "offering", "engine_modules",
           "addon_modules", "resolve", "manifest"]
