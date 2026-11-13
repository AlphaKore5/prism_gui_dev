"""Rebuild lang/_catalogue.json — the list of English strings Prism can translate.

Why a catalogue at all, when i18n.t() could just translate anything handed to
it? Because it must NOT translate anything handed to it. The same setText()
that draws "Start the work" also draws a customer's name, a file path, an
agent's brand name and — via the output panel — whole paragraphs written by
Claude. The catalogue is the allow-list: a string is only ever swapped if it
is in here, so everything else passes through untouched by construction.

That makes this file the one place a new piece of UI copy has to be
registered. Run it after adding any:

    python3 devtools/extract_strings.py

It rewrites lang/_catalogue.json in place and prints what changed. Existing
translation packs are never touched — a key that disappears from the
catalogue simply stops being looked up, and a new key falls back to English
until someone translates it.

What it finds:
  * string literals passed to the Qt calls that put words on screen
    (setText, setToolTip, QMessageBox.warning, QPushButton("…"), …)
  * string literals inside the module-level tables that hold UI copy
    (sidebar.PRIMARY, agents_panel.STAGE_COPY, …) — these reach the screen
    through a variable, so the call-site scan cannot see them
  * anything already wrapped in t("…") by hand, which is how f-string
    templates like "Opened {n} tabs" get in

What it deliberately skips: URLs, stylesheets, object names, format specs,
and anything without a letter in it.
"""
from __future__ import annotations

import ast
import json
import re
import os
import sys

# Windows consoles are cp1252 and cannot encode the characters below — see
# packaging/build.py for the CI failure that found this. Degrade, don't die.
#
# Under __main__ only: at import time sys.stdout belongs to the importer,
# not to us. devtools/mint.py is imported by five test files, so at module
# level this block would re-encode pytest's own capture stream as a side
# effect of collecting a test — a script reaching into its caller's I/O.
if __name__ == "__main__":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "lang", "_catalogue.json")

# Directories that hold no user-facing GUI copy. prism_terminal is the shared
# engine — it is a submodule the CLI also uses, and translating the CLI is not
# this app's business. The few engine strings that surface in the GUI arrive
# through the status sink and are listed by hand in EXTRA below.
# "venv" as well as ".venv": the working interpreter on the owner's machine lives
# in prism_gui/venv, and walking it catalogued thousands of PySide6 strings.
SKIP_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", "prism_terminal",
             "tests", "packaging", "devtools", "assets", "docs", "lang",
             # Claude Code keeps temporary git worktrees here. A worktree is a
             # second checkout of this same repo, so walking it lists every
             # string twice -- once against the real path and once against a
             # path that does not exist for anybody else -- and adds the
             # strings of whatever branch happens to be checked out in it.
             # tests/test_worker_mandate.py skips it for the same reason.
             ".claude"}

# A few helpers take a string that is NOT copy — a stylesheet object name, an
# icon name, a callback. Listing the argument positions that ARE copy keeps
# 'tagAccent' and 'sliders' out of the translator's way.
ARG_SLOTS = {
    "_tag": (0,),           # (text, style)
    "_mini": (1,),          # (icon_name, tip, slot)
    "icon_label": (1,),     # (icon_name, text, size, colour)
    "nav_button": (0, 3),   # (label, icon_name, small, tip)
    "_action": (0, 2),      # (label, icon_name, tip, slot)
    "_section": (0,),       # (text, faint) — the rail's group headers
    # The Email inquiry automation window's tab pages and their action buttons:
    # (sentence, table, icon, empty_title, empty_body) and (key, text, …).
    "_TabPage": (0, 3, 4),
    "add_action": (1,),
    "_make_table": (0,),    # (headers, stretch, fit) — the column titles

    # ── the shared component system (widgets/controls.py, dialogs/base.py) ──
    # These slots are not decoration: without an entry here EVERY positional
    # argument is scraped, and several of these take DATA in the first slot.
    # FileItem's first argument is a filename and MetricCard's second is a
    # measured number — putting either in the catalogue would mean i18n.t()
    # swapping a customer's own file or figure for a translation, which is the
    # precise failure the allow-list exists to prevent.
    "label": (0, 7),        # (text, role, level, colour, weight, wrap, size, tooltip)
    "button": (0,),         # (text, …) — tooltip differs between the two
                            # button() helpers, so it is caught by keyword below
    "icon_button": (1,),    # (icon_name, tooltip, on_click, colour)
    "Pill": (0,),           # (text, tone)
    "Chip": (0,),           # (text, icon_name, style)
    "StatusBadge": (1,),    # (state, detail) — `state` is a lookup key
    "PageHeader": (0, 1),   # (title, subtitle, actions)
    "SectionHeader": (0, 1),
    "SearchField": (0,),    # (placeholder)
    "FilterChips": (0,),    # (options, current)
    "Tabs": (0,),           # (options, current)
    "EmptyState": (1, 2, 3),  # (icon, title, body, action_text) — icon is a glyph
    "MetricCard": (0, 2),   # (label_text, value, detail, …) — value is DATA
    "FileItem": (1,),       # (name, detail, …) — name is a FILENAME
    "StepRow": (1, 2),      # (index, title, subtitle, state, …)
}

