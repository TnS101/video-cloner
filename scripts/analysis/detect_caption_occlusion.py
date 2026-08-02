#!/usr/bin/env python3
"""
detect_caption_occlusion.py

Video Cloner - caption foreground occlusion detector.

Purpose
-------
Detect caption/text events that appear partially behind a foreground subject/object,
or that are likely to require a foreground matte layer in an editor.

This script is editor-agnostic and does not modify a Resolve timeline. In addition to
creating a structured occlusion contract, it can persist full-frame per-frame foreground
alpha-mask PNG sequences for events that require foreground compositing. Later DaVinci /
FCPXML / OpenReel backends can consume those assets.

Expected future editor reconstruction:
    V1 = base video
    V2 = TextPlus / editable caption clips
    V3 = foreground matte / subject cutout layer above captions

Inputs
------
Required:
    --video          Source/full-res video path.
    --caption-style  Output JSON from detect_caption_style.py v5.2/v5.3+.
    --output         Output *_caption_occlusion.json path.

Optional but recommended:
    --transcript     Transcript JSON with segments/words/subtitle_candidates.

Backends
--------
    auto_gpu             Try Paddle GPU human segmentation first, then MediaPipe, then heuristic.
    paddle_humanseg      PaddleHub humanseg_lite / PP-HumanSeg-style backend using Paddle GPU.
    paddlehub_humanseg   Alias for paddle_humanseg.
    auto                 Try Paddle GPU if available, then MediaPipe, GrabCut, then heuristic.
    mediapipe            Optional MediaPipe Selfie Segmentation backend. Best CPU fallback for talking-head reels.
    grabcut              OpenCV GrabCut foreground approximation. CPU fallback.
    heuristic            Lightweight color/edge/skin/saliency heuristic. Fastest, weakest.

Important limitation
--------------------
Without a true segmentation model, occlusion detection is a best-effort estimate.
The JSON reports confidence, backend used, and mask-asset completeness. Treat
"needs_foreground_mask" as a signal for later compositing. A complete exported mask
sequence is still a segmentation estimate and must be visually validated.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2
import numpy as np

ANALYSIS_VERSION = "caption_occlusion_v1_9_classification_promotion_cue_reconciliation"
SCHEMA = "video_cloner_caption_occlusion"
SCHEMA_VERSION = "1.5"


# -----------------------------------------------------------------------------
# Generic helpers
# -----------------------------------------------------------------------------


def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    s = str(value).strip().lower()
    if s in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if s in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Boolean expected, got: {value}")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        value_f = float(value)
        if math.isnan(value_f) or math.isinf(value_f):
            return default
        return value_f
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        value_f = float(value)
        if math.isnan(value_f) or math.isinf(value_f):
            return default
        return int(round(value_f))
    except Exception:
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def round4(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return round(float(value), 4)
    except Exception:
        return default


def load_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def make_json_safe(value: Any, _stack: Optional[set] = None) -> Any:
    """Convert nested objects into JSON-safe values and break circular references.

    This protects n8n runs from failures like:
        ValueError: Circular reference detected

    It also normalizes numpy values, Path objects, tuples and sets.
    """
    if _stack is None:
        _stack = set()

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, np.ndarray):
        if value.size <= 2048:
            return value.tolist()
        return {
            "type": "ndarray",
            "shape": list(value.shape),
            "dtype": str(value.dtype),
            "min": safe_float(np.min(value), 0.0) if value.size else 0.0,
            "max": safe_float(np.max(value), 0.0) if value.size else 0.0,
        }

    if isinstance(value, dict):
        obj_id = id(value)
        if obj_id in _stack:
            return "<circular_reference>"
        _stack.add(obj_id)
        try:
            return {str(k): make_json_safe(v, _stack) for k, v in value.items()}
        finally:
            _stack.remove(obj_id)

    if isinstance(value, (list, tuple, set)):
        obj_id = id(value)
        if obj_id in _stack:
            return "<circular_reference>"
        _stack.add(obj_id)
        try:
            return [make_json_safe(v, _stack) for v in value]
        finally:
            _stack.remove(obj_id)

    try:
        json.dumps(value)
        return value
    except Exception:
        return str(value)


def write_json(path: str, data: Dict[str, Any], encoding: str = "utf-8") -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    safe_data = make_json_safe(data)
    with open(path, "w", encoding=encoding) as f:
        json.dump(safe_data, f, ensure_ascii=False, indent=2)
        f.flush()


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_match_text(text: Any) -> str:
    text = clean_text(text).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9а-яё'’]+", " ", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def token_set(text: Any) -> set:
    norm = normalize_match_text(text)
    return {t for t in norm.split() if t} if norm else set()


def fuzzy_similarity(a: Any, b: Any) -> float:
    import difflib

    a_norm = normalize_match_text(a)
    b_norm = normalize_match_text(b)
    if not a_norm or not b_norm:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a_norm, b_norm).ratio()
    a_tokens = token_set(a_norm)
    b_tokens = token_set(b_norm)
    if not a_tokens or not b_tokens:
        return round(float(ratio), 4)
    overlap = len(a_tokens & b_tokens) / max(1, min(len(a_tokens), len(b_tokens)))
    jaccard = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    return round(float(clamp((0.50 * ratio) + (0.35 * overlap) + (0.15 * jaccard), 0.0, 1.0)), 4)


def now_unix() -> float:
    return round(time.time(), 3)


# -----------------------------------------------------------------------------
# Video helpers
# -----------------------------------------------------------------------------


def read_video_info(video_path: str) -> Dict[str, Any]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"path": video_path, "opened": False}
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = (frame_count / fps) if fps > 0 and frame_count > 0 else 0.0
    cap.release()
    return {
        "path": video_path,
        "opened": True,
        "fps": round(float(fps), 4) if fps else None,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": round(float(duration), 4) if duration else None,
        "orientation": "vertical" if height > width else "horizontal" if width > height else "square",
    }


def read_frame_at(cap: cv2.VideoCapture, timestamp: float, duration: float) -> Tuple[bool, Optional[np.ndarray], float]:
    """Read the nearest valid frame without seeking to the non-decodable end boundary."""
    fps = safe_float(cap.get(cv2.CAP_PROP_FPS), 0.0)
    frame_count = safe_int(cap.get(cv2.CAP_PROP_FRAME_COUNT), 0)
    if fps > 0 and frame_count > 0:
        last_frame_time = max(0.0, (frame_count - 1) / fps)
        max_ts = min(max(0.0, duration - 0.001), last_frame_time)
    else:
        max_ts = max(0.0, duration - 0.001)
    ts = clamp(float(timestamp), 0.0, max_ts)
    cap.set(cv2.CAP_PROP_POS_MSEC, ts * 1000.0)
    ok, frame = cap.read()
    if not ok or frame is None:
        # POS_MSEC can seek one frame beyond the last decodable keyframe. Retry by frame index.
        if fps > 0 and frame_count > 0:
            frame_idx = min(frame_count - 1, max(0, int(round(ts * fps))))
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_idx))
            ok, frame = cap.read()
            ts = frame_idx / fps
    if not ok or frame is None:
        return False, None, ts
    return True, frame, ts


def sample_times_for_window(start: float, end: float, mid: float, samples: int, sample_window_sec: float, duration: float) -> List[float]:
    samples = max(1, min(9, int(samples)))
    start = safe_float(start, mid)
    end = safe_float(end, mid)
    mid = safe_float(mid, (start + end) / 2.0)

    if samples <= 1:
        values = [mid]
    else:
        # Prefer adjacent-frame-ish samples around the cue center, but keep them inside the cue.
        local_start = max(start, mid - sample_window_sec)
        local_end = min(end, mid + sample_window_sec)
        if local_end <= local_start:
            local_start = max(0.0, mid - sample_window_sec)
            local_end = min(duration, mid + sample_window_sec)
        if local_end <= local_start:
            values = [mid]
        else:
            values = np.linspace(local_start, local_end, samples).tolist()

    out: List[float] = []
    for value in values:
        ts = round(clamp(float(value), 0.0, max(0.0, duration - 0.001)), 4)
        if ts not in out:
            out.append(ts)
    return out


# -----------------------------------------------------------------------------
# Caption event / transcript extraction
# -----------------------------------------------------------------------------


def find_first_list(data: Any, keys: Iterable[str]) -> Optional[List[Any]]:
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
        for value in data.values():
            found = find_first_list(value, keys)
            if found is not None:
                return found
    elif isinstance(data, list):
        for value in data:
            found = find_first_list(value, keys)
            if found is not None:
                return found
    return None


def get_nested(data: Dict[str, Any], path: Sequence[str], default: Any = None) -> Any:
    cur: Any = data
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def cue_from_obj(obj: Dict[str, Any], source: str, idx: int) -> Optional[Dict[str, Any]]:
    if not isinstance(obj, dict):
        return None
    text = clean_text(obj.get("text") or obj.get("word") or obj.get("caption") or obj.get("content") or "")
    start = obj.get("start")
    end = obj.get("end")
    if start is None:
        start = obj.get("timeline_start") or obj.get("start_seconds") or obj.get("timeline_start_seconds")
    if end is None:
        end = obj.get("timeline_end") or obj.get("end_seconds") or obj.get("timeline_end_seconds")
    if not text or start is None:
        return None
    start_f = safe_float(start, 0.0)
    end_f = safe_float(end, start_f + 0.25)
    if end_f <= start_f:
        end_f = start_f + 0.18
    return {
        "id": str(obj.get("id") or obj.get("subtitle_id") or obj.get("cue_id") or f"{source}_{idx:04d}"),
        "source": source,
        "text": text,
        "start": round(start_f, 4),
        "end": round(end_f, 4),
        "mid": round((start_f + end_f) / 2.0, 4),
        "duration": round(end_f - start_f, 4),
        "raw": obj,
    }


def extract_transcript_cues(transcript: Dict[str, Any]) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    for key, source in (("subtitle_candidates", "subtitle_candidates"), ("subtitle_clips", "subtitle_clips"), ("captions", "captions"), ("subtitle_cues", "subtitle_cues")):
        items = transcript.get(key)
        if isinstance(items, list):
            for i, obj in enumerate(items):
                cue = cue_from_obj(obj, source, i) if isinstance(obj, dict) else None
                if cue:
                    cues.append(cue)

    segments = transcript.get("segments")
    if isinstance(segments, list):
        for i, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            cue = cue_from_obj(seg, "segments", i)
            if cue:
                cues.append(cue)
            words = seg.get("words")
            if isinstance(words, list):
                for j, word_obj in enumerate(words):
                    cue = cue_from_obj(word_obj, "words", len(cues) + j) if isinstance(word_obj, dict) else None
                    if cue:
                        cues.append(cue)

    words = transcript.get("words")
    if isinstance(words, list):
        for i, word_obj in enumerate(words):
            cue = cue_from_obj(word_obj, "words", i) if isinstance(word_obj, dict) else None
            if cue:
                cues.append(cue)

    seen = set()
    final: List[Dict[str, Any]] = []
    for cue in sorted(cues, key=lambda x: (x["start"], x["end"], normalize_match_text(x["text"]))):
        key = (round(cue["start"], 2), round(cue["end"], 2), normalize_match_text(cue["text"]))
        if key in seen:
            continue
        seen.add(key)
        final.append(cue)
    return final



ABSOLUTE_BBOX_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("bbox",),
    ("box",),
    ("absolute_bbox",),
    ("absolute_box",),
    ("visual", "bbox"),
    ("visual", "box"),
    ("visual", "absolute_bbox"),
    ("placement", "bbox"),
    ("placement", "box"),
    ("placement", "absolute_bbox"),
    ("layout", "bbox"),
    ("layout", "box"),
    ("position", "bbox"),
    ("position", "box"),
    ("detection", "bbox"),
    ("detection", "box"),
    ("ocr", "bbox"),
    ("ocr", "box"),
)

NORMALIZED_BBOX_PATHS: Tuple[Tuple[str, ...], ...] = (
    ("normalized_bbox",),
    ("bbox_norm",),
    ("normalized_box",),
    ("norm_bbox",),
    ("box_norm",),
    ("visual", "normalized_bbox"),
    ("visual", "bbox_norm"),
    ("visual", "normalized_box"),
    ("placement", "normalized_bbox"),
    ("placement", "bbox_norm"),
    ("placement", "normalized_box"),
    ("layout", "normalized_bbox"),
    ("layout", "bbox_norm"),
    ("position", "normalized_bbox"),
    ("position", "bbox_norm"),
    ("detection", "normalized_bbox"),
    ("detection", "bbox_norm"),
    ("ocr", "normalized_bbox"),
    ("ocr", "bbox_norm"),
)


def path_to_string(path: Sequence[str]) -> str:
    return ".".join(str(p) for p in path)


def get_by_path(data: Any, path: Sequence[str], default: Any = None) -> Any:
    cur: Any = data
    for key in path:
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return default
    return cur


def first_path_value(data: Dict[str, Any], paths: Sequence[Sequence[str]]) -> Tuple[Any, Optional[str]]:
    for path in paths:
        value = get_by_path(data, path, None)
        if value is not None:
            return value, path_to_string(path)
    return None, None


def first_observation_bbox_value(event: Dict[str, Any], normalized: bool = False) -> Tuple[Any, Optional[str]]:
    observations = event.get("observations")
    if not isinstance(observations, list):
        return None, None
    keys = ["normalized_bbox", "bbox_norm", "normalized_box", "norm_bbox", "box_norm"] if normalized else ["bbox", "box", "absolute_bbox", "absolute_box"]
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        for key in keys:
            if obs.get(key) is not None:
                return obs.get(key), f"observations[].{key}"
    return None, None


def get_event_bbox(event: Dict[str, Any]) -> Tuple[Any, Any]:
    """Return raw absolute and normalized bbox candidates from all supported event schemas.

    This intentionally returns raw values. Pixel/normalized coercion happens in
    normalize_bbox_from_event_detailed(), where frame dimensions are available.
    """
    if not isinstance(event, dict):
        return None, None

    bbox, _bbox_path = first_path_value(event, ABSOLUTE_BBOX_PATHS)
    if bbox is None:
        bbox, _bbox_path = first_observation_bbox_value(event, normalized=False)

    normalized_bbox, _norm_path = first_path_value(event, NORMALIZED_BBOX_PATHS)
    if normalized_bbox is None:
        normalized_bbox, _norm_path = first_observation_bbox_value(event, normalized=True)

    return bbox, normalized_bbox


def flatten_bbox_candidate(value: Any) -> Optional[List[float]]:
    """Convert list/dict/polygon bbox formats into [x1, y1, x2, y2] floats.

    Accepted formats:
    - [x1, y1, x2, y2]
    - [[x, y], [x, y], [x, y], [x, y]] OCR quadrilateral
    - {x1, y1, x2, y2}
    - {left, top, right, bottom}
    - {x, y, width, height} / {x, y, w, h}
    """
    if value is None:
        return None

    if isinstance(value, dict):
        lower = {str(k).lower(): v for k, v in value.items()}
        if all(k in lower for k in ("x1", "y1", "x2", "y2")):
            return [safe_float(lower["x1"]), safe_float(lower["y1"]), safe_float(lower["x2"]), safe_float(lower["y2"])]
        if all(k in lower for k in ("left", "top", "right", "bottom")):
            return [safe_float(lower["left"]), safe_float(lower["top"]), safe_float(lower["right"]), safe_float(lower["bottom"])]
        width_key = "width" if "width" in lower else "w" if "w" in lower else None
        height_key = "height" if "height" in lower else "h" if "h" in lower else None
        if "x" in lower and "y" in lower and width_key and height_key:
            x = safe_float(lower["x"])
            y = safe_float(lower["y"])
            w = safe_float(lower[width_key])
            h = safe_float(lower[height_key])
            return [x, y, x + w, y + h]
        return None

    if isinstance(value, (list, tuple)):
        if len(value) == 4 and all(isinstance(p, (list, tuple)) and len(p) >= 2 for p in value):
            xs = [safe_float(p[0]) for p in value]
            ys = [safe_float(p[1]) for p in value]
            return [min(xs), min(ys), max(xs), max(ys)]
        if len(value) == 4:
            return [safe_float(v) for v in value]

    return None


def coerce_bbox_to_absolute(value: Any, frame_w: int, frame_h: int, assumed_normalized: Optional[bool] = None) -> Optional[List[int]]:
    flat = flatten_bbox_candidate(value)
    if not flat or len(flat) != 4:
        return None

    x1f, y1f, x2f, y2f = [safe_float(v, 0.0) for v in flat]

    # Defensive support for [x, y, width, height] values that accidentally arrive
    # as a list. Normal xyxy boxes remain unchanged.
    if x2f <= x1f and x2f > 0:
        x2f = x1f + x2f
    if y2f <= y1f and y2f > 0:
        y2f = y1f + y2f

    max_abs = max(abs(x1f), abs(y1f), abs(x2f), abs(y2f))
    is_normalized = bool(assumed_normalized) if assumed_normalized is not None else max_abs <= 1.5

    if is_normalized:
        x1 = int(round(x1f * frame_w))
        y1 = int(round(y1f * frame_h))
        x2 = int(round(x2f * frame_w))
        y2 = int(round(y2f * frame_h))
    else:
        x1, y1, x2, y2 = [int(round(v)) for v in (x1f, y1f, x2f, y2f)]

    x1 = max(0, min(max(0, frame_w - 1), x1))
    x2 = max(0, min(max(0, frame_w), x2))
    y1 = max(0, min(max(0, frame_h - 1), y1))
    y2 = max(0, min(max(0, frame_h), y2))

    if x2 > x1 and y2 > y1:
        return [x1, y1, x2, y2]
    return None



def bbox_geometry_metrics(bbox: Optional[List[int]], frame_w: int, frame_h: int) -> Dict[str, Any]:
    """Measure bbox geometry after mapping into the current analysis frame."""
    if not bbox or len(bbox) != 4:
        return {
            "valid": False,
            "reason": "missing_or_malformed",
            "width": 0,
            "height": 0,
            "area": 0,
            "area_ratio": 0.0,
        }

    x1, y1, x2, y2 = [safe_int(v, 0) for v in bbox]
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    area = width * height
    frame_area = max(1, int(frame_w) * int(frame_h))
    area_ratio = float(area) / frame_area

    # One-word captions on the 304x540 proxy are commonly 20-120 px wide and
    # 10-45 px high. Reject only geometry that is clearly a clamp artifact.
    min_width = max(2, int(round(frame_w * 0.006)))
    min_height = max(2, int(round(frame_h * 0.004)))
    min_area = max(8, int(round(frame_area * 0.00008)))
    max_area_ratio = 0.80

    valid = (
        width >= min_width
        and height >= min_height
        and area >= min_area
        and area_ratio <= max_area_ratio
        and 0 <= x1 < x2 <= frame_w
        and 0 <= y1 < y2 <= frame_h
    )

    reason = "ok"
    if width < min_width:
        reason = "width_too_small"
    elif height < min_height:
        reason = "height_too_small"
    elif area < min_area:
        reason = "area_too_small"
    elif area_ratio > max_area_ratio:
        reason = "area_too_large"
    elif not (0 <= x1 < x2 <= frame_w and 0 <= y1 < y2 <= frame_h):
        reason = "out_of_bounds"

    return {
        "valid": bool(valid),
        "reason": reason,
        "width": int(width),
        "height": int(height),
        "area": int(area),
        "area_ratio": round(float(area_ratio), 6),
        "min_width": int(min_width),
        "min_height": int(min_height),
        "min_area": int(min_area),
    }


def normalized_candidate_to_absolute(value: Any, frame_w: int, frame_h: int) -> Optional[List[int]]:
    """Map a normalized [x1,y1,x2,y2] candidate into the target video frame."""
    flat = flatten_bbox_candidate(value)
    if not flat:
        return None
    vals = [safe_float(v, 0.0) for v in flat]
    # A normalized candidate must stay close to [0, 1]. Small OCR rounding
    # excursions are tolerated, but pixel coordinates are never treated as normalized.
    if max(abs(v) for v in vals) > 1.5:
        return None
    return coerce_bbox_to_absolute(vals, frame_w, frame_h, assumed_normalized=True)


def absolute_candidate_to_target(
    value: Any,
    frame_w: int,
    frame_h: int,
    source_frame_w: Optional[int] = None,
    source_frame_h: Optional[int] = None,
) -> Tuple[Optional[List[int]], str]:
    """Map absolute style-detector pixels into the current occlusion video.

    Caption style is often analyzed on the 1080x1920 source while occlusion is
    intentionally run on a 304x540 proxy. Direct clamping turns valid source boxes
    into 1x1 pixels at the proxy edge. When source dimensions are known, scale first.
    """
    flat = flatten_bbox_candidate(value)
    if not flat:
        return None, "malformed"

    x1f, y1f, x2f, y2f = [safe_float(v, 0.0) for v in flat]
    if x2f <= x1f or y2f <= y1f:
        return None, "invalid_xyxy"

    src_w = safe_int(source_frame_w, 0)
    src_h = safe_int(source_frame_h, 0)

    if src_w > 0 and src_h > 0:
        sx = float(frame_w) / float(src_w)
        sy = float(frame_h) / float(src_h)
        mapped = [
            int(round(x1f * sx)),
            int(round(y1f * sy)),
            int(round(x2f * sx)),
            int(round(y2f * sy)),
        ]
        mapped = [
            max(0, min(frame_w - 1, mapped[0])),
            max(0, min(frame_h - 1, mapped[1])),
            max(0, min(frame_w, mapped[2])),
            max(0, min(frame_h, mapped[3])),
        ]
        return mapped if mapped[2] > mapped[0] and mapped[3] > mapped[1] else None, "scaled_from_style_video"

    # Without source dimensions, accept direct target-space pixels only when the
    # candidate already fits the current frame. Do not clamp oversized coordinates.
    if 0 <= x1f < x2f <= frame_w and 0 <= y1f < y2f <= frame_h:
        return [int(round(x1f)), int(round(y1f)), int(round(x2f)), int(round(y2f))], "direct_target_pixels"

    return None, "source_dimensions_required"


def median_observation_bbox(event: Dict[str, Any], normalized: bool) -> Tuple[Any, Optional[str]]:
    """Aggregate repeated OCR observations with a coordinate-wise median."""
    observations = event.get("observations")
    if not isinstance(observations, list):
        return None, None

    keys = (
        ["normalized_bbox", "bbox_norm", "normalized_box", "norm_bbox", "box_norm"]
        if normalized
        else ["bbox", "box", "absolute_bbox", "absolute_box"]
    )
    candidates: List[List[float]] = []
    used_key: Optional[str] = None
    for obs in observations:
        if not isinstance(obs, dict):
            continue
        for key in keys:
            flat = flatten_bbox_candidate(obs.get(key))
            if flat:
                candidates.append([safe_float(v, 0.0) for v in flat])
                used_key = key
                break

    if not candidates:
        return None, None

    arr = np.asarray(candidates, dtype=np.float32)
    med = np.median(arr, axis=0).tolist()
    return med, f"observations[].{used_key}.median"


def scan_bbox_schema_paths(
    event: Dict[str, Any],
    frame_w: int,
    frame_h: int,
    source_frame_w: Optional[int] = None,
    source_frame_h: Optional[int] = None,
) -> Dict[str, int]:
    """Return bbox-like paths that produce non-degenerate target-frame geometry."""
    seen: Dict[str, int] = {}
    if not isinstance(event, dict):
        return seen

    for path in NORMALIZED_BBOX_PATHS:
        bbox = normalized_candidate_to_absolute(get_by_path(event, path, None), frame_w, frame_h)
        if bbox_geometry_metrics(bbox, frame_w, frame_h).get("valid"):
            p = path_to_string(path)
            seen[p] = seen.get(p, 0) + 1

    for path in ABSOLUTE_BBOX_PATHS:
        bbox, _mode = absolute_candidate_to_target(
            get_by_path(event, path, None),
            frame_w,
            frame_h,
            source_frame_w,
            source_frame_h,
        )
        if bbox_geometry_metrics(bbox, frame_w, frame_h).get("valid"):
            p = path_to_string(path)
            seen[p] = seen.get(p, 0) + 1

    observations = event.get("observations")
    if isinstance(observations, list):
        for obs in observations:
            if not isinstance(obs, dict):
                continue
            for key in ("normalized_bbox", "bbox_norm", "normalized_box", "norm_bbox", "box_norm"):
                bbox = normalized_candidate_to_absolute(obs.get(key), frame_w, frame_h)
                if bbox_geometry_metrics(bbox, frame_w, frame_h).get("valid"):
                    p = f"observations[].{key}"
                    seen[p] = seen.get(p, 0) + 1
            for key in ("bbox", "box", "absolute_bbox", "absolute_box"):
                bbox, _mode = absolute_candidate_to_target(
                    obs.get(key),
                    frame_w,
                    frame_h,
                    source_frame_w,
                    source_frame_h,
                )
                if bbox_geometry_metrics(bbox, frame_w, frame_h).get("valid"):
                    p = f"observations[].{key}"
                    seen[p] = seen.get(p, 0) + 1
    return seen


def normalize_bbox_from_event_detailed(
    event: Dict[str, Any],
    frame_w: int,
    frame_h: int,
    source_frame_w: Optional[int] = None,
    source_frame_h: Optional[int] = None,
) -> Tuple[Optional[List[int]], Dict[str, Any]]:
    """Select the best caption box and reconcile source/proxy coordinate spaces.

    Priority:
      1. placement/top-level normalized bbox
      2. median normalized observation bbox
      3. absolute bbox scaled from caption-style source dimensions
      4. median absolute observation bbox scaled from source dimensions

    A candidate is accepted only when it remains non-degenerate in the target frame.
    """
    info: Dict[str, Any] = {
        "bbox_schema_path": None,
        "normalized_bbox_schema_path": None,
        "used_normalized_input": False,
        "coordinate_space": None,
        "source_frame_size": {
            "width": safe_int(source_frame_w, 0) or None,
            "height": safe_int(source_frame_h, 0) or None,
        },
        "target_frame_size": {"width": int(frame_w), "height": int(frame_h)},
        "schema_paths_seen": scan_bbox_schema_paths(
            event,
            frame_w,
            frame_h,
            source_frame_w,
            source_frame_h,
        ),
        "candidates": [],
        "rejected_candidates": [],
    }

    candidates: List[Dict[str, Any]] = []

    # Prefer explicit normalized geometry because it is resolution-independent.
    for rank, path in enumerate(NORMALIZED_BBOX_PATHS):
        value = get_by_path(event, path, None)
        if value is None:
            continue
        bbox = normalized_candidate_to_absolute(value, frame_w, frame_h)
        metrics = bbox_geometry_metrics(bbox, frame_w, frame_h)
        candidates.append({
            "path": path_to_string(path),
            "bbox": bbox,
            "metrics": metrics,
            "normalized": True,
            "coordinate_space": "normalized_frame",
            "mapping_mode": "normalized_to_target",
            "priority": 1000 - rank,
        })

    obs_norm, obs_norm_path = median_observation_bbox(event, normalized=True)
    if obs_norm is not None:
        bbox = normalized_candidate_to_absolute(obs_norm, frame_w, frame_h)
        candidates.append({
            "path": obs_norm_path,
            "bbox": bbox,
            "metrics": bbox_geometry_metrics(bbox, frame_w, frame_h),
            "normalized": True,
            "coordinate_space": "normalized_frame",
            "mapping_mode": "normalized_observation_median_to_target",
            "priority": 900,
        })

    for rank, path in enumerate(ABSOLUTE_BBOX_PATHS):
        value = get_by_path(event, path, None)
        if value is None:
            continue
        bbox, mapping_mode = absolute_candidate_to_target(
            value,
            frame_w,
            frame_h,
            source_frame_w,
            source_frame_h,
        )
        candidates.append({
            "path": path_to_string(path),
            "bbox": bbox,
            "metrics": bbox_geometry_metrics(bbox, frame_w, frame_h),
            "normalized": False,
            "coordinate_space": "source_absolute_pixels" if mapping_mode == "scaled_from_style_video" else "absolute_pixels",
            "mapping_mode": mapping_mode,
            "priority": 700 - rank,
        })

    obs_abs, obs_abs_path = median_observation_bbox(event, normalized=False)
    if obs_abs is not None:
        bbox, mapping_mode = absolute_candidate_to_target(
            obs_abs,
            frame_w,
            frame_h,
            source_frame_w,
            source_frame_h,
        )
        candidates.append({
            "path": obs_abs_path,
            "bbox": bbox,
            "metrics": bbox_geometry_metrics(bbox, frame_w, frame_h),
            "normalized": False,
            "coordinate_space": "source_absolute_pixels" if mapping_mode == "scaled_from_style_video" else "absolute_pixels",
            "mapping_mode": f"{mapping_mode}_observation_median",
            "priority": 600,
        })

    valid_candidates = [c for c in candidates if c.get("metrics", {}).get("valid")]
    invalid_candidates = [c for c in candidates if not c.get("metrics", {}).get("valid")]

    # Higher priority wins. Geometry area only breaks ties between equivalent paths.
    valid_candidates.sort(
        key=lambda c: (
            safe_int(c.get("priority"), 0),
            safe_int(get_nested(c, ["metrics", "area"], 0), 0),
        ),
        reverse=True,
    )

    info["candidates"] = [
        {
            "path": c.get("path"),
            "bbox": c.get("bbox"),
            "mapping_mode": c.get("mapping_mode"),
            "metrics": c.get("metrics"),
            "priority": c.get("priority"),
        }
        for c in valid_candidates[:8]
    ]
    info["rejected_candidates"] = [
        {
            "path": c.get("path"),
            "bbox": c.get("bbox"),
            "mapping_mode": c.get("mapping_mode"),
            "metrics": c.get("metrics"),
        }
        for c in invalid_candidates[:8]
    ]

    if not valid_candidates:
        return None, info

    selected = valid_candidates[0]
    info["bbox_schema_path"] = selected.get("path")
    info["normalized_bbox_schema_path"] = selected.get("path") if selected.get("normalized") else None
    info["used_normalized_input"] = bool(selected.get("normalized"))
    info["coordinate_space"] = selected.get("coordinate_space")
    info["mapping_mode"] = selected.get("mapping_mode")
    info["selected_metrics"] = selected.get("metrics")
    return selected.get("bbox"), info


def normalize_bbox_from_event(
    event: Dict[str, Any],
    frame_w: int,
    frame_h: int,
    source_frame_w: Optional[int] = None,
    source_frame_h: Optional[int] = None,
) -> Optional[List[int]]:
    bbox, _info = normalize_bbox_from_event_detailed(
        event,
        frame_w,
        frame_h,
        source_frame_w,
        source_frame_h,
    )
    return bbox

def summarize_style_event_keys(raw_events: Any, limit: int = 3) -> List[Dict[str, Any]]:
    """Small diagnostic payload for schema failures; avoids dumping full events."""
    out: List[Dict[str, Any]] = []
    if not isinstance(raw_events, list):
        return out
    for idx, event in enumerate(raw_events[: max(1, int(limit))], start=1):
        if not isinstance(event, dict):
            out.append({"sample_index": idx, "type": type(event).__name__})
            continue
        nested: Dict[str, List[str]] = {}
        for key, value in event.items():
            if isinstance(value, dict):
                nested[str(key)] = sorted(str(k) for k in value.keys())
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                nested[f"{key}[]"] = sorted(str(k) for k in value[0].keys())
        out.append({
            "sample_index": idx,
            "event_id": event.get("event_id") or event.get("id"),
            "top_level_keys": sorted(str(k) for k in event.keys()),
            "nested_keys": nested,
        })
    return out

def bbox_to_normalized(bbox: List[int], frame_w: int, frame_h: int) -> List[float]:
    x1, y1, x2, y2 = bbox
    return [round(x1 / max(1, frame_w), 4), round(y1 / max(1, frame_h), 4), round(x2 / max(1, frame_w), 4), round(y2 / max(1, frame_h), 4)]


def bbox_center_norm(bbox: List[int], frame_w: int, frame_h: int) -> Dict[str, float]:
    x1, y1, x2, y2 = bbox
    return {"x": round(((x1 + x2) / 2.0) / max(1, frame_w), 4), "y": round(((y1 + y2) / 2.0) / max(1, frame_h), 4)}


def expand_bbox(bbox: List[int], frame_w: int, frame_h: int, pad_ratio: float = 0.15, min_pad: int = 8) -> List[int]:
    x1, y1, x2, y2 = bbox
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    px = max(min_pad, int(round(bw * pad_ratio)))
    py = max(min_pad, int(round(bh * pad_ratio)))
    return [max(0, x1 - px), max(0, y1 - py), min(frame_w, x2 + px), min(frame_h, y2 + py)]


def estimate_bbox_from_cue(cue: Dict[str, Any], style_data: Dict[str, Any], frame_w: int, frame_h: int) -> List[int]:
    resolved = style_data.get("caption_style_resolved") or style_data.get("resolved") or {}
    profile = None
    primary_id = resolved.get("primary_style_id") if isinstance(resolved, dict) else None
    for p in (style_data.get("caption_style_profiles") or style_data.get("style_profiles") or []):
        if isinstance(p, dict) and (p.get("style_id") == primary_id or profile is None):
            profile = p
            if p.get("style_id") == primary_id:
                break

    placement = (profile or {}).get("placement") or resolved.get("placement") or {}
    anchor = placement.get("anchor") or {"x": 0.5, "y": 0.55}
    ax = clamp(safe_float(anchor.get("x"), 0.5), 0.05, 0.95)
    ay = clamp(safe_float(anchor.get("y"), 0.55), 0.08, 0.92)

    typography = (profile or {}).get("typography") or resolved.get("typography") or {}
    font_px = safe_int(typography.get("font_height_px"), 0)
    if font_px <= 0:
        ratio = safe_float(typography.get("font_height_ratio"), 0.038)
        font_px = max(28, int(round(ratio * frame_h)))

    text = clean_text(cue.get("text"))
    chars = max(2, len(text))
    # Approximate one-word/short phrase caption box. Clamp to reel-safe width.
    width_px = int(round(min(frame_w * 0.78, max(font_px * 1.4, chars * font_px * 0.52))))
    height_px = int(round(font_px * (1.25 if " " not in text else 1.55)))
    cx = int(round(ax * frame_w))
    cy = int(round(ay * frame_h))
    x1 = max(0, cx - width_px // 2)
    x2 = min(frame_w, cx + width_px // 2)
    y1 = max(0, cy - height_px // 2)
    y2 = min(frame_h, cy + height_px // 2)
    return [x1, y1, x2, y2]


def normalize_caption_events(
    style_data: Dict[str, Any],
    transcript_cues: List[Dict[str, Any]],
    frame_w: int,
    frame_h: int,
    include_inferred: bool,
    max_inferred_events: int = 40,
    include_word_inferred_cues: bool = False,
    inferred_min_duration_sec: float = 0.12,
    inferred_min_text_chars: int = 2,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Normalize caption_style_events into occlusion events.

    v1.6 bbox-reconciliation changes:
    - Reconciles caption-style source pixels with a lower-resolution proxy video.
    - Prefers resolution-independent normalized geometry.
    - Rejects edge-clamped/degenerate 1x1 boxes.
    - Uses scaled source-pixel boxes and observation medians as fallbacks.
    - Emits explicit candidate-selection diagnostics.
    """
    raw_events = style_data.get("caption_style_events") or style_data.get("style_events") or []
    raw_events_list = raw_events if isinstance(raw_events, list) else []

    events: List[Dict[str, Any]] = []
    skipped_style_events_missing_bbox = 0
    style_events_with_bbox_count = 0
    normalized_from_style_event_count = 0
    bbox_schema_paths_seen: Dict[str, int] = {}
    bbox_schema_paths_used: Dict[str, int] = {}
    warnings: List[str] = []

    style_video_info = style_data.get("video_info") if isinstance(style_data.get("video_info"), dict) else {}
    source_frame_w = safe_int(style_video_info.get("width"), 0)
    source_frame_h = safe_int(style_video_info.get("height"), 0)
    if source_frame_w <= 0 or source_frame_h <= 0:
        # Some compact style contracts keep video dimensions under source/video.
        source_frame_w = safe_int(get_nested(style_data, ["source", "width"], 0), 0)
        source_frame_h = safe_int(get_nested(style_data, ["source", "height"], 0), 0)

    for i, event in enumerate(raw_events_list, start=1):
        if not isinstance(event, dict):
            continue

        bbox, bbox_info = normalize_bbox_from_event_detailed(event, frame_w, frame_h, source_frame_w, source_frame_h)
        for path, count in (bbox_info.get("schema_paths_seen") or {}).items():
            bbox_schema_paths_seen[str(path)] = bbox_schema_paths_seen.get(str(path), 0) + int(count)

        if not bbox:
            skipped_style_events_missing_bbox += 1
            continue

        style_events_with_bbox_count += 1
        normalized_from_style_event_count += 1
        used_path = str(bbox_info.get("bbox_schema_path") or "unknown")
        bbox_schema_paths_used[used_path] = bbox_schema_paths_used.get(used_path, 0) + 1

        start = safe_float(event.get("start"), safe_float(event.get("time", event.get("timestamp", 0.0)), 0.0))
        end = safe_float(event.get("end"), start + safe_float(event.get("duration"), 0.25))
        if end <= start:
            end = start + 0.18
        mid = safe_float(event.get("mid"), (start + end) / 2.0)

        events.append({
            "id": str(event.get("id") or event.get("event_id") or f"caption_event_{i:04d}"),
            "source": "caption_style_event",
            "caption_event_id": str(event.get("id") or event.get("event_id") or f"caption_event_{i:04d}"),
            "cue_id": str(event.get("cue_id") or event.get("matched_cue_id") or ""),
            "text": clean_text(event.get("text") or event.get("cue_text") or event.get("observed_text") or ""),
            "observed_text": clean_text(event.get("observed_text") or event.get("text") or ""),
            "start": round(start, 4),
            "end": round(end, 4),
            "mid": round(mid, 4),
            "duration": round(end - start, 4),
            "bbox": bbox,
            "normalized_bbox": bbox_to_normalized(bbox, frame_w, frame_h),
            "bbox_normalization": {
                "source": "caption_style_event",
                "bbox_schema_path": bbox_info.get("bbox_schema_path"),
                "normalized_bbox_schema_path": bbox_info.get("normalized_bbox_schema_path"),
                "used_normalized_input": bool(bbox_info.get("used_normalized_input")),
                "coordinate_space": bbox_info.get("coordinate_space"),
                "mapping_mode": bbox_info.get("mapping_mode"),
                "source_frame_size": bbox_info.get("source_frame_size"),
                "target_frame_size": bbox_info.get("target_frame_size"),
                "selected_metrics": bbox_info.get("selected_metrics"),
                "candidate_count": len(bbox_info.get("candidates") or []),
                "rejected_candidate_count": len(bbox_info.get("rejected_candidates") or []),
                "output_timebase": "seconds",
                "output_coordinate_space": "absolute_pixels_and_normalized_frame",
                "note": "Normalized boxes are preferred; source absolute pixels are scaled to the occlusion video before use.",
            },
            "style_profile_id": event.get("style_profile_id"),
            # Kept for backward compatibility with earlier occlusion reports.
            # Downstream compilers should consume bbox/normalized_bbox above, not
            # raw observation frame_index values inside this style payload.
            "style": event,
        })

    if raw_events_list and style_events_with_bbox_count == 0:
        sample_keys = summarize_style_event_keys(raw_events_list, limit=3)
        warnings.append(
            "caption_style_events exist, but zero usable bbox fields were found. "
            f"Sample event keys: {json.dumps(sample_keys, ensure_ascii=False)}"
        )

    inferred_count = 0
    normalized_from_inferred_transcript_count = 0
    inferred_candidates_seen = 0
    inferred_candidates_skipped_words = 0
    inferred_candidates_skipped_matched = 0
    inferred_candidates_skipped_too_short = 0
    inferred_candidates_skipped_cap = 0
    inferred_candidates_skipped_style_bbox_available = 0

    # Important: transcript boxes are estimates. Once real visual style-event
    # bboxes exist, do not mix in inferred cue boxes because they would pollute
    # foreground matte decisions with approximate locations.
    allow_inferred = bool(include_inferred and transcript_cues and style_events_with_bbox_count == 0)
    if include_inferred and transcript_cues and style_events_with_bbox_count > 0:
        inferred_candidates_skipped_style_bbox_available = len(transcript_cues)

    if allow_inferred:
        eligible_cues = list(transcript_cues)
        if not include_word_inferred_cues:
            eligible_cues = [c for c in eligible_cues if c.get("source") != "words"]
            inferred_candidates_skipped_words = len([c for c in transcript_cues if c.get("source") == "words"])

        # Prefer stronger subtitle/segment cues before words.
        source_rank = {
            "subtitle_candidates": 0,
            "subtitle_clips": 1,
            "captions": 2,
            "subtitle_cues": 3,
            "segments": 4,
            "words": 9,
        }
        eligible_cues = sorted(
            eligible_cues,
            key=lambda c: (
                source_rank.get(str(c.get("source")), 8),
                safe_float(c.get("start"), 0.0),
                safe_float(c.get("end"), 0.0),
            ),
        )

        for cue in eligible_cues:
            cue_mid = safe_float(cue.get("mid"), (safe_float(cue.get("start"), 0.0) + safe_float(cue.get("end"), 0.0)) / 2.0)
            cue_text = clean_text(cue.get("text"))
            cue_duration = safe_float(cue.get("duration"), safe_float(cue.get("end"), cue_mid) - safe_float(cue.get("start"), cue_mid))
            inferred_candidates_seen += 1

            if len(cue_text) < max(1, int(inferred_min_text_chars)) or cue_duration < max(0.0, float(inferred_min_duration_sec)):
                inferred_candidates_skipped_too_short += 1
                continue

            matched = False
            for ev in events:
                dt = abs(cue_mid - safe_float(ev.get("mid"), 0.0))
                sim = fuzzy_similarity(cue_text, ev.get("text") or ev.get("observed_text"))
                if dt <= 0.45 and (sim >= 0.42 or str(cue.get("id")) == str(ev.get("cue_id"))):
                    matched = True
                    break
            if matched:
                inferred_candidates_skipped_matched += 1
                continue

            if max_inferred_events > 0 and inferred_count >= int(max_inferred_events):
                inferred_candidates_skipped_cap += 1
                continue

            bbox = estimate_bbox_from_cue(cue, style_data, frame_w, frame_h)
            inferred_count += 1
            normalized_from_inferred_transcript_count += 1
            events.append({
                "id": f"inferred_caption_window_{inferred_count:04d}",
                "source": "inferred_transcript_cue",
                "caption_event_id": None,
                "cue_id": str(cue.get("id") or f"cue_{inferred_count:04d}"),
                "text": cue_text,
                "observed_text": "",
                "start": round(safe_float(cue.get("start"), cue_mid), 4),
                "end": round(safe_float(cue.get("end"), cue_mid + 0.2), 4),
                "mid": round(cue_mid, 4),
                "duration": round(max(0.001, safe_float(cue.get("end"), cue_mid + 0.2) - safe_float(cue.get("start"), cue_mid)), 4),
                "bbox": bbox,
                "normalized_bbox": bbox_to_normalized(bbox, frame_w, frame_h),
                "bbox_normalization": {
                    "source": "inferred_transcript_cue",
                    "bbox_schema_path": "estimated_from_transcript_cue",
                    "normalized_bbox_schema_path": None,
                    "used_normalized_input": False,
                    "coordinate_space": "estimated_absolute_pixels",
                    "output_timebase": "seconds",
                    "output_coordinate_space": "absolute_pixels_and_normalized_frame",
                },
                "style_profile_id": get_nested(style_data, ["caption_style_resolved", "primary_style_id"], None),
                "style": {"inferred": True, "source_cue": cue},
            })

    events = sorted(events, key=lambda e: (safe_float(e.get("start"), 0.0), safe_float(e.get("end"), 0.0), str(e.get("id"))))
    cue_reconciliation = reconcile_caption_event_identities(events, transcript_cues=transcript_cues)
    return events, {
        "raw_style_event_count": len(raw_events_list),
        "style_events_with_bbox_count": style_events_with_bbox_count,
        "style_events_missing_bbox_count": skipped_style_events_missing_bbox,
        "normalized_from_style_event_count": normalized_from_style_event_count,
        "normalized_from_inferred_transcript_count": normalized_from_inferred_transcript_count,
        "normalized_event_count": len(events),
        "inferred_transcript_event_count": inferred_count,
        "inferred_candidates_seen": inferred_candidates_seen,
        "inferred_candidates_skipped_words": inferred_candidates_skipped_words,
        "inferred_candidates_skipped_matched": inferred_candidates_skipped_matched,
        "inferred_candidates_skipped_too_short": inferred_candidates_skipped_too_short,
        "inferred_candidates_skipped_cap": inferred_candidates_skipped_cap,
        "inferred_candidates_skipped_style_bbox_available": inferred_candidates_skipped_style_bbox_available,
        "include_word_inferred_cues": bool(include_word_inferred_cues),
        "max_inferred_events": max_inferred_events,
        "bbox_schema_paths_seen": dict(sorted(bbox_schema_paths_seen.items())),
        "bbox_schema_paths_used": dict(sorted(bbox_schema_paths_used.items())),
        "caption_style_source_frame_size": {
            "width": source_frame_w or None,
            "height": source_frame_h or None,
        },
        "occlusion_target_frame_size": {
            "width": frame_w,
            "height": frame_h,
        },
        "coordinate_reconciliation_applied": bool(
            source_frame_w > 0
            and source_frame_h > 0
            and (source_frame_w != frame_w or source_frame_h != frame_h)
        ),
        "sample_style_event_keys_seen": summarize_style_event_keys(raw_events_list, limit=3),
        "cue_reconciliation": cue_reconciliation,
        "warnings": warnings,
    }


