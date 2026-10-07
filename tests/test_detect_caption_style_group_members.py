from __future__ import annotations

import sys
import types
from types import SimpleNamespace


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from video_cloner.analysis.caption_style import build_caption_style_events, group_caption_candidates


def _candidate(text: str, bbox: list[int], score: float, match: float) -> dict:
    return {
        "text": text, "confidence": 0.8, "bbox": bbox,
        "normalized_bbox": [value / 1080 for value in bbox],
        "center": {"x": (bbox[0] + bbox[2]) / 2160, "y": (bbox[1] + bbox[3]) / 3840},
        "position": {"vertical_zone": "top", "horizontal_align": "center"},
        "estimated_font_height_px": 80, "estimated_font_height_ratio": 0.04,
        "estimated_box_width_ratio": 0.3, "estimated_box_height_ratio": 0.05,
        "estimated_text_color": "#dcb999" if text == "sion" else "#f1efea",
        "estimated_stroke_color": "#20221c" if text == "sion" else "#292a23",
        "estimated_shadow_color": "#20221c" if text == "sion" else "#292a23",
        "has_dark_stroke": True, "has_shadow": True, "has_bright_text": True,
        "has_saturated_text": True, "text_area_ratio": 0.2, "dark_area_ratio": 0.2,
        "saturated_area_ratio": 0.2, "contrast_area_ratio": 0.8,
        "caption_role": "spoken_caption",
        "caption_score": {
            "score": score, "transcript_match_score": match, "hook_score": 0.4,
            "reason": "transcript_matched_caption", "matched_cue_ids": ["sub_0016", "sub_0018"],
        },
    }


def _args() -> SimpleNamespace:
    return SimpleNamespace(
        emit_caption_style_events=True, style_event_match_window_sec=1.25,
        style_event_min_match_score=0.18, max_style_events=0,
        animation_min_samples=3, animation_max_samples=7,
    )


def test_parent_group_keeps_union_geometry_and_member_identity():
    groups = group_caption_candidates([
        _candidate("beforethe", [284, 346, 637, 444], 0.6541, 0.4),
        _candidate("sion", [336, 408, 778, 536], 0.5867, 0.375),
    ], (1920, 1080, 3), y_tolerance=0.05)

    assert len(groups) == 1
    assert groups[0]["bbox"] == [284, 346, 778, 536]
    assert [member["text"] for member in groups[0]["members"]] == ["beforethe", "sion"]
    assert groups[0]["items_count"] == 2


def test_stronger_member_match_emits_sign_style_event_without_splitting_parent():
    groups = group_caption_candidates([
        _candidate("beforethe", [284, 346, 637, 444], 0.6541, 0.4),
        _candidate("sion", [336, 408, 778, 536], 0.5867, 0.375),
    ], (1920, 1080, 3), y_tolerance=0.05)
    groups[0].update(timestamp=5.4, frame_index=26)
    cues = [
        {"id": "sub_0016", "text": "before", "start": 4.82, "end": 5.16, "mid": 4.99},
        {"id": "sub_0018", "text": "sign", "start": 5.42, "end": 5.64, "mid": 5.53},
    ]
    profiles = [{"style_id": "style_01_spoken_caption", "role": "spoken_caption", "confidence": {"score": 1}, "sample_count": 1}]
    events, _ = build_caption_style_events(groups, cues, profiles, {"width": 1080, "height": 1920}, _args())
    sign = next(event for event in events if event["cue_id"] == "sub_0018")

    assert sign["observed_texts"] == ["sion"]
    assert sign["colors"]["fill"] == "#dcb999"
    assert sign["colors"]["stroke"] == "#20221c"
    assert groups[0]["bbox"] == [284, 346, 778, 536]


def test_unrelated_same_line_grouping_predicate_remains_unchanged():
    groups = group_caption_candidates([
        _candidate("one", [400, 500, 500, 560], 0.8, 1.0),
        _candidate("two", [510, 505, 610, 565], 0.8, 1.0),
    ], (1920, 1080, 3), y_tolerance=0.05)

    assert len(groups) == 1
    assert groups[0]["items_count"] == 2
