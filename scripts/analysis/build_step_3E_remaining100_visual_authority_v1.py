#!/usr/bin/env python3
"""Build source-pixel visual authority for the 100 preserved caption instances.

This is an offline Step 3E detector. It reads the original source video and
existing visual-derived metadata, writes explicit per-frame authority, and does
not invoke or mutate DaVinci Resolve.

Transcript text may remain as canonical text metadata. Transcript timing is
never promoted to visual timing authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import OrderedDict
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1"
VIDEO_ID = "DZsqH7auhjt"
EXPECTED_SOURCE_SHA256 = "fd60f596fb09031d8fa41071691cbdc1884edb32fd79f436f6be1df1ca186635"
EXPECTED_INSTANCE_COUNT = 100
EXPECTED_V4_TOKEN_COUNT = 17
EXPECTED_V4_SOURCE_CUE_COUNT = 15
TIMELINE_FPS = 24.0
SEARCH_PAD_FRAMES = 6
DOWNSCALE = 0.5

FULL_PLAN = Path(
    ".agent/reports/DZSQH7AUHJT_STEP_3D_VISUAL_FIRST_FULL_ROLLOUT_BASELINE_V1/"
    "20260810T080927254297Z_befb7b9f1474440fb817520c47ba8cd3/full_rollout_plan.json"
)
V4_AUTHORITY = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_visual_polish_authority_v4.json")
LIFECYCLE = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json")
WORD_TRACKS = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_word_instance_tracks_step_3B_6B.json")
POSITION_PLAN = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_position_full_plan_step_3B_5B.json")
FILL_PLAN = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_fill_color_full_plan_step_3B_4B.json")
SIZE_PLAN = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_font_size_plan_step_3B_2_step_3C_normalized.json")
STYLE_ANALYSIS = Path("data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_style.json")
SOURCE_VIDEO = Path("input/DZsqH7auhjt.mp4")
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/"
    "remaining100_visual_authority_v1.json"
)


class DetectionError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise DetectionError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def raw_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cue_key(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("sub_"):
        tail = text[4:]
        if tail.isdigit():
            return f"sub_{int(tail):03d}"
    return text


def index_rows(rows: Any, key: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for row in rows:
        if not isinstance(row, dict):
            continue
        identity = cue_key(row.get(key))
        if identity:
            result[identity] = row
    return result


def hex_to_bgr(value: Any, default: tuple[int, int, int] = (245, 245, 245)) -> tuple[int, int, int]:
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return default
    try:
        r, g, b = int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)
    except ValueError:
        return default
    return b, g, r


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def rounded_pair(x: float, y: float) -> list[float]:
    return [round(float(x), 6), round(float(y), 6)]


class VideoSource:
    """Random-access downscaled source frames with a bounded LRU cache."""

    def __init__(self, path: Path, timeline_fps: float = TIMELINE_FPS, cache_size: int = 36):
        self.path = path
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.source_fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.source_count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        self.source_width = int(round(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
        self.source_height = int(round(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
        require(self.source_fps > 0 and self.source_count > 0, "video_metadata")
        require(self.source_width > 0 and self.source_height > 0, "video_dimensions")
        self.timeline_fps = float(timeline_fps)
        self.cache_size = int(cache_size)
        self.cache: OrderedDict[int, np.ndarray] = OrderedDict()

    def source_index(self, timeline_frame: int) -> int:
        index = int(round(float(timeline_frame) * self.source_fps / self.timeline_fps))
        return max(0, min(self.source_count - 1, index))

    def read(self, timeline_frame: int) -> np.ndarray:
        index = self.source_index(timeline_frame)
        if index in self.cache:
            frame = self.cache.pop(index)
            self.cache[index] = frame
            return frame
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.cap.read()
        require(ok and frame is not None, f"frame_read:{timeline_frame}:{index}")
        if DOWNSCALE != 1.0:
            frame = cv2.resize(
                frame,
                (
                    max(1, int(round(frame.shape[1] * DOWNSCALE))),
                    max(1, int(round(frame.shape[0] * DOWNSCALE))),
                ),
                interpolation=cv2.INTER_AREA,
            )
        self.cache[index] = frame
        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return frame

    def close(self) -> None:
        self.cap.release()
        self.cache.clear()


def resolve_style_event(
    position_row: Mapping[str, Any] | None,
    event_by_id: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    if not position_row:
        return None
    source_position = position_row.get("source_position")
    if not isinstance(source_position, Mapping):
        return None
    detail = source_position.get("source_detail_id")
    ids: Sequence[Any] = detail if isinstance(detail, list) else [detail]
    for value in ids:
        if isinstance(value, str) and value in event_by_id:
            return event_by_id[value]
    return None


def style_profile_map(style: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in style.get("caption_style_profiles") or []:
        if isinstance(row, Mapping) and row.get("style_id"):
            result[str(row["style_id"])] = row
    return result


def seed_geometry(
    cue_ids: Sequence[str],
    text: str,
    position_map: Mapping[str, Mapping[str, Any]],
    size_map: Mapping[str, Mapping[str, Any]],
    style_events: Mapping[str, Mapping[str, Any]],
    profiles: Mapping[str, Mapping[str, Any]],
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    centers: list[tuple[float, float]] = []
    widths: list[float] = []
    heights: list[float] = []
    event_ids: list[str] = []
    profile_ids: list[str] = []

    for cue_id in cue_ids:
        pos = position_map.get(cue_id)
        if pos:
            target_center = pos.get("target_center")
            if (
                isinstance(target_center, list)
                and len(target_center) == 2
                and all(isinstance(v, (int, float)) for v in target_center)
            ):
                centers.append((float(target_center[0]), 1.0 - float(target_center[1])))
            profile_id = str(pos.get("style_profile_id") or "")
            if profile_id:
                profile_ids.append(profile_id)
            event = resolve_style_event(pos, style_events)
            if event:
                event_ids.append(str(event.get("event_id") or ""))
                placement = event.get("placement") if isinstance(event.get("placement"), Mapping) else {}
                bbox = placement.get("normalized_bbox")
                if isinstance(bbox, list) and len(bbox) == 4:
                    widths.append(max(0.01, float(bbox[2]) - float(bbox[0])))
                    heights.append(max(0.01, float(bbox[3]) - float(bbox[1])))

        size = size_map.get(cue_id)
        if size and not profile_ids:
            profile_id = str(size.get("style_profile_id") or "")
            if profile_id:
                profile_ids.append(profile_id)

    if centers:
        center_x = float(median([x for x, _ in centers]))
        center_y = float(median([y for _, y in centers]))
    else:
        center_x, center_y = 0.5, 0.48

    profile = profiles.get(profile_ids[0]) if profile_ids else None
    if heights:
        height_ratio = float(median(heights))
    elif profile and isinstance(profile.get("typography"), Mapping):
        height_ratio = float(profile["typography"].get("font_height_ratio") or 0.035)
    else:
        height_ratio = 0.035

    if widths:
        width_ratio = float(median(widths))
    else:
        char_count = max(1, len(str(text or "").strip()))
        width_ratio = clamp(height_ratio * max(2.0, char_count * 0.62), 0.10, 0.72)

    return {
        "center_top_origin": rounded_pair(center_x, center_y),
        "expected_height_px": round(clamp(height_ratio * frame_height, 10.0, frame_height * 0.18), 3),
        "expected_width_px": round(clamp(width_ratio * frame_width, 40.0, frame_width * 0.78), 3),
        "source_style_event_ids": sorted(set(filter(None, event_ids))),
        "style_profile_ids": sorted(set(filter(None, profile_ids))),
    }


def seed_fill(
    cue_ids: Sequence[str],
    fill_map: Mapping[str, Mapping[str, Any]],
) -> tuple[str, tuple[int, int, int]]:
    for cue_id in cue_ids:
        row = fill_map.get(cue_id)
        if not row:
            continue
        target = row.get("target_fill")
        if isinstance(target, Mapping):
            value = str(target.get("hex") or "")
            if value:
                return value, hex_to_bgr(value)
    return "#f5f5f5", (245, 245, 245)


def pixel_measure(
    frame: np.ndarray,
    center_top_origin: Sequence[float],
    fill_bgr: tuple[int, int, int],
    expected_width_px: float,
    expected_height_px: float,
) -> dict[str, Any]:
    """Measure text-like source pixels near a visual seed.

    The detector is intentionally text-engine agnostic. Color proximity is
    intersected with local edge support, preventing large flat background
    regions from becoming caption evidence.
    """
    height, width = frame.shape[:2]
    cx = int(round(clamp(float(center_top_origin[0]), 0.0, 1.0) * width))
    cy = int(round(clamp(float(center_top_origin[1]), 0.0, 1.0) * height))

    half_w = int(round(clamp(expected_width_px * 0.75 + 24.0, 56.0, width * 0.43)))
    half_h = int(round(clamp(expected_height_px * 1.75 + 18.0, 42.0, height * 0.18)))
    x0, x1 = max(0, cx - half_w), min(width, cx + half_w + 1)
    y0, y1 = max(0, cy - half_h), min(height, cy + half_h + 1)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return {"score": 0.0, "candidate_pixels": 0, "bbox": None, "roi": [x0, y0, x1, y1]}

    target = np.asarray(fill_bgr, dtype=np.float32).reshape(1, 1, 3)
    diff = np.linalg.norm(crop.astype(np.float32) - target, axis=2)
    target_range = max(fill_bgr) - min(fill_bgr)
    color_threshold = 72.0 if target_range < 38 else 58.0
    fill_like = (diff <= color_threshold).astype(np.uint8)

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    edge = (gradient >= 22.0).astype(np.uint8)
    edge = cv2.dilate(edge, np.ones((5, 5), dtype=np.uint8), iterations=1)
    candidate = (fill_like & edge).astype(np.uint8)

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(candidate, connectivity=8)
    accepted: list[int] = []
    roi_area = max(1, crop.shape[0] * crop.shape[1])
    expected_h = max(5.0, float(expected_height_px))
    expected_w = max(20.0, float(expected_width_px))
    local_cx, local_cy = cx - x0, cy - y0

    for idx in range(1, count):
        comp_x, comp_y, comp_w, comp_h, comp_area = [int(v) for v in stats[idx]]
        if comp_area < 2 or comp_area > roi_area * 0.12:
            continue
        if comp_h > expected_h * 2.7 or comp_w > expected_w * 1.25:
            continue
        px, py = centroids[idx]
        if abs(float(py) - local_cy) > max(expected_h * 1.55, 28.0):
            continue
        if abs(float(px) - local_cx) > max(expected_w * 0.75, 60.0):
            continue
        accepted.append(idx)

    if not accepted:
        candidate_pixels = 0
        bbox = None
    else:
        mask = np.isin(labels, np.asarray(accepted, dtype=np.int32))
        ys, xs = np.where(mask)
        candidate_pixels = int(mask.sum())
        bbox = [
            int(x0 + xs.min()),
            int(y0 + ys.min()),
            int(x0 + xs.max() + 1),
            int(y0 + ys.max() + 1),
        ]

    expected_area = max(60.0, expected_h * expected_w)
    score = float(candidate_pixels) / expected_area
    return {
        "score": round(score, 8),
        "candidate_pixels": candidate_pixels,
        "bbox": bbox,
        "roi": [x0, y0, x1, y1],
    }


def derive_visibility(
    scores: Sequence[float],
    search_frames: Sequence[int],
    seed_window: Sequence[int],
) -> dict[str, Any]:
    require(len(scores) == len(search_frames) and len(scores) > 0, "visibility_input")
    peak = max(float(v) for v in scores)
    peak_index = max(range(len(scores)), key=lambda i: float(scores[i]))
    edge_samples = list(scores[:2]) + list(scores[-2:])
    noise = float(median(edge_samples)) if edge_samples else 0.0
    dynamic = max(0.00002, peak - noise)
    threshold = max(noise + dynamic * 0.20, peak * 0.30, 0.00002)

    seed_start, seed_end = int(seed_window[0]), int(seed_window[1])
    selected = [
        int(frame)
        for frame, score in zip(search_frames, scores)
        if float(score) >= threshold
    ]

    # Require the selected evidence to intersect the baseline placement seed.
    # The seed defines only where to look; pixel score defines final visibility.
    seed_selected = [f for f in selected if seed_start <= f < seed_end]
    if not seed_selected:
        seed_indices = [
            i for i, frame in enumerate(search_frames) if seed_start <= int(frame) < seed_end
        ]
        if seed_indices:
            best_seed = max(seed_indices, key=lambda i: float(scores[i]))
            if float(scores[best_seed]) > 0:
                selected.append(int(search_frames[best_seed]))
                selected = sorted(set(selected))

    if not selected or peak <= 0:
        return {
            "ok": False,
            "peak_score": round(peak, 8),
            "noise_score": round(noise, 8),
            "threshold": round(threshold, 8),
            "selected_frames": [],
            "window": None,
            "peak_frame": int(search_frames[peak_index]),
        }

    # Keep only the contiguous run around the highest scoring selected frame.
    selected_set = set(selected)
    peak_frame = int(search_frames[peak_index])
    if peak_frame not in selected_set:
        peak_frame = min(selected, key=lambda f: abs(f - peak_frame))
    run = [peak_frame]
    cursor = peak_frame - 1
    while cursor in selected_set:
        run.insert(0, cursor)
        cursor -= 1
    cursor = peak_frame + 1
    while cursor in selected_set:
        run.append(cursor)
        cursor += 1

    # A one-frame detection is still valid source evidence, but callers retain
    # confidence metadata so rollout remains separately gated.
    return {
        "ok": True,
        "peak_score": round(peak, 8),
        "noise_score": round(noise, 8),
        "threshold": round(threshold, 8),
        "selected_frames": run,
        "window": [int(run[0]), int(run[-1]) + 1],
        "peak_frame": peak_frame,
    }


def nearest_measure(
    frame: int,
    measures: Mapping[int, Mapping[str, Any]],
) -> Mapping[str, Any] | None:
    usable = [f for f, row in measures.items() if row.get("bbox")]
    if not usable:
        return None
    best = min(usable, key=lambda value: abs(int(value) - int(frame)))
    return measures[best]


def build_frame_path(
    window: Sequence[int],
    measures: Mapping[int, Mapping[str, Any]],
    seed_center: Sequence[float],
    base_size: float,
    frame_width: int,
    frame_height: int,
    visibility: Mapping[str, Any],
) -> list[dict[str, Any]]:
    start, end = int(window[0]), int(window[1])
    peak = max(float(visibility.get("peak_score") or 0.0), 1e-8)
    bbox_heights = []
    for frame in range(start, end):
        row = measures.get(frame)
        if row and row.get("bbox"):
            bbox = row["bbox"]
            bbox_heights.append(max(1.0, float(bbox[3] - bbox[1])))
    median_height = float(median(bbox_heights)) if bbox_heights else 1.0

    result = []
    for frame in range(start, end):
        row = measures.get(frame) or nearest_measure(frame, measures) or {}
        bbox = row.get("bbox")
        if bbox:
            center_x = ((float(bbox[0]) + float(bbox[2])) / 2.0) / frame_width
            center_y = ((float(bbox[1]) + float(bbox[3])) / 2.0) / frame_height
            bbox_height = max(1.0, float(bbox[3] - bbox[1]))
            size_scale = clamp(bbox_height / median_height, 0.55, 1.45)
        else:
            center_x, center_y = float(seed_center[0]), float(seed_center[1])
            size_scale = 1.0
        raw_score = float((measures.get(frame) or {}).get("score") or 0.0)
        opacity = clamp(raw_score / peak, 0.08, 1.0)
        result.append(
            {
                "timeline_frame": frame,
                "position_top_origin": rounded_pair(center_x, center_y),
                "position_fusion": rounded_pair(center_x, 1.0 - center_y),
                "opacity_factor": round(opacity, 6),
                "size_scale": round(size_scale, 6),
                "application_size_candidate": round(float(base_size) * size_scale, 12),
                "pixel_score": round(raw_score, 8),
            }
        )
    return result


def base_size_for(cue_ids: Sequence[str], size_map: Mapping[str, Mapping[str, Any]]) -> float:
    values = []
    for cue_id in cue_ids:
        row = size_map.get(cue_id)
        if row:
            value = row.get("target_size")
            if isinstance(value, (int, float)) and float(value) > 0:
                values.append(float(value))
    return float(median(values)) if values else 0.089954170778


def font_for(cue_ids: Sequence[str], size_map: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    for cue_id in cue_ids:
        row = size_map.get(cue_id)
        if row:
            family = str(row.get("family") or "").strip()
            face = str(row.get("face") or "").strip()
            if family:
                return {"font_family": family, "font_style": face or "Regular"}
    return {"font_family": "Verdana", "font_style": "Bold"}


def lifecycle_seed(
    cue_ids: Sequence[str],
    lifecycle_map: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [lifecycle_map[cid] for cid in cue_ids if cid in lifecycle_map]
    authorities = [str(row.get("timing_authority") or "") for row in rows]
    visual_rows = [
        row for row in rows if str(row.get("timing_authority") or "").startswith("visual_primary")
    ]
    if visual_rows:
        start = min(int(row["lifecycle_window"][0]) for row in visual_rows)
        end = max(int(row["lifecycle_window"][1]) for row in visual_rows)
        return {
            "visual_primary": True,
            "visual_window": [start, end],
            "prior_authorities": authorities,
            "prior_visual_source_exactness": sorted(
                set(str(row.get("visual_source_exactness") or "") for row in visual_rows)
            ),
        }
    return {
        "visual_primary": False,
        "visual_window": None,
        "prior_authorities": authorities,
        "prior_visual_source_exactness": [],
    }


def build(repo_root: Path, output_path: Path) -> dict[str, Any]:
    paths = {
        "full_plan": repo_root / FULL_PLAN,
        "v4_authority": repo_root / V4_AUTHORITY,
        "lifecycle": repo_root / LIFECYCLE,
        "word_tracks": repo_root / WORD_TRACKS,
        "position_plan": repo_root / POSITION_PLAN,
        "fill_plan": repo_root / FILL_PLAN,
        "size_plan": repo_root / SIZE_PLAN,
        "style_analysis": repo_root / STYLE_ANALYSIS,
        "source_video": repo_root / SOURCE_VIDEO,
    }
    for key, path in paths.items():
        require(path.is_file(), f"missing_input:{key}:{path}")

    source_hash = raw_sha256(paths["source_video"])
    require(source_hash == EXPECTED_SOURCE_SHA256, f"source_video_sha256:{source_hash}")

    full_plan = load_json(paths["full_plan"])
    v4 = load_json(paths["v4_authority"])
    lifecycle = load_json(paths["lifecycle"])
    word_tracks = load_json(paths["word_tracks"])
    position = load_json(paths["position_plan"])
    fill = load_json(paths["fill_plan"])
    sizes = load_json(paths["size_plan"])
    style = load_json(paths["style_analysis"])

    preserved = ((full_plan.get("replacements") or {}).get("preserved_rows") or [])
    require(len(preserved) == EXPECTED_INSTANCE_COUNT, f"preserved_count:{len(preserved)}")
    require((full_plan.get("counts") or {}).get("preserved_textplus") == EXPECTED_INSTANCE_COUNT, "plan_preserved_count")

    v4_tokens = [
        token
        for group in v4.get("groups") or []
        for token in (group.get("tokens") or [])
        if isinstance(token, Mapping)
    ]
    require(len(v4_tokens) == EXPECTED_V4_TOKEN_COUNT, f"v4_token_count:{len(v4_tokens)}")
    protected_cues = {
        cue_key(token.get("source_cue_id"))
        for token in v4_tokens
        if cue_key(token.get("source_cue_id"))
    }
    require(len(protected_cues) == EXPECTED_V4_SOURCE_CUE_COUNT, f"v4_source_cue_count:{len(protected_cues)}")

    position_map = index_rows(position.get("items"), "cue_id")
    fill_map = index_rows(fill.get("items"), "cue_id")
    size_map = index_rows(sizes.get("items"), "cue_id")
    lifecycle_map = index_rows(lifecycle.get("layers"), "cue_id")
    track_map = index_rows(word_tracks.get("tracks"), "cue_id")
    event_by_id = {
        str(row.get("event_id")): row
        for row in style.get("caption_style_events") or []
        if isinstance(row, Mapping) and row.get("event_id")
    }
    profiles = style_profile_map(style)

    video = VideoSource(paths["source_video"])
    require(abs(video.source_fps - 30.0) < 0.02, f"source_fps:{video.source_fps}")
    scaled_width = int(round(video.source_width * DOWNSCALE))
    scaled_height = int(round(video.source_height * DOWNSCALE))

    instances: list[dict[str, Any]] = []
    direct_visual_count = 0
    pixel_redetected_count = 0
    low_confidence_count = 0
    total_rows = 0

    try:
        for index, preserved_row in enumerate(preserved):
            require(isinstance(preserved_row, Mapping), f"preserved_row:{index}")
            instance_id = str(preserved_row.get("instance_id") or "").strip()
            require(instance_id, f"instance_id:{index}")
            cue_ids = [cue_key(value) for value in preserved_row.get("source_cue_ids") or [] if cue_key(value)]
            require(cue_ids, f"source_cue_ids:{instance_id}")
            require(not (set(cue_ids) & protected_cues), f"protected_cue_overlap:{instance_id}")

            target_range = preserved_row.get("target_range")
            require(
                isinstance(target_range, list)
                and len(target_range) == 2
                and int(target_range[1]) > int(target_range[0]),
                f"target_range:{instance_id}",
            )
            seed_window = [int(target_range[0]), int(target_range[1])]
            text = str(preserved_row.get("text") or "")

            geometry = seed_geometry(
                cue_ids,
                text,
                position_map,
                size_map,
                event_by_id,
                profiles,
                scaled_width,
                scaled_height,
            )
            fill_hex, fill_bgr = seed_fill(cue_ids, fill_map)
            base_size = base_size_for(cue_ids, size_map)
            lifecycle_info = lifecycle_seed(cue_ids, lifecycle_map)

            # Existing visual-primary lifecycle is already source-observed and is
            # retained as timing authority. Fallback lifecycle is actively
            # re-detected from source pixels inside a bounded search window.
            if lifecycle_info["visual_primary"]:
                authority_method = "accepted_source_visual_track_plus_pixel_readback"
                authoritative_window = list(lifecycle_info["visual_window"])
                search_seed = authoritative_window
                direct_visual_count += 1
            else:
                authority_method = "source_pixel_redetection"
                authoritative_window = None
                search_seed = seed_window
                pixel_redetected_count += 1

            search_start = max(0, int(search_seed[0]) - SEARCH_PAD_FRAMES)
            search_end = int(search_seed[1]) + SEARCH_PAD_FRAMES
            search_frames = list(range(search_start, search_end))
            measures: dict[int, dict[str, Any]] = {}
            for timeline_frame in search_frames:
                frame = video.read(timeline_frame)
                measures[timeline_frame] = pixel_measure(
                    frame,
                    geometry["center_top_origin"],
                    fill_bgr,
                    geometry["expected_width_px"],
                    geometry["expected_height_px"],
                )

            scores = [float(measures[frame]["score"]) for frame in search_frames]
            visibility = derive_visibility(scores, search_frames, search_seed)

            if authoritative_window is None:
                require(visibility["ok"] is True, f"pixel_redetection:{instance_id}")
                authoritative_window = list(visibility["window"])
            else:
                # Pixel readback is validation/geometry evidence for already
                # accepted visual timing. It never widens/clamps that timing.
                if visibility["ok"] is not True:
                    low_confidence_count += 1

            frame_path = build_frame_path(
                authoritative_window,
                measures,
                geometry["center_top_origin"],
                base_size,
                scaled_width,
                scaled_height,
                visibility,
            )
            require(frame_path, f"frame_path:{instance_id}")
            total_rows += len(frame_path)

            peak_score = float(visibility.get("peak_score") or 0.0)
            if peak_score < 0.00015:
                confidence = "low"
                low_confidence_count += 1
            elif peak_score < 0.0007:
                confidence = "medium"
            else:
                confidence = "high"

            track_rows = [track_map[cid] for cid in cue_ids if cid in track_map]
            instances.append(
                {
                    "instance_id": instance_id,
                    "target_name": str(preserved_row.get("target_name") or ""),
                    "source_cue_ids": cue_ids,
                    "canonical_text": text,
                    "text_authority": "existing_canonical_text_metadata",
                    "transcript_timing_authority": False,
                    "visual_timing_authority": authority_method,
                    "visual_window": authoritative_window,
                    "search_seed_only": {
                        "window": seed_window,
                        "source": "accepted_full_rollout_preserved_row",
                        "timing_authority": False,
                    },
                    "style": {
                        "fill_hex": fill_hex,
                        "font": font_for(cue_ids, size_map),
                        "base_application_size": round(base_size, 12),
                        "source_style_event_ids": geometry["source_style_event_ids"],
                        "style_profile_ids": geometry["style_profile_ids"],
                    },
                    "source_pixel_seed": geometry,
                    "source_pixel_scan": {
                        "search_window": [search_start, search_end],
                        "peak_frame": int(visibility.get("peak_frame") or search_seed[0]),
                        "peak_score": round(peak_score, 8),
                        "noise_score": round(float(visibility.get("noise_score") or 0.0), 8),
                        "threshold": round(float(visibility.get("threshold") or 0.0), 8),
                        "selected_frames": [int(v) for v in visibility.get("selected_frames") or []],
                        "detected_frame_count": len(visibility.get("selected_frames") or []),
                        "confidence": confidence,
                        "downscaled_dimensions": [scaled_width, scaled_height],
                    },
                    "prior_visual_evidence": {
                        "prior_timing_authorities": lifecycle_info["prior_authorities"],
                        "prior_visual_source_exactness": lifecycle_info["prior_visual_source_exactness"],
                        "word_track_rows_available": len(track_rows),
                        "accepted_word_track_rows": sum(
                            1 for row in track_rows if row.get("accepted_source_instance") is True
                        ),
                    },
                    "frame_path": frame_path,
                    "explicit_frame_row_count": len(frame_path),
                }
            )
    finally:
        video.close()

    instance_ids = [row["instance_id"] for row in instances]
    require(len(instance_ids) == len(set(instance_ids)) == EXPECTED_INSTANCE_COUNT, "instance_identity")
    require(direct_visual_count + pixel_redetected_count == EXPECTED_INSTANCE_COUNT, "authority_partition")
    require(pixel_redetected_count > 0, "pixel_redetection_required")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "video_id": VIDEO_ID,
        "ok": True,
        "authority_policy": {
            "primary_authority": "source_video_pixels_and_previously_accepted_source_visual_tracks",
            "transcript_text_allowed_as_metadata": True,
            "transcript_timing_authority": False,
            "explicit_frame_paths_required": True,
            "resolve_modified": False,
            "protected_v4_tokens_modified": False,
            "remaining_caption_rollout_authorized": False,
            "visual_approval_required_after_rollout": True,
            "known_deferred_issue": "fade_in_fade_out_fidelity_polish_after_rollout",
        },
        "inputs": {
            key: {
                "path": str(path.relative_to(repo_root)),
                "sha256": raw_sha256(path),
            }
            for key, path in paths.items()
        },
        "source_video": {
            "sha256": source_hash,
            "source_fps": round(video.source_fps, 6),
            "timeline_fps": TIMELINE_FPS,
            "source_dimensions": [video.source_width, video.source_height],
            "analysis_dimensions": [scaled_width, scaled_height],
        },
        "protected_v4": {
            "token_count": len(v4_tokens),
            "source_cue_count": len(protected_cues),
            "source_cue_ids": sorted(protected_cues),
            "semantic_sha256": str(v4.get("semantic_sha256") or canonical_sha256(v4)),
        },
        "summary": {
            "remaining_instance_count": len(instances),
            "accepted_visual_primary_instance_count": direct_visual_count,
            "source_pixel_redetected_instance_count": pixel_redetected_count,
            "low_confidence_pixel_readback_count": low_confidence_count,
            "explicit_frame_row_count": total_rows,
            "protected_v4_token_count": len(v4_tokens),
            "protected_v4_source_cue_count": len(protected_cues),
            "resolve_modified": False,
            "remaining_caption_rollout_authorized": False,
        },
        "instances": instances,
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_REMAINING100_FULL_ROLLOUT_V1_AFTER_TECHNICAL_VALIDATION",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else (root / DEFAULT_OUTPUT)
    try:
        result = build(root, output)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    summary = result["summary"]
    print(
        f"PASS {TASK_ID}: instances={summary['remaining_instance_count']} "
        f"visual_primary={summary['accepted_visual_primary_instance_count']} "
        f"pixel_redetected={summary['source_pixel_redetected_instance_count']} "
        f"rows={summary['explicit_frame_row_count']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
