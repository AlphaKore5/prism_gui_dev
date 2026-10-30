"""
HVAC Takeoff Extractor - simple desktop tool.

Pick a tender PDF (vector CAD plot), tell it which line colour is supply / return duct,
and it writes a JSON + CSV of measured duct runs, OCR'd labels (sizes, CFM, TR) and rooms.
Send the JSON to Claude to build the BOQ; engineering rules (gauge, allowance, insulation,
exclusions) are applied there, not here.

Run:   python hvac_takeoff.py                      GUI
       python hvac_takeoff.py file.pdf --list      list line layers
       python hvac_takeoff.py file.pdf --map "#000000@1.56:line=supply" "#ff0000@1.08:line=return"   headless
Needs: pip install pdfplumber pypdfium2 pillow rapidocr onnxruntime   (OCR models ship in the wheel -- no separate binary install)
"""
import bisect, csv, json, math, os, re, sys, threading
from collections import defaultdict
from datetime import datetime

import pdfplumber

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MAP_FILE = os.path.join(APP_DIR, "layer_map.json")   # remembers colour -> role between tenders
# "system" vocabulary -- matches the parameter schema's ducts (4) / pipes (8)
# "system" field directly, so a mapped role becomes a meaningful value in
# the output with no renaming step, not a generic "pipe" bucket.
ROLES = [
    "ignore",
    # air side
    "supply", "return", "fresh_air", "exhaust", "toilet_exhaust",
    "kitchen_exhaust", "smoke_extract", "stair_pressurization", "transfer",
    # water / refrigerant side -- KNOWN GAP: pair_runs() only pairs two
    # parallel walls (rectangular duct). A pipe drawn as a single
    # centreline (the common convention) has no second wall to pair with
    # and is silently dropped by min_w_in's 4" floor -- not measured, not
    # even reported as a miss. Not fixed here; needs its own real-file
    # test the same way the duct rules did before being trusted.
    "chw_supply", "chw_return", "condenser_water", "refrigerant_liquid",
    "refrigerant_suction", "condensate", "hot_water", "makeup_water",
    # symbols -- a RECT-kind layer counted as a repeating shape, not
    # measured as duct wall. A PDF export rarely keeps a reusable block
    # reference the way a DXF INSERT does; every occurrence is literal,
    # flattened geometry, so this counts rectangles, not named blocks.
    "diffuser", "flex_connector", "volume_damper",
]
_PIPE_ROLES = {"chw_supply", "chw_return", "condenser_water", "refrigerant_liquid",
               "refrigerant_suction", "condensate", "hot_water", "makeup_water"}
# Reverse-engineered from the real ASPENTECH drawing, 24 Oct 2026: a
# damper's outer and inner square share a layer with the building's own
# giant outline rectangle (and a few unrelated elongated rects) -- a size
# cap, tuned from that file's own measurements, keeps the symbol and
# excludes the rest. Per-role because a diffuser/connector square is a
# different real size than a damper's.
SYMBOL_ROLES = {"diffuser", "flex_connector", "volume_damper"}
_SYMBOL_MAX_PT = {"diffuser": 20.0, "flex_connector": 20.0, "volume_damper": 12.0}
SCALES = {  # label -> points on paper per real foot
    '1/8" = 1\'-0"': 0.125 * 72, '3/16" = 1\'-0"': 0.1875 * 72, '1/4" = 1\'-0"': 0.25 * 72,
    '3/32" = 1\'-0"': 0.09375 * 72, '1:50': 12 / 50 * 72, '1:100': 12 / 100 * 72, '1:200': 12 / 200 * 72,
}

# ---------------------------------------------------------------- helpers
def color_hex(c):
    if c is None: return "#000000"
    if isinstance(c, (int, float)): c = (c,)
    c = tuple(float(v) for v in c)
    if len(c) == 1: r = g = b = c[0]
    elif len(c) == 3: r, g, b = c
    elif len(c) == 4:  # CMYK
        k = c[3]; r, g, b = [(1 - v) * (1 - k) for v in c[:3]]
    else: return "#000000"
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in (r, g, b))

def iter_segments(page):
    """Every straight segment on the page with its colour, line weight and kind:
    line = plain CAD line, rect = rectangle side, poly = polyline / filled outline segment."""
    for l in page.lines:
        yield l, "line", (l["x0"], l["top"], l["x1"], l["bottom"])
    for r in page.rects:
        x0, y0, x1, y1 = r["x0"], r["top"], r["x1"], r["bottom"]
        for seg in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x0, y1, x1, y1), (x0, y0, x0, y1)):
            yield r, "rect", seg
    for c in page.curves:
        pts = c.get("pts") or []
        for (xa, ya), (xb, yb) in zip(pts, pts[1:]):
            yield c, "poly", (xa, ya, xb, yb)

def layer_key(obj, kind):
    """colour@weight:kind - kind separates plain lines, rectangle sides and polylines,
    because CAD plots ducts, grilles and wide polylines as different object types."""
    col = obj.get("stroking_color") if obj.get("stroke", True) and obj.get("stroking_color") is not None else obj.get("non_stroking_color")
    return f"{color_hex(col)}@{round(obj.get('linewidth') or 0, 2)}:{kind}"

def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    t = 0 if L2 == 0 else max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

# ---------------------------------------------------------------- step 1: layers
def scan_layers(pdf_path):
    """Group every straight edge (lines, rectangle sides, polyline segments) by (colour, line weight)."""
    groups = defaultdict(lambda: {"segments": 0, "length_pt": 0.0, "pages": set()})
    with pdfplumber.open(pdf_path) as pdf:
        for pi, page in enumerate(pdf.pages):
            for obj, kind, (x0, y0, x1, y1) in iter_segments(page):
                g = groups[layer_key(obj, kind)]
                g["segments"] += 1
                g["length_pt"] += math.hypot(x1 - x0, y1 - y0)
                g["pages"].add(pi)
    out = [{"key": k, "color": k.split("@")[0], "linewidth": float(k.split("@")[1].split(":")[0]), "kind": k.split(":")[1],
            "segments": v["segments"], "length_pt": v["length_pt"], "pages": sorted(v["pages"])}
           for k, v in groups.items()]
    return sorted(out, key=lambda d: -d["length_pt"])

def layer_lines(pdf_path, key, page_index):
    with pdfplumber.open(pdf_path) as pdf:
        p = pdf.pages[page_index]
        return [seg for obj, kind, seg in iter_segments(p) if layer_key(obj, kind) == key], (p.width, p.height)

def layer_preview_png(pdf_path, key, page_index=0, dpi=100):
    """What a Layer-mapping row's colour swatch/segment-count actually
    draws, as a picture instead of a guess -- the same "render one layer
    alone, look at it" technique that caught the #808080
    perimeter-mapped-as-duct bug by eye (BOQ-CHANGES-TODO.md item 25e: a
    whole return-air total was wrong because that layer turned out to be
    the building's own wall outline, not ductwork, found only once it was
    rendered alone and recognised). This is that same check, wired as a
    one-click tool in Step 1 instead of a one-off debug script -- the
    confusion it fixes was pointed out directly against a rival PDF-takeoff
    tool that already offers it (BOQ-CHANGES-TODO.md item 33).

    Returns PNG bytes, not a file path -- a person still deciding every
    layer's role may click this on many of them in one sitting, and
    writing a file next to the client's PDF on every click would litter
    their folder for a result nobody keeps."""
    import io
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    img = pdfium.PdfDocument(pdf_path)[page_index].render(scale=dpi / 72).to_pil().convert("RGB")
    img = Image.blend(img, Image.new("RGB", img.size, "white"), 0.75)
    dr = ImageDraw.Draw(img)
    segs, _ = layer_lines(pdf_path, key, page_index)
    k = dpi / 72
    for x0, y0, x1, y1 in segs:
        dr.line([x0 * k, y0 * k, x1 * k, y1 * k], fill=(230, 0, 0), width=3)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def count_symbol_rects(page, layer_map: dict, role: str) -> list:
    """Centre position AND size (w_pt, h_pt) of every rect on a layer
    mapped to `role`, deduped by position and filtered to a plausible
    size for that role. Returns (cx, cy, w_pt, h_pt) tuples.

    Deduped because a symbol can be two overlapping rects, not one (a
    damper's outer and inner square, found on the real file) -- counting
    raw rects there would double every damper. The OUTER (larger) of a
    nested pair is kept as the symbol's own size -- billing an item by its
    footprint (item 27 rule 3, the client's own "VCD taken in sq.m" note)
    needs the frame someone would actually cut a hole for, not whichever
    of the pair happened to be scanned first. Filtered because the same
    colour/weight that draws the symbol can also carry something else
    entirely that happens to share it (a page border, in the real file)."""
    cap = _SYMBOL_MAX_PT.get(role, 20.0)
    cands = []
    for r in page.rects:
        if layer_map.get(layer_key(r, "rect"), "ignore") != role:
            continue
        w, h = abs(r["x1"] - r["x0"]), abs(r["bottom"] - r["top"])
        if w > cap or h > cap:
            continue
        cands.append(((r["x0"] + r["x1"]) / 2, (r["top"] + r["bottom"]) / 2, w, h))
    out = []
    for cx, cy, w, h in cands:
        match = next((o for o in out if math.hypot(cx - o[0], cy - o[1]) < 2.0), None)
        if match is None:
            out.append([cx, cy, w, h])
        elif w * h > match[2] * match[3]:
            match[2], match[3] = w, h
    return [tuple(o) for o in out]


