"""The one shared "read the drawing" step (item 64, BOQ-CHANGES-TODO.md) --
used by every industry's drawing-reading path (ELV today; HVAC and General's
"Make with drawing" are meant to grow onto this too, not keep their own
separate logic).

Reading order, cheapest and most exact first, never the reverse:

  1. DXF real entities -- a DWG is converted to DXF first
     (core.boq.dwg_to_dxf()), then read via core.boq.measure()'s own
     `text_entities`/`block_counts` (item 65) -- the engine's own
     already-built, already-tested entity walk, reached only through
     CB.get_boq() per architecture rule 3, not a second parse of the same
     file: free, instant, exactly what is on the drawing, zero AI,
     nothing leaves this machine, so no consent prompt is needed for this
     path at all. If the file has no real text/block entities (common
     cause: the text was "exploded" into plain line/shape geometry by
     whatever drew it), this step finds nothing -- that absence is itself
     the signal, not a separate detector.
  2. AI-tiled reading -- only reached when step 1 found nothing (a plain
     PDF, or a DXF that turned out to be geometry-only). ALWAYS tiled,
     never "whole": a small drawing already collapses to one tile on its
     own (_tile_bounds() returns a single tile once the page fits inside
     max_dim), so "your drawing is never sent to AI as a whole" is simply
     true here, not a second mode with different wording to maintain.
     Every page of a multi-page file is read this way, not just the first
     -- found as a real gap (a PDF whose page 1 is cover text and page 2 is
     the actual drawing) before this module existed.

Either way, what a caller gets back is PLAIN TEXT (this module's own
`summary_text()`). The raw file itself is never hoisted onward from here --
once a drawing has been read, only the extracted text goes to the BOQ
write-up stage, never the file a second time.

This module itself never touches the network -- `tag_reader` is a plain
callback, built and owned by addons/boq/workers.py, the same boundary
elv_takeoff.py's own (now-superseded) reading functions already kept.
Stdlib + pypdfium2 + optional rapidocr, nothing that needs an API key or
ever sees one; every DXF entity read and the DWG->DXF conversion both
reach into the engine only through CB.get_boq(), per architecture rule 3
-- this module no longer imports ezdxf directly at all (item 65)."""
from __future__ import annotations

from datetime import datetime
import os

import core_bridge as CB

DRAWING_EXTENSIONS = (".pdf", ".dwg", ".dxf")


def _tile_bounds(w: int, h: int, max_dim: int = 2400, overlap: float = 0.08):
    """Same shape and reasoning as hvac_takeoff._tile_bounds() -- copied,
    not imported: this module stays independent of a module named for a
    different trade."""
    step = int(max_dim * (1 - overlap))
    xs = list(range(0, max(w - max_dim, 0) + 1, step)) or [0]
    if xs[-1] + max_dim < w:
        xs.append(w - max_dim)
    ys = list(range(0, max(h - max_dim, 0) + 1, step)) or [0]
    if ys[-1] + max_dim < h:
        ys.append(h - max_dim)
    return [(x, y, min(x + max_dim, w), min(y + max_dim, h)) for y in ys for x in xs]


_RAPIDOCR_ENGINE = None


def _rapidocr_engine():
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None:
        from rapidocr import RapidOCR
        _RAPIDOCR_ENGINE = RapidOCR(params={"Det.limit_side_len": 2880})
    return _RAPIDOCR_ENGINE


