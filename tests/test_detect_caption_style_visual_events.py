from __future__ import annotations

import sys
import types
from types import SimpleNamespace


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from video_cloner.analysis.caption_style import build_caption_style_events


VIDEO = {"width": 1080, "height": 1920}
PROFILES = [{
    "style_id": "style_01_spoken_caption",
    "role": "spoken_caption",
    "confidence": {"score": 1.0},
    "sample_count": 1,
}]


def _args():
    return SimpleNamespace(
        emit_caption_style_events=True,
        style_event_match_window_sec=1.25,
        style_event_min_match_score=0.18,
        max_style_events=0,
        animation_min_samples=3,
        animation_max_samples=7,
    )


def _member(tracklet_id, timestamp, text, bbox, *, end=None, cue_id=None, continuous=None, provenance="accepted_direct"):
    x1, y1, x2, y2 = bbox
    row = {
        "text": text,
        "confidence": 0.9,
        "caption_score": 0.8,
        "transcript_match_score": 0.8,
        "hook_score": 0.2,
        "candidate_reason": "transcript_matched_caption",
        "role": "spoken_caption",
        "tracklet_id": tracklet_id,
        "observation_provenance": provenance,
        "observed_timestamp": timestamp,
        "inferred_visibility_end": timestamp + 0.1 if end is None else end,
        "bbox": bbox,
        "normalized_bbox": [x1 / 1080, y1 / 1920, x2 / 1080, y2 / 1920],
        "center": {"x": (x1 + x2) / 2160, "y": (y1 + y2) / 3840},
        "estimated_font_height_px": y2 - y1,
        "estimated_font_height_ratio": (y2 - y1) / 1920,
        "estimated_box_width_ratio": (x2 - x1) / 1080,
        "estimated_box_height_ratio": (y2 - y1) / 1920,
        "estimated_text_color": "#f2cb9b",
        "estimated_stroke_color": "#122017",
        "estimated_shadow_color": "#122017",
        "has_dark_stroke": True,
        "has_shadow": True,
        "has_saturated_text": True,
        "text_area_ratio": 0.2,
        "dark_area_ratio": 0.2,
        "saturated_area_ratio": 0.2,
        "contrast_area_ratio": 0.8,
        "matched_cue_ids": [cue_id] if cue_id else [],
    }
    if continuous:
        row.update({
            "continuous_visual_identity_id": continuous["id"],
            "continuous_visual_identity_tracklet_ids": continuous["tracklets"],
            "continuous_visual_identity_observed_start": continuous["start"],
            "continuous_visual_identity_last_observed": continuous["last"],
            "continuous_visual_identity_inferred_end": continuous["end"],
            "continuous_visual_identity_interval_semantics": "half_open",
        })
    return row


def _group(timestamp, *members, text=None):
    boxes = [member["bbox"] for member in members]
    bbox = [min(box[0] for box in boxes), min(box[1] for box in boxes), max(box[2] for box in boxes), max(box[3] for box in boxes)]
    return {
        "timestamp": timestamp,
        "frame_index": round(timestamp * 30),
        "text": text or " ".join(member["text"] for member in members),
        "bbox": bbox,
        "tracklet_ids": [member["tracklet_id"] for member in members],
        "members": list(members),
    }


def test_standalone_tracklet_owns_event_timing_and_transcript_is_annotation_only():
    member = _member("caption_tracklet_0001", 1.2, "We", [200, 400, 320, 470], end=1.7, cue_id="sub_1")
    cues = [{"id": "sub_1", "text": "We", "start": 9.0, "end": 9.2, "mid": 9.1}]

    events, diagnostics = build_caption_style_events([_group(1.2, member)], cues, PROFILES, VIDEO, _args())

    assert len(events) == 1
    assert events[0]["visual_event_identity"] == "caption_tracklet_0001"
    assert (events[0]["start"], events[0]["end"]) == (1.2, 1.7)
    assert events[0]["cue_id"] == "sub_1"
    assert events[0]["semantic_reference"]["cue_start"] == 9.0
    assert diagnostics["visual_identity_authority"] is True


def test_continuous_identity_owns_one_event_without_synthetic_gap_observation():
    identity = {"id": "continuous_visual_identity_0028", "tracklets": ["caption_tracklet_0028", "caption_tracklet_0033"], "start": 5.333, "last": 6.2, "end": 6.3}
    left = _member("caption_tracklet_0028", 5.4, "sion", [336, 408, 778, 536], continuous=identity)
    right = _member("caption_tracklet_0033", 6.0, "Sian", [340, 410, 780, 538], continuous=identity)

    events, _ = build_caption_style_events([_group(5.4, left), _group(6.0, right)], [], PROFILES, VIDEO, _args())

    assert len(events) == 1
    event = events[0]
    assert event["tracklet_ids"] == ["caption_tracklet_0028", "caption_tracklet_0033"]
    assert (event["start"], event["last_observed"], event["end"]) == (5.333, 6.2, 6.3)
    assert [row["observed_timestamp"] for row in event["observations"]] == [5.4, 6.0]


def test_repeated_semantic_labels_and_upper_lower_the_remain_distinct():
    upper = _member("upper_the", 5.0, "the", [420, 330, 560, 390], cue_id="the")
    lower = _member("lower_the", 5.0, "the", [360, 710, 500, 770], cue_id="the")
    cues = [{"id": "the", "text": "the", "start": 4.9, "end": 5.2, "mid": 5.05}]

    events, _ = build_caption_style_events([_group(5.0, upper, lower)], cues, PROFILES, VIDEO, _args())

    assert len(events) == 2
    assert {event["visual_event_identity"] for event in events} == {"upper_the", "lower_the"}
    assert {event["cue_id"] for event in events} == {"the"}
    assert len({tuple(event["placement"]["bbox"]) for event in events}) == 2


def test_parent_phrase_never_suppresses_visible_children():
    before = _member("before", 5.0, "before", [280, 350, 470, 440], cue_id="before")
    sign = _member("sign", 5.0, "sion", [500, 350, 760, 440], cue_id="sign")
    cues = [
        {"id": "before", "text": "before", "start": 4.8, "end": 5.2, "mid": 5.0},
        {"id": "sign", "text": "sign", "start": 5.42, "end": 5.64, "mid": 5.53},
    ]

    events, _ = build_caption_style_events([_group(5.0, before, sign, text="before the sign")], cues, PROFILES, VIDEO, _args())

    assert {event["visual_event_identity"] for event in events} == {"before", "sign"}
    assert all(event["observations"][0]["composition"]["text"] == "before the sign" for event in events)


def test_missing_semantic_mapping_preserves_visual_event_and_provenance():
    member = _member("caption_tracklet_6000", 22.6, "6000", [120, 400, 880, 600], end=23.7, provenance="accepted_refined")

    events, diagnostics = build_caption_style_events([_group(22.6, member)], [], PROFILES, VIDEO, _args())

    assert len(events) == 1
    assert events[0]["cue_id"] is None
    assert events[0]["label_source"] == "image_ocr"
    assert events[0]["observation_provenance"] == ["accepted_refined"]
    assert (events[0]["start"], events[0]["end"]) == (22.6, 23.7)
    assert diagnostics["visual_only_count"] == 1
