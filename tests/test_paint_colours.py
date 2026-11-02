"""Tint colours must survive being painted.

The theme's tints (OK_BG, WARN_BG, ERR_BG, INFO_BG, CARD, HAIRLINE, ...) became
CSS `rgba(...)` strings when the glass theme landed. Qt's `QColor("rgba(...)")`
cannot parse that: it returns an INVALID colour, and a QPainter brush set to an
invalid colour paints solid black. Nothing raised. The Status pills and Fit
chips in Leads, the Inquiry register's status pills and every progress track
came out black-on-black in the running app while every test stayed green —
because no test ever looked at a pixel.

So these tests look at pixels. Each one paints the real widget and asserts the
tint is light, not black, and a static scan keeps the raw call from coming back.
"""
from __future__ import annotations

import ast
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem  # noqa: E402

_app = QApplication.instance() or QApplication([])

import theme  # noqa: E402

# What main.py does before any widget exists. Without it these tests paint over
# whatever palette the DESKTOP has -- dark mode made the bevel roles dark and
# two of them failed on any machine set to dark, while the shipped app was
# never at fault in that way.
theme.apply_palette(_app)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _is_black(c: QColor) -> bool:
    return c.red() < 60 and c.green() < 60 and c.blue() < 60


def _rgba_tokens() -> set:
    return {n for n in dir(theme) if n.isupper() and isinstance(getattr(theme, n), str)
            and getattr(theme, n).strip().startswith("rgba")}


# ── the helpers ──────────────────────────────────────────────────────────────

def test_every_rgba_token_is_readable_by_the_themes_own_helpers():
    tokens = _rgba_tokens()
    # CARD left this set in the AlphaKore re-skin: the card is a solid white hex now,
    # not frosted rgba. The guard is unchanged for every token that is still rgba.
    assert {"OK_BG", "WARN_BG", "ERR_BG", "INFO_BG"} <= tokens
    for name in tokens:
        value = getattr(theme, name)
        assert theme.qcolor(value).isValid(), name
        assert theme.c(value).isValid(), name


def test_theme_c_keeps_the_alpha_of_an_rgba_token():
    got = theme.c(theme.OK_BG)
    assert got.alpha() < 80 and (got.red(), got.green(), got.blue()) == (22, 163, 74)


def test_an_unreadable_colour_is_transparent_never_black():
    """The failure mode this file exists for, pinned: bad input must fall back
    to nothing, not to a black rectangle."""
    assert theme.qcolor("not a colour").alpha() == 0
    assert theme.c("not a colour").alpha() == 0


# ── the widgets, painted ─────────────────────────────────────────────────────

def _grab_cell(table: QTableWidget, row: int, col: int):
    table.resize(900, 120)
    table.show()
    image = table.grab().toImage()
    return image, table.visualRect(table.model().index(row, col))


def test_the_leads_status_pill_is_tinted_not_black():
    from addons.leads import cockpit as CK
    from prospector.models import Dossier, Lead
    lead = Lead(name="Asha", title="Owner", company="Patel Fab", email="a@x.com",
                fit_score=90.0)
    lead.extra = {"email_check": "valid"}
    c = CK.LeadsCockpit()
    c.set_dossiers([Dossier(lead=lead, verdict="hot", score=90, signal_status="found")])
    c.resize(1100, 500)
    c.show()
    table = c._table
    image = table.viewport().grab().toImage()   # visualRect() is in viewport coordinates
    for col, label in ((CK._C_STATUS, "status"), (CK._C_FIT, "fit")):
        rect = table.visualRect(table.model().index(0, col))
        assert rect.isValid(), label
        # A few pixels inside the pill's left/right end, vertically centred: the
        # tint, before the text starts.
        x = (rect.left() + CK._PAD + 5) if col == CK._C_STATUS else (rect.right() - CK._PAD - 5)
        pixel = image.pixelColor(x, rect.center().y())
        assert not _is_black(pixel), \
            f"the {label} pill painted black ({pixel.name()}) — an rgba token went through QColor()"


def test_the_leads_signal_pill_is_tinted_not_black():
    from addons.leads import cockpit as CK
    from prospector.models import Dossier, Lead
    c = CK.LeadsCockpit()
    c.set_dossiers([Dossier(lead=Lead(name="A", email="a@x.com", fit_score=80.0),
                            verdict="warm", score=80, signal_status="found")])
    c.resize(1100, 500)
    c.show()
    table = c._table
    image = table.viewport().grab().toImage()   # visualRect() is in viewport coordinates
    rect = table.visualRect(table.model().index(0, CK._C_SIGNAL))
    pixel = image.pixelColor(rect.left() + CK._PAD + 5, rect.center().y())
    assert not _is_black(pixel), f"the why-now pill painted black ({pixel.name()})"


