"""core.reel_lite: the zero-credit reel built from the script and the pictures.

No AI, no browser: the spec is checked structurally. The full run through
automation.run is in test_studio_refusal_wiring.py.
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                       # noqa: E402

import core_bridge as CB                                            # noqa: E402,F401

SCRIPT = """```json
{"scenes": [
 {"role": "hook", "seconds": 5, "kicker": "College Placements", "headline": "Your skills, your job.", "support": "Find the career path that fits your talent."},
 {"role": "statement", "seconds": 5, "kicker": "AI Campus Platform", "headline": "Empowering students and placement cells.", "support": "Intelligent job matching built for campus recruitment."},
 {"role": "statement", "seconds": 40, "kicker": "Smart Matching", "headline": "Delta matches you to the right role.", "support": "Directly linking verified skills to top employer openings."},
 {"role": "endcard", "seconds": 5, "headline": "Delta", "support": "Try Delta today.", "contact": "delta.ai"}]}
```"""


@pytest.fixture
def pics(tmp_path):
    from PIL import Image
    out = []
    for name, size in (("a.png", (1080, 1920)), ("b.png", (600, 600))):
        p = tmp_path / name
        Image.new("RGB", size, (200, 40, 20)).save(p)
        out.append(str(p))
    return out


def test_a_script_becomes_scenes_that_pass_the_structural_check(pics):
    from core import reel_lite, reel_web
    spec = reel_lite.build_lite_spec(["not a script", SCRIPT], pics)
    assert spec["_lite"] is True and spec["design"]["name"] == "lite"
    assert len(spec["scenes"]) == 4
    assert reel_web.structural_faults(spec) == []
    assert spec["scenes"][2]["seconds"] == 12          # 40 s clamped to the limit
    blob = json.dumps([s["html"] for s in spec["scenes"]])
    for want in ("College Placements", "Your skills, your job.", "Delta matches you",
                 "delta.ai", "Try Delta today."):
        assert want in blob
    assert [s["cut"] for s in spec["scenes"][:3]] == ["push", "zoom", "push-up"]


def test_only_pictures_in_the_table_are_referenced(pics):
    from core import reel_lite
    spec = reel_lite.build_lite_spec([SCRIPT], pics + ["/no/such/file.png"])
    used = set(re.findall(r"asset:([A-Za-z0-9_-]+)",
                          " ".join(s["html"] for s in spec["scenes"])))
    assert used and used <= set(spec["_assets"])
    assert len(spec["_assets"]) == 2                    # the missing file is left out


def test_a_tall_picture_fills_the_frame_and_a_square_one_sits_on_paper(pics):
    from core import reel_lite
    spec = reel_lite.build_lite_spec([SCRIPT], pics)
    assert "class='bg'" in spec["scenes"][0]["html"]          # 1080x1920
    assert "lt paper" in spec["scenes"][1]["html"]            # 600x600


def test_without_pictures_it_still_builds_on_the_brand_colour():
    from core import reel_lite
    spec = reel_lite.build_lite_spec([SCRIPT], [])
    assert spec["_assets"] == {} and "asset:" not in json.dumps(spec["scenes"])
    assert spec["brand"]["accent"] and spec["brand"]["deep"]


def test_script_text_is_escaped(pics):
    from core import reel_lite
    evil = json.dumps({"scenes": [{"role": "hook", "seconds": 4,
                                   "kicker": "<b>k</b>",
                                   "headline": "<script>alert(1)</script> & co",
                                   "support": "<img src=x onerror=y>"}]})
    spec = reel_lite.build_lite_spec([evil], pics)
    html = spec["scenes"][0]["html"]
    assert "<script" not in html and "<img" not in html and "<b>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; co" in html


@pytest.mark.parametrize("src", [["I could not write that."], [""], [],
                                 ['{"scenes": []}'], ['{"scenes": [{"role": "hook"}]}']])
def test_an_unreadable_script_gives_none(src, pics):
    from core import reel_lite
    assert reel_lite.build_lite_spec(src, pics) is None


def test_a_given_brand_is_kept(pics):
    from core import reel_lite
    spec = reel_lite.build_lite_spec([SCRIPT], pics, {"accent": "#112233"})
    assert spec["brand"]["accent"] == "#112233" and spec["brand"]["deep"]
