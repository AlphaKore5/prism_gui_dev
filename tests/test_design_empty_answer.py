"""A reel's design stage that comes back empty (owner's real run, 19 Nov 2026).

The 'code' role answered nothing twice after 78 s (nothing charged), the run
went on to film with no design, and the person read "No JSON found in the
agent's reply" — from the caption, not from anything near a design.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402  (puts prism_terminal/core on sys.path)
from core import ai_client, automation, server_session as SS  # noqa: E402


def _session(role):
    s = SS.ServerSession("studio")
    s.begin("design", "Prism AI", role)
    return s


def test_an_empty_design_answer_is_asked_once_more_of_another_model():
    calls = []

    def fake(role, prompt, **kw):
        calls.append(kw.get("model", ""))
        if len(calls) == 1:
            raise ai_client.AiError("EMPTY", "The AI sent back an empty answer.")
        return '{"scenes": [{"html": "<div>ok</div>"}]}'
    with mock.patch.object(ai_client, "chat", side_effect=fake):
        out = _session("code").send("design the reel")
    assert calls == ["", SS._RETRY_MODEL]
    assert "scenes" in out


def test_other_errors_are_not_retried():
    with mock.patch.object(ai_client, "chat",
                           side_effect=ai_client.AiError("NO_CREDITS", "No credits left.")) as chat:
        with pytest.raises(ai_client.AiError):
            _session("code").send("design the reel")
    assert chat.call_count == 1


def test_an_empty_writer_answer_is_retried_too():
    seq = [ai_client.AiError("EMPTY", "empty"), "Hello"]
    with mock.patch.object(ai_client, "chat", side_effect=seq) as chat:
        assert _session("writer").send("write it") == "Hello"
    assert chat.call_count == 2


def test_the_studio_names_the_closest_reason_not_no_json_found():
    """The three texts the real failed run handed the renderer: the images
    step's line, a script with scenes but no html, and a caption."""
    sources = ["Prism AI drew 5 image(s).",
               '```json\n{"scenes": [{"role": "hook", "seconds": 4.5, '
               '"kicker": "तुलसी विवाह", "headline": "शुभकामनाएँ"}]}\n```',
               "**तुलसी विवाह रील कैप्शन** 🌿 तुलसी विवाह की हार्दिक शुभकामनाएँ!"]
    from core import reel_web
    with mock.patch.object(reel_web, "available", return_value=(True, "")), \
            mock.patch.object(automation, "_keep_failed_spec", return_value=""):
        path, why = automation._run_studio(sources, [], {})
    assert path == ""
    assert "no markup" in why and "No JSON found" not in why