def count_symbol_curves(page, layer_map: dict, role: str, max_extent_pt: float = 50.0) -> list:
    """Same job as count_symbol_rects(), for a symbol drawn as a filled
    POLYLINE instead of a rectangle. Found reverse-engineering the real
    file, 29 Oct 2026 (BOQ-CHANGES-TODO.md item 29d): the real manual
    volume-control-damper symbol is a hatched rectangle with a bowtie
    blade mark, exactly 8 of them on the one real test page, every one
    visually confirmed against the rendered drawing -- not count_symbol_
    rects' small square damper icon (that one, `#ff0000@1.08:rect`, turned
    out to be a different, unidentified symbol -- see item 28a). Returns
    (cx, cy, w_pt, h_pt) tuples, same shape as count_symbol_rects().

    `max_extent_pt` is looser than count_symbol_rects' per-role cap
    (9-20pt): this symbol's own bounding box runs the damper's drawn
    length along the duct (36-44pt / ~4-5ft on the real file), not a
    small fixed icon size -- a plain, generous ceiling, not tuned against
    a labelled set."""
    out = []
    for c in page.curves:
        if layer_map.get(layer_key(c, "poly"), "ignore") != role:
            continue
        pts = c.get("pts") or []
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if max(w, h) > max_extent_pt:
            continue
        cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
        if not any(math.hypot(cx - o[0], cy - o[1]) < 2.0 for o in out):
            out.append((cx, cy, w, h))
    return out

# ---------------------------------------------------------------- step 2: duct runs
def _merge(segs):
    """Join collinear overlapping/duplicate segments (CAD plots split lines into many pieces)."""
    by_c = defaultdict(list)
    for c, a, b in segs: by_c[round(c, 1)].append((a, b))
    out = []
    for c, iv in by_c.items():
        iv.sort(); ca, cb = iv[0]
        for a, b in iv[1:]:
            if a <= cb + 0.3: cb = max(cb, b)
            else: out.append((c, ca, cb)); ca, cb = a, b
        out.append((c, ca, cb))
    return sorted(out)

def pair_runs(lines, pt_per_ft, min_w_in=4, max_w_in=48, min_len_ft=1.5, step=0.5):
    """Duct = two parallel walls. For each wall and each point along it, the partner is the nearest
    parallel wall above/right within a plausible duct width. max_w_in caps false pairs between two neighbouring ducts. H/V ducts only."""
    H, V = [], []
    for x0, y0, x1, y1 in lines:
        if abs(y1 - y0) < 0.3 and abs(x1 - x0) > 1: H.append((y0, min(x0, x1), max(x0, x1)))
        elif abs(x1 - x0) < 0.3 and abs(y1 - y0) > 1: V.append((x0, min(y0, y1), max(y0, y1)))
    lo, hi = min_w_in / 12 * pt_per_ft, max_w_in / 12 * pt_per_ft
    out = []
    for orient, segs in (("H", _merge(H)), ("V", _merge(V))):
        cs = [s[0] for s in segs]
        def up(c, t):    # nearest wall above c covering t
            for c2, a2, b2 in segs[bisect.bisect_left(cs, c + lo):bisect.bisect_right(cs, c + hi)]:
                if a2 <= t <= b2: return c2
        for c, a, b in segs:
            cur, t = None, a + step / 2
            while t < b:
                p = up(c, t)
                if cur and p == cur[0]: cur[2] = t
                else:
                    if cur: out.append((orient, c, *cur))
                    cur = [p, t, t] if p is not None else None
                t += step
            if cur: out.append((orient, c, *cur))
    res = []
    for orient, c, c2, a, b in out:
        length_ft = (b - a + step) / pt_per_ft
        if length_ft < min_len_ft: continue
        mid = (c + c2) / 2
        x1, y1, x2, y2 = (a - step / 2, mid, b + step / 2, mid) if orient == "H" else (mid, a - step / 2, mid, b + step / 2)
        res.append({"orientation": orient, "width_in": round((c2 - c) / pt_per_ft * 12),
                    "length_ft": round(length_ft, 2), "pt": (x1, y1, x2, y2)})
    return res

def split_by_labels(run, sizes, pt_per_ft, match_ft):
    """A run of constant drawn width can change depth along its length (e.g. 20x30 -> 20x26).
    Find every size label near the run whose width matches; split the run between label positions."""
    x1, y1, x2, y2 = run["pt"]; H = run["orientation"] == "H"
    a, b = (x1, x2) if H else (y1, y2)
    R = match_ft * pt_per_ft
    for tier in ("w", "d"):
        hits = []
        for s in sizes:
            v = s["w_in"] if tier == "w" else s["d_in"]
            if abs(v - run["width_in"]) > 1: continue
            d = seg_dist(s["x_pt"], s["y_pt"], x1, y1, x2, y2)
            if d < (R if tier == "w" else 2 * pt_per_ft): hits.append((max(a, min(b, s["x_pt"] if H else s["y_pt"])), d, s))
        if hits: break
    if not hits:
        r = dict(run); r.update({"label": None, "depth_in": None}); return [r]
    # one label per position along the run (closest wins), sorted along the run
    hits.sort(key=lambda h: h[1]); keep = []
    for h in hits:
        if all(abs(h[0] - k[0]) > 2 * pt_per_ft for k in keep): keep.append(h)
    keep.sort(key=lambda h: h[0])
    cuts = [a] + [(keep[i][0] + keep[i + 1][0]) / 2 for i in range(len(keep) - 1)] + [b]
    pieces = []
    for i, (_, d, s) in enumerate(keep):
        ca, cb = cuts[i], cuts[i + 1]
        if cb - ca < 0.5 * pt_per_ft: continue
        w, dd = (s["w_in"], s["d_in"]) if tier == "w" else (s["d_in"], s["w_in"])
        pt = (ca, y1, cb, y2) if H else (x1, ca, x2, cb)
        pieces.append({"orientation": run["orientation"], "width_in": w, "depth_in": dd, "label": f'{s["w_in"]}x{s["d_in"]}',
                       "label_dist_ft": round(d / pt_per_ft, 1), "length_ft": round((cb - ca) / pt_per_ft, 2), "pt": pt})
    return pieces

