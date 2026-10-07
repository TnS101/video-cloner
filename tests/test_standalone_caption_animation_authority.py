from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.standalone.video_cloner_textplus import (
    StandaloneTextplusError,
    attach_visual_animation_authority,
    render_visual_compositions,
    resolve_visual_style_authority,
)


ROOT = Path(__file__).parents[1]
STYLE = ROOT / "data" / "DcJRJtUKScu" / "analysis" / "DcJRJtUKScu_caption_style.json"


def _composition(text: str, cue_id: str, event_id: str, window: list[int], authority: str = "visual_primary") -> dict:
    return {
        "composition_id": f"visual_composition_{cue_id}",
        "window": window,
        "authority": {"kind": authority, "evidence_ids": [event_id]},
        "tokens": [{
            "token_id": f"visual_token_{cue_id}",
            "text": text,
            "semantic_ids": [cue_id],
            "window": window,
            "style_evidence_id": event_id,
        }],
    }


def _attach(composition: dict, style_data: dict) -> tuple[dict, int]:
    cue_id = composition["tokens"][0]["semantic_ids"][0]
    cues, _ = render_visual_compositions([composition], [cue_id], 30.0)
    styles, _ = resolve_visual_style_authority(cues, style_data, 30.0)
    return cues[0], attach_visual_animation_authority(cues, style_data, styles, 30.0)


def test_reel2_slide_and_scale_attach_normalized_local_textplus_payloads():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))

    we, we_count = _attach(_composition("We", "sub_007", "style_event_sub_0007", [49, 52]), style_data)
    selling, selling_count = _attach(
        _composition("Selling", "sub_010", "style_event_sub_0010", [67, 75]), style_data
    )

    assert we_count == selling_count == 1
    assert we["animation_authority"] == {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_0007",
        "source_type": "slide",
        "property": "Center",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": [-0.0106, 0.0565]},
            {"frame": 2, "relative_time": 1.0, "value": [0.0, 0.0]},
        ],
    }
    assert selling["animation_authority"] == {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_0010",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": pytest.approx(0.3255441425)},
            {"frame": 7, "relative_time": 1.0, "value": 0.25},
        ],
    }