def render_page(pdf_path: str, page_index: int = 0, dpi: int = 250):
    """The page as a PIL Image, same rendering hvac_takeoff.ocr_page() uses."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(pdf_path)
    return pdf[page_index].render(scale=dpi / 72).to_pil().convert("RGB")


def page_count(pdf_path: str) -> int:
    import pypdfium2 as pdfium
    return len(pdfium.PdfDocument(pdf_path))


def _ocr_tile_text(tile_image) -> list[str]:
    try:
        import numpy as np
        engine = _rapidocr_engine()
    except Exception:
        return []
    try:
        result = engine(np.array(tile_image))
    except Exception:
        return []
    if result is None or result.txts is None:
        return []
    return [t for t in result.txts if t]


def _png_bytes(img) -> bytes:
    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def read_tiled_page(pdf_path: str, tag_reader, page_index: int = 0, dpi: int = 250,
                    max_dim: int = 2400, overlap: float = 0.08, log=print) -> dict:
    """One page, always tiled -- the SAME crop boxes hvac_takeoff.ocr_page()
    already uses, each tile read by BOTH RapidOCR (local) and `tag_reader`
    (the vision model). A page that already fits inside `max_dim` yields a
    single tile covering the whole page -- not a special case, just what
    _tile_bounds() already does, which is what makes "always tiled" the
    same thing as "whole" for a small drawing, with no second code path."""
    img = render_page(pdf_path, page_index, dpi)
    w, h = img.size
    tiles = _tile_bounds(w, h, max_dim=max_dim, overlap=overlap)
    log(f"  page {page_index + 1}: reading {len(tiles)} tile(s) (OCR + AI) ...")
    ocr_text: list[str] = []
    ai_text: list[str] = []
    for i, (x0, y0, x1, y1) in enumerate(tiles):
        crop = img.crop((x0, y0, x1, y1))
        ocr_text += _ocr_tile_text(crop)
        try:
            found = tag_reader(_png_bytes(crop))
        except Exception as e:                          # noqa: BLE001
            log(f"    tile {i + 1}/{len(tiles)}: AI read failed ({e})")
            found = ""
        if found:
            ai_text.append(found)
        log(f"    tile {i + 1}/{len(tiles)}: {len(ocr_text)} OCR string(s), "
            f"{len(ai_text)} AI read(s) so far")
    return {"page": page_index, "ocr_text": ocr_text, "ai_text": "\n".join(ai_text)}


def _read_dxf_entities(dxf_path: str) -> dict:
    """Real TEXT/MTEXT content and named INSERT block counts, straight off
    the DXF's modelspace -- zero AI, zero estimation.

    item 65: reached through `core.boq.measure()` (via CB.get_boq(), per
    architecture rule 3), not a second, independent ezdxf parse of the
    same file -- measure() already walks every TEXT/MTEXT/INSERT entity
    for HVAC's own geometry takeoff and now RETURNS that reading
    (`text_entities`, always collected, `hvac` only gates whether rule 3
    goes on to match them against a duct run). Before item 65, this
    function duplicated that same walk itself; now every caller -- the
    GUI's own auto-measure on attach, this module, the "Make with
    drawing" recheck step -- shares that one walk's answer instead of
    three independent, potentially-different ones."""
    boq = CB.get_boq()
    q = boq.measure(dxf_path, hvac=False)
    texts = [content for _, content in q["text_entities"]]
    return {"text": texts, "blocks": dict(q["block_counts"]),
            "entity_count": q["entity_count"]}


def extract(path: str, tag_reader, dpi: int = 250, log=print) -> dict:
    """The one entry point every industry's drawing reading now calls
    through. `path` is a PDF, DWG or DXF -- a DWG converts to DXF first.
    `tag_reader` is only ever reached for the AI-tiled fallback; a DXF with
    real entities never calls it at all."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in DRAWING_EXTENSIONS:
        raise ValueError(f"Unsupported drawing file type: {ext!r}")

    conv_notes: list[str] = []
    if ext == ".dwg":
        log("  converting .dwg to .dxf ...")
        boq = CB.get_boq()
        path, conv_notes = boq.dwg_to_dxf(path)
        ext = ".dxf"

    source_name = os.path.basename(path)

    if ext == ".dxf":
        log("  reading real DXF entities (no AI) ...")
        found = _read_dxf_entities(path)
        method = "dxf_entities" if (found["text"] or found["blocks"]) else "dxf_no_text"
        return {
            "tool": "drawing_reader v1",
            "generated": datetime.now().isoformat(timespec="seconds"),
            "source": {"file": source_name},
            "method": method,
            "notes": conv_notes,
            "dxf": found,
            "pages": [],
        }

    n_pages = page_count(path)
    log(f"  reading {n_pages} page(s), always tiled ...")
    pages = [read_tiled_page(path, tag_reader, page_index=pi, dpi=dpi, log=log)
             for pi in range(n_pages)]
    return {
        "tool": "drawing_reader v1",
        "generated": datetime.now().isoformat(timespec="seconds"),
        "source": {"file": source_name},
        "method": "ai_tiled",
        "notes": conv_notes,
        "dxf": None,
        "pages": pages,
    }


def summary_text(res: dict) -> str:
    """The plain-text handoff onward -- this, never the raw file, is what
    goes to the BOQ write-up stage from here on."""
    s = [f'File: {res["source"]["file"]}   method: {res["method"]}']
    if res["notes"]:
        s += [""] + [f"  note: {n}" for n in res["notes"]]

    if res["method"] == "dxf_entities":
        s += ["", "REAL DXF ENTITY DATA -- read directly off the drawing's own "
                  "text and block entities, zero AI, exactly as drawn."]
        dxf = res["dxf"]
        if dxf["text"]:
            s += ["", f'Text entities found ({len(dxf["text"])}):']
            s += [f"  {t}" for t in dxf["text"]]
        if dxf["blocks"]:
            s += ["", "Named block inserts found (device/symbol counts):"]
            s += [f"  {name}: {count}" for name, count in dxf["blocks"].items()]
        return "\n".join(s)

    if res["method"] == "dxf_no_text":
        s += ["", "This DXF has no real TEXT/MTEXT or named block (INSERT) "
                  "entities to read directly -- its labels and symbols were "
                  "most likely \"exploded\" into plain lines and shapes by "
                  "whatever drew it, which looks right on screen but carries "
                  "no readable text data at all. Export or print this drawing "
                  "to PDF and attach that instead -- the AI reading step can "
                  "then read it."]
        return "\n".join(s)

    # ai_tiled
    s += ["", "THIS IS AN AI READING OF THE DRAWING, NOT A MEASURED TAKEOFF. No "
              "vector geometry was measured -- counts, cable runs and device "
              "schedules below come from the vision model reading the "
              "drawing (and local OCR too), not from drawn line lengths. "
              "Verify every quantity against the drawing before pricing."]
    for page in res["pages"]:
        s += ["", f'--- page {page["page"] + 1} ---']
        if page["ocr_text"]:
            s += ["", "OCR text (read locally, never sent anywhere):"]
            s += [f"  {t}" for t in page["ocr_text"]]
        s += ["", "AI reading:"]
        s.append(page["ai_text"] or "(nothing read)")
    return "\n".join(s)