# ---------------------------------------------------------------- step 3: labels
SIZE_RE = re.compile(r'(\d{1,3})"?\s*x\s*(\d{1,3})"?')
CFM_RE = re.compile(r'(\d{2,5})\s*(?:c\s*f\s*i?\s*m|ctm|crm|cfrn)\b', re.I)
TR_RE = re.compile(r'(\d{1,3}(?:\.\d)?)\s*TR\b')
SQFT_RE = re.compile(r'(\d{2,5})\s*Sq\.?\s*Ft', re.I)
# Found reverse-engineering a real tender drawing (ASPENTECH), 24 Oct 2026:
# small wall-mounted split units are noted on the drawing itself, not drawn
# as a distinct countable block -- "2TR HI-WALL", sometimes with the
# installed count given a line below as "2NOS." (a separate OCR box, not
# the same string). TR_RE alone already matched the "2TR" inside this and
# silently folded it into the generic tonnage list, indistinguishable from
# the main rooftop unit's own "17 TR" -- HIWALL_RE claims that span first
# (parse_label skips the generic TR_RE match on the same text once this
# fires) so it becomes its own equipment entry instead.
HIWALL_RE = re.compile(r'(\d{1,2}(?:\.\d)?)\s*TR\s*HI[\s-]*WALL', re.I)
NOS_RE = re.compile(r'(\d{1,2})\s*NOS\.?', re.I)

def norm(t):
    t = re.sub(r'[°’‘“”\'`]', '"', t)
    return t.replace('×', 'x').replace('X', 'x').replace('%', 'x')

def parse_label(text, x, y, source, conf=1.0):
    t = norm(text)
    found = []
    for m in SIZE_RE.finditer(t):
        w, d = int(m.group(1)), int(m.group(2))
        if 2 <= w <= 120 and 2 <= d <= 120:
            found.append({"kind": "size", "w_in": w, "d_in": d, "text": text, "x_pt": x, "y_pt": y, "source": source, "conf": conf})
    for m in CFM_RE.finditer(t):
        found.append({"kind": "cfm", "cfm": int(m.group(1)), "text": text, "x_pt": x, "y_pt": y, "source": source, "conf": conf})
    hiwall_spans = []
    for m in HIWALL_RE.finditer(t):
        hiwall_spans.append(m.span())
        found.append({"kind": "equipment", "type": "Hi-Wall Split AC", "capacity_tr": float(m.group(1)),
                      "text": text, "x_pt": x, "y_pt": y, "source": source, "conf": conf})
    for m in TR_RE.finditer(text):
        if any(s <= m.start() < e for s, e in hiwall_spans):
            continue   # already captured as a Hi-Wall unit's own capacity, not a second generic TR tag
        found.append({"kind": "tr", "tr": float(m.group(1)), "text": text, "x_pt": x, "y_pt": y, "source": source, "conf": conf})
    for m in NOS_RE.finditer(t):
        found.append({"kind": "nos", "nos": int(m.group(1)), "text": text, "x_pt": x, "y_pt": y, "source": source, "conf": conf})
    return found


def _equipment_from_labels(labels: list, pt_per_ft: float, match_ft: float = 3.0) -> list:
    """Hi-Wall units: the capacity note and the installed count are often
    two separate text boxes on the drawing (the count a line below the
    capacity) -- joined here by proximity, not assumed to be the same
    string. No "NOS." found nearby means a single unit's own note, not a
    missing count, so qty defaults to 1 rather than being left blank."""
    hiwalls = [l for l in labels if l["kind"] == "equipment"]
    nos = [l for l in labels if l["kind"] == "nos"]
    r = match_ft * pt_per_ft
    out = []
    for h in hiwalls:
        best = None
        for n in nos:
            if n["page"] != h["page"]:
                continue
            d = math.hypot(n["x_pt"] - h["x_pt"], n["y_pt"] - h["y_pt"])
            if d < r and (best is None or d < best[1]):
                best = (n, d)
        qty = best[0]["nos"] if best else 1
        conf = h["conf"] if best is None else round((h["conf"] + best[0]["conf"]) / 2, 3)
        out.append({"tag": "", "type": h["type"], "capacity": f'{h["capacity_tr"]:g}TR', "qty": qty,
                    "room": "", "page": h["page"], "x_pt": h["x_pt"], "y_pt": h["y_pt"],
                    "source": h["source"], "conf": conf})
    return out

def _lines_from_words(words, vertical):
    """Group words into text lines; split where the gap is large (CAD often puts unrelated text on one row)."""
    lines = []
    key = (lambda w: (round(w["x0"]), -w["bottom"])) if vertical else (lambda w: (round(w["top"]), w["x0"]))
    for w in sorted(words, key=key):
        h = (w["x1"] - w["x0"]) if vertical else (w["bottom"] - w["top"])
        for ln in lines:
            if vertical: same = abs(ln["x0"] - w["x0"]) < 2 and -1 < ln["top"] - w["bottom"] < 1.5 * h
            else: same = abs(ln["top"] - w["top"]) < 2 and -1 < w["x0"] - ln["x1"] < 1.5 * h
            if same:
                ln["text"] += " " + w["text"]
                ln.update(x0=min(ln["x0"], w["x0"]), x1=max(ln["x1"], w["x1"]), top=min(ln["top"], w["top"]), bottom=max(ln["bottom"], w["bottom"]))
                break
        else:
            lines.append(dict({k: w[k] for k in ("text", "x0", "x1", "top", "bottom")}, vertical=vertical))
    return lines

def text_layer(page, pi):
    """Real (selectable) text: rooms, notes, and labels if the CAD used TrueType fonts."""
    upright = page.filter(lambda o: o.get("object_type") != "char" or o.get("upright", True))
    rotated = page.filter(lambda o: o.get("object_type") != "char" or not o.get("upright", True))
    lines = _lines_from_words(upright.extract_words(), False)
    try: lines += _lines_from_words(rotated.extract_words(char_dir_rotated="btt"), True)  # vertical text, read bottom-to-top
    except TypeError: pass
    labels, rooms, notes = [], [], []
    for ln in lines:
        x, y = (ln["x0"] + ln["x1"]) / 2, (ln["top"] + ln["bottom"]) / 2
        labels += parse_label(ln["text"], x, y, "text")
        m = SQFT_RE.search(ln["text"])
        if m:
            name = re.sub(r"[^A-Za-z0-9/&()\- ]", " ", SQFT_RE.sub("", ln["text"])).strip()
            if len(name) < 3:  # name is the text block just above (or just left, for vertical text)
                vert = ln.get("vertical")
                def gap(o): return (ln["x0"] - o["x1"]) if vert else (ln["top"] - o["bottom"])
                def overlap(o): return (o["top"] < ln["bottom"] and o["bottom"] > ln["top"]) if vert else (o["x0"] < ln["x1"] and o["x1"] > ln["x0"])
                cand = [o for o in lines if o.get("vertical") == vert and -1 < gap(o) < 25 and overlap(o)
                        and not SQFT_RE.search(o["text"]) and not TR_RE.search(o["text"]) and o["text"] != "CR"]
                if cand:
                    g0 = min(gap(o) for o in cand)
                    block = [o for o in cand if gap(o) < g0 + 12]
                    name = " ".join(o["text"] for o in sorted(block, key=lambda o: (o["x0"] if vert else o["top"])))
            rooms.append({"name": name, "sqft": int(m.group(1)), "x_pt": x, "y_pt": y, "page": pi})
        elif len(ln["text"]) > 1:
            notes.append({"text": ln["text"], "x_pt": x, "y_pt": y, "page": pi})
    return labels, rooms, notes

_RAPIDOCR_ENGINE = None   # built once, reused across pages -- loading the ONNX models is the slow part


def _rapidocr_engine():
    global _RAPIDOCR_ENGINE
    if _RAPIDOCR_ENGINE is None:
        from rapidocr import RapidOCR
        # Default Det.limit_side_len (736) downscales a page rendered at
        # typical takeoff DPI (4000+ px on the long side) hard enough to
        # crush small CAD label text before detection even runs -- found
        # live: it cut the real match rate from Tesseract's 32% to 23%.
        # 2880 recovered it and more: full-pipeline match rate on the real
        # tender PDF went 32% (Tesseract) -> 43% (this), two independent
        # runs, both logged.
        # "Det.model_type"/"Rec.model_type" -> ModelType.MEDIUM was also
        # tried (they take an internal Enum, not the plain string that
        # looks right and raises "must be Enum Type" instead) -- built
        # successfully once the Enum import was fixed, but measured WORSE
        # on the same file (43% -> 31%), so left at the package default
        # ("small") rather than kept on the assumption that a bigger
        # model is automatically a better one.
        _RAPIDOCR_ENGINE = RapidOCR(params={"Det.limit_side_len": 2880})
    return _RAPIDOCR_ENGINE


