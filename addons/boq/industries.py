"""Per-industry rule-sets for BOQ's PDF-takeoff path (item 26).

BOQ is sold across industries -- HVAC today, ELV/CCTV/fibre-link and
others later -- and each one reads its own drawings by its own rules, so
WHICH rule-set runs must be an explicit choice (the Industry dropdown in
addons/boq/dialog.py), never guessed from an uploaded PDF's own content.
A pharma-tech drawing has nothing in it saying "I am not HVAC" -- without
an explicit choice the system could silently run HVAC's OCR and rules on
it anyway just because nothing told it otherwise. See
BOQ-CHANGES-TODO.md item 26 for the decision this module implements.

Only "HVAC" has a real rule-set today: hvac_takeoff/ (OCR + geometry
extraction) and HVAC_DRAWING_RULES.md (write-up guidance, wired through
addons/boq/dialog.py's own self._hvac). Adding another industry's own
PDF-takeoff later is "add one entry to this module", not "edit
addons/boq/dialog.py's core logic" -- the same shape addons/registry.py
already gives add-ons themselves.
"""
from __future__ import annotations

from collections import defaultdict

GENERAL = "General"
HVAC = "HVAC"

# Shown in the dropdown, in this order -- General (no special rule-set)
# first, since that is the common case for an industry with no PDF-takeoff
# of its own yet.
NAMES = [GENERAL, HVAC]

# A label read confidently enough to trust without a second look --
# hvac_takeoff's own cutoff (its "unread" warning list already flags
# anything below this), reused here rather than inventing a second
# threshold for the same judgement.
CONFIDENT = 0.6

# Label kinds whose downstream aggregate (tr_labels / cfm_label_counts) is
# a flat, cheap recompute from result["labels"] alone -- see
# recompute_aggregates(). "size" labels also feed duct_runs through a
# heavier, geometry-coupled pairing pass (split_by_labels, run inside
# extract() against the actual duct walls) that a text edit here cannot
# safely redo, so a "size" row is shown for visibility only, not editable.
EDITABLE_KINDS = {"tr", "cfm"}


def has_takeoff(industry: str) -> bool:
    """Whether `industry` has its own PDF-takeoff tool to offer."""
    return industry == HVAC


def _hvac():
    """Imported lazily: hvac_takeoff/ carries its own heavy OCR/PDF
    dependencies (pdfplumber, pypdfium2, rapidocr) that nobody who never
    touches the HVAC industry should be made to import just by opening
    the BOQ add-on."""
    import hvac_takeoff.hvac_takeoff as m
    return m


def roles(industry: str) -> list[str]:
    """The role choices a layer in `industry`'s "Step 1" (what each line
    colour is) can be assigned -- whatever that industry's own OCR/
    extraction actually knows how to measure."""
    if industry == HVAC:
        return list(_hvac().ROLES)
    return []


def scales(industry: str) -> dict:
    """Drawing-scale label -> points-per-foot, for `industry`'s own common
    scale conventions."""
    if industry == HVAC:
        return dict(_hvac().SCALES)
    return {}


def scan_layers(industry: str, pdf_path: str) -> list[dict]:
    """Step 1: every line/edge in the PDF grouped by colour+weight, longest
    first -- for the person to say what each one actually is, before
    anything is extracted."""
    if industry == HVAC:
        return _hvac().scan_layers(pdf_path)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def extract(industry: str, pdf_path: str, layer_map: dict, pt_per_ft: float,
           use_ocr: bool = True, log=None) -> dict:
    """Step 2: run `industry`'s own extraction with the layer roles chosen
    at Step 1. Returns the tool's own result dict, untouched -- so a future
    industry's own shape only has to be understood by whatever review step
    reads it, never reshaped here to match HVAC's."""
    if industry == HVAC:
        return _hvac().extract(pdf_path, layer_map, pt_per_ft, use_ocr=use_ocr,
                               log=log or (lambda *a: None))
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def summary_text(industry: str, result: dict) -> str:
    """The plain-text handoff to the BOQ prompt -- treated exactly like any
    other external measurement from here on (see
    BoqDialog._use_external_measurements)."""
    if industry == HVAC:
        return _hvac().summary_text(result)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def review_rows(industry: str, result: dict) -> list[dict]:
    """One row per OCR/text label read off the drawing (size, CFM, TR,
    room note) -- the only readings with real, varying confidence. A duct
    run's own length is exact vector geometry (conf 1.0 always, nothing to
    second-guess); a label is whatever the OCR engine made of a character
    string, which is exactly where a real misread happens. Each row's
    `conf` is that engine's own score, never an invented per-row guess --
    the same number hvac_takeoff's own "unread" warning already uses."""
    if industry != HVAC:
        return []
    return [{"index": i, "kind": l.get("kind", ""), "text": l.get("text", ""),
             "conf": float(l.get("conf", 1.0)), "page": l.get("page", 0),
             "editable": l.get("kind", "") in EDITABLE_KINDS}
            for i, l in enumerate(result.get("labels") or [])]


def apply_review_edit(industry: str, result: dict, index: int, new_text: str) -> bool:
    """A person's correction to labels[index]'s text, written back into
    `result` itself and folded into the aggregates summary_text() actually
    reads -- a cosmetic-only table edit that never reached the final
    numbers would be worse than no edit box at all. Only for a "tr"/"cfm"
    row (see EDITABLE_KINDS); returns False, changing nothing, otherwise."""
    if industry != HVAC:
        return False
    label = result["labels"][index]
    if label.get("kind") not in EDITABLE_KINDS:
        return False
    hvac = _hvac()
    parsed = hvac.parse_label(new_text, label.get("x_pt", 0), label.get("y_pt", 0),
                              source="manual", conf=1.0)
    match = next((p for p in parsed if p["kind"] == label["kind"]), None)
    if match is None:
        return False
    label.update(match)
    label["page"] = result["labels"][index].get("page", label.get("page", 0))
    _recompute_aggregates(result)
    return True


def _recompute_aggregates(result: dict) -> None:
    """Mirrors extract()'s own tr_labels/cfm_label_counts one-liners
    exactly, so an edited label's correction shows up in the same places
    an original reading would -- never a second, drifting definition of
    the same counts."""
    result["tr_labels"] = [l["tr"] for l in result["labels"] if l["kind"] == "tr"]
    cfm = defaultdict(int)
    for l in result["labels"]:
        if l["kind"] == "cfm" and not l.get("is_secondary_duct_color"):
            cfm[l["cfm"]] += 1
    result["cfm_label_counts"] = dict(sorted(cfm.items()))