# Words that look like copy but must never be translated. The product name is
# the product name in every language; the rest are formats and placeholders
# the user is meant to read literally.
NEVER = {
    "Prism", "PRISM", "Prism Setup", "Prism Studio", "Prism Reel",
    "Prism Motion", "Groq",
    "Chrome", "Canva", "Apollo", "ChatGPT", "Claude", "Perplexity", "Gmail",
    "PRSM-XXXXX-XXXXX-XXXXX-XXXXX", "gsk_…", "tagAccent", "tagOutline",
    # Language names in the picker stay in their own script, always. The one
    # person who most needs that list is someone who set the wrong language
    # and can no longer read the interface — translating "English" into
    # Devanagari is exactly the moment it stops being a way back out.
    "English",
    # A QFileDialog name filter is a syntax, not a sentence — Qt parses the
    # parentheses. Translating it breaks the filter.
    "Text (*.txt)",
    # A date-format hint is read literally — the customer types digits into
    # exactly those positions. Translated, it stops matching what the code
    # parses.
    "DD-MM-YYYY",
    # The IMAP folder name is protocol, not prose.
    "INBOX",
}

# Calls whose string arguments end up on screen.
TEXT_CALLS = {
    # Qt setters
    "setText", "setToolTip", "setPlaceholderText", "setWindowTitle",
    "setStatusTip", "setWhatsThis", "setTitle", "setLabelText", "setSuffix",
    "setPrefix", "setItemText", "setTabText", "setInformativeText",
    "setDetailedText", "addItem", "addItems", "insertItem",
    # Qt static dialogs — (parent, title, body) are all args 1..2
    "information", "warning", "critical", "question", "about",
    "getExistingDirectory", "getOpenFileName", "getOpenFileNames",
    "getSaveFileName", "getText",
    # Qt widget constructors that take their label first
    "_TabPage", "add_action", "_make_table",
    "QLabel", "QPushButton", "QCheckBox", "QRadioButton", "QGroupBox",
    "QAction", "QListWidgetItem", "QToolButton", "QTreeWidgetItem",
    # Prism's own text helpers (widgets/controls.py) and local factories
    "heading", "meta", "kicker", "icon_label", "nav_button", "Section",
    "_action", "_tag", "_mini", "_section", "pill", "chip",
    # The shared component system. Every one of these puts words on screen,
    # and the redesign routed most of the app's copy through them — 200-odd
    # call sites that were silently invisible to this scanner, so their copy
    # reached no translator and shipped in English inside a Hindi build. The
    # matcher resolves C.button(), self.button() and a bare button() to the
    # same name, so one entry covers every calling style.
    "label", "button", "icon_button", "Pill", "Chip", "StatusBadge",
    "PageHeader", "SectionHeader", "SearchField", "FilterChips", "Tabs",
    "EmptyState", "MetricCard", "FileItem", "StepRow",
    # the hand-written escape hatch
    "t", "_t", "tr",
}

