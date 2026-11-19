"""What is inside a file, read for the in-app viewer (dialogs/file_viewer.py).

No Qt in this module, so it runs on a worker thread and tests without a
display. Everything here treats a file as DATA: a spreadsheet cell that starts
with "=" is the text "=...", a Word document is paragraphs and tables, a
Markdown file is text. Nothing is executed, no macro runs, no HTML from the
file is ever handed to a renderer.

Every read is bounded, and says so when it cut something off, so a 400 MB CSV
opens in a second instead of freezing the window.

`read(path)` returns a plain dict with at least:
    kind      one of KINDS
    name      the file name
    size      bytes on disk (0 if unknown)
    error     "" or a plain-language reason the file could not be shown
and, per kind, the fields documented on each `_read_*` function.
"""
from __future__ import annotations

import csv
import io
import os
import re
import zipfile

KINDS = ("folder", "image", "pdf", "docx", "xlsx", "csv", "markdown", "text",
         "dxf", "pptx", "video", "audio", "other")

MAX_ROWS = 2000            # table rows shown per sheet
MAX_COLS = 60              # table columns shown per sheet
MAX_SHEETS = 30
MAX_CELL_CHARS = 2000      # one cell is never longer than this on screen
MAX_TEXT_BYTES = 2_000_000  # text read from a text/markdown file
MAX_OFFICE_BYTES = 100 * 1024 * 1024   # docx/xlsx/pptx bigger than this: not opened
MAX_DOCX_BLOCKS = 5000
MAX_TABLE_CELLS = 5000     # per Word table

_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff",
          ".ico", ".svg"}
_VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}
_TEXT = {".txt", ".json", ".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm",
         ".css", ".java", ".c", ".cpp", ".h", ".go", ".rb", ".php", ".sh",
         ".sql", ".yaml", ".yml", ".xml", ".log", ".ini", ".cfg", ".toml",
         ".bat", ".ps1", ".rtf", ".tsv", ".ipynb", ".eml", ".gbr", ".drl",
         ".gtl", ".gbl", ".gts", ".gbs", ".gto", ".gbo", ".gm1", ".nc"}


def classify(path: str) -> str:
    if os.path.isdir(path):
        return "folder"
    ext = os.path.splitext(path)[1].lower()
    if ext in _IMAGE:
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext == ".docx":
        return "docx"
    if ext in (".xlsx", ".xlsm"):
        return "xlsx"
    if ext in (".csv", ".tsv"):
        return "csv"
    if ext in (".md", ".markdown"):
        return "markdown"
    if ext == ".dxf":
        return "dxf"
    if ext == ".pptx":
        return "pptx"
    if ext in _VIDEO:
        return "video"
    if ext in _AUDIO:
        return "audio"
    if ext in _TEXT:
        return "text"
    return "other"


def size_of(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def _clip(value) -> str:
    """One cell as text, never huge, never carrying control characters that
    would break a table."""
    if value is None:
        return ""
    text = str(value)
    if len(text) > MAX_CELL_CHARS:
        text = text[:MAX_CELL_CHARS] + "…"
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)


