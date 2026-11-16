"""The Email inquiries pipeline board: one column per stage, a card per
inquiry, a KPI strip on top.

It is a VIEW over InquiryDialog's state and holds no copy of it. Every
refresh reads `host._register_rows`, the worklist once, and the client's
pipeline settings (inquiry_config.pipeline_of). Where a card sits comes from
the engine (CB.inquiry_stage -> register.stage_of), never from here, so the
board, the KPI counts and the client file cannot disagree.

The words on screen are the client's: stage labels and the words for a
quotation and a PO come from cfg["inquiry"]["pipeline"]. A label left at its
default is shown through i18n.t, so a Hindi UI still translates "Inquiry";
a client's own "Enquiry" is shown exactly as typed.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal, QRectF, QSize
from PySide6.QtGui import (
    QFont, QFontMetrics, QPainter, QPainterPath, QPen, QTextCharFormat, QTextLayout,
)
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)

import core_bridge as CB
import i18n
import theme
import inquiry_config
from widgets import controls as C

# Stage -> REGISTER_TONES key (header tint, stripe, KPI tile).
STAGE_TONES = {"inquiry": "new", "quoted": "quoted", "nego": "negotiating",
               "po": "no_reply", "won": "won", "lost": "lost"}
STAGE_ICONS = {"inquiry": "inbox", "quoted": "file", "nego": "message-circle",
               "po": "check-square", "won": "check"}

# The words under each column title. Named LABELS so extract_strings picks
# them up (COPY_TABLES); translated at render time.
LABELS = {
    "inquiry": "New, or waiting on details",
    "quoted": "Sent — waiting, reminders, revisions",
    "nego": "They countered — hold, or revise",
    "po": "Check it against the final quotation",
    "po_proforma": "Check it, or wait for it / the advance",
    "won": "Order confirmed",
}

# What Prism read a pending reply as -> (pill text, tone).
COPY = {
    "negotiating": ("Better rate?", "negotiating"),
    "needs_info": ("Question", "no_reply"),
    "accepted": ("Said yes", "won"),
    "rejected": ("Said no", "lost"),
    "unclear": ("Your eye", "quoted"),
}

ORDER = ("inquiry", "quoted", "nego", "po", "won")


# ── pure helpers (no widgets) ─────────────────────────────────────────────
def pipeline(cfg: dict) -> dict:
    return inquiry_config.pipeline_of(cfg or {})


def stage_text(p: dict, stage: str) -> str:
    """The client's word for a stage: translated when it is still Prism's
    default, verbatim when the client typed their own."""
    default = inquiry_config.PIPELINE_DEFAULTS["labels"].get(stage, stage)
    value = (p.get("labels") or {}).get(stage, default)
    if stage == "lost":
        return i18n.t("Lost")
    return i18n.t(default) if value == default else value


def word_text(p: dict, key: str) -> str:
    default = inquiry_config.PIPELINE_DEFAULTS["words"].get(key, key)
    value = (p.get("words") or {}).get(key, default)
    if value == default or value in inquiry_config.WORDS.get(key, ()):
        return i18n.t(value)        # one of the offered words: translated
    return value


def columns(p: dict) -> list[str]:
    """The board's columns, in order. Negotiation off -> four."""
    steps = p.get("steps") or {}
    return [s for s in ORDER if s != "nego" or steps.get("negotiation", True)]


def place(rows: list[dict], p: dict) -> dict[str, list[tuple[dict, str]]]:
    """{stage: [(row, sub), ...]} for every row, lost included."""
    out: dict[str, list] = {s: [] for s in (*ORDER, "lost")}
    for row in rows:
        stage, sub = CB.inquiry_stage(row, p)
        out.setdefault(stage, []).append((row, sub))
    return out