# Module-level tables whose strings reach the screen through a variable.
# Matched on the assignment target's name, anywhere in the GUI package.
# The redesign moved most rail and screen copy into tables like these
# (sidebar.MORE, settings_panel.SECTIONS, GuidePanel.CARDS), so a table
# missing from this set silently ships its labels untranslatable.
COPY_TABLES = {
    "PRIMARY", "SECONDARY", "STAGE_COPY", "FEATURE_NAMES", "FEATURE_BLURB",
    "STATUS_COPY", "STATES", "STEP_COPY", "COPY", "LABELS", "TIPS",
    "PLACEHOLDERS", "SKIP", "SOON",
    "MORE", "ADDONS", "DIRECT", "SECTIONS", "CARDS", "TABS", "STEPS",
    # inquiry_config: the words and tax names Pipeline & wording offers.
    "WORDS", "TAXES",
    # addons/<key>/addon.py's `MANIFEST = Addon(...)`. The rail and Home
    # tables are now comprehensions over the registry, so their labels and
    # tips are no longer literals where this scan can see them -- they live
    # in the manifests instead, and without this line every add-on's name and
    # description would silently ship untranslatable.
    #
    # _is_copy() already sorts the wheat from the chaff in an Addon call:
    # "Gerber" is copy; "gerber" and "accent" are rejected as lowercase;
    # "addons.gerber.contract:open_with_files" is rejected for the dot; and
    # "Gerber — " is rejected for the trailing space -- which is exactly what
    # the run prefixes need, since a TRANSLATED prefix would match nothing and
    # History would silently empty in Hindi.
    "MANIFEST",
    "TITLE", "BLURB", "HEADLINE", "DETAIL", "ACTION",
    "ROW_ACTIONS", "REGISTER_RANGES", "OPEN_LABEL",
    # Leads & Outreach (Apollo's Find People): the filter rail's facet names
    # (prospector.filters), the Sort box, the Total / Net New / Saved tabs,
    # the page's empty states and Default view's starter searches — each
    # reaches the screen through a variable.
    "FACET_LABELS", "_SORTS", "_PEOPLE_TABS", "_EMPTY_TITLE", "_EMPTY_BODY",
    "_NO_MATCH_TITLE", "_NO_MATCH_BODY", "_STARTERS",
    # …and Stage / Lists / Custom fields: the Contact | Account switch's
    # labels, and what each says with nothing to pick yet. (Stage and list
    # NAMES are records' values, shown as kept — never looked up.)
    "_RECORD_SIDES", "_CUSTOM_SIDES", "_RECORD_EMPTY", "_CUSTOM_EMPTY",
    # …and Find phones: the kind of number a found phone looks like, and what the
    # person panel says under it about where it was published (prospector/phones.py).
    "KIND_LABEL", "SOURCE_LINE",
    # …and Find mobiles: what the panel says under a person's own mobile.
    "PERSON_LINE",
}

# Strings that reach the UI from somewhere this scan cannot see: the engine's
# status sink, and the handful of built-in Qt button labels Prism relies on.
EXTRA = [
    "Yes", "No", "OK", "Cancel", "Save", "Close", "Open", "Apply", "Retry",
    "Ignore", "Discard", "Help", "Reset", "Abort",
    # The BOQ dialog's own name for the document it produces. It is chosen by
    # a conditional and kept on an attribute --
    #
    #     self._doc = "Bill of Materials" if self.mode == "bom" else "Bill of Quantities"
    #
    # -- and then translated (`i18n.t(self._doc)`) and used as the window
    # title. This scan reads literals in call arguments and in the copy
    # tables; a literal assigned to an attribute is invisible to it, so both
    # halves have to be listed here or the window title silently stops
    # translating. "Bill of Quantities" was in the catalogue by historical
    # accident and fell out the first time it was regenerated.
    "Bill of Quantities", "Bill of Materials",
]


def _is_copy(s: str) -> bool:
    """True if this literal is prose meant for a human, not machinery."""
    s = s.strip()
    if len(s) < 2 or not any(c.isalpha() for c in s):
        return False
    if s in NEVER:
        return False
    # A translatable template — "{n} steps of {total}" — is copy, and its
    # braces must not be mistaken for the stylesheet braces filtered below.
    # Blanked out first so the rest of the checks see the prose around them.
    bare = re.sub(r"\{[a-z_][a-z0-9_]*\}", "", s, flags=re.IGNORECASE)
    if not any(c.isalpha() for c in bare):
        return False
    # URLs, paths, selectors, keys
    if bare.lstrip().startswith(("http", "gsk_", "/", "~/", ".", "#", "--")):
        return False
    if "://" in s or s.startswith("data:"):
        return False
    # CSS / stylesheet fragments
    if ("{" in bare and "}" in bare) or ";" in bare and ":" in bare:
        return False
    # HTML the code splices around a value — '<a href="', '</a>', '" style="'
    if "<" in s or ">" in s or '="' in s:
        return False
    # snake_case / camelCase identifiers, object names, config keys
    if " " not in s and ("_" in s or s.islower() and len(s) < 14 and s.isalnum()):
        return False
    # CSS selectors like "QFrame#setupHeader"
    if s.startswith("Q") and ("#" in s or "::" in s):
        return False
    # A shard of an f-string: the code built "Opened " + n + " tabs" and we
    # are looking at one end of it. Translating half a sentence is worse than
    # leaving it in English, so these are skipped and the call site is
    # converted to i18n.t("Opened {n} tabs") by hand instead — see the
    # "templates" note in i18n.py.
    if s.endswith((" ", ":", "—", "(")) and not s.endswith("…"):
        return False
    return True


