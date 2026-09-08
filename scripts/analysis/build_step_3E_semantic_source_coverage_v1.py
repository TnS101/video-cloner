#!/usr/bin/env python3
"""Expand semantic source coverage for excluded Step 3E caption rows.

This is a read-only source-video analysis boundary.  The current universal
visual-repair authority intentionally excludes structural Text+ rows that lack
semantic source confirmation.  This builder actively evaluates every excluded
row using two source-grounded signals:

1. source-pixel visibility windows from the existing remaining-100 authority
   are search priors only; they never establish semantic identity by themselves;
2. PaddleOCR text matches inside those source-pixel windows establish semantic
   identity, with local-crop OCR used only as a recovery pass for small/stylised
   glyphs.

Rows already represented by an accepted protected composite visual layer are
classified as source_absent_or_nonsemantic for the redundant structural row.
All other failed probes remain source_unresolved.  No row may remain
source_not_evaluated and this step never authorizes a Resolve repair rollout.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np

TASK_ID = "DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1"
EXPECTED_TOTAL = 117
EXPECTED_PROTECTED = 17
EXPECTED_EXCLUDED = 53
CURRENT_AUTHORITY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/"
    "universal_visual_repair_authority_v1.json"
)
REMAINING_AUTHORITY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_REMAINING100_VISUAL_AUTHORITY_V1/"
    "remaining100_visual_authority_v1.json"
)
OCR_MODULE = Path("scripts/davinci/redetect_caption_word_instances_step_3B_6.py")
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/"
    "semantic_source_coverage_v1.json"
)


class BuildError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BuildError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_ocr_module(repo_root: Path):
    path = repo_root / OCR_MODULE
    require(path.is_file(), f"missing_ocr_module:{path}")
    spec = importlib.util.spec_from_file_location("vc_step_3b6b_semantic_probe", path)
    require(spec is not None and spec.loader is not None, f"ocr_module_load:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def compact_text(value: Any) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def text_similarity(a: Any, b: Any) -> float:
    from difflib import SequenceMatcher

    aa, bb = compact_text(a), compact_text(b)
    if not aa or not bb:
        return 0.0
    if aa == bb:
        return 1.0
    ratio = SequenceMatcher(None, aa, bb).ratio()
    if aa in bb or bb in aa:
        ratio = max(ratio, min(len(aa), len(bb)) / max(len(aa), len(bb)))
    return round(clamp(ratio, 0.0, 1.0), 6)


def evenly_spaced(values: Sequence[int], limit: int) -> list[int]:
    ordered = sorted(set(int(v) for v in values))
    if len(ordered) <= limit:
        return ordered
    if limit <= 1:
        return [ordered[len(ordered) // 2]]
    indices = {round(i * (len(ordered) - 1) / (limit - 1)) for i in range(limit)}
    return [ordered[i] for i in sorted(indices)]


def probe_frames_for_row(row: Mapping[str, Any], *, max_frames: int) -> list[int]:
    """Choose deterministic source-pixel-supported timeline frames.

    Transcript/cue timing is intentionally absent here.  The only temporal
    inputs are the prior source-pixel scan and its derived visual window.
    """
    scan = row.get("source_pixel_scan") if isinstance(row.get("source_pixel_scan"), Mapping) else {}
    selected = [int(v) for v in scan.get("selected_frames") or []]
    peak = scan.get("peak_frame")
    window = row.get("visual_window") if isinstance(row.get("visual_window"), list) else None
    candidates = list(selected)
    if peak is not None:
        candidates.append(int(peak))
    if window and len(window) == 2 and int(window[1]) > int(window[0]):
        start, end = int(window[0]), int(window[1])
        candidates.extend([start, (start + end - 1) // 2, end - 1])
    candidates = sorted(set(v for v in candidates if v >= 0))
    return evenly_spaced(candidates, max_frames)


def position_for_frame(row: Mapping[str, Any], frame: int) -> tuple[float, float]:
    for item in row.get("frame_path") or []:
        if not isinstance(item, Mapping) or int(item.get("timeline_frame") or -1) != int(frame):
            continue
        value = item.get("position_top_origin")
        if isinstance(value, list) and len(value) == 2:
            return clamp(float(value[0]), 0.0, 1.0), clamp(float(value[1]), 0.0, 1.0)
    seed = row.get("source_pixel_seed") if isinstance(row.get("source_pixel_seed"), Mapping) else {}
    value = seed.get("center_top_origin")
    if isinstance(value, list) and len(value) == 2:
        return clamp(float(value[0]), 0.0, 1.0), clamp(float(value[1]), 0.0, 1.0)
    return 0.5, 0.48


def expected_geometry_source_px(row: Mapping[str, Any], source_width: int, source_height: int) -> tuple[float, float]:
    seed = row.get("source_pixel_seed") if isinstance(row.get("source_pixel_seed"), Mapping) else {}
    # remaining100 source_pixel_seed geometry is measured at 540x960.
    ew = max(8.0, float(seed.get("expected_width_px") or 80.0)) * source_width / 540.0
    eh = max(8.0, float(seed.get("expected_height_px") or 28.0)) * source_height / 960.0
    return ew, eh


def protected_composite_map(authority: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Map structural instance IDs already represented by protected composites."""
    result: dict[str, dict[str, Any]] = {}
    for row in authority.get("instances") or []:
        if not isinstance(row, Mapping) or row.get("presence_status") != "protected_existing":
            continue
        resolution = row.get("text_resolution") if isinstance(row.get("text_resolution"), Mapping) else {}
        if not resolution.get("ok"):
            continue
        ids = [str(v) for v in resolution.get("source_instance_ids") or [] if str(v)]
        for instance_id in ids:
            require(instance_id not in result, f"composite_duplicate_source:{instance_id}")
            result[instance_id] = {
                "protected_instance_id": str(row.get("instance_id") or ""),
                "protected_target_name": str(row.get("target_name") or ""),
                "protected_text": str(row.get("canonical_text") or ""),
                "resolution_method": str(resolution.get("method") or ""),
                "source_instance_ids": ids,
            }
    return result