def test_the_inquiry_register_status_pill_is_tinted_not_black():
    from addons.inquiry.register_table import TONE_ROLE, StatusPillDelegate
    table = QTableWidget(1, 1)
    item = QTableWidgetItem("Quoted")
    item.setData(TONE_ROLE, "ok")
    table.setItem(0, 0, item)
    table.setItemDelegate(StatusPillDelegate(table))
    table.horizontalHeader().hide()
    table.verticalHeader().hide()
    table.setColumnWidth(0, 300)
    image, rect = _grab_cell(table, 0, 0)
    pixel = image.pixelColor(rect.left() + 9, rect.center().y())
    assert not _is_black(pixel), f"the register pill painted black ({pixel.name()})"


def test_a_progress_track_is_light_not_black():
    from widgets import controls as C
    bar = C.ProgressBar(0.25)
    bar.resize(200, 5)
    image = bar.grab().toImage()
    assert not _is_black(image.pixelColor(190, 2)), "the unfilled track painted black"


# ── the static guard ─────────────────────────────────────────────────────────

def test_no_source_file_hands_an_rgba_token_straight_to_qcolor():
    """`QColor(theme.OK_BG)` compiles, runs and paints black. Use
    theme.qcolor(...). This scans every shipped .py for the literal pattern."""
    tokens = _rgba_tokens()
    offenders = []
    skip = {"venv", ".venv", ".git", "__pycache__", "prism_terminal", "tests", "node_modules"}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                tree = ast.parse(open(path, encoding="utf-8").read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and node.args):
                    continue
                fn = node.func
                fname = fn.id if isinstance(fn, ast.Name) else \
                    fn.attr if isinstance(fn, ast.Attribute) else ""
                arg = node.args[0]
                if fname == "QColor" and isinstance(arg, ast.Attribute) \
                        and isinstance(arg.value, ast.Name) and arg.value.id == "theme" \
                        and arg.attr in tokens:
                    offenders.append(f"{os.path.relpath(path, ROOT)}:{node.lineno} "
                                     f"QColor(theme.{arg.attr})")
    assert not offenders, "use theme.qcolor(): " + "; ".join(offenders)


def test_no_html_bgcolor_uses_rgba_token():
    """Qt's QTextHtmlParser silently maps any unrecognised `bgcolor` value to
    #000000 (pitch black). `rgba(...)` strings are not recognised. This test
    scans every .py that contains `bgcolor=` f-string patterns and ensures none
    of them embed a theme token that resolves to an rgba() string.

    The only safe values for `bgcolor` are solid 6-digit hex strings.
    Use `theme.HTML_ERR_BG`, `theme.HTML_OK_BG`, etc., or call `theme.html_bg()`.
    """
    # rgba token names from the live theme module
    tokens = _rgba_tokens()
    import re
    # grep source files for   bgcolor='{theme.SOMETHING}'
    # or                       bgcolor="{theme.SOMETHING}"
    pattern = re.compile(r"""bgcolor=['"][^'"]*\{theme\.(\w+)\}[^'"]*['"]""")
    offenders = []
    skip = {"venv", ".venv", ".git", "__pycache__", "prism_terminal", "tests", "node_modules"}
    for root, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in skip]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                src = open(path, encoding="utf-8").read()
            except (OSError, UnicodeDecodeError):
                continue
            for m in pattern.finditer(src):
                attr = m.group(1)
                # Only flag if the token resolves to an rgba() string
                # e.g. ACCENT_RAMP is a dict — skip it, the key determines the value
                val = getattr(theme, attr, None)
                if isinstance(val, str) and val.strip().startswith("rgba"):
                    lineno = src[:m.start()].count("\n") + 1
                    offenders.append(
                        f"{os.path.relpath(path, ROOT)}:{lineno} "
                        f"bgcolor uses rgba token theme.{attr} — use theme.HTML_* or theme.html_bg()"
                    )
    assert not offenders, "bgcolor+rgba will render black: " + "; ".join(offenders)



# ── the application palette ──────────────────────────────────────────────────

def test_the_palette_is_light_whatever_the_desktop_is_set_to():
    """Seven pinned roles left placeholder text, selection, the bevels and the
    Disabled group to the OS. All of them are fixed values now."""
    from PySide6.QtGui import QPalette
    p = _app.palette()
    assert not _is_black(p.color(QPalette.Window))
    for role in (QPalette.Light, QPalette.Midlight, QPalette.Mid):
        assert not _is_black(p.color(role)), role
    assert p.color(QPalette.Highlight).name() == theme.qcolor(theme.ACCENT).name()
    assert p.color(QPalette.PlaceholderText) != p.color(QPalette.Text), \
        "placeholder text must not look like typed text"
    assert p.color(QPalette.Disabled, QPalette.Text) != p.color(QPalette.Active, QPalette.Text), \
        "disabled text must look disabled"
    assert p.color(QPalette.Disabled, QPalette.ButtonText).name() == "#b7b7ba"
