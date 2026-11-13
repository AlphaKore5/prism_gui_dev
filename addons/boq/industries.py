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
# item 63 (7 Nov 2026): the real-world umbrella term for CCTV, access
# control, PA, structured cabling and the rest -- one entry, not a
# separate CCTV/ELV pair, since those are the same trade's own drawing
# conventions in practice, not two different rule-sets.
ELV = "ELV"

# Shown in the dropdown, in this order -- General (no special rule-set)
# first, since that is the common case for an industry with no PDF-takeoff
# of its own yet.
NAMES = [GENERAL, HVAC, ELV]

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
    return industry in (HVAC, ELV)


def has_ai_tag_recheck(industry: str) -> bool:
    """Whether `industry`'s own OCR pass has an AI tag re-check to fold
    in alongside it (item 2, 5 Nov 2026) -- gated here, the same place
    has_takeoff() already is, so IndustryTakeoffDialog (addons/boq/
    takeoff.py) can offer or withhold it without knowing HVAC-specific
    anything itself; today, only HVAC's VAV tags have one."""
    return industry == HVAC


def has_ai_read_modes(industry: str) -> bool:
    """Whether `industry` is read PURELY by addons/boq/drawing_reader.py's
    shared reader -- no vector-geometry engine behind it at all (item 63,
    generalized into the shared reader at item 64). Separate from
    has_ai_tag_recheck(): HVAC's geometry measurement is still the primary
    source there, with AI only supplementing OCR on top of it; here, for an
    industry with no geometry engine of its own yet, the shared reader's
    own DXF-entities-first/AI-tiled-fallback result IS the whole takeoff.
    Mutually exclusive with has_ai_tag_recheck() today (no industry needs
    both shapes at once), but nothing stops a future one from growing a
    real geometry engine and moving from this gate to that one."""
    return industry == ELV


def _hvac():
    """Imported lazily: hvac_takeoff/ carries its own heavy OCR/PDF
    dependencies (pdfplumber, pypdfium2, rapidocr) that nobody who never
    touches the HVAC industry should be made to import just by opening
    the BOQ add-on."""
    import hvac_takeoff.hvac_takeoff as m
    return m


def _elv():
    """Imported lazily, same reasoning as _hvac() -- drawing_reader carries
    its own optional rapidocr/pypdfium2/ezdxf dependencies. Named `_elv`
    (not `_drawing_reader`) because this is the lazy accessor ELV's own
    dispatch uses; the module itself (addons/boq/drawing_reader.py) is
    shared, not ELV-specific."""
    from addons.boq import drawing_reader as m
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


def suggest_role(industry: str, name: str | None) -> str | None:
    """item 76: a layer's own real CAD name (scan_layers()'s "name"
    field, item 74) read for the role it plainly describes -- "Supply
    Air Duct" pre-fills "supply" instead of leaving every one of a real
    drawing's layers on "ignore" for a person to click through by hand.
    None (not "ignore") when nothing in the name says so, or for a
    colour-only layer with no real name at all, or any industry but
    HVAC -- the caller (addons/boq/takeoff.py) only overrides its
    dropdown's own default when this returns something, same restraint
    saved_layer_roles() already uses for its own cross-tender memory."""
    if industry == HVAC and name:
        return _hvac().suggest_role_from_name(name)
    return None


def suggest_role_from_memory(industry: str, layer: dict, saved_roles: dict) -> str | None:
    """item 80: the role a real named layer should start on when its own
    name says nothing, read from colours the owner already mapped on an
    earlier drawing (scan_layers()'s "color_keys" for that layer, against
    saved_layer_roles()). Found live: return duct fell from 16.5 ft to
    4.9 ft on the same drawing because the geometry one remembered colour
    used to pick up now sat inside a named layer nothing mapped. None for
    a colour-only row, an industry with no rule-set, or no match."""
    if industry == HVAC and layer.get("name"):
        return _hvac().suggest_role_from_colours(layer.get("color_keys"), saved_roles)
    return None


