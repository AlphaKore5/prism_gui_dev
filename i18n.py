"""Prism in the user's own language.

────────────────────────────────────────────────────────────────────────────
How this works, and why it isn't Qt's own translation system
────────────────────────────────────────────────────────────────────────────
The obvious route is QTranslator: wrap every string in self.tr(), run lupdate
to make .ts files, lrelease to compile them, and load a .qm at startup. It was
the wrong fit here for three reasons:

  · tr() only exists on QObject subclasses. Half of Prism's copy lives in
    plain module-level tables (sidebar.PRIMARY, agents_panel.STAGE_COPY) and
    in helper functions in widgets/controls.py, none of which are QObjects.
  · it would mean editing ~300 call sites across 16 files, and every new
    string after that would silently ship untranslated with nothing to catch it.
  · it needs the Qt linguist toolchain in the build, for a desktop app whose
    build story is already the fiddliest part of shipping it.

So Prism translates by VALUE instead of by call site. t() takes the English
string and returns the local one; install() patches the handful of Qt methods
that put text on screen so every widget goes through t() without a single
call site changing.

The safety property that makes patching Qt acceptable:

    A string is only ever replaced if it appears in lang/_catalogue.json.

The same setText() that draws "Start the work" also draws a customer's name, a
file path, an agent's brand name, and — through the output panel — whole
paragraphs written by Claude. None of those are in the catalogue, so none of
them can be touched. The catalogue is an allow-list, not a cache, and that is
the whole design. Run devtools/extract_strings.py after adding UI copy.

────────────────────────────────────────────────────────────────────────────
Templates
────────────────────────────────────────────────────────────────────────────
Value translation cannot see an f-string — by the time setText() has it, the
sentence is already assembled and matches nothing. Those call sites are
converted by hand to a placeholder form:

    self.count.setText(i18n.t("{on} steps of {total}").format(on=on, total=n))

which keeps ONE catalogue entry with the numbers marked, and lets a translator
put them wherever that language's grammar needs them.

────────────────────────────────────────────────────────────────────────────
Two different languages
────────────────────────────────────────────────────────────────────────────
"Language" here means the app's own words: buttons, labels, dialogs. What the
AI tools WRITE BACK is a separate setting (`output_language`), because they
are separate wishes — plenty of people want Prism in Gujarati and their client
deliverable in English. See prompt_directive().
"""
from __future__ import annotations

import json
import os

import paths

# code -> (English name, endonym, right-to-left?)
#
# The endonym is what goes in the picker: someone who needs the app in Hindi
# is exactly the person least helped by the word "Hindi" written in English.
LANGUAGES: dict[str, tuple[str, str, bool]] = {
    "en": ("English",   "English",   False),
    "hi": ("Hindi",     "हिन्दी",      False),
    "gu": ("Gujarati",  "ગુજરાતી",     False),
    "mr": ("Marathi",   "मराठी",      False),
    "bn": ("Bengali",   "বাংলা",       False),
    "ta": ("Tamil",     "தமிழ்",       False),
    "te": ("Telugu",    "తెలుగు",      False),
    "es": ("Spanish",   "Español",   False),
    "fr": ("French",    "Français",  False),
    "de": ("German",    "Deutsch",   False),
    "pt": ("Portuguese", "Português", False),
    "ar": ("Arabic",    "العربية",     True),
}

DEFAULT = "en"

# Barlow is the whole design system, and Barlow has no Devanagari, Gujarati,
# Bengali, Tamil, Telugu or Arabic glyphs. Qt will substitute per character
# when a family is missing one, but style.qss pins bare `font-family: "Barlow
# Condensed"` on every heading and button with no fallback listed at all —
# which is most of Prism's chrome. Leaving it to chance gets tofu boxes on
# Windows and a different substitute per widget on macOS.
#
# So the stylesheet's font stacks are extended at load time with families that
# actually cover the active script, newest first, then the platform's own.
# Latin-script languages need nothing: Barlow already covers them.
SCRIPT_FONTS: dict[str, tuple[str, ...]] = {
    "hi": ("Noto Sans Devanagari", "Kohinoor Devanagari",
           "Devanagari Sangam MN", "Nirmala UI", "Mangal"),
    "mr": ("Noto Sans Devanagari", "Kohinoor Devanagari",
           "Devanagari Sangam MN", "Nirmala UI", "Mangal"),
    "gu": ("Noto Sans Gujarati", "Gujarati Sangam MN", "Nirmala UI", "Shruti"),
    "bn": ("Noto Sans Bengali", "Bangla Sangam MN", "Nirmala UI", "Vrinda"),
    "ta": ("Noto Sans Tamil", "Tamil Sangam MN", "Nirmala UI", "Latha"),
    "te": ("Noto Sans Telugu", "Telugu Sangam MN", "Nirmala UI", "Gautami"),
    "ar": ("Noto Sans Arabic", "Geeza Pro", "Segoe UI", "Tahoma"),
}

