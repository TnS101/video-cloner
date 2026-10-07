from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest

from video_cloner.resolve import fcpxml as canonical
from video_cloner.captions import lifecycle


def cue(index: int, text: str, start: int, end: int, source_ids=None) -> dict:
    return {
        "id": f"sub_{index:03d}",
        "index": index,
        "text": text,
        "start_frame": start,
        "end_frame": end,
        "start": start / 10,
        "end": end / 10,
        "source_cue_ids": source_ids or [f"sub_{index:03d}"],
    }


def event(cue_id: str, text: str, *, count: int = 2, suffix: str = "", visual_identity: str = "") -> dict:
    row = {
        "event_id": f"event_{cue_id}{suffix}",
        "cue_id": cue_id,
        "style_profile_id": "style_test",
        "match": {"reason": "accepted"},
        "observed_text": text,
        "observed_texts": [text] * count,
        "observations": [
            {"timestamp": 0.4 + i / 10, "text": text, "bbox": [20, 20, 80, 50], "caption_score": 0.9}
            for i in range(count)
        ],
    }
    if visual_identity:
        row["visual_event_identity"] = visual_identity
    return row


class FakeCapture:
    def isOpened(self):
        return True

    def get(self, prop):
        values = {
            lifecycle.dense.cv2.CAP_PROP_FPS: 10,
            lifecycle.dense.cv2.CAP_PROP_FRAME_COUNT: 100,
            lifecycle.dense.cv2.CAP_PROP_FRAME_WIDTH: 100,
            lifecycle.dense.cv2.CAP_PROP_FRAME_HEIGHT: 100,
        }
        return values[prop]

    def release(self):
        pass


def accepted_track(*args) -> dict:
    cue_row = args[6]
    start = int(cue_row["start_frame"])
    return {
        "cue_id": cue_row["id"],
        "text": cue_row["text"],
        "accepted_source_instance": True,
        "source_exactness": "source_video_dense_template_track",
        "confidence": {"label": "high", "dense_observation_count": 5},
        "geometry": {"first_visible_frame": start, "last_visible_frame": start + 4},
        "frame_observations": [],
        "boundary_evidence": {"left_proven": True, "right_proven": True},
    }


def run(tmp_path: Path, monkeypatch, cues, events, tracker=accepted_track, accepted_motion=None):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"deterministic-test-video")
    monkeypatch.setattr(lifecycle.dense.cv2, "VideoCapture", lambda _: FakeCapture())
    return lifecycle.generate_lifecycle(
        cues, {"caption_style_events": events}, source, 10,
        tracker=tracker, accepted_motion=accepted_motion,
    )


