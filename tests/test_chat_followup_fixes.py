"""GUI-side chat follow-up fixes (2026-11-26).

  1. A failed follow-up step must not re-show the earlier answer as the reply.
  2. A change request on a picture is redrawn through the picture step, not
     answered by the text writer.
  3. An image file shows a thumbnail on its card (a bad file does not break it).
  4. Cards for artwork/design the engine adds sit above the queued video card.

No event loop is run; workers and the engine are replaced by fakes.
"""
from __future__ import annotations

import base64
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import chatlog                                                      # noqa: E402
from test_chat_thread import (win, _window, ai, no_chrome, PNG)     # noqa: E402,F401
from widgets import chat_thread as T                                # noqa: E402
from widgets import output_panel as OP                              # noqa: E402
from widgets.file_card import FileCard                              # noqa: E402

OLD = ["Prism AI drew 1 image(s): a red truck"]


def _bubbles(win):
    return win.output_panel.findChildren(T.AnswerBubble)


def _prime(win, tmp_path, responses=None):
    img = tmp_path / "pic.png"
    img.write_bytes(base64.b64decode(PNG))
    responses = responses or {"visual": OLD}
    win._followup_session = {
        "query": "a red truck", "title": "", "run_file": "",
        "responses": responses, "links": {"visual": str(img)},
        "agents": {"visual": "ChatGPT"}, "artifacts_dir": ""}
    win._followup_responses = responses
    win._stage_agents = {"visual": "ChatGPT"}
    win._is_followup_run = True
    return img


# ── 1. stale answer ──────────────────────────────────────────────────────────

def test_a_failed_step_does_not_reshow_the_old_answer(win):
    win._followup_responses = {"visual": OLD}
    win._is_followup_run = True
    win._stage_results = [{"stage": "visual", "ok": False, "text": "boom"}]
    before = len(_bubbles(win))
    win._add_turn_result({"visual": OLD}, {})
    assert len(_bubbles(win)) == before


def test_an_unchanged_old_step_is_not_a_reply_but_a_new_one_is(win):
    win._followup_responses = {"content": ["old text"]}
    win._is_followup_run = True
    win._stage_results = [{"stage": "visual", "ok": True, "text": "new"}]
    before = len(_bubbles(win))
    win._add_turn_result({"content": ["old text"], "visual": ["new picture"]}, {})
    assert len(_bubbles(win)) == before + 1
    assert "new picture" in _bubbles(win)[-1].text()


def test_a_first_run_answer_is_still_shown(win):
    win._is_followup_run = False
    win._followup_responses = {"content": ["same"]}
    win._stage_results = []
    before = len(_bubbles(win))
    win._add_turn_result({"content": ["same"]}, {})
    assert len(_bubbles(win)) == before + 1


# ── 2. picture follow-up ─────────────────────────────────────────────────────

def test_change_request_wording():
    assert chatlog.is_change_request("make the truck blue")
    assert not chatlog.is_change_request("what is in the picture?")
    assert not chatlog.is_change_request("describe it")
    assert not chatlog.is_change_request("")


def test_a_change_on_a_picture_is_redrawn_not_written(win, tmp_path):
    _prime(win, tmp_path)
    with mock.patch.object(win, "_submit_followup") as submit, \
            mock.patch.object(win, "_start_chat_reply") as reply:
        win._on_chat_submitted("make the truck blue", [])
    assert not reply.called
    forced = submit.call_args.kwargs["forced"]
    assert forced["steps"] == ["visual"]
    prompt = forced["prompts"]["visual"]
    assert prompt.startswith("a red truck") and prompt.endswith("Change: make the truck blue")
    notes = [i for i in win.output_panel.thread_items() if i["kind"] == "note"]
    assert any("cannot edit" in n["text"] for n in notes)


def test_a_question_on_a_picture_still_goes_to_the_writer(win, tmp_path):
    _prime(win, tmp_path)
    with mock.patch.object(win, "_submit_followup") as submit, \
            mock.patch.object(win, "_start_chat_reply") as reply:
        win._on_chat_submitted("what colour is the truck?", [])
    assert reply.called and not submit.called


def test_a_text_answer_is_not_treated_as_a_picture(win, tmp_path):
    _prime(win, tmp_path, responses={"content": ["Some text."]})
    win._followup_session["links"] = {}
    with mock.patch.object(win, "_submit_followup") as submit, \
            mock.patch.object(win, "_start_chat_reply") as reply:
        win._on_chat_submitted("make it shorter", [])
    assert reply.called and not submit.called


def test_a_picture_with_no_file_on_disk_is_not_redrawn(win, tmp_path):
    img = _prime(win, tmp_path)
    img.unlink()
    with mock.patch.object(win, "_submit_followup") as submit, \
            mock.patch.object(win, "_start_chat_reply") as reply:
        win._on_chat_submitted("make the truck blue", [])
    assert reply.called and not submit.called


def test_second_change_keeps_the_first(win, tmp_path):
    _prime(win, tmp_path)
    win.output_panel.begin_turn("make it blue")
    win.output_panel.add_answer("Prism AI drew 1 image(s).", "Prism AI", "visual")
    with mock.patch.object(win, "_submit_followup") as submit:
        win._on_chat_submitted("add snow", [])
    prompt = submit.call_args.kwargs["forced"]["prompts"]["visual"]
    assert "Change: make it blue" in prompt and prompt.endswith("Change: add snow")


def test_forced_plan_runs_exactly_those_steps(win):
    win._followup_responses = {"visual": OLD}
    with mock.patch.object(win, "_start_followup_run") as run, \
            mock.patch.object(win, "_followup_as_local_file") as local:
        win._on_followup_routed({"steps": ["visual"], "forced": True,
                                 "prompts": {"visual": "p"}, "titles": {"visual": "T"}})
    assert not local.called
    assert run.call_args.args[0] == ["visual"]
    assert run.call_args.kwargs["prompts"] == {"visual": "p"}


# ── 3. thumbnail ─────────────────────────────────────────────────────────────

def test_image_card_shows_a_thumbnail(win, tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(base64.b64decode(PNG))
    assert FileCard(str(p)).thumb is not None


def test_bad_or_missing_or_non_image_files_have_no_thumbnail(win, tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image")
    doc = tmp_path / "a.txt"
    doc.write_text("hi")
    assert FileCard(str(bad)).thumb is None
    assert FileCard(str(tmp_path / "gone.png")).thumb is None
    assert FileCard(str(doc)).thumb is None


# ── 4. card order ────────────────────────────────────────────────────────────

def test_artwork_and_design_cards_sit_above_the_queued_video(win):
    panel = win.output_panel
    panel.set_plan({"content": "ChatGPT", "media": "Prism Studio"}, keep_thread=True)
    panel.stage_started("artwork", "ChatGPT")
    panel.stage_started("design", "ChatGPT")
    assert panel._order == ["content", "artwork", "design", "media"]
    box = panel.cards_box
    seen = [box.itemAt(i).widget().stage for i in range(box.count())
            if isinstance(box.itemAt(i).widget(), OP.StageCard)]
    assert seen == ["content", "artwork", "design", "media"]
    assert [panel._cards[k].number.text() for k in panel._order] == ["1", "2", "3", "4"]


def test_a_new_card_after_the_video_started_goes_last(win):
    panel = win.output_panel
    panel.set_plan({"media": "Prism Studio"}, keep_thread=True)
    panel.stage_started("media", "Prism Studio")
    panel.stage_started("artwork", "ChatGPT")
    assert panel._order == ["media", "artwork"]