def ocr_page(pdf_path, pi, dpi=250, log=print):
    """OCR for labels drawn as SHX strokes (invisible to text extraction).

    RapidOCR (ONNX Runtime, bundled PP-OCRv6-small models) instead of
    Tesseract. Still two passes, 0 and 90 degrees -- found testing against
    a real tender drawing: RapidOCR's angle classifier only flips upside-
    down text (its own label set is just "0"/"180"), it does not read
    genuinely sideways (90-degree) text at all, and a real CAD drawing's
    vertical dimension/CFM labels are exactly that. A single pass missed
    130 real labels (sizes, CFM, even a "2TR HI-WALL" note) the 90-degree
    pass alone caught. What IS gone: no longer a separate OS-level program
    to install -- RapidOCR's models ship inside the pip wheel."""
    try:
        import numpy as np
        import pypdfium2 as pdfium
        engine = _rapidocr_engine()
    except Exception as e:
        log(f"  OCR skipped (RapidOCR not available: {e.__class__.__name__})")
        return []
    pdf = pdfium.PdfDocument(pdf_path)
    img = pdf[pi].render(scale=dpi / 72).to_pil().convert("RGB")
    W, H = img.size
    k = 72 / dpi
    out = []
    for angle in (0, 90):
        log(f"  OCR pass {angle} deg ...")
        im = img if angle == 0 else img.rotate(-90, expand=True)
        result = engine(np.array(im))
        if result.boxes is None:
            continue
        scores = result.scores or [1.0] * len(result.boxes)
        for box, txt, conf in zip(result.boxes, result.txts, scores):
            # RapidOCR's box coordinates are numpy float32 -- not JSON
            # serializable, so cast to plain Python float right away.
            cx = float(sum(p[0] for p in box) / len(box))
            cy = float(sum(p[1] for p in box) / len(box))
            if angle == 90:
                cx, cy = cy, H - 1 - cx   # map back to page pixels
            # real per-box confidence from the model itself, not a
            # placeholder -- the "quality fields" the parameter schema
            # asks for on every entry.
            out += parse_label(txt, cx * k, cy * k, f"ocr{angle}", conf=float(conf))
    # de-duplicate the same label seen twice -- keep the higher-confidence
    # read when both passes caught it, not just whichever ran first.
    uniq = []
    for l in out:
        dupe = next((u for u in uniq if u["kind"] == l["kind"] and u["text"] == l["text"]
                    and abs(u["x_pt"] - l["x_pt"]) < 6 and abs(u["y_pt"] - l["y_pt"]) < 6), None)
        if dupe is None:
            uniq.append(l)
        elif l["conf"] > dupe["conf"]:
            uniq[uniq.index(dupe)] = l
    return uniq


def _label_value_key(l: dict):
    """What makes two labels "the same reading" regardless of kind."""
    if l["kind"] == "size": return (l["w_in"], l["d_in"])
    if l["kind"] == "cfm": return (l["cfm"],)
    if l["kind"] == "tr": return (l["tr"],)
    if l["kind"] == "nos": return (l["nos"],)
    if l["kind"] == "equipment": return (l["type"], l["capacity_tr"])
    return (l.get("text"),)


def dedupe_labels(labels: list, pt_per_ft: float, radius_ft: float = 1.0) -> list:
    """The same physical label can be read twice -- once as real
    (selectable) text, once by OCR scanning the same rasterised page,
    which has no way to know real text already caught it there. Found
    live: the drawing's real "17 TR" label was present in both a
    text-sourced and an ocr90-sourced entry at the same spot, double-
    counting the one real rooftop unit (ocr_page()'s own de-dup only
    compares its two OCR passes against each other, never against the
    text layer). Keeps one entry per (kind, value, position) cluster --
    real text wins over OCR (it is exact, not a guess); among OCR-only
    entries, the higher-confidence read wins. Two genuinely separate
    occurrences of the same value stay separate -- this only merges
    entries within `radius_ft` of each other, not every "17 TR" on the
    sheet."""
    def rank(l):
        return (0 if l["source"] == "text" else 1, -l.get("conf", 1.0))
    r = radius_ft * pt_per_ft
    out = []
    for l in sorted(labels, key=rank):
        dupe = next((o for o in out if o["kind"] == l["kind"] and o["page"] == l["page"]
                    and _label_value_key(o) == _label_value_key(l)
                    and math.hypot(o["x_pt"] - l["x_pt"], o["y_pt"] - l["y_pt"]) < r), None)
        if dupe is None:
            out.append(l)
    return out


def _is_secondary_duct_pixel(r, g, b):
    """True for the orange/tan ink the drawing's second duct subsystem
    uses, false for the primary black/grey one. Thresholds set from real
    pixels sampled off the actual tender PDF, not guessed: every real
    orange label read (255, 163-198, 72-142); every real black/grey one
    (even when contaminated by a nearby coloured gridline bleeding into
    the sample radius) stayed within ~30 of R==G==B, nowhere near this
    margin."""
    return r > 200 and (r - b) > 80 and g > b


def _classify_duct_label_colors(pdf_path, pi, labels, dpi=150):
    """Tags each size/CFM label with whether it's drawn in the orange/tan
    ink a SECOND duct subsystem uses on this drawing -- found live, real
    on the page: every room has a primary black size/CFM pair (e.g.
    "20"x30"/4000cfm") and a second one right below it in orange (e.g.
    "36"x8"/600cfm"). What that second number actually represents --
    secondary branch? return tie-in? an older system? -- has no legend on
    this sheet and isn't geometry-derivable; left unresolved, for the
    write-up agent to ask about, not guessed here.

    Both labels are SHX-stroke text (OCR-read, not real selectable text --
    see ocr_page()), so OCR gives back no colour of its own. Sampled
    directly from the rendered page's own pixels instead, at each label's
    position: real orange reads ~(255, 165-200, 75-140), real black/grey
    reads as near-equal R/G/B -- confirmed against this file before
    picking the threshold, not guessed."""
    targets = [l for l in labels if l["kind"] in ("size", "cfm")]
    if not targets:
        return
    import pypdfium2 as pdfium
    img = pdfium.PdfDocument(pdf_path)[pi].render(scale=dpi / 72).to_pil().convert("RGB")
    px = img.load()
    W, H = img.size
    k = dpi / 72
    for l in targets:
        cx, cy = int(l["x_pt"] * k), int(l["y_pt"] * k)
        cols = [px[x, y] for x in range(max(0, cx - 6), min(W, cx + 7))
                for y in range(max(0, cy - 6), min(H, cy + 7)) if px[x, y] != (255, 255, 255)]
        if not cols:
            l["is_secondary_duct_color"] = False
            continue
        r = sum(c[0] for c in cols) / len(cols)
        g = sum(c[1] for c in cols) / len(cols)
        b = sum(c[2] for c in cols) / len(cols)
        l["is_secondary_duct_color"] = _is_secondary_duct_pixel(r, g, b)

