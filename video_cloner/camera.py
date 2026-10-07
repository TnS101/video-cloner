"""Build a bounded camera-style profile from motion analysis and face samples."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


SCHEMA = "video_cloner.camera_style.v1"


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sample_times(start: float, end: float, count: int) -> list[float]:
    if end <= start:
        return []
    margin = min(0.08, (end - start) * 0.1)
    return [float(value) for value in np.linspace(start + margin, end - margin, max(1, count))]


def _primary_face(cascade: cv2.CascadeClassifier, frame: np.ndarray) -> tuple[int, int, int, int] | None:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    minimum = max(24, int(min(frame.shape[:2]) * 0.07))
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(minimum, minimum))
    return max(faces, key=lambda box: int(box[2]) * int(box[3])) if len(faces) else None


def collect_face_observations(video_path: Path, segments: list[dict], samples_per_shot: int) -> list[dict]:
    cascade_path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(str(cascade_path))
    if cascade.empty():
        raise RuntimeError(f"OpenCV face cascade unavailable: {cascade_path}")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 24.0)
    observations: list[dict] = []
    try:
        for segment in segments:
            shot_id = segment.get("shot_id")
            start = float(segment.get("start_seconds") or 0.0)
            end = float(segment.get("end_seconds") or start)
            for time_sec in _sample_times(start, end, samples_per_shot):
                capture.set(cv2.CAP_PROP_POS_MSEC, time_sec * 1000.0)
                ok, frame = capture.read()
                row = {"shot_id": shot_id, "time_sec": round(time_sec, 4), "detected": False}
                if ok and frame is not None:
                    face = _primary_face(cascade, frame)
                    if face is not None:
                        x, y, width, height = (int(value) for value in face)
                        frame_height, frame_width = frame.shape[:2]
                        row.update({
                            "detected": True,
                            "center": [round((x + width / 2) / frame_width, 5), round((y + height / 2) / frame_height, 5)],
                            "size": [round(width / frame_width, 5), round(height / frame_height, 5)],
                        })
                observations.append(row)
    finally:
        capture.release()
    return observations


def build_camera_style_profile(motion: dict, observations: list[dict]) -> dict:
    segments = motion.get("segments") if isinstance(motion.get("segments"), list) else []
    detected = [row for row in observations if row.get("detected") and row.get("center") and row.get("size")]
    coverage = len(detected) / len(observations) if observations else 0.0
    centers_x = [float(row["center"][0]) for row in detected]
    centers_y = [float(row["center"][1]) for row in detected]
    heights = [float(row["size"][1]) for row in detected]
    center_x = float(np.median(centers_x)) if centers_x else None
    center_y = float(np.median(centers_y)) if centers_y else None
    face_height = float(np.median(heights)) if heights else None
    center_spread = float(np.percentile(np.abs(np.asarray(centers_x) - center_x), 90)) if centers_x else None
    subject_lock = bool(coverage >= 0.6 and center_spread is not None and center_spread <= 0.1)

    moving = [row for row in segments if str(row.get("motion_family") or "unknown") not in {"static", "unknown"}]
    camera_motion = "moving" if moving else "static"
    punch_events = [
        {"shot_id": row.get("shot_id"), "start_seconds": row.get("start_seconds"), "end_seconds": row.get("end_seconds"), "direction": "in" if row.get("motion_family") == "push_in" else "out", "confidence": row.get("confidence")}
        for row in segments if row.get("motion_family") in {"push_in", "pull_out"}
    ]
    pan_events = [
        {"shot_id": row.get("shot_id"), "start_seconds": row.get("start_seconds"), "end_seconds": row.get("end_seconds"), "direction": ((row.get("global_motion") or {}).get("translation") or {}).get("direction"), "confidence": row.get("confidence")}
        for row in segments if row.get("motion_family") == "pan_tilt"
    ]
    shaky = sum(1 for row in segments if row.get("motion_family") == "shaky")
    stabilization = "handheld_or_unstabilized" if shaky else "stable_or_stabilized" if segments else "unknown"

    keyframes = []
    if coverage >= 0.6:
        for row in detected:
            x, y = (float(value) for value in row["center"])
            height = float(row["size"][1])
            keyframes.append({
                "shot_id": row.get("shot_id"),
                "time_sec": row.get("time_sec"),
                "center": [round(_clamp(1.0 - x, 0.35, 0.65), 5), round(_clamp(0.45 + (0.38 - y), 0.3, 0.6), 5)],
                "zoom": round(_clamp(0.22 / max(height, 0.01), 1.0, 1.35), 5),
            })

    confidence = round(min(1.0, coverage) * (1.0 if len(detected) >= 3 else 0.7), 3)
    framing = "centered_talking_head" if subject_lock and face_height is not None and face_height >= 0.1 else "person_present" if detected else "unknown"
    return {
        "schema": SCHEMA,
        "framing": framing,
        "subject_lock": subject_lock,
        "reframe_strategy": "sampled_primary_face_center" if keyframes else "preserve_source_frame",
        "camera_motion": {
            "behavior": camera_motion,
            "dominant_family": (motion.get("summary") or {}).get("dominant_motion_family", "unknown"),
            "origin": "source_or_baked_editor_indeterminate",
            "note": "A flattened video cannot prove whether observed global motion was physical camera motion or a baked editor transform.",
        },
        "editor_transform": {
            "operation": "subject_reframe" if keyframes else "none",
            "authority": "recommendation",
            "keyframes": keyframes,
        },
        "punch_in_events": [row for row in punch_events if row["direction"] == "in"],
        "punch_out_events": [row for row in punch_events if row["direction"] == "out"],
        "pan_events": pan_events,
        "stabilization": stabilization,
        "subject_observation": {
            "detected_samples": len(detected),
            "sample_count": len(observations),
            "coverage": round(coverage, 3),
            "median_center": [round(center_x, 5), round(center_y, 5)] if center_x is not None else None,
            "median_face_height": round(face_height, 5) if face_height is not None else None,
            "center_spread_p90": round(center_spread, 5) if center_spread is not None else None,
        },
        "confidence": confidence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--motion", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-shot", type=int, default=5)
    args = parser.parse_args()
    motion = json.loads(args.motion.read_text(encoding="utf-8-sig"))
    segments = motion.get("segments") if isinstance(motion.get("segments"), list) else []
    observations = collect_face_observations(args.video, segments, max(1, args.samples_per_shot))
    profile = build_camera_style_profile(motion, observations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(args.output), "confidence": profile["confidence"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
