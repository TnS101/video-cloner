from __future__ import annotations

import copy
import sys
import types

import pytest


if "paddleocr" not in sys.modules:
    paddleocr = types.ModuleType("paddleocr")
    paddleocr.PaddleOCR = object
    sys.modules["paddleocr"] = paddleocr

from scripts.analysis.detect_caption_style import apply_continuous_visual_identity_relations


def _det(
    tracklet_id,
    timestamp,
    bbox=(0.3, 0.2, 0.7, 0.28),
    *,
    text="sign",
    inferred_end=None,
    fill="#dcb999",
    stroke="#20221c",
    font_ratio=0.07,
    role="spoken_caption",
    provenance="accepted_direct",
):
    return {
        "tracklet_id": tracklet_id,
        "text": text,
        "bbox": [int(value * 1000) for value in bbox],
        "normalized_bbox": list(bbox),
        "observed_bbox": [int(value * 1000) for value in bbox],
        "observed_timestamp": timestamp,
        "inferred_visibility_end": timestamp + 0.1 if inferred_end is None else inferred_end,
        "estimated_text_color": fill,
        "estimated_stroke_color": stroke,
        "estimated_font_height_ratio": font_ratio,
        "caption_role": role,
        "observation_provenance": provenance,
        "is_caption_candidate": True,
    }


def _frames(*detections):
    return [{"timestamp": det["observed_timestamp"], "detections": [det]} for det in detections]


def _pairs(diagnostics):
    return {
        (link["predecessor_tracklet_id"], link["successor_tracklet_id"])
        for relation in diagnostics["relations"]
        for link in relation["links"]
    }


def test_four_independent_source_verified_relations_share_continuous_identities():
    rows = [
        _det("caption_tracklet_0014", 0.0, text="Setong", inferred_end=0.1),
        _det("caption_tracklet_0016", 0.267, text="Solang"),
        _det("caption_tracklet_0028", 2.0, text="sion", inferred_end=2.1),
        _det("caption_tracklet_0033", 2.6, text="Sian"),
        _det("caption_tracklet_0098", 4.0, text="vers", inferred_end=4.1),
        _det("caption_tracklet_0103", 4.3, text="Mers"),
        _det("caption_tracklet_0113", 6.0, text="PAMEILA", inferred_end=6.1),
        _det("caption_tracklet_0116", 6.3, text="PAMEILA"),
    ]
    diagnostics = apply_continuous_visual_identity_relations(_frames(*rows))

    assert _pairs(diagnostics) == {
        ("caption_tracklet_0014", "caption_tracklet_0016"),
        ("caption_tracklet_0028", "caption_tracklet_0033"),
        ("caption_tracklet_0098", "caption_tracklet_0103"),
        ("caption_tracklet_0113", "caption_tracklet_0116"),
    }
    assert rows[0]["continuous_visual_identity_id"] == rows[1]["continuous_visual_identity_id"]
    assert rows[2]["continuous_visual_identity_id"] == rows[3]["continuous_visual_identity_id"]
    assert diagnostics["transcript_used_for_eligibility"] is False


@pytest.mark.parametrize(
    ("left_text", "right_text"),
    [("behind", "scenes"), ("And", "from"), ("scenes", "personally"), ("in how", "home")],
)
def test_sequential_same_style_captions_do_not_stitch(left_text, right_text):
    left = _det("left", 0.0, text=left_text, inferred_end=0.1)
    right = _det("right", 0.3, text=right_text)
    diagnostics = apply_continuous_visual_identity_relations(_frames(left, right))

    assert not diagnostics["relations"]
    assert "continuous_visual_identity_id" not in left
    assert "continuous_visual_identity_id" not in right


def test_repeated_word_and_hierarchy_neighbors_remain_separate():
    first_we = _det("we_1", 0.0, (0.31, 0.22, 0.43, 0.26), text="We", inferred_end=0.1)
    second_we = _det("we_2", 0.4, (0.27, 0.23, 0.40, 0.28), text="We")
    upper_the = _det("upper_the", 1.0, (0.47, 0.19, 0.58, 0.23), text="the", inferred_end=2.0)
    lower_the = _det("lower_the", 1.0, (0.34, 0.41, 0.50, 0.46), text="the", inferred_end=2.0)
    before = _det("before", 3.0, (0.27, 0.19, 0.47, 0.22), text="before", inferred_end=3.1)
    sign = _det("sign", 3.2, (0.31, 0.21, 0.72, 0.28), text="sign")

    diagnostics = apply_continuous_visual_identity_relations(_frames(first_we, second_we, upper_the, lower_the, before, sign))

    assert not diagnostics["relations"]


def test_one_to_many_and_many_to_one_ambiguity_fail_closed():
    predecessor = _det("pred", 0.0, text="listing", inferred_end=0.1)
    successor_a = _det("successor_a", 0.3, text="listinq")
    successor_b = _det("successor_b", 0.3, text="listina")
    diagnostics = apply_continuous_visual_identity_relations(_frames(predecessor, successor_a, successor_b))
    assert not diagnostics["relations"]
    assert diagnostics["ambiguous_pair_count"] == 2

    predecessor_a = _det("predecessor_a", 2.0, text="buyers", inferred_end=2.1)
    predecessor_b = _det("predecessor_b", 2.0, text="buyars", inferred_end=2.1)
    successor = _det("successor", 2.4, text="buyors")
    diagnostics = apply_continuous_visual_identity_relations(_frames(predecessor_a, predecessor_b, successor))
    assert not diagnostics["relations"]
    assert diagnostics["ambiguous_pair_count"] == 2


