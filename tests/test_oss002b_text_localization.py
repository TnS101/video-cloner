from __future__ import annotations

import pytest

from video_cloner.text_localization_oss import fallback_event, rank_candidates, text_similarity


def test_expected_caption_text_wins_over_nearby_text():
    ranked = rank_candidates(
        "scene",
        [
            {"bbox": [10, 10, 80, 30], "text": "biggest", "confidence": 0.99},
            {"bbox": [20, 40, 90, 65], "text": "scene", "confidence": 0.88},
        ],
        (100, 100),
    )
    assert ranked[0]["text"] == "scene"
    assert text_similarity("scene", ranked[0]["text"]) == 1.0


def test_fallback_fails_closed_when_expected_caption_is_absent():
    caption = {"ordinal": 44, "caption_id": "sub_044", "text": "scene", "start_frame": 243, "duration": 4}
    detections = {
        243: [{"bbox": [10, 10, 90, 30], "text": "biggest", "confidence": 0.99}],
        244: [{"bbox": [10, 10, 90, 30], "text": "THESE", "confidence": 0.99}],
        246: [{"bbox": [10, 10, 90, 30], "text": "biggest", "confidence": 0.99}],
    }
    with pytest.raises(ValueError, match="fallback_localization:44"):
        fallback_event(caption, 24.0, (100, 100), detections, "easyocr_fallback")


def test_successful_match_preserves_localization_provenance_and_visibility():
    caption = {"ordinal": 2, "caption_id": "sub_002", "text": "I", "start_frame": 5, "duration": 3}
    detections = {frame: [{"bbox": [40, 40, 50, 70], "text": "I", "confidence": 0.95}] for frame in (5, 6, 7)}
    event = fallback_event(caption, 24.0, (100, 100), detections, "easyocr_fallback")
    assert event["localization_source"] == "easyocr_fallback"
    assert event["localization_confidence"] > 0.8
    assert event["localization_evidence"]["first_visible_frame"] == 5
    assert event["localization_evidence"]["last_visible_frame"] == 7
    assert len(event["localization_evidence"]["frames"]) == 3
