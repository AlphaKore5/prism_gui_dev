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
def _read_xlsx(path: str) -> dict:
    """Same shape as _read_csv, one sheet per worksheet. Shows each cell's last
    calculated value; a formula nobody has calculated yet (a file Prism wrote
    itself has no cached results) is shown as its formula text. Nothing runs."""
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    forms = load_workbook(path, read_only=True, data_only=False)
    sheets = []
    try:
        for ws, wf in list(zip(book.worksheets, forms.worksheets))[:MAX_SHEETS]:
            rows, more, cols_cut = [], False, False
            pairs = zip(ws.iter_rows(max_col=MAX_COLS + 1, values_only=True),
                        wf.iter_rows(max_col=MAX_COLS + 1, values_only=True))
            for row, frow in pairs:
                if len(rows) >= MAX_ROWS + 1:
                    more = True
                    break
                if any(c is not None and c != "" for c in row[MAX_COLS:]):
                    cols_cut = True
                shown = [f if v is None and isinstance(f, str) and f.startswith("=") else v
                         for v, f in zip(row, frow)]
                rows.append([_clip(c) for c in shown[:MAX_COLS]])
            while rows and not any(rows[-1]):          # a sheet's empty tail
                rows.pop()
            width = max((max((i + 1 for i, c in enumerate(r) if c), default=0)
                         for r in rows), default=0)
            rows = [(r + [""] * width)[:width] for r in rows]
            header = rows[0] if rows else []
            cols = [h or f"Column {i + 1}" for i, h in enumerate(header)]
            sheets.append({"name": ws.title, "columns": cols, "rows": rows[1:],
                           "rows_total": None if more else max(len(rows) - 1, 0),
                           "truncated": more, "cols_cut": cols_cut})
    finally:
        book.close()      # a read-only book keeps the file open: locks it on Windows
        forms.close()
    return {"sheets": sheets, "sheets_cut": len(book.worksheets) > MAX_SHEETS}


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
