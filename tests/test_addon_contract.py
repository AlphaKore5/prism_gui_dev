"""The add-on boundaries, as tests rather than as a convention.

`docs/architecture/06-addons.md` has always described how an add-on is
wired -- rail entry, launcher, licence gate, dialog, worker, engine call
through core_bridge. It described it as a RECIPE, six steps to follow by
hand, and hand-wiring is why the same fact ended up written in seven tables
that disagree.

This file is the recipe made checkable. Each test pins one rule, and each
one is here because breaking it fails somewhere expensive: at release, in
CI, or in front of a customer in a windowed build with no console.

Note what is NOT tested yet. Nothing consumes the registry at this stage --
it exists, it is proven to reproduce the live tables exactly, and the
rewiring is a separate commit so that reverting one is not reverting both.
The tests that only make sense after the rewiring (no shell module imports
an add-on; no module keeps a private add-on table) arrive with it.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import flavour                                          # noqa: E402
import plans                                            # noqa: E402
from addons import manifest, names, registry            # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDONS_DIR = os.path.join(ROOT, "addons")

# The manifest layer, which packaging/prism.spec imports in a bare
# interpreter. Everything here must be importable with no Qt, no engine and
# no display.
STDLIB_ONLY = ["addons/__init__.py", "addons/manifest.py", "addons/names.py",
               "addons/registry.py", "flavour.py"]

# addons/flavours/ is not an add-on: it is the registry's own selection layer
# (gate G1), one module per build flavour holding plain static imports of that
# flavour's manifests. It is part of the manifest layer, so it is held to the
# same stdlib-only rule, and to a narrower import rule of its own below.
FLAVOUR_MODULES = "flavours"

# Modules the manifest layer is allowed to import besides the standard
# library: itself, and flavour.py (itself stdlib-only, checked above).
OWN = {"addons", "flavour"}


def _imports(path: str) -> list[tuple[str, int]]:
    with open(path, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=path)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            found.append((node.module or "", node.lineno))
    return found


def _addon_packages() -> list[str]:
    return sorted(
        name for name in os.listdir(ADDONS_DIR)
        if os.path.isdir(os.path.join(ADDONS_DIR, name))
        and name not in ("__pycache__", FLAVOUR_MODULES))


class TheManifestLayerIsStdlibOnly(unittest.TestCase):
    """packaging/prism.spec imports addons.registry in a bare interpreter to
    compute hiddenimports, exactly as it already imports app_meta and
    licensing.keys. A Qt import here would need a display on the build box;
    an engine import would break the build the day the submodule moves."""

    def test_the_manifest_layer_imports_nothing_but_the_standard_library(self):
        stdlib = set(getattr(sys, "stdlib_module_names", ()))
        offenders = []
        for rel in STDLIB_ONLY + [
                "addons/%s/addon.py" % p for p in _addon_packages()] + [
                "addons/%s/%s" % (FLAVOUR_MODULES, f) for f in
                sorted(os.listdir(os.path.join(ADDONS_DIR, FLAVOUR_MODULES)))
                if f.endswith(".py")]:
            path = os.path.join(ROOT, rel)
            if not os.path.isfile(path):
                continue
            for name, lineno in _imports(path):
                top = name.split(".")[0]
                if not top or top in stdlib or top in OWN:
                    continue
                offenders.append("%s:%d  %s" % (rel, lineno, name))
        self.assertEqual(
            offenders, [],
            "The manifest layer imported something outside the standard "
            "library:\n  " + "\n  ".join(offenders)
            + "\n\nprism.spec imports addons.registry in a bare interpreter. "
              "Qt would need a display on the build box; the engine would "
              "break the build when the submodule moves. Name the thing with "
              "a dotted string and let the registry resolve it lazily.")

    def test_a_bare_interpreter_can_import_the_registry(self):
        """The AST check above can be satisfied by a file that still fails to
        import. This is the same check CI already makes for `updater`."""
        proc = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, '.'); "
             "import flavour; flavour.FLAVOUR = %r; "      # the build's flavour
             "import addons.registry as R; print(len(R.REGISTRY))"
             % flavour.FLAVOUR],
            cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(
            proc.returncode, 0,
            "addons.registry does not import in a bare interpreter, so the "
            "frozen build cannot enumerate add-ons:\n" + proc.stderr)
        self.assertEqual(proc.stdout.strip(), str(len(registry.REGISTRY)))


class NoAddOnKnowsAnotherAddOn(unittest.TestCase):
    """The whole product depends on this one. Four people can work in four
    folders only while those folders do not reach into each other."""

    def test_no_add_on_imports_another_add_on(self):
        offenders = []
        for pkg in _addon_packages():
            folder = os.path.join(ADDONS_DIR, pkg)
            for dirpath, dirs, files in os.walk(folder):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(dirpath, name)
                    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
                    for mod, lineno in _imports(path):
                        parts = mod.split(".")
                        if (len(parts) >= 2 and parts[0] == "addons"
                                and parts[1] not in ("manifest", "names",
                                                     "registry")
                                and parts[1] != pkg):
                            offenders.append("%s:%d  %s"
                                             % (rel, lineno, mod))
        self.assertEqual(
            offenders, [],
            "These add-ons import each other:\n  " + "\n  ".join(offenders)
            + "\n\nAsk for the work by intent instead -- declare it in "
              "addons/names.py, offer it from the add-on that does it, and "
              "route through the host. An import couples you to the other "
              "add-on's module path, class name, constructor AND to the "
              "customer being entitled to it.")

    def test_a_flavour_module_imports_only_add_on_manifests(self):
        """The flavour modules may name any add-on, but only its manifest
        (addons.<key>.addon). Reaching for a panel, worker or dialog here
        would couple the selection layer to an add-on's internals."""
        folder = os.path.join(ADDONS_DIR, FLAVOUR_MODULES)
        offenders = []
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".py") or name == "__init__.py":
                continue
            for mod, lineno in _imports(os.path.join(folder, name)):
                parts = mod.split(".")
                if parts[0] == "addons" and not (
                        len(parts) == 3 and parts[2] == "addon"):
                    offenders.append("addons/%s/%s:%d  %s"
                                     % (FLAVOUR_MODULES, name, lineno, mod))
        self.assertEqual(
            offenders, [],
            "A flavour module imported more than an add-on's manifest:\n  "
            + "\n  ".join(offenders))

    def test_every_add_on_package_is_in_the_registry(self):
        """Unregistered code ships, is unreachable and is UNGATED, which is
        the worst of the three."""
        registered = set(registry.keys())
        on_disk = {p for p in _addon_packages()
                   if os.path.isfile(os.path.join(ADDONS_DIR, p, "addon.py"))}
        # A flavour build leaves out add-ons on purpose (the tree still holds
        # them); what it leaves out must be exactly what flavour.py says, so
        # an add-on in no flavour's registry line still fails here.
        self.assertEqual(
            on_disk - registered, set(flavour.excluded_addon_keys()),
            "these add-ons exist on disk but are in no registry line, so "
            "they ship without appearing and without a licence check: "
            + ", ".join(sorted(on_disk - registered)))
        self.assertEqual(
            registered - on_disk, set(),
            "the registry names add-ons with no package: "
            + ", ".join(sorted(registered - on_disk)))