def decode(raw: bytes) -> str:
    """Bytes to text without ever raising: BOMs first, then UTF-8, then the
    Windows code page a spreadsheet exported on an office PC is really in."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _too_big(path: str) -> str:
    if size_of(path) > MAX_OFFICE_BYTES:
        return ("This file is over 100 MB, which is too large to show here. "
                "Use “Open in another app”.")
    return ""


# ── text / markdown ───────────────────────────────────────────────────────────
def _read_text(path: str) -> dict:
    """{"text", "truncated"}"""
    with open(path, "rb") as f:
        raw = f.read(MAX_TEXT_BYTES + 1)
    truncated = len(raw) > MAX_TEXT_BYTES
    text = decode(raw[:MAX_TEXT_BYTES]).replace("\r\n", "\n").replace("\r", "\n")
    return {"text": text.replace("\x00", ""), "truncated": truncated}


# ── csv ───────────────────────────────────────────────────────────────────────
def _delimiter(sample: str, ext: str) -> str:
    if ext == ".tsv":
        return "\t"
    first = sample.split("\n", 1)[0]
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def _read_csv(path: str) -> dict:
    """{"sheets": [{"name", "columns", "rows", "rows_total", "truncated",
    "cols_cut"}]}. rows_total is None when the file has more rows than were read."""
    with open(path, "rb") as f:
        raw = f.read(MAX_TEXT_BYTES * 4 + 1)
    cut_bytes = len(raw) > MAX_TEXT_BYTES * 4
    text = decode(raw[:MAX_TEXT_BYTES * 4])
    if cut_bytes and "\n" in text:
        text = text[:text.rindex("\n")]          # never show half a row
    delim = _delimiter(text[:4096], os.path.splitext(path)[1].lower())
    csv.field_size_limit(10_000_000)
    rows, more, cols_cut = [], cut_bytes, False
    try:
        for row in csv.reader(io.StringIO(text), delimiter=delim):
            if len(rows) >= MAX_ROWS + 1:           # +1 for the header
                more = True
                break
            if len(row) > MAX_COLS:
                cols_cut = True
            rows.append([_clip(c) for c in row[:MAX_COLS]])
    except csv.Error:
        pass                                          # show what read cleanly
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = rows[0] if rows else []
    body = rows[1:]
    cols = [h or f"Column {i + 1}" for i, h in enumerate(header)]
    return {"sheets": [{"name": os.path.basename(path), "columns": cols,
                        "rows": body, "rows_total": None if more else len(body),
                        "truncated": more, "cols_cut": cols_cut}]}


# ── xlsx ──────────────────────────────────────────────────────────────────────
# ── formulas nobody calculated ────────────────────────────────────────────────
# A workbook written by a program (Prism's own priced BOQ, core/boq_price.py)
# holds live formulas and no calculated results; Excel computes them when it
# opens the file. Showing "=SUM(F5:F6)" where a grand total belongs is no use,
# so the simple formulas such files use are computed here: + - * / ^, brackets,
# cell and range references (also on another sheet), SUM, ROUND, MIN, MAX,
# ABS, AVERAGE. A tokenizer and a small recursive-descent parser, never eval.
# Anything else (another function, text in arithmetic, a loop) keeps the
# formula text, exactly as before.

class _Formula(str):
    """A formula with no saved result (so a text cell starting with "=" is
    never mistaken for one)."""


class _CannotCompute(Exception):
    pass


_TOKEN_RE = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d*)?(?:[eE][-+]?\d+)?|\.\d+)"
    r"|(?P<fn>[A-Z][A-Z0-9.]*)\s*\("
    r"|(?P<ref>(?:(?:'[^']+'|[A-Za-z_][\w.]*)!)?\$?[A-Za-z]{1,3}\$?\d+"
    r"(?::\$?[A-Za-z]{1,3}\$?\d+)?)"
    r"|(?P<op>[-+*/^(),]))")
_ADDR_RE = re.compile(r"\$?([A-Za-z]{1,3})\$?(\d+)")


def _col_number(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


class _Calc:
    def __init__(self, sheets: dict, cut: dict):
        self.sheets = sheets          # {sheet: {(row, col): value | _Formula}} 1-based
        self.cut = cut                # {sheet: (rows_loaded, cols_loaded, truncated)}
        self.memo: dict = {}
        self.busy: set = set()

    def value(self, sheet: str, row: int, col: int):
        key = (sheet, row, col)
        if key in self.memo:
            if self.memo[key] is _CannotCompute:
                raise _CannotCompute(key)
            return self.memo[key]
        if sheet not in self.sheets:
            raise _CannotCompute(sheet)
        rows, cols, truncated = self.cut[sheet]
        if truncated and (row > rows or col > cols):
            raise _CannotCompute("outside what was read")
        raw = self.sheets[sheet].get((row, col))
        if isinstance(raw, _Formula):
            if key in self.busy:
                raise _CannotCompute("loop")
            self.busy.add(key)
            try:
                raw = self._formula(sheet, raw[1:])
            except _CannotCompute:
                self.memo[key] = _CannotCompute
                raise
            finally:
                self.busy.discard(key)
        self.memo[key] = raw
        return raw

    # parser
    def _formula(self, sheet: str, text: str):
        toks, pos = [], 0
        while pos < len(text):
            m = _TOKEN_RE.match(text, pos)
            if not m or m.end() == pos:
                if text[pos:].strip():
                    raise _CannotCompute(text[pos:])
                break
            kind = m.lastgroup
            toks.append((kind, m.group(kind)))
            pos = m.end()
        self._toks, self._i, self._sheet = toks, 0, sheet
        out = self._expr()
        if self._i != len(toks):
            raise _CannotCompute("trailing")
        return out

    def _peek(self):
        return self._toks[self._i] if self._i < len(self._toks) else (None, None)

    def _take(self):
        tok = self._peek()
        self._i += 1
        return tok

    def _expr(self):
        v = self._term()
        while self._peek() in (("op", "+"), ("op", "-")):
            op = self._take()[1]
            r = self._term()
            v = v + r if op == "+" else v - r
        return v

    def _term(self):
        v = self._power()
        while self._peek() in (("op", "*"), ("op", "/")):
            op = self._take()[1]
            r = self._power()
            if op == "/" and r == 0:
                raise _CannotCompute("division by zero")
            v = v * r if op == "*" else v / r
        return v

    def _power(self):
        v = self._unary()
        if self._peek() == ("op", "^"):
            self._take()
            return v ** self._power()
        return v

    def _unary(self):
        if self._peek() == ("op", "-"):
            self._take()
            return -self._unary()
        if self._peek() == ("op", "+"):
            self._take()
            return self._unary()
        return self._primary()

    def _primary(self):
        kind, text = self._take()
        if kind == "num":
            return float(text)
        if kind == "ref":
            if ":" in text:
                raise _CannotCompute("range outside a function")
            return self._number(self._cell(text))
        if kind == "fn":
            return self._call(text.upper(), self._args())
        if (kind, text) == ("op", "("):
            v = self._expr()
            if self._take() != ("op", ")"):
                raise _CannotCompute("bracket")
            return v
        raise _CannotCompute(text)

    def _args(self) -> list:
        args = []
        if self._peek() == ("op", ")"):
            self._take()
            return args
        while True:
            kind, text = self._peek()
            nxt = self._toks[self._i + 1] if self._i + 1 < len(self._toks) else (None, None)
            if kind == "ref" and nxt in (("op", ","), ("op", ")")):
                self._take()
                args.append(self._range(text))       # a reference: keep text as text
            else:
                args.append([self._expr()])
            sep = self._take()
            if sep == ("op", ")"):
                return args
            if sep != ("op", ","):
                raise _CannotCompute("arguments")

    def _split(self, ref: str):
        sheet = self._sheet
        if "!" in ref:
            sheet, ref = ref.rsplit("!", 1)
            sheet = sheet.strip("'")
        return sheet, ref

    def _cell(self, ref: str):
        sheet, addr = self._split(ref)
        m = _ADDR_RE.fullmatch(addr)
        return self.value(sheet, int(m.group(2)), _col_number(m.group(1)))

    def _range(self, ref: str) -> list:
        sheet, addr = self._split(ref)
        ends = [_ADDR_RE.fullmatch(a) for a in addr.split(":")]
        (c1, r1), (c2, r2) = [(_col_number(e.group(1)), int(e.group(2))) for e in ends * (2 // len(ends))]
        if (abs(r2 - r1) + 1) * (abs(c2 - c1) + 1) > 200_000:
            raise _CannotCompute("range too big")
        return [self.value(sheet, r, c)
                for r in range(min(r1, r2), max(r1, r2) + 1)
                for c in range(min(c1, c2), max(c1, c2) + 1)]

    @staticmethod
    def _number(v):
        if v is None or v == "":
            return 0.0
        if isinstance(v, bool):
            return float(v)
        if isinstance(v, (int, float)):
            return float(v)
        raise _CannotCompute("text in arithmetic")

    @staticmethod
    def _call(name: str, args: list):
        nums = [float(v) for a in args for v in a
                if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if name == "SUM":
            return sum(nums)
        if name == "MIN":
            return min(nums) if nums else 0.0
        if name == "MAX":
            return max(nums) if nums else 0.0
        if name == "AVERAGE":
            if not nums:
                raise _CannotCompute("average of nothing")
            return sum(nums) / len(nums)
        if name == "ABS" and len(args) == 1:
            return abs(_Calc._number(args[0][0]))
        if name == "ROUND" and len(args) in (1, 2):
            from decimal import ROUND_HALF_UP, Decimal
            x = _Calc._number(args[0][0])
            places = int(_Calc._number(args[1][0])) if len(args) == 2 else 0
            q = Decimal(1).scaleb(-places)
            return float(Decimal(repr(x)).quantize(q, rounding=ROUND_HALF_UP))
        raise _CannotCompute(name)


def _shown_number(v: float):
    """15.000000000000002 -> 15; 3.3300000000000001 -> 3.33."""
    v = round(v, 9)
    return int(v) if v == int(v) else v


def _read_xlsx(path: str) -> dict:
    """Same shape as _read_csv, one sheet per worksheet. Shows each cell's last
    calculated value; a formula nobody has calculated yet (a file Prism wrote
    itself has no cached results) is computed by _Calc when it is simple and
    shown as its formula text when it is not. Nothing runs."""
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    forms = load_workbook(path, read_only=True, data_only=False)
    raw_sheets, cut, order = {}, {}, []
    try:
        for ws, wf in list(zip(book.worksheets, forms.worksheets))[:MAX_SHEETS]:
            grid, rows, more, cols_cut = {}, [], False, False
            pairs = zip(ws.iter_rows(min_row=1, min_col=1, max_col=MAX_COLS + 1, values_only=True),
                        wf.iter_rows(min_row=1, min_col=1, max_col=MAX_COLS + 1, values_only=True))
            for r, (row, frow) in enumerate(pairs, 1):
                if len(rows) >= MAX_ROWS + 1:
                    more = True
                    break
                if any(c is not None and c != "" for c in row[MAX_COLS:]):
                    cols_cut = True
                cells = [_Formula(f) if v is None and isinstance(f, str) and f.startswith("=") else v
                         for v, f in zip(row, frow)]
                for c, v in enumerate(cells, 1):
                    if v is not None:
                        grid[(r, c)] = v
                rows.append(cells)
            raw_sheets[ws.title] = grid
            cut[ws.title] = (len(rows), MAX_COLS + 1, more or cols_cut)
            order.append((ws.title, rows, more, cols_cut))
        sheets_cut = len(book.worksheets) > MAX_SHEETS
    finally:
        book.close()      # a read-only book keeps the file open: locks it on Windows
        forms.close()
    calc = _Calc(raw_sheets, cut)
    sheets = []
    for title, rows, more, cols_cut in order:
        shown_rows = []
        for r, cells in enumerate(rows, 1):
            shown = []
            for c, v in enumerate(cells, 1):
                if isinstance(v, _Formula):
                    try:
                        got = calc.value(title, r, c)
                        v = _shown_number(got) if isinstance(got, float) else got
                    except (_CannotCompute, ArithmeticError, ValueError, RecursionError):
                        v = str(v)
                shown.append(v)
            shown_rows.append([_clip(x) for x in shown[:MAX_COLS]])
        rows = shown_rows
        while rows and not any(rows[-1]):          # a sheet's empty tail
            rows.pop()
        width = max((max((i + 1 for i, c in enumerate(r) if c), default=0)
                     for r in rows), default=0)
        rows = [(r + [""] * width)[:width] for r in rows]
        header = rows[0] if rows else []
        cols = [h or f"Column {i + 1}" for i, h in enumerate(header)]
        sheets.append({"name": title, "columns": cols, "rows": rows[1:],
                       "rows_total": None if more else max(len(rows) - 1, 0),
                       "truncated": more, "cols_cut": cols_cut})
    return {"sheets": sheets, "sheets_cut": sheets_cut}


# ── docx ──────────────────────────────────────────────────────────────────────
def _read_docx(path: str) -> dict:
    """{"blocks": [("heading", level, text) | ("para", text) | ("bullet", text)
    | ("table", rows)], "truncated"}, in document order."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    blocks, truncated = [], False
    for child in doc.element.body.iterchildren():
        if len(blocks) >= MAX_DOCX_BLOCKS:
            truncated = True
            break
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            m = re.search(r"heading\s*([1-6])", style)
            if style == "title":
                blocks.append(("heading", 1, _clip(text)))
            elif m:
                blocks.append(("heading", int(m.group(1)), _clip(text)))
            elif "list" in style:
                blocks.append(("bullet", _clip(text)))
            else:
                blocks.append(("para", _clip(text)))
        elif tag == "tbl":
            table = Table(child, doc)
            rows, cells = [], 0
            for row in table.rows:
                cells += len(row.cells)
                if cells > MAX_TABLE_CELLS:
                    truncated = True
                    break
                rows.append([_clip(c.text.strip()) for c in row.cells])
            if rows:
                blocks.append(("table", rows))
    return {"blocks": blocks, "truncated": truncated}