# ---------------------------------------------------------------- main extraction
def _isolated_runs(duct_runs: list, tol_ft: float = 2.0) -> list:
    """item 29c: a measured run that connects to NOTHING else, at either
    end, within the same system -- a real anomaly, not just a normal
    dead end. Every terminal run in a real network is free at ONE end
    (where it reaches a diffuser, an AHU, a stub) -- that is completely
    normal and NOT flagged. A run free at BOTH ends never ties into the
    network at all, which is what a misread, a duplicate fragment, or
    junk geometry looks like.

    REPORT-ONLY: this never alters a run, a length or a total. Deliberately
    narrower than the DXF pipeline's own rejected gap-bridging idea
    (`HVAC_DRAWING_RULES.md` rule 2, built, shipped, then had to be
    walked back after misreading a real branch tee-junction as a gap) --
    that one changed a MEASUREMENT from a proximity guess; this only ever
    adds a warning, so the same mistake can't repeat here even if the
    proximity guess is sometimes wrong.

    `tol_ft=2.0`: checked against the real file, not picked blind -- at
    1.0 ft it flagged 90 of 145 runs (false-positive flood, ordinary CAD
    gaps are often wider than that); at 2.0 ft it flagged exactly the
    short, unlabeled runs this file's own write-up had already named by
    hand (the "very short identical runs... may be collars, stubs or
    symbol edges" note) -- a plain middle value chosen because it
    reproduces a known real anomaly without flooding, not tuned against a
    labelled test set."""
    by_system = defaultdict(list)
    for r in duct_runs:
        by_system[r["system"]].append(r)
    out = []
    for rs in by_system.values():
        for i, r in enumerate(rs):
            a = (r["x1_ft"], r["y1_ft"])
            b = (r["x2_ft"], r["y2_ft"])
            connects = False
            for j, r2 in enumerate(rs):
                if j == i:
                    continue
                for p in ((r2["x1_ft"], r2["y1_ft"]), (r2["x2_ft"], r2["y2_ft"])):
                    if math.hypot(a[0] - p[0], a[1] - p[1]) < tol_ft or \
                       math.hypot(b[0] - p[0], b[1] - p[1]) < tol_ft:
                        connects = True
                        break
                if connects:
                    break
            if not connects:
                out.append(r)
    return out