# ── a stable key per card (review R9) ─────────────────────────────────────
# A card is keyed by its inquiry number when that number is there and is
# the only one of its kind. A row with no number (an imported old list) or
# a number shared with another row (an Excel copy-paste) gets "#<print>@<i>"
# instead: what the row says, plus where it sits. Keying those by the
# number made every blank card one card — clicking did nothing, ticking one
# ticked them all, and the bulk delete found none.
def _print(row: dict) -> str:
    import hashlib
    text = "\x1f".join(str(row.get(c, "")) for c in (
        "Inquiry no", "Date received", "Time received", "Customer", "Email",
        "Product asked", "Quotation no"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def card_keys(rows: list[dict]) -> dict[int, str]:
    """{id(row): key} for every row."""
    counts: dict[str, int] = {}
    for r in rows:
        no = (r.get("Inquiry no") or "").strip()
        counts[no] = counts.get(no, 0) + 1
    out = {}
    for i, r in enumerate(rows):
        no = (r.get("Inquiry no") or "").strip()
        out[id(r)] = no if no and counts[no] == 1 else f"#{_print(r)}@{i}"
    return out


def row_for_key(rows: list[dict], key: str) -> dict | None:
    """The row a card key names, or None when it is gone."""
    if not key:
        return None
    if not key.startswith("#"):
        same = [r for r in rows if (r.get("Inquiry no") or "").strip() == key]
        return same[0] if len(same) == 1 else None
    fp, _, index = key[1:].partition("@")
    try:
        i = int(index)
    except ValueError:
        i = -1
    if 0 <= i < len(rows) and _print(rows[i]) == fp:
        return rows[i]
    for r in rows:                          # moved since the key was made
        if _print(r) == fp:
            return r
    return None


def money_value(row: dict) -> float:
    for key in ("Order value", "Quotation value"):
        text = (row.get(key) or "").strip()
        if text:
            try:
                return float(CB.get_register().money(text))
            except Exception:                           # noqa: BLE001
                continue
    return 0.0


def due_state(row: dict, p: dict, today: date | None = None) -> tuple[str, int]:
    """("over", days) / ("today", 0) / ("later", days) for a quoted row —
    the reminder clock the follow-up list runs on."""
    register = CB.get_register()
    today = today or date.today()
    last = (register.parse_date(row.get("Last contact", ""))
            or register.parse_date(row.get("Quotation date", "")))
    if last is None:
        return "later", 0
    due = last + timedelta(days=int(p.get("remind_days") or 2))
    diff = (today - due).days
    if diff > 0:
        return "over", diff
    if diff == 0:
        return "today", 0
    return "later", -diff


def reminders_sent(row: dict) -> int:
    try:
        return int(str(row.get("Reminders sent") or "0").strip() or 0)
    except ValueError:
        return 0


def kpis(placed: dict, p: dict, today: date | None = None) -> list[tuple]:
    """[(stage, count, detail), ...] — one per board column. The count is
    exactly that column's count."""
    out = []
    for stage in columns(p):
        items = placed.get(stage, [])
        if stage == "inquiry":
            n = sum(1 for _r, s in items if s == "you")
            detail = i18n.t("{n} your turn").replace("{n}", str(n))
        elif stage == "quoted":
            n = sum(1 for r, s in items if s != "countered"
                    and due_state(r, p, today)[0] in ("over", "today"))
            detail = i18n.t("{n} overdue").replace("{n}", str(n))
        elif stage == "nego":
            reg = CB.get_register()
            n = sum(1 for r, _s in items
                    if (r.get(reg.TURN) or "you").strip().lower() != reg.TURN_THEM)
            detail = i18n.t("{n} your turn").replace("{n}", str(n))
        elif stage == "po":
            n = sum(1 for _r, s in items if s in ("check", "nopo"))
            detail = i18n.t("{n} to check").replace("{n}", str(n))
        else:
            total = sum(money_value(r) for r, _s in items)
            detail = inquiry_config.format_money(total, p.get("currency", "₹")) \
                if total else i18n.t("nothing yet")
        out.append((stage, len(items), detail))
    return out


def min_column_width(fm: QFontMetrics) -> int:
    """A column fits a customer's name and a "You ₹1,25,000 vs They …" row."""
    return fm.averageCharWidth() * 22 + 2 * theme.SPACE_3


def board_min_width(fm: QFontMetrics, p: dict) -> int:
    n = len(columns(p))
    col = min_column_width(fm)
    return int(col * (n - 1) + col * 0.8) + theme.SPACE_2 * (n - 1)


# ── what a card quotes from a reply ───────────────────────────────────────
# Where the client's own words end and the thread they replied to begins:
# "On 3 Oct, Parth wrote:", Outlook's "-----Original Message-----" or a
# "From: …" block, a "> " quoted line, a phone footer.
_QUOTED_START = re.compile(
    r"^\s*(?:on\b.{0,120}\bwrote:?\s*$|-{2,}\s*original message|-{2,}\s*forwarded"
    r"|from:\s|sent from my\b|>)", re.IGNORECASE)
# "Dear Sir," / "Hi," / "Hello Parth," / "Good morning team," / "Respected
# Sir," at the very top. Only up to its own comma, colon, "!" or line end —
# "Hi we need 50 pcs" keeps every word, because there is no greeting to cut.
_GREETING = re.compile(
    r"^\s*(?:dear|hi|hello|hey|hii+|respected|greetings|namaste|good\s+"
    r"(?:morning|afternoon|evening|day))\b[^\n,!:.]{0,40}(?:[,!:.]+[ \t]*|\s*\n)",
    re.IGNORECASE)


def bubble_text(body: str) -> str:
    """The sentence a card quotes: the client's latest words, without the
    thread underneath them, the greeting above them or blank lines."""
    lines = []
    for line in str(body or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if _QUOTED_START.match(line):
            break
        lines.append(line)
    text = "\n".join(lines).strip()
    for _ in range(3):                      # "Hi,\n\nGood morning," — both go
        cut = _GREETING.sub("", text, count=1).lstrip()
        if cut == text or not cut:
            break
        text = cut
    return " ".join(text.split())


def clamp_lines(head: str, text: str, font: QFont, bold: QFont, width: int,
                lines: int = 2) -> list[str]:
    """`head` (shown bold) + `text`, broken the way Qt breaks it at `width`,
    cut to `lines` lines; the last kept line ends in … when anything was cut.
    Returns the lines as plain text, the first starting with `head`."""
    full = f"{head} {text}" if head else text
    width = max(1, int(width))
    layout = QTextLayout(full, font)
    if head:
        fmt = QTextCharFormat()
        fmt.setFont(bold)
        rng = QTextLayout.FormatRange()
        rng.start, rng.length, rng.format = 0, len(head), fmt
        layout.setFormats([rng])
    layout.beginLayout()
    spans = []
    while True:
        line = layout.createLine()
        if not line.isValid():
            break
        line.setLineWidth(width)
        spans.append((line.textStart(), line.textLength()))
    layout.endLayout()
    if len(spans) <= lines:
        return [full[a:a + n].rstrip() for a, n in spans] or [full]
    out = [full[a:a + n].rstrip() for a, n in spans[:lines - 1]]
    start = spans[lines - 1][0]
    rest = " ".join(full[start:].split())
    fm = QFontMetrics(bold if start < len(head) else font)
    out.append(fm.elidedText(rest + " …", Qt.ElideRight, width)
               if fm.horizontalAdvance(rest) <= width
               else fm.elidedText(rest, Qt.ElideRight, width))
    return out


# ── small widgets ─────────────────────────────────────────────────────────
def _tone(key: str) -> tuple[str, str]:
    return theme.register_tones().get(key, theme.register_tones()["quoted"])


class TonePill(QLabel):
    """A small upper-case pill in a REGISTER_TONES pair."""

    def __init__(self, text: str, tone: str, parent=None):
        super().__init__(text.upper(), parent)
        bg, ink = _tone(tone)
        self.setObjectName("boardPill")
        self.setStyleSheet(
            f"QLabel#boardPill {{ background: {bg}; color: {ink}; "
            f"border-radius: 6px; padding: 2px 7px; "
            f"font-family: {theme.FONT_MONO_STACK}; "
            f"font-size: 10px; font-weight: 500; }}")
        C.track(self, 0.06)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)


class Elided(QLabel):
    """One line, cut with … to the width it is given."""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full = text
        self.setMinimumWidth(10)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(text)
        super().setText(text)

    def setText(self, text: str):                       # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        width = max(10, self.width())
        super().setText(self.fontMetrics().elidedText(
            self._full, Qt.ElideRight, width))


class _Said(QLabel):
    """What they said, in a grey bubble: "<b>Who:</b> text", clamped to two
    lines at the width the card actually gives it. Clamping at a fixed
    width made the label's minimum width that line's width, which pushed
    every card in a narrow column under its scroll bar."""

    _PAD = 12                                           # padding: 3px 6px

    def __init__(self, who: str, text: str, parent=None):
        super().__init__(parent)
        self._who, self._text = who, text
        self.setObjectName("boardSaid")
        self.setTextFormat(Qt.RichText)
        self.setMinimumWidth(10)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setToolTip(f"{who}: {text}")
        self.setStyleSheet(
            "QLabel#boardSaid { background: %s; border-radius: 6px;"
            " padding: 3px 6px; %s }" % (theme.NEUTRAL[100],
                                        theme.type_css("SUPPORT", theme.NEUTRAL[700])))
        self._lines = 0
        self._clamp(200)

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        self._clamp(self.width())

    def _clamp(self, width: int):
        hd = f"{self._who}: "
        lines = clamp_lines(hd, self._text, theme.font("SUPPORT", 400),
                            theme.font("SUPPORT", 700),
                            max(20, width - self._PAD), lines=2)
        first = lines[0]
        rest = first[len(hd):] if first.startswith(hd) else first
        html = [f"<b>{_esc(self._who)}:</b> {_esc(rest)}"]
        if len(lines) > 1:
            html.append(_esc(lines[1]))
        super().setText("<br>".join(html))
        if len(lines) != self._lines:
            self._lines = len(lines)
            self.updateGeometry()


def _meta(text: str, icon: str = "") -> QLabel:
    lab = C.label(text, "meta")
    if icon:
        lab.setText(text)
    return lab


class BoardCard(QFrame):
    """One inquiry on the board. Opaque white with a hairline edge; the stage
    tone is carried by its pill and its column, not by a stripe."""
    clicked = Signal(str)

    def __init__(self, row: dict, *, head: str, pill: tuple | None,
                 product: str, tone: str, said: tuple | None = None,
                 price: tuple | None = None, meta: list | None = None,
                 amount: str = "", dim: bool = False, picked: bool | None = None,
                 current: bool = False, parent=None):
        super().__init__(parent)
        self.inquiry_no = row.get("Inquiry no", "")
        self.key = self.inquiry_no          # BoardView sets the card key
        self.setObjectName("boardCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName(f"{self.inquiry_no} {row.get('Customer', '')}")
        self._stripe = _tone(tone)[1]
        self._dim = dim
        self._current = current
        self._picked = picked
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2 + 2,
                               theme.SPACE_3, theme.SPACE_2 + 2)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(theme.SPACE_1)
        if picked is not None:
            self.tick = QLabel("✓" if picked else "")
            self.tick.setObjectName("boardTick")
            self.tick.setFixedSize(16, 16)
            self.tick.setAlignment(Qt.AlignCenter)
            self.tick.setStyleSheet(
                "QLabel#boardTick { border: 1px solid %s; border-radius: 4px;"
                " background: %s; color: white; font-weight: 700; }"
                % (theme.NEUTRAL[400], theme.NEUTRAL[900] if picked else "white"))
            top.addWidget(self.tick)
        self.head = Elided(head)
        self.head.setObjectName("meta")
        top.addWidget(self.head, 1)
        if pill:
            top.addWidget(TonePill(pill[0], pill[1]))
        lay.addLayout(top)
        self.customer = Elided(row.get("Customer", "") or row.get("Email", ""))
        self.customer.setFont(theme.font("BODY", 500))
        lay.addWidget(self.customer)
        self.product = Elided(product)
        self.product.setObjectName("meta")
        lay.addWidget(self.product)
        if said:
            lay.addWidget(_Said(said[0], bubble_text(said[1])))
        if price:
            phost = QWidget()
            prow = C.FlowLayout(phost, h_space=theme.SPACE_1, v_space=0)
            you = QLabel(f"{_esc(i18n.t('You'))} <b>{_esc(price[0])}</b>")
            vs = C.label(i18n.t("vs"), "meta")
            they = QLabel(f"{_esc(i18n.t('They'))} <b>{_esc(price[1])}</b>")
            you.setTextFormat(Qt.RichText)
            they.setTextFormat(Qt.RichText)
            they.setStyleSheet(f"color: {_tone('negotiating')[1]};")
            for w in (you, vs, they):
                prow.addWidget(w)
            lay.addWidget(phost)
        foot = QHBoxLayout()
        foot.setSpacing(theme.SPACE_1)
        flow_host = QWidget()
        flow = C.FlowLayout(flow_host, h_space=theme.SPACE_2,
                            v_space=theme.SPACE_1)
        for item in meta or []:
            if isinstance(item, QWidget):
                flow.addWidget(item)
            else:
                flow.addWidget(C.label(str(item), "meta"))
        foot.addWidget(flow_host, 1)
        if amount:
            amt = QLabel(amount)
            amt.setFont(theme.font("MONO", 500))
            amt.setAlignment(Qt.AlignRight | Qt.AlignBottom)
            foot.addWidget(amt, 0, Qt.AlignBottom)
        lay.addLayout(foot)

    def mouseReleaseEvent(self, event):                 # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(
                event.position().toPoint()):
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):                     # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.key)
            return
        super().keyPressEvent(event)

    def paintEvent(self, _event):                       # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 12, 12)
        p.fillPath(path, theme.qcolor("#fafafa" if self._dim else "#ffffff"))
        edge = theme.INK if (self._current or self._picked) \
            else theme.HAIRLINE
        p.setPen(QPen(theme.qcolor(edge), 1.5 if self._current or self._picked
                      else 1))
        p.drawPath(path)