def test_explicit_product_motion_overlays_current_observations(tmp_path: Path, monkeypatch):
    social = event("sub_0045", "social,", visual_identity="caption_tracklet_0064")
    social.update({"event_id": "style_event_caption_tracklet_0064", "start": 36.5, "end": 37.6})
    fragment = event("sub_0045", "so", count=1, visual_identity="caption_tracklet_0066")
    fragment.update({"event_id": "style_event_caption_tracklet_0066", "start": 37.6, "end": 37.7})
    launching = event("sub_0088", "launching")
    accepted = json.loads(
        (Path(__file__).parents[1] / "config" / "DcJRJtUKScu.accepted_caption_motion.json")
        .read_text(encoding="utf-8")
    )
    assert accepted["window"] == [359, 383]
    assert accepted["animation"] == {
        "authority": "visual_observed",
        "source_type": "scale",
        "property": "Size",
        "keyframes": [
            {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
            {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
        ],
    }

    result = run(
        tmp_path, monkeypatch,
        [cue(45, "social,", 365, 376), cue(88, "launching", 721, 737)],
        [social, fragment, launching], accepted_motion=accepted,
    )
    layers = {row["cue_id"]: row for row in result["layers"]}
    assert layers["sub_045"]["lifecycle_window"] == [359, 383]
    assert layers["sub_045"]["visual_source_exactness"] == "source_video_dense_template_track"
    assert layers["sub_088"]["visual_source_exactness"] == "source_video_dense_template_track_observation_only"
    social_token = result["visual_compositions"][0]["tokens"][0]
    assert social_token["visual_event_identity"] == "caption_tracklet_0064"
    assert social_token["style_evidence_id"] == "style_event_caption_tracklet_0064"
    assert social_token["accepted_motion_authority"]["source_visual_event_identity"] == "caption_tracklet_0064"
    assert social_token["accepted_motion_authority"]["source_evidence_id"] == "style_event_caption_tracklet_0064"
    assert all(
        token.get("visual_event_identity") != "caption_tracklet_0066"
        for composition in result["visual_compositions"]
        for token in composition["tokens"]
        if token.get("accepted_motion_authority")
    )
    assert social_token["accepted_motion_authority"]["keyframes"] == [
        {"frame": 0, "relative_time": 0.0, "value": 0.080528214},
        {"frame": 23, "relative_time": 1.0, "value": 0.10833333333333332},
    ]
    assert result["summary"]["accepted_product_motion_count"] == 1


def test_visual_motion_owner_zero_multiple_and_wrong_cue_fail_closed():
    accepted = json.loads(
        (Path(__file__).parents[1] / "config" / "DcJRJtUKScu.accepted_caption_motion.json")
        .read_text(encoding="utf-8")
    )
    owner = event("sub_0045", "social,", visual_identity="caption_tracklet_0064")
    owner["event_id"] = "style_event_caption_tracklet_0064"

    for rows in ([], [owner, {**copy.deepcopy(owner), "event_id": "duplicate"}], [{**owner, "cue_id": "sub_0046"}]):
        with pytest.raises(lifecycle.LifecycleGenerationError, match="does not match current evidence"):
            lifecycle._accepted_motion_decision(accepted, [cue(45, "social,", 365, 376)], rows)


def test_legacy_motion_owner_keeps_event_id_behavior_and_cue_normalization():
    accepted = json.loads(
        (Path(__file__).parents[1] / "config" / "DcJRJtUKScu.accepted_caption_motion.json")
        .read_text(encoding="utf-8")
    )
    accepted.pop("visual_event_identity")
    owner = event("sub_0045", "social,")
    owner["event_id"] = "style_event_sub_0045"

    decision = lifecycle._accepted_motion_decision(accepted, [cue(45, "social,", 365, 376)], [owner])

    assert decision["cue_id"] == "sub_045"
    assert decision["style_evidence_id"] == "style_event_sub_0045"
    assert "visual_event_identity" not in decision
    assert "source_visual_event_identity" not in decision["animation"]


def test_dense_template_track_proves_half_open_visual_boundaries():
    class Frames:
        def __init__(self, rows):
            self.rows = rows
            self.index = 0

        def set(self, _prop, value):
            self.index = int(value)

        def read(self):
            return True, self.rows[self.index].copy()

    frames = []
    for index in range(12):
        frame = np.zeros((96, 192, 3), dtype=np.uint8)
        if 3 <= index <= 7:
            lifecycle.dense.cv2.putText(
                frame, "WORD", (40, 55), lifecycle.dense.cv2.FONT_HERSHEY_SIMPLEX,
                0.8, (255, 255, 255), 2, lifecycle.dense.cv2.LINE_AA,
            )
        frames.append(frame)
    result = lifecycle._dense_track(
        Frames(frames), 12, 192, 96, 10, 10,
        cue(1, "word", 3, 8),
        {"observations": [
            {"timestamp": 0.4, "text": "word", "bbox": [38, 34, 118, 60], "caption_score": 1},
            {"timestamp": 0.5, "text": "word", "bbox": [38, 34, 118, 60], "caption_score": 1},
        ]},
        0.3,
    )
    assert result["geometry"] == {"first_visible_frame": 3, "last_visible_frame": 7}
    assert result["boundary_evidence"]["left_proven"] is True
    assert result["boundary_evidence"]["right_proven"] is True


def test_output_is_deterministic_complete_and_compiler_safe(tmp_path: Path, monkeypatch):
    cues = [cue(1, "one", 0, 4), cue(2, "two", 4, 8)]
    events = [event("sub_0001", "one")]
    first = run(tmp_path, monkeypatch, cues, events)
    second = run(tmp_path, monkeypatch, copy.deepcopy(cues), copy.deepcopy(events))
    assert first == second
    assert [row["cue_id"] for row in first["layers"]] == ["sub_001", "sub_002"]
    assert [row["timing_authority"] for row in first["layers"]] == ["visual_primary", "transcript_fallback"]
    assert first["layers"][1]["lifecycle_window"] == first["layers"][1]["transcript_window"]
    assert first["mandatory_visual_redetection_queue"] == []
    assert all(row["lifecycle_window"][1] > row["lifecycle_window"][0] for row in first["layers"])
    applied, info = canonical.apply_caption_lifecycle_plan(copy.deepcopy(cues), first, fps=10)
    assert info["lane_allocation"]["lane_count"] == 2
    assert [row["lane"] for row in applied] == [1, 2]


def test_unique_accepted_style_event_window_precedes_dense_tracking(tmp_path: Path, monkeypatch):
    row = event("sub_0001", "one")
    row.update({"start": 0.2, "end": 0.7})

    def forbidden_tracker(*_args):
        raise AssertionError("accepted event window must precede dense tracking")

    result = run(tmp_path, monkeypatch, [cue(1, "one", 0, 9)], [row], forbidden_tracker)
    layer = result["layers"][0]
    assert layer["timing_authority"] == "visual_primary"
    assert layer["lifecycle_window"] == [2, 7]
    assert result["diagnostics"] == []
    assert result["visual_compositions"][0]["authority"]["reason"] == "accepted_visual_style_event_window"
    assert result["summary"]["visual_style_event_window_count"] == 1
    assert result["summary"]["dense_tracker_count"] == 0


def test_group_style_event_is_not_caption_lifecycle_evidence(tmp_path: Path, monkeypatch):
    row = event("1", "one")
    row.update({"start": 0.2, "end": 0.7})
    result = run(tmp_path, monkeypatch, [cue(1, "one", 0, 9)], [row])
    assert result["layers"][0]["timing_authority"] == "transcript_fallback"
    assert result["diagnostics"] == []


def test_accepted_event_overlap_retains_independent_token_windows(tmp_path: Path, monkeypatch):
    first = event("sub_0001", "one")
    second = event("sub_0002", "two")
    first.update({"start": 0.1, "end": 0.5})
    second.update({"start": 0.3, "end": 0.8})
    result = run(tmp_path, monkeypatch, [cue(1, "one", 1, 5), cue(2, "two", 5, 8)], [first, second])
    composition = result["visual_compositions"][0]
    assert composition["relation"]["mode"] == "simultaneous"
    assert composition["window"] == [1, 8]
    assert [token["window"] for token in composition["tokens"]] == [[1, 5], [3, 8]]
    assert result["summary"]["visual_concurrent_overlap_pair_count"] == 1


def test_unproven_boundary_falls_back_and_records_redetection(tmp_path: Path, monkeypatch):
    def unproven(*args):
        result = accepted_track(*args)
        result["boundary_evidence"]["right_proven"] = False
        return result

    result = run(tmp_path, monkeypatch, [cue(1, "one", 1, 5)], [event("sub_0001", "one")], unproven)
    layer = result["layers"][0]
    assert layer["timing_authority"] == "transcript_fallback"
    assert layer["lifecycle_window"] == layer["transcript_window"]
    assert result["summary"]["needs_redetection_count"] == 1
    assert result["mandatory_visual_redetection_queue"] == []


def test_ambiguous_and_contaminated_associations_fail_closed(tmp_path: Path, monkeypatch):
    cues = [cue(1, "one", 1, 5), cue(2, "two", 5, 9)]
    events = [
        event("sub_0001", "one", suffix="a"),
        event("sub_0001", "one", suffix="b"),
        event("sub_0002", "two words"),
    ]
    result = run(tmp_path, monkeypatch, cues, events)
    assert [row["timing_authority"] for row in result["layers"]] == ["transcript_fallback"] * 2
    assert [row["reason"] for row in result["diagnostics"]] == [
        "ambiguous_source_association",
        "contaminated_or_insufficient_ocr_seed",
    ]


def test_supported_motion_uses_only_exact_observations_and_normalized_boxes(tmp_path: Path, monkeypatch):
    row = event("sub_0045", "social", count=4)
    row["observed_texts"] = ["socid", "social", "social", "social for"]
    row["observations"] = [
        {
            "timestamp": 15.1 + index / 10,
            "text": text,
            "bbox": [400, 700, 700, 800],
            "normalized_bbox": [0.3, 0.35, 0.7, 0.45],
            "caption_score": 0.9,
        }
        for index, text in enumerate(row["observed_texts"])
    ]
    row["animation"] = {
        "detected": True,
        "type": "scale",
        "style": "scale",
        "confidence": 0.7,
        "samples": 4,
        "keyframes": [
            {"timestamp": 15.1, "relative_time": 0.0, "scale": 0.8},
            {"timestamp": 15.4, "relative_time": 1.0, "scale": 1.0},
        ],
    }
    row.update({"start": 36.5, "end": 37.6})

    def exact_motion_track(*args):
        observations = args[7]["observations"]
        assert [item["text"] for item in observations] == ["social", "social"]
        assert all(item["bbox"] == item["normalized_bbox"] for item in observations)
        result = accepted_track(*args)
        result["geometry"] = {"first_visible_frame": 359, "last_visible_frame": 382}
        return result

    result = run(
        tmp_path,
        monkeypatch,
        [cue(45, "social,", 365, 376)],
        [row],
        exact_motion_track,
    )
    composition = result["visual_compositions"][0]
    assert composition["composition_id"] == "visual_composition_sub_045"
    assert composition["authority"]["kind"] == "visual_primary"
    assert composition["window"] == [359, 383]
    assert composition["tokens"][0]["style_evidence_id"] == "event_sub_0045"


def test_partial_exact_observations_do_not_expand_static_caption_authority(tmp_path: Path, monkeypatch):
    row = event("sub_0001", "one", count=3)
    row["observed_texts"] = ["one", "noise", "one"]
    row["observations"] = [
        {"timestamp": 0.4 + index / 10, "text": text, "bbox": [20, 20, 80, 50], "caption_score": 0.9}
        for index, text in enumerate(row["observed_texts"])
    ]
    result = run(tmp_path, monkeypatch, [cue(1, "one", 1, 5)], [row])
    assert result["visual_compositions"][0]["authority"] == {
        "kind": "unresolved",
        "evidence_ids": ["event_sub_0001"],
        "reason": "contaminated_or_insufficient_ocr_seed",
    }


def test_many_to_one_authority_remains_one_lifecycle_row(tmp_path: Path, monkeypatch):
    authority = [cue(65, "6000", 20, 28, ["sub_065", "sub_066"])]
    result = run(tmp_path, monkeypatch, authority, [event("sub_0066", "6000")])
    assert len(result["layers"]) == 1
    assert result["layers"][0]["cue_id"] == "sub_065"
    assert result["layers"][0]["text"] == "6000"
    token = result["visual_compositions"][0]["tokens"][0]
    assert token["text"] == "6000"
    assert token["semantic_ids"] == ["sub_065", "sub_066"]


def test_multiword_visible_state_remains_one_visual_composition(tmp_path: Path, monkeypatch):
    authority = [cue(1, "We don't", 0, 8, ["sub_001", "sub_002"])]
    result = run(tmp_path, monkeypatch, authority, [event("sub_0002", "We don't")])
    composition = result["visual_compositions"][0]
    assert composition["authority"]["kind"] == "visual_primary"
    assert composition["tokens"] == [{
        "token_id": "visual_token_sub_001",
        "text": "We don't",
        "semantic_ids": ["sub_001", "sub_002"],
        "window": [0, 5],
        "style_ref": "style_test",
        "style_evidence_id": "event_sub_0002",
    }]


def test_visual_token_retains_exact_accepted_style_event(tmp_path: Path, monkeypatch):
    result = run(tmp_path, monkeypatch, [cue(1, "one", 1, 5)], [event("sub_0001", "one")])
    assert result["visual_compositions"][0]["tokens"][0] == {
        "token_id": "visual_token_sub_001",
        "text": "one",
        "semantic_ids": ["sub_001"],
        "window": [1, 6],
        "style_ref": "style_test",
        "style_evidence_id": "event_sub_0001",
    }


def test_overlapping_visual_tokens_share_one_simultaneous_composition(tmp_path: Path, monkeypatch):
    cues = [cue(61, "calling", 493, 514), cue(62, "and", 493, 514)]
    result = run(tmp_path, monkeypatch, cues, [event("sub_0061", "calling"), event("sub_0062", "and")])
    composition = result["visual_compositions"][0]
    assert composition["relation"]["mode"] == "simultaneous"
    assert [token["text"] for token in composition["tokens"]] == ["calling", "and"]
    assert [token["window"] for token in composition["tokens"]] == [[493, 498], [493, 498]]


def test_conflicting_visual_evidence_is_unresolved_not_fallback(tmp_path: Path, monkeypatch):
    result = run(
        tmp_path, monkeypatch, [cue(1, "one", 1, 5)],
        [event("sub_0001", "one", suffix="a"), event("sub_0001", "one", suffix="b")],
    )
    assert result["visual_compositions"][0]["authority"]["kind"] == "unresolved"


def test_lane_allocation_is_deterministic_from_generated_overlaps(tmp_path: Path, monkeypatch):
    cues = [cue(1, "one", 0, 4), cue(2, "two", 4, 8)]
    result = run(tmp_path, monkeypatch, cues, [event("sub_0001", "one"), event("sub_0002", "two")])
    first, first_info = canonical.apply_caption_lifecycle_plan(copy.deepcopy(cues), result, fps=10)
    second, second_info = canonical.apply_caption_lifecycle_plan(copy.deepcopy(cues), result, fps=10)
    assert [row["lane"] for row in first] == [1, 2]
    assert [row["lane"] for row in first] == [row["lane"] for row in second]
    assert first_info["lane_allocation"] == second_info["lane_allocation"]


def test_simultaneous_parent_window_is_order_independent_union():
    cues = [cue(7, "We", 49, 53), cue(8, "launch", 52, 62)]
    events = [event("sub_0007", "We"), event("sub_0008", "launch")]

    def layers(order):
        return [
            {
                "cue_id": row["id"],
                "timing_authority": "visual_primary",
                "lifecycle_window": window,
            }
            for row, window in order
        ]

    forward = lifecycle._visual_compositions(
        cues,
        events,
        layers([(cues[0], [49, 53]), (cues[1], [48, 63])]),
        [],
    )
    reverse = lifecycle._visual_compositions(
        list(reversed(cues)),
        events,
        layers([(cues[1], [48, 63]), (cues[0], [49, 53])]),
        [],
    )

    assert forward[0]["window"] == [48, 63]
    assert reverse[0]["window"] == [48, 63]
    assert all(
        composition["window"][0] <= token["window"][0]
        and token["window"][1] <= composition["window"][1]
        for composition in forward + reverse
        for token in composition["tokens"]
    )