def test_reel2_social_scale_composes_with_step3_size_and_static_token_stays_static():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    composition = _composition("social,", "sub_045", "style_event_sub_0045", [359, 383])
    composition["tokens"][0]["accepted_motion_authority"] = {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_0045",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }
    cues, _ = render_visual_compositions([composition], ["sub_045"], 30.0)
    styles, _ = resolve_visual_style_authority(cues, style_data, 30.0)

    base_size = styles[1]["textplus_size"]
    assert base_size == 0.1
    assert attach_visual_animation_authority(cues, style_data, styles, 30.0) == 1
    assert cues[0]["animation_authority"]["keyframes"] == [
        {"frame": 0, "relative_time": 0.0, "value": pytest.approx(0.080528214)},
        {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
    ]

    static_composition = _composition("social,", "sub_045", "style_event_sub_0045", [365, 376])
    static_cues, _ = render_visual_compositions([static_composition], ["sub_045"], 30.0)
    static_styles, _ = resolve_visual_style_authority(static_cues, style_data, 30.0)
    before = copy.deepcopy(static_styles)
    assert attach_visual_animation_authority(static_cues, style_data, static_styles, 30.0) == 0
    assert "animation_authority" not in static_cues[0]
    assert static_styles == before


def test_migrated_social_motion_attaches_by_visual_identity_not_stale_event_id():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    owner = next(row for row in style_data["caption_style_events"] if row["event_id"] == "style_event_sub_0045")
    owner["event_id"] = "style_event_caption_tracklet_0064"
    owner["visual_event_identity"] = "caption_tracklet_0064"
    composition = _composition("social,", "sub_045", owner["event_id"], [359, 383])
    composition["tokens"][0]["visual_event_identity"] = "caption_tracklet_0064"
    composition["tokens"][0]["accepted_motion_authority"] = {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_0045",
        "source_visual_event_identity": "caption_tracklet_0064",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }

    cue, count = _attach(composition, style_data)

    assert count == 1
    assert cue["visual_event_identity"] == "caption_tracklet_0064"
    assert cue["animation_authority"] == {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_caption_tracklet_0064",
        "source_visual_event_identity": "caption_tracklet_0064",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }


def test_migrated_motion_duplicate_visual_owner_fails_closed():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    owner = next(row for row in style_data["caption_style_events"] if row["event_id"] == "style_event_sub_0045")
    owner["event_id"] = "style_event_caption_tracklet_0064"
    owner["visual_event_identity"] = "caption_tracklet_0064"
    style_data["caption_style_events"].append({**copy.deepcopy(owner), "event_id": "duplicate"})
    composition = _composition("social,", "sub_045", owner["event_id"], [359, 383])
    composition["tokens"][0]["visual_event_identity"] = "caption_tracklet_0064"
    composition["tokens"][0]["accepted_motion_authority"] = {
        "authority": "visual_observed",
        "source_visual_event_identity": "caption_tracklet_0064",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }
    cues, _ = render_visual_compositions([composition], ["sub_045"], 30.0)
    styles, _ = resolve_visual_style_authority(cues, style_data, 30.0)

    with pytest.raises(StandaloneTextplusError, match="missing or ambiguous"):
        attach_visual_animation_authority(cues, style_data, styles, 30.0)


def test_explicit_product_motion_does_not_promote_other_observed_motion():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    social = _composition("social,", "sub_045", "style_event_sub_0045", [359, 383])
    social["tokens"][0]["accepted_motion_authority"] = {
        "authority": "visual_observed",
        "source_evidence_id": "style_event_sub_0045",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }
    launching = _composition("launching", "sub_088", "style_event_sub_0088", [721, 737])
    cues, _ = render_visual_compositions([social, launching], ["sub_045", "sub_088"], 30.0)
    styles, _ = resolve_visual_style_authority(cues, style_data, 30.0)

    assert attach_visual_animation_authority(cues, style_data, styles, 30.0) == 1
    assert cues[0]["animation_authority"]["source_evidence_id"] == "style_event_sub_0045"
    assert "animation_authority" not in cues[1]


def test_reel2_scale_pop_outlier_and_unsupported_motion_remain_static():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    long_cue, count = _attach(
        _composition("long", "sub_015", "style_event_sub_0015", [105, 116]), style_data
    )
    assert count == 0
    assert "animation_authority" not in long_cue

    unsupported = copy.deepcopy(style_data)
    event = next(row for row in unsupported["caption_style_events"] if row["event_id"] == "style_event_sub_0010")
    event["animation"]["type"] = event["animation"]["style"] = "fade"
    selling, count = _attach(
        _composition("Selling", "sub_010", "style_event_sub_0010", [67, 75]), unsupported
    )
    assert count == 0
    assert "animation_authority" not in selling


def test_mismatched_and_ambiguous_animation_evidence_remain_static():
    style_data = json.loads(STYLE.read_text(encoding="utf-8-sig"))
    cue = {
        "index": 1,
        "source_cue_ids": ["sub_008"],
        "style_evidence_id": "style_event_sub_0007",
        "duration_frames": 3,
    }
    styles = {1: {"style_authority": "visual_observed"}}
    assert attach_visual_animation_authority([cue], style_data, styles, 30.0) == 0
    assert "animation_authority" not in cue

    ambiguous = copy.deepcopy(style_data)
    event = next(row for row in ambiguous["caption_style_events"] if row["event_id"] == "style_event_sub_0007")
    ambiguous["caption_style_events"].append(copy.deepcopy(event))
    cue["source_cue_ids"] = ["sub_007"]
    assert attach_visual_animation_authority([cue], ambiguous, styles, 30.0) == 0
    assert "animation_authority" not in cue


def test_actual_reel2_unresolved_motion_compositions_remain_closed():
    compositions = [
        _composition("We", "sub_007", "style_event_sub_0007", [49, 52], "unresolved"),
        _composition("Selling", "sub_010", "style_event_sub_0010", [67, 75], "unresolved"),
    ]
    with pytest.raises(StandaloneTextplusError, match="unresolved visual composition"):
        render_visual_compositions(compositions, ["sub_007", "sub_010"], 30.0)
