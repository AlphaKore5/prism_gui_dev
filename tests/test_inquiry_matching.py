"""
[9] A picture read badly, and a guess shown as certain.

Real case (owner's data, sent 2026-10-02): an inquiry whose mail said only
"this product, 10 nos" was quoted against a rate-list row at ₹1,10,000 a
piece, ₹12,98,000 in all, with the window showing "Confident match". The
words "this" and "product" matched, and so did the quantity's "10". These
pin the matcher changes (core/quoting.py) and the window's confidence rule
(addons/inquiry/quotation.py) that stop that.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from decimal import Decimal
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication  # noqa: E402

import core_bridge as CB  # noqa: E402,F401
from core import mailflow, ocr, quoting, register  # noqa: E402
from addons.inquiry import quotation as Q  # noqa: E402
from addons.inquiry import ai_match  # noqa: E402

_app = QApplication.instance() or QApplication([])

LOCKERS = [
    quoting.RateItem(code="KJP 6", description="SS Locker 6 Comp",
                     rate=Decimal("62000")),
    quoting.RateItem(code="KJP 8", description="SS Locker 8 Comp",
                     rate=Decimal("78000")),
    quoting.RateItem(code="KJP 10", description="SS Locker 10 Comp",
                     rate=Decimal("110000")),
    quoting.RateItem(code="KJP 12", description="Steel cabinet 4 shelf",
                     rate=Decimal("24000")),
]


class TheWordsThatCount(unittest.TestCase):

    def test_this_product_is_not_a_product(self):
        self.assertEqual(quoting.tokens("this product, 10 nos"), ["10"])
        for word in ("this", "that", "these", "those", "item", "items",
                     "piece", "pieces", "pc", "product", "products"):
            self.assertEqual(quoting.tokens(word), [], word)

    def test_a_lone_digit_is_kept(self):
        """"8 Comp" is what tells the 8-compartment locker from the 6."""
        self.assertEqual(quoting.tokens("SS Locker 8 Comp"),
                         ["ss", "locker", "8", "comp"])

    def test_a_digit_glued_to_its_unit_is_not_a_lone_digit(self):
        """Keeping the 2 of "2mm" made every 2 mm spring look alike, and an
        exact spec stopped reading as confident."""
        self.assertEqual(quoting.tokens("2mm wire"), ["mm", "wire"])
        self.assertEqual(quoting.tokens("Locker (8 Comp)"), ["locker", "8", "comp"])
        items = [quoting.RateItem(code=c, description=d) for c, d in (
            ("CS-201", "Compression spring 2mm wire 25 OD"),
            ("CS-202", "Compression spring 2mm wire 30 OD"),
            ("CS-203", "Compression spring 3mm wire 25 OD"))]
        exact = quoting.match_item("compression spring 2mm wire 30 od", items)
        self.assertEqual(exact[0].item.code, "CS-202")
        self.assertTrue(quoting.is_confident(exact))

    def test_a_lone_letter_is_still_noise(self):
        self.assertEqual(quoting.tokens("a b 2 mm"), ["2", "mm"])


class PickingTheRow(unittest.TestCase):

    def test_8_comp_picks_the_8_comp_locker(self):
        matches = quoting.match_item("SS Locker 8 Comp", LOCKERS)
        self.assertEqual(matches[0].item.code, "KJP 8")
        self.assertTrue(Q.confident_match(matches))

    def test_a_codes_digits_do_not_count_unless_the_code_is_named(self):
        """"8 Comp" must not pull in the row whose code is "KJP 8" on the
        strength of the 8 alone — here the 4-shelf cabinet would be, if its
        code were KJP 8."""
        items = [quoting.RateItem(code="KJP 8", description="Steel cabinet 4 shelf"),
                 quoting.RateItem(code="KJP 12", description="SS Locker 8 Comp")]
        matches = quoting.match_item("Locker 8 Comp", items)
        self.assertEqual([m.item.code for m in matches], ["KJP 12"])

    def test_a_named_code_still_matches_on_its_digits(self):
        matches = quoting.match_item("KJP 8 please", LOCKERS)
        self.assertEqual(matches[0].item.code, "KJP 8")
        self.assertIn("8", matches[0].matched)


class NeverConfidentOnAGuess(unittest.TestCase):

    def test_this_product_10_nos_is_never_a_confident_match(self):
        """The real ₹12,98,000 case."""
        matches = quoting.match_item("this product, 10 nos", LOCKERS)
        self.assertFalse(Q.confident_match(matches))

    def test_a_number_alone_is_not_enough_even_with_a_clear_margin(self):
        items = [quoting.RateItem(code="A", description="Locker 10 Comp"),
                 quoting.RateItem(code="B", description="Almirah heavy duty "
                                  "steel 10 shelf 2000mm powder coated")]
        matches = quoting.match_item("10 nos", items)
        self.assertTrue(matches)
        self.assertFalse(Q.confident_match(matches))

    def test_one_generic_word_on_a_lone_candidate_is_not_enough(self):
        matches = quoting.match_item("locker", LOCKERS[3:] + [
            quoting.RateItem(code="Z", description="Locker")])
        self.assertEqual(len(matches), 1)
        self.assertFalse(Q.confident_match(matches))

    def test_nothing_matched_is_not_confident(self):
        self.assertFalse(Q.confident_match([]))


LAB_ITEMS = [
    quoting.RateItem(code="KJP 91", description="SS Lab Modular With Sink",
                     rate=Decimal("12480")),
    quoting.RateItem(code="KJP 6", description="SS Locker 6 Comp",
                     rate=Decimal("62000")),
    quoting.RateItem(code="KJP 8", description="SS Locker 4 Comp",
                     rate=Decimal("58000")),
    quoting.RateItem(code="KJP 77", description="SS Cross Over Bench Pigeon "
                     "Box Type", rate=Decimal("9500")),
]

# item 55 (4 Nov 2026), found live: this exact shape, from a real inquiry --
# a numbered/tabulated list of distinct products, no catalogue code, a
# quantity written after each with "<desc> :- <qty>" -- went through
# Prism's quotation screen as ONE line (qty 1, a generic description).
# Reproduced here character-for-character against the owner's own mail
# (the sender's mail client flows an HTML table's rows into one
# unbroken paragraph with no line breaks at all, which is the harder of
# the two shapes to split correctly).
_REAL_MULTI_ITEM_MAIL = (
    "requirement : SS Locker (4 Comp) :- 10 SS Locker (6 Comp) :- 12 "
    "SS Lab Modular (L shape) :-13 SS Lab Modular (L shape, long) :-9 "
    "SS Lab Modular (single) :-6 SS Cross Over Bench Pigeon Box Type :-3 "
    "SS E Type Cross Over Bench with Shoe Buttey / Cap Box :-7 "
    "SS E Type Cross Over Bench with Shoe Buttey / Cap Box (double) :-9")


class SplitFreeTextLinesReadsAnItemisedListNoCode(unittest.TestCase):
    """quoting.split_free_text_lines() -- pure pattern splitting, no
    rate-list involved, same separation find_requests()/_quantity_near()
    already keep between "find the pieces" and "match them to a row"."""

    def test_the_real_eight_item_mail_splits_into_eight_lines(self):
        out = quoting.split_free_text_lines(_REAL_MULTI_ITEM_MAIL)
        self.assertEqual(len(out), 8)
        self.assertEqual(out[0], ("SS Locker (4 Comp)", Decimal(10),
                                  "SS Locker (4 Comp) :- 10"))
        self.assertEqual(out[-1][0],
                         "SS E Type Cross Over Bench with Shoe Buttey / "
                         "Cap Box (double)")
        self.assertEqual(out[-1][1], Decimal(9))

    def test_a_single_sentence_with_no_itemised_shape_splits_into_nothing(self):
        self.assertEqual(
            quoting.split_free_text_lines("this product, 10 nos"), [])

    def test_lines_separated_by_real_newlines_split_the_same_way(self):
        text = "SS Locker (4 Comp): 10\nSS Lab Modular (single): 6\n"
        out = quoting.split_free_text_lines(text)
        self.assertEqual([d for d, _, _ in out],
                         ["SS Locker (4 Comp)", "SS Lab Modular (single)"])


class FindFreeTextRequestsMatchesEachLineToARateListRow(unittest.TestCase):
    def test_the_real_mail_becomes_eight_requests_against_a_matching_list(self):
        requests, unmatched = quoting.find_free_text_requests(
            _REAL_MULTI_ITEM_MAIL, LAB_ITEMS)
        self.assertEqual(len(requests), 8)
        self.assertEqual(unmatched, [])
        self.assertEqual(requests[0].item.code, "KJP 8")   # 4 Comp
        self.assertEqual(requests[0].quantity, Decimal(10))
        self.assertEqual(requests[1].item.code, "KJP 6")   # 6 Comp
        self.assertEqual(requests[5].item.code, "KJP 77")  # Pigeon Box Type

    def test_a_line_matching_nothing_on_the_rate_list_is_never_dropped(self):
        requests, unmatched = quoting.find_free_text_requests(
            "SS Locker (4 Comp): 10\nTitanium Widget: 3", LAB_ITEMS[2:3])
        self.assertEqual(len(requests), 1)
        self.assertEqual(unmatched, ["Titanium Widget: 3"])

    def test_a_weak_lone_match_is_flagged_not_hidden(self):
        """Same bar confident_match() uses for the single-item screen: a
        lone candidate needs at least two shared words."""
        requests, _ = quoting.find_free_text_requests(
            "Locker: 5", [quoting.RateItem(code="Z", description="Locker")])
        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0].match_confident)


class AiMatchBuildsThePromptAndReadsBackOnlyRealCatalogueCodes(unittest.TestCase):
    """item 56 (4 Nov 2026): the owner's own words, asked for in so many
    words -- "replace this with the AI as i want this accurate... its ok
    if the token usage is more but the answer should be accurate... no
    ask AI buttons needed." addons/inquiry/ai_match.py is the module this
    built; these are its pure functions, no network call."""

    def test_the_prompt_carries_the_whole_catalogue_and_the_whole_inquiry(self):
        prompt = ai_match.build_prompt(_REAL_MULTI_ITEM_MAIL, LAB_ITEMS)
        for item in LAB_ITEMS:
            self.assertIn(item.code, prompt)
            self.assertIn(item.description, prompt)
        self.assertIn("SS Locker (4 Comp)", prompt)
        self.assertIn("SS Cross Over Bench Pigeon Box Type", prompt)

    def test_a_real_catalogue_code_becomes_a_request_with_the_local_item(self):
        reply = ('{"items": [{"requested": "SS Locker (4 Comp)", '
                '"quantity": 10, "code": "KJP 8", "confidence": "high"}]}')
        requests, unmatched = ai_match.parse_response(reply, LAB_ITEMS)
        self.assertEqual(unmatched, [])
        self.assertEqual(len(requests), 1)
        self.assertIs(requests[0].item, LAB_ITEMS[2])   # the real local RateItem
        self.assertEqual(requests[0].quantity, Decimal(10))

    def test_every_ai_matched_row_still_needs_checking_regardless_of_its_own_confidence(self):
        """"we still have to keep check this" -- the owner's own words.
        "confidence": "high" from the model itself must never skip the
        review flag -- match_confident is always False for an AI match."""
        reply = ('{"items": [{"requested": "SS Locker (4 Comp)", '
                '"quantity": 10, "code": "KJP 8", "confidence": "high"}]}')
        requests, _ = ai_match.parse_response(reply, LAB_ITEMS)
        self.assertFalse(requests[0].match_confident)

    def test_a_code_the_catalogue_does_not_actually_have_is_never_priced(self):
        """A hallucinated or simply wrong code must never become a real
        Request -- core.boq_price's own rule, applied here: no number of
        record comes from the AI. Only a code genuinely on the local rate
        list can ever become a priced line."""
        reply = ('{"items": [{"requested": "Something made up", '
                '"quantity": 3, "code": "KJP 999", "confidence": "high"}]}')
        requests, unmatched = ai_match.parse_response(reply, LAB_ITEMS)
        self.assertEqual(requests, [])
        self.assertEqual(unmatched, ["Something made up"])

    def test_code_null_is_an_honest_dont_know_not_dropped(self):
        reply = ('{"items": [{"requested": "A bespoke part not on the '
                'list", "quantity": 1, "code": null, "confidence": "low"}]}')
        requests, unmatched = ai_match.parse_response(reply, LAB_ITEMS)
        self.assertEqual(requests, [])
        self.assertEqual(unmatched, ["A bespoke part not on the list"])

    def test_junk_back_from_the_model_parses_to_nothing_not_a_crash(self):
        requests, unmatched = ai_match.parse_response(
            "I'm sorry, I can't help with that.", LAB_ITEMS)
        self.assertEqual(requests, [])
        self.assertEqual(unmatched, [])

    def test_a_markdown_fenced_reply_still_parses(self):
        reply = ('```json\n{"items": [{"requested": "SS Locker (4 Comp)", '
                '"quantity": 10, "code": "KJP 8", "confidence": "high"}]}\n```')
        requests, _ = ai_match.parse_response(reply, LAB_ITEMS)
        self.assertEqual(len(requests), 1)


class TheQuotationWindow(unittest.TestCase):
    """The same rule, where the owner actually sees it."""

    def setUp(self):
        from addons.inquiry import dialog as UI
        self.UI = UI
        self.folder = tempfile.mkdtemp()
        self.cfg = {"api_key": "", "inquiry": {
            "folder": self.folder, "company": "Acme",
            "terms": {"gst_percent": 18, "validity_days": 15,
                      "payment": "", "delivery": ""},
            "knowledge": {}, "local_only": True}}
        self.inquiry = os.path.join(self.folder, "inquiries", "INQ-26-27-0008")
        os.makedirs(self.inquiry)
        self.row = register.blank_row()
        self.row.update({"Inquiry no": "INQ/26-27/0008", "Status": register.NEW,
                         "Email": "buyer@kj.in", "Folder": self.inquiry,
                         "Product asked": "this product, 10 nos"})
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.parent = UI.InquiryDialog(self.cfg)
        self.parent._refresh_register()

    def _window(self):
        return self.UI.QuotationDialog(self.cfg, self.parent._register_rows[0],
                                       LOCKERS, self.parent)

    def test_the_real_case_asks_the_owner_to_check(self):
        window = self._window()
        self.assertFalse(window._confident)

    def test_the_picture_text_is_matched_too(self):
        """"this product" in the mail, "SS Locker (8 Comp)" in the photo:
        one request, and the photo is what names the row."""
        ocr.remember(self.inquiry, "[IMG_2041.jpeg]\nSS Locker (8 Comp)\nKJ Pharmatech\n")
        window = self._window()
        self.assertEqual(window.matches[0].item.code, "KJP 8")

    def test_the_file_name_line_of_the_picture_text_is_not_matched(self):
        ocr.remember(self.inquiry, "[Locker-10-comp.jpeg]\nSS Locker (8 Comp)\n")
        window = self._window()
        self.assertEqual(window.matches[0].item.code, "KJP 8")


class TheQuotationWindowSplitsARealMultiItemMailIntoLines(unittest.TestCase):
    """item 55 (4 Nov 2026): the real bug, reproduced end to end through
    the actual screen a person opens -- not just the matching functions
    in isolation above. The same real 8-item inquiry, no catalogue code
    anywhere, used to come through this window as ONE line, qty 1."""

    def setUp(self):
        from addons.inquiry import dialog as UI
        self.UI = UI
        self.folder = tempfile.mkdtemp()
        self.cfg = {"api_key": "", "inquiry": {
            "folder": self.folder, "company": "Acme",
            "terms": {"gst_percent": 18, "validity_days": 15,
                      "payment": "", "delivery": ""},
            "knowledge": {}, "local_only": True}}
        self.inquiry = os.path.join(self.folder, "inquiries", "INQ-26-27-0006")
        os.makedirs(self.inquiry)
        self.row = register.blank_row()
        self.row.update({
            "Inquiry no": "INQ/26-27/0006", "Status": register.NEW,
            "Email": "shlok@kj.in", "Folder": self.inquiry,
            # The whole point of item 55's prompt fix (mailflow.py) --
            # "Product asked" now carries the full itemised list rather
            # than a 15-word summary. Set directly here since this test
            # is about the quotation screen, not the extraction call.
            "Product asked": _REAL_MULTI_ITEM_MAIL})
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.parent = UI.InquiryDialog(self.cfg)
        self.parent._refresh_register()

    def _window(self):
        return self.UI.QuotationDialog(self.cfg, self.parent._register_rows[0],
                                       LAB_ITEMS, self.parent)

    def test_all_eight_items_land_as_eight_lines_not_one(self):
        window = self._window()
        self.assertTrue(window._lines_mode)
        self.assertEqual(len(window.requests), 8)
        self.assertEqual(window.lines_table.rowCount(), 8)

    def test_the_lines_table_is_actually_visible(self):
        window = self._window()
        self.assertTrue(window.lines_table.isVisible()
                        or window.lines_table.isVisibleTo(window))

    def test_a_short_single_item_mail_still_uses_the_single_item_form(self):
        """The fix must not turn every inquiry into a lines table -- a mail
        that really does ask for one thing stays the one-item screen."""
        self.row["Product asked"] = "SS Locker 8 Comp, 5 nos"
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.parent._refresh_register()
        window = self._window()
        self.assertFalse(window._lines_mode)


class TheQuotationWindowAsksAiWhenAKeyIsConfigured(unittest.TestCase):
    """item 56 (4 Nov 2026): the owner's own words -- "replace this with
    the AI... no ask AI buttons needed." A real OpenRouter key means the
    screen starts AIMatchWorker itself, no button, the moment it opens
    on a fewer-than-two-code inquiry; AIMatchWorker itself is mocked so
    no real network call is ever made in a test (CLAUDE.md)."""

    def setUp(self):
        from addons.inquiry import dialog as UI
        self.UI = UI
        self.folder = tempfile.mkdtemp()
        self.cfg = {"api_key": "", "openrouter_api_key": "sk-or-test",
                   "inquiry": {
                       "folder": self.folder, "company": "Acme",
                       "terms": {"gst_percent": 18, "validity_days": 15,
                                "payment": "", "delivery": ""},
                       "knowledge": {}, "local_only": True}}
        self.inquiry = os.path.join(self.folder, "inquiries", "INQ-26-27-0006")
        os.makedirs(self.inquiry)
        self.row = register.blank_row()
        self.row.update({
            "Inquiry no": "INQ/26-27/0006", "Status": register.NEW,
            "Email": "shlok@kj.in", "Folder": self.inquiry,
            "Product asked": _REAL_MULTI_ITEM_MAIL})
        register.save([self.row], mailflow.Paths(self.folder).register_csv)
        self.parent = UI.InquiryDialog(self.cfg)
        self.parent._refresh_register()
        self.fake_worker = mock.Mock()

    def _window(self):
        with mock.patch.object(Q, "AIMatchWorker", return_value=self.fake_worker) as cls:
            self.worker_cls = cls
            return self.UI.QuotationDialog(
                self.cfg, self.parent._register_rows[0], LAB_ITEMS, self.parent)

    def test_a_key_starts_the_ai_worker_not_the_local_matcher_directly(self):
        window = self._window()
        self.worker_cls.assert_called_once()
        self.fake_worker.start.assert_called_once()
        self.assertTrue(window._ai_pending)
        self.assertEqual(window.lines_table.rowCount(), 0)
        self.assertTrue(window.ai_loading_label.isVisible()
                        or window.ai_loading_label.isVisibleTo(window))

    def test_the_worker_is_given_the_real_api_key_text_and_rate_list(self):
        self._window()
        args = self.worker_cls.call_args[0]
        self.assertEqual(args[0], "sk-or-test")
        self.assertIn("SS Locker (4 Comp)", args[1])
        self.assertEqual(args[2], LAB_ITEMS)

    def test_ai_returning_eight_matches_fills_the_lines_table(self):
        window = self._window()
        requests = [quoting.Request(it, Decimal(1), evidence="x",
                                    match_confident=False)
                   for it in (LAB_ITEMS * 2)[:8]]
        done_cb = self.fake_worker.done.connect.call_args[0][0]
        done_cb(requests, [])
        self.assertFalse(window._ai_pending)
        self.assertTrue(window._lines_from_ai)
        self.assertEqual(len(window.requests), 8)
        self.assertEqual(window.lines_table.rowCount(), 8)
        self.assertFalse(window.single_form.isVisible())

    def test_ai_returning_too_few_lines_falls_back_to_local_matching(self):
        window = self._window()
        done_cb = self.fake_worker.done.connect.call_args[0][0]
        done_cb([quoting.Request(LAB_ITEMS[0], Decimal(1))], [])
        self.assertFalse(window._ai_pending)
        self.assertTrue(window._lines_from_free_text)
        self.assertEqual(len(window.requests), 8)   # the real mail, matched locally

    def test_the_ai_call_failing_falls_back_to_local_matching_not_a_dead_end(self):
        window = self._window()
        failed_cb = self.fake_worker.failed.connect.call_args[0][0]
        with mock.patch.object(Q.QMessageBox, "warning"):
            failed_cb("No OpenRouter key set.")
        self.assertFalse(window._ai_pending)
        self.assertTrue(window._lines_from_free_text)
        self.assertEqual(len(window.requests), 8)


if __name__ == "__main__":
    unittest.main()
