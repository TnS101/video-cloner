from __future__ import annotations

import importlib.util
from pathlib import Path

import cv2
import numpy as np

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "davinci" / "redetect_caption_lifecycle_step_3D.py"
SPEC = importlib.util.spec_from_file_location("lifecycle_redetection", MODULE_PATH)
assert SPEC and SPEC.loader
redetect = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(redetect)


def test_segment_around_seed_preserves_visual_lifetime_outside_transcript():
    frames = list(range(100, 141))
    scores = [0.12] * 5 + [0.38, 0.56, 0.72, 0.85] + [0.92] * 26 + [0.76, 0.58, 0.43, 0.31] + [0.12] * 2
    result = redetect.segment_around_seed(frames, scores, seed_frame=112)
    assert result["first_visible_source_frame"] <= 106
    assert result["last_visible_source_frame"] >= 136
    assert result["exit_start_source_frame"] is not None


def test_template_match_tracks_text_like_shape():
    image = np.zeros((120, 360, 3), dtype=np.uint8)
    cv2.putText(image, "COME", (90, 78), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 4, cv2.LINE_AA)
    template = image[30:90, 80:250].copy()
    shifted = np.zeros_like(image)
    cv2.putText(shifted, "COME", (112, 78), cv2.FONT_HERSHEY_SIMPLEX, 1.8, (255, 255, 255), 4, cv2.LINE_AA)
    result = redetect.multi_scale_match(shifted, template)
    assert result["score"] > 0.45


def test_calibrated_plan_removes_mandatory_queue_and_preserves_text():
    layers = []
    for index in range(1, 117):
        cue = f"sub_{index:03d}"
        layers.append({
            "layer_id": f"caption_layer_{cue}",
            "cue_id": cue,
            "text": "COME" if cue == "sub_052" else cue,
            "text_authority": "transcript_primary",
            "timing_authority": "transcript_fallback",
            "transcript_window": [index * 5, index * 5 + 4],
            "lifecycle_window": [index * 5, index * 5 + 4],
            "animation_selected_step_3C": cue in redetect.EXPECTED_CUES,
            "requires_visual_lifecycle_redetection": cue in redetect.EXPECTED_CUES,
            "concurrent_transcript_cue_ids": [],
            "concurrent_visual_layer_ids": [],
        })
    authority = {
        "ok": True,
        "layers": layers,
        "summary": {"caption_layer_count": 116},
        "checks": {"caption_count_matches_plan": True},
        "mandatory_visual_redetection_queue": [{"cue_id": cue} for cue in redetect.EXPECTED_CUES],
    }
    detections = []
    for cue in redetect.EXPECTED_CUES:
        layer = next(row for row in layers if row["cue_id"] == cue)
        detections.append({
            "cue_id": cue,
            "lifecycle_window": [layer["transcript_window"][0] - 2, layer["transcript_window"][1] + 8],
            "lifecycle_phases": {"entry": [0, 1], "hold": [1, 8], "exit": [8, 10]},
            "starts_before_transcript_frames": 2,
            "starts_after_transcript_frames": 0,
            "ends_after_transcript_frames": 8,
            "ends_before_transcript_frames": 0,
            "crosses_transcript_boundaries": True,
            "confidence": "high",
            "observations": [{"timeline_frame": 1}] * 8,
            "contact_sheet": f"{cue}.jpg",
            "source_seed": {},
            "tracking": {},
        })
    plan = redetect.calibrated_plan(authority, detections)
    assert plan["ok"] is True
    assert plan["mandatory_visual_redetection_queue"] == []
    assert plan["summary"]["selected_animation_visual_primary_count"] == 4
    assert next(row for row in plan["layers"] if row["cue_id"] == "sub_052")["text"] == "COME"


def test_timeline_conversion_uses_project_24fps():
    assert redetect.timeline_frame(300, 30.0) == 240


def test_detect_cue_tracks_hold_and_fade_from_source_video(tmp_path):
    video = tmp_path / "source.mp4"
    width, height, fps, frames = 360, 240, 30.0, 120
    writer = cv2.VideoWriter(
        str(video),
        cv2.VideoWriter_fourcc(*"mp4v"),
        fps,
        (width, height),
    )
    assert writer.isOpened()
    for frame_index in range(frames):
        image = np.zeros((height, width, 3), dtype=np.uint8)
        image[:] = (24, 24, 24)
        if 20 <= frame_index <= 84:
            x = 72 if frame_index >= 30 else 42 + (frame_index - 20) * 3
            alpha = 1.0 if frame_index <= 72 else max(0.12, (84 - frame_index) / 12.0)
            overlay = image.copy()
            cv2.putText(
                overlay,
                "COME",
                (x, 130),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.5,
                (255, 255, 255),
                4,
                cv2.LINE_AA,
            )
            image = cv2.addWeighted(overlay, alpha, image, 1.0 - alpha, 0)
        writer.write(image)
    writer.release()

    capture = cv2.VideoCapture(str(video))
    assert capture.isOpened()
    audit = {
        "cue_id": "sub_052",
        "cue_index": 52,
        "name": "VC_TEXTPLUS_0052_sub_052",
        "text": "COME",
        "geometry_exactness": "cue_instance_clean",
        "source_animation_detected": True,
        "source_bbox": [70 / width, 85 / height, 245 / width, 145 / height],
    }
    animation = {
        "start_frame": 16,
        "end_frame": 24,
        "animation": {
            "source_event_id": "style_event_sub_0052",
            "source_start": 20 / fps,
            "source_end": 30 / fps,
        },
    }
    result = redetect.detect_cue(
        capture,
        fps,
        frames,
        width,
        height,
        audit,
        animation,
        tmp_path / "debug",
    )
    capture.release()
    assert result["lifecycle_window"][0] <= 18
    assert result["lifecycle_window"][1] >= 64
    assert result["ends_after_transcript_frames"] > 30
    assert Path(result["contact_sheet"]).is_file()
