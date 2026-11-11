"""Reel's spec lint does not mistake a phone number for a data series.

Study of 11 Nov 2026 (finding R1): `+91 98765 43210` on an endcard matched
the "two or more big numbers" rule and the writer was told to move the
client's phone number into a chart.
"""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core import reel  # noqa: E402


def _spec(**endcard):
    scenes = [
        {"type": "statement", "seconds": 4, "lines": ["Precision turned parts.", "Made in Vadodara."]},
        {"type": "figure", "seconds": 5, "value": "22", "label": "years of CNC machining"},
        {"type": "pillar", "seconds": 5, "heading": "CNC turning and milling",
         "caption": "Parts for pumps and automotive", "icons": ["tools", "factory", "package"]},
        {"type": "figure", "seconds": 4.5, "value": "ISO 9001", "label": "certified"},
        {"type": "endcard", "seconds": 4.5, "name": "Shree Precision Engineering",
         "tagline_lines": ["CNC turned and milled parts"], **endcard},
    ]
    return {"fps": 30, "scenes": scenes}


def _series_faults(faults):
    return [f for f in faults if "series of numbers" in f]


class PhoneNumbersAreNotSeries(unittest.TestCase):
    def test_indian_mobile_on_the_endcard_passes(self):
        faults = reel.lint_spec(_spec(contact="+91 98765 43210"))
        self.assertEqual(_series_faults(faults), [])

    def test_landline_with_std_code_passes(self):
        faults = reel.lint_spec(_spec(contact="0265 2345678 · www.shreeprecision.in"))
        self.assertEqual(_series_faults(faults), [])

    def test_a_phone_number_in_a_caption_passes_too(self):
        spec = _spec(contact="hello@shreeprecision.in")
        spec["scenes"][2]["caption"] = "Call +91 98765 43210 for a quote"
        self.assertEqual(_series_faults(reel.lint_spec(spec)), [])

    def test_a_real_series_in_a_caption_is_still_sent_to_a_chart(self):
        spec = _spec(contact="hello@shreeprecision.in")
        spec["scenes"][2]["caption"] = "Output grew from 1,200 units to 4,800 to 9,500"
        faults = _series_faults(reel.lint_spec(spec))
        self.assertEqual(len(faults), 1)
        self.assertIn("Scene 3 (pillar)", faults[0])


if __name__ == "__main__":
    unittest.main()