def writeup_note(industry: str) -> str:
    """`industry`'s own write-up rules, handed straight to
    core.boq.formatting_prompt()'s `industry_note` parameter -- the write-up
    side of the same split scan_layers()/extract()/summary_text() already
    make on the measurement side. Lives here, in the add-on, not in the
    engine (prism_terminal/core/boq.py): found live, 31 Oct 2026, that the
    engine used to carry this exact HVAC text inline, gated on a bare
    `hvac: bool` -- one `if` away from leaking into every other trade's own
    BOQ, the opposite of the owner's own standing rule that a trade-specific
    rule must live apart and fire only when that trade is named. An industry
    with nothing written yet gets "", same as `roles()`/`scales()` above --
    a lookup, not an operation this industry is being asked to perform."""
    if industry == HVAC:
        return (
            "\n\nHVAC-SPECIFIC WRITE-UP RULES (this BOQ was asked for as HVAC):\n"
            "  (e) TWO SIMILARLY-NAMED LAYERS ARE NOT AUTOMATICALLY A DUPLICATE "
            "— caught on a real file: a layer pair named like an old/new naming "
            "convention (e.g. a legacy prefix vs a current one) was assumed to "
            "be the same system measured twice, and the 'legacy' half was "
            "dropped from the BOQ entirely — it was a real, separate half of "
            "the building with its own equipment and different sizes, not a "
            "duplicate at all. So: compare the actual figures, not just the "
            "names. Two layers whose lengths or counts are IDENTICAL or within "
            "a percent or two of each other are very likely the same geometry "
            "traced twice — pick the one to keep, state which and why, and say "
            "so under that line. Two layers whose figures DIFFER by more than "
            "a small margin are more likely two real, separate things (two "
            "zones, two halves, two systems) — in that case NEVER drop either "
            "one. Price both, under their own line items, and flag it for the "
            "designer to confirm which naming convention is current or whether "
            "they are genuinely separate. When you are not sure which case "
            "this is, keep both — the failure mode that actually happened was "
            "dropping real, paid-for ductwork because it looked like a "
            "duplicate; there is no equivalent failure mode from keeping an "
            "actual duplicate priced twice, because you still say so on the "
            "line and the reader can net it out. Silence that drops a measured "
            "quantity is the one mistake not to make.\n"
            "  (f) Block counts can include a drawing's own LEGEND/KEY — a "
            "single reference instance of a symbol, drawn once for reference, "
            "not an installed item. Prism's measurement cannot tell a legend "
            "instance apart from a real one, so if the count for any terminal, "
            "damper, valve or fitting type looks like it could include one, say "
            "so plainly next to that figure and tell the reader to cross-check "
            "it against a terminal/equipment schedule if the drawing has one — "
            "never silently subtract or silently trust the raw count either.\n"
            "  (g) A BARE NUMBER IS NOT A TYPE — found live comparing a second "
            "real tool run against a real file: every bare TR tag in the "
            "measured data got called \"Hi-Wall\" in the finished BOQ, because "
            "\"Hi-Wall\" was the only equipment TYPE word anywhere else in this "
            "document, and nothing told the write-up stage not to fill that "
            "gap with it. The rule, stated plainly rather than left to be "
            "inferred: when the measured data gives you a number (a capacity, "
            "a count, a size) WITHOUT a type/category attached to it, say the "
            "type is not identified, on that line, every time — never borrow a "
            "type name from a DIFFERENT reading elsewhere in this same "
            "document just because it is the only one available. A reading "
            "that already states its own \"type not read\"/\"not identified\" "
            "wording is doing this for you — use it, don't override it with "
            "something more specific-sounding.\n"
            "  (h) SHEET-METAL AND INSULATION AREA ARE PER DUCT SIZE, NEVER ONE "
            "BLENDED TOTAL — found live comparing two real runs on the same "
            "drawing: one write-up broke supply and return duct into their own "
            "line per measured size (e.g. \"18in x ? , 140.4ft\" became its own "
            "row with its own perimeter, gauge and insulation area), the other "
            "collapsed every duct system into a single \"length x one assumed "
            "average perimeter\" figure — correct-looking, but useless for "
            "pricing or ordering sheet by size. The measured data already gives "
            "you each system's duct broken out by exact size and length (e.g. "
            "\"supply 18x? 140.4ft (21 runs)\") — use that breakdown. For EACH "
            "such line: state the duct's width (as measured) and height (as "
            "measured if both were read, otherwise one explicit assumed height "
            "stated once as an input and reused — never a different silent "
            "guess per line), compute that line's OWN perimeter, sheet-metal "
            "area (perimeter x length) and insulation area, and give it its own "
            "row. Do this separately for EACH duct system (supply, return, "
            "exhaust, toilet-exhaust, condensate, any other named system) — "
            "never merge systems into one combined area figure. A single "
            "blended total across every system, in place of this per-size, "
            "per-system breakdown, is not acceptable. Under each system's "
            "rows give that system's own subtotal for length, sheet-metal "
            "area and insulation area, and after the last system one line "
            "each for total sheet-metal area and total insulation area "
            "(the sum of those subtotals). Insulation area is always given "
            "as a figure this way -- never left blank, and never moved to a "
            "provisional 'not shown on drawing' line, when the duct area it "
            "comes from has been worked out.\n"
            "  (i) VAV BOX QUANTITY COMES FROM THE SHAPE COUNT WHEN THERE IS "
            "ONE — the measured data may give two VAV figures: 'VAV BOXES "
            "COUNTED BY SHAPE' (drawn blocks on the drawing's own VAV layer) "
            "and a count of VAV tags read as text. When the shape count is "
            "present, it is the VAV box quantity; state the tag count beside "
            "it as a cross-check only. Never add the two, and never bill the "
            "lower tag count in place of the shape count."
        )
    return ""


def derivation_example(industry: str) -> str:
    """The one worked arithmetic example inside formatting_prompt()'s own
    "how to handle an item the drawing's own measured geometry does not
    cover" rule -- kept per-industry so an HVAC job is shown an HVAC
    example (duct supports), never ELV's own default (camera spacing),
    which has nothing to do with ductwork. Empty falls back to that ELV
    default inside formatting_prompt() itself -- unchanged for any
    industry, HVAC included until this was written, that has none yet."""
    if industry == HVAC:
        return "'duct run 300 m ÷ 2.4 m support spacing = 125 nos'"
    return ""


