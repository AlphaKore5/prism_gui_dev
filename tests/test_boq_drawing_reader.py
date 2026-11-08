"""addons/boq/drawing_reader.py -- the shared "read the drawing" step
(item 64, BOQ-CHANGES-TODO.md).

Covers the real decision this module makes: DXF entities first (built
against real ezdxf documents, not mocked -- the whole point of this step
is that it is not a guess), a DXF with nothing readable reported honestly
rather than silently guessed at, DWG routed through the engine's own
converter (CB.get_boq().dwg_to_dxf(), mocked -- that converter is already
covered by tests/test_core_boq_dwg2dxf.py), and the AI-tiled PDF fallback
reading every page, never just the first."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from addons.boq import drawing_reader as R                          # noqa: E402


def _write_dxf(add_entities) -> str:
    import ezdxf
    doc = ezdxf.new()
    msp = doc.modelspace()
    add_entities(msp)
    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    doc.saveas(path)
    return path


class TileBoundsCollapsesToOneTileForASmallPage(unittest.TestCase):
    """The mechanism that makes "always tiled" equal to "whole" for a
    drawing that already fits -- no second code path needed for a small
    file, per item 64's own design."""

    def test_a_page_within_max_dim_is_one_tile(self):
        tiles = R._tile_bounds(1000, 800, max_dim=2400)
        self.assertEqual(tiles, [(0, 0, 1000, 800)])

    def test_a_page_larger_than_max_dim_is_several_tiles(self):
        tiles = R._tile_bounds(5000, 3000, max_dim=2400)
        self.assertGreater(len(tiles), 1)


class RealDxfTextAndBlocksAreReadWithZeroAi(unittest.TestCase):
    def test_text_and_mtext_entities_are_read_verbatim(self):
        path = _write_dxf(lambda msp: (
            msp.add_text("CAM-01", dxfattribs={"insert": (0, 0)}),
            msp.add_mtext("Panel schedule note", dxfattribs={"insert": (1, 1)}),
        ))
        try:
            found = R._read_dxf_entities(path)
        finally:
            os.remove(path)
        self.assertIn("CAM-01", found["text"])
        self.assertIn("Panel schedule note", found["text"])

    def test_named_insert_blocks_are_counted_by_name(self):
        path = _write_dxf(lambda msp: None)
        import ezdxf
        doc = ezdxf.readfile(path)
        doc.blocks.new(name="CAMERA-DOME")
        msp = doc.modelspace()
        msp.add_blockref("CAMERA-DOME", (0, 0))
        msp.add_blockref("CAMERA-DOME", (10, 10))
        doc.saveas(path)
        try:
            found = R._read_dxf_entities(path)
        finally:
            os.remove(path)
        self.assertEqual(found["blocks"]["CAMERA-DOME"], 2)

    def test_a_dxf_with_real_text_is_read_without_any_tag_reader_call(self):
        path = _write_dxf(lambda msp: msp.add_text(
            "DVR-01", dxfattribs={"insert": (0, 0)}))
        reader = mock.Mock()
        try:
            res = R.extract(path, reader)
        finally:
            os.remove(path)
        self.assertEqual(res["method"], "dxf_entities")
        self.assertFalse(reader.called)
        self.assertIn("DVR-01", res["dxf"]["text"])


class ADxfWithNoRealTextIsReportedNotGuessedAt(unittest.TestCase):
    """Text "exploded" into plain LINE/LWPOLYLINE geometry leaves nothing
    in TEXT/MTEXT/INSERT for this module to find -- that absence is the
    signal. No AI fallback is attempted for a DXF (no DXF-to-raster
    pipeline exists anywhere in this codebase to call) -- the honest
    answer is to say so, same discipline elv_takeoff.py's own docstring
    already held to: an unverified measurement is worse than none."""

    def test_geometry_only_dxf_reports_dxf_no_text(self):
        path = _write_dxf(lambda msp: msp.add_line((0, 0), (10, 0)))
        reader = mock.Mock()
        try:
            res = R.extract(path, reader)
        finally:
            os.remove(path)
        self.assertEqual(res["method"], "dxf_no_text")
        self.assertFalse(reader.called)

    def test_summary_text_tells_the_user_to_use_a_pdf_instead(self):
        res = {"source": {"file": "x.dxf"}, "method": "dxf_no_text",
               "notes": [], "dxf": {"text": [], "blocks": {}, "entity_count": 4},
               "pages": []}
        text = R.summary_text(res)
        self.assertIn("PDF", text)