_active: dict[str, str] = {}
_active_code = DEFAULT
_installed = False


# ── where packs live ──────────────────────────────────────────────────────
def _bundled(code: str) -> str:
    """A pack shipped with Prism."""
    return paths.resource("lang", f"{code}.json")


def _user(code: str) -> str:
    """A pack the user (or a translator working for them) supplied.

    Kept outside the bundle on purpose: a onefile build wipes and re-extracts
    its payload on every launch, so anything written next to the executable is
    gone by the next start. ~/.prism survives, and is the same folder the CLI
    reads — one translation serves both apps.
    """
    return paths.user_dir("lang", f"{code}.json")


def catalogue() -> dict[str, list[str]]:
    """Every English string Prism is allowed to translate, and where it's
    used. Empty (translation simply off) if the file didn't ship."""
    try:
        with open(paths.resource("lang", "_catalogue.json"),
                  encoding="utf-8") as f:
            return json.load(f).get("strings", {})
    except (OSError, ValueError):
        return {}


def _read(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    entries = data.get("strings", data)
    if not isinstance(entries, dict):
        return {}
    # Blank values are the normal state of a half-finished pack. Dropping them
    # here means an untranslated string falls back to English instead of
    # rendering as an empty label, which looks like a broken build.
    return {k: v for k, v in entries.items()
            if isinstance(v, str) and v.strip()}


def available() -> list[tuple[str, str, str]]:
    """(code, English name, endonym) for English plus every language that has
    a pack — bundled or user-supplied. Drives the Settings picker, so it never
    offers a language that would come out entirely in English."""
    out = [("en", "English", "English")]
    for code, (name, native, _rtl) in LANGUAGES.items():
        if code == "en":
            continue
        if os.path.exists(_bundled(code)) or os.path.exists(_user(code)):
            out.append((code, name, native))
    return out


def coverage(code: str) -> tuple[int, int]:
    """(translated, total) — how complete a pack is. Shown in Settings so a
    partial pack is an informed choice rather than a surprise."""
    total = len(catalogue())
    if code == "en" or not total:
        return total, total
    pack = {**_read(_bundled(code)), **_read(_user(code))}
    return sum(1 for k in catalogue() if pack.get(k)), total


# ── the lookup ────────────────────────────────────────────────────────────
def load(code: str) -> None:
    """Make `code` the active language for every later t() call.

    A user pack layered over the bundled one, so someone can correct a single
    phrase for their own copy without maintaining a whole file.
    """
    global _active, _active_code
    code = code if code in LANGUAGES else DEFAULT
    _active_code = code
    if code == DEFAULT:
        _active = {}
        return
    allowed = catalogue()
    merged = {**_read(_bundled(code)), **_read(_user(code))}
    # Intersect with the catalogue. A pack is a data file that can be edited
    # by hand or generated by a script, and without this an extra key in it
    # could rewrite text the catalogue never sanctioned — a stage's output,
    # say. Enforced at load so t() stays a plain dict lookup.
    _active = {k: v for k, v in merged.items() if k in allowed}


def current() -> str:
    return _active_code


def is_rtl(code: str | None = None) -> bool:
    return LANGUAGES.get(code or _active_code, ("", "", False))[2]


# English sentences that are untrue while AI runs on Prism's server (they
# talk about Chrome, sign-ins and the customer's own keys). ai_server.install()
# registers {old: new}; t() swaps them before any lookup, so the screens that
# hold the old words in module-level lists need no per-screen switch. The new
# sentence has no translation yet and shows in English.
_reworded: dict = {}


def set_rewording(mapping: dict) -> None:
    _reworded.clear()
    _reworded.update(mapping or {})


def t(text: str) -> str:
    """English in, the active language out — or English back, unchanged.

    Surrounding whitespace is preserved around the lookup. Prism pads button
    labels for icon spacing ("  Start the work", " Save"), and without this
    every one of those would be a separate catalogue entry that a translator
    would have to get the padding right on.
    """
    if _reworded:
        s0 = str(text)
        new = _reworded.get(s0.strip())
        if new is not None:
            text = s0[:len(s0) - len(s0.lstrip())] + new + s0[len(s0.rstrip()):]
    if not _active:
        return text
    s = str(text)
    core = s.strip()
    if not core:
        return s
    hit = _active.get(core)
    if hit is None:
        return s
    lead = s[:len(s) - len(s.lstrip())]
    trail = s[len(s.rstrip()):]
    return f"{lead}{hit}{trail}"


# ── what the AI tools write back ──────────────────────────────────────────
def prompt_directive(code: str) -> str:
    """The line that makes the tools answer in `code`.

    Delegates to the engine (core/lang.py), which is where prompts are
    actually assembled and which the CLI shares. Kept here as a re-export so
    the GUI has one obvious place to look for anything language-shaped, and so
    a test can assert the two modules still agree about the codes.
    """
    import core_bridge as CB
    return CB.lang.directive(code)


# ── making Qt go through t() ──────────────────────────────────────────────
def install() -> None:
    """Route every Qt call that puts words on screen through t().

    Must run before the first widget is built — a QLabel constructed earlier
    keeps whatever text it was given.

    Constructors need wrapping as well as setters: QLabel("Save") never calls
    setText at all, it hands the string straight to C++. The first *string*
    positional argument is the one translated, rather than argument 0, so both
    QPushButton("Save") and QPushButton(icon, "Save") are covered.

    Deliberately NOT patched: QLineEdit, QTextEdit and QPlainTextEdit
    constructors, and setPlainText/setHtml/setMarkdown. Those carry content —
    the user's API key, a draft email, a stage's output — not labels. The
    catalogue would refuse them anyway; leaving them alone means never having
    to rely on that.
    """
    global _installed
    if _installed:
        return

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import (
        QAbstractButton, QComboBox, QGroupBox, QLabel, QLineEdit,
        QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QTextEdit,
        QTreeWidgetItem, QWidget,
    )

    def wrap_setter(cls, name: str, index: int = 0):
        """Translate one string argument of one method, in place."""
        original = getattr(cls, name, None)
        if original is None:
            return

        def replacement(self, *args, **kwargs):
            args = list(args)
            if len(args) > index and isinstance(args[index], str):
                args[index] = t(args[index])
            return original(self, *args, **kwargs)

        setattr(cls, name, replacement)

    def wrap_ctor(cls):
        """Translate the first string argument handed to a constructor."""
        original = cls.__init__

        def __init__(self, *args, **kwargs):
            args = list(args)
            for i, a in enumerate(args):
                if isinstance(a, str):
                    args[i] = t(a)
                    break
            original(self, *args, **kwargs)

        cls.__init__ = __init__

    def wrap_static(cls, name: str, indices: tuple[int, ...]):
        """QMessageBox.warning(parent, title, body) and friends — the parent
        occupies argument 0, so the copy starts at 1."""
        original = getattr(cls, name, None)
        if original is None:
            return

        def replacement(*args, **kwargs):
            args = list(args)
            for i in indices:
                if len(args) > i and isinstance(args[i], str):
                    args[i] = t(args[i])
            return original(*args, **kwargs)

        setattr(cls, name, staticmethod(replacement))

    # Labels and captions.
    wrap_setter(QWidget, "setToolTip")
    wrap_setter(QWidget, "setStatusTip")
    wrap_setter(QWidget, "setWhatsThis")
    wrap_setter(QWidget, "setWindowTitle")
    wrap_setter(QLabel, "setText")
    # Covers QPushButton, QCheckBox and QRadioButton in one go.
    wrap_setter(QAbstractButton, "setText")
    wrap_setter(QGroupBox, "setTitle")
    wrap_setter(QAction, "setText")
    wrap_setter(QListWidgetItem, "setText")
    wrap_setter(QTreeWidgetItem, "setText", index=1)   # (column, text)

    # Prompts inside empty inputs are copy, even though their contents are not.
    for cls in (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox):
        wrap_setter(cls, "setPlaceholderText")

    # Dropdown entries — the category pickers in Setup are built from these.
    wrap_setter(QComboBox, "addItem")
    wrap_setter(QComboBox, "setItemText", index=1)
    _add_items = QComboBox.addItems
    QComboBox.addItems = lambda self, items: _add_items(self, [t(i) for i in items])

    # Message boxes, both shapes.
    for name in ("information", "warning", "critical", "question", "about"):
        wrap_static(QMessageBox, name, (1, 2))
    wrap_setter(QMessageBox, "setText")
    wrap_setter(QMessageBox, "setInformativeText")

    # NOT patched, on purpose: QFileDialog's static methods.
    #
    # They were, briefly, to translate the caption — and file attaching stopped
    # working. These statics are the entry point to a NATIVE OS panel, not to a
    # Qt widget: wrapping them puts a Python frame in the middle of a call that
    # hands control to Cocoa (and to the Windows shell), and the overload
    # resolution and return marshalling are Shiboken's, not ours to stand in
    # front of.
    #
    # The trade was bad even if it had worked. macOS does not display a title
    # on an open panel at all, so the patch bought nothing on the platform
    # Prism is developed on, in exchange for owning the code path that every
    # single attachment goes through.
    #
    # Captions are still translated — the call sites pass i18n.t("…")
    # themselves, which is explicit, greppable, and cannot break the dialog.
    # Same reasoning for QInputDialog.getText.

    for cls in (QLabel, QPushButton, QGroupBox, QAction, QListWidgetItem):
        wrap_ctor(cls)
    # QCheckBox/QRadioButton subclass QAbstractButton but each defines its own
    # __init__, so the base class is not enough.
    from PySide6.QtWidgets import QCheckBox, QRadioButton, QToolButton
    for cls in (QCheckBox, QRadioButton, QToolButton):
        wrap_ctor(cls)

    # ── every QLabel is plain text unless it asks not to be ──────────────
    #
    # QLabel defaults to Qt.AutoText, which runs a heuristic over the string
    # and renders it as HTML if it looks like markup. The register panels feed
    # it values that come from customer email: register.py fills "Customer"
    # from the From display name and "Product asked" from the message body, so
    # both are written by whoever emails the sales inbox. The sharpest one is
    # the quotation dialog, which is the screen the owner reads to decide a
    # price.
    #
    # Done HERE rather than in the four _label() helpers because the helpers
    # are not the whole surface — the worst sinks are bare QLabel(...) calls,
    # and Pill/Avatar/ToolBadge are subclasses. This constructor is the one
    # place all 142 of them already pass through.
    #
    # It is also cheaper: AutoText makes Qt scan every string with
    # mightBeRichText() on each setText; PlainText skips that outright.
    _translating_init = QLabel.__init__

    def _plain_by_default_init(self, *args, **kwargs):
        _translating_init(self, *args, **kwargs)
        if "textFormat" not in kwargs:      # an explicit request still wins
            self.setTextFormat(Qt.TextFormat.PlainText)

    QLabel.__init__ = _plain_by_default_init

    _installed = True


def style_for_script(qss: str, code: str | None = None) -> str:
    """Append script-appropriate fallbacks to every font stack in the QSS.

    Rewrites `font-family: "Barlow Condensed";` into
    `font-family: "Barlow Condensed", "Noto Sans Devanagari", …;` so a heading
    whose glyphs Barlow does not have still lands on one chosen family rather
    than whatever Qt happens to substitute for that particular widget.

    Returns the stylesheet unchanged for Latin-script languages, which is
    every case where Barlow already has the glyphs.
    """
    import re

    fonts = SCRIPT_FONTS.get(code or _active_code)
    if not fonts:
        return qss
    extra = ", ".join(f'"{f}"' for f in fonts)

    def extend(match: "re.Match") -> str:
        stack = match.group(1).rstrip().rstrip(";")
        if extra.split(",")[0] in stack:      # already extended
            return match.group(0)
        return f"font-family: {stack}, {extra};"

    return re.sub(r"font-family:\s*([^;}]+);", extend, qss)


def apply_to(app) -> None:
    """Set the application-wide layout direction for the active language.

    Arabic and Hebrew mirror the whole interface — the rail moves to the right
    and every row reverses. Qt does this for the entire widget tree from one
    call, so it belongs next to the language rather than in any one widget.
    """
    from PySide6.QtCore import Qt
    app.setLayoutDirection(Qt.RightToLeft if is_rtl() else Qt.LeftToRight)


def start(cfg: dict, app=None) -> None:
    """One call for main.py: read the saved language, install, apply."""
    load(cfg.get("language") or DEFAULT)
    install()
    if app is not None:
        apply_to(app)
