from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

from scripts.davinci import compile_davinci_textplus_fcpxml as canonical
from scripts.standalone import video_cloner_caption_lifecycle as lifecycle


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


def event(cue_id: str, text: str, *, count: int = 2, suffix: str = "") -> dict:
    return {
        "event_id": f"event_{cue_id}{suffix}",
        "cue_id": cue_id,
        "observed_text": text,
        "observed_texts": [text] * count,
        "observations": [
            {"timestamp": 0.4 + i / 10, "text": text, "bbox": [20, 20, 80, 50], "caption_score": 0.9}
            for i in range(count)
        ],
    }


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


def run(tmp_path: Path, monkeypatch, cues, events, tracker=accepted_track):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"deterministic-test-video")
    monkeypatch.setattr(lifecycle.dense.cv2, "VideoCapture", lambda _: FakeCapture())
    return lifecycle.generate_lifecycle(cues, {"caption_style_events": events}, source, 10, tracker=tracker)


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


def test_many_to_one_authority_remains_one_lifecycle_row(tmp_path: Path, monkeypatch):
    authority = [cue(65, "6000", 20, 28, ["sub_065", "sub_066"])]
    result = run(tmp_path, monkeypatch, authority, [event("sub_0066", "6000")])
    assert len(result["layers"]) == 1
    assert result["layers"][0]["cue_id"] == "sub_065"
    assert result["layers"][0]["text"] == "6000"


def test_lane_allocation_is_deterministic_from_generated_overlaps(tmp_path: Path, monkeypatch):
    cues = [cue(1, "one", 0, 4), cue(2, "two", 4, 8)]
    result = run(tmp_path, monkeypatch, cues, [event("sub_0001", "one"), event("sub_0002", "two")])
    first, first_info = canonical.apply_caption_lifecycle_plan(copy.deepcopy(cues), result, fps=10)
    second, second_info = canonical.apply_caption_lifecycle_plan(copy.deepcopy(cues), result, fps=10)
    assert [row["lane"] for row in first] == [1, 2]
    assert [row["lane"] for row in first] == [row["lane"] for row in second]
    assert first_info["lane_allocation"] == second_info["lane_allocation"]
