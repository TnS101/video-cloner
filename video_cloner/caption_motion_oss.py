"""OSS-backed caption motion extraction and editor-independent recipes.

The extraction routes use OpenCV primitives.  HyperFrames' GSAP model is the
representation reference: position and scale remain independent seekable
channels instead of being collapsed into a single animation family.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

from video_cloner.animation_recipe import SCHEMA, SCHEMA_VERSION, validate_recipe

ROUTE_LK = "opencv_lk_affine"
ROUTE_TEMPLATE = "opencv_multiscale_template"


def _cue_ordinal(cue_id: object) -> int:
    try:
        value = int(str(cue_id).rsplit("_", 1)[-1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"cue_id:{cue_id}") from exc
    if value < 1:
        raise ValueError(f"cue_id:{cue_id}")
    return value


def fcpx_time_to_frames(value: str, fps: int = 24) -> int:
    raw = str(value or "").removesuffix("s")
    return int(Fraction(raw) * fps)


def caption_authority(fcpxml: Path) -> list[dict[str, Any]]:
    root = ET.parse(fcpxml).getroot()
    titles = list(root.findall("./library/event/project/sequence/spine/title"))
    rows = []
    for ordinal, title in enumerate(titles, start=1):
        text_node = title.find("./text/text-style")
        if text_node is None:
            raise ValueError(f"fcpxml_caption:{ordinal}")
        rows.append(
            {
                "ordinal": ordinal,
                "caption_id": f"sub_{ordinal:03d}",
                "text": str(text_node.text or ""),
                "start_frame": fcpx_time_to_frames(str(title.get("offset") or "")),
                "duration": fcpx_time_to_frames(str(title.get("duration") or "")),
            }
        )
    return rows


def select_localization_event(events: Iterable[dict[str, Any]], ordinal: int) -> dict[str, Any]:
    candidates = []
    for event in events:
        try:
            event_ordinal = _cue_ordinal(event.get("cue_id"))
        except ValueError:
            continue
        if event_ordinal != ordinal or event.get("role") != "spoken_caption":
            continue
        bbox = (event.get("placement") or {}).get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        confidence = float((event.get("confidence") or {}).get("score") or 0.0)
        match = float((event.get("match") or {}).get("score") or 0.0)
        observations = int((event.get("confidence") or {}).get("observations_count") or 0)
        candidates.append((confidence + match + min(observations, 20) / 100.0, str(event.get("event_id")), event))
    if not candidates:
        raise ValueError(f"caption_localization:{ordinal}")
    return max(candidates, key=lambda row: (row[0], row[1]))[2]


def _read_frames(video_path: Path, timestamps: list[float]) -> tuple[list[np.ndarray], float]:
    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"video_open:{video_path}")
    fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
    frames = []
    try:
        for timestamp in timestamps:
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000.0)
            ok, frame = capture.read()
            if not ok or frame is None:
                raise ValueError(f"video_frame:{timestamp:.6f}")
            frames.append(frame)
    finally:
        capture.release()
    return frames, fps


def _hex_bgr(value: object) -> np.ndarray | None:
    raw = str(value or "").lstrip("#")
    if len(raw) != 6:
        return None
    try:
        rgb = [int(raw[index : index + 2], 16) for index in (0, 2, 4)]
    except ValueError:
        return None
    return np.array(rgb[::-1], dtype=np.int16)


def _text_mask(frame: np.ndarray, fill: object) -> np.ndarray:
    target = _hex_bgr(fill)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.dilate(cv2.Canny(gray, 45, 135), np.ones((3, 3), np.uint8))
    if target is None:
        return edges
    distance = np.linalg.norm(frame.astype(np.int16) - target, axis=2)
    color = np.where(distance <= 72.0, 255, 0).astype(np.uint8)
    return cv2.bitwise_and(cv2.dilate(color, np.ones((3, 3), np.uint8)), edges)


def _rect(value: Iterable[object], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = (int(round(float(part))) for part in value)
    x1, x2 = sorted((max(0, x1), min(width, x2)))
    y1, y2 = sorted((max(0, y1), min(height, y2)))
    if x2 - x1 < 8 or y2 - y1 < 8:
        raise ValueError("caption_bbox")
    return x1, y1, x2, y2


def _search_rect(bbox: tuple[int, int, int, int], width: int, height: int) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = bbox
    bw, bh = x2 - x1, y2 - y1
    return (
        max(0, x1 - int(round(bw * 0.8))),
        max(0, y1 - int(round(bh * 1.0))),
        min(width, x2 + int(round(bw * 0.8))),
        min(height, y2 + int(round(bh * 1.0))),
    )


def _localization_bbox(event: dict[str, Any]) -> list[object]:
    observations = [
        row for row in (event.get("observations") or [])
        if str(row.get("observation_provenance") or "").startswith("accepted")
        and isinstance(row.get("bbox"), list) and len(row["bbox"]) == 4
    ]
    if observations:
        return observations[-1]["bbox"]
    return (event.get("placement") or {}).get("bbox") or []


def _lk_transforms(frames: list[np.ndarray], bbox: tuple[int, int, int, int], fill: object) -> tuple[list[tuple[float, float, float]], list[float]]:
    reference = frames[-1]
    height, width = reference.shape[:2]
    gray_ref = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
    mask = np.zeros_like(gray_ref)
    x1, y1, x2, y2 = bbox
    local = _text_mask(reference, fill)
    mask[y1:y2, x1:x2] = local[y1:y2, x1:x2]
    points = cv2.goodFeaturesToTrack(gray_ref, mask=mask, maxCorners=300, qualityLevel=0.005, minDistance=3, blockSize=5)
    if points is None or len(points) < 4:
        mask[y1:y2, x1:x2] = 255
        points = cv2.goodFeaturesToTrack(gray_ref, mask=mask, maxCorners=300, qualityLevel=0.01, minDistance=4, blockSize=5)
    if points is None or len(points) < 4:
        raise ValueError("lk_features")
    rows, confidence = [], []
    for frame in frames:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        current, status, _ = cv2.calcOpticalFlowPyrLK(gray_ref, gray, points, None, winSize=(31, 31), maxLevel=4)
        if current is None or status is None:
            raise ValueError("lk_flow")
        back, back_status, _ = cv2.calcOpticalFlowPyrLK(gray, gray_ref, current, None, winSize=(31, 31), maxLevel=4)
        ok = status.reshape(-1).astype(bool)
        if back is not None and back_status is not None:
            ok &= back_status.reshape(-1).astype(bool)
            ok &= np.linalg.norm(back.reshape(-1, 2) - points.reshape(-1, 2), axis=1) <= 1.75
        source = points.reshape(-1, 2)[ok]
        target = current.reshape(-1, 2)[ok]
        if len(source) < 4:
            raise ValueError("lk_tracks")
        matrix, inliers = cv2.estimateAffinePartial2D(source, target, method=cv2.RANSAC, ransacReprojThreshold=2.5)
        if matrix is None:
            raise ValueError("lk_affine")
        scale = float(np.hypot(matrix[0, 0], matrix[0, 1]))
        center = np.array([[(x1 + x2) / 2.0, (y1 + y2) / 2.0, 1.0]])
        moved = center @ matrix.T
        rows.append(((float(moved[0, 0]) - center[0, 0]) / width, (float(moved[0, 1]) - center[0, 1]) / height, scale))
        confidence.append(float(np.mean(inliers)) if inliers is not None else 0.0)
    return rows, confidence


def _template_transforms(frames: list[np.ndarray], bbox: tuple[int, int, int, int], fill: object) -> tuple[list[tuple[float, float, float]], list[float]]:
    reference = frames[-1]
    height, width = reference.shape[:2]
    x1, y1, x2, y2 = bbox
    sx1, sy1, sx2, sy2 = _search_rect(bbox, width, height)
    template = cv2.Canny(cv2.cvtColor(reference[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY), 45, 135)
    base_h, base_w = template.shape
    rows, confidence = [], []
    for frame in frames:
        search = cv2.Canny(cv2.cvtColor(frame[sy1:sy2, sx1:sx2], cv2.COLOR_BGR2GRAY), 45, 135)
        best: tuple[float, float, int, int] | None = None
        for scale in np.linspace(0.65, 1.35, 29):
            tw, th = max(4, int(round(base_w * scale))), max(4, int(round(base_h * scale)))
            if tw >= search.shape[1] or th >= search.shape[0]:
                continue
            candidate = cv2.resize(template, (tw, th), interpolation=cv2.INTER_LINEAR)
            result = cv2.matchTemplate(search, candidate, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if best is None or score > best[0]:
                best = (float(score), float(scale), int(location[0]), int(location[1]))
        if best is None:
            raise ValueError("template_match")
        score, scale, lx, ly = best
        center_x = sx1 + lx + base_w * scale / 2.0
        center_y = sy1 + ly + base_h * scale / 2.0
        rows.append(((center_x - (x1 + x2) / 2.0) / width, (center_y - (y1 + y2) / 2.0) / height, scale))
        confidence.append(score)
    return rows, confidence


def _sample_timestamps(event: dict[str, Any], duration: int, fps: float) -> list[float]:
    observed = [
        float(row["timestamp"])
        for row in (event.get("observations") or [])
        if str(row.get("observation_provenance") or "").startswith("accepted")
        and row.get("timestamp") is not None
    ]
    if len(observed) >= 2:
        indexes = np.linspace(0, len(observed) - 1, min(duration, len(observed))).round().astype(int)
        return [observed[index] for index in sorted(set(indexes.tolist()))]
    start, end = float(event.get("start") or 0.0), float(event.get("end") or 0.0)
    if end <= start:
        raise ValueError("localization_window")
    count = max(2, min(duration, int(round((end - start) * max(fps, 1.0))) + 1))
    last = max(start, end - 1.0 / max(fps, 1.0))
    return [float(value) for value in np.linspace(start, last, count)]


def derive_recipe(video_path: Path, caption: dict[str, Any], event: dict[str, Any], route: str, timestamps: list[float] | None = None) -> dict[str, Any]:
    probe = cv2.VideoCapture(str(video_path))
    fps = float(probe.get(cv2.CAP_PROP_FPS) or 0.0)
    width = int(probe.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(probe.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    probe.release()
    if fps <= 0 or width <= 0 or height <= 0:
        raise ValueError("video_metadata")
    sample_times = timestamps or _sample_timestamps(event, int(caption["duration"]), fps)
    transforms, scores = extract_transforms(video_path, event, route, sample_times)
    duration = int(caption["duration"])
    local_frames = [int(round(index * (duration - 1) / max(1, len(transforms) - 1))) for index in range(len(transforms))]
    compact = []
    for frame, transform in zip(local_frames, transforms):
        row = (frame, transform)
        if compact and compact[-1][0] == frame:
            compact[-1] = row
        else:
            compact.append(row)
    position = [{"frame": frame, "value": [round(value[0], 6), round(value[1], 6)], "interpolation": "linear"} for frame, value in compact]
    scale = [{"frame": frame, "value": [round(value[2], 6), round(value[2], 6)], "interpolation": "linear"} for frame, value in compact]
    recipe = {
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "caption_id": str(caption["caption_id"]),
        "text": str(caption["text"]),
        "start_frame": int(caption["start_frame"]),
        "duration": duration,
        "channels": {"position": position, "scale": scale},
        "confidence": round(float(np.mean(scores)), 4),
        "provenance": {
            "route": route,
            "component": "opencv",
            "localization_event_id": str(event.get("event_id") or ""),
            "reference_video": str(video_path),
            "sample_timestamps": [round(value, 6) for value in sample_times],
            "animation_classification_used": False,
        },
    }
    return validate_recipe(recipe)


def extract_transforms(video_path: Path, event: dict[str, Any], route: str, timestamps: list[float]) -> tuple[list[tuple[float, float, float]], list[float]]:
    frames, _ = _read_frames(video_path, timestamps)
    height, width = frames[0].shape[:2]
    bbox = _rect(_localization_bbox(event), width, height)
    fill = (event.get("colors") or {}).get("fill")
    if route == ROUTE_LK:
        return _lk_transforms(frames, bbox, fill)
    if route == ROUTE_TEMPLATE:
        return _template_transforms(frames, bbox, fill)
    raise ValueError(f"route:{route}")


def recipe_relative_rows(recipe: dict[str, Any]) -> list[tuple[int, float, float, float]]:
    positions = {int(row["frame"]): row["value"] for row in recipe["channels"]["position"]}
    scales = {int(row["frame"]): row["value"] for row in recipe["channels"]["scale"]}
    frames = sorted(set(positions) & set(scales))
    return [(frame, float(positions[frame][0]), float(positions[frame][1]), float(scales[frame][0])) for frame in frames]
