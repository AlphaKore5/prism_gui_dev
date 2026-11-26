"""Rules added after the first live Motion runs with an art direction and a
brand kit (13 Nov 2026). Each test is a fault that was seen in a rendered film
or in its transcript. No network, no browser."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "prism_terminal"))

from core.motion import generate as G  # noqa: E402
from core.motion import inspect as I  # noqa: E402


def _reply(scene: dict) -> str:
    return "```json\n" + json.dumps(scene) + "\n```"


# ── a check reads what will be played ────────────────────────────────────────

def test_secondary_motion_beside_animation_is_not_sent_back():
    """The model wrote secondary_motion next to "animation" on every scene; the
    renderer accepts it, the layer check did not, and each scene was sent back
    twice for nothing."""
    raw = {"nodes": [
        {"id": "haze", "type": "light_field", "layer": "background", "position": [540, 960],
         "color": "#D9D9D6", "secondary_motion": {"property": "x", "freq": 0.15, "amount": 12}},
        {"id": "cap", "type": "text", "layer": "foreground", "position": [540, 900], "text": "Hello",
         "animation": {"enter": {"time": 0, "duration": 0.5, "tweens": []}},
         "exit": {"time": 2.0, "duration": 0.4, "tweens": []}},
    ]}
    scene = G.parse_scene(_reply(raw))
    haze, cap = scene["nodes"]
    assert haze["animation"]["secondary_motion"]["property"] == "x"
    assert "secondary_motion" not in haze
    assert cap["content"] == "Hello" and "exit" in cap["animation"]
    scene.update(id="scene_0", duration=3.0)
    faults = I.inspect({"project": {"width": 1080, "height": 1920}, "scenes": [scene]})
    assert not [f for f in faults if "secondary_motion" in f or '"content"' in f], faults


def test_children_are_normalised_too():
    raw = {"nodes": [{"id": "card", "type": "glass_panel", "position": [540, 900],
                      "children": [{"id": "t", "type": "text", "text": "Inside", "x": 0, "y": 0}]}]}
    child = G.parse_scene(_reply(raw))["nodes"][0]["children"][0]
    assert child["content"] == "Inside" and child["position"] == [0, 0]


def test_caption_written_as_text_key_counts_as_the_caption():
    raw = {"nodes": [{"id": "cap", "type": "text", "position": [540, 900], "text": "Christmas, gathered."}]}
    scene = G.parse_scene(_reply(raw))
    assert G.caption_faults(scene, {"caption": "Christmas, gathered."}) == []


# ── the stand-in scene ───────────────────────────────────────────────────────

_LIGHT = {"width": 1080, "height": 1920, "background": "#F5F5F3",
          "palette": {"bg_a": "#F5F5F3", "ink": "#111111", "accent": "#C8161D"}}


def test_fallback_shows_the_caption_not_the_designers_note():
    row = {"job": "Warm the page: a bright sky arrives from the right and the greeting is said.",
           "caption": "Merry Christmas from Ember & Oak. What can we bake for you?"}
    node = G.fallback_scene(row, _LIGHT)["nodes"][0]
    assert "Merry Christmas" in node["content"] and "Warm the page" not in node["content"]


def test_fallback_fits_the_frame_and_reads_on_a_light_page():
    row = {"caption": "Merry Christmas from Ember & Oak. What can we bake for you?"}
    scene = G.fallback_scene(row, _LIGHT)
    node = scene["nodes"][0]
    assert node["fill"] == "#111111"                      # ink, not near-white on a light page
    assert "\n" in node["content"]
    scene.update(id="scene_0", duration=3.0)
    faults = I.inspect({"project": _LIGHT, "scenes": [scene]})
    assert not [f for f in faults if "runs off the edge" in f], faults


def test_fallback_stays_light_on_a_dark_page_and_without_a_project():
    dark = dict(_LIGHT, background="#0B0B0D", palette={"bg_a": "#0B0B0D", "ink": "#F4EFE6"})
    assert G.fallback_scene({"caption": "Hello"}, dark)["nodes"][0]["fill"] == "#F8FAFC"
    node = G.fallback_scene({"job": "say hello"})["nodes"][0]
    assert node["content"] == "say hello" and node["position"] == [540, 960]


# ── the ink look must stay ink-coloured ──────────────────────────────────────

def test_ink_film_turns_the_grey_spotlight_off():
    """Round 2 (13 Nov 2026): a #0C0808 film rendered grey (42,40,41) at its
    edges because the ink preset's white spotlight fades through grey. With the
    spotlight "none" the same frame was (10,7,7)."""
    spec = {"project": {"look": "ink", "background": "#0C0808"}, "scenes": []}
    G._flat_ink_backdrop(spec)
    assert spec["visual"]["spotlight"] == {"color": "none", "secondary": "none"}


def test_ink_backdrop_keeps_what_the_writer_set_and_leaves_other_looks_alone():
    own = {"project": {"look": "ink"}, "visual": {"spotlight": {"color": "rgba(200,20,20,0.2)"}, "grain_opacity": 0}}
    G._flat_ink_backdrop(own)
    assert own["visual"]["spotlight"] == {"color": "rgba(200,20,20,0.2)"}
    for look in ("paper", "tech", None):
        spec = {"project": {"look": look}, "scenes": []}
        G._flat_ink_backdrop(spec)
        assert "visual" not in spec


# ── legibility: type a phone can read, the client's mark not a thumbnail ─────

_LOGO = {"logo": {"w": 719, "h": 757, "kind": "logo"}}


def test_text_under_the_floor_is_sent_back_and_the_floor_passes():
    scene = {"nodes": [
        {"type": "text", "content": "Ember & Oak", "font_size": 26, "position": [540, 1490]},
        {"type": "text", "content": "Baked slow.", "font_size": 34, "position": [540, 1320]},
        {"type": "text", "content": "", "font_size": 10, "position": [0, 0]}]}
    got = G.legibility_faults(scene, (1080, 1920), _LOGO)
    assert len(got) == 1 and "Ember & Oak" in got[0] and "26" in got[0]


def test_logo_in_a_thumbnail_box_is_sent_back():
    """The 13 Nov night film: a 719x757 logo in a 420x260 box is 247 px wide."""
    small = {"nodes": [{"type": "image", "src": "asset:logo", "width": 420, "height": 260, "position": [540, 700]}]}
    got = G.legibility_faults(small, (1080, 1920), _LOGO)
    assert len(got) == 1 and "247" in got[0]


def test_logo_at_a_proper_size_passes_and_the_largest_image_decides():
    big = {"nodes": [{"type": "image", "src": "asset:logo", "width": 420, "height": 440, "position": [540, 700]}]}
    assert G.legibility_faults(big, (1080, 1920), _LOGO) == []
    grid = {"nodes": [{"type": "image", "src": "asset:logo", "width": 200, "height": 200, "position": [200, 700]},
                      {"type": "image", "src": "asset:logo", "width": 500, "height": 500, "position": [800, 700]}]}
    assert G.legibility_faults(grid, (1080, 1920), _LOGO) == []
    assert G.legibility_faults(small_no_table := {"nodes": [{"type": "image", "src": "asset:x", "width": 50, "height": 50}]},
                               (1080, 1920), {}) == []


# ── the cinematic recipes must speak the film's colours ──────────────────────

_PALETTE = {"bg_a": "#0C0808", "bg_b": "#170909", "ink": "#F3EBE2", "accent": "#C8161D", "accent2": "#900F14"}
_REFERENCE_BLUES = ("#8fb4d6", "#3d5c94", "#2563FF", "rgba(140,200,255,0.95)", "violet", "orange, purple, blue, gold")


def test_recipes_are_given_in_the_films_palette():
    """Round 3 (13 Nov 2026): a dark red film had a #3d5c94 sky-blue scene because
    the recipe handed the writer the reference's blues."""
    from core.motion import spine
    for beat in ("hub", "sweep", "cards", "knowledge"):
        plain = spine.recipe_text(beat)
        mine = spine.recipe_text(beat, _PALETTE)
        assert any(b in plain for b in _REFERENCE_BLUES) or beat == "hub"
        for blue in _REFERENCE_BLUES:
            assert blue not in mine, (beat, blue)
    sweep = spine.recipe_text("sweep", _PALETTE)
    assert "#0C0808" in sweep and "#C8161D" in sweep