def bbox_center(box: Sequence[float]) -> tuple[float, float]:
    return (float(box[0]) + float(box[2])) * 0.5, (float(box[1]) + float(box[3])) * 0.5


def bbox_size(box: Sequence[float]) -> tuple[float, float]:
    return max(1.0, float(box[2]) - float(box[0])), max(1.0, float(box[3]) - float(box[1]))


def semantic_candidate_score(
    candidate: Any,
    canonical_text: str,
    expected_center: tuple[float, float],
    expected_size: tuple[float, float],
    frame_width: int,
    frame_height: int,
    *,
    min_text_similarity: float,
    crop_localized: bool,
) -> dict[str, float] | None:
    similarity = text_similarity(canonical_text, getattr(candidate, "text", ""))
    if similarity < min_text_similarity:
        return None
    confidence = clamp(float(getattr(candidate, "confidence", 0.0)), 0.0, 1.0)
    bbox = [float(v) for v in getattr(candidate, "bbox", [])]
    if len(bbox) != 4:
        return None
    cx, cy = bbox_center(bbox)
    sx, sy = expected_center
    ew, eh = expected_size
    dx = abs(cx - sx) / max(28.0, ew * 1.25)
    dy = abs(cy - sy) / max(24.0, eh * 1.80)
    spatial = math.exp(-(0.75 * dx + 1.0 * dy))

    compact_len = len(compact_text(canonical_text))
    # Very short tokens are semantically ambiguous; require exact OCR text and
    # meaningful spatial support.  This is token-shape generic, not word-specific.
    if compact_len <= 2 and similarity < 1.0:
        return None
    if not crop_localized and spatial < (0.20 if compact_len >= 4 else 0.32):
        return None

    cw, ch = bbox_size(bbox)
    size_error = abs(math.log(cw / max(ew, 1.0))) + 0.65 * abs(math.log(ch / max(eh, 1.0)))
    size_score = math.exp(-0.45 * size_error)
    score = clamp(0.68 * similarity + 0.18 * confidence + 0.10 * spatial + 0.04 * size_score, 0.0, 1.0)
    return {
        "score": round(score, 6),
        "text_similarity": round(similarity, 6),
        "ocr_confidence": round(confidence, 6),
        "spatial_score": round(spatial, 6),
        "size_score": round(size_score, 6),
    }