def _esc(text) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def _clip(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


class _GroupHeader(QPushButton):
    """A group's fold line. Elided to the column, never wider than it: a
    push button's minimum width is its whole text, and "▾ ASKED FOR DETAILS
    · THEIR TURN · 1" made the Inquiry column's cards 40 px wider than the
    column, so their right edge and pills ran under the scroll bar."""

    def __init__(self, text: str, open_: bool, parent=None):
        self._full = ("▾ " if open_ else "▸ ") + text.upper()
        super().__init__(self._full, parent)
        self.setObjectName("boardGroup")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip(text)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(10)
        self.setStyleSheet(
            "QPushButton#boardGroup { text-align: left; border: none;"
            " padding: 4px 2px; %s font-weight: 500; }"
            % theme.type_css("LABEL", theme.NEUTRAL[600]))

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.ElideRight,
                                      max(10, self.width() - 6)))


class Column(QFrame):
    """One stage: a tinted header and a scrolling list of cards."""

    def __init__(self, stage: str, number: int, title: str, sub: str,
                 count: int, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("boardColumn")
        _bg, ink = _tone(STAGE_TONES[stage])
        self.setStyleSheet(
            "QFrame#boardColumn { background: #ffffff;"
            " border: 1px solid %s; border-radius: 16px; }"
            "QFrame#boardColHead { background: #F6F5F2; border: none;"
            " border-bottom: 1px solid %s; border-top-left-radius: 16px;"
            " border-top-right-radius: 16px; }" % (theme.HAIRLINE, theme.HAIRLINE))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QFrame()
        head.setObjectName("boardColHead")
        hl = QVBoxLayout(head)
        hl.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                              theme.SPACE_2)
        hl.setSpacing(0)
        trow = QHBoxLayout()
        trow.setSpacing(theme.SPACE_2)
        mark = QLabel()
        mark.setFixedSize(6, 6)
        mark.setStyleSheet(f"background: {ink}; border: none;")
        trow.addWidget(mark)
        # Elided, never wider than the column (review R12): a QLabel's
        # minimum width is its whole text.
        self.title = Elided(f"{number} · {title}")
        self.title.setFont(theme.font("CARD_TITLE", 500))
        self.title.setStyleSheet(f"color: {theme.INK};")
        trow.addWidget(self.title, 1)
        self.count = QLabel(str(count))
        self.count.setObjectName("boardCount")
        self.count.setStyleSheet(
            "QLabel#boardCount { background: #EFEEEA; border-radius: 6px;"
            " padding: 1px 7px; font-family: %s; %s font-weight: 500; }"
            % (theme.FONT_MONO_STACK, theme.type_css("LABEL", theme.INK)))
        trow.addWidget(self.count)
        hl.addLayout(trow)
        self.sub = QLabel(sub)
        self.sub.setWordWrap(True)
        self.sub.setStyleSheet(theme.type_css("SUPPORT", theme.MUTE))
        hl.addWidget(self.sub)
        lay.addWidget(head)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("boardColScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea#boardColScroll, "
                                  "QScrollArea#boardColScroll > QWidget > QWidget"
                                  " { background: transparent; }")
        inner = QWidget()
        self.cards = QVBoxLayout(inner)
        self.cards.setContentsMargins(theme.SPACE_2, theme.SPACE_2,
                                      theme.SPACE_2, theme.SPACE_2)
        self.cards.setSpacing(theme.SPACE_2)
        self.scroll.setWidget(inner)
        lay.addWidget(self.scroll, 1)

    def add(self, widget: QWidget):
        self.cards.addWidget(widget)

    def finish(self):
        if self.cards.count() == 0:
            empty = C.label(i18n.t("Nothing here. All caught up."), "meta",
                            wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            self.cards.addWidget(empty)
        self.cards.addStretch(1)


class _Kpi(QFrame):
    """One KPI tile; a click scrolls its column into view. A QFrame, not a
    QPushButton: a button's size hint ignores the layout inside it, which
    squashed the three lines into one."""
    clicked = Signal()

    def __init__(self, stage: str, parent=None):
        super().__init__(parent)
        self.stage = stage
        self.setObjectName("boardKpi")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        _bg, ink = _tone(STAGE_TONES[stage])
        self.setStyleSheet(
            "QFrame#boardKpi { background: white; border: 1px solid %s;"
            " border-radius: 14px; }" % theme.HAIRLINE)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_2,
                               theme.SPACE_2)
        lay.setSpacing(theme.SPACE_2)
        self.pad = QLabel()
        self.pad.setFixedSize(34, 34)
        self.pad.setAlignment(Qt.AlignCenter)
        self.pad.setStyleSheet("background: #F6F5F2; border-radius: 10px;")
        try:
            from widgets import icons
            self.pad.setPixmap(icons.pixmap(STAGE_ICONS.get(stage, "inbox"),
                                            16, theme.INK))
        except Exception:                               # noqa: BLE001
            pass
        lay.addWidget(self.pad, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value = QLabel("0")
        self.value.setFont(theme.font("SECTION", 500))
        self.title = Elided("")
        self.detail = Elided("")
        self.detail.setStyleSheet(theme.type_css("SUPPORT", theme.MUTE))
        col.addWidget(self.value)
        col.addWidget(self.title)
        col.addWidget(self.detail)
        lay.addLayout(col, 1)
        fm = self.fontMetrics()
        self.setMinimumWidth(fm.averageCharWidth() * 12)

    def mouseReleaseEvent(self, event):                 # noqa: N802
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):                     # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            return
        super().keyPressEvent(event)

    def set(self, number: int, title: str, count: int, detail: str):
        self.value.setText(str(count))
        self.title.setText(f"{number} · {title}")
        self.detail.setText(detail)
        self.setAccessibleName(f"{title}: {count}, {detail}")