def _walk_strings(node: ast.AST):
    """Every string constant inside node, except the pieces of an f-string.

    An f-string is a JoinedStr whose literal halves are Constants like
    "Opened " and " tab(s) in Chrome". Collecting those would put half a
    sentence in front of a translator, and it could never match anything
    anyway: by the time setText() sees the value it is one assembled string.

    So f-strings are stepped over entirely. The way to make one translatable
    is to convert the call site to a template — i18n.t("Opened {n} tab(s)")
    .format(n=…) — which arrives here as a plain Constant inside a t() call.
    """
    if isinstance(node, ast.JoinedStr):
        return
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            yield node.value
        return
    for child in ast.iter_child_nodes(node):
        yield from _walk_strings(child)


def collect() -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}

    def note(value: str, where: str, forced: bool = False):
        # `forced` means the string was written inside an explicit t() call.
        # The author has already declared it copy, so the prose heuristics —
        # which reject a bare "sent" as an identifier and "{i}/{total} · {x}"
        # as punctuation — must not get a second opinion.
        if forced and value.strip():
            # NEVER still wins. A call site can declare something is copy, but
            # it cannot make the product's own name translatable — "Prism" is
            # "Prism" in every language, and a window titled with a translated
            # brand is a bug nobody would think to look for.
            if value.strip() in NEVER:
                return
            found.setdefault(value.strip(), set()).add(where)
            return
        if _is_copy(value):
            # Stored stripped: t() re-applies the caller's padding, so the
            # icon-spacing prefix on "  Start the work" must not fork the key.
            found.setdefault(value.strip(), set()).add(where)

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            # Forward slashes even on Windows: these paths are catalogue KEYS'
            # provenance, diffed in git, and a regeneration must not rewrite
            # every entry just because it ran on a different OS.
            rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except SyntaxError as exc:
                print(f"  ! skipped {rel}: {exc}", file=sys.stderr)
                continue

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = (func.attr if isinstance(func, ast.Attribute)
                            else func.id if isinstance(func, ast.Name) else "")
                    if name in TEXT_CALLS:
                        slots = ARG_SLOTS.get(name)
                        args = ([node.args[i] for i in slots
                                 if i < len(node.args)]
                                if slots else node.args)
                        explicit = name in ("t", "_t", "tr")
                        for arg in args:
                            for s in _walk_strings(arg):
                                note(s, rel, forced=explicit)
                        for kw in node.keywords:
                            # `tooltip`, `subtitle`, `body`, `action_text` and
                            # `detail` are how the shared components take most
                            # of their copy, and the two button() helpers put
                            # tooltip at different positions — so the keyword
                            # is the only reliable way to catch it.
                            if kw.arg in ("text", "tip", "tooltip", "title",
                                          "blurb", "label", "label_text",
                                          "placeholder", "desc", "subtitle",
                                          "body", "action_text", "detail"):
                                for s in _walk_strings(kw.value):
                                    note(s, rel)
                elif isinstance(node, ast.Assign):
                    targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                    if any(t in COPY_TABLES for t in targets):
                        for s in _walk_strings(node.value):
                            note(s, rel)

    for s in EXTRA:
        found.setdefault(s, set()).add("(built-in)")
    return {k: sorted(v) for k, v in sorted(found.items(), key=lambda kv: kv[0].lower())}


def main() -> int:
    old = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8")).get("strings", {})

    strings = collect()
    added = sorted(set(strings) - set(old))
    gone = sorted(set(old) - set(strings))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({
            "_comment": "Generated by devtools/extract_strings.py — do not "
                        "edit by hand. Maps each English UI string to the "
                        "files it appears in. Translation packs (lang/xx.json) "
                        "key off these exact strings.",
            "count": len(strings),
            "strings": strings,
        }, f, indent=1, ensure_ascii=False)
        f.write("\n")

    print(f"{len(strings)} strings → {os.path.relpath(OUT, ROOT)}")
    if added:
        print(f"\n  +{len(added)} new (need translating):")
        for s in added[:40]:
            print(f"      {s!r}")
        if len(added) > 40:
            print(f"      … and {len(added) - 40} more")
    if gone:
        print(f"\n  -{len(gone)} no longer used:")
        for s in gone[:20]:
            print(f"      {s!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
