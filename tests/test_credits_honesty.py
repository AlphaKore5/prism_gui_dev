"""Owner's Studio run, 26 Nov 2026: say a refusal once, and say what was charged.

1. 'Not enough AI credits ...' was shown on its own and again inside 'The design
   step did not return a design: <same text>' (plus a would-not-parse file).
2. The server charged 255.378 credits twice for two empty (finish=length)
   answers while the app said 'Nothing was charged' and asked again.
"""
from __future__ import annotations

import os
import sys
from unittest import mock

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import core_bridge  # noqa: F401,E402
from core import ai_client, automation, server_session as SS  # noqa: E402

_REFUSAL = ("Not enough AI credits for that: it needs 337.6 and you have 256.4. "
            "Ask Alphakore to top up and it will run straight away. Nothing was charged.")


def _studio(design):
    from core import reel_web
    with mock.patch.object(reel_web, "available", return_value=(True, "")), \
            mock.patch.object(automation, "_keep_failed_spec", return_value="/k/x.txt") as keep:
        out = automation._run_studio(["Prism AI drew 5 image(s)."], [], {}, design=design)
    return out, keep


def test_an_ai_refusal_on_the_design_step_is_not_repeated_or_called_a_bad_design():
    (path, why), keep = _studio({"texts": [], "error": _REFUSAL, "refused": True})
    assert path == ""
    assert "337.6" not in why and "credits" not in why
    assert "did not return a design" not in why
    assert "saved to" not in why
    keep.assert_not_called()


def test_a_non_ai_design_failure_keeps_its_wording():
    (path, why), keep = _studio({"texts": [], "error": "boom", "refused": False})
    assert why.startswith("The design step did not return a design: boom")
    keep.assert_called_once()


def _send(data, **kw):
    return mock.patch.object(ai_client, "_post", return_value=data)


def _chat():
    return ai_client.chat("code", "design it")


def test_an_empty_but_charged_answer_states_the_real_charge():
    data = {"text": "", "finish": "length", "charged_mc": 255378, "balance_mc": 1000}
    with _send(data), pytest.raises(ai_client.AiError) as ei:
        _chat()
    e = ei.value
    assert "Nothing was charged" not in str(e)
    assert "255.4" in str(e)
    assert e.detail["charged_mc"] == 255378 and e.detail["balance_mc"] == 1000


def test_an_empty_uncharged_answer_still_says_nothing_was_charged():
    with _send({"text": "", "charged_mc": 0}), pytest.raises(ai_client.AiError) as ei:
        _chat()
    assert "Nothing was charged" in str(ei.value)


def test_a_charged_empty_answer_is_never_sent_again():
    s = SS.ServerSession("studio")
    s.begin("design", "Prism AI", "code")
    err = ai_client.AiError("EMPTY", "empty, charged", {"charged_mc": 255378})
    with mock.patch.object(ai_client, "chat", side_effect=err) as chat:
        with pytest.raises(ai_client.AiError):
            s.send("design the reel")
    assert chat.call_count == 1


def test_a_session_remembers_that_the_error_was_an_ai_error():
    s = SS.ServerSession("studio")
    s.begin("design", "Prism AI", "code")
    with mock.patch.object(ai_client, "chat",
                           side_effect=ai_client.AiError("NO_CREDITS", _REFUSAL)):
        with pytest.raises(ai_client.AiError):
            s.send("x")
    assert s.last_error_code == "NO_CREDITS"
    s.begin("design", "Prism AI", "code")
    assert s.last_error_code == ""


def test_the_charged_empty_answer_reaches_the_person_with_its_charge():
    import friendly
    with _send({"text": "", "finish": "length", "charged_mc": 255378}), \
            pytest.raises(ai_client.AiError) as ei:
        _chat()
    p = friendly.explain(str(ei.value))
    text = friendly.as_text(p)
    assert "255.4 credits" in text
    assert "Nothing was charged" not in text


def test_a_charged_length_cutoff_is_one_transport_call_end_to_end():
    """Through ServerSession.send and the real ai_client.chat: the first call is
    an empty finish=length answer that cost credits, and the second (retry)
    model is never asked."""
    s = SS.ServerSession("studio")
    s.begin("design", "Prism AI", "code")
    data = {"text": "", "finish": "length", "charged_mc": 255378, "balance_mc": 1000}
    with mock.patch.object(ai_client, "_post", return_value=data) as post:
        with pytest.raises(ai_client.AiError) as ei:
            s.send("design the reel")
    assert post.call_count == 1
    assert "255.4" in str(ei.value) and s.last_error_code == "EMPTY"


def test_an_uncharged_empty_answer_is_still_retried_once_on_the_other_model():
    s = SS.ServerSession("studio")
    s.begin("design", "Prism AI", "code")
    empty = {"text": "", "finish": "length", "charged_mc": 0}
    good = {"text": "a design", "finish": "stop", "charged_mc": 5, "balance_mc": 1}
    with mock.patch.object(ai_client, "_post", side_effect=[empty, good]) as post:
        assert s.send("design the reel") == "a design"
    assert post.call_count == 2