# ── the board ─────────────────────────────────────────────────────────────
class BoardView(QWidget):
    """KPI strip + columns + lost line. `host` is the InquiryDialog."""
    card_opened = Signal(str)
    show_client_file = Signal()

    def __init__(self, host, parent=None):
        super().__init__(parent)
        self.host = host
        self.setObjectName("inquiryBoard")
        self.query = ""
        self.range_key = "all"
        self.select_mode = False
        self.picked: set[str] = set()
        self.groups_open: dict[str, bool] = {}
        self.current_no = ""
        self.cards: dict[str, BoardCard] = {}
        self.column_widgets: dict[str, Column] = {}
        self._placed: dict = {}
        self._pending_replies: dict[str, dict] = {}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.SPACE_2)

        self.kpi_row = QHBoxLayout()
        self.kpi_row.setSpacing(theme.SPACE_2)
        self.kpis: dict[str, _Kpi] = {}
        lay.addLayout(self.kpi_row)

        # Select mode: what the ticks act on.
        self.bulk = QFrame()
        self.bulk.setObjectName("boardBulk")
        self.bulk.setStyleSheet(
            "QFrame#boardBulk { background: white; border: 1px solid %s;"
            " border-radius: 10px; }" % theme.NEUTRAL[300])
        bl = QHBoxLayout(self.bulk)
        bl.setContentsMargins(theme.SPACE_3, theme.SPACE_1, theme.SPACE_2,
                              theme.SPACE_1)
        self.bulk_label = C.label("", weight=700)
        bl.addWidget(self.bulk_label, 1)
        self.bulk_xlsx = C.button(i18n.t("Save these as Excel"), "secondary",
                                  icon_name="download", small=True,
                                  on_click=self._save_picked)
        self.bulk_delete = C.button("", "destructive", icon_name="trash",
                                    on_click=self._delete_picked)
        self.bulk_done = C.button(i18n.t("Done"), "secondary", small=True,
                                  on_click=lambda: self.set_select_mode(False))
        for b in (self.bulk_xlsx, self.bulk_delete, self.bulk_done):
            bl.addWidget(b)
        self.bulk.setVisible(False)
        lay.addWidget(self.bulk)

        self.hscroll = QScrollArea()
        self.hscroll.setObjectName("boardScroll")
        self.hscroll.setWidgetResizable(True)
        self.hscroll.setFrameShape(QFrame.NoFrame)
        self.hscroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.hscroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.hscroll.setStyleSheet(
            "QScrollArea#boardScroll, QScrollArea#boardScroll > QWidget > QWidget"
            " { background: transparent; }")
        self.strip = QWidget()
        self.cols = QHBoxLayout(self.strip)
        self.cols.setContentsMargins(0, 0, 0, 0)
        self.cols.setSpacing(theme.SPACE_2)
        self.hscroll.setWidget(self.strip)
        lay.addWidget(self.hscroll, 1)

        lost_row = QHBoxLayout()
        lost_row.setSpacing(theme.SPACE_1)
        self.lost_label = C.label("", "meta")
        lost_row.addWidget(self.lost_label)
        self.lost_link = C.button(i18n.t("client file"), "tertiary", small=True,
                                  on_click=self.show_client_file.emit)
        self.lost_link.setObjectName("linkBtn")
        lost_row.addWidget(self.lost_link)
        self.lost_tail = C.label(
            i18n.t("with the reason · any card can be marked lost"), "meta")
        lost_row.addWidget(self.lost_tail)
        lost_row.addStretch(1)
        lay.addLayout(lost_row)

    # ── state in ──────────────────────────────────────────────────────────
    def pipeline(self) -> dict:
        return pipeline(self.host.cfg)

    def visible_rows(self) -> list[dict]:
        """The dialog's rows through the board's own search and range."""
        from addons.inquiry import dialog as UI
        register = CB.get_register()
        today = date.today()
        out = []
        for row in getattr(self.host, "_register_rows", []) or []:
            if self.range_key != "all" and not UI._in_date_range(
                    register.parse_date(row.get("Date received", "")),
                    self.range_key, today):
                continue
            if self.query and not UI._matches(
                    self.query, row.get("Inquiry no", ""), row.get("Customer", ""),
                    row.get("Email", ""), row.get("Product asked", ""),
                    row.get("Quotation no", "")):
                continue
            out.append(row)
        return out

    def _load_replies(self):
        """The latest pending reply per inquiry — ONE worklist read."""
        self._pending_replies = {}
        root = self.host._root() if hasattr(self.host, "_root") else ""
        if not root:
            return
        try:
            wl = CB.get_worklist()
            data = wl.load(root)
            for entry in wl.pending(data, "replies"):
                no = entry.get("inquiry_no", "")
                if no:
                    self._pending_replies[no] = entry
        except Exception:                               # noqa: BLE001
            self._pending_replies = {}

    def latest_reply(self, no: str) -> dict | None:
        return self._pending_replies.get(no)

    # ── render ────────────────────────────────────────────────────────────
    def set_query(self, text: str):
        self.query = (text or "").strip()
        self.refresh()

    def set_range(self, key: str):
        self.range_key = key or "all"
        self.refresh()

    def set_select_mode(self, on: bool):
        self.select_mode = bool(on)
        if not on:
            self.picked.clear()
        self.refresh()

    def refresh(self):
        p = self.pipeline()
        self._load_replies()
        rows = self.visible_rows()
        self._placed = place(rows, p)
        stages = columns(p)
        # KPI strip, rebuilt when the stage set changes.
        if list(self.kpis) != stages:
            while self.kpi_row.count():
                item = self.kpi_row.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.kpis = {}
            for s in stages:
                k = _Kpi(s)
                k.clicked.connect(lambda s=s: self.scroll_to(s))
                self.kpis[s] = k
                self.kpi_row.addWidget(k, 1)
        for i, (stage, count, detail) in enumerate(kpis(self._placed, p), 1):
            self.kpis[stage].set(i, stage_text(p, stage), count, detail)
        self._fit_height()
        # Columns: rebuilt every refresh (cheap; tens of cards), scroll kept.
        scroll = {s: c.scroll.verticalScrollBar().value()
                  for s, c in self.column_widgets.items()}
        hpos = self.hscroll.horizontalScrollBar().value()
        while self.cols.count():
            item = self.cols.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.column_widgets = {}
        self.cards = {}
        self._keys = card_keys(getattr(self.host, "_register_rows", []) or [])
        fm = self.fontMetrics()
        col_w = min_column_width(fm)
        for i, stage in enumerate(stages, 1):
            items = self._placed.get(stage, [])
            sub = LABELS["po_proforma"] if (stage == "po" and (p.get("steps") or {})
                                            .get("proforma")) else LABELS[stage]
            if stage == "po" and sub == LABELS["po"]:
                text = i18n.t("Check it against the final {quote}").replace(
                    "{quote}", word_text(p, "quote").lower())
            else:
                text = i18n.t(sub)
            col = Column(stage, i, stage_text(p, stage), text, len(items))
            col.setMinimumWidth(int(col_w * (0.8 if stage == "won" else 1)))
            getattr(self, f"_fill_{stage}")(col, items, p)
            col.finish()
            self.column_widgets[stage] = col
            self.cols.addWidget(col, 3 if stage == "won" else 4)
            if stage in scroll:
                col.scroll.verticalScrollBar().setValue(scroll[stage])
        self.strip.setMinimumWidth(board_min_width(fm, p))
        self.hscroll.horizontalScrollBar().setValue(hpos)
        lost = len(self._placed.get("lost", []))
        self.lost_label.setText("✕ " + i18n.t("{n} lost — kept in the").replace(
            "{n}", str(lost)))
        self._sync_bulk()

    def _sync_bulk(self):
        self.bulk.setVisible(self.select_mode)
        n = len(self.picked)
        self.bulk_label.setText(
            i18n.t("{n} selected").replace("{n}", str(n)) if n
            else i18n.t("Tick the inquiries to act on"))
        self.bulk_xlsx.setVisible(n > 0)
        self.bulk_delete.setVisible(n > 0)
        self.bulk_delete.setText(i18n.t("Delete {n} inquiries").replace(
            "{n}", str(n)))

    def scroll_to(self, stage: str):
        col = self.column_widgets.get(stage)
        if col is not None:
            self.hscroll.ensureWidgetVisible(col, 0, 0)

    # ── cards per column ──────────────────────────────────────────────────
    def key_of(self, row: dict) -> str:
        keys = getattr(self, "_keys", None) or {}
        key = keys.get(id(row))
        if key is None:
            rows = getattr(self.host, "_register_rows", []) or []
            self._keys = keys = card_keys(rows)
            key = keys.get(id(row), (row.get("Inquiry no") or "").strip())
        return key

    def row_for(self, key: str) -> dict | None:
        return row_for_key(getattr(self.host, "_register_rows", []) or [], key)

    def _card(self, col: Column, row: dict, **kw) -> BoardCard:
        no = self.key_of(row)
        card = BoardCard(row, picked=(no in self.picked) if self.select_mode
                         else None, current=(no == self.current_no), **kw)
        card.key = no
        card.clicked.connect(self._card_clicked)
        self.cards[no] = card
        col.add(card)
        return card

    def _group(self, col: Column, key: str, text: str, items: list, make):
        if not items:
            return
        open_ = self.groups_open.get(key, True)
        head = _GroupHeader(f"{text} · {len(items)}", open_)
        head.clicked.connect(lambda _=False, k=key: self._toggle_group(k))
        col.add(head)
        if open_:
            for row, sub in items:
                make(row, sub)

    def _toggle_group(self, key: str):
        self.groups_open[key] = not self.groups_open.get(key, True)
        self.refresh()

    def _said(self, row: dict) -> tuple | None:
        entry = self.latest_reply(row.get("Inquiry no", ""))
        if not entry:
            return None
        who = (entry.get("from_name") or row.get("Contact person")
               or row.get("Customer") or "").split(" ")[0]
        body = entry.get("body") or entry.get("subject") or ""
        return (who, body) if body.strip() else None

    def _read_pill(self, row: dict) -> tuple | None:
        entry = self.latest_reply(row.get("Inquiry no", ""))
        if not entry:
            return None
        text, tone = COPY.get(entry.get("intent", ""), COPY["unclear"])
        return (i18n.t(text), tone)

    def _maybe_po_pill(self, p: dict, row: dict) -> tuple | None:
        """The mail check thought the latest mail may be a PO but was not
        sure, so the row stayed an inquiry (register.flag_maybe_po)."""
        if not CB.get_register().maybe_po(row):
            return None
        return (i18n.t("Looks like a {po}").replace("{po}", word_text(p, "po")),
                "no_reply")

    def _money(self, p: dict, value) -> str:
        return inquiry_config.format_money(value, p.get("currency", "₹"))

    def _date_meta(self, row: dict, key: str = "Date received") -> str:
        d = CB.get_register().parse_date(row.get(key, ""))
        return "📅 " + d.strftime("%d %b").lstrip("0") if d else ""

    @staticmethod
    def _newest_first(items):
        """The mail that just arrived on top: with 15 inquiries the newest,
        listed last, was below the fold and read as "it never arrived"."""
        register = CB.get_register()

        def key(x):
            row = x[0]
            d = register.parse_date(row.get("Date received", ""))
            return (d.toordinal() if d else 0, row.get("Time received", "") or "")
        return sorted(items, key=key, reverse=True)

    def _fill_inquiry(self, col, items, p):
        details = (p.get("steps") or {}).get("details", True)
        items = self._newest_first(items)
        yours = [x for x in items if x[1] != "them"]
        theirs = [x for x in items if x[1] == "them"]
        if details and yours:
            col.add(_GroupHeader(i18n.t("Your turn"), True))
        for row, _sub in yours:
            pill = (self._maybe_po_pill(p, row) or self._read_pill(row)
                    or (i18n.t("New"), "new"))
            meta = [m for m in (("▣ " + row["Quantity"]) if row.get("Quantity")
                                else "", self._date_meta(row)) if m]
            self._card(col, row, head=row.get("Inquiry no", ""), pill=pill,
                       product=row.get("Product asked", ""), tone="new",
                       said=self._said(row), meta=meta)
        if details:
            self._group(col, "details", i18n.t("Asked for details · their turn"),
                        theirs, lambda r, s: self._card(
                            col, r, head=r.get("Inquiry no", ""),
                            pill=(i18n.t("Their turn"), "quoted"),
                            product=r.get("Product asked", ""), tone="quoted",
                            dim=True, said=self._said(r),
                            meta=[self._date_meta(r, "Last contact")]))

    def _quoted_card(self, col, row, p):
        register = CB.get_register()
        state, days = due_state(row, p)
        sent = reminders_sent(row)
        maxed = sent >= int(p.get("max_reminders") or 3)
        if state == "over":
            pill = (i18n.t("Overdue {n}d").replace("{n}", str(days)), "lost")
        elif state == "today":
            pill = (i18n.t("Due today"), "no_reply")
        else:
            pill = (i18n.t("Not yet due"), "quoted")
        meta = []
        d = register.parse_date(row.get("Quotation date", ""))
        if d:
            meta.append("➤ " + i18n.t("sent {when}").replace(
                "{when}", d.strftime("%d %b").lstrip("0")))
        if sent:
            meta.append(f"🔔 {sent}/{int(p.get('max_reminders') or 3)}")
        rev = register.revision_of(row)
        if rev:
            meta.append(i18n.t("Rev {n}").replace("{n}", str(rev)))
        if maxed:
            meta.append(TonePill(i18n.t("Call them"), "lost"))
        self._card(col, row, head=register.quote_label(row) or row.get(
            "Inquiry no", ""), pill=pill, product=row.get("Product asked", ""),
            tone="lost" if state == "over" else "quoted", meta=meta,
            amount=self._money(p, row.get("Quotation value", "")))

    def _nego_card(self, col, row, p):
        register = CB.get_register()
        turn = (row.get(register.TURN) or "you").strip().lower()
        pill = ((i18n.t("Their turn"), "quoted") if turn == register.TURN_THEM
                else (i18n.t("Your turn"), "no_reply"))
        ask = row.get(register.THEIR_ASK, "")
        price = ((self._money(p, row.get("Quotation value", "")),
                  self._money(p, ask)) if ask else None)
        meta = []
        rp = self._read_pill(row)
        if rp:
            meta.append(TonePill(*rp))
        dm = self._date_meta(row, "Last contact")
        if dm:
            meta.append(dm)
        self._card(col, row, head=register.quote_label(row) or row.get(
            "Inquiry no", ""), pill=pill, product=row.get("Product asked", ""),
            tone="negotiating", said=self._said(row), price=price, meta=meta,
            amount="" if price else self._money(p, row.get("Quotation value", "")))

    def _fill_quoted(self, col, items, p):
        def over_first(x):
            return 0 if due_state(x[0], p)[0] == "over" else 1
        plain = sorted([x for x in items if x[1] != "countered"], key=over_first)
        for row, _s in plain:
            self._quoted_card(col, row, p)
        self._group(col, "countered", i18n.t("Countered — reply or revise"),
                    [x for x in items if x[1] == "countered"],
                    lambda r, s: self._nego_card(col, r, p))

    def _fill_nego(self, col, items, p):
        register = CB.get_register()
        ordered = sorted(items, key=lambda x: 1 if (x[0].get(register.TURN) or "")
                         .strip().lower() == register.TURN_THEM else 0)
        for row, _s in ordered:
            self._nego_card(col, row, p)

    def _fill_po(self, col, items, p):
        register = CB.get_register()
        po_word, q_word = word_text(p, "po"), word_text(p, "quote")

        def check(row, sub):
            if sub == "nopo":
                self._card(col, row, head=row.get("Inquiry no", ""),
                           pill=(i18n.t("No quotation"), "no_reply"),
                           product=i18n.t("{po} with no {quote} — price it")
                           .replace("{po}", po_word)
                           .replace("{quote}", q_word.lower()),
                           tone="won", meta=[self._date_meta(row, "Last contact")])
            else:
                self._card(col, row, head=register.quote_label(row),
                           pill=(i18n.t("Check it"), "won"),
                           product=f"{po_word} {row.get('PO number', '')} · "
                                   f"{row.get('Product asked', '')}",
                           tone="won", meta=[self._date_meta(row, "PO date")
                                             or self._date_meta(row, "Last contact")],
                           amount=self._money(p, row.get("Order value") or
                                              row.get("Quotation value", "")))

        def yes(row, sub):
            self._card(col, row, head=register.quote_label(row),
                       pill=(i18n.t("Awaited"), "no_reply"),
                       product=row.get("Product asked", ""), tone="won",
                       said=self._said(row),
                       meta=[i18n.t("yes on {when}").replace(
                           "{when}", self._date_meta(row, "Last contact")
                           .replace("📅 ", ""))],
                       amount=self._money(p, row.get("Quotation value", "")))

        def proforma(row, sub):
            self._card(col, row, head=register.quote_label(row),
                       pill=((i18n.t("Proforma to send"), "new")
                             if register.proforma_due(row)
                             else (i18n.t("Advance due"), "no_reply")),
                       product=i18n.t("Proforma for {what}").replace(
                           "{what}", row.get("Product asked", "")),
                       tone="won", meta=[row.get("PO number", "")],
                       amount=self._money(p, row.get("Order value") or
                                          row.get("Quotation value", "")))

        self._group(col, "check", i18n.t("{po} to check").replace("{po}", po_word),
                    [x for x in items if x[1] in ("check", "nopo")], check)
        self._group(col, "yes", i18n.t("Said yes · {po} awaited").replace(
            "{po}", po_word), [x for x in items if x[1] == "yes"], yes)
        self._group(col, "proforma", i18n.t("Proforma · advance awaited"),
                    [x for x in items if x[1] == "proforma"], proforma)

    def _fill_won(self, col, items, p):
        total = sum(money_value(r) for r, _s in items)
        summary = QFrame()
        summary.setObjectName("boardWonSum")
        summary.setStyleSheet("QFrame#boardWonSum { background: white;"
                              " border: 1px solid %s; border-radius: 10px; }"
                              % theme.NEUTRAL[200])
        sl = QVBoxLayout(summary)
        sl.setContentsMargins(theme.SPACE_3, theme.SPACE_2, theme.SPACE_3,
                              theme.SPACE_2)
        big = QLabel(self._money(p, total) if total else "—")
        big.setFont(theme.font("SECTION", 700))
        big.setStyleSheet(f"color: {_tone('won')[1]};")
        sl.addWidget(big)
        sl.addWidget(C.label(i18n.t("{n} orders").replace("{n}", str(len(items))),
                             "meta"))
        col.add(summary)
        self.won_summary = big
        register = CB.get_register()
        self._group(col, "won", i18n.t("Confirmed"), items,
                    lambda r, s: self._card(
                        col, r, head=r.get("PO number") or r.get("Inquiry no", ""),
                        pill=None, product=r.get("Product asked", ""), tone="won",
                        dim=True, meta=[self._date_meta(r, "PO date")
                                        or self._date_meta(r, "Last contact")],
                        amount=self._money(p, r.get("Order value") or
                                           r.get("Quotation value", ""))))
        del register

    # ── clicks ────────────────────────────────────────────────────────────
    def _card_clicked(self, no: str):
        if self.select_mode:
            if no in self.picked:
                self.picked.discard(no)
            else:
                self.picked.add(no)
            self.refresh()
            return
        self.card_opened.emit(no)

    def set_current(self, no: str):
        self.current_no = no or ""
        for key, card in self.cards.items():
            card._current = key == self.current_no
            card.update()

    def picked_rows(self) -> list[dict]:
        rows = getattr(self.host, "_register_rows", []) or []
        out = []
        for key in sorted(self.picked):
            r = row_for_key(rows, key)
            if r is not None and not any(r is o for o in out):
                out.append(r)
        return out

    def _delete_picked(self):
        rows = self.picked_rows()
        if rows:
            self.host.act_on_rows(rows, "delete")
        left = getattr(self.host, "_register_rows", []) or []
        keys = set(card_keys(left).values())
        self.picked = {k for k in self.picked if k in keys}
        self.refresh()

    def _save_picked(self):
        rows = self.picked_rows()
        if rows:
            self.host.act_on_rows(rows, "xlsx")

    def resizeEvent(self, event):                       # noqa: N802
        super().resizeEvent(event)
        self._fit_height()

    def _fit_height(self):
        """On a short window (a 1366x768 laptop at 125%) the KPI strip would
        leave the columns a sliver; the column headers carry the same counts,
        so the strip steps aside first."""
        win = self.window()
        room = self.height() >= 480 and (win is None or win.height() > 680)
        for k in self.kpis.values():
            k.setVisible(room)

    def minimumSizeHint(self) -> QSize:                 # noqa: N802
        hint = super().minimumSizeHint()
        return QSize(min(hint.width(), 320), hint.height())