def scan_layers(industry: str, pdf_path: str) -> list[dict]:
    """Step 1: every line/edge in the PDF grouped by colour+weight, longest
    first -- for the person to say what each one actually is, before
    anything is extracted."""
    if industry == HVAC:
        return _hvac().scan_layers(pdf_path)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def saved_layer_roles(industry: str) -> dict:
    """Step 1's own cross-tender memory -- the role a colour+weight+kind
    key was mapped to on a PREVIOUS drawing, so the same key on a new one
    starts pre-filled rather than back at "ignore" every single time.
    Found 30 Oct 2026: the standalone hvac_takeoff.py tool has always read
    this (`load_map()`, pre-filling its own combo boxes) and the exact
    same key a tender ago (`#000000@1.56:line`/`:poly` -> "supply") is why
    it measured real duct runs on a drawing BOQ's own Step 1 showed every
    layer still on "ignore" for -- BOQ never looked at this file at all.
    An unbuilt industry has no memory to read, same as `roles`/`scales`
    above -- empty, not an error, since nothing here is being asked to
    measure anything."""
    if industry == HVAC:
        return _hvac().load_map()
    return {}


def remember_layer_roles(industry: str, layer_map: dict) -> None:
    """The other half of `saved_layer_roles` -- called once a person has
    set Step 1's roles for THIS drawing, so the next one gets the benefit.
    A no-op for an industry with no PDF-takeoff rule-set, same reasoning
    as `saved_layer_roles`."""
    if industry == HVAC:
        _hvac().save_map(layer_map)


def layer_preview(industry: str, pdf_path: str, key: str, page_index: int = 0) -> bytes:
    """Step 1's own "what does this colour actually draw" picture, PNG
    bytes -- a layer's own segments highlighted on the faded page, so a
    person can SEE what a colour swatch and a segment count can't say.
    Raises ValueError for an industry with no PDF-takeoff rule-set, same
    as every other function here."""
    if industry == HVAC:
        return _hvac().layer_preview_png(pdf_path, key, page_index)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def extract(industry: str, pdf_path: str, layer_map: dict, pt_per_ft: float,
           use_ocr: bool = True, log=None, vision_tag_reader=None) -> dict:
    """Step 2: run `industry`'s own extraction with the layer roles chosen
    at Step 1. Returns the tool's own result dict, untouched -- so a future
    industry's own shape only has to be understood by whatever review step
    reads it, never reshaped here to match HVAC's.

    `vision_tag_reader`: HVAC's own AI VAV-tag re-check (hvac_takeoff.py's
    vision_vav_recount()) -- threaded through only because this is the one
    dispatch point every industry's extraction already passes through, the
    same reason `use_ocr` does; no other industry reads this parameter,
    and this function still raises for one below before it would matter."""
    if industry == HVAC:
        return _hvac().extract(pdf_path, layer_map, pt_per_ft, use_ocr=use_ocr,
                               log=log or (lambda *a: None),
                               vision_tag_reader=vision_tag_reader)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def summary_text(industry: str, result: dict) -> str:
    """The plain-text handoff to the BOQ prompt -- treated exactly like any
    other external measurement from here on (see
    BoqDialog._use_external_measurements)."""
    if industry == HVAC:
        return _hvac().summary_text(result)
    if industry == ELV:
        return _elv().summary_text(result)
    raise ValueError(f"No PDF-takeoff rule-set for {industry!r}")


def extract_ai_read(industry: str, path: str, tag_reader, log=None) -> dict:
    """Step 2 for an industry whose whole takeoff IS the shared reader
    (has_ai_read_modes()) -- a separate entry point from extract() above,
    not an overload of it: extract()'s own signature (layer_map, pt_per_ft)
    is HVAC's Step-1 geometry shape, which this kind of industry has none
    of. `path` is a PDF, DWG or DXF (drawing_reader.py decides which
    reading path from the extension, DXF-entities-first); `tag_reader` is
    the same plain callback shape hvac_takeoff.vision_vav_recount() already
    uses -- built and owned by addons/boq/workers.py, never by this module
    or drawing_reader.py itself. No `mode` parameter any more (item 64):
    the shared reader always tries real DXF entities first and always
    tiles for the AI fallback, never a user-facing whole/tiled choice."""
    if industry == ELV:
        return _elv().extract(path, tag_reader, log=log or (lambda *a: None))
    raise ValueError(f"No AI-read rule-set for {industry!r}")


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


def symbol_counts_and_areas(industry: str, result: dict) -> list[tuple[str, int, float | None]]:
    """Item 27 rule 3, the review UI's half: one (type, count, area_sqft)
    row per symbol type found by shape -- the same figures summary_text()
    hands to the BOQ writer, shown here before that, so "Use these
    measurements" is never the first time anyone sees them."""
    if industry != HVAC:
        return []
    return _hvac().symbol_counts_and_areas(result)


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
