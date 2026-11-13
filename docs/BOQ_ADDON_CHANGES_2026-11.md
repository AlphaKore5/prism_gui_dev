# BOQ add-on: what was added and changed (11–13 Nov 2026)

Everything here is in `addons/boq/`, `hvac_takeoff/` and one engine file
(`prism_terminal/core/openrouter.py`). The numbers in brackets are the item numbers
used in the code comments, so a change can be found by searching for "item 74".

## State of proof

| Area | State |
|---|---|
| Measurement changes (layers, counts, return duct, VAV boxes) | Checked on a real HVAC drawing against the client's own take-off |
| Write-up prompt rules (per-size duct area, insulation, VAV quantity) | One real run produced the per-size supply table; the run was cut off before the later sections |
| Reasoning switched off for the write-up, cut-off answers refused | Unit-tested only. Not yet run against the live service |
| VAV tag read at temperature 0, with retry | One real run (30 tags). The tag read is still weak; the shape count is what the BOQ uses |
| Windows | Not run by hand. The Windows test job on GitHub is the only Windows check |

## Added

### Fill the client's own Word template (66)
- A drafted BOQ can be poured into the client's own `.docx` template.
- Tables are matched by their column headings. A section with no matching table is
  appended at the end, and the dialog says which ones.

### BOQ counter on the BOQ home panel (70, 73)
- One small line: BOQs made today, this month and this year, with tokens used.
- A Reset button starts the count again from now. No run file is deleted.
- Token use is taken from each Prism Agent call and saved with the run.

### Real CAD layer names in the PDF takeoff (74)
- When a PDF is exported "with layers", Prism now reads the drawing's own layer
  names and shows them in Layer mapping, in place of colour codes.
- Old colour-based layer maps keep working unchanged.

### Layer roles suggested for you (76, 77, 78, 80)
- A layer named like "Supply Air Duct" starts on `supply`. Label, text, cable,
  power and detector layers are never suggested.
- A named layer whose name says nothing can start on a role you already gave one
  of its colours on an earlier drawing.
- A remembered "ignore" never beats a real suggestion.
- Every suggestion is shown in the list and can be changed. Nothing is applied
  out of sight.

### VAV boxes counted from the drawing itself (80)
- New role `vav_box`. Prism counts the drawn VAV blocks on the layer mapped to it.
- The count is the same on every run. The tag read (OCR and the AI re-check) stays
  as a cross-check only.

## Changed

### Diffuser and damper counts (75, 79)
- A named layer carries hatching and tick marks that the old colour key never
  picked up. Counted as symbols, they gave 4 diffusers and 873 dampers on a real
  drawing.
- Diffusers now need a near-square shape above a size floor. Dampers have their
  own floor and a size cap that fits a long damper mark.

### Return duct (80)
- On the test drawing, return duct sits on a layer whose name no rule reads. It
  started on "ignore" and return duct fell to almost nothing.
- The colour-memory suggestion above puts it back.

### Write-up rules for HVAC (h, i)
- Sheet-metal and insulation area are given per duct size and per system, with a
  subtotal for each system and one total each. One blended figure for all ducts is
  not accepted.
- Insulation area is always a figure, never a blank provisional line.
- Where a duct's height was not read, one assumed height is stated once as an
  input and reused.
- The VAV quantity comes from the shape count when there is one.

### Write-up rules for every industry (67, 68, 69)
- Compartment dividers and partitions are listed as their own parts.
- Handwritten notes and multi-item catalogue files are read with care, and the
  BOQ says what could not be read.
- When an order is for more than one unit, weight is split into "per unit" and
  "all units" columns.

### "Make my BOQ" on a file that was never measured (71)
- It used to write a BOQ with no link to the file. It now stops and says to
  measure first, or to use "Make with drawing".

### Workbooks that Excel wanted to repair (72)
- A formula naming an input that does not exist was written as a broken formula.
  Excel repaired the file by stripping formulas.
- Such a cell is now written as plain text. Formulas inside the Inputs sheet that
  refer to earlier inputs now work.

### A BOQ that is not whole is refused (81)
- Two real failures were saved as finished BOQs: one stopped mid-table, one held
  the model's own working notes in place of a BOQ.
- Prism now checks that the answer finished and is a real answer. If not, nothing
  is saved and the message says to try again.
- Hidden reasoning is switched off for the write-up call, so the whole output
  limit goes to the document.

### AI VAV tag re-check (80)
- Runs at temperature 0.
- A drawing tile that fails is tried a second time. If it still fails, the
  measurements carry a warning saying how many tiles were lost.

### Layer memory file
- `hvac_takeoff/layer_map.json` now keeps a named layer only when it has a real
  role. Two fire-alarm detector layers that had been saved as smoke-extract duct
  were reset.

## Measured on the test drawing

Client's own take-off against Prism, before these changes and after.

| Item | Client | Before | After |
|---|---|---|---|
| Supply duct length | 589.4 m | 595.9 m | 649.3 m |
| Return duct length | 26.4 m | 5.0 m | 23.1 m |
| Toilet exhaust length | 57.3 m | not measured | 54.6 m |
| VAV boxes | 48 | 42 | 49 |
| Diffusers | 96 | 83 | 86 |
| Volume dampers | 8 | not counted | 14 |
| FA disc valves | 27 | 27 | 27 |

Supply duct length is further from the client's figure than before. The named
supply layers bring in about 50 m more than the old colour mapping; which lines
has not been traced yet.

## Still open

- Duct height is read from size labels on about a quarter of the duct. The rest
  uses one assumed height, so duct areas need a spot check.
- Acoustic and thermal insulation are not told apart.
- Fittings (elbows, offsets, tapers) are not listed as their own items.
- Volume dampers over-count (14 against 8).
- Only the AHU with its airflow printed beside the tag is read.
- A second pass that merges chained wall strips was tried and made return and
  toilet exhaust worse, so it was not kept.

## Tests

New and changed tests are in `hvac_takeoff/test_hvac_takeoff.py`,
`tests/test_boq_dialog.py`, `tests/test_boq_history.py`,
`tests/test_boq_industries.py`, `tests/test_boq_openrouter_writer.py` and
`tests/test_boq_takeoff.py`. Two older tests were changed on purpose and say why
in a comment: a layer named "…-VAV" now suggests `vav_box` where it used to
suggest nothing.
