"""core/openrouter.py -- the BOQ add-on's "Prism Agent" write-up path
(item 30b): a plain API call through OpenRouter, mirroring router.py's own
groq_chat()/verify_key() shape. Nothing here reaches the real OpenRouter API
-- requests.post/get are replaced with a scripted response.
"""
from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "prism_terminal"))

from core import openrouter as OR                                  # noqa: E402


def _resp(status, body):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = body
    r.headers = {}
    return r


class OpenrouterChatReturnsTheAnswer(unittest.TestCase):
    def test_a_200_with_choices_returns_the_text(self):
        with mock.patch.object(OR.requests, "post", return_value=_resp(
                200, {"choices": [{"message": {"content": "the BOQ text"}}]})):
            out = OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "write it")
        self.assertEqual(out, "the BOQ text")

    def test_no_api_key_raises_without_a_network_call(self):
        with mock.patch.object(OR.requests, "post") as post:
            with self.assertRaises(RuntimeError):
                OR.openrouter_chat("", "anthropic/claude-sonnet-5.5", "write it")
            self.assertFalse(post.called)

    def test_401_raises_with_a_clear_message(self):
        with mock.patch.object(OR.requests, "post", return_value=_resp(401, {})):
            with self.assertRaises(RuntimeError) as cm:
                OR.openrouter_chat("sk-or-bad", "anthropic/claude-sonnet-5.5", "write it")
        self.assertIn("rejected", str(cm.exception))

    def test_429_retries_once_then_raises_if_still_limited(self):
        with mock.patch.object(OR.requests, "post", return_value=_resp(429, {})), \
                mock.patch.object(OR.time, "sleep"):
            with self.assertRaises(RuntimeError) as cm:
                OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "write it", retries=1)
        self.assertIn("rate-limiting", str(cm.exception))

    def test_a_retry_status_then_a_good_reply_succeeds(self):
        calls = [_resp(503, {}), _resp(200, {"choices": [{"message": {"content": "ok"}}]})]
        with mock.patch.object(OR.requests, "post", side_effect=calls), \
                mock.patch.object(OR.time, "sleep"):
            out = OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "write it", retries=1)
        self.assertEqual(out, "ok")

    def test_a_network_error_raises_a_plain_message(self):
        import requests as real_requests
        with mock.patch.object(OR.requests, "post",
                               side_effect=real_requests.ConnectionError("down")):
            with self.assertRaises(RuntimeError) as cm:
                OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "write it")
        self.assertIn("internet connection", str(cm.exception))


class AttachmentsBuildOpenroutersMultimodalContentShape(unittest.TestCase):
    """item 32: a rendered drawing (cad_render.prepare_for_ai()'s own
    shape) going along with the text prompt, never instead of it."""

    def test_no_attachments_sends_a_plain_string_unchanged(self):
        """Every call before item 32 sent `content` as a bare string --
        this must still be true when nothing is attached, so a payload
        inspection tool or a provider that chokes on an array-of-one
        sees exactly what it always has."""
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _resp(200, {"choices": [{"message": {"content": "ok"}}]})

        with mock.patch.object(OR.requests, "post", side_effect=fake_post):
            OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "write it")
        self.assertEqual(captured["json"]["messages"][0]["content"], "write it")

    def test_an_image_attachment_becomes_an_image_url_block(self):
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _resp(200, {"choices": [{"message": {"content": "ok"}}]})

        att = [{"kind": "image", "mime": "image/png", "b64": "QQ==", "name": "x.png"}]
        with mock.patch.object(OR.requests, "post", side_effect=fake_post):
            OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "check it",
                               attachments=att)
        content = captured["json"]["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "check it"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64,QQ==")

    def test_a_pdf_attachment_becomes_a_file_block_not_an_image(self):
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured["json"] = json
            return _resp(200, {"choices": [{"message": {"content": "ok"}}]})

        att = [{"kind": "pdf", "mime": "application/pdf", "b64": "QQ==", "name": "x.pdf"}]
        with mock.patch.object(OR.requests, "post", side_effect=fake_post):
            OR.openrouter_chat("sk-or-x", "anthropic/claude-sonnet-5.5", "check it",
                               attachments=att)
        block = captured["json"]["messages"][0]["content"][1]
        self.assertEqual(block["type"], "file")
        self.assertEqual(block["file"]["filename"], "x.pdf")
        self.assertEqual(block["file"]["file_data"], "data:application/pdf;base64,QQ==")

    def test_an_empty_attachments_list_is_the_same_as_none(self):
        self.assertEqual(OR._content_blocks("hi", []), "hi")
        self.assertEqual(OR._content_blocks("hi", None), "hi")


class VerifyKeyReturnsEmptyOnlyWhenItWorks(unittest.TestCase):
    def test_empty_key_is_rejected_without_a_network_call(self):
        with mock.patch.object(OR.requests, "get") as get:
            self.assertEqual(OR.verify_key(""), "No key entered.")
            self.assertFalse(get.called)

    def test_a_key_with_the_wrong_prefix_is_rejected_without_a_network_call(self):
        with mock.patch.object(OR.requests, "get") as get:
            out = OR.verify_key("gsk_not_an_openrouter_key")
        self.assertIn("sk-or-", out)
        self.assertFalse(get.called)

    def test_a_good_key_returns_empty_string(self):
        with mock.patch.object(OR.requests, "get", return_value=_resp(200, {"data": []})):
            self.assertEqual(OR.verify_key("sk-or-good"), "")

    def test_a_401_names_the_real_problem(self):
        with mock.patch.object(OR.requests, "get", return_value=_resp(401, {})):
            out = OR.verify_key("sk-or-bad")
        self.assertIn("rejected", out)

    def test_an_unavailable_model_is_named_even_though_the_key_works(self):
        with mock.patch.object(OR.requests, "get", return_value=_resp(
                200, {"data": [{"id": "some/other-model"}]})):
            out = OR.verify_key("sk-or-good", model="anthropic/claude-sonnet-5.5")
        self.assertIn("claude-sonnet-5.5", out)


if __name__ == "__main__":
    unittest.main()
