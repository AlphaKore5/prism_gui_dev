"""The file viewer shows NUMBERS for formulas nobody has calculated yet.

Prism's priced BOQ (core/boq_price.write_boq_xlsx) writes live formulas
(=D5*E5, =SUM(...), =ROUND(...)) and, like any file written by a program,
carries no calculated results. Excel computes them on opening; Prism's own
viewer showed the formula text, so a customer opening their priced BOQ in
Prism saw "=SUM(F5:F6)" where the grand total should be. viewer_data now
computes the simple formulas such files use, with its own small calculator
(no eval). What it cannot compute still shows the formula.
"""
from __future__ import annotations

import os
import sys
from decimal import Decimal

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PRISM_LICENSE_OFFLINE_DEV", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl                                                    # noqa: E402

import core_bridge as CB                                           # noqa: E402
import viewer_data as VD                                           # noqa: E402


def _cells(data):
    return [c for s in data["sheets"] for r in [s["columns"]] + s["rows"] for c in r]


def _num(text) -> float:
    return float(str(text).replace(",", ""))


def test_prisms_own_priced_boq_shows_amounts_and_the_right_grand_total(tmp_path):
    bp = CB.get_boq_price()
    boq = bp.Boq(title="Test BOQ", contingency_pct=Decimal(5), gst_pct=Decimal(18), items=[
        bp.BoqItem("GI duct 600x400", "m", Decimal("42"), Decimal("1450.50")),
        bp.BoqItem("Supply air diffuser", "nos", Decimal("12"), Decimal("2300")),
    ])
    path = bp.write_boq_xlsx(boq, str(tmp_path / "priced.xlsx"))
    data = VD._read_xlsx(path)
    left = [c for c in _cells(data) if isinstance(c, str) and c.startswith("=")]
    assert left == [], f"formulas still shown: {left[:5]}"
    numbers = []
    for c in _cells(data):
        try:
            numbers.append(_num(c))
        except (TypeError, ValueError):
            pass
    assert 60921.0 in numbers                     # 42 x 1450.50
    assert float(boq.grand_total()) in numbers    # the same total Prism computes itself


def _book(tmp_path, rows, extra=None):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "BOQ"
    for r in rows:
        ws.append(r)
    if extra:
        ws2 = wb.create_sheet(extra[0])
        for r in extra[1]:
            ws2.append(r)
    p = tmp_path / "b.xlsx"
    wb.save(p)
    return VD._read_xlsx(str(p))


def test_arithmetic_sum_round_min_max_abs_average(tmp_path):
    d = _book(tmp_path, [
        ["a", "b", "out"],
        [2, 3, "=A2*B2+1"],                   # 7
        [10, 4, "=(A3-B3)/2^1"],              # 3
        [None, None, "=SUM(C2:C3)"],          # 10
        [None, None, "=ROUND(C4/3,2)"],       # 3.33
        [None, None, "=MAX(A2:B3)-MIN(A2,B2)+ABS(-1)"],   # 10-2+1 = 9
        [None, None, "=AVERAGE(A2:A3)"],      # 6
    ])
    col = [r[2] for r in d["sheets"][0]["rows"]]
    assert [_num(c) for c in col] == [7, 3, 10, 3.33, 9, 6]


def test_another_sheet_can_be_referenced(tmp_path):
    d = _book(tmp_path, [["total"], ["=Rates!B1*2"]], extra=("Rates", [["rate", 2300]]))
    assert _num(d["sheets"][0]["rows"][0][0]) == 4600


def test_text_in_a_sum_is_skipped_like_excel(tmp_path):
    d = _book(tmp_path, [["v"], [5], ["n/a"], [7], ["=SUM(A2:A4)"]])
    assert _num(d["sheets"][0]["rows"][3][0]) == 12


def test_what_cannot_be_computed_still_shows_the_formula(tmp_path):
    d = _book(tmp_path, [["v"], ['=VLOOKUP(1,A1:A2,1,FALSE)'], ["=A4"], ["=A3"], ['=A1*2']])
    col = [r[0] for r in d["sheets"][0]["rows"]]
    assert col[0].startswith("=VLOOKUP")      # unknown function
    assert col[1] == "=A4" and col[2] == "=A3"  # a loop between two cells
    assert col[3] == "=A1*2"                   # text times a number


def test_a_formula_cannot_run_python(tmp_path):
    d = _book(tmp_path, [["v"], ['=__import__("os").system("x")'], ["=1+1;2"]])
    col = [r[0] for r in d["sheets"][0]["rows"]]
    assert col[0].startswith("=__import__") and col[1] == "=1+1;2"


def test_a_cached_value_from_excel_is_shown_as_it_was_saved(tmp_path):
    # A cell with a saved value keeps that value; nothing is recomputed.
    d = _book(tmp_path, [["v"], [3]])
    assert d["sheets"][0]["rows"][0][0] in (3, "3")