def best_candidate(
    candidates: Iterable[Any],
    canonical_text: str,
    expected_center: tuple[float, float],
    expected_size: tuple[float, float],
    frame_width: int,
    frame_height: int,
    *,
    min_text_similarity: float,
    crop_localized: bool,
) -> tuple[Any, dict[str, float]] | None:
    scored: list[tuple[float, float, float, Any, dict[str, float]]] = []
    for candidate in candidates:
        detail = semantic_candidate_score(
            candidate,
            canonical_text,
            expected_center,
            expected_size,
            frame_width,
            frame_height,
            min_text_similarity=min_text_similarity,
            crop_localized=crop_localized,
        )
        if detail is None:
            continue
        scored.append((detail["score"], detail["text_similarity"], detail["ocr_confidence"], candidate, detail))
    if not scored:
        return None
    scored.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return scored[0][3], scored[0][4]


def source_frame_for_timeline_frame(timeline_frame: int, timeline_fps: float, source_fps: float, source_count: int) -> int:
    index = int(round(float(timeline_frame) * source_fps / timeline_fps))
    return max(0, min(source_count - 1, index))


class VideoReader:
    def __init__(self, path: Path, timeline_fps: float):
        self.path = path
        self.timeline_fps = float(timeline_fps)
        self.cap = cv2.VideoCapture(str(path))
        require(self.cap.isOpened(), f"video_open:{path}")
        self.width = int(round(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0))
        self.height = int(round(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0))
        self.fps = float(self.cap.get(cv2.CAP_PROP_FPS) or 0.0)
        self.count = int(round(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0))
        require(self.width > 0 and self.height > 0 and self.fps > 0 and self.count > 0, "video_metadata")
        self.current_source_frame = -1

    def reset(self) -> None:
        self.cap.release()
        self.cap = cv2.VideoCapture(str(self.path))
        require(self.cap.isOpened(), f"video_reopen:{self.path}")
        self.current_source_frame = -1

    def read(self, timeline_frame: int) -> tuple[int, np.ndarray]:
        source_frame = source_frame_for_timeline_frame(timeline_frame, self.timeline_fps, self.fps, self.count)
        # Callers iterate timeline frames in ascending order. Decode forward
        # instead of doing hundreds of codec seeks, which is materially faster
        # and deterministic for the short source reel. A backwards request
        # starts a clean sequential pass.
        if source_frame <= self.current_source_frame:
            self.reset()
        frame = None
        while self.current_source_frame < source_frame:
            ok, frame = self.cap.read()
            self.current_source_frame += 1
            require(ok and frame is not None, f"frame_read:{timeline_frame}:{source_frame}")
        require(frame is not None, f"frame_read_empty:{timeline_frame}:{source_frame}")
        return source_frame, frame

    def close(self) -> None:
        self.cap.release()


