"""Words the client never gave are not shown on their film."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "prism_terminal")
if ENGINE not in sys.path:
    sys.path.insert(0, ENGINE)

from core.motion import grounding  # noqa: E402


def _scene(*texts):
    return {"id": "s", "nodes": [{"id": f"t{i}", "type": "text", "content": t} for i, t in enumerate(texts)]}


def _corpus(request, **kw):
    return grounding.allowed_corpus(request, kw)


class Invented(unittest.TestCase):
    def test_the_christmas_sign_off_is_caught(self):
        c = _corpus("make a motion graphics video celebrating christmas")
        f = grounding.grounding_faults(_scene("Merry Christmas", "from all of us at Prism"), c)
        self.assertTrue(any("Prism" in x for x in f), f)

    def test_the_tool_name_is_fine_when_the_client_is_called_that(self):
        c = _corpus("A film for Prism Dental in Surat")
        self.assertEqual(grounding.grounding_faults(_scene("Prism Dental", "from the team at Prism Dental"), c), [])

    def test_a_signer_the_client_gave_passes_and_one_they_did_not_fails(self):
        c = _corpus("Reel for Shree Engineering, say merry christmas")
        self.assertEqual(grounding.grounding_faults(_scene("from all of us at Shree Engineering"), c), [])
        f = grounding.grounding_faults(_scene("from all of us at Acme Works"), c)
        self.assertTrue(f and "Acme Works" in f[0], f)

    def test_invented_contacts_are_caught_given_ones_pass(self):
        c = _corpus("Reel for Shree. Phone +91 98765 43210, shree.in, hello@shree.in, @shree_eng")
        ok = _scene("Call +91 98765 43210", "shree.in", "hello@shree.in", "@shree_eng")
        self.assertEqual(grounding.grounding_faults(ok, c), [])
        bad = _scene("Call 022 1234 5678", "www.acme.com", "sales@acme.com", "@acme_official")
        f = grounding.grounding_faults(bad, c)
        for needle in ("022 1234 5678", "www.acme.com", "sales@acme.com", "@acme_official"):
            self.assertTrue(any(needle in x for x in f), (needle, f))

    def test_ordinary_numbers_and_dates_are_not_phone_numbers(self):
        c = _corpus("a christmas film")
        self.assertEqual(grounding.grounding_faults(_scene("25 December", "Since 1998", "10,000,000 meals"), c), [])

    def test_text_in_checklists_children_and_runs_is_read(self):
        c = _corpus("a christmas film")
        scene = {"nodes": [{"type": "ui_window", "children": [{"type": "text", "content": "by Acme Works"}]},
                           {"type": "ui_checklist", "items": [{"label": "Call 9876543210"}]}]}
        f = grounding.grounding_faults(scene, c)
        self.assertEqual(len(f), 2, f)

    def test_with_nothing_known_about_the_client_nothing_is_checked(self):
        self.assertEqual(grounding.grounding_faults(_scene("from all of us at Prism"), ""), [])


class InThePrompts(unittest.TestCase):
    def test_the_rulebook_says_never_invent_a_sender_in_every_profile(self):
        from core.motion import generate
        for sk in (None, "cinematic_glass", "story", "brand_launch"):
            self.assertIn("NEVER INVENT WHO IT IS FROM", generate._rulebook(sk), sk)

    def test_build_spec_sends_an_invented_sign_off_back(self):
        from core.motion import generate
        import json
        first = json.dumps({"project": {"width": 1080, "height": 1920, "fps": 30},
                            "storyboard": [{"scene": 1, "seconds": 3, "job": "close", "caption": "Merry Christmas",
                                            "subject": "s", "look": "l", "motion": "m"}]})
        asked = []

        def ask(prompt, expect=None):
            asked.append(prompt)
            bad = len(asked) == 1
            txt = "from all of us at Prism" if bad else "Merry Christmas"
            return "```json\n" + json.dumps({"nodes": [
                {"id": "a", "type": "text", "content": "Merry Christmas", "position": [540, 800]},
                {"id": "b", "type": "text", "content": txt, "position": [540, 1000]}]}) + "\n```"

        generate.build_spec(first, ask, check=lambda spec: [], request="make a christmas film", skeleton=None)
        self.assertGreaterEqual(len(asked), 2, "the invented sign-off should have been sent back")
        self.assertIn("Prism", asked[1])


if __name__ == "__main__":
    unittest.main()