def test_tracklet_role_must_overlap_despite_noisy_endpoint_role():
    left = _det("left", 0.0, text="Selling", inferred_end=0.1, role="spoken_caption")
    right_endpoint = _det("right", 0.3, text="Selang", role="hook_caption")
    right_stable = _det("right", 0.4, text="Selling", role="spoken_caption")

    diagnostics = apply_continuous_visual_identity_relations(_frames(left, right_endpoint, right_stable))

    assert _pairs(diagnostics) == {("left", "right")}


@pytest.mark.parametrize(
    ("field", "value"),
    [("estimated_text_color", None), ("estimated_stroke_color", None), ("estimated_font_height_ratio", None)],
)
def test_missing_required_style_fails_closed(field, value):
    left = _det("left", 0.0, text="PAMEILA", inferred_end=0.1)
    right = _det("right", 0.3, text="PAMEILA")
    right[field] = value

    assert not apply_continuous_visual_identity_relations(_frames(left, right))["relations"]


def test_ocr_below_threshold_and_gap_above_point_six_do_not_stitch():
    low_ocr_left = _det("low_ocr_left", 0.0, text="behind", inferred_end=0.1)
    low_ocr_right = _det("low_ocr_right", 0.3, text="scenes")
    late_left = _det("late_left", 2.0, text="PAMEILA", inferred_end=2.1)
    late_right = _det("late_right", 2.7001, text="PAMEILA")

    diagnostics = apply_continuous_visual_identity_relations(_frames(low_ocr_left, low_ocr_right, late_left, late_right))
    assert not diagnostics["relations"]


def test_exact_text_is_not_required_when_weak_ocr_corroborates():
    left = _det("left", 0.0, text="sion", inferred_end=0.1)
    right = _det("right", 0.6, text="Sian")

    diagnostics = apply_continuous_visual_identity_relations(_frames(left, right))
    assert _pairs(diagnostics) == {("left", "right")}


def test_6000_overlap_and_split_geometry_receive_no_bridge():
    whole = _det("caption_tracklet_0089", 0.0, (0.11, 0.19, 0.87, 0.34), text="6000", inferred_end=1.2)
    suffix = _det("caption_tracklet_0090", 1.1, (0.53, 0.24, 0.68, 0.28), text="ers")
    prefix = _det("caption_tracklet_0091", 1.1, (0.33, 0.23, 0.55, 0.28), text="buy")

    diagnostics = apply_continuous_visual_identity_relations(_frames(whole, suffix, prefix))
    assert not diagnostics["relations"]


def test_relation_preserves_provenance_and_geometry_without_fabricated_samples():
    left = _det("left", 0.0, text="sion", inferred_end=0.1, provenance="accepted_direct")
    right = _det("right", 0.6, text="Sian", provenance="rejected_visual_continuation")
    frames = _frames(left, right)
    original = copy.deepcopy(frames)

    diagnostics = apply_continuous_visual_identity_relations(frames)

    assert len(frames) == len(original) == 2
    assert sum(len(frame["detections"]) for frame in frames) == 2
    for before, after in zip(original, frames):
        before_det, after_det = before["detections"][0], after["detections"][0]
        assert after_det["bbox"] == before_det["bbox"]
        assert after_det["normalized_bbox"] == before_det["normalized_bbox"]
        assert after_det["observed_bbox"] == before_det["observed_bbox"]
        assert after_det["observation_provenance"] == before_det["observation_provenance"]
    relation = diagnostics["relations"][0]
    assert relation["observed_start"] == 0.0
    assert relation["last_observed"] == 0.6
    assert relation["inferred_visibility_end"] == 0.7
    assert [window["tracklet_id"] for window in relation["tracklet_windows"]] == ["left", "right"]


def test_gap_is_seconds_based_and_frame_rate_independent():
    for frame_indices in ((0, 14), (0, 36)):
        left = _det(f"left_{frame_indices[1]}", 0.0, text="buyers", inferred_end=0.1)
        right = _det(f"right_{frame_indices[1]}", 0.6, text="buyars")
        left["frame_index"], right["frame_index"] = frame_indices
        assert apply_continuous_visual_identity_relations(_frames(left, right))["linked_pair_count"] == 1


def test_natural_chain_requires_each_pairwise_link_and_shares_one_identity():
    first = _det("first", 0.0, text="PAMEILA", inferred_end=0.1)
    middle = _det("middle", 0.3, text="PAMEILA", inferred_end=0.4)
    last = _det("last", 0.6, text="PAMEILA")

    diagnostics = apply_continuous_visual_identity_relations(_frames(first, middle, last))

    assert _pairs(diagnostics) == {("first", "middle"), ("middle", "last")}
    assert len({first["continuous_visual_identity_id"], middle["continuous_visual_identity_id"], last["continuous_visual_identity_id"]}) == 1
