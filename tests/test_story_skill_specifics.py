"""Story skill: a brief that forbids invention must not be sent to a paid repair.

26 Nov 2026, the owner's reel run: the brains step wrote a plan full of real
numbers (28 seconds, 120 BPM, 30 fps, 72 px, 6%, 16:00) and the checker said
"Only 2 checkable specifics", because the 2 it found were the '1920' of
'1080x1920' read as a year, while '%' and every unit above were not recognised.
The brief said "none supplied, do not invent", so the repair it triggered
could not have been satisfied, and it was paid for.
"""
from __future__ import annotations

import os
import sys
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402,F401
from core import skills as SK                                       # noqa: E402
from test_ai_via_server import FakeAi, ai                           # noqa: E402,F401

with open(os.path.join(ROOT, "tests", "fixtures", "story_brains_reel_plan.txt"),
          encoding="utf-8") as _f:
    REEL_PLAN = _f.read()

_FILLER = ("She stood at the counter and waited for the kettle to finish, "
           "thinking about the letter that had come in the morning post. ") * 9
_SPEECH = ' He said "come in and sit down with me."'


def _only(faults):
    return [f for f in faults if "checkable specific" in f]


def _story(text):
    return SK.check(["story"], text, {})


def _specifics(text):
    return SK._checks_module(SK.get("story")).SPECIFIC.findall(text)


def test_the_owners_reel_plan_is_not_called_specific_free():
    assert not _only(_story(REEL_PLAN))


@pytest.mark.parametrize("dims", ["1080x1920", "1080×1920", "1080 x 1920", "1080 × 1920"])
def test_a_resolution_is_not_a_year(dims):
    assert _specifics(f"{_FILLER} at {dims} {_SPEECH}") == []


@pytest.mark.parametrize("phrase", [
    "pushes in 6%", "a drop of 8%", "28 seconds", "28 sec", "4s", "120 BPM",
    "30 fps", "72 px", "six frames at 24 frames", "at 16:00", "in 2019"])
def test_real_numbers_and_units_count(phrase):
    assert _specifics(f"{_FILLER} {phrase} {_SPEECH}"), phrase


def test_a_story_with_no_figures_is_still_flagged():
    assert _only(_story(_FILLER + _SPEECH))


def test_the_narrative_checks_are_unchanged():
    text = ("In today's fast-paced world " + _FILLER
            + " It was a journey of passion, and that is why we do it. Contact us.")
    got = " ".join(_story(text))
    assert "stock phrase" in got and "Nobody speaks" in got
    assert "journey" in got and "explains its own point" in got and "call to action" in got


# ── the paid repair ─────────────────────────────────────────────────────────

def _run(ai, text, task="Write the plan."):
    from core import automation, config as C
    import ai_server
    ai.responder = lambda body: text
    ai_server.begin_run("run-story-1")
    try:
        automation.run({}, C.load(), custom_stages=[("content", "Claude", [task])],
                       chatgpt_analysis=False, query=task, failover=False,
                       stage_skills={"content": ["story"]})
    finally:
        ai_server.end_run()
    return [c for c in ai.chats()
            if "checked your answer against the skill" in str(c["body"]["messages"][-1]["content"])]


_NO_SPECIFICS_FORBIDDEN = (
    _FILLER + _SPEECH + " [HOOK WORD - awaiting brand copy] [NAME - to supply]. "
    "Nothing is invented.")


def test_a_brief_that_forbids_invention_is_not_sent_to_a_paid_repair(ai):
    assert not _run(ai, _NO_SPECIFICS_FORBIDDEN)


def test_the_same_shortfall_without_that_marker_is_still_repaired(ai):
    assert _run(ai, _FILLER + _SPEECH)


def test_a_different_real_fault_is_still_repaired_even_with_the_marker(ai):
    bad = ("In today's fast-paced world " + _NO_SPECIFICS_FORBIDDEN)
    sent = _run(ai, bad)
    assert sent
    assert "stock phrase" in str(sent[0]["body"]["messages"][-1]["content"])
