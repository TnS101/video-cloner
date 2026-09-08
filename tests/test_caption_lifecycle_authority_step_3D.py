from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "scripts"
    / "davinci"
    / "caption_lifecycle_authority_step_3D.py"
)
SPEC = importlib.util.spec_from_file_location("lifecycle", MODULE_PATH)
assert SPEC and SPEC.loader
lifecycle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lifecycle)


def caption(cue_id: str, index: int, text: str, start: int, end: int, selected: bool = False):
    return {
        "cue_id": cue_id,
        "cue_index": index,
        "name": f"VC_TEXTPLUS_{index:04d}_{cue_id}",
        "text": text,
        "start_frame": start,
        "end_frame": end,
        "selected": selected,
        "animation": {"animation_type": "slide"} if selected else None,
    }


def track(cue_id: str, text: str, first: int, last: int, observations=None):
    return {
        "cue_id": cue_id,
        "text": text,
        "accepted_source_instance": True,
        "source_exactness": "source_redetected_dense_word_instance",
        "confidence": {"label": "high", "dense_observation_count": last - first + 1},
        "geometry": {"first_visible_frame": first, "last_visible_frame": last},
        "frame_observations": observations or [],
    }


def plan(captions, tracks):
    return lifecycle.build_plan({"tracks": tracks}, {"items": captions})


def test_visual_lifecycle_overrides_transcript_and_allows_overlap():
    captions = [
        caption("sub_001", 1, "COME", 100, 104, True),
        caption("sub_002", 2, "they", 104, 108),
    ]
    tracks = [
        track("sub_001", "come", 100, 152),
        track("sub_002", "they", 120, 130),
    ]
    result = plan(captions, tracks)
    come = result["layers"][0]
    assert come["text"] == "COME"
    assert come["text_authority"] == "transcript_primary"
    assert come["timing_authority"] == "visual_primary"
    assert come["lifecycle_window"] == [100, 153]
    assert come["ends_after_transcript_frames"] == 49
    assert "caption_layer_sub_002" in come["concurrent_visual_layer_ids"]


def test_transcript_text_wins_over_ocr_typo():
    result = plan(
        [caption("sub_001", 1, "THEY", 10, 14)],
        [track("sub_001", "thev", 9, 16)],
    )
    row = result["layers"][0]
    assert row["text"] == "THEY"
    assert row["visual_source_exactness"] == "source_redetected_dense_word_instance"


def test_selected_animation_without_visual_track_is_mandatory_redetection():
    result = plan([caption("sub_052", 52, "COME", 430, 434, True)], [])
    row = result["layers"][0]
    assert row["timing_authority"] == "transcript_fallback"
    assert row["requires_visual_lifecycle_redetection"] is True
    assert result["summary"]["mandatory_redetection_cue_ids"] == ["sub_052"]


def test_opacity_envelope_detects_entry_and_exit():
    observations = [
        {"timeline_frame": 1, "opacity_proxy": 0.1},
        {"timeline_frame": 2, "opacity_proxy": 0.7},
        {"timeline_frame": 3, "opacity_proxy": 1.0},
        {"timeline_frame": 4, "opacity_proxy": 0.8},
        {"timeline_frame": 5, "opacity_proxy": 0.2},
    ]
    result = plan(
        [caption("sub_001", 1, "word", 1, 4)],
        [track("sub_001", "word", 1, 5, observations)],
    )
    envelope = result["layers"][0]["opacity_envelope"]
    assert envelope["fade_in_detected"] is True
    assert envelope["fade_out_detected"] is True
    assert envelope["enter_end_frame"] == 3
    assert envelope["exit_start_frame"] == 4


def test_duplicate_caption_cue_is_rejected():
    duplicate = caption("sub_001", 1, "one", 1, 2)
    try:
        plan([duplicate, dict(duplicate)], [])
    except ValueError as exc:
        assert "duplicate_caption_plan_cue_id" in str(exc)
    else:
        raise AssertionError("expected duplicate rejection")