def extract(pdf_path, layer_map, pt_per_ft, use_ocr=True, dpi=250, match_ft=8, log=print):
    result = {"tool": "hvac_takeoff v2", "generated": datetime.now().isoformat(timespec="seconds"),
              "source": {"file": os.path.basename(pdf_path)}, "settings": {"pt_per_ft": pt_per_ft,
              "layer_map": layer_map, "ocr": use_ocr, "label_match_radius_ft": match_ft},
              "duct_runs": [], "duct_summary": [], "labels": [], "rooms": [], "notes": [], "warnings": [],
              # Present in every output, honestly empty rather than
              # absent, for whichever of these this tool still does not
              # extract: equipment is now Hi-Wall units only (item 1,
              # from a drawing note); terminals/accessories now hold
              # diffusers/flex connectors/dampers counted by shape when a
              # layer is mapped to that role (item 2) -- neither is
              # complete (equipment/duct type, legend auto-read, schedule
              # tables, multi-sheet links are still genuinely untouched).
              "equipment": [], "duct_fittings": [], "accessories": [],
              "terminals": [], "legend": [], "schedules": [], "links": [],
              "unresolved_duct_labels": []}
    with pdfplumber.open(pdf_path) as pdf:
        md = pdf.metadata or {}
        result["source"].update({"pages": len(pdf.pages), "creator": md.get("Creator"), "created": md.get("CreationDate"),
                                 "page_size_pt": [round(pdf.pages[0].width), round(pdf.pages[0].height)]})
        for pi, page in enumerate(pdf.pages):
            log(f"Page {pi + 1}: duct walls ...")
            by_role = defaultdict(list)
            for obj, kind, seg in iter_segments(page):
                role = layer_map.get(layer_key(obj, kind), "ignore")
                # A symbol role (diffuser/flex_connector/volume_damper) is
                # counted below, from page.rects directly -- never paired
                # as a duct wall here, which is what raw rect EDGE segments
                # would otherwise look like to pair_runs().
                if role != "ignore" and role not in SYMBOL_ROLES:
                    by_role[role].append(seg)
            log("  symbols (diffusers, flex connectors, dampers) ...")
            for role in SYMBOL_ROLES:
                # item 29d: the real manual volume damper is drawn as a
                # filled polyline (count_symbol_curves), not a rect -- a
                # role can have symbols of either kind, so both are
                # checked. Each function dedupes its OWN candidates, but
                # not against the other's, so a final pass here catches a
                # rect and a curve symbol that happened to land on the
                # same spot (none do on the real file -- a safety net for
                # the next one, not a fix for something seen).
                rect_found = [(cx, cy, w, h, "rect")
                             for cx, cy, w, h in count_symbol_rects(page, layer_map, role)]
                curve_found = []
                for cx, cy, w, h in count_symbol_curves(page, layer_map, role):
                    if not any(math.hypot(cx - o[0], cy - o[1]) < 2.0 for o in rect_found):
                        curve_found.append((cx, cy, w, h, "curve"))
                for cx, cy, w_pt, h_pt, shape in rect_found + curve_found:
                    entry = {"page": pi, "x_pt": cx, "y_pt": cy, "source": "geometry", "conf": 1.0}
                    # item 27 rule 3: some trades bill a damper by area
                    # (sq.m/sq.ft of its own frame), not by count -- the
                    # client's own remark on the real file ("VCD quantity
                    # take in SQMTR"). Both units are carried on every
                    # RECT-sourced symbol entry so the write-up can use
                    # whichever the client's own convention wants, not
                    # just "No.".
                    #
                    # item 29d: a CURVE-sourced symbol's bounding box is
                    # the drawn mark's own extent along the duct (the real
                    # manual damper, ~4-5ft of hatching), not the item's
                    # physical cross-section the way a rect icon's bbox
                    # is -- computing an "area" from it would be a real
                    # number that means nothing. Left blank, honestly,
                    # rather than shown and silently wrong.
                    if shape == "rect":
                        width_in = round(w_pt / pt_per_ft * 12, 1)
                        height_in = round(h_pt / pt_per_ft * 12, 1)
                        area_sqft = round((width_in / 12) * (height_in / 12), 3)
                    else:
                        width_in = height_in = area_sqft = None
                    if role == "diffuser":
                        entry.update({"type": "Supply Diffuser", "purpose": "supply", "face": "",
                                     "neck": "", "cfm": 0, "qty": 1, "room": "",
                                     "width_in": width_in, "height_in": height_in, "area_sqft": area_sqft})
                        result["terminals"].append(entry)
                    else:
                        entry.update({"type": "Flex Duct Connector" if role == "flex_connector"
                                     else "Volume Control Damper",
                                     "size": f"{width_in}x{height_in}" if width_in is not None else "",
                                     "width_in": width_in, "height_in": height_in,
                                     "area_sqft": area_sqft, "qty": 1})
                        result["accessories"].append(entry)
            runs = []
            for role, lines in by_role.items():
                for r in pair_runs(lines, pt_per_ft):
                    r["system"] = role; r["page"] = pi
                    # "kind" (duct/pipe) from the role's own vocabulary --
                    # NOTE geometry still measures every role the same way
                    # (two parallel walls); a single-line pipe is the known
                    # gap flagged on ROLES above, not fixed by this field.
                    r["kind"] = "pipe" if role in _PIPE_ROLES else "duct"
                    r["source"] = "geometry"; r["conf"] = 1.0   # exact vector geometry, not a guess
                    runs.append(r)
            log(f"  {len(runs)} runs")
            log("  text layer ...")
            labels, rooms, notes = text_layer(page, pi)
            if use_ocr: labels += ocr_page(pdf_path, pi, dpi, log)
            _classify_duct_label_colors(pdf_path, pi, labels)
            for l in labels:
                l["page"] = pi
            for o in rooms + notes:
                o["source"] = "text"; o["conf"] = 1.0
            # split runs at size labels (depth changes along a constant-width run) and attach sizes
            sizes = [l for l in labels if l["kind"] == "size"]
            runs = [dict(p, system=r["system"], kind=r["kind"], source=r["source"], conf=r["conf"], page=pi)
                    for r in runs for p in split_by_labels(r, sizes, pt_per_ft, match_ft)]
            result["duct_runs"] += runs
            result["labels"] += labels
            result["rooms"] += rooms
            result["notes"] += notes
    # Real text and OCR can both read the same physical label -- real text
    # always wins (see dedupe_labels()). Runs once, after every page's
    # labels are in, same reasoning as the equipment join below.
    result["labels"] = dedupe_labels(result["labels"], pt_per_ft)
    # Hi-Wall units: once every page's labels are in, not per-page -- a
    # capacity note and its "NOS." count can plausibly sit close together
    # across a page boundary is not assumed here (join is page-scoped
    # inside the function), but running it once, after the full labels
    # list exists, is simpler than threading partial state through the
    # per-page loop for a join that doesn't need per-page separation.
    result["equipment"] += _equipment_from_labels(result["labels"], pt_per_ft)
    # A noisier OCR read of the SAME Hi-Wall note ("L2TR _HI-WALL", stray
    # characters breaking HIWALL_RE) can still fall through to a plain
    # TR_RE match -- found live: a second, garbled pass of the real
    # "2TR HI-WALL" label produced a spurious generic tr:2.0 entry a few
    # inches from the equipment entry already captured correctly. Drop a
    # "tr" label when it sits this close to an equipment entry of the same
    # capacity -- it is that same note read twice, not a second tag.
    for e in result["equipment"]:
        cap = float(e["capacity"].rstrip("TR"))
        result["labels"] = [
            l for l in result["labels"]
            if not (l["kind"] == "tr" and l["page"] == e["page"]
                   and abs(l["tr"] - cap) < 0.05
                   and math.hypot(l["x_pt"] - e["x_pt"], l["y_pt"] - e["y_pt"]) < 3.0 * pt_per_ft)]
    # convert coordinates to feet from sheet top-left, round
    f = lambda v: round(v / pt_per_ft, 2)
    for r in result["duct_runs"]:
        x1, y1, x2, y2 = r.pop("pt")
        r.update({"x1_ft": f(x1), "y1_ft": f(y1), "x2_ft": f(x2), "y2_ft": f(y2)})
    for coll in ("labels", "rooms", "notes", "equipment", "terminals", "accessories"):
        for o in result[coll]:
            o["x_ft"], o["y_ft"] = f(o.pop("x_pt")), f(o.pop("y_pt"))
    # summary by system + size
    agg = defaultdict(lambda: {"length_ft": 0.0, "runs": 0})
    for r in result["duct_runs"]:
        size = f'{r["width_in"]}x{r["depth_in"] if r["depth_in"] else "?"}'
        a = agg[(r["system"], size)]; a["length_ft"] += r["length_ft"]; a["runs"] += 1
    result["duct_summary"] = [{"system": s, "size_in": z, "length_ft": round(v["length_ft"], 1),
                               "length_m": round(v["length_ft"] * 0.3048, 2), "runs": v["runs"]}
                              for (s, z), v in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1]["length_ft"]))]
    # A second, differently-coloured duct subsystem shows up per room (see
    # _classify_duct_label_colors) -- real on the drawing, but what it
    # represents is a judgement call, not something geometry can answer.
    # Pulled out here rather than silently merged into cfm_label_counts;
    # left for the write-up agent to ask about.
    result["unresolved_duct_labels"] = [
        {"page": l["page"], "x_ft": l["x_ft"], "y_ft": l["y_ft"], "kind": l["kind"], "text": l["text"]}
        for l in result["labels"] if l.get("is_secondary_duct_color")]
    # counts that help Claude
    cfm = defaultdict(int)
    for l in result["labels"]:
        if l["kind"] == "cfm" and not l.get("is_secondary_duct_color"): cfm[l["cfm"]] += 1
    result["cfm_label_counts"] = dict(sorted(cfm.items()))
    result["tr_labels"] = [l["tr"] for l in result["labels"] if l["kind"] == "tr"]
    # The parameter schema's ★ quality list: anything read with real doubt,
    # named and located, not silently kept or silently dropped. 0.6 is a
    # plain middle threshold, not tuned against a labelled test set yet.
    result["unread"] = [{"page": l["page"], "x_ft": l["x_ft"], "y_ft": l["y_ft"],
                         "reason": f'OCR confidence {l["conf"]:.2f} on "{l["text"]}"'}
                        for l in result["labels"] if l["source"].startswith("ocr") and l["conf"] < 0.6]
    # self-checks
    n = len(result["duct_runs"]); m = sum(1 for r in result["duct_runs"] if r["label"])
    rate = m / n if n else 0
    result["checks"] = {"runs": n, "runs_with_size_label": m, "label_match_rate": round(rate, 2)}
    if n == 0: result["warnings"].append("No duct runs found: check the layer mapping (which colour is supply/return).")
    elif rate < 0.3: result["warnings"].append("Few runs matched a size label: scale may be wrong, or labels need OCR.")
    # item 27 rule 4: under half of a real file's runs had NO label at all
    # (43%, nowhere near the 30% floor above) and that never surfaced as a
    # warning -- an estimator reading only the headline totals had no way
    # to know most of the length behind them was unconfirmed. A second,
    # softer tier so "more than half unlabeled" is said out loud even when
    # it isn't bad enough to hit the sharper warning above.
    elif rate < 0.5:
        result["warnings"].append(
            f"Only {round(rate * 100)}% of duct runs matched a size label -- more than half have "
            "no confirmed size. Any area/length total built only from the matched runs is missing "
            "real duct; do not treat it as a firm total without checking the overlay.")
    if not any(l["source"].startswith("ocr") for l in result["labels"]) and use_ocr:
        result["warnings"].append("No OCR labels: check rapidocr/onnxruntime are installed, or labels may be missing.")
    result["warnings"].append("Only straight horizontal/vertical ducts are measured; bends, angled runs and fittings are not.")
    # item 27 rule 4, continued: the old check was all-or-nothing (any ONE
    # symbol role mapped silenced the warning for all three) -- found live,
    # 28 Oct 2026: a file with diffuser and flex_connector mapped but NOT
    # volume_damper reported 0 dampers with no warning at all, which reads
    # exactly like "confirmed zero on the drawing" rather than "nobody told
    # this tool which layer is the damper". Checked per role instead.
    mapped_symbol_roles = {role for role in SYMBOL_ROLES if role in layer_map.values()}
    unmapped_symbol_roles = SYMBOL_ROLES - mapped_symbol_roles
    if not mapped_symbol_roles:
        result["warnings"].append(
            "No diffuser/flex_connector/volume_damper layer mapped -- symbols are not counted at "
            "all unless a rect layer is mapped to one of those roles; use cfm_label_counts and "
            "check against the drawing instead.")
    else:
        if unmapped_symbol_roles:
            result["warnings"].append(
                f'No layer mapped to: {", ".join(sorted(unmapped_symbol_roles))} -- these report as '
                '0 in terminals/accessories, which means "not counted on this file", not "confirmed '
                'zero on the drawing". Map a layer to each role that needs counting.')
        result["warnings"].append(
            "Symbol counts (diffusers/flex connectors/dampers) are geometric finds (exact), not an "
            "interpretation -- a rect that happens to share the mapped layer's colour/weight and "
            "size range would be miscounted as one; check the overlay, not just the number.")
    # item 27 rule 4, continued: a size/gauge group built from exactly one
    # measured run is a single point of failure -- one bad scale or OCR
    # read on that one run swings the WHOLE group's total, the same way the
    # real file's "return, 22G" category (a single 20x30 run) came out
    # more than 2x the client's real figure. 30% is a plain middle
    # threshold (same honest framing as `unread`'s 0.6, above) -- not
    # tuned against a labelled test set yet.
    sys_totals = defaultdict(float)
    for d in result["duct_summary"]:
        sys_totals[d["system"]] += d["length_ft"]
    for d in result["duct_summary"]:
        total = sys_totals[d["system"]]
        if d["runs"] == 1 and total > 0 and d["length_ft"] / total > 0.3:
            result["warnings"].append(
                f'{d["system"]} {d["size_in"]}: {d["length_ft"]} ft comes from a single measured run '
                f'({round(d["length_ft"] / total * 100)}% of all {d["system"]} length) -- one bad '
                "scale or OCR read on this one run swings the whole size total built from it.")
    # item 29c: report-only -- never changes a run, a length or a total,
    # see _isolated_runs' own docstring for why this stops short of
    # bridging/merging anything.
    isolated = _isolated_runs(result["duct_runs"])
    if isolated:
        iso_ft = sum(r["length_ft"] for r in isolated)
        result["warnings"].append(
            f'{len(isolated)} duct run(s) ({iso_ft:.1f} ft total) do not connect to any other '
            "measured run at either end -- not a normal dead end (that only needs ONE free end); "
            "possibly a misread, a duplicate, or junk geometry. Not altered, just flagged -- check "
            "these against the overlay before trusting their length.")
    # "equipment" now holds real finds (Hi-Wall split units, from a "<N>TR
    # HI-WALL" note) -- the "empty by design" warning stayed true for it
    # even after real entries started landing, which is its own kind of
    # silently wrong. Split the three claims: equipment and
    # terminals/accessories are real, partial reads (each with its own
    # honest gap, stated on its own line); duct_fittings/legend/schedules/
    # links are still genuinely untouched.
    result["warnings"].append(
        "equipment: only Hi-Wall split units noted as \"<N>TR HI-WALL\" are read -- every other "
        "equipment type (AHU, chiller, FCU, exhaust fan...) is NOT extracted yet. room/tag are "
        "left blank on every entry (not matched to a room); qty defaults to 1 when no \"NOS.\" "
        "count was found nearby, which is not the same as a confirmed count of 1.")
    result["warnings"].append(
        "terminals/accessories (diffusers, flex connectors, dampers): counted by shape, one entry "
        "per symbol found -- cfm/size/room/tag are NOT read from this, left blank on every entry; "
        "cross-check cfm_label_counts and the drawing for those.")
    result["warnings"].append(
        "duct_fittings/legend/schedules/links are empty by design, not a finding -- this tool does "
        "not extract those categories yet; do not read an empty list as \"none on this drawing\".")
    if any(r["kind"] == "pipe" for r in result["duct_runs"]):
        result["warnings"].append(
            "Pipe runs use the same double-wall measurement as ducts -- a pipe drawn as a single "
            "centreline (the common convention) is not measured and will not appear at all.")
    if result["unresolved_duct_labels"]:
        result["warnings"].append(
            f'{len(result["unresolved_duct_labels"])} duct size/CFM label(s) are drawn in a different '
            "ink colour from the primary duct network (orange/tan vs black) -- a second duct subsystem "
            "on this drawing. Its role (secondary branch? return tie-in? an older system?) cannot be "
            "determined from geometry -- listed in unresolved_duct_labels, excluded from "
            "cfm_label_counts; ask the client before using these figures.")
    return result