def crop_for_probe(
    frame: np.ndarray,
    center_norm: tuple[float, float],
    expected_size: tuple[float, float],
) -> tuple[np.ndarray, tuple[int, int], tuple[float, float]]:
    height, width = frame.shape[:2]
    cx, cy = center_norm[0] * width, center_norm[1] * height
    ew, eh = expected_size
    half_w = int(round(clamp(ew * 1.45 + 50.0, 120.0, width * 0.42)))
    half_h = int(round(clamp(eh * 2.20 + 42.0, 90.0, height * 0.24)))
    x0, x1 = max(0, int(round(cx)) - half_w), min(width, int(round(cx)) + half_w + 1)
    y0, y1 = max(0, int(round(cy)) - half_h), min(height, int(round(cy)) + half_h + 1)
    crop = frame[y0:y1, x0:x1]
    require(crop.size > 0, "empty_probe_crop")

    scale = max(1.0, min(3.0, 300.0 / max(1.0, crop.shape[0])))
    if scale > 1.01:
        probe = cv2.resize(
            crop,
            (max(1, int(round(crop.shape[1] * scale))), max(1, int(round(crop.shape[0] * scale)))),
            interpolation=cv2.INTER_CUBIC,
        )
    else:
        probe = crop
    return probe, (x0, y0), (1.0 / scale, 1.0 / scale)


def candidate_to_observation(
    candidate: Any,
    detail: Mapping[str, Any],
    timeline_frame: int,
    source_frame: int,
    frame_width: int,
    frame_height: int,
    *,
    method: str,
    offset: tuple[int, int] = (0, 0),
) -> dict[str, Any]:
    box = [float(v) for v in getattr(candidate, "bbox", [])]
    require(len(box) == 4, "candidate_bbox")
    x0, y0 = offset
    full = [box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0]
    normalized = [
        round(full[0] / frame_width, 8),
        round(full[1] / frame_height, 8),
        round(full[2] / frame_width, 8),
        round(full[3] / frame_height, 8),
    ]
    return {
        "timeline_frame": int(timeline_frame),
        "source_frame": int(source_frame),
        "method": method,
        "ocr_text": str(getattr(candidate, "text", "")),
        "ocr_source_text": str(getattr(candidate, "source_text", "")),
        "candidate_kind": str(getattr(candidate, "source_kind", "")),
        "ocr_confidence": round(float(detail["ocr_confidence"]), 6),
        "text_similarity": round(float(detail["text_similarity"]), 6),
        "semantic_score": round(float(detail["score"]), 6),
        "spatial_score": round(float(detail["spatial_score"]), 6),
        "normalized_bbox": normalized,
    }


def classify_probe(
    observations: Sequence[Mapping[str, Any]],
    *,
    source_pixel_detected_frames: int,
    source_pixel_confidence: str,
    min_median_similarity: float,
    min_median_confidence: float,
) -> tuple[str, list[str]]:
    if not observations:
        return "source_unresolved", ["no_semantic_ocr_match_in_source_pixel_probe"]
    similarities = [float(row.get("text_similarity") or 0.0) for row in observations]
    confidences = [float(row.get("ocr_confidence") or 0.0) for row in observations]
    if len(observations) >= 2 and median(similarities) >= min_median_similarity and median(confidences) >= min_median_confidence:
        return "source_confirmed", []
    if (
        len(observations) == 1
        and int(source_pixel_detected_frames) == 1
        and str(source_pixel_confidence).lower() == "high"
        and similarities[0] >= 0.90
        and confidences[0] >= 0.70
    ):
        return "source_confirmed", ["single_frame_source_caption_high_confidence"]
    reasons = []
    if len(observations) < 2:
        reasons.append("fewer_than_two_semantic_ocr_frames")
    if median(similarities) < min_median_similarity:
        reasons.append("median_text_similarity_below_threshold")
    if median(confidences) < min_median_confidence:
        reasons.append("median_ocr_confidence_below_threshold")
    return "source_unresolved", reasons or ["semantic_probe_not_confirmed"]