class ADwgConvertsToDxfThroughTheEngineFirst(unittest.TestCase):
    def test_dwg_to_dxf_is_reached_through_cb_get_boq(self):
        dxf_path = _write_dxf(lambda msp: msp.add_text(
            "AP-01", dxfattribs={"insert": (0, 0)}))
        # Only dwg_to_dxf() is faked (no real DWG/converter in this test) --
        # measure() runs for real, same as _read_dxf_entities() now reaches
        # it through CB.get_boq() for the text/block walk too (item 65).
        real_boq = R.CB.get_boq()
        fake_boq = mock.Mock()
        fake_boq.dwg_to_dxf.return_value = (dxf_path, ["converted with -m"])
        fake_boq.measure = real_boq.measure
        try:
            with mock.patch.object(R.CB, "get_boq", return_value=fake_boq):
                res = R.extract("/x/fake.dwg", mock.Mock())
        finally:
            os.remove(dxf_path)
        fake_boq.dwg_to_dxf.assert_called_once_with("/x/fake.dwg")
        self.assertEqual(res["method"], "dxf_entities")
        self.assertEqual(res["notes"], ["converted with -m"])


class SummaryTextNeverHandsTheRawFileOnwardAgain(unittest.TestCase):
    def test_dxf_entities_summary_lists_the_text_and_blocks_not_a_file_path(self):
        res = {"source": {"file": "site.dxf"}, "method": "dxf_entities",
               "notes": [],
               "dxf": {"text": ["CAM-01"], "blocks": {"CAMERA": 3}, "entity_count": 9},
               "pages": []}
        text = R.summary_text(res)
        self.assertIn("CAM-01", text)
        self.assertIn("CAMERA: 3", text)

    def test_ai_tiled_summary_covers_every_page_not_just_the_first(self):
        res = {"source": {"file": "x.pdf"}, "method": "ai_tiled", "notes": [],
               "dxf": None,
               "pages": [{"page": 0, "ocr_text": [], "ai_text": "page one text"},
                        {"page": 1, "ocr_text": [], "ai_text": "page two text"}]}
        text = R.summary_text(res)
        self.assertIn("page one text", text)
        self.assertIn("page two text", text)
        self.assertIn("page 1", text)
        self.assertIn("page 2", text)


class ExtractReadsEveryPageOfAMultiPagePdf(unittest.TestCase):
    """The real gap found before this module existed: a PDF whose page 1
    is cover text and page 2 is the actual drawing must not be missed by
    only ever reading page 0."""

    def test_extract_calls_read_tiled_page_once_per_page(self):
        with mock.patch.object(R, "page_count", return_value=3), \
                mock.patch.object(R, "read_tiled_page",
                                  side_effect=lambda *a, **kw: {
                                      "page": kw["page_index"], "ocr_text": [],
                                      "ai_text": ""}) as rtp:
            res = R.extract("/x/fake.pdf", mock.Mock(), log=lambda *a: None)
        self.assertEqual(rtp.call_count, 3)
        self.assertEqual([p["page"] for p in res["pages"]], [0, 1, 2])
        self.assertEqual(res["method"], "ai_tiled")

    def test_unsupported_extension_raises(self):
        with self.assertRaises(ValueError):
            R.extract("/x/fake.txt", mock.Mock())


if __name__ == "__main__":
    unittest.main()