class TheManifestsAgreeWithTheRestOfTheApp(unittest.TestCase):

    def test_every_feature_key_exists_in_plans(self):
        """A key the licence server cannot mint padlocks the add-on for
        everyone -- which looks like a bug in the add-on rather than in a
        table, and is therefore debugged in the wrong file."""
        unknown = sorted({a.feature for a in registry.REGISTRY
                          if a.feature and a.feature not in plans.FEATURES})
        self.assertEqual(unknown, [],
                         "not present in plans.FEATURES: " + ", ".join(unknown))

    def test_run_prefixes_are_unique(self):
        """Two add-ons claiming one prefix means History attributes runs to
        whichever sorts first, silently."""
        seen = {}
        clashes = []
        for a in registry.REGISTRY:
            for prefix in a.run_prefixes:
                if prefix in seen:
                    clashes.append("%r claimed by %s and %s"
                                   % (prefix, seen[prefix], a.key))
                seen[prefix] = a.key
        self.assertEqual(clashes, [], "\n".join(clashes))

    def test_run_prefixes_are_never_translated(self):
        """These match f-strings written in the dialogs. A translated prefix
        matches nothing and History silently empties in Hindi -- no error, an
        empty list. devtools/extract_strings.py's _is_copy() already rejects
        a string with a trailing space, which is why every display prefix
        here ends in one."""
        for a in registry.REGISTRY:
            for prefix in a.run_prefixes:
                with self.subTest(addon=a.key, prefix=prefix):
                    self.assertTrue(
                        prefix.startswith("/") or prefix.endswith(" "),
                        "%r would be picked up as translatable copy; a run "
                        "prefix must be a slash command or end in a space"
                        % prefix)

    def test_every_intent_is_offered_by_at_most_one_addon(self):
        owners = {}
        clashes = []
        for a in registry.REGISTRY:
            for offer in a.offers:
                if offer.intent in owners:
                    clashes.append("%s offered by %s and %s"
                                   % (offer.intent, owners[offer.intent], a.key))
                owners[offer.intent] = a.key
        self.assertEqual(clashes, [], "\n".join(clashes))

    def test_every_intent_used_is_declared_in_names(self):
        """A typo'd intent is indistinguishable from a feature the customer
        has not bought: both draw no button and neither raises."""
        unknown = []
        for a in registry.REGISTRY:
            for offer in a.offers:
                if offer.intent not in names.ALL:
                    unknown.append("%s offers %r" % (a.key, offer.intent))
            for want in a.wants:
                if want not in names.ALL:
                    unknown.append("%s wants %r" % (a.key, want))
        self.assertEqual(unknown, [],
                         "not in addons/names.ALL:\n  " + "\n  ".join(unknown))

    def test_every_want_is_offered_by_somebody(self):
        """Not strictly required -- a want with no offer correctly degrades to
        a hidden button -- but in this build every want is deliberate, and a
        silently missing one is worth failing over."""
        for a in registry.REGISTRY:
            for want in a.wants:
                with self.subTest(addon=a.key, intent=want):
                    owner, handler = registry.offering(want)
                    if owner is None and flavour.FLAVOUR != "complete":
                        # A flavour build may lack the add-on that offers it
                        # (Sales has no BOQ, so Inquiry's "measure drawing"
                        # is unoffered and its button is not drawn: by
                        # design). It must still be offered in the complete
                        # build, by an add-on this build leaves out.
                        from addons.flavours.complete import MANIFESTS
                        owner = next(
                            (m for m in MANIFESTS if not m.is_off()
                             and m.key in flavour.excluded_addon_keys()
                             and any(o.intent == want for o in m.offers)),
                            None)
                    self.assertIsNotNone(
                        owner, "%s wants %r and nothing offers it"
                               % (a.key, want))