def overlay_png(pdf_path, result, page_index=0, dpi=100):
    """Verification image: drawing faded, measured runs on top (green = size label found, red = no label)."""
    import pypdfium2 as pdfium
    from PIL import Image, ImageDraw
    img = pdfium.PdfDocument(pdf_path)[page_index].render(scale=dpi / 72).to_pil().convert("RGB")
    img = Image.blend(img, Image.new("RGB", img.size, "white"), 0.65)
    dr = ImageDraw.Draw(img); k = result["settings"]["pt_per_ft"] * dpi / 72
    for r in result["duct_runs"]:
        if r["page"] != page_index: continue
        col = (0, 160, 0) if r["label"] else (220, 0, 0)
        if r["system"] == "return": col = (0, 90, 255) if r["label"] else (255, 120, 0)
        x1, y1, x2, y2 = (r[c] * k for c in ("x1_ft", "y1_ft", "x2_ft", "y2_ft"))
        wpx = max(2, r["width_in"] / 12 * k)
        if r["orientation"] == "H": dr.rectangle([x1, y1 - wpx / 2, x2, y1 + wpx / 2], outline=col, width=2)
        else: dr.rectangle([x1 - wpx / 2, y1, x1 + wpx / 2, y2], outline=col, width=2)
        dr.text((min(x1, x2) + 2, min(y1, y2) + 1), f'{r["width_in"]}x{r["depth_in"] or "?"}', fill=col)
    out = os.path.splitext(pdf_path)[0] + f"_takeoff_overlay_p{page_index + 1}.png"
    img.save(out); return out