def test_recipes_are_unchanged_without_a_usable_palette_and_still_pass_their_own_check():
    from core.motion import spine
    assert spine.recipe_text("sweep") == spine.recipe_text("sweep", None) == spine.recipe_text("sweep", {"accent": "#C8161D"})
    # the recoloured backdrop is still a big gradient, which is what the beat checks for
    node = {"type": "shape_circle", "radius": 1900, "fill": "radial-gradient(circle at 50% 50%, #170909 0%, #0C0808 100%)"}
    assert spine._is_bright_backdrop(node)


def test_scene_prompt_carries_the_palette_into_the_recipe():
    row = {"job": "j", "beat": "sweep", "caption": "c", "seconds": 4.4}
    text = G.scene_instructions(5, 7, row, "", skeleton="cinematic_glass", palette=_PALETTE)
    assert "#C8161D" in text and "#8fb4d6" not in text


# ── a shot is aimed at the middle of its target, not at its anchor ───────────

def test_shot_on_a_top_left_anchored_node_is_aimed_at_the_node_middle():
    """Round 4 (13 Nov 2026): logo at [72, 560], anchor [0, 0], 720x400, shot "push" on it:
    the camera went to its corner and the logo ended cut off at the frame edge."""
    scene = {"shot": {"intent": "push", "target": "logo"},
             "nodes": [{"id": "logo", "type": "image", "position": [72, 560], "anchor": [0, 0], "width": 720, "height": 400}]}
    G._aim_shots_at_centres([scene])
    assert scene["shot"]["target"] == [432.0, 760.0]


def test_shot_aiming_leaves_centred_nodes_coordinates_and_unknown_ids_alone():
    centred = {"shot": {"intent": "push", "target": "a"},
               "nodes": [{"id": "a", "type": "image", "position": [540, 700], "width": 400, "height": 400}]}
    coords = {"shot": {"intent": "push", "target": [540, 900]},
              "nodes": [{"id": "a", "type": "image", "position": [0, 0], "anchor": [0, 0], "width": 400, "height": 400}]}
    missing = {"shot": {"intent": "hold", "target": "nope"}, "nodes": []}
    for scene in (centred, coords, missing):
        before = json.dumps(scene)
        G._aim_shots_at_centres([scene])
        assert json.dumps(scene) == before
    G._aim_shots_at_centres([{"nodes": []}])        # no shot at all
