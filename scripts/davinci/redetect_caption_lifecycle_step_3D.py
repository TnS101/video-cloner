#!/usr/bin/env python3
"""Targeted visual lifecycle redetection for animated caption layers.

The detector tracks an already-identified caption-layer template in the source
video. Transcript timing is used only to choose a broad search window; detected
visual presence owns the emitted lifecycle window.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import cv2  # type: ignore
import numpy as np

VERSION = "caption_lifecycle_redetection_step_3D_v1_0_visual_template_tracking"
SCHEMA = "video_cloner_caption_lifecycle_redetection"
CALIBRATED_SCHEMA = "video_cloner_caption_lifecycle_authority_plan"
EXPECTED_CUES = ("sub_052", "sub_057", "sub_058", "sub_081")
TIMELINE_FPS = 24.0


class RedetectionError(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def as_int(value: Any) -> int | None:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


def as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def unique_index(rows: Iterable[dict[str, Any]], key: str, label: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = str(row.get(key) or "").strip()
        if not value:
            raise RedetectionError(f"missing_{label}_{key}")
        if value in result:
            raise RedetectionError(f"duplicate_{label}_{key}:{value}")
        result[value] = row
    return result


def clamp_bbox(bbox: list[float], width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(width - 1, int(math.floor(bbox[0] * width))))
    y1 = max(0, min(height - 1, int(math.floor(bbox[1] * height))))
    x2 = max(x1 + 1, min(width, int(math.ceil(bbox[2] * width))))
    y2 = max(y1 + 1, min(height, int(math.ceil(bbox[3] * height))))
    return x1, y1, x2, y2


def expand_bbox(
    bbox: tuple[int, int, int, int],
    width: int,
    height: int,
    x_factor: float = 2.2,
    y_factor: float = 2.8,
) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    new_w = box_w * x_factor
    new_h = box_h * y_factor
    return (
        max(0, int(math.floor(cx - new_w / 2.0))),
        max(0, int(math.floor(cy - new_h / 2.0))),
        min(width, int(math.ceil(cx + new_w / 2.0))),
        min(height, int(math.ceil(cy + new_h / 2.0))),
    )


def highpass(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    background = cv2.GaussianBlur(gray, (0, 0), 3.0)
    hp = cv2.absdiff(gray, background)
    hp = cv2.normalize(hp, None, 0, 255, cv2.NORM_MINMAX)
    return hp.astype(np.uint8)


def multi_scale_match(
    search_image: np.ndarray,
    template: np.ndarray,
    scales: tuple[float, ...] = (0.82, 0.9, 0.96, 1.0, 1.04, 1.1, 1.18),
) -> dict[str, Any]:
    search = highpass(search_image)
    template_hp = highpass(template)
    best = {"score": -1.0, "location": [0, 0], "size": [0, 0], "scale": 1.0}
    for scale in scales:
        target_w = max(8, int(round(template_hp.shape[1] * scale)))
        target_h = max(8, int(round(template_hp.shape[0] * scale)))
        if target_w > search.shape[1] or target_h > search.shape[0]:
            continue
        candidate = cv2.resize(
            template_hp,
            (target_w, target_h),
            interpolation=cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC,
        )
        result = cv2.matchTemplate(search, candidate, cv2.TM_CCOEFF_NORMED)
        _, maximum, _, location = cv2.minMaxLoc(result)
        if float(maximum) > best["score"]:
            best = {
                "score": float(maximum),
                "location": [int(location[0]), int(location[1])],
                "size": [target_w, target_h],
                "scale": float(scale),
            }
    return best


def smooth(values: list[float], radius: int = 2) -> list[float]:
    if not values:
        return []
    result: list[float] = []
    for index in range(len(values)):
        left = max(0, index - radius)
        right = min(len(values), index + radius + 1)
        result.append(float(sum(values[left:right]) / (right - left)))
    return result


def segment_around_seed(
    frame_indices: list[int],
    scores: list[float],
    seed_frame: int,
    max_gap: int = 4,
) -> dict[str, Any]:
    if not frame_indices or len(frame_indices) != len(scores):
        raise RedetectionError("invalid_score_series")
    smoothed = smooth(scores)
    peak = max(smoothed)
    if peak < 0.30:
        raise RedetectionError(f"template_peak_too_low:{peak:.4f}")
    strong_threshold = max(0.34, peak * 0.62)
    weak_threshold = max(0.26, peak * 0.43)
    seed_index = min(range(len(frame_indices)), key=lambda i: abs(frame_indices[i] - seed_frame))

    strong_indices = [i for i, value in enumerate(smoothed) if value >= strong_threshold]
    if not strong_indices:
        raise RedetectionError("no_strong_template_observation")
    anchor = min(strong_indices, key=lambda i: abs(i - seed_index))

    left = anchor
    misses = 0
    for index in range(anchor - 1, -1, -1):
        if smoothed[index] >= weak_threshold:
            left = index
            misses = 0
        else:
            misses += 1
            if misses > max_gap:
                break
            left = index
    while left < anchor and smoothed[left] < weak_threshold:
        left += 1

    right = anchor
    misses = 0
    for index in range(anchor + 1, len(smoothed)):
        if smoothed[index] >= weak_threshold:
            right = index
            misses = 0
        else:
            misses += 1
            if misses > max_gap:
                break
            right = index
    while right > anchor and smoothed[right] < weak_threshold:
        right -= 1

    if right - left + 1 < 3:
        raise RedetectionError("visual_segment_too_short")

    segment_scores = smoothed[left : right + 1]
    segment_peak = max(segment_scores)
    stable_threshold = segment_peak * 0.86
    stable = [left + i for i, value in enumerate(segment_scores) if value >= stable_threshold]
    enter_end = frame_indices[stable[0]] if stable else frame_indices[left]
    exit_start: int | None = None
    if stable:
        last_stable = stable[-1]
        if last_stable < right:
            tail = smoothed[last_stable : right + 1]
            if tail[-1] < segment_peak * 0.72:
                exit_start = frame_indices[last_stable + 1]

    return {
        "first_visible_source_frame": frame_indices[left],
        "last_visible_source_frame": frame_indices[right],
        "enter_end_source_frame": enter_end,
        "exit_start_source_frame": exit_start,
        "peak_score": round(peak, 6),
        "strong_threshold": round(strong_threshold, 6),
        "weak_threshold": round(weak_threshold, 6),
        "anchor_source_frame": frame_indices[anchor],
        "score_count": len(scores),
        "segment_frame_count": right - left + 1,
        "smoothed_scores": [round(value, 6) for value in smoothed],
        "segment_indices": [left, right],
    }


def timeline_frame(source_frame: int, source_fps: float) -> int:
    return int(round((source_frame / source_fps) * TIMELINE_FPS))


def sample_contact_frames(result: dict[str, Any]) -> list[tuple[str, int]]:
    first = int(result["first_visible_source_frame"])
    last = int(result["last_visible_source_frame"])
    enter = int(result["enter_end_source_frame"])
    exit_start = result.get("exit_start_source_frame")
    midpoint = (enter + (int(exit_start) if exit_start is not None else last)) // 2
    samples = [
        ("before", max(0, first - 2)),
        ("first", first),
        ("entry_end", enter),
        ("hold", midpoint),
    ]
    if exit_start is not None:
        samples.append(("exit_start", int(exit_start)))
    samples.extend([("last", last), ("after", last + 2)])
    dedup: list[tuple[str, int]] = []
    seen: set[int] = set()
    for label, frame in samples:
        if frame not in seen:
            dedup.append((label, frame))
            seen.add(frame)
    return dedup


def read_frame(capture: cv2.VideoCapture, frame_index: int) -> np.ndarray:
    capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
    ok, frame = capture.read()
    if not ok or frame is None:
        raise RedetectionError(f"could_not_read_source_frame:{frame_index}")
    return frame


def make_contact_sheet(
    capture: cv2.VideoCapture,
    samples: list[tuple[str, int]],
    search_bbox: tuple[int, int, int, int],
    cue_id: str,
    text: str,
    output: Path,
) -> None:
    tiles: list[np.ndarray] = []
    x1, y1, x2, y2 = search_bbox
    for label, frame_index in samples:
        frame = read_frame(capture, frame_index)
        crop = frame[y1:y2, x1:x2].copy()
        crop = cv2.resize(crop, (420, 220), interpolation=cv2.INTER_AREA)
        cv2.putText(
            crop,
            f"{label}  src={frame_index}",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            (0, 255, 255),
            2,
            cv2.LINE_AA,
        )
        tiles.append(crop)
    header = np.zeros((54, 420 * min(3, max(1, len(tiles))), 3), dtype=np.uint8)
    cv2.putText(
        header,
        f"{cue_id}  {text}",
        (12, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    rows: list[np.ndarray] = []
    for index in range(0, len(tiles), 3):
        chunk = tiles[index : index + 3]
        while len(chunk) < 3:
            chunk.append(np.zeros_like(tiles[0]))
        rows.append(np.hstack(chunk))
    body = np.vstack(rows)
    if header.shape[1] != body.shape[1]:
        header = cv2.resize(header, (body.shape[1], header.shape[0]))
    sheet = np.vstack([header, body])
    output.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output), sheet):
        raise RedetectionError(f"contact_sheet_write_failed:{output}")


def detect_cue(
    capture: cv2.VideoCapture,
    source_fps: float,
    frame_count: int,
    width: int,
    height: int,
    audit_row: dict[str, Any],
    animation_row: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    cue_id = str(audit_row.get("cue_id") or "")
    text = str(audit_row.get("text") or "")
    animation = animation_row.get("animation") or {}
    source_start = as_float(animation.get("source_start"))
    source_end = as_float(animation.get("source_end"))
    source_bbox = audit_row.get("source_bbox")
    if source_start is None or source_end is None or source_end <= source_start:
        raise RedetectionError(f"missing_animation_time:{cue_id}")
    if not isinstance(source_bbox, list) or len(source_bbox) != 4:
        raise RedetectionError(f"missing_source_bbox:{cue_id}")
    if audit_row.get("geometry_exactness") != "cue_instance_clean":
        raise RedetectionError(f"source_seed_not_clean:{cue_id}")
    if not audit_row.get("source_animation_detected"):
        raise RedetectionError(f"source_animation_not_detected:{cue_id}")

    seed_bbox = clamp_bbox([float(v) for v in source_bbox], width, height)
    search_bbox = expand_bbox(seed_bbox, width, height)
    seed_frame = min(frame_count - 1, max(0, int(round(source_end * source_fps)) - 1))
    seed_image = read_frame(capture, seed_frame)
    sx1, sy1, sx2, sy2 = seed_bbox
    template = seed_image[sy1:sy2, sx1:sx2]
    if template.size == 0 or min(template.shape[:2]) < 8:
        raise RedetectionError(f"invalid_template:{cue_id}")

    search_start = max(0, int(math.floor((source_start - 0.75) * source_fps)))
    search_end = min(frame_count - 1, int(math.ceil((source_end + 3.0) * source_fps)))
    x1, y1, x2, y2 = search_bbox
    frame_indices: list[int] = []
    scores: list[float] = []
    matches: list[dict[str, Any]] = []
    for frame_index in range(search_start, search_end + 1):
        frame = read_frame(capture, frame_index)
        search = frame[y1:y2, x1:x2]
        match = multi_scale_match(search, template)
        frame_indices.append(frame_index)
        scores.append(float(match["score"]))
        matches.append(match)

    segment = segment_around_seed(frame_indices, scores, seed_frame)
    first_source = int(segment["first_visible_source_frame"])
    last_source = int(segment["last_visible_source_frame"])
    enter_source = int(segment["enter_end_source_frame"])
    exit_source = segment.get("exit_start_source_frame")

    transcript_start = as_int(animation_row.get("start_frame"))
    transcript_end = as_int(animation_row.get("end_frame"))
    if transcript_start is None or transcript_end is None:
        raise RedetectionError(f"missing_transcript_window:{cue_id}")
    lifecycle = [
        timeline_frame(first_source, source_fps),
        timeline_frame(last_source + 1, source_fps),
    ]
    entry_end = timeline_frame(enter_source + 1, source_fps)
    exit_start = timeline_frame(int(exit_source), source_fps) if exit_source is not None else None
    if lifecycle[1] <= lifecycle[0]:
        raise RedetectionError(f"invalid_lifecycle:{cue_id}:{lifecycle}")

    samples = sample_contact_frames(segment)
    contact_path = output_dir / "contact_sheets" / f"{cue_id}_lifecycle_contact_sheet.jpg"
    make_contact_sheet(capture, samples, search_bbox, cue_id, text, contact_path)

    left, right = segment["segment_indices"]
    observation_rows = []
    for local_index in range(left, right + 1):
        match = matches[local_index]
        observation_rows.append(
            {
                "source_frame": frame_indices[local_index],
                "source_seconds": round(frame_indices[local_index] / source_fps, 6),
                "timeline_frame": timeline_frame(frame_indices[local_index], source_fps),
                "template_score": round(scores[local_index], 6),
                "match_scale": match["scale"],
                "match_location_in_search": match["location"],
                "match_size": match["size"],
            }
        )

    peak = float(segment["peak_score"])
    confidence = "high" if peak >= 0.62 and segment["segment_frame_count"] >= 8 else "medium"
    return {
        "ok": True,
        "cue_id": cue_id,
        "cue_index": audit_row.get("cue_index"),
        "name": audit_row.get("name"),
        "text": text,
        "text_authority": "transcript_primary",
        "timing_authority": "visual_primary_targeted_redetection",
        "source_seed": {
            "source_event_id": animation.get("source_event_id"),
            "source_start": source_start,
            "source_end": source_end,
            "source_bbox": source_bbox,
            "seed_source_frame": seed_frame,
            "seed_bbox_pixels": list(seed_bbox),
            "search_bbox_pixels": list(search_bbox),
        },
        "transcript_window": [transcript_start, transcript_end],
        "lifecycle_window": lifecycle,
        "lifecycle_phases": {
            "entry": [lifecycle[0], min(lifecycle[1], max(lifecycle[0] + 1, entry_end))],
            "hold": [min(lifecycle[1], max(lifecycle[0] + 1, entry_end)), exit_start or lifecycle[1]],
            "exit": [exit_start, lifecycle[1]] if exit_start is not None else None,
            "exit_type": "fade_or_decay_detected" if exit_start is not None else "hard_or_unobserved_exit",
        },
        "starts_before_transcript_frames": max(0, transcript_start - lifecycle[0]),
        "starts_after_transcript_frames": max(0, lifecycle[0] - transcript_start),
        "ends_after_transcript_frames": max(0, lifecycle[1] - transcript_end),
        "ends_before_transcript_frames": max(0, transcript_end - lifecycle[1]),
        "crosses_transcript_boundaries": lifecycle != [transcript_start, transcript_end],
        "tracking": {key: value for key, value in segment.items() if key != "smoothed_scores"},
        "confidence": confidence,
        "contact_sheet": str(contact_path),
        "observations": observation_rows,
    }


def intervals_overlap(left: list[int], right: list[int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]


def calibrated_plan(
    authority_plan: dict[str, Any], detections: list[dict[str, Any]]
) -> dict[str, Any]:
    result = copy.deepcopy(authority_plan)
    layers = [row for row in result.get("layers") or [] if isinstance(row, dict)]
    by_cue = unique_index(layers, "cue_id", "lifecycle_layer")
    detection_by_cue = unique_index(detections, "cue_id", "detection")
    if tuple(detection_by_cue) != EXPECTED_CUES:
        raise RedetectionError(f"detection_queue:{list(detection_by_cue)}")

    for cue_id, detection in detection_by_cue.items():
        layer = by_cue.get(cue_id)
        if layer is None:
            raise RedetectionError(f"missing_lifecycle_layer:{cue_id}")
        layer.update(
            {
                "timing_authority": "visual_primary_redetected",
                "lifecycle_window": detection["lifecycle_window"],
                "lifecycle_status": "targeted_source_video_redetection",
                "visual_track_available": True,
                "visual_track_accepted": True,
                "visual_source_exactness": "source_video_template_tracked_layer",
                "visual_confidence_label": detection["confidence"],
                "visual_dense_observation_count": len(detection["observations"]),
                "starts_before_transcript_frames": detection["starts_before_transcript_frames"],
                "starts_after_transcript_frames": detection["starts_after_transcript_frames"],
                "ends_after_transcript_frames": detection["ends_after_transcript_frames"],
                "ends_before_transcript_frames": detection["ends_before_transcript_frames"],
                "crosses_transcript_boundaries": detection["crosses_transcript_boundaries"],
                "requires_visual_lifecycle_redetection": False,
                "calibration_priority": "none",
                "lifecycle_phases": detection["lifecycle_phases"],
                "targeted_redetection": {
                    "confidence": detection["confidence"],
                    "contact_sheet": detection["contact_sheet"],
                    "source_seed": detection["source_seed"],
                    "tracking": detection["tracking"],
                },
            }
        )

    transcript_windows = {
        row["cue_id"]: row["transcript_window"] for row in layers
    }
    visual_layers = [
        row for row in layers if str(row.get("timing_authority") or "").startswith("visual_primary")
    ]
    overlap_pairs: list[list[str]] = []
    for row in layers:
        row["concurrent_transcript_cue_ids"] = sorted(
            cue_id
            for cue_id, window in transcript_windows.items()
            if cue_id != row["cue_id"] and intervals_overlap(row["lifecycle_window"], window)
        )
        row["concurrent_visual_layer_ids"] = []
    for index, left in enumerate(visual_layers):
        for right in visual_layers[index + 1 :]:
            if intervals_overlap(left["lifecycle_window"], right["lifecycle_window"]):
                left["concurrent_visual_layer_ids"].append(right["layer_id"])
                right["concurrent_visual_layer_ids"].append(left["layer_id"])
                overlap_pairs.append([left["layer_id"], right["layer_id"]])
    for row in layers:
        row["concurrent_visual_layer_ids"].sort()

    selected = [row for row in layers if row.get("animation_selected_step_3C")]
    mandatory = [row for row in layers if row.get("requires_visual_lifecycle_redetection")]
    result["version"] = "caption_lifecycle_authority_step_3D_v1_1_targeted_redetection"
    result["authority_policy"] = "VISUAL_PRIMARY_TRANSCRIPT_TEXT_AND_TIMING_FALLBACK_CALIBRATED"
    result["mandatory_visual_redetection_queue"] = []
    result["visual_overlap_pairs"] = overlap_pairs
    result["layers"] = layers
    result["summary"] = {
        **(result.get("summary") or {}),
        "caption_layer_count": len(layers),
        "visual_primary_count": len(visual_layers),
        "transcript_fallback_count": len(layers) - len(visual_layers),
        "visual_concurrent_overlap_pair_count": len(overlap_pairs),
        "selected_animation_count": len(selected),
        "selected_animation_visual_primary_count": sum(
            str(row.get("timing_authority") or "").startswith("visual_primary")
            for row in selected
        ),
        "selected_animation_missing_visual_lifecycle_count": sum(
            row.get("timing_authority") == "transcript_fallback" for row in selected
        ),
        "mandatory_redetection_count": len(mandatory),
        "mandatory_redetection_cue_ids": [row["cue_id"] for row in mandatory],
        "targeted_redetection_count": len(detections),
        "targeted_redetection_cue_ids": list(EXPECTED_CUES),
    }
    result["checks"] = {
        **(result.get("checks") or {}),
        "targeted_redetection_complete": not mandatory,
        "all_step_3C_animated_layers_visual_primary": all(
            str(row.get("timing_authority") or "").startswith("visual_primary")
            for row in selected
        ),
        "visual_lifecycle_not_clamped_to_transcript": all(
            row.get("lifecycle_window") == detection_by_cue[row["cue_id"]]["lifecycle_window"]
            for row in layers
            if row["cue_id"] in detection_by_cue
        ),
    }
    result["ok"] = all(result["checks"].values())
    result["plan_semantic_sha256"] = canonical_hash(result)
    return result


def run(
    source_video: Path,
    source_audit: dict[str, Any],
    word_tracks: dict[str, Any],
    animation_plan: dict[str, Any],
    authority_plan: dict[str, Any],
    output: Path,
    calibrated_output: Path,
    debug_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_hash = str(word_tracks.get("source_video_sha256") or "")
    actual_hash = sha256(source_video)
    if expected_hash and actual_hash != expected_hash:
        raise RedetectionError("source_video_hash_mismatch")

    queue = [
        str(row.get("cue_id") or "")
        for row in authority_plan.get("mandatory_visual_redetection_queue") or []
    ]
    if queue != list(EXPECTED_CUES):
        raise RedetectionError(f"mandatory_queue:{queue}")

    audit_by_cue = unique_index(
        [row for row in source_audit.get("items") or [] if isinstance(row, dict)],
        "cue_id",
        "source_audit",
    )
    animation_by_cue = unique_index(
        [row for row in animation_plan.get("items") or [] if isinstance(row, dict)],
        "cue_id",
        "animation_plan",
    )

    capture = cv2.VideoCapture(str(source_video))
    if not capture.isOpened():
        raise RedetectionError(f"source_video_open_failed:{source_video}")
    source_fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if source_fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise RedetectionError("invalid_source_video_metadata")

    detections: list[dict[str, Any]] = []
    try:
        for cue_id in EXPECTED_CUES:
            detections.append(
                detect_cue(
                    capture,
                    source_fps,
                    frame_count,
                    width,
                    height,
                    audit_by_cue[cue_id],
                    animation_by_cue[cue_id],
                    debug_dir,
                )
            )
    finally:
        capture.release()

    result = {
        "ok": len(detections) == len(EXPECTED_CUES),
        "schema": SCHEMA,
        "schema_version": 1,
        "version": VERSION,
        "source_video": str(source_video),
        "source_video_sha256": actual_hash,
        "source_video_info": {
            "fps": source_fps,
            "frame_count": frame_count,
            "width": width,
            "height": height,
        },
        "authority_policy": "VISUAL_LIFECYCLE_PRIMARY_TRANSCRIPT_TEXT_ONLY",
        "target_cue_ids": list(EXPECTED_CUES),
        "resolved_cue_count": len(detections),
        "unresolved_cue_count": len(EXPECTED_CUES) - len(detections),
        "detections": detections,
        "timeline_modified": False,
        "resolve_invoked": False,
        "bridge_invoked": False,
    }
    result["semantic_sha256"] = canonical_hash(result)
    calibrated = calibrated_plan(authority_plan, detections)
    write_json(output, result)
    write_json(calibrated_output, calibrated)
    return result, calibrated


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-video", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--word-tracks", type=Path, required=True)
    parser.add_argument("--animation-plan", type=Path, required=True)
    parser.add_argument("--authority-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--calibrated-output", type=Path, required=True)
    parser.add_argument("--debug-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result, calibrated = run(
            args.source_video,
            load_json(args.source_audit),
            load_json(args.word_tracks),
            load_json(args.animation_plan),
            load_json(args.authority_plan),
            args.output,
            args.calibrated_output,
            args.debug_dir,
        )
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "resolved_cue_count": result["resolved_cue_count"],
                "calibrated_summary": calibrated["summary"],
            },
            indent=2,
        )
    )
    return 0 if result["ok"] and calibrated["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