# ── pptx ──────────────────────────────────────────────────────────────────────
def _read_pptx(path: str) -> dict:
    """{"slides": [[line, ...], ...]}: the visible text of each slide."""
    import xml.etree.ElementTree as ET
    slides = []
    with zipfile.ZipFile(path) as deck:
        names = sorted((n for n in deck.namelist()
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"\d+", n).group()))
        for name in names[:200]:
            if deck.getinfo(name).file_size > 5_000_000:
                slides.append(["(This slide is too large to read.)"])
                continue
            root = ET.fromstring(deck.read(name))
            slides.append([_clip(n.text) for n in root.iter()
                           if n.tag.endswith("}t") and n.text])
    return {"slides": slides}


# ── pdf ───────────────────────────────────────────────────────────────────────
def _read_pdf(path: str) -> dict:
    """{"pages": count}. Pages are drawn one at a time by render_pdf_page()."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        return {"pages": len(pdf)}
    finally:
        pdf.close()


def render_pdf_page(path: str, index: int, zoom: float = 1.0):
    """One PDF page as (width, height, RGBA bytes). pypdfium2 is already
    bundled for the HVAC takeoff; QtPdf is left out of the build on purpose."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(path)
    try:
        page = pdf[max(0, min(index, len(pdf) - 1))]
        bitmap = page.render(scale=max(0.25, min(zoom, 4.0)) * 1.35)
        img = bitmap.to_pil().convert("RGBA")
        return img.width, img.height, img.tobytes()
    finally:
        pdf.close()


