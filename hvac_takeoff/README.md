# HVAC Takeoff Extractor

Pick a tender PDF and it measures the duct runs, then writes a JSON file. Send that JSON to Claude to get the BOQ.

## Install (once)
1. Python 3.10+ (on Windows, tick "tcl/tk" in the installer; it's on by default)
2. `pip install -r requirements.txt`

That's it — OCR (for size/CFM labels) is RapidOCR, running on ONNX Runtime with its detection/recognition/angle models bundled straight into the `rapidocr` wheel. No separate OCR program to install, no PATH setup, nothing that leaves this machine: ~80 MB total (onnxruntime + opencv-headless + rapidocr's own models), well under the old Tesseract-install story on Windows.

## Use
1. `python hvac_takeoff.py`, then **Open PDF**
2. Set the **drawing scale** (from the title block)
3. **Step 1:** for each layer (colour, weight, kind), pick its role: `supply`, `return`, etc.
   Use **Preview** to see what a layer contains.
   - Ducts are often split across a `line` layer and a `poly` layer of the same colour. Map both.
   - Leave grille rectangles (`rect`) as `ignore`, or they get counted as duct.
   - The mapping is remembered in `layer_map.json` for the next drawing from the same consultant.
4. **Step 2 - Extract.** It saves these next to the PDF:
   - `*_takeoff.json`: send this to Claude
   - `*_takeoff_summary.csv`: length by system and size
   - `*_takeoff_runs.csv`: every run with coordinates
   - `*_takeoff_overlay_p1.png`: check this
5. **Open overlay**
   - Green/blue = run with a matched size label
   - Red/orange = drawn width only (`?` depth)
   - Anything missing or extra here is what to fix in Step 1

## What it measures vs what Claude decides
| Tool (geometry, exact) | Claude (rules / judgement) |
|---|---|
| Duct runs: drawn width, length, position | Depth where no label matched; label leaders, "4 NOS" |
| Size / CFM / TR labels (text layer + OCR, 0 and 90 deg) | Gauge (IS 655/SMACNA), fittings allowance, insulation, lining |
| Room names + sq.ft | Diffuser/grille counts from CFM chain, air-balance check |
| | Equipment, piping (provisional), exclusions, BOQ format |

## Limits
- Only straight horizontal/vertical ducts. Bends, angled runs and fittings are left to the allowance.
- A pipe drawn as a single centreline (common convention) is not measured at all — the geometry pass
  only pairs two parallel walls, which a duct has and a single-line pipe does not.
- Vector PDFs only. Scanned drawings have no geometry to measure.
- OCR on SHX (stroked) text is about 60-90%. Text-layer labels are exact.
- If you can get the DWG/DXF, use it instead: layers and text are exact there.
- Every output row carries `source` (geometry/text/ocr0/ocr90) and `conf` (1.0 for geometry/text,
  the model's own score for OCR) — low-confidence OCR reads also land in a separate `unread` list
  (< 0.6), named and located, rather than silently kept or silently dropped.
- `equipment` / `duct_fittings` / `accessories` / `terminals` / `legend` / `schedules` / `links` are
  present in the JSON but always empty — not built yet. An empty list there means "not extracted",
  never "none on this drawing".

## Headless
```
python hvac_takeoff.py drawing.pdf --list
python hvac_takeoff.py drawing.pdf --map "#000000@1.56:line=supply" "#000000@1.56:poly=supply" "#ff0000@1.08:line=return" [--ptperft 9] [--no-ocr]
```
pt/ft = paper points per real foot. 1/8"=1'-0" -> 9, 1/4" -> 18, 1:100 -> 8.64.
