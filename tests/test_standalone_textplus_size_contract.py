from scripts.standalone.video_cloner_textplus import (
    _ensure_textplus_size,
    apply_static_style_authority,
    attach_independent_style_evidence_contract,
)


def test_textplus_size_contract_fills_heuristic_style_and_preserves_static_size():
    heuristic = {"font_size_px": 88}
    large = {"font_size_px": 295}
    static = {"font_size_px": 78, "textplus_size": 0.10833333333333332}

    _ensure_textplus_size(heuristic, 1080)
    _ensure_textplus_size(large, 1080)
    _ensure_textplus_size(static, 1080)

    assert heuristic["textplus_size"] == 0.12222222222222223
    assert large["textplus_size"] == 0.4097222222222222
    assert static["textplus_size"] == 0.10833333333333332


def test_static_style_authority_preserves_identity_and_serializes_geometry_font_stroke_and_z_order():
    cue = {
        "index": 1,
        "visual_event_identity": "fragment_a",
        "lane": 1,
        "static_style": {
            "visual_event_identity": "fragment_a",
            "font_name": "Arial Black",
            "font_authority": "BEST_AVAILABLE_FONT_MATCH",
            "font_size_px": 110,
            "bold": True,
            "normalized_bbox": [0.25, 0.20, 0.50, 0.30],
            "fill": "#f0c090",
            "fill_opacity": 0.8,
            "stroke_enabled": True,
            "stroke_width_px": 5,
            "stroke_color": "#101010",
            "static_z_order": 4,
            "static_rotation_degrees": -2.0,
        },
    }
    style = {
        "font_name": "Arial",
        "font_size_px": 60,
        "bold": False,
        "fill": "#ffffff",
        "outline": "#000000",
        "outline_px": 1.0,
        "placement": {"normalized_bbox": [0.0, 0.0, 0.1, 0.1]},
    }

    assert apply_static_style_authority([cue], {1: style}, 1080) == 1
    assert cue["visual_event_identity"] == "fragment_a"
    assert cue["lane"] == 6
    assert style["font_name"] == "Arial Black"
    assert style["font_size_px"] == 110
    assert style["anchor"] == {"x": 0.375, "y": 0.25}
    assert style["outline_px"] == 5.0
    assert style["fill_fcpxml"].endswith(" 0.8")
    assert style["static_rotation_degrees"] == -2.0


def test_style_evidence_is_identity_owned_even_inside_a_composition_or_fragment_group():
    cues = [
        {"index": 1, "id": "a", "visual_event_identity": "a", "static_style": {"fragment_group": "buyers"}},
        {"index": 2, "id": "b", "visual_event_identity": "b", "static_style": {"fragment_group": "buyers"}},
        {"index": 3, "id": "c", "visual_event_identity": "c"},
    ]
    styles = {1: {}, 2: {}, 3: {}}

    attach_independent_style_evidence_contract(cues, styles)

    assert [styles[index]["style_evidence_owner"] for index in styles] == ["a", "b", "c"]
    assert all(styles[index]["style_sharing_authority"] == "independent_by_default" for index in styles)
    assert cues[0]["physical_word_group_id"] == cues[1]["physical_word_group_id"] == "buyers"
    assert "physical_word_group_id" not in cues[2]