# ── dxf ───────────────────────────────────────────────────────────────────────
def render_dxf(path: str, dpi: int = 130):
    """A DXF drawing as PNG bytes, drawn by ezdxf's own matplotlib backend
    (Agg: no window). Same approach as the BOQ add-on's cad_render, kept here
    because an add-on may not be imported from shared code."""
    import ezdxf
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    doc = ezdxf.readfile(path)
    fig = plt.figure(figsize=(9, 6.5))
    try:
        ax = fig.add_axes((0, 0, 1, 1))
        Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(
            doc.modelspace(), finalize=True)
        buf = io.BytesIO()
        fig.savefig(buf, dpi=dpi, format="png")
        return buf.getvalue()
    finally:
        plt.close(fig)


# ── entry ─────────────────────────────────────────────────────────────────────
def friendly_error(kind: str, exc: Exception) -> str:
    """A reason a person can act on, not a traceback."""
    name = type(exc).__name__
    if isinstance(exc, PermissionError):
        return ("Prism is not allowed to read this file. It may be open in "
                "another program, or in a protected folder.")
    if isinstance(exc, FileNotFoundError):
        return ("This file is no longer where Prism saved it. It may have been "
                "moved or deleted.")
    if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
        return "This file is password-protected, so Prism cannot show it."
    word = {"pdf": "PDF", "docx": "Word document", "xlsx": "workbook",
            "pptx": "presentation", "csv": "table", "dxf": "drawing"}.get(kind, "file")
    return (f"Prism could not read this {word}. It may be damaged or in a "
            f"format Prism does not know ({name}).")


def read(path: str) -> dict:
    """Everything the viewer needs to show `path`. Never raises."""
    kind = classify(path)
    out = {"kind": kind, "name": os.path.basename(path.rstrip("/\\")) or path,
           "path": path, "size": size_of(path), "error": ""}
    if not os.path.exists(path):
        out["error"] = friendly_error(kind, FileNotFoundError())
        return out
    try:
        if kind == "folder":
            return out
        if kind in ("docx", "xlsx", "pptx"):
            big = _too_big(path)
            if big:
                out["error"] = big
                return out
        reader = {"text": _read_text, "markdown": _read_text, "csv": _read_csv,
                  "xlsx": _read_xlsx, "docx": _read_docx, "pptx": _read_pptx,
                  "pdf": _read_pdf}.get(kind)
        if reader:
            out.update(reader(path))
        elif kind == "dxf":
            out["png"] = render_dxf(path)
    except ImportError as e:
        out["error"] = ("This copy of Prism is missing a part it needs to show "
                        f"this kind of file ({e.name or e}). Use “Open in another app”.")
    except Exception as e:                                # noqa: BLE001
        out["error"] = friendly_error(kind, e)
    return out
