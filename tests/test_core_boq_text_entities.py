"""core.boq.measure()'s own `text_entities` return key (item 65).

measure() has always walked every TEXT/MTEXT entity internally (rule 3
reads duct/pipe sizes out of them when hvac=True) but never handed that
reading back -- the only reason addons/boq/drawing_reader.py grew its own,
separate ezdxf walk just to read a DXF's own text, parsing the same file
a second time for a different slice of the same entities. This is the
one, additive key that lets every caller share ONE walk's answer instead.

The drawing here is built with ezdxf in a temp folder; nothing real is
read and nothing is sent anywhere."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import core_bridge as CB  # noqa: E402

boq = CB.get_boq()

try:
    import ezdxf
except ImportError:                                   # pragma: no cover
    ezdxf = None


def _dxf(add_entities) -> str:
    doc = ezdxf.new()
    msp = doc.modelspace()
    add_entities(msp)
    fd, path = tempfile.mkstemp(suffix=".dxf")
    os.close(fd)
    doc.saveas(path)
    return path


@unittest.skipUnless(ezdxf, "ezdxf not installed")
class MeasureReturnsTheRealTextItAlreadyWalks(unittest.TestCase):
    def test_text_and_mtext_content_and_position_are_both_returned(self):
        path = _dxf(lambda msp: (
            msp.add_text("CAM-01", dxfattribs={"insert": (1.0, 2.0)}),
            msp.add_mtext("Panel schedule note", dxfattribs={"insert": (3.0, 4.0)}),
        ))
        try:
            q = boq.measure(path)
        finally:
            os.remove(path)
        texts = {content: pos for pos, content in q["text_entities"]}
        self.assertEqual(texts["CAM-01"], (1.0, 2.0))
        self.assertIn("Panel schedule note", texts)

    def test_a_drawing_with_no_text_returns_an_empty_list_not_a_missing_key(self):
        path = _dxf(lambda msp: msp.add_line((0, 0), (10, 0)))
        try:
            q = boq.measure(path)
        finally:
            os.remove(path)
        self.assertEqual(q["text_entities"], [])

    def test_summary_text_lists_real_text_not_already_a_block(self):
        path = _dxf(lambda msp: (
            msp.add_text("Panel P-04, 12 circuits", dxfattribs={"insert": (0, 0)}),
            msp.add_text("Panel P-04, 12 circuits", dxfattribs={"insert": (5, 0)}),
        ))
        try:
            q = boq.measure(path)
            text = boq.summary_text(q)
        finally:
            os.remove(path)
        self.assertIn("TEXT ON THE DRAWING", text)
        self.assertIn("Panel P-04, 12 circuits  (×2)", text)

    def test_summary_text_has_no_text_section_when_there_is_none(self):
        path = _dxf(lambda msp: msp.add_line((0, 0), (10, 0)))
        try:
            q = boq.measure(path)
            text = boq.summary_text(q)
        finally:
            os.remove(path)
        self.assertNotIn("TEXT ON THE DRAWING", text)

    def test_text_entities_are_collected_regardless_of_the_hvac_flag(self):
        """Always collected, same as the engine's own docstring says --
        `hvac` only gates whether rule 3 goes on to MATCH them against a
        duct run, never whether they are read at all."""
        path = _dxf(lambda msp: msp.add_text(
            "AP-04", dxfattribs={"insert": (0, 0)}))
        try:
            q_hvac = boq.measure(path, hvac=True)
            q_plain = boq.measure(path, hvac=False)
        finally:
            os.remove(path)
        self.assertEqual(q_hvac["text_entities"], q_plain["text_entities"])


if __name__ == "__main__":
    unittest.main()