def save(result, pdf_path):
    base = os.path.splitext(pdf_path)[0] + "_takeoff"
    with open(base + ".json", "w", encoding="utf-8") as fh: json.dump(result, fh, indent=1, ensure_ascii=False)
    with open(base + "_summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); w.writerow(["system", "size_in", "length_ft", "length_m", "runs"])
        for s in result["duct_summary"]: w.writerow([s["system"], s["size_in"], s["length_ft"], s["length_m"], s["runs"]])
    with open(base + "_runs.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh); cols = ["page", "system", "orientation", "width_in", "depth_in", "label", "length_ft", "x1_ft", "y1_ft", "x2_ft", "y2_ft"]
        w.writerow(cols)
        for r in result["duct_runs"]: w.writerow([r.get(c) for c in cols])
    return base + ".json"

def symbol_counts_and_areas(res):
    """One (type, count, total_area_sqft_or_None) tuple per symbol type
    found by shape (diffuser/flex_connector/volume_damper) -- the single
    place both summary_text() and the review UI read this from, so the
    two never drift into reporting different numbers for the same run."""
    counts = defaultdict(int)
    areas = defaultdict(float)
    has_area = defaultdict(bool)
    for e in (res.get("terminals") or []) + (res.get("accessories") or []):
        counts[e["type"]] += 1
        if e.get("area_sqft") is not None:
            areas[e["type"]] += e["area_sqft"]
            has_area[e["type"]] = True
    return [(t, n, areas[t] if has_area[t] else None) for t, n in sorted(counts.items())]


def summary_text(res):
    s = [f'File: {res["source"]["file"]}   pages: {res["source"]["pages"]}   runs: {res["checks"]["runs"]}   '
         f'label match: {int(res["checks"]["label_match_rate"] * 100)}%', "", "DUCT SUMMARY (system, size in, length ft / m, runs)"]
    for d in res["duct_summary"]:
        s.append(f'  {d["system"]:<8} {d["size_in"]:<8} {d["length_ft"]:>8.1f} ft  {d["length_m"]:>7.2f} m  ({d["runs"]})')
    tot = defaultdict(float)
    for d in res["duct_summary"]: tot[d["system"]] += d["length_ft"]
    s.append("  TOTAL: " + ", ".join(f"{k} {v:.1f} ft" for k, v in tot.items()))
    s += ["", f'TR tags: {res["tr_labels"]}', f'CFM labels (value: count): {res["cfm_label_counts"]}',
          f'Rooms: {len(res["rooms"])}  ' + "; ".join(f'{r["name"]} {r["sqft"]}' for r in res["rooms"][:40])]
    if res["equipment"]:
        s += ["", "EQUIPMENT (from drawing notes, partial -- see warnings)"]
        s += [f'  {e["type"]} {e["capacity"]} x{e["qty"]} (conf {e["conf"]:.2f})' for e in res["equipment"]]
    if res["terminals"] or res["accessories"]:
        s += ["", "SYMBOLS COUNTED BY SHAPE (partial -- see warnings)"]
        # item 27 rule 3: the per-symbol area (width_in/height_in/area_sqft,
        # from count_symbol_rects' own outer footprint) was computed but
        # never reached this hand-off -- a BOQ built only from this text
        # never saw it, even though every entry has carried it since 28c.
        # Shown as a total per type so a trade that bills (e.g.) a damper
        # by sq.m, not by count, has the number here, not just in the raw
        # JSON.
        for t, n, area in symbol_counts_and_areas(res):
            area_bit = f'  ({area:.2f} sq.ft / {area * 0.0929:.2f} sq.m total frame area)' if area is not None else ""
            s.append(f'  {t}: {n}{area_bit}')
    if res["unresolved_duct_labels"]:
        s += ["", "UNRESOLVED -- SECOND DUCT SYSTEM (different ink colour, role not geometry-derivable)"]
        s += [f'  {u["kind"]}: {u["text"]} (page {u["page"] + 1})' for u in res["unresolved_duct_labels"][:40]]
    s += ["", "WARNINGS"]
    s += ["  - " + w for w in res["warnings"]]
    return "\n".join(s)

# ---------------------------------------------------------------- GUI
def load_map():
    try: return json.load(open(MAP_FILE))
    except Exception: return {}

def save_map(updates: dict):
    """Remember this tender's own role choices for the NEXT one -- the
    same cross-tender memory `MAP_FILE` already promises, just callable
    from outside run_gui()'s own tkinter `start()` too."""
    saved = load_map(); saved.update(updates)
    try: json.dump(saved, open(MAP_FILE, "w"), indent=1)
    except Exception: pass

def run_gui(preload=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk(); root.title("HVAC Takeoff Extractor"); root.geometry("900x720")
    st = {"pdf": None, "layers": [], "vars": {}, "result": None}

    top = ttk.Frame(root, padding=8); top.pack(fill="x")
    path_var = tk.StringVar(value="No PDF selected")
    scale_var = tk.StringVar(value='1/8" = 1\'-0"')
    ocr_var = tk.BooleanVar(value=True)
    ttk.Button(top, text="Open PDF", command=lambda: pick()).grid(row=0, column=0, sticky="w")
    ttk.Label(top, textvariable=path_var, width=70).grid(row=0, column=1, columnspan=4, sticky="w", padx=6)
    ttk.Label(top, text="Drawing scale:").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Combobox(top, textvariable=scale_var, values=list(SCALES) + ["custom pt/ft: 9"], width=22).grid(row=1, column=1, sticky="w")
    ttk.Checkbutton(top, text="OCR labels (RapidOCR)", variable=ocr_var).grid(row=1, column=2, sticky="w", padx=8)

    ttk.Label(root, text="Step 1 - set what each line colour is (Preview to check). Longest layers first.", padding=(8, 0)).pack(anchor="w")
    box = ttk.Frame(root, padding=8); box.pack(fill="both", expand=False)
    canvas = tk.Canvas(box, height=230, highlightthickness=0); sb = ttk.Scrollbar(box, command=canvas.yview)
    inner = ttk.Frame(canvas); inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.create_window((0, 0), window=inner, anchor="nw"); canvas.configure(yscrollcommand=sb.set)
    canvas.pack(side="left", fill="both", expand=True); sb.pack(side="right", fill="y")

    bar = ttk.Frame(root, padding=8); bar.pack(fill="x")
    go = ttk.Button(bar, text="Step 2 - Extract", command=lambda: start()); go.pack(side="left")
    ttk.Button(bar, text="Copy JSON", command=lambda: copy()).pack(side="left", padx=6)
    ttk.Button(bar, text="Open overlay", command=lambda: open_file(st.get("overlay"))).pack(side="left")
    status = tk.StringVar(value="Open a PDF to begin."); ttk.Label(bar, textvariable=status).pack(side="left", padx=10)
    out = tk.Text(root, wrap="none", font=("Courier", 10)); out.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def pt_per_ft():
        v = scale_var.get()
        if v in SCALES: return SCALES[v]
        m = re.search(r"([\d.]+)\s*$", v)
        if m: return float(m.group(1))
        raise ValueError("Scale not understood")

    def pick():
        p = filedialog.askopenfilename(filetypes=[("PDF", "*.pdf")])
        if p: load(p)

    def load(p):
        st["pdf"] = p; path_var.set(p); status.set("Scanning line layers ...")
        root.update_idletasks()
        st["layers"] = scan_layers(p)
        for w in inner.winfo_children(): w.destroy()
        saved = load_map(); st["vars"] = {}
        try: ppf = pt_per_ft()
        except ValueError: ppf = 9.0
        layers = sorted(st["layers"], key=lambda L: (saved.get(L["key"], "ignore") == "ignore", -L["length_pt"]))
        for i, L in enumerate(layers[:40]):
            tk.Label(inner, bg=L["color"], width=3).grid(row=i, column=0, padx=4, pady=1)
            ttk.Label(inner, text=f'{L["color"]}  wt {L["linewidth"]:<5} {L["kind"]:<4} {L["segments"]:>6} segs  {L["length_pt"] / ppf:>8.0f} ft of line',
                      font=("Courier", 9)).grid(row=i, column=1, sticky="w")
            v = tk.StringVar(value=saved.get(L["key"], "ignore")); st["vars"][L["key"]] = v
            ttk.Combobox(inner, textvariable=v, values=ROLES, width=10, state="readonly").grid(row=i, column=2, padx=6)
            ttk.Button(inner, text="Preview", command=lambda k=L["key"], c=L["color"], pg=L["pages"][0]: preview(k, c, pg)).grid(row=i, column=3)
        status.set(f'{len(st["layers"])} layers found. Set roles, then Extract.')

    def preview(key, color, pg):
        lines, (W, H) = layer_lines(st["pdf"], key, pg)
        win = tk.Toplevel(root); win.title(f"Layer {key} - page {pg + 1}")
        s = min(560 / W, 760 / H); c = tk.Canvas(win, width=W * s, height=H * s, bg="white"); c.pack()
        c.create_rectangle(1, 1, W * s - 1, H * s - 1, outline="#ccc")
        col = color if color not in ("#ffffff",) else "#888"
        for x0, y0, x1, y1 in lines: c.create_line(x0 * s, y0 * s, x1 * s, y1 * s, fill=col)

    def start():
        if not st["pdf"]: return messagebox.showinfo("HVAC Takeoff", "Open a PDF first.")
        mp = {k: v.get() for k, v in st["vars"].items() if v.get() != "ignore"}
        if not mp: return messagebox.showinfo("HVAC Takeoff", "Set at least one layer to supply or return.")
        try: ppf = pt_per_ft()
        except ValueError as e: return messagebox.showerror("HVAC Takeoff", str(e))
        save_map({k: v.get() for k, v in st["vars"].items()})
        go.state(["disabled"]); out.delete("1.0", "end")
        log = lambda m: root.after(0, lambda: status.set(m))
        def work():
            try:
                res = extract(st["pdf"], mp, ppf, ocr_var.get(), log=log)
                path = save(res, st["pdf"]); st["result"] = res
                log("Drawing verification overlay ...")
                st["overlay"] = overlay_png(st["pdf"], res)
                root.after(0, lambda: (out.insert("end", summary_text(res)), status.set(f"Saved: {path}")))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror("HVAC Takeoff", f"{e.__class__.__name__}: {e}"))
            finally:
                root.after(0, lambda: go.state(["!disabled"]))
        threading.Thread(target=work, daemon=True).start()

    def copy():
        if not st["result"]: return
        root.clipboard_clear(); root.clipboard_append(json.dumps(st["result"], ensure_ascii=False)); status.set("JSON copied - paste it to Claude.")

    def open_file(p):
        if not p: return status.set("Run Extract first.")
        import subprocess
        if sys.platform.startswith("win"): os.startfile(p)
        else: subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", p])

    if preload: root.after(100, lambda: load(preload))
    root.mainloop()

# ---------------------------------------------------------------- CLI
if __name__ == "__main__":
    args = sys.argv[1:]
    pdf_path = next((a for a in args if a.lower().endswith(".pdf")), None)
    if pdf_path and "--map" in args:            # headless extraction
        mp = {}
        for a in args[args.index("--map") + 1:]:
            if a.startswith("--"): break
            k, v = a.rsplit("=", 1); mp[k] = v
        ppf = float(args[args.index("--ptperft") + 1]) if "--ptperft" in args else SCALES['1/8" = 1\'-0"']
        res = extract(pdf_path, mp, ppf, use_ocr="--no-ocr" not in args)
        print("Saved", save(res, pdf_path), overlay_png(pdf_path, res)); print(summary_text(res))
    elif pdf_path and "--list" in args:         # show layers
        for L in scan_layers(pdf_path)[:30]:
            print(f'{L["key"]:<22} {L["segments"]:>6} segs  {L["length_pt"]:>9.0f} pt')
    else:
        run_gui(pdf_path)
