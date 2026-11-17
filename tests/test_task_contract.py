"""A step is held to what it OWES, not just to having said something.

Every case here is a failure from the owner's own run history (11 Sep 2026
audit, prism+gui/artifacts/prompt-pipeline-and-deliverables-2026-09-11.html),
or one the review of the first version of this change found:

- "make DOCX document for this product" ended with 9,521 characters of Word
  text in a chat window and no file, because the planner had written
  "Non-Goals: Do NOT generate an actual .docx file" into the prompt;
- the same week Claude DID build the DOCX, and Prism dropped it — the card
  said "Document·DOCX" with no extension, and the download click landed on
  the wrapper around the button;
- an image step replied "I can't complete the requested PNG generation" and
  was recorded as a completed step;
- the first version of the request matcher read "excellent" as a request
  for Excel and "the attached PDF" as a request for a PDF, and made every
  writing step in a run a file step.

Nothing here opens a browser.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (ROOT, os.path.join(ROOT, "prism_terminal")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core import automation as AU     # noqa: E402
from core import contract as C        # noqa: E402
from core import router as R          # noqa: E402


class KindsComeFromTheStageThePlanAndTheTool(unittest.TestCase):

    def test_each_stage_has_a_default(self):
        self.assertEqual("text", C.for_stage("brains"))
        self.assertEqual("image", C.for_stage("visual"))
        self.assertEqual("image", C.for_stage("artwork"))
        self.assertEqual("video", C.for_stage("media"))
        self.assertEqual("links", C.for_stage("leads"))
        self.assertEqual("file", C.for_stage("presentation"))

    def test_the_planner_may_choose_but_not_invent(self):
        self.assertEqual("file", C.for_stage("research", "file"))
        self.assertEqual("text", C.for_stage("research", "a spreadsheet please"))

    def test_the_planner_cannot_turn_a_picture_step_into_a_text_step(self):
        """The planner copies its example; "text" on "Make the images" would
        switch off the image line, the image check and the end-of-run check."""
        self.assertEqual("image", C.for_stage("visual", "text"))
        self.assertEqual("video", C.for_stage("media", "text"))
        self.assertEqual("links", C.for_stage("leads", "text"))

    def test_a_tool_is_not_held_to_what_it_cannot_make(self):
        self.assertEqual("text", C.for_stage("content", "file", {"produces": ("text",)}))
        self.assertEqual("file", C.for_stage("content", "file", {"produces": ("text", "file")}))
        # Apollo answers with contacts whatever the plan said.
        self.assertEqual("links", C.for_stage("leads", "file", {"produces": ("links",)}))


class ReadingTheRequest(unittest.TestCase):
    CASES = {
        "make DOCX document for this product": (True, ".docx"),
        "make a pretty good document use colors from it and give me in .docx": (True, ".docx"),
        "give me this in PDF": (True, ".pdf"),
        "export as csv": (True, ".csv"),
        "make an excel sheet of the leads": (True, ".xlsx"),
        "create a pdf report on EV charging": (True, ".pdf"),
        "put it into a word document": (True, ".docx"),
        "write an excellent blog post": (False, ""),
        "summarise the attached PDF": (False, ""),
        "summarise the attached PDF file": (False, ""),
        "analyse this spreadsheet and tell me the top customers": (False, ""),
        "write a summary of the pdf": (False, ""),
        "In a word, the launch went well; write a post about it": (False, ""),
        "make them excel at customer service": (False, ""),
        "create a password reset email": (False, ""),
        "make me a document about EV charging": (False, ""),
    }

    def test_a_request_is_told_apart_from_a_mention(self):
        for query, (wants, ext) in self.CASES.items():
            with self.subTest(query=query):
                self.assertEqual(wants, C.wants_file(query))
                self.assertEqual(ext, C.wanted_ext(query))


class TheRequestedFileFallsToOneStep(unittest.TestCase):
    ASK = "make DOCX document for this product"

    def test_the_last_step_that_writes_owes_it(self):
        entries = [("research", "text", {"produces": ("text",)}),
                   ("brains", "text", {}), ("content", "text", {})]
        self.assertEqual(2, C.file_step_index(entries, self.ASK))

    def test_a_step_whose_tool_cannot_return_a_file_is_passed_over(self):
        entries = [("brains", "text", {}), ("content", "text", {"produces": ("text",)})]
        self.assertEqual(0, C.file_step_index(entries, self.ASK))

    def test_a_plan_that_already_has_a_file_step_needs_nothing(self):
        entries = [("content", "text", {}), ("presentation", "file", {})]
        self.assertEqual(-1, C.file_step_index(entries, self.ASK))

    def test_a_step_a_program_reads_is_never_chosen(self):
        entries = [("brains", "text", {}), ("content", "data", {})]
        self.assertEqual(0, C.file_step_index(entries, self.ASK))

    def test_no_request_no_file_step(self):
        self.assertEqual(-1, C.file_step_index([("content", "text", {})], "write a post"))


class OneLineSaysWhatToHandBack(unittest.TestCase):

    def test_a_file_step_names_the_tool_and_the_format_asked_for(self):
        line = C.deliverable_line("file", "Claude", {}, ".docx")
        self.assertIn(".docx", line)
        self.assertIn("Claude", line)
        self.assertIn("download", line)

    def test_no_format_is_invented_when_none_was_named(self):
        """Gamma asked for "a file" builds a deck; it must not be told .docx."""
        self.assertNotIn(".docx", C.deliverable_line("file", "Gamma.app", {}, ""))
        self.assertNotIn(".docx", C.reask("file", ""))

    def test_a_file_retry_carries_the_original_task_for_a_recovered_chat(self):
        retry = C.reask("file", ".docx", "Create a product brief for the valve range")
        self.assertIn("Original task: Create a product brief", retry)
        self.assertIn(".docx", retry)

    def test_a_file_retry_prefers_the_write_steps_actual_prompt(self):
        retry = C.reask(
            "file", ".docx", "Make a catalogue",
            task="Write a customer-ready product catalogue for the valve range")
        self.assertIn("Original task: Write a customer-ready product catalogue", retry)
        self.assertNotIn("Original task: Make a catalogue", retry)

    def test_the_tools_own_hint_rides_along(self):
        line = C.deliverable_line("file", "Claude", {"file_hint": "Use your tools."})
        self.assertTrue(line.endswith("Use your tools."))

    def test_an_image_step_asks_for_the_picture_not_a_description(self):
        self.assertIn("picture itself", C.deliverable_line("image"))

    def test_a_text_step_adds_nothing(self):
        self.assertEqual("", C.deliverable_line("text", "ChatGPT"))

    def test_it_is_only_ever_one_line(self):
        for kind in C.KINDS:
            self.assertNotIn("\n", C.deliverable_line(kind, "X", {}))


class WhatIsCheckedAfterwards(unittest.TestCase):

    def test_chat_text_is_not_a_file(self):
        self.assertTrue(C.missing("file", texts=["Here is your document…"], files=0))
        self.assertEqual("", C.missing("file", texts=[], files=1))

    def test_an_image_step_with_no_picture_is_short(self):
        self.assertEqual("no picture was generated", C.missing(
            "image", texts=["I can't generate the requested asset"], images=0))

    def test_text_needs_words(self):
        self.assertTrue(C.missing("text", texts=["   "]))
        self.assertEqual("", C.missing("text", texts=["an answer"]))

    def test_the_run_names_what_it_did_not_produce(self):
        owed = C.promised([("brains", "text"), ("content", "file"),
                           ("visual", "image"), ("media", "video")])
        self.assertEqual(["file", "image", "video"], owed)
        self.assertEqual(["file", "video"], C.shortfall(owed, {"image": 3}))


class TheWordsAreNeverLost(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prism-contract-")

    def test_chat_text_becomes_a_word_document_with_real_headings(self):
        from docx import Document
        path, note = C.document_from_text(
            "# Lazycook\n\nIntro line.\n\n## Features\n- fast\n- cited",
            self.tmp, "Lazycook")
        self.assertTrue(path.endswith(".docx"))
        shapes = [(p.style.name, p.text) for p in Document(path).paragraphs]
        self.assertIn(("Heading 1", "Lazycook"), shapes)
        self.assertIn(("Heading 2", "Features"), shapes)
        self.assertIn(("List Bullet", "fast"), shapes)
        self.assertIn("Word document", note)

    def test_a_pdf_request_is_answered_honestly(self):
        # A real PDF now; the Word fallback (said out loud) only when Qt is missing.
        path, note = C.document_from_text("body", self.tmp, "x", ".pdf")
        self.assertTrue(path.endswith(".pdf"))
        self.assertEqual(open(path, "rb").read(5), b"%PDF-")
        with mock.patch.object(C, "_write_pdf", side_effect=ImportError):
            path, note = C.document_from_text("body", self.tmp, "x", ".pdf")
        self.assertTrue(path.endswith(".docx"))
        self.assertIn("PDF", note)

    def test_a_spreadsheet_is_not_faked_from_prose(self):
        self.assertEqual(("", ""), C.document_from_text("a | b", self.tmp, "x", ".xlsx"))

    def test_nothing_to_write_is_not_an_error(self):
        self.assertEqual(("", ""), C.document_from_text("   ", self.tmp, "x"))


class ADocumentCardIsAFile(unittest.TestCase):
    #: Verbatim from the saved reply of the 2026-09-08 15:07 run.
    CARD = "Lazycook design brief\nDocument·DOCX \nDownload"

    def test_claudes_card_names_its_file(self):
        self.assertEqual("Lazycook design brief.docx", AU._card_filename(self.CARD))
        self.assertEqual("Lazycook design brief.docx", AU._filename_in_text(self.CARD))

    def test_a_bare_type_word_in_prose_is_not_a_file(self):
        self.assertEqual("", AU._card_filename("Here is the summary\nPDF\nthanks"))

    def test_chatgpts_chip_still_works(self):
        self.assertEqual("report.docx", AU._filename_in_text("report.docx"))


class _El:
    """Just enough of a Selenium element for _innermost_control."""

    def __init__(self, tag, text, role="", shown=True):
        self.tag_name, self.text = tag, text
        self._role, self._shown = role, shown
        self.clicked = False

    def is_displayed(self):
        return self._shown

    def is_enabled(self):
        return True

    def get_attribute(self, name):
        return self._role if name == "role" else ""

    def click(self):
        self.clicked = True


class TheClickLandsOnTheControl(unittest.TestCase):

    def test_the_button_wins_over_the_card_around_it(self):
        column = _El("div", "…the whole conversation… Download")
        card = _El("div", "Lazycook design brief Document·DOCX Download")
        button = _El("button", "Download")
        # Document order, outermost first — the element the old code clicked.
        self.assertIs(button, AU._innermost_control([column, card, button]))

    def test_a_role_button_counts_as_a_control(self):
        span = _El("span", "Download", role="button")
        self.assertIs(span, AU._innermost_control([_El("div", "x Download y"), span]))

    def test_hidden_matches_are_ignored(self):
        self.assertIsNone(AU._innermost_control([_El("button", "Download", shown=False)]))

    def test_click_by_text_clicks_the_innermost(self):
        card, button = _El("div", "card Download"), _El("button", "Download")
        driver = mock.Mock()
        driver.find_elements.return_value = [card, button]
        self.assertTrue(AU._click_by_text(driver, ["download"], timeout=0))
        self.assertTrue(button.clicked)
        self.assertFalse(card.clicked)

    def test_current_chatgpt_file_card_is_clicked_before_old_page_controls(self):
        """ChatGPT's current card is filename + ``Document`` plus an
        icon-only ``Download file`` button.  The button belongs to the last
        assistant turn, so it must win before the page-wide fallback sees an
        older artifact in the same conversation."""
        driver = mock.Mock()
        driver.execute_script.return_value = True
        self.assertTrue(AU._click_download_control(driver, {}))
        driver.find_elements.assert_not_called()


class AStepIsHeldToItsContract(unittest.TestCase):
    """_meet_contract with no browser: the half that must work regardless."""

    def test_a_file_step_that_answered_in_prose_still_leaves_a_file(self):
        text = "# Lazycook — Product Document\n\nExecutive summary…"
        got = AU._meet_contract(None, {}, "content", "file", [text], [],
                                query="make DOCX document for this product")
        self.assertEqual(1, len(got["files"]))
        self.assertTrue(os.path.isfile(got["files"][0]["path"]))
        self.assertTrue(got["files"][0]["path"].endswith(".docx"))
        self.assertIn("Word document", got["note"])
        self.assertEqual("", got["missing"])

    def test_a_clarifying_retry_never_replaces_the_actual_document_text(self):
        """A real ChatGPT retry said there was no earlier conversation.

        That reply is longer than a short report introduction, so the old
        longest-string fallback wrote the clarification into the DOCX instead
        of the report the first turn had already supplied.
        """
        original = "# Product brief\n\nThe actual product summary belongs here."
        clarification = (
            "I don't see anything earlier in this conversation to turn into "
            "a file — this looks like the start of our chat here. Please "
            "paste the content you want saved.")
        driver = mock.Mock()
        cfg = {"textarea_selector": "textarea"}
        with mock.patch.object(AU, "_reask", return_value=[clarification]), \
             mock.patch.object(AU, "_wait_for_files", return_value=0), \
             mock.patch.object(AU, "_harvest_files", return_value=[]):
            got = AU._meet_contract(
                driver, cfg, "content", "file", [original], [],
                query="make DOCX document for this product")
        from docx import Document
        body = "\n".join(p.text for p in Document(got["files"][0]["path"]).paragraphs)
        self.assertIn("actual product summary", body)
        self.assertNotIn("don't see anything earlier", body)

    def test_a_spreadsheet_request_is_reported_not_faked(self):
        got = AU._meet_contract(None, {}, "content", "file", ["Company | Email"], [],
                                query="make an excel sheet of the leads")
        self.assertEqual([], got["files"])
        self.assertTrue(got["missing"])

    def test_a_file_step_that_has_its_file_is_left_alone(self):
        got = AU._meet_contract(None, {}, "content", "file", ["done"],
                                [{"path": "/x.docx", "kind": "document"}])
        self.assertEqual({"files": [], "texts": [], "note": "", "missing": ""}, got)

    def test_an_image_step_with_no_picture_says_so(self):
        got = AU._meet_contract(None, {}, "visual", "image",
                                ["I can't generate that"], [])
        self.assertEqual("no picture was generated", got["missing"])
        self.assertEqual([], got["files"])

    def test_stop_means_no_second_ask(self):
        with mock.patch.object(AU, "_reask", side_effect=AssertionError("asked")):
            got = AU._meet_contract(mock.Mock(), {"textarea_selector": "textarea"},
                                    "visual", "image", ["words"], [],
                                    should_stop=lambda: True)
        self.assertEqual("no picture was generated", got["missing"])


class TheReelGetsItsPicturesByDefault(unittest.TestCase):

    def test_the_default_is_pictures(self):
        self.assertTrue(AU._reel_imagery_on({}, {}))

    def test_type_only_turns_them_off(self):
        self.assertFalse(AU._reel_imagery_on({"_reel_imagery": False},
                                             {"reel_imagery": True}))

    def test_the_customers_own_setting_is_not_overridden(self):
        self.assertFalse(AU._reel_imagery_on({"_reel_imagery": True},
                                             {"reel_imagery": False}))


class PrismsOwnEchoIsRecognised(unittest.TestCase):

    def test_the_first_message_is_recognised_by_its_header(self):
        self.assertTrue(AU._is_prompt_echo(
            "Prism · EV reel · Research\n\nWHAT THE PERSON ACTUALLY ASKED FOR"))

    def test_a_reply_that_quotes_one_heading_is_kept(self):
        self.assertFalse(AU._is_prompt_echo(
            "HANDOFF FOR CHATGPT\nWhat the person actually asked for — in their "
            "own words: a reel about EV charging in India."))

    def test_the_body_of_the_message_is_recognised(self):
        self.assertTrue(AU._is_prompt_echo(
            "make a reel about EV charging\n\nFrom the earlier step (Look "
            "things up):\n- one\n\nFor this step: write the script.\n\n"
            "At the end add a section headed 'HANDOFF FOR CLAUDE': at most "
            "4 lines."))


class ThePlannerWritesBriefsNotSpecifications(unittest.TestCase):
    AGENTS = {"research": "Perplexity", "brains": "ChatGPT",
              "content": "ChatGPT", "visual": "ChatGPT",
              "media": "Prism Studio", "presentation": "Claude"}

    def prompt(self):
        with mock.patch.object(R, "_tool_notes", return_value=""):
            return R.build_prompt("make a reel about EV charging", "", self.AGENTS)

    def test_every_step_declares_what_it_produces(self):
        p = self.prompt()
        self.assertIn('"brains": { "needed": false, "kind": "text"', p)
        # The example shows each step's own kind, so a copied example keeps
        # the picture step a picture step.
        self.assertIn('"visual": { "needed": false, "kind": "image"', p)
        for kind in C.KINDS:
            self.assertIn(kind, p)

    def test_the_rules_that_bred_over_engineered_prompts_are_gone(self):
        p = self.prompt()
        for phrase in ("PROMPT CRAFT", "SCOPE LOCK", "QUALITY BAR",
                       "NON-GOALS:", "THE NOTES WIN", "Prefer ONE stage",
                       "HAND-OFF AWARENESS"):
            self.assertNotIn(phrase, p)

    def test_a_tool_carrying_several_steps_is_described_once(self):
        self.assertGreaterEqual(self.prompt().count("as described under BRAINS above"), 2)

    def test_only_the_notes_for_tools_in_this_plan_are_sent(self):
        notes = ("Perplexity:\nPros:\n1)good at web scraping\n\n"
                 "Lazycook:\nPros:\n1)deep knowledge\n\n"
                 "Claude:\nMy recommendation:\nbest for documents\n\n"
                 "== MULTI-FILE TASKS ==\n- ChatGPT analyses files first\n")
        with mock.patch.object(R, "_tool_notes", return_value=notes):
            got = R._notes_for({"research": "Perplexity", "content": "Claude"})
        self.assertIn("good at web scraping", got)
        self.assertIn("best for documents", got)
        self.assertIn("MULTI-FILE TASKS", got)
        self.assertNotIn("deep knowledge", got)


class DocumentsAreWritingJobs(unittest.TestCase):
    AGENTS = {"brains": "ChatGPT", "content": "ChatGPT", "development": "Claude"}

    def forced(self, query):
        return R.apply_make_guardrail(query, {}, self.AGENTS)

    def test_a_document_or_a_report_forces_the_writing_step(self):
        self.assertIn("content", self.forced("make me a document about EV charging"))
        self.assertIn("content", self.forced("write a report on EV trends"))

    def test_documentation_for_an_api_is_not_an_app_build(self):
        got = self.forced("make me documentation for this API")
        self.assertIn("content", got)
        self.assertNotIn("development", got)

    def test_building_an_api_still_is(self):
        self.assertIn("development", self.forced("build an api server for orders"))


if __name__ == "__main__":
    unittest.main()