def build(repo_root: Path, output_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    authority_path = repo_root / CURRENT_AUTHORITY
    remaining_path = repo_root / REMAINING_AUTHORITY
    for path in (authority_path, remaining_path, repo_root / OCR_MODULE):
        require(path.is_file(), f"missing_input:{path}")
    authority = load_json(authority_path)
    remaining = load_json(remaining_path)
    require(int((authority.get("summary") or {}).get("total_instances") or 0) == EXPECTED_TOTAL, "authority_total")
    require(int((authority.get("summary") or {}).get("protected_existing_instances") or 0) == EXPECTED_PROTECTED, "authority_protected")
    require(authority.get("policy", {}).get("repair_rollout_authorized") is False, "authority_rollout_lock")
    require(authority.get("policy", {}).get("transcript_timing_authority") is False, "authority_transcript_policy")

    excluded = [
        row for row in authority.get("instances") or []
        if isinstance(row, Mapping) and row.get("presence_status") in {"source_unresolved", "source_not_evaluated"}
    ]
    require(len(excluded) == EXPECTED_EXCLUDED, f"excluded_count:{len(excluded)}")
    excluded_ids = [str(row.get("instance_id") or "") for row in excluded]
    require(len(excluded_ids) == len(set(excluded_ids)) == EXPECTED_EXCLUDED, "excluded_identity")

    remaining_map = {
        str(row.get("instance_id") or ""): row
        for row in remaining.get("instances") or []
        if isinstance(row, Mapping) and row.get("instance_id")
    }
    require(all(instance_id in remaining_map for instance_id in excluded_ids), "excluded_missing_remaining_row")

    protected_map = protected_composite_map(authority)
    ocr = load_ocr_module(repo_root)

    inputs = authority.get("inputs") if isinstance(authority.get("inputs"), Mapping) else {}
    source_info = inputs.get("source_video") if isinstance(inputs.get("source_video"), Mapping) else {}
    source_rel = Path(str(source_info.get("path") or "input/DZsqH7auhjt.mp4").replace("\\", "/"))
    source_path = repo_root / source_rel
    require(source_path.is_file(), f"source_video:{source_path}")
    expected_source_hash = str(source_info.get("sha256") or "")
    if expected_source_hash:
        require(sha256(source_path) == expected_source_hash, "source_video_sha256")

    source_meta = remaining.get("source_video") if isinstance(remaining.get("source_video"), Mapping) else {}
    timeline_fps = float(source_meta.get("timeline_fps") or 24.0)
    reader = VideoReader(source_path, timeline_fps)
    engine, ocr_info = ocr.create_ocr(args.ocr_lang, args.ocr_device, args.ocr_gpu_id)

    target_rows = {instance_id: remaining_map[instance_id] for instance_id in excluded_ids}
    probe_frames: dict[str, list[int]] = {
        instance_id: probe_frames_for_row(row, max_frames=args.max_probe_frames)
        for instance_id, row in target_rows.items()
    }
    require(all(probe_frames[instance_id] for instance_id in excluded_ids if instance_id not in protected_map), "empty_probe_frames")

    active_by_frame: dict[int, list[str]] = defaultdict(list)
    for instance_id, frames in probe_frames.items():
        if instance_id in protected_map:
            continue
        for frame in frames:
            active_by_frame[int(frame)].append(instance_id)

    observations: dict[str, dict[int, dict[str, Any]]] = defaultdict(dict)
    full_frame_candidate_counts: dict[str, int] = defaultdict(int)
    local_probe_counts: dict[str, int] = defaultdict(int)
    ocr_errors: dict[str, list[str]] = defaultdict(list)

    try:
        with tempfile.TemporaryDirectory(prefix="vc_step3e_semantic_coverage_") as temp_name:
            temp_dir = Path(temp_name)
            # First pass: one full-frame OCR call per unique source-pixel-supported frame.
            full_frames = sorted(active_by_frame)
            for frame_index, timeline_frame in enumerate(full_frames, start=1):
                if frame_index == 1 or frame_index % 20 == 0 or frame_index == len(full_frames):
                    print(f"[semantic-coverage] full-frame OCR {frame_index}/{len(full_frames)} timeline_frame={timeline_frame}", flush=True)
                source_frame, frame = reader.read(timeline_frame)
                ocr_frame, scale_x, scale_y = ocr.resize_for_ocr(frame, args.ocr_max_side)
                try:
                    parsed = ocr.parse_paddle_result(ocr.run_ocr(engine, ocr_frame, temp_dir, f"full_{timeline_frame}"))
                    candidates = ocr.build_candidates(
                        parsed,
                        scale_x,
                        scale_y,
                        reader.width,
                        reader.height,
                        args.min_ocr_confidence,
                    )
                except Exception as exc:  # noqa: BLE001
                    candidates = []
                    error = f"full_frame_ocr:{timeline_frame}:{type(exc).__name__}:{exc}"
                    for instance_id in active_by_frame[timeline_frame]:
                        ocr_errors[instance_id].append(error)
                for instance_id in active_by_frame[timeline_frame]:
                    row = target_rows[instance_id]
                    center_norm = position_for_frame(row, timeline_frame)
                    expected_size = expected_geometry_source_px(row, reader.width, reader.height)
                    expected_center = (center_norm[0] * reader.width, center_norm[1] * reader.height)
                    full_frame_candidate_counts[instance_id] += len(candidates)
                    matched = best_candidate(
                        candidates,
                        str(row.get("canonical_text") or ""),
                        expected_center,
                        expected_size,
                        reader.width,
                        reader.height,
                        min_text_similarity=args.min_text_similarity,
                        crop_localized=False,
                    )
                    if matched is None:
                        continue
                    candidate, detail = matched
                    observations[instance_id][timeline_frame] = candidate_to_observation(
                        candidate,
                        detail,
                        timeline_frame,
                        source_frame,
                        reader.width,
                        reader.height,
                        method="full_frame_ocr",
                    )

            # Recovery pass: targeted pixel-localized crops only for rows that do
            # not yet have two semantic observations. Build requests first and
            # process them in frame order so the video is decoded sequentially.
            local_requests: dict[int, list[str]] = defaultdict(list)
            for instance_id in excluded_ids:
                if instance_id in protected_map or len(observations[instance_id]) >= 2:
                    continue
                row = target_rows[instance_id]
                candidate_frames = probe_frames[instance_id]
                scan = row.get("source_pixel_scan") if isinstance(row.get("source_pixel_scan"), Mapping) else {}
                peak = scan.get("peak_frame")
                ordered = []
                if peak is not None and int(peak) in candidate_frames:
                    ordered.append(int(peak))
                ordered.extend(frame for frame in candidate_frames if frame not in ordered)
                for timeline_frame in ordered[: args.max_local_probe_frames]:
                    if timeline_frame not in observations[instance_id]:
                        local_requests[int(timeline_frame)].append(instance_id)

            local_frames = sorted(local_requests)
            if local_frames:
                reader.reset()
            for frame_index, timeline_frame in enumerate(local_frames, start=1):
                if frame_index == 1 or frame_index % 20 == 0 or frame_index == len(local_frames):
                    print(f"[semantic-coverage] local-crop OCR {frame_index}/{len(local_frames)} timeline_frame={timeline_frame}", flush=True)
                source_frame, frame = reader.read(timeline_frame)
                for instance_id in local_requests[timeline_frame]:
                    if len(observations[instance_id]) >= 2:
                        continue
                    row = target_rows[instance_id]
                    center_norm = position_for_frame(row, timeline_frame)
                    expected_size = expected_geometry_source_px(row, reader.width, reader.height)
                    expected_center = (center_norm[0] * reader.width, center_norm[1] * reader.height)
                    try:
                        probe, offset, map_scale = crop_for_probe(frame, center_norm, expected_size)
                        parsed = ocr.parse_paddle_result(
                            ocr.run_ocr(engine, probe, temp_dir, f"crop_{instance_id}_{timeline_frame}")
                        )
                        crop_width = int(round(probe.shape[1] * map_scale[0]))
                        crop_height = int(round(probe.shape[0] * map_scale[1]))
                        candidates = ocr.build_candidates(
                            parsed,
                            map_scale[0],
                            map_scale[1],
                            crop_width,
                            crop_height,
                            args.min_ocr_confidence,
                        )
                        local_center = (expected_center[0] - offset[0], expected_center[1] - offset[1])
                        matched = best_candidate(
                            candidates,
                            str(row.get("canonical_text") or ""),
                            local_center,
                            expected_size,
                            crop_width,
                            crop_height,
                            min_text_similarity=args.min_text_similarity,
                            crop_localized=True,
                        )
                        local_probe_counts[instance_id] += 1
                    except Exception as exc:  # noqa: BLE001
                        matched = None
                        ocr_errors[instance_id].append(
                            f"local_crop_ocr:{timeline_frame}:{type(exc).__name__}:{exc}"
                        )
                    if matched is None:
                        continue
                    candidate, detail = matched
                    observations[instance_id][timeline_frame] = candidate_to_observation(
                        candidate,
                        detail,
                        timeline_frame,
                        source_frame,
                        reader.width,
                        reader.height,
                        method="source_pixel_local_crop_ocr",
                        offset=offset,
                    )
    finally:
        reader.close()

    coverage_rows: list[dict[str, Any]] = []
    for authority_row in excluded:
        instance_id = str(authority_row.get("instance_id") or "")
        remaining_row = target_rows[instance_id]
        scan = remaining_row.get("source_pixel_scan") if isinstance(remaining_row.get("source_pixel_scan"), Mapping) else {}
        original_status = str(authority_row.get("presence_status") or "")
        common = {
            "instance_id": instance_id,
            "target_name": str(authority_row.get("target_name") or ""),
            "canonical_text": str(authority_row.get("canonical_text") or ""),
            "source_cue_ids": [str(v) for v in authority_row.get("source_cue_ids") or []],
            "original_presence_status": original_status,
            "transcript_timing_authority": False,
            "search_prior": {
                "authority": "source_pixel_visibility_only",
                "probe_frames": probe_frames[instance_id],
                "source_pixel_selected_frames": [int(v) for v in scan.get("selected_frames") or []],
                "source_pixel_peak_frame": int(scan.get("peak_frame")) if scan.get("peak_frame") is not None else None,
                "source_pixel_confidence": str(scan.get("confidence") or "unknown"),
                "source_pixel_search_window": [int(v) for v in scan.get("search_window") or []],
                "cue_or_transcript_window_used_as_authority": False,
            },
        }
        if instance_id in protected_map:
            coverage_rows.append(
                {
                    **common,
                    "coverage_status": "source_absent_or_nonsemantic",
                    "semantic_basis": "represented_by_protected_composite_visual_layer",
                    "semantic_observations": [],
                    "semantic_observation_count": 0,
                    "protected_composite": protected_map[instance_id],
                    "probe_evidence": {
                        "full_frame_candidate_count": 0,
                        "local_crop_probe_count": 0,
                        "ocr_errors": [],
                        "reasons": ["redundant_structural_row_represented_by_accepted_visual_composite"],
                    },
                }
            )
            continue

        rows = [observations[instance_id][frame] for frame in sorted(observations[instance_id])]
        status, reasons = classify_probe(
            rows,
            source_pixel_detected_frames=int(scan.get("detected_frame_count") or 0),
            source_pixel_confidence=str(scan.get("confidence") or ""),
            min_median_similarity=args.min_text_similarity,
            min_median_confidence=args.min_median_ocr_confidence,
        )
        similarities = [float(row.get("text_similarity") or 0.0) for row in rows]
        confidences = [float(row.get("ocr_confidence") or 0.0) for row in rows]
        coverage_rows.append(
            {
                **common,
                "coverage_status": status,
                "semantic_basis": "source_ocr_inside_source_pixel_visibility_prior" if status == "source_confirmed" else "semantic_probe_inconclusive",
                "semantic_observations": rows,
                "semantic_observation_count": len(rows),
                "protected_composite": None,
                "probe_evidence": {
                    "full_frame_candidate_count": int(full_frame_candidate_counts[instance_id]),
                    "local_crop_probe_count": int(local_probe_counts[instance_id]),
                    "ocr_errors": ocr_errors[instance_id],
                    "median_text_similarity": round(float(median(similarities)), 6) if similarities else 0.0,
                    "median_ocr_confidence": round(float(median(confidences)), 6) if confidences else 0.0,
                    "reasons": reasons,
                },
            }
        )

    statuses = {name: sum(1 for row in coverage_rows if row["coverage_status"] == name) for name in (
        "source_confirmed",
        "source_absent_or_nonsemantic",
        "source_unresolved",
        "source_not_evaluated",
    )}
    require(len(coverage_rows) == EXPECTED_EXCLUDED, "coverage_total")
    require(statuses["source_not_evaluated"] == 0, "coverage_not_evaluated")
    require(sum(statuses.values()) == EXPECTED_EXCLUDED, "coverage_partition")

    result = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "source_video_pixels_plus_semantic_ocr",
            "source_pixel_windows_are_search_priors_only": True,
            "transcript_timing_authority": False,
            "geometry_only_cannot_confirm_semantics": True,
            "negative_ocr_alone_cannot_prove_absence": True,
            "protected_composite_can_reconcile_redundant_structural_rows": True,
            "per_cue_hardcoded_overrides": False,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "inputs": {
            "current_authority": {"path": str(CURRENT_AUTHORITY), "sha256": sha256(authority_path)},
            "remaining_authority": {"path": str(REMAINING_AUTHORITY), "sha256": sha256(remaining_path)},
            "ocr_module": {"path": str(OCR_MODULE), "sha256": sha256(repo_root / OCR_MODULE)},
            "source_video": {"path": str(source_rel), "sha256": sha256(source_path)},
        },
        "configuration": {
            "ocr_lang": args.ocr_lang,
            "ocr_device": ocr_info.get("selected_device"),
            "ocr_engine": ocr_info.get("engine"),
            "ocr_max_side": args.ocr_max_side,
            "min_ocr_confidence": args.min_ocr_confidence,
            "min_text_similarity": args.min_text_similarity,
            "min_median_ocr_confidence": args.min_median_ocr_confidence,
            "max_probe_frames": args.max_probe_frames,
            "max_local_probe_frames": args.max_local_probe_frames,
        },
        "summary": {
            "evaluated_excluded_instances": len(coverage_rows),
            "source_confirmed_instances": statuses["source_confirmed"],
            "source_absent_or_nonsemantic_instances": statuses["source_absent_or_nonsemantic"],
            "source_unresolved_instances": statuses["source_unresolved"],
            "source_not_evaluated_instances": statuses["source_not_evaluated"],
            "protected_composite_reconciled_instances": statuses["source_absent_or_nonsemantic"],
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "coverage": coverage_rows,
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_MERGE_SEMANTIC_COVERAGE_INTO_UNIVERSAL_AUTHORITY_AFTER_VALIDATION",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--ocr-lang", default="en")
    parser.add_argument("--ocr-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--ocr-gpu-id", type=int, default=0)
    parser.add_argument("--ocr-max-side", type=int, default=1600)
    parser.add_argument("--min-ocr-confidence", type=float, default=0.20)
    parser.add_argument("--min-text-similarity", type=float, default=0.62)
    parser.add_argument("--min-median-ocr-confidence", type=float, default=0.24)
    parser.add_argument("--max-probe-frames", type=int, default=7)
    parser.add_argument("--max-local-probe-frames", type=int, default=4)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = args.root.resolve()
    output = args.output.resolve() if args.output else root / DEFAULT_OUTPUT
    try:
        result = build(root, output, args)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    summary = result["summary"]
    print(
        f"PASS {TASK_ID}: evaluated={summary['evaluated_excluded_instances']} "
        f"confirmed={summary['source_confirmed_instances']} "
        f"absent_or_nonsemantic={summary['source_absent_or_nonsemantic_instances']} "
        f"unresolved={summary['source_unresolved_instances']} not_evaluated={summary['source_not_evaluated_instances']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
