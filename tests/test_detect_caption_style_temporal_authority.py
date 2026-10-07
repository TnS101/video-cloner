from __future__ import annotations

import math
import sys
import types

import pytest


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from scripts.analysis.detect_caption_style import (
    _compatible_continuation,
    apply_short_caption_continuations,
    observation_timestamps,
)


def _det(
    bbox=(0.4, 0.4, 0.6, 0.5),
    *,
    accepted=True,
    reason=None,
    text="sign",
    source="direct",
):
    return {
        "text": text,
        "bbox": [int(value * 1000) for value in bbox],
        "normalized_bbox": list(bbox),
        "classifier_accepted": accepted,
        "is_caption_candidate": accepted,
        "is_subtitle_candidate": accepted,
        "source_provenance": source,
        "caption_role": "spoken_caption" if accepted else None,
        "caption_score": {"reason": reason or ("transcript_matched_caption" if accepted else "low_caption_score")},
    }


def _frames(*rows):
    return [{"timestamp": timestamp, "detections": detections} for timestamp, detections in rows]


def test_schedule_unions_floor_and_preferred_on_valid_source_frames():
    timestamps = observation_timestamps(1.0, 24.0, 24, [0.041, 0.333, 0.333])

    assert any(math.isclose(timestamp, 1 / 24, abs_tol=1e-6) for timestamp in timestamps)
    assert any(math.isclose(timestamp, 8 / 24, abs_tol=1e-6) for timestamp in timestamps)
    assert len(timestamps) == len(set(timestamps))
    assert all(math.isclose(timestamp * 24, round(timestamp * 24), abs_tol=1e-5) for timestamp in timestamps)
    assert max(timestamps) <= 23 / 24


def test_schedule_is_ten_fps_floor_not_full_fps_and_is_frame_rate_generic():
    for fps in (24.0, 60.0):
        timestamps = observation_timestamps(2.0, fps, int(2 * fps))
        assert len(timestamps) == 20
        assert len(timestamps) < int(2 * fps)
        assert max(b - a for a, b in zip(timestamps, timestamps[1:])) <= 0.1 + (1.0 / fps) + 1e-6


def test_rejected_evidence_never_seeds_and_other_rejection_classes_are_ineligible():
    frames = _frames((0.0, [_det(accepted=False)]), (0.1, [_det(accepted=False, reason="noise_text")]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert all(not frame["caption_candidates"] for frame in frames)
    assert all("tracklet_id" not in det for frame in frames for det in frame["detections"])


def test_text_mismatch_low_score_tail_continues_with_explicit_provenance_and_grace():
    seed = _det(text="sign")
    tail = _det(accepted=False, text="totally different")
    frames = _frames((0.0, [seed]), (0.2, [tail]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert tail["tracklet_id"] == seed["tracklet_id"]
    assert tail["observation_provenance"] == "rejected_visual_continuation"
    assert tail["observed_bbox"] == tail["bbox"]
    assert tail["inferred_visibility_end"] == 0.3
    assert tail["visibility_interval_semantics"] == "half_open"


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ((0.40, 0.40, 0.60, 0.50), (0.48, 0.40, 0.68, 0.50)),  # IoU below 0.45
        ((0.40, 0.40, 0.60, 0.50), (0.461, 0.40, 0.661, 0.50)),  # center distance above 0.06
        ((0.40, 0.40, 0.60, 0.50), (0.40, 0.40, 0.60, 0.449)),  # area ratio above 2
        ((0.40, 0.40, 0.60, 0.50), (0.40, 0.40, 0.52, 0.50)),  # aspect ratio above 1.6
    ],
)
def test_each_geometry_threshold_rejects_out_of_contract_match(left, right):
    assert not _compatible_continuation(_det(left), _det(right))


def test_geometry_threshold_boundaries_are_inclusive():
    base = _det((0.40, 0.40, 0.60, 0.50))
    same = _det((0.40, 0.40, 0.60, 0.50))
    assert _compatible_continuation(base, same)


def test_gap_over_point_two_seconds_does_not_bridge_6000_or_any_identity():
    seed = _det(text="6000")
    tail = _det(accepted=False, text="6000")
    frames = _frames((0.0, [seed]), (0.2001, [tail]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert "tracklet_id" not in tail
    assert not frames[1]["caption_candidates"]


def test_direct_and_refined_reacquisition_restore_strong_authority():
    seed = _det()
    rejected = _det(accepted=False, text="sion")
    refined = _det(source="crop_refined_child", text="Sian")
    frames = _frames((0.0, [seed]), (0.1, [rejected]), (0.2, [refined]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert len({seed["tracklet_id"], rejected["tracklet_id"], refined["tracklet_id"]}) == 1
    assert seed["observation_provenance"] == "accepted_direct"
    assert refined["observation_provenance"] == "accepted_refined"


def test_repeated_words_remain_separate_by_geometry_and_assign_one_to_one():
    upper = _det((0.2, 0.2, 0.35, 0.28), text="the")
    lower = _det((0.2, 0.7, 0.35, 0.78), text="the")
    upper_tail = _det((0.2, 0.2, 0.35, 0.28), accepted=False, text="x")
    lower_tail = _det((0.2, 0.7, 0.35, 0.78), accepted=False, text="y")
    frames = _frames((0.0, [upper, lower]), (0.1, [lower_tail, upper_tail]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert upper["tracklet_id"] != lower["tracklet_id"]
    assert upper_tail["tracklet_id"] == upper["tracklet_id"]
    assert lower_tail["tracklet_id"] == lower["tracklet_id"]


def test_known_dont_low_score_continuation_stays_on_its_geometry():
    dont = _det((0.25, 0.24, 0.58, 0.31), text="don't")
    nearby_other = _det((0.62, 0.24, 0.78, 0.31), text="We")
    dont_tail = _det((0.26, 0.24, 0.59, 0.31), accepted=False, text="dont")
    frames = _frames((0.0, [dont, nearby_other]), (0.1, [dont_tail]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert dont_tail["tracklet_id"] == dont["tracklet_id"]
    assert dont_tail["tracklet_id"] != nearby_other["tracklet_id"]


def test_visibility_grace_clamps_to_source_end_without_fabricating_geometry():
    seed = _det()
    frames = _frames((0.95, [seed]))
    apply_short_caption_continuations(frames, 0.1, 1.0)

    assert seed["inferred_visibility_end"] == 1.0
    assert seed["observed_bbox"] == seed["bbox"]
    assert len(frames) == 1
