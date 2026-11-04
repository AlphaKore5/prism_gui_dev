"""addons/boq/workers.py's HvacTakeoffWorker -- item 2 (5 Nov 2026)'s own
AI VAV-tag re-check wiring: the one place that builds the real tag_reader
callback hvac_takeoff.vision_vav_recount() calls, and the one place that
decides (from api_key + use_ai_tags) whether that callback is offered to
industries.extract() at all. `run()` is called directly, never start() --
a plain QThread method call, no real thread, matching this repo's own
testing rule against exercising the Qt event loop in a test.
"""
from __future__ import annotations

import base64
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                         # noqa: E402

_app = QApplication.instance() or QApplication([])

from addons.boq import workers as W                                 # noqa: E402


class TagReaderCallsOpenrouterWithTheCappedReasoningOffShape(unittest.TestCase):
    """Found live testing a vision model on a real drawing tile: no cap
    at all let one tile run 10 minutes repeating itself, and a
    "thinking" model can return an empty answer unless reasoning is
    turned off -- both must be set on every call this makes, not left
    to whatever openrouter_chat's own defaults are."""

    def test_sends_the_model_capped_tokens_and_reasoning_off(self):
        w = W.HvacTakeoffWorker("HVAC", "/x/fake.pdf", {}, 9.0, api_key="sk-or-x")
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="VAV-1-2") as chat:
            out = w._tag_reader(b"\x89PNG...")
        self.assertEqual(out, "VAV-1-2")
        args, kwargs = chat.call_args
        self.assertEqual(args[0], "sk-or-x")
        self.assertEqual(args[1], W.HVAC_VISION_MODEL)
        self.assertEqual(kwargs["max_tokens"], 900)
        self.assertEqual(kwargs["extra"]["reasoning"], {"enabled": False})

    def test_the_image_bytes_are_base64_encoded_into_an_image_attachment(self):
        w = W.HvacTakeoffWorker("HVAC", "/x/fake.pdf", {}, 9.0, api_key="sk-or-x")
        with mock.patch.object(W.CB.openrouter, "openrouter_chat",
                               return_value="") as chat:
            w._tag_reader(b"hello")
        attachments = chat.call_args.kwargs["attachments"]
        self.assertEqual(attachments[0]["kind"], "image")
        self.assertEqual(base64.b64decode(attachments[0]["b64"]), b"hello")


class RunOnlyOffersTheAiTagReaderWhenBothGatesAreOn(unittest.TestCase):
    """The two-gate shape _run_prism_agent() (addons/boq/dialog.py)
    already uses for the BOQ write-up path, reused here: an empty key or
    use_ai_tags=False must mean industries.extract() never even sees a
    reader, the same as if the feature did not exist."""

    def _run_and_capture(self, **kw):
        w = W.HvacTakeoffWorker("HVAC", "/x/fake.pdf", {}, 9.0, **kw)
        with mock.patch.object(W.industries, "extract",
                               return_value={"labels": []}) as ex:
            w.run()
        return ex

    def test_no_api_key_means_no_reader_even_if_the_box_is_checked(self):
        ex = self._run_and_capture(use_ai_tags=True, api_key="")
        self.assertIsNone(ex.call_args.kwargs["vision_tag_reader"])

    def test_use_ai_tags_false_means_no_reader_even_with_a_key(self):
        ex = self._run_and_capture(use_ai_tags=False, api_key="sk-or-x")
        self.assertIsNone(ex.call_args.kwargs["vision_tag_reader"])

    def test_both_gates_on_passes_the_bound_tag_reader(self):
        w = W.HvacTakeoffWorker("HVAC", "/x/fake.pdf", {}, 9.0,
                                use_ai_tags=True, api_key="sk-or-x")
        with mock.patch.object(W.industries, "extract",
                               return_value={"labels": []}) as ex:
            w.run()
        reader = ex.call_args.kwargs["vision_tag_reader"]
        self.assertIsNotNone(reader)
        self.assertEqual(reader, w._tag_reader)

    def test_an_extraction_failure_still_emits_failed_not_an_exception(self):
        w = W.HvacTakeoffWorker("HVAC", "/x/fake.pdf", {}, 9.0)
        seen = []
        w.failed.connect(seen.append)
        with mock.patch.object(W.industries, "extract", side_effect=RuntimeError("boom")):
            w.run()
        self.assertEqual(seen, ["boom"])


if __name__ == "__main__":
    unittest.main()