STABLE_SUB_CUE_RE = re.compile(r"^sub_\d+$", re.IGNORECASE)


def is_stable_sub_cue_id(value: Any) -> bool:
    return bool(STABLE_SUB_CUE_RE.fullmatch(clean_text(value)))


def interval_overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(float(a_end), float(b_end)) - max(float(a_start), float(b_start)))


def uppercase_letter_ratio(text: Any) -> float:
    value = clean_text(text)
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if ch.isupper()) / len(letters)


def reconcile_caption_event_identities(events: List[Dict[str, Any]], transcript_cues: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Separate stable word cues from aggregate transcript windows and title graphics.

    The caption-style detector can emit:
    - stable word cues such as sub_0052;
    - long sentence-level events with numeric IDs such as "5" or "12";
    - repeated opening/closing title graphics with no transcript cue.

    Only stable word cues are valid targets for V3/V4 caption compositing. Aggregate
    windows and title graphics remain in the visual audit, but they are explicitly
    excluded from the caption-occlusion editor contract instead of being counted as
    unresolved subtitle failures.
    """
    stable_events = [event for event in events if is_stable_sub_cue_id(event.get("cue_id"))]
    stable_records: List[Dict[str, Any]] = list(stable_events)
    for cue in transcript_cues or []:
        if not is_stable_sub_cue_id(cue.get("id")):
            continue
        stable_records.append({
            "cue_id": clean_text(cue.get("id")),
            "text": clean_text(cue.get("text")),
            "observed_text": clean_text(cue.get("text")),
            "start": safe_float(cue.get("start"), 0.0),
            "end": safe_float(cue.get("end"), safe_float(cue.get("start"), 0.0) + 0.18),
            "mid": safe_float(cue.get("mid"), (safe_float(cue.get("start"), 0.0) + safe_float(cue.get("end"), 0.0)) / 2.0),
            "source": "transcript_stable_cue",
        })

    # De-duplicate stable records by cue ID, preferring the narrower word-level interval.
    stable_by_id: Dict[str, Dict[str, Any]] = {}
    for record in stable_records:
        cue_id = clean_text(record.get("cue_id"))
        if not cue_id:
            continue
        previous = stable_by_id.get(cue_id)
        if previous is None:
            stable_by_id[cue_id] = record
            continue
        prev_duration = max(0.001, safe_float(previous.get("end"), 0.0) - safe_float(previous.get("start"), 0.0))
        record_duration = max(0.001, safe_float(record.get("end"), 0.0) - safe_float(record.get("start"), 0.0))
        if record_duration < prev_duration:
            stable_by_id[cue_id] = record
    stable_records = list(stable_by_id.values())

    max_end = max((safe_float(event.get("end"), 0.0) for event in events), default=0.0)

    counts = {
        "stable_sub_cue_count": 0,
        "remapped_to_stable_sub_cue_count": 0,
        "aggregate_caption_window_count": 0,
        "non_caption_graphic_count": 0,
        "unresolved_count": 0,
    }

    for event in events:
        original_cue_id = clean_text(event.get("cue_id"))
        event["original_cue_id"] = original_cue_id or None

        if is_stable_sub_cue_id(original_cue_id):
            event["editor_event_type"] = "stable_caption_cue"
            event["exclude_from_caption_occlusion_editor"] = False
            event["related_cue_ids"] = [original_cue_id]
            event["cue_mapping"] = {
                "status": "stable",
                "stable_cue_id": original_cue_id,
                "related_cue_ids": [original_cue_id],
                "excluded_from_editor": False,
                "reason": "input_cue_id_is_stable_sub_xxxx",
            }
            counts["stable_sub_cue_count"] += 1
            continue

        start = safe_float(event.get("start"), 0.0)
        end = safe_float(event.get("end"), start)
        duration = max(0.001, end - start)
        event_mid = safe_float(event.get("mid"), (start + end) / 2.0)
        event_text = clean_text(event.get("text") or event.get("observed_text"))
        style_raw = event.get("style") if isinstance(event.get("style"), dict) else {}
        style_source = clean_text(style_raw.get("source"))
        match = style_raw.get("match") if isinstance(style_raw.get("match"), dict) else {}

        candidates: List[Dict[str, Any]] = []
        for stable in stable_records:
            s_start = safe_float(stable.get("start"), 0.0)
            s_end = safe_float(stable.get("end"), s_start)
            s_duration = max(0.001, s_end - s_start)
            overlap = interval_overlap_seconds(start, end, s_start, s_end)
            mid_dist = abs(event_mid - safe_float(stable.get("mid"), (s_start + s_end) / 2.0))
            if overlap <= 0.0 and mid_dist > 0.16:
                continue
            event_coverage = overlap / duration
            stable_coverage = overlap / s_duration
            similarity = fuzzy_similarity(event_text, stable.get("text") or stable.get("observed_text"))
            score = clamp(
                (0.42 * min(1.0, stable_coverage))
                + (0.28 * min(1.0, event_coverage))
                + (0.20 * similarity)
                + (0.10 * clamp(1.0 - (mid_dist / 0.35), 0.0, 1.0)),
                0.0,
                1.0,
            )
            if overlap > 0.0 or score >= 0.46:
                candidates.append({
                    "cue_id": clean_text(stable.get("cue_id")),
                    "text": clean_text(stable.get("text")),
                    "start": s_start,
                    "end": s_end,
                    "overlap_seconds": round(overlap, 4),
                    "event_coverage": round(event_coverage, 4),
                    "stable_coverage": round(stable_coverage, 4),
                    "text_similarity": round(similarity, 4),
                    "score": round(score, 4),
                })

        # Keep one record per stable cue and order by confidence/time.
        by_id: Dict[str, Dict[str, Any]] = {}
        for candidate in candidates:
            cue_id = candidate["cue_id"]
            if not cue_id:
                continue
            previous = by_id.get(cue_id)
            if previous is None or safe_float(candidate.get("score"), 0.0) > safe_float(previous.get("score"), 0.0):
                by_id[cue_id] = candidate
        candidates = sorted(
            by_id.values(),
            key=lambda candidate: (
                -safe_float(candidate.get("score"), 0.0),
                safe_float(candidate.get("start"), 0.0),
                candidate.get("cue_id") or "",
            ),
        )
        related = [
            candidate["cue_id"]
            for candidate in sorted(candidates, key=lambda candidate: safe_float(candidate.get("start"), 0.0))
            if safe_float(candidate.get("overlap_seconds"), 0.0) > 0.0
        ]

        # A single short visual event may be safely remapped to one stable word cue.
        best = candidates[0] if candidates else None
        single_remap = bool(
            best
            and len(related) <= 1
            and duration <= 0.60
            and safe_float(best.get("score"), 0.0) >= 0.72
            and (
                safe_float(best.get("text_similarity"), 0.0) >= 0.48
                or safe_float(best.get("stable_coverage"), 0.0) >= 0.88
            )
        )
        if single_remap:
            stable_id = clean_text(best.get("cue_id"))
            event["cue_id"] = stable_id
            event["editor_event_type"] = "stable_caption_cue"
            event["exclude_from_caption_occlusion_editor"] = False
            event["related_cue_ids"] = [stable_id]
            event["cue_mapping"] = {
                "status": "remapped",
                "stable_cue_id": stable_id,
                "related_cue_ids": [stable_id],
                "excluded_from_editor": False,
                "confidence": best.get("score"),
                "reason": "single_short_event_temporally_matches_stable_word_cue",
                "candidate": best,
            }
            counts["remapped_to_stable_sub_cue_count"] += 1
            continue

        # Numeric sentence-level cues duplicate several word-level V3 cues.
        aggregate = bool(
            (
                original_cue_id.isdigit()
                and duration >= 0.72
                and (len(related) >= 1 or len(event_text.split()) >= 4)
            )
            or (
                duration >= 0.72
                and len(related) >= 2
            )
        )
        if aggregate:
            event["editor_event_type"] = "aggregate_caption_window"
            event["exclude_from_caption_occlusion_editor"] = True
            event["related_cue_ids"] = related
            event["cue_mapping"] = {
                "status": "excluded_aggregate",
                "stable_cue_id": None,
                "related_cue_ids": related,
                "excluded_from_editor": True,
                "reason": "sentence_level_visual_event_duplicates_multiple_stable_word_cues",
                "candidate_count": len(candidates),
                "candidates_sample": candidates[:12],
            }
            counts["aggregate_caption_window_count"] += 1
            continue

        near_title_edge = bool(start <= 4.0 or end >= max(0.0, max_end - 2.25))
        likely_graphic = bool(
            not original_cue_id
            and style_source == "visual_style_event_without_transcript_cue"
            and near_title_edge
            and duration <= 0.55
            and len(event_text) >= 6
            and uppercase_letter_ratio(event_text) >= 0.72
            and safe_float(match.get("score"), 0.0) < 0.30
        )
        if likely_graphic:
            event["editor_event_type"] = "non_caption_graphic"
            event["exclude_from_caption_occlusion_editor"] = True
            event["related_cue_ids"] = []
            event["cue_mapping"] = {
                "status": "excluded_graphic",
                "stable_cue_id": None,
                "related_cue_ids": [],
                "excluded_from_editor": True,
                "reason": "unmatched_short_uppercase_opening_or_closing_title_graphic",
            }
            counts["non_caption_graphic_count"] += 1
            continue

        event["editor_event_type"] = "unresolved_caption_event"
        event["exclude_from_caption_occlusion_editor"] = False
        event["related_cue_ids"] = related
        event["cue_mapping"] = {
            "status": "unresolved",
            "stable_cue_id": None,
            "related_cue_ids": related,
            "excluded_from_editor": False,
            "reason": "could_not_resolve_event_to_one_stable_sub_xxxx_cue",
            "candidate_count": len(candidates),
            "candidates_sample": candidates[:12],
        }
        counts["unresolved_count"] += 1

    counts["editor_eligible_stable_cue_count"] = sum(
        1 for event in events
        if is_stable_sub_cue_id(event.get("cue_id"))
        and not bool(event.get("exclude_from_caption_occlusion_editor"))
    )
    return counts


# -----------------------------------------------------------------------------
# Foreground segmentation backends
# -----------------------------------------------------------------------------


class ForegroundSegmenter:
    def __init__(
        self,
        backend: str = "auto_gpu",
        max_side: int = 720,
        segmentation_device: str = "auto",
        paddle_gpu_id: int = 0,
        paddle_hub_module: str = "humanseg_lite",
        paddle_seg_threshold: float = 0.50,
        enable_grabcut_fallback: bool = False,
    ) -> None:
        self.backend_requested = str(backend or "auto_gpu").lower()
        self.max_side = max(240, int(max_side))
        self.segmentation_device = str(segmentation_device or "auto").lower()
        self.paddle_gpu_id = max(0, int(paddle_gpu_id))
        self.paddle_hub_module = str(paddle_hub_module or "humanseg_lite")
        self.paddle_seg_threshold = float(clamp(float(paddle_seg_threshold), 0.01, 0.99))
        self.enable_grabcut_fallback = bool(enable_grabcut_fallback)

        self._mediapipe_model = None
        self._mediapipe_error = None

        self._paddle = None
        self._paddlehub = None
        self._paddle_hub_model = None
        self._paddle_runtime: Dict[str, Any] = {
            "backend": "paddle_humanseg",
            "initialized": False,
            "available": False,
            "compiled_with_cuda": False,
            "device_requested": self.segmentation_device,
            "device_selected": None,
            "gpu_id": self.paddle_gpu_id,
            "module": self.paddle_hub_module,
            "error": None,
        }

    def _resize_for_segmentation(self, frame: np.ndarray) -> Tuple[np.ndarray, float]:
        h, w = frame.shape[:2]
        side = max(h, w)
        if side <= self.max_side:
            return frame, 1.0
        scale = self.max_side / float(side)
        resized = cv2.resize(frame, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))), interpolation=cv2.INTER_AREA)
        return resized, scale

    def _restore_mask(self, mask_small: np.ndarray, original_shape: Tuple[int, int]) -> np.ndarray:
        h, w = original_shape
        if mask_small.shape[:2] == (h, w):
            return mask_small.astype(np.uint8)
        return cv2.resize(mask_small.astype(np.uint8), (w, h), interpolation=cv2.INTER_NEAREST)

    def _with_attempts(self, info: Dict[str, Any], attempts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return a fresh info dict with attempts, without creating circular refs."""
        out = dict(info)
        out["attempts"] = [dict(a) for a in attempts]
        return out

    def segment(self, frame: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        requested = self.backend_requested
        attempts: List[Dict[str, Any]] = []

        # GPU-first mode. Preferred route for this project.
        if requested in {"auto", "auto_gpu", "paddle", "paddle_humanseg", "paddlehub_humanseg"}:
            mask, info = self._segment_paddle_humanseg(frame)
            attempts.append(dict(info))
            if mask is not None:
                return mask, self._with_attempts(info, attempts)

        if requested in {"auto", "auto_gpu", "mediapipe", "mediapipe_selfie", "paddle", "paddle_humanseg", "paddlehub_humanseg"}:
            mask, info = self._segment_mediapipe(frame)
            attempts.append(dict(info))
            if mask is not None:
                return mask, self._with_attempts(info, attempts)

        # GrabCut is CPU-heavy. In auto_gpu mode we avoid it unless explicitly
        # enabled. This prevents falling from fast GPU segmentation into another
        # long CPU-bound run when PaddleHub is not installed or not compatible.
        grabcut_allowed = requested in {"auto", "grabcut", "mediapipe", "mediapipe_selfie"} or (
            requested in {"auto_gpu", "paddle", "paddle_humanseg", "paddlehub_humanseg"} and self.enable_grabcut_fallback
        )

        if grabcut_allowed:
            mask, info = self._segment_grabcut(frame)
            attempts.append(dict(info))
            if mask is not None:
                return mask, self._with_attempts(info, attempts)

        mask, info = self._segment_heuristic(frame)
        attempts.append(dict(info))
        return mask, self._with_attempts(info, attempts)

    # -----------------------------
    # Paddle GPU human segmentation
    # -----------------------------

    def _setup_paddle_runtime(self) -> Dict[str, Any]:
        if self._paddle_runtime.get("initialized"):
            return self._paddle_runtime

        rt = self._paddle_runtime
        rt["initialized"] = True
        try:
            import paddle  # type: ignore

            self._paddle = paddle
            compiled = bool(paddle.device.is_compiled_with_cuda())
            rt["compiled_with_cuda"] = compiled

            want_gpu = self.segmentation_device in {"auto", "gpu", "cuda", "gpu:0"}
            if want_gpu and compiled:
                os.environ.setdefault("CUDA_VISIBLE_DEVICES", str(self.paddle_gpu_id))
                paddle.device.set_device(f"gpu:{self.paddle_gpu_id}")
            else:
                paddle.device.set_device("cpu")

            rt["device_selected"] = str(paddle.device.get_device())
            rt["paddle_version"] = getattr(paddle, "__version__", None)

            import paddlehub as hub  # type: ignore

            self._paddlehub = hub
            self._paddle_hub_model = hub.Module(name=self.paddle_hub_module)
            rt["available"] = True
            rt["module"] = self.paddle_hub_module
            return rt
        except Exception as exc:
            rt["available"] = False
            rt["error"] = repr(exc)
            return rt

    @staticmethod
    def _is_valid_mask_array(arr: Any) -> bool:
        return isinstance(arr, np.ndarray) and arr.size > 0 and arr.ndim in {2, 3}

    def _extract_mask_from_paddle_result(self, result: Any) -> Optional[np.ndarray]:
        """Best-effort parser for PaddleHub humanseg outputs.

        Different humanseg modules return slightly different structures. Common
        outputs include {"data": mask}, {"mask": mask}, {"segmentation": mask},
        a direct ndarray, or a list containing one of these.
        """
        if result is None:
            return None
        if isinstance(result, list) and result:
            for item in result:
                mask = self._extract_mask_from_paddle_result(item)
                if mask is not None:
                    return mask
            return None
        if isinstance(result, dict):
            preferred_keys = (
                "data",
                "mask",
                "masks",
                "segmentation",
                "segmentation_mask",
                "alpha",
                "matte",
                "result",
                "res",
                "predict",
                "processed",
                "output",
                "label_map",
                "score_map",
                "foreground",
                "foreground_mask",
            )
            for key in preferred_keys:
                if key in result:
                    mask = self._extract_mask_from_paddle_result(result.get(key))
                    if mask is not None:
                        return mask
            return None
        if self._is_valid_mask_array(result):
            arr = np.asarray(result)
            if arr.ndim == 3:
                # RGBA result: use alpha. Otherwise reduce to grayscale/max channel.
                if arr.shape[2] == 4:
                    arr = arr[:, :, 3]
                elif arr.shape[2] == 1:
                    arr = arr[:, :, 0]
                else:
                    arr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_BGR2GRAY) if arr.dtype != np.float32 else np.max(arr, axis=2)
            arr = np.asarray(arr)
            if arr.dtype != np.uint8:
                arr_f = arr.astype(np.float32)
                max_v = float(np.max(arr_f)) if arr_f.size else 0.0
                if max_v <= 1.5:
                    arr_f = arr_f * 255.0
                arr = np.clip(arr_f, 0, 255).astype(np.uint8)
            return arr
        return None

    def _call_paddlehub_segmentation(self, small: np.ndarray, use_gpu: bool) -> Any:
        model = self._paddle_hub_model
        if model is None:
            return None

        # PaddleHub humanseg_lite commonly exposes segment(...), not segmentation(...).
        # Different PaddleHub modules expose different signatures, so try the safe
        # variants in order and report the real error only after all fail.
        method_names = ["segmentation", "segment", "predict"]
        methods = []
        for name in method_names:
            if hasattr(model, name):
                methods.append((name, getattr(model, name)))

        if not methods:
            public_methods = [name for name in dir(model) if not name.startswith("_")]
            raise AttributeError(
                f"PaddleHub module {type(model)} has no supported method from {method_names}. "
                f"Available public attributes: {public_methods[:80]}"
            )

        call_variants = [
            {"images": [small], "visualization": False, "use_gpu": use_gpu},
            {"images": [small], "visualization": False},
            {"data": {"image": [small]}, "visualization": False, "use_gpu": use_gpu},
            {"data": {"image": [small]}, "visualization": False},
            {"image": small, "visualization": False, "use_gpu": use_gpu},
            {"image": small, "visualization": False},
        ]

        last_exc: Optional[Exception] = None

        for method_name, method in methods:
            for kwargs in call_variants:
                try:
                    return method(**kwargs)
                except TypeError as exc:
                    last_exc = exc
                    continue
                except Exception as exc:
                    last_exc = exc
                    continue

        # Some PaddleHub modules only support file paths. This is slower, but still
        # can run GPU inference if Paddle is already set to gpu:0.
        tmp_dir = Path(os.environ.get("VIDEO_CLONER_TMP", str(Path.cwd()))) / "_paddle_humanseg_tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"humanseg_{os.getpid()}_{int(time.time() * 1000)}.jpg"

        try:
            cv2.imwrite(str(tmp_path), small)

            path_variants = [
                {"paths": [str(tmp_path)], "visualization": False, "use_gpu": use_gpu},
                {"paths": [str(tmp_path)], "visualization": False},
                {"data": {"image": [str(tmp_path)]}, "visualization": False, "use_gpu": use_gpu},
                {"data": {"image": [str(tmp_path)]}, "visualization": False},
                {"path": str(tmp_path), "visualization": False, "use_gpu": use_gpu},
                {"path": str(tmp_path), "visualization": False},
            ]

            for method_name, method in methods:
                for kwargs in path_variants:
                    try:
                        return method(**kwargs)
                    except TypeError as exc:
                        last_exc = exc
                        continue
                    except Exception as exc:
                        last_exc = exc
                        continue

        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        if last_exc:
            available = [name for name in dir(model) if not name.startswith("_")]
            raise RuntimeError(
                f"All PaddleHub humanseg call variants failed for {type(model)}. "
                f"Available public attributes: {available[:80]}. Last error: {repr(last_exc)}"
            )

        return None

    def _segment_paddle_humanseg(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        info: Dict[str, Any] = {
            "backend": "paddle_humanseg",
            "ok": False,
            "module": self.paddle_hub_module,
            "threshold": self.paddle_seg_threshold,
            "device_requested": self.segmentation_device,
            "gpu_id": self.paddle_gpu_id,
        }
        try:
            runtime = self._setup_paddle_runtime()
            info["runtime"] = dict(runtime)
            if not runtime.get("available"):
                info["reason"] = "paddle_humanseg_unavailable"
                return None, info

            original_h, original_w = frame.shape[:2]
            small, scale = self._resize_for_segmentation(frame)
            selected_device = str(runtime.get("device_selected") or "")
            use_gpu = selected_device.startswith("gpu")

            result = self._call_paddlehub_segmentation(small, use_gpu=use_gpu)
            mask_raw = self._extract_mask_from_paddle_result(result)
            if mask_raw is None:
                info["reason"] = "could_not_extract_mask_from_paddle_result"
                info["result_type"] = str(type(result))
                return None, info

            if mask_raw.shape[:2] != small.shape[:2]:
                mask_raw = cv2.resize(mask_raw.astype(np.uint8), (small.shape[1], small.shape[0]), interpolation=cv2.INTER_LINEAR)

            # Convert score/alpha map into binary foreground mask.
            threshold_value = int(round(self.paddle_seg_threshold * 255.0))
            mask_small = (mask_raw.astype(np.uint8) >= threshold_value).astype(np.uint8) * 255
            mask_small = self._postprocess_mask(mask_small)
            mask = self._restore_mask(mask_small, (original_h, original_w))
            info.update({
                "ok": True,
                "scale": round(scale, 4),
                "processed_size": {"width": int(small.shape[1]), "height": int(small.shape[0])},
                "device_selected": selected_device,
                "paddle_compiled_with_cuda": bool(runtime.get("compiled_with_cuda")),
                "paddle_version": runtime.get("paddle_version"),
            })
            return mask, info
        except Exception as exc:
            info.update({"ok": False, "error": repr(exc)})
            return None, info

    # -----------------------------
    # CPU fallback backends
    # -----------------------------

    def _segment_mediapipe(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        info: Dict[str, Any] = {"backend": "mediapipe_selfie", "ok": False}
        try:
            if self._mediapipe_model is None:
                import mediapipe as mp  # type: ignore
                self._mediapipe_model = mp.solutions.selfie_segmentation.SelfieSegmentation(model_selection=1)

            original_h, original_w = frame.shape[:2]
            small, scale = self._resize_for_segmentation(frame)
            rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
            result = self._mediapipe_model.process(rgb)
            seg = getattr(result, "segmentation_mask", None)
            if seg is None:
                info["reason"] = "no_segmentation_mask"
                return None, info
            mask_small = (seg >= 0.45).astype(np.uint8) * 255
            mask_small = self._postprocess_mask(mask_small)
            mask = self._restore_mask(mask_small, (original_h, original_w))
            info.update({
                "ok": True,
                "threshold": 0.45,
                "scale": round(scale, 4),
                "processed_size": {"width": int(small.shape[1]), "height": int(small.shape[0])},
            })
            return mask, info
        except Exception as exc:
            self._mediapipe_error = repr(exc)
            info.update({"ok": False, "error": repr(exc)})
            return None, info

    def _segment_grabcut(self, frame: np.ndarray) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        info: Dict[str, Any] = {"backend": "grabcut", "ok": False}
        try:
            original_h, original_w = frame.shape[:2]
            small, scale = self._resize_for_segmentation(frame)
            h, w = small.shape[:2]
            x = int(round(w * 0.06))
            y = int(round(h * 0.02))
            rw = int(round(w * 0.88))
            rh = int(round(h * 0.96))
            rect = (x, y, max(1, rw), max(1, rh))
            mask = np.zeros((h, w), np.uint8)
            bgd_model = np.zeros((1, 65), np.float64)
            fgd_model = np.zeros((1, 65), np.float64)
            cv2.grabCut(small, mask, rect, bgd_model, fgd_model, 1, cv2.GC_INIT_WITH_RECT)
            out_small = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
            out_small = self._postprocess_mask(out_small)
            out = self._restore_mask(out_small, (original_h, original_w))
            info.update({"ok": True, "rect": rect, "scale": round(scale, 4)})
            return out, info
        except Exception as exc:
            info.update({"ok": False, "error": repr(exc)})
            return None, info

    def _segment_heuristic(self, frame: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
        info: Dict[str, Any] = {"backend": "heuristic", "ok": True}
        h, w = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        skin1 = cv2.inRange(hsv, np.array([0, 25, 45], dtype=np.uint8), np.array([25, 210, 255], dtype=np.uint8))
        skin2 = cv2.inRange(hsv, np.array([160, 20, 45], dtype=np.uint8), np.array([180, 210, 255], dtype=np.uint8))
        skin = cv2.bitwise_or(skin1, skin2)
        sat = cv2.inRange(hsv, np.array([0, 55, 35], dtype=np.uint8), np.array([180, 255, 255], dtype=np.uint8))
        edges = cv2.Canny(gray, 65, 160)
        edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=1)

        center_prior = np.zeros((h, w), np.uint8)
        cv2.ellipse(center_prior, (w // 2, int(h * 0.52)), (int(w * 0.42), int(h * 0.48)), 0, 0, 360, 255, -1)
        mask = cv2.bitwise_or(skin, cv2.bitwise_and(sat, center_prior))
        mask = cv2.bitwise_or(mask, cv2.bitwise_and(edges, center_prior))
        mask = self._postprocess_mask(mask)
        return mask, info

    @staticmethod
    def _postprocess_mask(mask: np.ndarray) -> np.ndarray:
        if mask is None:
            return mask
        mask = (mask > 0).astype(np.uint8) * 255
        kernel = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        num, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if num <= 1:
            return mask
        out = np.zeros_like(mask)
        area_min = max(64, int(mask.size * 0.002))
        for idx in range(1, num):
            if int(stats[idx, cv2.CC_STAT_AREA]) >= area_min:
                out[labels == idx] = 255
        return out


# -----------------------------------------------------------------------------
# Occlusion scoring
# -----------------------------------------------------------------------------


def hex_to_bgr(hex_color: Any) -> Optional[np.ndarray]:
    if not isinstance(hex_color, str):
        return None
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        r = int(value[0:2], 16)
        g = int(value[2:4], 16)
        b = int(value[4:6], 16)
        return np.array([b, g, r], dtype=np.float32)
    except Exception:
        return None


def get_event_colors(event: Dict[str, Any]) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    style = event.get("style") if isinstance(event.get("style"), dict) else {}
    colors = style.get("colors") if isinstance(style.get("colors"), dict) else {}
    stroke = style.get("stroke") if isinstance(style.get("stroke"), dict) else {}
    fill = colors.get("fill") or style.get("fill") or get_nested(style, ["typography", "fill"], None)
    outline = colors.get("stroke") or stroke.get("color") or style.get("outline")
    return hex_to_bgr(fill), hex_to_bgr(outline)


def color_distance_mask(crop: np.ndarray, color_bgr: np.ndarray, tolerance: float) -> np.ndarray:
    if crop.size == 0 or color_bgr is None:
        return np.zeros(crop.shape[:2], dtype=np.uint8)
    diff = crop.astype(np.float32) - color_bgr.reshape(1, 1, 3)
    dist = np.sqrt(np.sum(diff * diff, axis=2))
    return (dist <= tolerance).astype(np.uint8) * 255


def build_text_likelihood_mask(crop: np.ndarray, event: Dict[str, Any]) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Estimate caption pixels using expected fill/stroke colors plus conservative contrast cues.

    The result is deliberately stricter than the old visibility proxy. Saturated subject
    pixels alone are not treated as text, because that made almost every overlapping event
    look as if the caption was in front of the subject.
    """
    if crop.size == 0:
        return np.zeros(crop.shape[:2], dtype=np.uint8), {"method": "empty", "support_ratio": 0.0}

    fill_bgr, stroke_bgr = get_event_colors(event)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    methods: List[str] = []

    if fill_bgr is not None:
        mask = cv2.bitwise_or(mask, color_distance_mask(crop, fill_bgr, tolerance=46))
        methods.append("fill_color")
    if stroke_bgr is not None:
        mask = cv2.bitwise_or(mask, color_distance_mask(crop, stroke_bgr, tolerance=38))
        methods.append("stroke_color")

    # Flat regions that merely share the detected fill/stroke color are not text.
    # Gate color matches through local edges so black clothing, white walls and
    # saturated backgrounds do not become false caption pixels.
    edge_gate = cv2.dilate(cv2.Canny(gray, 55, 145), np.ones((3, 3), np.uint8))
    mask = cv2.bitwise_and(mask, edge_gate)

    # Fallback only when style colors provide almost no support. Use high-contrast
    # thin structures, not broad saturated regions that often belong to clothing.
    initial_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)
    if initial_ratio < 0.008:
        bright = ((gray >= 205) & (hsv[:, :, 1] <= 150)).astype(np.uint8) * 255
        dark = ((gray <= 42) & (hsv[:, :, 2] <= 90)).astype(np.uint8) * 255
        edges = cv2.Canny(gray, 70, 160)
        fallback = cv2.bitwise_and(cv2.bitwise_or(bright, dark), cv2.dilate(edges, np.ones((3, 3), np.uint8)))
        mask = cv2.bitwise_or(mask, fallback)
        methods.append("contrast_edge_fallback")

    kernel = np.ones((2, 2), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    support_ratio = float(np.count_nonzero(mask)) / max(1, mask.size)
    return mask, {
        "method": "+".join(methods) if methods else "none",
        "support_ratio": round(support_ratio, 4),
        "fill_color_available": fill_bgr is not None,
        "stroke_color_available": stroke_bgr is not None,
    }


def estimate_layer_order_evidence(frame: np.ndarray, fg_mask: np.ndarray, bbox: List[int], event: Dict[str, Any]) -> Dict[str, Any]:
    """Compare caption-pixel density inside vs. outside the foreground silhouette.

    v1.9 preserves raw evidence even when the density comparison is formally
    underconstrained (for example, when the subject fills almost the entire text
    bbox and there are too few background pixels). In those cases v1.8 scaled a
    clear raw front score of 1.0 down to 0.35 and then refused to promote it.
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    x1, x2 = max(0, min(x1, w - 1)), max(1, min(x2, w))
    y1, y2 = max(0, min(y1, h - 1)), max(1, min(y2, h))
    if x2 <= x1 or y2 <= y1:
        return {"reliable": False, "reason": "empty_bbox"}

    crop = frame[y1:y2, x1:x2]
    fg_crop = fg_mask[y1:y2, x1:x2] > 0
    text_mask, text_info = build_text_likelihood_mask(crop, event)
    text_bool = text_mask > 0

    fg_pixels = int(np.count_nonzero(fg_crop))
    bg_pixels = int(np.count_nonzero(~fg_crop))
    text_inside = int(np.count_nonzero(text_bool & fg_crop))
    text_outside = int(np.count_nonzero(text_bool & (~fg_crop)))
    inside_density = text_inside / max(1, fg_pixels)
    outside_density = text_outside / max(1, bg_pixels)
    total_text = text_inside + text_outside
    total_area = max(1, crop.shape[0] * crop.shape[1])
    text_support = total_text / total_area

    density_ratio = inside_density / max(0.002, outside_density)
    raw_front_score = clamp((density_ratio - 0.30) / 0.70, 0.0, 1.0)
    behind_gap = clamp((outside_density - inside_density) / max(0.01, outside_density), 0.0, 1.0)
    raw_behind_score = clamp(behind_gap, 0.0, 1.0)

    enough_fg = fg_pixels >= max(12, int(total_area * 0.06))
    enough_bg = bg_pixels >= max(12, int(total_area * 0.06))
    enough_text = total_text >= max(8, int(total_area * 0.008))
    reliable = bool(enough_fg and enough_bg and enough_text and text_support >= 0.008)

    front_score = raw_front_score
    behind_score = raw_behind_score
    reliability_scale = 1.0 if reliable else 0.35
    if not reliable:
        front_score *= reliability_scale
        behind_score *= reliability_scale

    if reliable and front_score >= 0.62 and inside_density >= 0.008:
        order = "text_over_foreground"
    elif reliable and behind_score >= 0.58 and outside_density >= 0.012:
        order = "foreground_over_text"
    else:
        order = "uncertain"

    reliability_reasons: List[str] = []
    if not enough_fg:
        reliability_reasons.append("insufficient_foreground_pixels")
    if not enough_bg:
        reliability_reasons.append("insufficient_background_pixels")
    if not enough_text:
        reliability_reasons.append("insufficient_text_pixels")
    if text_support < 0.008:
        reliability_reasons.append("text_support_below_threshold")

    return {
        "reliable": reliable,
        "reliability_reasons": reliability_reasons,
        "reliability_scale": reliability_scale,
        "order": order,
        "front_score": round(float(front_score), 4),
        "behind_score": round(float(behind_score), 4),
        "front_score_raw": round(float(raw_front_score), 4),
        "behind_score_raw": round(float(raw_behind_score), 4),
        "text_support_ratio": round(float(text_support), 4),
        "text_inside_foreground_density": round(float(inside_density), 4),
        "text_outside_foreground_density": round(float(outside_density), 4),
        "inside_outside_density_ratio": round(float(density_ratio), 4),
        "foreground_pixels_in_bbox": fg_pixels,
        "background_pixels_in_bbox": bg_pixels,
        "text_pixels_inside_foreground": text_inside,
        "text_pixels_outside_foreground": text_outside,
        "text_mask": text_info,
    }


def estimate_text_visibility(frame: np.ndarray, bbox: List[int], event: Dict[str, Any]) -> Dict[str, Any]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = expand_bbox(bbox, w, h, pad_ratio=0.08, min_pad=3)
    crop = frame[y1:y2, x1:x2]
    if crop.size == 0:
        return {"text_pixel_ratio": 0.0, "bright_ratio": 0.0, "dark_ratio": 0.0, "saturated_ratio": 0.0, "visibility_proxy": 0.0}

    fill_bgr, stroke_bgr = get_event_colors(event)
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    bright = (gray >= 180).astype(np.uint8) * 255
    dark = (gray <= 65).astype(np.uint8) * 255
    saturated = ((hsv[:, :, 1] >= 75) & (hsv[:, :, 2] >= 55)).astype(np.uint8) * 255

    color_mask = np.zeros(crop.shape[:2], dtype=np.uint8)
    if fill_bgr is not None:
        color_mask = cv2.bitwise_or(color_mask, color_distance_mask(crop, fill_bgr, tolerance=58))
    if stroke_bgr is not None:
        color_mask = cv2.bitwise_or(color_mask, color_distance_mask(crop, stroke_bgr, tolerance=52))

    # Text can be white/colored with black outline. This proxy measures whether
    # expected text-like pixels are present inside the event area.
    text_like = cv2.bitwise_or(color_mask, cv2.bitwise_or(bright, cv2.bitwise_and(dark, saturated | bright)))
    area = max(1, text_like.size)
    text_ratio = float(np.count_nonzero(text_like)) / area
    bright_ratio = float(np.count_nonzero(bright)) / area
    dark_ratio = float(np.count_nonzero(dark)) / area
    sat_ratio = float(np.count_nonzero(saturated)) / area
    visibility = clamp((text_ratio * 2.8) + (bright_ratio * 0.6) + (sat_ratio * 0.4), 0.0, 1.0)
    return {
        "text_pixel_ratio": round(text_ratio, 4),
        "bright_ratio": round(bright_ratio, 4),
        "dark_ratio": round(dark_ratio, 4),
        "saturated_ratio": round(sat_ratio, 4),
        "visibility_proxy": round(float(visibility), 4),
    }


def mask_overlap(mask: np.ndarray, bbox: List[int]) -> Dict[str, Any]:
    h, w = mask.shape[:2]
    x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
    x1, x2 = min(x1, w - 1), min(max(x2, x1 + 1), w)
    y1, y2 = min(y1, h - 1), min(max(y2, y1 + 1), h)
    crop = mask[y1:y2, x1:x2]
    area = max(1, crop.size)
    fg_count = int(np.count_nonzero(crop > 0))
    return {
        "foreground_pixels": fg_count,
        "area_pixels": int(area),
        "overlap_ratio": round(float(fg_count) / area, 4),
    }


def score_sample(frame: np.ndarray, fg_mask: np.ndarray, bbox: List[int], event: Dict[str, Any]) -> Dict[str, Any]:
    h, w = frame.shape[:2]
    bbox_expanded = expand_bbox(bbox, w, h, pad_ratio=0.16, min_pad=6)
    exact_overlap = mask_overlap(fg_mask, bbox)
    expanded_overlap = mask_overlap(fg_mask, bbox_expanded)
    visibility = estimate_text_visibility(frame, bbox, event)
    layer_evidence = estimate_layer_order_evidence(frame, fg_mask, bbox, event)

    fg_overlap = safe_float(expanded_overlap.get("overlap_ratio"), 0.0)
    exact_fg = safe_float(exact_overlap.get("overlap_ratio"), 0.0)
    visibility_proxy = safe_float(visibility.get("visibility_proxy"), 0.0)
    front_score = safe_float(layer_evidence.get("front_score"), 0.0)
    behind_score = safe_float(layer_evidence.get("behind_score"), 0.0)
    evidence_reliable = bool(layer_evidence.get("reliable"))

    overlap_score = (0.45 * fg_overlap) + (0.55 * exact_fg)
    if evidence_reliable:
        occlusion_score = overlap_score * (0.42 + (0.58 * behind_score)) * (1.0 - (0.72 * front_score))
    else:
        # Keep an audit signal but do not aggressively infer layer order from the
        # legacy saturation visibility proxy.
        low_visibility_factor = clamp(1.0 - visibility_proxy, 0.0, 1.0)
        occlusion_score = overlap_score * (0.36 + (0.24 * low_visibility_factor))
    occlusion_score = clamp(occlusion_score, 0.0, 1.0)

    return {
        "bbox": bbox,
        "expanded_bbox": bbox_expanded,
        "foreground_overlap": {
            "exact": exact_overlap,
            "expanded": expanded_overlap,
        },
        "text_visibility": visibility,
        "layer_order_evidence": layer_evidence,
        "occlusion_score": round(float(occlusion_score), 4),
    }


def classify_event_occlusion(samples: List[Dict[str, Any]], occlusion_threshold: float, mask_overlap_threshold: float) -> Dict[str, Any]:
    valid = [sample for sample in samples if isinstance(sample, dict) and sample.get("ok")]
    if not valid:
        return {
            "detected": False,
            "needs_foreground_mask": False,
            "score": 0.0,
            "label": "none",
            "layer_order": "unknown",
            "review_required": True,
            "reason": "no_valid_samples",
        }

    scores = [safe_float(sample.get("occlusion_score"), 0.0) for sample in valid]
    exact_overlaps = [safe_float(get_nested(sample, ["foreground_overlap", "exact", "overlap_ratio"], 0.0), 0.0) for sample in valid]
    expanded_overlaps = [safe_float(get_nested(sample, ["foreground_overlap", "expanded", "overlap_ratio"], 0.0), 0.0) for sample in valid]
    front_scores = [safe_float(get_nested(sample, ["layer_order_evidence", "front_score"], 0.0), 0.0) for sample in valid]
    behind_scores = [safe_float(get_nested(sample, ["layer_order_evidence", "behind_score"], 0.0), 0.0) for sample in valid]
    raw_front_scores: List[float] = []
    raw_behind_scores: List[float] = []
    for sample in valid:
        evidence = get_nested(sample, ["layer_order_evidence"], {}) or {}
        reliable = bool(evidence.get("reliable"))
        scale = safe_float(evidence.get("reliability_scale"), 1.0 if reliable else 0.35)
        front_value = safe_float(evidence.get("front_score"), 0.0)
        behind_value = safe_float(evidence.get("behind_score"), 0.0)
        raw_front_scores.append(
            safe_float(
                evidence.get("front_score_raw"),
                clamp(front_value / max(0.01, scale), 0.0, 1.0) if not reliable else front_value,
            )
        )
        raw_behind_scores.append(
            safe_float(
                evidence.get("behind_score_raw"),
                clamp(behind_value / max(0.01, scale), 0.0, 1.0) if not reliable else behind_value,
            )
        )
    reliable_flags = [bool(get_nested(sample, ["layer_order_evidence", "reliable"], False)) for sample in valid]
    orders = [str(get_nested(sample, ["layer_order_evidence", "order"], "uncertain")) for sample in valid]
    outside_densities = [safe_float(get_nested(sample, ["layer_order_evidence", "text_outside_foreground_density"], 0.0), 0.0) for sample in valid]
    inside_densities = [safe_float(get_nested(sample, ["layer_order_evidence", "text_inside_foreground_density"], 0.0), 0.0) for sample in valid]
    text_support = [safe_float(get_nested(sample, ["layer_order_evidence", "text_support_ratio"], 0.0), 0.0) for sample in valid]

    max_score = max(scores)
    med_score = float(np.median(scores))
    max_exact = max(exact_overlaps)
    med_exact = float(np.median(exact_overlaps))
    max_expanded = max(expanded_overlaps)
    med_expanded = float(np.median(expanded_overlaps))
    med_front = float(np.median(front_scores))
    med_behind = float(np.median(behind_scores))
    med_raw_front = float(np.median(raw_front_scores))
    med_raw_behind = float(np.median(raw_behind_scores))
    med_outside_density = float(np.median(outside_densities))
    med_inside_density = float(np.median(inside_densities))
    med_text_support = float(np.median(text_support))
    reliable_count = sum(1 for value in reliable_flags if value)
    front_votes = sum(1 for value in orders if value == "text_over_foreground")
    behind_votes = sum(1 for value in orders if value == "foreground_over_text")

    raw_front_signal_votes = sum(
        1
        for front, behind, exact in zip(raw_front_scores, raw_behind_scores, exact_overlaps)
        if front >= 0.74 and behind <= 0.18 and exact >= 0.30
    )
    strict_behind_signal_votes = sum(
        1
        for reliable, front, behind, exact, outside in zip(
            reliable_flags, front_scores, behind_scores, exact_overlaps, outside_densities
        )
        if reliable and behind >= 0.58 and front <= 0.22 and exact >= 0.12 and outside >= 0.012
    )

    meaningful_overlap = bool(max_exact >= mask_overlap_threshold or max_expanded >= mask_overlap_threshold)
    persistent_overlap = bool(
        med_exact >= max(0.10, mask_overlap_threshold * 0.72)
        or med_expanded >= mask_overlap_threshold
    )

    # v1.9 front promotion:
    # - preserve the original reliable rule;
    # - also accept 2/3 strong raw-front samples when the subject fills the bbox
    #   and the old reliability test had too few background pixels;
    # - accept a consistent medium front signal with low behind evidence.
    strong_front = bool(
        meaningful_overlap
        and (
            (
                reliable_count >= 1
                and (front_votes >= 2 or (med_front >= 0.62 and med_behind <= 0.36))
            )
            or (
                raw_front_signal_votes >= 2
                and med_raw_front >= 0.74
                and med_raw_behind <= 0.18
                and med_exact >= 0.35
            )
            or (
                reliable_count >= 2
                and med_front >= 0.48
                and med_behind <= 0.18
                and med_exact >= 0.35
            )
            or (
                # Caption-colored glyph pixels remain materially visible inside
                # the subject silhouette even when the density ratio is only
                # moderate. This resolves cases such as "blocks." and
                # "overnight." that v1.8 left under review.
                reliable_count >= 2
                and med_exact >= 0.35
                and med_inside_density >= 0.035
                and med_raw_front >= 0.20
                and med_raw_behind <= 0.60
            )
        )
    )

    # v1.9 behind policy deliberately requires material glyph-area collision.
    # This rejects event sub_0079 ("the"), where only ~8-10% of the bbox touches
    # the person and no detected caption glyph pixels collide with the silhouette.
    material_behind_overlap = bool(max_exact >= 0.15 and med_exact >= 0.12)
    strong_behind = bool(
        meaningful_overlap
        and persistent_overlap
        and material_behind_overlap
        and reliable_count >= 2
        and behind_votes >= 2
        and strict_behind_signal_votes >= 2
        and med_behind >= 0.65
        and med_front <= 0.18
        and med_outside_density >= 0.012
        and med_text_support >= 0.008
    )

    low_material_overlap = bool(
        meaningful_overlap
        and max_exact < 0.12
        and med_exact < 0.10
        and max_expanded < 0.22
    )
    transient_nonpersistent_overlap = bool(
        meaningful_overlap
        and not persistent_overlap
        and med_exact < 0.04
        and med_expanded < 0.04
        and reliable_count <= 1
    )

    if not meaningful_overlap:
        layer_order = "no_overlap"
        detected = False
        needs_mask = False
        label = "none"
        review_required = False
        reason = "no_meaningful_foreground_overlap"
    elif strong_front:
        layer_order = "text_over_foreground"
        detected = False
        needs_mask = False
        label = "front"
        review_required = False
        reason = "caption_pixels_persist_inside_foreground_text_is_in_front"
    elif strong_behind:
        layer_order = "foreground_over_text"
        detected = True
        needs_mask = True
        confidence_score = clamp(
            (0.42 * med_behind)
            + (0.26 * max_exact)
            + (0.20 * med_exact)
            + (0.12 * min(1.0, behind_votes / 2.0)),
            0.0,
            1.0,
        )
        # The strong_behind gate is already strict: at least 2 reliable direct
        # behind votes, material exact overlap, low front evidence and sufficient
        # caption support. Passing that gate is an approved classification; cue
        # mapping and asset completeness are checked later.
        label = "high"
        review_required = False
        reason = "caption_pixels_drop_inside_foreground_subject_is_in_front"
    elif low_material_overlap:
        layer_order = "no_material_overlap"
        detected = False
        needs_mask = False
        label = "none"
        review_required = False
        reason = "foreground_touches_caption_bbox_but_not_enough_glyph_area_for_production_matte"
    elif transient_nonpersistent_overlap:
        layer_order = "transient_nonpersistent_overlap"
        detected = False
        needs_mask = False
        label = "none"
        review_required = False
        reason = "foreground_overlap_occurs_in_only_one_sample_and_is_not_persistent_enough_for_event_matte"
    else:
        layer_order = "uncertain"
        detected = False
        needs_mask = False
        label = "review"
        review_required = True
        reason = "foreground_overlap_present_but_layer_order_evidence_is_inconclusive"

    confidence = clamp(
        max(med_front, med_behind, med_raw_front * 0.72, med_raw_behind * 0.72)
        * (0.45 + (0.55 * min(1.0, reliable_count / max(1, len(valid)))))
        + (0.18 * max_exact),
        0.0,
        1.0,
    )

    return {
        "detected": detected,
        "needs_foreground_mask": needs_mask,
        "score": round(float((0.55 * max_score) + (0.45 * med_score)), 4),
        "label": label,
        "layer_order": layer_order,
        "review_required": review_required,
        "classification_confidence": round(float(confidence), 4),
        "reason": reason,
        "max_score": round(float(max_score), 4),
        "median_score": round(float(med_score), 4),
        "max_foreground_overlap": round(float(max_expanded), 4),
        "median_foreground_overlap": round(float(med_expanded), 4),
        "max_exact_foreground_overlap": round(float(max_exact), 4),
        "median_exact_foreground_overlap": round(float(med_exact), 4),
        "median_front_score": round(float(med_front), 4),
        "median_behind_score": round(float(med_behind), 4),
        "median_raw_front_score": round(float(med_raw_front), 4),
        "median_raw_behind_score": round(float(med_raw_behind), 4),
        "median_text_inside_foreground_density": round(float(med_inside_density), 4),
        "median_text_outside_foreground_density": round(float(med_outside_density), 4),
        "median_text_support_ratio": round(float(med_text_support), 4),
        "reliable_layer_evidence_samples": int(reliable_count),
        "front_vote_count": int(front_votes),
        "behind_vote_count": int(behind_votes),
        "raw_front_signal_vote_count": int(raw_front_signal_votes),
        "strict_behind_signal_vote_count": int(strict_behind_signal_votes),
        "material_behind_overlap": bool(material_behind_overlap),
        "transient_nonpersistent_overlap": bool(transient_nonpersistent_overlap),
        "likely_text_in_front": layer_order == "text_over_foreground",
        "legacy_compatibility": {
            "occlusion_threshold": round(float(occlusion_threshold), 4),
            "mask_overlap_threshold": round(float(mask_overlap_threshold), 4),
        },
    }


def classify_event_occlusion_legacy(samples: List[Dict[str, Any]], occlusion_threshold: float, mask_overlap_threshold: float) -> Dict[str, Any]:
    """Reproduce the v1.7 decision for audit comparison only."""
    valid = [s for s in samples if isinstance(s, dict) and s.get("ok")]
    if not valid:
        return {"label": "none", "detected": False, "needs_foreground_mask": False, "likely_text_in_front": False}
    scores = [safe_float(s.get("occlusion_score"), 0.0) for s in valid]
    overlaps = [safe_float(get_nested(s, ["foreground_overlap", "expanded", "overlap_ratio"], 0.0), 0.0) for s in valid]
    visibility = [safe_float(get_nested(s, ["text_visibility", "visibility_proxy"], 0.0), 0.0) for s in valid]
    max_score = max(scores)
    med_score = float(np.median(scores))
    max_overlap = max(overlaps)
    med_overlap = float(np.median(overlaps))
    med_visibility = float(np.median(visibility))
    final_score = clamp((0.60 * max_score) + (0.40 * med_score), 0.0, 1.0)
    detected = bool(final_score >= occlusion_threshold and max_overlap >= mask_overlap_threshold)
    likely_text_in_front = bool(med_visibility >= 0.55 and med_overlap >= mask_overlap_threshold and final_score < (occlusion_threshold + 0.12))
    if detected:
        label = "high" if final_score >= 0.68 else "medium"
    elif likely_text_in_front or max_overlap >= mask_overlap_threshold:
        label = "low"
    else:
        label = "none"
    return {
        "label": label,
        "detected": detected,
        "needs_foreground_mask": detected,
        "likely_text_in_front": likely_text_in_front,
        "score": round(float(final_score), 4),
        "max_overlap": round(float(max_overlap), 4),
        "median_overlap": round(float(med_overlap), 4),
        "median_visibility": round(float(med_visibility), 4),
    }


# -----------------------------------------------------------------------------
# Debug output
# -----------------------------------------------------------------------------


def draw_debug_overlay(frame: np.ndarray, bbox: List[int], fg_mask: np.ndarray, sample_result: Dict[str, Any], event: Dict[str, Any]) -> np.ndarray:
    out = frame.copy()
    overlay = out.copy()
    color_mask = np.zeros_like(out)
    color_mask[:, :, 1] = fg_mask
    overlay = cv2.addWeighted(overlay, 1.0, color_mask, 0.32, 0)
    out = overlay
    x1, y1, x2, y2 = bbox
    cv2.rectangle(out, (x1, y1), (x2, y2), (0, 220, 255), 3)
    eb = sample_result.get("expanded_bbox") or bbox
    cv2.rectangle(out, (eb[0], eb[1]), (eb[2], eb[3]), (255, 120, 0), 2)
    text = f"occ={sample_result.get('occlusion_score')} fg={get_nested(sample_result, ['foreground_overlap','exact','overlap_ratio'], 0)} front={get_nested(sample_result, ['layer_order_evidence','front_score'], 0)} behind={get_nested(sample_result, ['layer_order_evidence','behind_score'], 0)}"
    cv2.putText(out, text, (max(5, x1), max(24, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 2, cv2.LINE_AA)
    caption = clean_text(event.get("text"))[:60]
    if caption:
        cv2.putText(out, caption, (max(5, x1), min(out.shape[0] - 10, y2 + 30)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 220, 255), 2, cv2.LINE_AA)
    return out


def save_debug_frame(debug_dir: str, event_index: int, sample_index: int, timestamp: float, frame: np.ndarray, bbox: List[int], fg_mask: np.ndarray, sample_result: Dict[str, Any], event: Dict[str, Any]) -> Optional[str]:
    try:
        os.makedirs(debug_dir, exist_ok=True)
        debug = draw_debug_overlay(frame, bbox, fg_mask, sample_result, event)
        path = os.path.join(debug_dir, f"occlusion_event_{event_index:04d}_sample_{sample_index:02d}_{timestamp:.2f}s.jpg")
        cv2.imwrite(path, debug)
        return path
    except Exception:
        return None


def sanitize_asset_token(value: Any, fallback: str = "event") -> str:
    token = clean_text(value)
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", token).strip("._-")
    return token[:96] or fallback


def event_frame_range(event: Dict[str, Any], fps: float, frame_count: int) -> Tuple[int, int]:
    """Return [start_frame, end_frame_exclusive) clamped to the source video."""
    start_sec = max(0.0, safe_float(event.get("start"), 0.0))
    end_sec = max(start_sec, safe_float(event.get("end"), start_sec))
    start_frame = max(0, int(math.floor((start_sec * fps) + 1e-6)))
    end_frame_exclusive = max(start_frame + 1, int(math.ceil((end_sec * fps) - 1e-6)))
    if frame_count > 0:
        start_frame = min(start_frame, max(0, frame_count - 1))
        end_frame_exclusive = min(max(start_frame + 1, end_frame_exclusive), frame_count)
    return start_frame, end_frame_exclusive


def write_mask_png(path: Path, mask: np.ndarray) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        mask_u8 = np.asarray(mask)
        if mask_u8.ndim == 3:
            mask_u8 = mask_u8[:, :, 0]
        if mask_u8.dtype != np.uint8:
            mask_u8 = np.clip(mask_u8, 0, 255).astype(np.uint8)
        ok = bool(cv2.imwrite(str(path), mask_u8, [cv2.IMWRITE_PNG_COMPRESSION, 9]))
        return ok and path.exists() and path.stat().st_size > 0
    except Exception:
        return False


def export_event_mask_assets(
    event: Dict[str, Any],
    event_index: int,
    cap: cv2.VideoCapture,
    segmenter: ForegroundSegmenter,
    args: argparse.Namespace,
    fps: float,
    frame_count: int,
    frame_w: int,
    frame_h: int,
) -> Dict[str, Any]:
    """Persist a full-frame 8-bit alpha-mask PNG sequence for one event.

    The mask uses 0 for transparent/background and 255 for foreground. Files use
    absolute source-frame numbers, which makes the contract deterministic and
    directly alignable with the source video and Resolve timeline.
    """
    cue_id = sanitize_asset_token(event.get("cue_id") or event.get("caption_event_id") or event.get("id"), f"event_{event_index:04d}")
    event_dir_name = f"{event_index:04d}_{cue_id}"
    root = Path(str(args.mask_output_dir)).resolve()
    event_dir = root / event_dir_name
    start_frame, end_frame_exclusive = event_frame_range(event, fps=fps, frame_count=frame_count)
    expected_count = max(0, end_frame_exclusive - start_frame)

    result: Dict[str, Any] = {
        "requested": True,
        "asset_type": "png_sequence_alpha_mask",
        "mask_encoding": "grayscale_u8_0_background_255_foreground",
        "mask_root": str(root),
        "event_dir": str(event_dir),
        "event_dir_name": event_dir_name,
        "mask_pattern": str(event_dir / "mask_%06d.png"),
        "relative_mask_pattern": str(Path(event_dir_name) / "mask_%06d.png"),
        "source_frame_start": start_frame,
        "source_frame_end_exclusive": end_frame_exclusive,
        "frame_count_expected": expected_count,
        "frame_count_written": 0,
        "width": frame_w,
        "height": frame_h,
        "complete": False,
        "backend_counts": {},
        "files_sample": [],
        "errors": [],
    }

    if expected_count <= 0:
        result["errors"].append("empty_frame_range")
        return result

    if event_dir.exists() and bool(args.clear_mask_assets_per_event):
        shutil.rmtree(event_dir, ignore_errors=True)
    event_dir.mkdir(parents=True, exist_ok=True)

    files: List[str] = []
    backend_counts: Dict[str, int] = {}
    previous_pos = cap.get(cv2.CAP_PROP_POS_FRAMES)

    try:
        for frame_idx in range(start_frame, end_frame_exclusive):
            cap.set(cv2.CAP_PROP_POS_FRAMES, float(frame_idx))
            ok, frame = cap.read()
            if not ok or frame is None:
                result["errors"].append(f"frame_read_failed:{frame_idx}")
                if bool(args.mask_stop_on_first_failure):
                    break
                continue

            fg_mask, seg_info = segmenter.segment(frame)
            backend = str(seg_info.get("backend") or "unknown")
            backend_counts[backend] = backend_counts.get(backend, 0) + 1

            if bool(args.require_paddle_gpu) and backend != "paddle_humanseg":
                result["errors"].append(f"non_paddle_backend:{frame_idx}:{backend}")
                if bool(args.mask_stop_on_first_failure):
                    break
                continue

            if fg_mask is None or not isinstance(fg_mask, np.ndarray) or fg_mask.size == 0:
                result["errors"].append(f"empty_mask:{frame_idx}")
                if bool(args.mask_stop_on_first_failure):
                    break
                continue

            if fg_mask.shape[:2] != (frame_h, frame_w):
                fg_mask = cv2.resize(fg_mask.astype(np.uint8), (frame_w, frame_h), interpolation=cv2.INTER_NEAREST)

            mask_path = event_dir / f"mask_{frame_idx:06d}.png"
            if not write_mask_png(mask_path, fg_mask):
                result["errors"].append(f"mask_write_failed:{frame_idx}")
                if bool(args.mask_stop_on_first_failure):
                    break
                continue

            files.append(str(mask_path))
            written_total = int(getattr(args, "_mask_frames_written", 0)) + 1
            setattr(args, "_mask_frames_written", written_total)
            progress_every = max(0, int(getattr(args, "mask_progress_every", 0)))
            if progress_every > 0 and written_total % progress_every == 0:
                print(json.dumps({
                    "mask_progress": True,
                    "event_index": event_index,
                    "cue_id": cue_id,
                    "mask_frames_written": written_total,
                    "current_source_frame": frame_idx,
                }, ensure_ascii=False), flush=True)
    finally:
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, previous_pos)
        except Exception:
            pass

    result["frame_count_written"] = len(files)
    result["complete"] = len(files) == expected_count and not result["errors"]
    result["backend_counts"] = backend_counts
    result["files_sample"] = files[:3] + (files[-2:] if len(files) > 3 else [])
    result["first_file"] = files[0] if files else None
    result["last_file"] = files[-1] if files else None

    manifest_path = event_dir / "manifest.json"
    manifest = {
        "schema": "video_cloner_foreground_mask_sequence",
        "schema_version": "1.0",
        "analysis_version": ANALYSIS_VERSION,
        "event_index": event_index,
        "cue_id": event.get("cue_id"),
        "caption_event_id": event.get("caption_event_id"),
        "text": event.get("text"),
        "start_seconds": event.get("start"),
        "end_seconds": event.get("end"),
        "fps": fps,
        **{k: v for k, v in result.items() if k not in {"files_sample", "errors"}},
        "errors": list(result["errors"]),
    }
    try:
        write_json(str(manifest_path), manifest, encoding=args.encoding)
        result["manifest"] = str(manifest_path)
    except Exception as exc:
        result["errors"].append(f"manifest_write_failed:{repr(exc)}")
        result["complete"] = False

    return result


# -----------------------------------------------------------------------------
# Main analysis
# -----------------------------------------------------------------------------


def analyze_event(
    event: Dict[str, Any],
    event_index: int,
    cap: cv2.VideoCapture,
    video_duration: float,
    segmenter: ForegroundSegmenter,
    args: argparse.Namespace,
    frame_w: int,
    frame_h: int,
    fps: float,
    frame_count: int,
) -> Dict[str, Any]:
    bbox = event.get("bbox")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return {
            "id": event.get("id"),
            "source": event.get("source"),
            "text": event.get("text"),
            "skipped": True,
            "reason": "missing_bbox",
        }

    sample_times = sample_times_for_window(
        start=safe_float(event.get("start"), 0.0),
        end=safe_float(event.get("end"), 0.0),
        mid=safe_float(event.get("mid"), 0.0),
        samples=max(1, int(args.samples_per_event)),
        sample_window_sec=safe_float(args.sample_window_sec, 0.22),
        duration=video_duration,
    )

    sample_results: List[Dict[str, Any]] = []
    backend_counts: Dict[str, int] = {}
    debug_paths: List[str] = []

    for sample_idx, ts in enumerate(sample_times, start=1):
        ok, frame, ts_used = read_frame_at(cap, ts, video_duration)
        if not ok or frame is None:
            sample_results.append({"timestamp": ts, "ok": False, "reason": "frame_read_failed"})
            continue
        fg_mask, seg_info = segmenter.segment(frame)
        backend = str(seg_info.get("backend") or "unknown")
        backend_counts[backend] = backend_counts.get(backend, 0) + 1
        sample_result = score_sample(frame, fg_mask, bbox, event)
        sample_result.update({
            "timestamp": round(float(ts_used), 4),
            "ok": True,
            "segmentation": seg_info,
        })
        if args.write_debug_frames:
            written_so_far = int(getattr(args, "_debug_frames_written", 0))
            debug_budget = max(0, int(getattr(args, "debug_max_frames", 80)))
            if debug_budget == 0 or written_so_far < debug_budget:
                path = save_debug_frame(args.debug_dir, event_index, sample_idx, ts_used, frame, bbox, fg_mask, sample_result, event)
                if path:
                    setattr(args, "_debug_frames_written", written_so_far + 1)
                    sample_result["debug_frame"] = path
                    debug_paths.append(path)
            else:
                sample_result["debug_frame_skipped"] = "debug_max_frames_reached"
        sample_results.append(sample_result)

    occlusion = classify_event_occlusion(sample_results, occlusion_threshold=safe_float(args.occlusion_threshold, 0.42), mask_overlap_threshold=safe_float(args.mask_overlap_threshold, 0.18))
    occlusion["legacy_v1_7_decision"] = classify_event_occlusion_legacy(sample_results, occlusion_threshold=safe_float(args.occlusion_threshold, 0.42), mask_overlap_threshold=safe_float(args.mask_overlap_threshold, 0.18))
    cue_id_value = clean_text(event.get("cue_id"))
    cue_id_valid = is_stable_sub_cue_id(cue_id_value)
    cue_mapping = event.get("cue_mapping") if isinstance(event.get("cue_mapping"), dict) else {}
    excluded_from_editor = bool(event.get("exclude_from_caption_occlusion_editor"))

    if excluded_from_editor:
        occlusion["detected"] = False
        occlusion["needs_foreground_mask"] = False
        occlusion["review_required"] = False
        occlusion["editor_excluded"] = True
        occlusion["editor_exclusion_reason"] = cue_mapping.get("reason") or event.get("editor_event_type")
    elif not cue_id_valid:
        occlusion["review_required"] = True
        occlusion["cue_mapping_warning"] = "cue_id_is_not_stable_sub_xxxx"

    occlusion["cue_id_valid"] = bool(cue_id_valid)
    occlusion["editor_event_type"] = event.get("editor_event_type")
    occlusion["cue_mapping"] = cue_mapping
    occlusion["ready_for_editor_compositing"] = bool(
        occlusion.get("needs_foreground_mask")
        and cue_id_valid
        and not excluded_from_editor
        and not occlusion.get("review_required")
    )

    mask_asset: Optional[Dict[str, Any]] = None
    should_export_mask = bool(args.write_mask_assets) and (
        bool(occlusion.get("needs_foreground_mask")) or not bool(args.mask_assets_only_needed)
    )
    if should_export_mask:
        mask_asset = export_event_mask_assets(
            event=event,
            event_index=event_index,
            cap=cap,
            segmenter=segmenter,
            args=args,
            fps=fps,
            frame_count=frame_count,
            frame_w=frame_w,
            frame_h=frame_h,
        )

    result = {
        "index": event_index,
        "id": event.get("id") or f"occlusion_event_{event_index:04d}",
        "source": event.get("source"),
        "caption_event_id": event.get("caption_event_id"),
        "cue_id": event.get("cue_id"),
        "original_cue_id": event.get("original_cue_id"),
        "cue_mapping": event.get("cue_mapping"),
        "related_cue_ids": event.get("related_cue_ids") or [],
        "editor_event_type": event.get("editor_event_type"),
        "exclude_from_caption_occlusion_editor": bool(event.get("exclude_from_caption_occlusion_editor")),
        "text": event.get("text"),
        "observed_text": event.get("observed_text"),
        "start": event.get("start"),
        "end": event.get("end"),
        "mid": event.get("mid"),
        "duration": event.get("duration"),
        "bbox": bbox,
        "normalized_bbox": event.get("normalized_bbox") or bbox_to_normalized(bbox, frame_w, frame_h),
        "center": bbox_center_norm(bbox, frame_w, frame_h),
        "style_profile_id": event.get("style_profile_id"),
        "sample_times": sample_times,
        "samples": sample_results,
        "foreground": {
            "backend_requested": args.backend,
            "backend_counts": backend_counts,
        },
        "occlusion": occlusion,
        "mask_asset": mask_asset,
        "layering": {
            "occluded_by_foreground": bool(occlusion.get("detected")),
            "foreground_mask_required": bool(occlusion.get("needs_foreground_mask")),
            "recommended_layers": {
                "V1": "base_video",
                "V2": "editable_caption_text",
                "V3": "foreground_subject_matte_above_caption",
            } if occlusion.get("needs_foreground_mask") else None,
            "mask_bbox": expand_bbox(bbox, frame_w, frame_h, pad_ratio=0.25, min_pad=12) if occlusion.get("needs_foreground_mask") else None,
            "mask_time_range": {"start": event.get("start"), "end": event.get("end")} if occlusion.get("needs_foreground_mask") else None,
            "mask_asset_type": (mask_asset or {}).get("asset_type") if mask_asset else None,
            "mask_asset_pattern": (mask_asset or {}).get("mask_pattern") if mask_asset else None,
            "mask_asset_exists": bool((mask_asset or {}).get("complete")),
            "mask_asset_frame_count": (mask_asset or {}).get("frame_count_written") if mask_asset else 0,
        },
        "renderer_hints": {
            "preferred_layer_type": "foreground_matte_composite" if occlusion.get("needs_foreground_mask") else "normal_text_overlay",
            "resolve_target": "V4 foreground matte above V3 TextPlus" if occlusion.get("needs_foreground_mask") else "TextPlus only",
            "fcpxml_target": "foreground alpha-mask PNG sequence asset" if bool((mask_asset or {}).get("complete")) else ("metadata_marker_or_placeholder" if occlusion.get("needs_foreground_mask") else "none"),
            "openreel_target": "foreground_mask_layer" if occlusion.get("needs_foreground_mask") else "text_layer",
        },
    }
    if debug_paths:
        result["debug_frames"] = debug_paths
    return result


def summarize_results(results: List[Dict[str, Any]], normalized_info: Dict[str, Any]) -> Dict[str, Any]:
    analyzed = [r for r in results if not r.get("skipped")]
    occluded = [r for r in analyzed if get_nested(r, ["occlusion", "detected"], False)]
    mask_needed = [r for r in analyzed if get_nested(r, ["occlusion", "needs_foreground_mask"], False)]
    inferred = [r for r in analyzed if r.get("source") == "inferred_transcript_cue"]
    mask_assets_requested = [r for r in analyzed if isinstance(r.get("mask_asset"), dict) and r.get("mask_asset", {}).get("requested")]
    mask_assets_complete = [r for r in mask_assets_requested if bool(r.get("mask_asset", {}).get("complete"))]
    mask_assets_incomplete = [r for r in mask_assets_requested if not bool(r.get("mask_asset", {}).get("complete"))]
    mask_frames_written = sum(safe_int(r.get("mask_asset", {}).get("frame_count_written"), 0) for r in mask_assets_requested)
    mask_backend_counts: Dict[str, int] = {}
    for r in mask_assets_requested:
        for backend, count in (r.get("mask_asset", {}).get("backend_counts") or {}).items():
            mask_backend_counts[str(backend)] = mask_backend_counts.get(str(backend), 0) + int(count)
    backend_counts: Dict[str, int] = {}
    for r in analyzed:
        for backend, count in (get_nested(r, ["foreground", "backend_counts"], {}) or {}).items():
            backend_counts[str(backend)] = backend_counts.get(str(backend), 0) + int(count)
    labels: Dict[str, int] = {}
    for r in analyzed:
        label = str(get_nested(r, ["occlusion", "label"], "unknown"))
        labels[label] = labels.get(label, 0) + 1
    return {
        "events_input_count": normalized_info.get("normalized_event_count", len(results)),
        "events_analyzed_count": len(analyzed),
        "events_skipped_count": len(results) - len(analyzed),
        "occluded_count": len(occluded),
        "needs_foreground_mask_count": len(mask_needed),
        "inferred_transcript_event_count": len(inferred),
        "raw_style_event_count": normalized_info.get("raw_style_event_count"),
        "style_events_with_bbox_count": normalized_info.get("style_events_with_bbox_count"),
        "style_events_missing_bbox_count": normalized_info.get("style_events_missing_bbox_count"),
        "normalized_from_style_event_count": normalized_info.get("normalized_from_style_event_count"),
        "normalized_from_inferred_transcript_count": normalized_info.get("normalized_from_inferred_transcript_count"),
        "bbox_schema_paths_seen": normalized_info.get("bbox_schema_paths_seen", {}),
        "backend_sample_counts": backend_counts,
        "mask_asset_backend_counts": mask_backend_counts,
        "mask_assets_requested_count": len(mask_assets_requested),
        "mask_assets_complete_count": len(mask_assets_complete),
        "mask_assets_incomplete_count": len(mask_assets_incomplete),
        "mask_frames_written": mask_frames_written,
        "mask_assets_ready": len(mask_assets_requested) > 0 and len(mask_assets_incomplete) == 0,
        "occlusion_label_counts": labels,
        "editor_ready_matte_count": sum(
            1 for result in analyzed
            if bool(get_nested(result, ["occlusion", "ready_for_editor_compositing"], False))
            and bool((result.get("mask_asset") or {}).get("complete"))
        ),
        "editor_excluded_event_count": sum(
            1 for result in analyzed if bool(result.get("exclude_from_caption_occlusion_editor"))
        ),
        "non_caption_graphic_count": sum(
            1 for result in analyzed if result.get("editor_event_type") == "non_caption_graphic"
        ),
        "aggregate_caption_window_count": sum(
            1 for result in analyzed if result.get("editor_event_type") == "aggregate_caption_window"
        ),
        "unresolved_caption_event_count": sum(
            1 for result in analyzed if result.get("editor_event_type") == "unresolved_caption_event"
        ),
        "ready_for_merge_analysis": bool(
            any(
                bool(get_nested(result, ["occlusion", "ready_for_editor_compositing"], False))
                and bool((result.get("mask_asset") or {}).get("complete"))
                for result in analyzed
            )
            and len(mask_assets_incomplete) == 0
            and not any(
                bool(get_nested(result, ["occlusion", "needs_foreground_mask"], False))
                and not bool(get_nested(result, ["occlusion", "ready_for_editor_compositing"], False))
                for result in analyzed
            )
        ),
        "ready_for_editor_compilers": bool(
            any(
                bool(get_nested(result, ["occlusion", "ready_for_editor_compositing"], False))
                and bool((result.get("mask_asset") or {}).get("complete"))
                for result in analyzed
            )
            and len(mask_assets_incomplete) == 0
            and not any(
                bool(get_nested(result, ["occlusion", "needs_foreground_mask"], False))
                and not bool(get_nested(result, ["occlusion", "ready_for_editor_compositing"], False))
                for result in analyzed
            )
        ),
    }



def validate_debug_artifacts(
    results: List[Dict[str, Any]],
    debug_dir: str,
    write_debug_frames: bool,
    debug_max_frames: int,
) -> Dict[str, Any]:
    """Validate that debug images cover all successful event samples.

    The old global debug cap wrote only the first N samples, which made a 40-frame
    run appear to stop near the third second. A debug_max_frames value of 0 is
    explicitly unlimited. This validator records both logical coverage and actual
    file readability so downstream testing can distinguish a complete debug run
    from a capped or damaged one.
    """
    planned_sample_count = 0
    successful_sample_count = 0
    failed_sample_count = 0
    referenced_path_count = 0
    skipped_due_limit_count = 0
    existing_file_count = 0
    readable_file_count = 0
    unreadable_files: List[str] = []
    missing_files: List[str] = []
    successful_without_debug: List[Dict[str, Any]] = []
    debug_timestamps: List[float] = []
    successful_event_indexes = set()
    debug_event_indexes = set()

    for event in results:
        event_index = safe_int(event.get("index"), 0)
        samples = event.get("samples") if isinstance(event.get("samples"), list) else []
        planned_sample_count += len(samples)
        event_has_success = False
        event_has_debug = False

        for sample_index, sample in enumerate(samples, start=1):
            if not isinstance(sample, dict):
                failed_sample_count += 1
                continue
            if not bool(sample.get("ok")):
                failed_sample_count += 1
                continue

            successful_sample_count += 1
            event_has_success = True
            ts = safe_float(sample.get("timestamp"), -1.0)
            debug_path = sample.get("debug_frame")
            if debug_path:
                referenced_path_count += 1
                event_has_debug = True
                if ts >= 0:
                    debug_timestamps.append(ts)
                path_str = str(debug_path)
                if os.path.exists(path_str):
                    existing_file_count += 1
                    image = cv2.imread(path_str, cv2.IMREAD_COLOR)
                    if image is not None and image.size > 0:
                        readable_file_count += 1
                    else:
                        unreadable_files.append(path_str)
                else:
                    missing_files.append(path_str)
            else:
                if sample.get("debug_frame_skipped") == "debug_max_frames_reached":
                    skipped_due_limit_count += 1
                successful_without_debug.append({
                    "event_index": event_index,
                    "sample_index": sample_index,
                    "timestamp": round(ts, 4) if ts >= 0 else None,
                    "reason": sample.get("debug_frame_skipped") or "missing_debug_frame_reference",
                })

        if event_has_success:
            successful_event_indexes.add(event_index)
        if event_has_debug:
            debug_event_indexes.add(event_index)

    actual_dir_file_count = 0
    if debug_dir and os.path.isdir(debug_dir):
        try:
            actual_dir_file_count = sum(
                1
                for name in os.listdir(debug_dir)
                if name.lower().endswith((".jpg", ".jpeg", ".png"))
                and os.path.isfile(os.path.join(debug_dir, name))
            )
        except Exception:
            actual_dir_file_count = 0

    full_sample_coverage = (
        write_debug_frames
        and successful_sample_count > 0
        and referenced_path_count == successful_sample_count
        and skipped_due_limit_count == 0
    )
    full_event_coverage = (
        bool(successful_event_indexes)
        and debug_event_indexes == successful_event_indexes
    )
    files_intact = (
        referenced_path_count == existing_file_count == readable_file_count
        and not missing_files
        and not unreadable_files
    )
    complete = bool(full_sample_coverage and full_event_coverage and files_intact)

    earliest = min(debug_timestamps) if debug_timestamps else None
    latest = max(debug_timestamps) if debug_timestamps else None

    reasons: List[str] = []
    if not write_debug_frames:
        reasons.append("write_debug_frames_disabled")
    if debug_max_frames > 0 and skipped_due_limit_count > 0:
        reasons.append("global_debug_frame_cap_reached")
    if referenced_path_count != successful_sample_count:
        reasons.append("not_every_successful_sample_has_debug_frame")
    if debug_event_indexes != successful_event_indexes:
        reasons.append("not_every_successful_event_has_debug_coverage")
    if missing_files:
        reasons.append("referenced_debug_files_missing")
    if unreadable_files:
        reasons.append("debug_files_unreadable")

    return {
        "enabled": bool(write_debug_frames),
        "debug_max_frames": int(debug_max_frames),
        "debug_max_frames_semantics": "0=unlimited",
        "planned_sample_count": int(planned_sample_count),
        "successful_sample_count": int(successful_sample_count),
        "failed_sample_count": int(failed_sample_count),
        "referenced_path_count": int(referenced_path_count),
        "skipped_due_limit_count": int(skipped_due_limit_count),
        "existing_file_count": int(existing_file_count),
        "readable_file_count": int(readable_file_count),
        "actual_debug_directory_image_count": int(actual_dir_file_count),
        "successful_event_count": len(successful_event_indexes),
        "events_with_debug_count": len(debug_event_indexes),
        "first_debug_timestamp": round(float(earliest), 4) if earliest is not None else None,
        "last_debug_timestamp": round(float(latest), 4) if latest is not None else None,
        "full_sample_coverage": bool(full_sample_coverage),
        "full_event_coverage": bool(full_event_coverage),
        "files_intact": bool(files_intact),
        "complete": bool(complete),
        "reasons": reasons,
        "missing_files_sample": missing_files[:20],
        "unreadable_files_sample": unreadable_files[:20],
        "samples_without_debug_sample": successful_without_debug[:20],
    }


# -----------------------------------------------------------------------------
# Classification audit artifacts
# -----------------------------------------------------------------------------


def _audit_rel_or_uri(path: Any, html_path: Path) -> str:
    if not path:
        return ""
    try:
        p = Path(str(path)).resolve()
        try:
            return os.path.relpath(str(p), str(html_path.parent)).replace("\\", "/")
        except Exception:
            return p.as_uri()
    except Exception:
        return str(path)


def build_event_audit_row(event: Dict[str, Any]) -> Dict[str, Any]:
    occ = event.get("occlusion") if isinstance(event.get("occlusion"), dict) else {}
    return {
        "index": safe_int(event.get("index"), 0),
        "cue_id": clean_text(event.get("cue_id")),
        "original_cue_id": clean_text(event.get("original_cue_id")),
        "cue_id_valid": is_stable_sub_cue_id(event.get("cue_id")),
        "cue_mapping_status": get_nested(event, ["cue_mapping", "status"], None),
        "related_cue_ids": list(event.get("related_cue_ids") or []),
        "editor_event_type": event.get("editor_event_type"),
        "editor_excluded": bool(event.get("exclude_from_caption_occlusion_editor")),
        "text": clean_text(event.get("text")),
        "start": safe_float(event.get("start"), 0.0),
        "end": safe_float(event.get("end"), 0.0),
        "label": occ.get("label"),
        "layer_order": occ.get("layer_order"),
        "needs_foreground_mask": bool(occ.get("needs_foreground_mask")),
        "review_required": bool(occ.get("review_required")),
        "ready_for_editor_compositing": bool(occ.get("ready_for_editor_compositing")),
        "classification_confidence": occ.get("classification_confidence"),
        "max_exact_overlap": occ.get("max_exact_foreground_overlap"),
        "median_exact_overlap": occ.get("median_exact_foreground_overlap"),
        "max_expanded_overlap": occ.get("max_foreground_overlap"),
        "median_expanded_overlap": occ.get("median_foreground_overlap"),
        "median_front_score": occ.get("median_front_score"),
        "median_behind_score": occ.get("median_behind_score"),
        "median_raw_front_score": occ.get("median_raw_front_score"),
        "median_raw_behind_score": occ.get("median_raw_behind_score"),
        "raw_front_signal_votes": occ.get("raw_front_signal_vote_count"),
        "strict_behind_signal_votes": occ.get("strict_behind_signal_vote_count"),
        "front_votes": occ.get("front_vote_count"),
        "behind_votes": occ.get("behind_vote_count"),
        "reliable_samples": occ.get("reliable_layer_evidence_samples"),
        "reason": occ.get("reason"),
        "legacy_label": get_nested(occ, ["legacy_v1_7_decision", "label"], None),
        "legacy_needs_foreground_mask": bool(get_nested(occ, ["legacy_v1_7_decision", "needs_foreground_mask"], False)),
        "legacy_likely_text_in_front": bool(get_nested(occ, ["legacy_v1_7_decision", "likely_text_in_front"], False)),
        "debug_frames": list(event.get("debug_frames") or []),
        "mask_complete": bool((event.get("mask_asset") or {}).get("complete")),
        "mask_pattern": (event.get("mask_asset") or {}).get("mask_pattern"),
    }


def write_classification_audit(results: List[Dict[str, Any]], audit_dir: str, clear: bool, encoding: str = "utf-8") -> Dict[str, Any]:
    root = Path(audit_dir).resolve()
    if clear and root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    event_sheet_dir = root / "event_sheets"
    event_sheet_dir.mkdir(parents=True, exist_ok=True)

    rows = [build_event_audit_row(event) for event in results if not event.get("skipped")]
    counts: Dict[str, int] = {}
    layer_counts: Dict[str, int] = {}
    for row in rows:
        counts[str(row.get("label") or "unknown")] = counts.get(str(row.get("label") or "unknown"), 0) + 1
        layer_counts[str(row.get("layer_order") or "unknown")] = layer_counts.get(str(row.get("layer_order") or "unknown"), 0) + 1

    json_path = root / "classification_audit.json"
    csv_path = root / "classification_audit.csv"
    html_path = root / "classification_audit.html"
    write_json(str(json_path), {
        "schema": "video_cloner_caption_occlusion_classification_audit",
        "schema_version": "1.0",
        "analysis_version": ANALYSIS_VERSION,
        "event_count": len(rows),
        "label_counts": counts,
        "layer_order_counts": layer_counts,
        "review_required_count": sum(1 for r in rows if r.get("review_required")),
        "editor_ready_matte_count": sum(1 for r in rows if r.get("ready_for_editor_compositing")),
        "invalid_cue_id_count": sum(
            1 for r in rows if not r.get("cue_id_valid") and not r.get("editor_excluded")
        ),
        "excluded_event_count": sum(1 for r in rows if r.get("editor_excluded")),
        "non_caption_graphic_count": sum(1 for r in rows if r.get("editor_event_type") == "non_caption_graphic"),
        "aggregate_caption_window_count": sum(1 for r in rows if r.get("editor_event_type") == "aggregate_caption_window"),
        "events": rows,
    }, encoding=encoding)

    csv_fields = [k for k in rows[0].keys() if k not in {"debug_frames", "related_cue_ids"}] if rows else []
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k) for k in csv_fields})

    # Build one three-sample contact sheet per event.
    created_sheets: List[str] = []
    for row in rows:
        images: List[np.ndarray] = []
        for path in row.get("debug_frames") or []:
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is not None and image.size:
                images.append(image)
        if not images:
            continue
        thumb_w, thumb_h = 304, 540
        resized = [cv2.resize(img, (thumb_w, thumb_h), interpolation=cv2.INTER_AREA) for img in images[:3]]
        while len(resized) < 3:
            resized.append(np.zeros((thumb_h, thumb_w, 3), dtype=np.uint8))
        header_h = 92
        canvas = np.zeros((header_h + thumb_h, thumb_w * 3, 3), dtype=np.uint8)
        title = f"#{row['index']:04d} {row['cue_id']} {row['text'][:48]}"
        decision = f"{row['label']} | {row['layer_order']} | mask={row['needs_foreground_mask']} | review={row['review_required']}"
        metrics = f"exact={row['median_exact_overlap']} front={row['median_front_score']} behind={row['median_behind_score']} conf={row['classification_confidence']}"
        cv2.putText(canvas, title, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (240, 240, 240), 2, cv2.LINE_AA)
        cv2.putText(canvas, decision, (12, 56), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 220, 255), 2, cv2.LINE_AA)
        cv2.putText(canvas, metrics, (12, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (190, 190, 190), 1, cv2.LINE_AA)
        for i, img in enumerate(resized):
            canvas[header_h:header_h + thumb_h, i * thumb_w:(i + 1) * thumb_w] = img
        sheet_path = event_sheet_dir / f"event_{row['index']:04d}.jpg"
        if cv2.imwrite(str(sheet_path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 90]):
            row["event_sheet"] = str(sheet_path)
            created_sheets.append(str(sheet_path))

    css = """
    body{font-family:Arial,sans-serif;background:#111;color:#eee;margin:20px} table{border-collapse:collapse;width:100%}
    th,td{border:1px solid #444;padding:7px;vertical-align:top} th{background:#222;position:sticky;top:0}
    tr.review{background:#3b2d10} tr.front{background:#123024} tr.behind{background:#301515} tr.excluded{background:#202833}
    img{max-width:520px;height:auto}.muted{color:#aaa}.yes{font-weight:bold;color:#ffbd4a}.good{color:#76e38b}
    """
    html_rows: List[str] = []
    for row in rows:
        cls = "excluded" if row.get("editor_excluded") else ("review" if row.get("review_required") else ("behind" if row.get("layer_order") == "foreground_over_text" else "front" if row.get("layer_order") == "text_over_foreground" else ""))
        sheet = _audit_rel_or_uri(row.get("event_sheet"), html_path)
        image_html = f'<a href="{html.escape(sheet)}"><img src="{html.escape(sheet)}"></a>' if sheet else ""
        html_rows.append(
            f'<tr class="{cls}"><td>{row["index"]}</td><td>{html.escape(str(row["cue_id"]))}<br>'
            f'<span class="muted">{html.escape(str(row.get("editor_event_type") or ""))}</span><br>'
            f'<span class="muted">map={html.escape(str(row.get("cue_mapping_status") or ""))}</span></td>'
            f'<td>{html.escape(str(row["text"]))}<br><span class="muted">{row["start"]:.3f}-{row["end"]:.3f}s</span></td>'
            f'<td>{html.escape(str(row["label"]))}<br>{html.escape(str(row["layer_order"]))}<br>'
            f'mask={row["needs_foreground_mask"]}<br>review={row["review_required"]}</td>'
            f'<td>exact med/max={row["median_exact_overlap"]}/{row["max_exact_overlap"]}<br>'
            f'front={row["median_front_score"]} behind={row["median_behind_score"]}<br>'
            f'votes F/B={row["front_votes"]}/{row["behind_votes"]}<br>conf={row["classification_confidence"]}</td>'
            f'<td>{html.escape(str(row["reason"]))}</td><td>{image_html}</td></tr>'
        )
    html_doc = f"""<!doctype html><html><head><meta charset="utf-8"><title>Caption Occlusion Classification Audit</title><style>{css}</style></head>
    <body><h1>Caption Occlusion Classification Audit</h1>
    <p>Version: {html.escape(ANALYSIS_VERSION)} | Events: {len(rows)} | Labels: {html.escape(str(counts))} | Layer orders: {html.escape(str(layer_counts))}</p>
    <p>Yellow rows require review. Red rows request a foreground matte. Green rows are text-over-subject. Blue/gray rows are graphics or aggregate transcript windows excluded from caption V4.</p>
    <table><thead><tr><th>#</th><th>Cue</th><th>Text/time</th><th>Decision</th><th>Metrics</th><th>Reason</th><th>3-sample sheet</th></tr></thead>
    <tbody>{''.join(html_rows)}</tbody></table></body></html>"""
    html_path.write_text(html_doc, encoding="utf-8")

    logical_conflicts = [
        row for row in rows
        if not row.get("editor_excluded") and (
            (row.get("needs_foreground_mask") and row.get("layer_order") != "foreground_over_text")
            or (row.get("layer_order") == "text_over_foreground" and row.get("needs_foreground_mask"))
            or (row.get("ready_for_editor_compositing") and (not row.get("cue_id_valid") or row.get("review_required")))
        )
    ]

    return {
        "enabled": True,
        "root": str(root),
        "json": str(json_path),
        "csv": str(csv_path),
        "html": str(html_path),
        "event_sheet_dir": str(event_sheet_dir),
        "event_sheet_count": len(created_sheets),
        "event_count": len(rows),
        "label_counts": counts,
        "layer_order_counts": layer_counts,
        "review_required_count": sum(1 for r in rows if r.get("review_required")),
        "editor_ready_matte_count": sum(1 for r in rows if r.get("ready_for_editor_compositing")),
        "invalid_cue_id_count": sum(
            1 for r in rows if not r.get("cue_id_valid") and not r.get("editor_excluded")
        ),
        "excluded_event_count": sum(1 for r in rows if r.get("editor_excluded")),
        "non_caption_graphic_count": sum(1 for r in rows if r.get("editor_event_type") == "non_caption_graphic"),
        "aggregate_caption_window_count": sum(1 for r in rows if r.get("editor_event_type") == "aggregate_caption_window"),
        "logical_conflict_count": len(logical_conflicts),
        "logical_conflicts_sample": logical_conflicts[:20],
        "complete": len(created_sheets) == len(rows) and not logical_conflicts,
    }


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Detect caption foreground occlusion / text-behind-subject candidates.")
    p.add_argument("--video", required=True, help="Video used for segmentation/mask export. May be a proxy; caption boxes are reconciled through normalized coordinates.")
    p.add_argument("--caption-style", required=True, help="Path to *_caption_style.json from detect_caption_style.py")
    p.add_argument("--transcript", default=None, help="Optional transcript JSON path. Recommended for inferred OCR-missed caption windows.")
    p.add_argument("--output", required=True, help="Output *_caption_occlusion.json path")
    p.add_argument("--debug-dir", default=None, help="Debug frame directory")
    p.add_argument("--write-mask-assets", type=str2bool, default=False, help="Export full-frame per-frame foreground alpha-mask PNG sequences")
    p.add_argument("--mask-output-dir", default=None, help="Root directory for exported mask sequences. Default: <output_dir>/foreground_masks")
    p.add_argument("--clear-mask-assets", type=str2bool, default=True, help="Clear the mask output root before a run")
    p.add_argument("--clear-mask-assets-per-event", type=str2bool, default=True, help="Clear each event directory before writing its sequence")
    p.add_argument("--mask-assets-only-needed", type=str2bool, default=True, help="Export masks only for events classified as needs_foreground_mask")
    p.add_argument("--mask-stop-on-first-failure", type=str2bool, default=True, help="Stop an event mask sequence after its first failed frame")
    p.add_argument("--mask-progress-every", type=int, default=25, help="Print mask export progress every N written frames. 0 = disabled")
    p.add_argument("--backend", default="auto_gpu", choices=["auto", "auto_gpu", "paddle", "paddle_humanseg", "paddlehub_humanseg", "mediapipe", "mediapipe_selfie", "grabcut", "heuristic"], help="Foreground segmentation backend")
    p.add_argument("--segmentation-device", default="auto", choices=["auto", "gpu", "cpu", "cuda", "gpu:0"], help="Device for Paddle segmentation backend")
    p.add_argument("--paddle-gpu-id", type=int, default=0, help="GPU id for Paddle segmentation backend")
    p.add_argument("--paddle-hub-module", default="humanseg_lite", help="PaddleHub human segmentation module name")
    p.add_argument("--paddle-seg-threshold", type=float, default=0.50, help="Threshold for Paddle humanseg alpha/probability mask")
    p.add_argument("--enable-grabcut-fallback", type=str2bool, default=False, help="Allow CPU-heavy GrabCut fallback in auto_gpu/paddle modes")
    p.add_argument("--require-paddle-gpu", type=str2bool, default=False, help="Fail fast if Paddle humanseg cannot initialize on GPU")
    p.add_argument("--samples-per-event", type=int, default=5, help="Adjacent samples per caption event. Recommended 3-7.")
    p.add_argument("--sample-window-sec", type=float, default=0.22, help="Local time window around each cue mid for adjacent sampling")
    p.add_argument("--max-events", type=int, default=0, help="Limit analyzed events. 0 = no limit")
    p.add_argument("--include-inferred-transcript-cues", type=str2bool, default=True, help="Create estimated caption windows for transcript cues that OCR/style events missed")
    p.add_argument("--include-word-inferred-cues", type=str2bool, default=False, help="Also infer occlusion windows from word-level transcript cues. Default false prevents huge CPU runs.")
    p.add_argument("--max-inferred-events", type=int, default=40, help="Maximum inferred transcript events to add. Prevents runaway transcript-word analysis.")
    p.add_argument("--max-total-samples", type=int, default=220, help="Soft cap for total segmentation samples. If events*samples is higher, samples-per-event is reduced automatically.")
    p.add_argument("--time-budget-sec", type=float, default=240.0, help="Stop gracefully after this many seconds and write a partial report. 0 = no time budget.")
    p.add_argument("--occlusion-threshold", type=float, default=0.42, help="Minimum occlusion score for detected=true")
    p.add_argument("--mask-overlap-threshold", type=float, default=0.18, help="Minimum foreground overlap required for foreground mask recommendation")
    p.add_argument("--segmentation-max-side", type=int, default=720, help="Max side for GrabCut segmentation before upscaling mask")
    p.add_argument("--write-debug-frames", type=str2bool, default=True, help="Write debug frames with foreground mask overlay")
    p.add_argument("--debug-max-frames", type=int, default=80, help="Maximum debug frames to write across the whole run. 0 = unlimited/full event coverage.")
    p.add_argument("--progress-every", type=int, default=10, help="Print progress every N analyzed events. 0 = disabled.")
    p.add_argument("--clear-debug", type=str2bool, default=True, help="Clear debug dir before writing")
    p.add_argument("--write-classification-audit", type=str2bool, default=True, help="Write JSON/CSV/HTML and three-sample event sheets for all classification decisions")
    p.add_argument("--classification-audit-dir", default=None, help="Classification audit output directory. Default: <output_dir>/caption_occlusion_audit")
    p.add_argument("--clear-classification-audit", type=str2bool, default=True, help="Clear the classification audit directory before writing")
    p.add_argument("--encoding", default="utf-8", choices=["utf-8", "utf-8-sig"])
    return p


def main(argv: Optional[List[str]] = None) -> int:
    started = now_unix()
    args = build_arg_parser().parse_args(argv)

    report: Dict[str, Any] = {
        "success": False,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "started_at_unix": started,
        "inputs": {
            "video": args.video,
            "caption_style": args.caption_style,
            "transcript": args.transcript,
            "output": args.output,
            "debug_dir": args.debug_dir,
            "mask_output_dir": args.mask_output_dir,
        },
        "config": {
            "backend": args.backend,
            "segmentation_device": args.segmentation_device,
            "paddle_gpu_id": args.paddle_gpu_id,
            "paddle_hub_module": args.paddle_hub_module,
            "paddle_seg_threshold": args.paddle_seg_threshold,
            "enable_grabcut_fallback": bool(args.enable_grabcut_fallback),
            "require_paddle_gpu": bool(args.require_paddle_gpu),
            "samples_per_event": args.samples_per_event,
            "sample_window_sec": args.sample_window_sec,
            "max_events": args.max_events,
            "include_inferred_transcript_cues": bool(args.include_inferred_transcript_cues),
            "include_word_inferred_cues": bool(args.include_word_inferred_cues),
            "max_inferred_events": args.max_inferred_events,
            "max_total_samples": args.max_total_samples,
            "time_budget_sec": args.time_budget_sec,
            "occlusion_threshold": args.occlusion_threshold,
            "mask_overlap_threshold": args.mask_overlap_threshold,
            "segmentation_max_side": args.segmentation_max_side,
            "write_debug_frames": bool(args.write_debug_frames),
            "debug_max_frames": args.debug_max_frames,
            "write_classification_audit": bool(args.write_classification_audit),
            "classification_audit_dir": args.classification_audit_dir,
            "progress_every": args.progress_every,
            "write_mask_assets": bool(args.write_mask_assets),
            "mask_output_dir": args.mask_output_dir,
            "clear_mask_assets": bool(args.clear_mask_assets),
            "clear_mask_assets_per_event": bool(args.clear_mask_assets_per_event),
            "mask_assets_only_needed": bool(args.mask_assets_only_needed),
            "mask_stop_on_first_failure": bool(args.mask_stop_on_first_failure),
            "mask_progress_every": int(args.mask_progress_every),
        },
        "errors": [],
        "warnings": [],
    }

    try:
        video_path = str(args.video)
        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video not found: {video_path}")
        if not os.path.exists(args.caption_style):
            raise FileNotFoundError(f"Caption style JSON not found: {args.caption_style}")

        video_info = read_video_info(video_path)
        report["video_info"] = video_info
        if not video_info.get("opened"):
            raise RuntimeError(f"Could not open video: {video_path}")
        frame_w = safe_int(video_info.get("width"), 0)
        frame_h = safe_int(video_info.get("height"), 0)
        fps = safe_float(video_info.get("fps"), 24.0) or 24.0
        duration = safe_float(video_info.get("duration_seconds"), 0.0)
        if frame_w <= 0 or frame_h <= 0 or duration <= 0:
            raise RuntimeError("Invalid video info; width/height/duration are required.")

        caption_style = load_json(args.caption_style)
        transcript = load_json(args.transcript) if args.transcript and os.path.exists(args.transcript) else {}
        transcript_cues = extract_transcript_cues(transcript) if transcript else []
        if args.transcript and not transcript:
            report["warnings"].append("--transcript was provided but could not be loaded or did not exist; inferred missing captions will be weaker.")

        events, normalized_info = normalize_caption_events(
            style_data=caption_style,
            transcript_cues=transcript_cues,
            frame_w=frame_w,
            frame_h=frame_h,
            include_inferred=bool(args.include_inferred_transcript_cues),
            max_inferred_events=max(0, int(args.max_inferred_events)),
            include_word_inferred_cues=bool(args.include_word_inferred_cues),
        )
        for warning in normalized_info.get("warnings", []) or []:
            report["warnings"].append(str(warning))
        if args.max_events and args.max_events > 0:
            events = events[: int(args.max_events)]

        requested_samples_per_event = max(1, int(args.samples_per_event))
        effective_samples_per_event = requested_samples_per_event
        max_total_samples = max(0, int(args.max_total_samples))
        planned_samples = len(events) * requested_samples_per_event
        if max_total_samples > 0 and planned_samples > max_total_samples and events:
            effective_samples_per_event = max(1, int(max_total_samples // max(1, len(events))))
            if effective_samples_per_event < requested_samples_per_event:
                report["warnings"].append(
                    f"Reduced samples_per_event from {requested_samples_per_event} to {effective_samples_per_event} "
                    f"because planned segmentation samples ({planned_samples}) exceeded --max-total-samples ({max_total_samples})."
                )
                args.samples_per_event = effective_samples_per_event

        report["performance_plan"] = {
            "events_to_analyze": len(events),
            "requested_samples_per_event": requested_samples_per_event,
            "effective_samples_per_event": int(args.samples_per_event),
            "planned_segmentation_samples": len(events) * int(args.samples_per_event),
            "debug_max_frames": int(args.debug_max_frames),
        }

        debug_dir = args.debug_dir or str((Path(args.output).parent / "debug_caption_occlusion").resolve())
        args.debug_dir = debug_dir
        if args.write_debug_frames and args.clear_debug and os.path.exists(debug_dir):
            shutil.rmtree(debug_dir, ignore_errors=True)

        mask_output_dir = args.mask_output_dir or str((Path(args.output).parent / "foreground_masks").resolve())
        args.mask_output_dir = mask_output_dir
        report["inputs"]["mask_output_dir"] = mask_output_dir
        report["config"]["mask_output_dir"] = mask_output_dir
        if bool(args.write_mask_assets) and bool(args.clear_mask_assets) and os.path.exists(mask_output_dir):
            shutil.rmtree(mask_output_dir, ignore_errors=True)
        if bool(args.write_mask_assets):
            os.makedirs(mask_output_dir, exist_ok=True)

        segmenter = ForegroundSegmenter(
            backend=args.backend,
            max_side=args.segmentation_max_side,
            segmentation_device=args.segmentation_device,
            paddle_gpu_id=args.paddle_gpu_id,
            paddle_hub_module=args.paddle_hub_module,
            paddle_seg_threshold=args.paddle_seg_threshold,
            enable_grabcut_fallback=bool(args.enable_grabcut_fallback),
        )

        if bool(args.require_paddle_gpu):
            paddle_runtime = segmenter._setup_paddle_runtime()
            selected = str(paddle_runtime.get("device_selected") or "")
            if not paddle_runtime.get("available") or not selected.startswith("gpu"):
                raise RuntimeError(
                    "--require-paddle-gpu was set, but Paddle humanseg did not initialize on GPU. "
                    f"runtime={paddle_runtime}"
                )

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video for frame reads: {video_path}")

        results: List[Dict[str, Any]] = []
        partial_stop_reason = None
        setattr(args, "_debug_frames_written", 0)
        setattr(args, "_mask_frames_written", 0)

        for idx, event in enumerate(events, start=1):
            if args.time_budget_sec and args.time_budget_sec > 0 and (time.time() - started) >= float(args.time_budget_sec):
                partial_stop_reason = f"time_budget_sec_reached_{args.time_budget_sec}"
                report["warnings"].append(f"Stopped early after {idx - 1}/{len(events)} events because --time-budget-sec was reached.")
                break

            results.append(
                analyze_event(
                    event=event,
                    event_index=idx,
                    cap=cap,
                    video_duration=duration,
                    segmenter=segmenter,
                    args=args,
                    frame_w=frame_w,
                    frame_h=frame_h,
                    fps=fps,
                    frame_count=safe_int(video_info.get("frame_count"), 0),
                )
            )

            if args.progress_every and int(args.progress_every) > 0 and (idx % int(args.progress_every) == 0 or idx == len(events)):
                print(json.dumps({
                    "progress": True,
                    "event": idx,
                    "events_total": len(events),
                    "elapsed_sec": round(time.time() - started, 2),
                    "debug_frames_written": int(getattr(args, "_debug_frames_written", 0)),
                }, ensure_ascii=False), flush=True)

        cap.release()

        summary = summarize_results(results, normalized_info)
        debug_artifacts = validate_debug_artifacts(
            results=results,
            debug_dir=debug_dir,
            write_debug_frames=bool(args.write_debug_frames),
            debug_max_frames=int(args.debug_max_frames),
        )
        if bool(args.write_debug_frames) and not bool(debug_artifacts.get("complete")):
            report["warnings"].append(
                "Debug artifact coverage is incomplete. Use --debug-max-frames 0 for full-video coverage. "
                f"details={debug_artifacts.get('reasons')}"
            )

        audit_dir = args.classification_audit_dir or str((Path(args.output).parent / "caption_occlusion_audit").resolve())
        classification_audit = {"enabled": False}
        if bool(args.write_classification_audit):
            classification_audit = write_classification_audit(
                results=results,
                audit_dir=audit_dir,
                clear=bool(args.clear_classification_audit),
                encoding=args.encoding,
            )
            if not bool(classification_audit.get("complete")):
                report["warnings"].append("Classification audit contact sheets are incomplete.")

        # Strict GPU validation. The previous check only proves that Paddle can
        # initialize on gpu:0. This check proves that the actual samples used
        # Paddle human segmentation and did not silently fall back to heuristic.
        if bool(args.require_paddle_gpu):
            backend_sample_counts = summary.get("backend_sample_counts") or {}
            mask_backend_counts = summary.get("mask_asset_backend_counts") or {}
            combined_backend_counts: Dict[str, int] = {}
            for source_counts in (backend_sample_counts, mask_backend_counts):
                for backend, count in source_counts.items():
                    combined_backend_counts[str(backend)] = combined_backend_counts.get(str(backend), 0) + int(count)
            total_backend_samples = sum(int(v) for v in combined_backend_counts.values())
            paddle_samples = int(combined_backend_counts.get("paddle_humanseg", 0))
            non_paddle_counts = {
                str(k): int(v)
                for k, v in combined_backend_counts.items()
                if str(k) != "paddle_humanseg" and int(v) > 0
            }

            if total_backend_samples <= 0:
                raise RuntimeError(
                    "--require-paddle-gpu was set, but no segmentation samples were completed."
                )

            if paddle_samples <= 0:
                raise RuntimeError(
                    "--require-paddle-gpu was set, but zero samples used paddle_humanseg. "
                    f"backend_sample_counts={combined_backend_counts}"
                )

            if non_paddle_counts:
                raise RuntimeError(
                    "--require-paddle-gpu was set, but some samples used fallback backends. "
                    f"paddle_humanseg={paddle_samples}, fallback_counts={non_paddle_counts}"
                )

        report.update({
            "success": True,
            "ok": True,
            "fps": fps,
            "duration_seconds": round(duration, 4),
            "caption_style_analysis_version": caption_style.get("analysis_version"),
            "transcript": {
                "path": args.transcript,
                "available": bool(transcript),
                "cues_count": len(transcript_cues),
            },
            "normalization": normalized_info,
            "summary": summary,
            "segmentation_runtime": getattr(segmenter, "_paddle_runtime", {}),
            "partial": {
                "stopped_early": bool(partial_stop_reason),
                "reason": partial_stop_reason,
                "events_planned": len(events),
                "events_completed": len(results),
            },
            "occlusion_events": results,
            "debug": {
                "debug_dir": debug_dir,
                "frames_written": int(getattr(args, "_debug_frames_written", 0)),
                "max_frames": int(args.debug_max_frames),
            },
            "debug_artifacts": debug_artifacts,
            "classification_audit": classification_audit,
            "mask_assets": {
                "enabled": bool(args.write_mask_assets),
                "root": mask_output_dir,
                "frames_written": int(getattr(args, "_mask_frames_written", 0)),
                "events_requested": summary.get("mask_assets_requested_count"),
                "events_complete": summary.get("mask_assets_complete_count"),
                "events_incomplete": summary.get("mask_assets_incomplete_count"),
                "ready": summary.get("mask_assets_ready"),
            },
            "finished_at_unix": now_unix(),
            "runtime_sec": round(now_unix() - started, 3),
        })

        write_json(args.output, report, encoding=args.encoding)
        print(json.dumps({
            "success": True,
            "output": args.output,
            "events": len(results),
            "needs_foreground_mask_count": summary.get("needs_foreground_mask_count"),
            "raw_style_event_count": normalized_info.get("raw_style_event_count"),
            "style_events_with_bbox_count": normalized_info.get("style_events_with_bbox_count"),
            "style_events_missing_bbox_count": normalized_info.get("style_events_missing_bbox_count"),
            "normalized_from_style_event_count": normalized_info.get("normalized_from_style_event_count"),
            "normalized_from_inferred_transcript_count": normalized_info.get("normalized_from_inferred_transcript_count"),
            "debug_dir": debug_dir,
            "mask_output_dir": mask_output_dir,
            "mask_assets_complete_count": summary.get("mask_assets_complete_count"),
            "mask_assets_incomplete_count": summary.get("mask_assets_incomplete_count"),
            "mask_frames_written": summary.get("mask_frames_written"),
            "debug_frames_written": int(getattr(args, "_debug_frames_written", 0)),
            "debug_full_coverage": debug_artifacts.get("complete"),
            "debug_first_timestamp": debug_artifacts.get("first_debug_timestamp"),
            "debug_last_timestamp": debug_artifacts.get("last_debug_timestamp"),
            "classification_audit_html": classification_audit.get("html"),
            "classification_review_required_count": classification_audit.get("review_required_count"),
            "editor_ready_matte_count": classification_audit.get("editor_ready_matte_count"),
        }, ensure_ascii=False))
        return 0

    except Exception as exc:
        report["success"] = False
        report["ok"] = False
        report["errors"].append({"type": type(exc).__name__, "message": str(exc)})
        report["finished_at_unix"] = now_unix()
        report["runtime_sec"] = round(now_unix() - started, 3)
        try:
            write_json(args.output, report, encoding=args.encoding)
        except Exception:
            pass
        try:
            import traceback
            traceback.print_exc()
        except Exception:
            pass

        print(json.dumps({
            "success": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "output": args.output,
        }, ensure_ascii=False), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