class TheDottedReferencesResolve(unittest.TestCase):
    """The price of trading static analysis for strings, paid here."""

    def test_every_dialog_and_probe_resolves(self):
        for a in registry.REGISTRY:
            for field in ("dialog", "probe"):
                dotted = getattr(a, field)
                if not dotted:
                    continue
                with self.subTest(addon=a.key, field=field, target=dotted):
                    try:
                        got = registry.resolve(dotted)
                    except Exception as exc:            # noqa: BLE001
                        self.fail("%s.%s = %r did not resolve: %s"
                                  % (a.key, field, dotted, exc))
                    self.assertIsNotNone(got)

    def test_offer_handlers_live_inside_their_own_addon_and_resolve(self):
        """An add-on must answer for its own offers, out of its own package.
        A handler pointing into somebody else's package would be the import
        ban laundered through a string."""
        for a in registry.REGISTRY:
            for offer in a.offers:
                with self.subTest(addon=a.key, intent=offer.intent):
                    self.assertTrue(
                        offer.handler.startswith("addons.%s." % a.key),
                        "%s offers %s through %r, which is not in its own "
                        "package" % (a.key, offer.intent, offer.handler))
                    try:
                        got = registry.resolve(offer.handler)
                    except Exception as exc:            # noqa: BLE001
                        self.fail("%s offers %s through %r, which does not "
                                  "resolve: %s"
                                  % (a.key, offer.intent, offer.handler, exc))
                    self.assertTrue(
                        callable(got),
                        "%r is not callable, so the hand-off would fail at "
                        "the moment a user clicks rather than here"
                        % offer.handler)

    def test_no_addon_reaches_into_another_addons_package_undeclared(self):
        """The string version of the import ban.

        Every dotted reference a manifest makes must name its own package --
        unless the manifest DECLARES the borrowing with provided_by, which
        exists so that the one real case in this build (BOM opens BOQ's
        dialog with mode="bom") is visible and tested rather than hidden in
        a string nobody reads.
        """
        for a in registry.REGISTRY:
            for field in ("panel", "dialog", "entry"):
                dotted = getattr(a, field, "")
                if not dotted or not dotted.startswith("addons."):
                    continue
                owner = dotted.split(".")[1]
                if owner == a.key:
                    continue
                with self.subTest(addon=a.key, field=field):
                    self.assertEqual(
                        owner, a.provided_by,
                        "%s.%s points into addons/%s/, which is another "
                        "add-on's package. If that is deliberate, declare it "
                        "with provided_by=%r and say why; if it is not, the "
                        "two add-ons are not independent and one of them "
                        "cannot be shipped, sold or owned separately."
                        % (a.key, field, owner, owner))

    def test_provided_by_names_a_real_addon(self):
        for a in registry.REGISTRY:
            if not a.provided_by:
                continue
            with self.subTest(addon=a.key):
                self.assertIn(
                    a.provided_by, registry.keys(),
                    "%s declares provided_by=%r, which is not an add-on"
                    % (a.key, a.provided_by))
                self.assertNotEqual(a.provided_by, a.key,
                                    "an add-on cannot borrow from itself")


