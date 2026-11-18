"""What was counted, in plain words (stdlib only).

The "Check the count" step shows this above the table so a person sees what
the numbers rest on before trusting them: how many things were counted, from
which layers, what Prism flagged, and what is MEASURED (read off the drawing
by code) versus ESTIMATED (written by AI, only when the user lets it).

Everything here is read from fields the engines already return; nothing is
re-judged. `confidence` is the engines' own: geometry and text-layer reads are
exact (1.0), OCR and AI reads carry their own score, listed as unread when low.
"""
from __future__ import annotations

from collections import Counter


def _n(x) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return 0


def _plain(w: str) -> str:
    """The engines' own warnings, with the developer's words made plain."""
    if "No OCR labels" in w:
        return ("OCR is not available on this computer, so sizes and tags come only from "
                "the text inside the PDF. Tags drawn as lines or pictures were not read.")
    return w


def for_quantities(q: dict) -> dict:
    """A drawing measured by Prism's own geometry (DXF/DWG)."""
    lengths = q.get("lengths_by_layer") or {}
    areas = q.get("areas_by_layer") or {}
    blocks = q.get("block_counts") or {}
    notes = [str(x) for x in (q.get("notes") or [])]
    site = q.get("site") or {}
    flagged = len(site.get("lookalikes") or []) + len(site.get("remote_blocks") or []) + len(notes)
    rows = [
        ("Lengths measured", f"{len(lengths)} layer(s)"),
        ("Areas measured", f"{len(areas)} layer(s)"),
        ("Symbols counted", f"{sum(_n(v) for v in blocks.values())} in {len(blocks)} type(s)"),
    ]
    top = Counter({k: _n(v) for k, v in blocks.items()}).most_common(3)
    if top:
        rows.append(("Most common symbols", ", ".join(f"{k} x{v}" for k, v in top)))
    if not q.get("unit_confirmed", q.get("unit_code", 0) != 0):
        rows.append(("Unit", "not recorded in the file; check it before pricing"))
    headline = (f"{_n(q.get('entity_count')):,} drawing objects read; "
                f"{len(lengths)} length layer(s), {sum(_n(v) for v in blocks.values())} symbols; "
                f"{flagged} flagged")
    return {"headline": headline, "rows": rows, "flagged": flagged, "warnings": notes,
            "source": "measured",
            "basis": "Measured from the drawing by code, not by AI. Nothing here is an "
                     "estimate. Estimates only appear if you let the writer add items the "
                     "drawing does not contain, and they are marked as estimates."}


def for_takeoff(result: dict) -> dict:
    """A vector PDF measured by the HVAC tool (geometry plus OCR labels)."""
    runs = result.get("duct_runs") or []
    labels = result.get("labels") or []
    unread = result.get("unread") or []
    ft = 0.0
    for r in runs:
        ft += float(r.get("length_ft") or r.get("length") or 0) if isinstance(r, dict) else 0
    by_src = Counter((l.get("source") or "?") for l in labels if isinstance(l, dict))
    ocr = [l for l in labels if isinstance(l, dict) and str(l.get("source", "")).startswith(("ocr", "ai"))]
    low = [l for l in ocr if float(l.get("conf") or 1.0) < 0.6]
    warns = [_plain(str(w)) for w in (result.get("warnings") or [])]
    rows = [("Duct runs", f"{len(runs)}" + (f", about {ft:,.0f} ft" if ft else "")),
            ("Labels read", f"{len(labels)} (" + ", ".join(f"{k} {v}" for k, v in sorted(by_src.items())) + ")"
             if labels else "0")]
    rows.append(("Unreadable tags", f"{len(unread)}" if unread else "none"))
    st = result.get("settings") or {}
    rows.append(("OCR reads", str(sum(1 for l in labels if isinstance(l, dict)
                                      and str(l.get("source", "")).startswith("ocr")))))
    rows.append(("Prism AI tag check", "used" if st.get("ai_tag_recheck") else "not used"))
    if result.get("vav_tags") is not None:
        rows.append(("Air boxes (VAV) tags", f"{len(result.get('vav_tags') or [])} read; "
                     "a lower bound, count the rest on the drawing"))
    headline = f"{len(runs)} duct run(s), {len(labels)} label(s) read; {len(unread)} tag(s) unreadable"
    return {"headline": headline, "rows": rows, "flagged": len(unread) + len(low),
            "warnings": warns, "source": "measured+read",
            "ai_used": bool(st.get("ai_tag_recheck")),
            "ocr_reads": sum(1 for l in labels if isinstance(l, dict)
                             and str(l.get("source", "")).startswith("ocr")),
            "basis": "Duct lengths are measured from the PDF's lines. Sizes and tags are READ "
                     "from text (exact) or by OCR/AI (each carries a confidence). Nothing is an "
                     "estimate unless you let the writer add items."}


def for_reading(res: dict) -> dict:
    """A reading by the shared drawing reader (ELV; DXF text, or PDF/picture via OCR+AI)."""
    method = res.get("method", "")
    dxf = res.get("dxf") or {}
    pages = res.get("pages") or []
    if method == "dxf_entities":
        rows = [("Text found", str(len(dxf.get("text") or []))),
                ("Symbols found", f"{sum(_n(v) for v in (dxf.get('blocks') or {}).values())}"
                 f" in {len(dxf.get('blocks') or {})} type(s)")]
        headline = "Read straight from the drawing's own text and symbols"
        basis = "Read directly from the file by code. Not an AI reading."
        src = "measured"
    elif method == "dxf_no_text":
        rows = [("Text found", "0")]
        headline = "This DXF has no readable text or symbols"
        basis = "Export the drawing to PDF and read that instead."
        src = "none"
    else:
        ocr = sum(len(p.get("ocr_text") or []) for p in pages)
        ai = sum(1 for p in pages if (p.get("ai_text") or "").strip())
        rows = [("Pages read", str(len(pages))), ("Text read by OCR", str(ocr)),
                ("Pages the AI read", f"{ai} of {len(pages)}")]
        headline = f"{len(pages)} page(s) read by OCR and Prism AI"
        basis = ("This is a READING of the picture, not a measurement. Counts, cable runs "
                 "and schedules come from OCR and an AI vision model. Check every quantity "
                 "against the drawing.")
        src = "read"
    return {"headline": headline, "rows": rows, "flagged": 0,
            "warnings": [str(n) for n in (res.get("notes") or [])],
            "source": src, "basis": basis}


def for_description() -> dict:
    return {"headline": "Nothing was measured: no drawing", "rows": [], "flagged": 0,
            "warnings": [], "source": "estimated",
            "basis": "There is no drawing, so every quantity is an ESTIMATE written by AI "
                     "from your words and marked as one. Read each line yourself."}


def as_html(ev: dict) -> str:
    """The evidence as a few short lines for a label."""
    import html
    lines = [f"<b>{html.escape(ev['headline'])}</b>"]
    for k, v in ev["rows"]:
        lines.append(f"{html.escape(k)}: {html.escape(v)}")
    lines.append(f"<i>{html.escape(ev['basis'])}</i>")
    for w in ev["warnings"][:3]:
        lines.append("⚠ " + html.escape(w))
    if len(ev["warnings"]) > 3:
        lines.append(f"… and {len(ev['warnings']) - 3} more in the list below")
    return "<br>".join(lines)