class TheRegistryStillMatchesTheLiveTables(unittest.TestCase):
    """A transitional test, and the most valuable one in this file right now.

    The registry does not drive anything yet. Its whole claim is that it can
    reproduce the hand-maintained tables EXACTLY -- so this asserts that,
    key for key and in order. It stays until the tables are gone, and until
    then it is what makes the rewiring provably behaviour-neutral.
    """

    # ── the golden shelves ───────────────────────────────────────────────
    # Written out as literals ON PURPOSE. Comparing the registry to
    # sidebar.ADDONS was the right test while that table was hand-written;
    # now that it is a comprehension over the registry, such a test compares
    # the registry to itself and would pass ANY membership. A golden test has
    # to be a second, independent statement of the answer or it is decoration.
    #
    # These lists are a decision, not an observation. reel and motion are on
    # Home and not on the rail, and that was settled on 2026-09-07:
    #
    #   · the rail is at 12 of 12 controls and Reel already gave its row to
    #     Artifacts, so a rail row costs something else its place;
    #   · Motion was switched off then (core/motion/render.py's
    #     _DISABLED_PENDING_ASSET_FIX), so a rail row would have advertised
    #     a feature that opened nothing. It runs again since 2026-09-08 —
    #     attached artwork reaches the film (tests/test_motion_assets.py) —
    #     but the first reason alone keeps it on Home, beside Reel.
    #
    # Both remain reachable by command, which is exactly why their licence
    # gate matters and why tests/test_addon_gates.py covers them.
    #
    # Changing a shelf means changing this list in the same commit. That is
    # the point: for months sidebar.ADDONS and home_panel.ADDONS disagreed
    # about these two while home_panel.py carried a comment saying it "must
    # never drift from" the rail.
    # step (order 35) sits between Gerber and Email so the three measuring
    # add-ons are neighbours on both shelves -- see addons/step/addon.py.
    # bom left both shelves on 2026-11-16: the owner asked for BOM & Stock to
    # be removed from the UI for now, so addons/bom/addon.py is status=OFF.
    # Flipping it back to LIVE puts "bom" back at the end of both lists
    # (tests/test_ui_port_bom_hidden.py proves that).
    #
    # Flavours (gate G1): the two lists below are the COMPLETE build's shelves,
    # pinned exactly as before. A flavour build shows the same shelves minus
    # the add-ons it does not contain, in the same order (every add-on keeps
    # its manifest `order`), so the per-build lists are derived by filtering.
    # What each flavour contains is pinned separately and explicitly in
    # tests/test_flavour.py, so this filter cannot hide a membership change.
    COMPLETE_RAIL = ["inquiry", "boq", "gerber", "step", "email", "leads",
                     "whatsapp"]
    COMPLETE_HOME = ["inquiry", "boq", "gerber", "step", "email", "leads",
                     "whatsapp", "reel", "motion"]
    GOLDEN_RAIL = [k for k in COMPLETE_RAIL if k in flavour.addon_keys()]
    GOLDEN_HOME = [k for k in COMPLETE_HOME if k in flavour.addon_keys()]

    def test_the_rail_shelf_is_what_we_decided(self):
        self.assertEqual(
            [a.key for a in registry.shelf(manifest.RAIL)], self.GOLDEN_RAIL,
            "the rail's membership changed. If that was deliberate, update "
            "GOLDEN_RAIL in the same commit and say why in the manifest that "
            "changed; if it was not, an add-on has silently appeared on or "
            "vanished from the shelf customers navigate by.")

    def test_the_home_shelf_is_what_we_decided(self):
        self.assertEqual(
            [a.key for a in registry.shelf(manifest.HOME)], self.GOLDEN_HOME,
            "the Home shelf's membership changed -- see GOLDEN_RAIL's note.")

    def test_the_rail_is_home_minus_the_command_only_addons(self):
        """The relationship the two tables could never express while there
        were two of them, and the reason one `order` reproduces both."""
        self.assertEqual(
            [k for k in self.GOLDEN_HOME if k in self.GOLDEN_RAIL],
            self.GOLDEN_RAIL,
            "the rail is no longer a subset of Home in the same order, so "
            "the same add-on now appears in two different positions "
            "depending on which screen you are looking at")

    def test_the_derived_tables_still_agree_with_the_registry(self):
        """Not tautological: sidebar and home_panel could stop deriving --
        somebody could paste a literal list back in, which is precisely what
        this restructure removed."""
        import widgets.home_panel as home_panel
        import widgets.sidebar as sidebar
        self.assertEqual([row[0] for row in sidebar.ADDONS], self.GOLDEN_RAIL)
        self.assertEqual([row[0] for row in home_panel.ADDONS],
                         self.GOLDEN_HOME)

    def test_the_licence_gate_matches_the_rail_for_every_addon(self):
        import widgets.sidebar as sidebar
        for row in sidebar.ADDONS:
            key, feature = row[0], row[4]
            with self.subTest(addon=key):
                entry = registry.by_key(key)
                self.assertIsNotNone(entry, "%r is on the rail and not in "
                                            "the registry" % key)
                self.assertEqual(
                    entry.feature, feature,
                    "widgets/sidebar.py gates %r on %r, the manifest says %r"
                    % (key, feature, entry.feature))

    def test_the_agent_gate_matches_main_windows_table(self):
        import main_window
        for agent, feature in main_window.AGENT_FEATURES.items():
            with self.subTest(agent=agent):
                self.assertEqual(
                    registry.feature_of_agent(agent), feature,
                    "main_window.AGENT_FEATURES gates %r on %r, the registry "
                    "says %r" % (agent, feature,
                                 registry.feature_of_agent(agent)))

    def test_the_run_prefixes_match_the_panel_base(self):
        import widgets.panel_base as panel_base
        live = {key: tuple(prefixes)
                for key, prefixes in panel_base._RUN_PREFIXES}
        mine = {a.key: a.run_prefixes for a in registry.REGISTRY
                if a.run_prefixes}
        self.assertEqual(
            mine, live,
            "the registry's run prefixes no longer reproduce "
            "widgets/panel_base._RUN_PREFIXES -- History would start "
            "attributing runs to the wrong add-on, or to none")


if __name__ == "__main__":
    unittest.main()
