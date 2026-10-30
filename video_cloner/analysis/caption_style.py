#!/usr/bin/env python3
"""
detect_caption_style.py

Video Cloner caption style detector.

v5.4 changes:
    - Explicit PaddleOCR/Paddle device control with --ocr-device auto|cpu|gpu.
    - Emits OCR runtime diagnostics so n8n can verify gpu:0 instead of silent CPU fallback.

v5.3 changes:
    - Adjacent-frame caption animation tracking.
    - Measures same-cue bbox scale, opacity/brightness, and position motion across 3-7 sampled frames.
    - Detects pop / scale / fade / slide animation hints for downstream Resolve/Fusion keyframing.

v5.2 changes:
    - Transcript-aware viral-caption detection.
    - Uses transcript/subtitle cue timing to distinguish real captions from UI text.
    - Supports center-screen / lower-middle / huge hook captions, not only classic bottom subtitles.
    - Extracts multiple caption style profiles instead of forcing one global style.
    - Emits per-cue caption_style_events so compilers can style each caption differently.
    - Emits backward-compatible summary/caption_style_resolved objects.

Why this layer matters:
    The .srt file only carries timing/text. The product quality comes from style:
    placement, font size/weight, fill, outline, shadow, density, and animation hints.
"""

from __future__ import annotations

import argparse
import difflib
import json
import math
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# IMPORTANT:
# These must be set BEFORE importing PaddleOCR / paddle.
os.environ["FLAGS_use_onednn"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

import cv2
import numpy as np
from paddleocr import PaddleOCR


ANALYSIS_VERSION = "caption_style_v5_5_temporal_authority"
SCHEMA = "video_cloner_caption_style"
SCHEMA_VERSION = "3.3"
OBSERVATION_FLOOR_FPS = 10.0
CONTINUATION_MAX_GAP_SEC = 0.2
CONTINUATION_MIN_IOU = 0.45
CONTINUATION_MAX_CENTER_DISTANCE = 0.06
CONTINUATION_MAX_AREA_RATIO = 2.0
CONTINUATION_MAX_ASPECT_RATIO = 1.6
CONTINUOUS_IDENTITY_MAX_GAP_SEC = 0.6
CONTINUOUS_IDENTITY_MAX_FILL_DISTANCE = 0.15
CONTINUOUS_IDENTITY_MAX_STROKE_DISTANCE = 0.15
CONTINUOUS_IDENTITY_MAX_FONT_HEIGHT_RATIO = 1.5
CONTINUOUS_IDENTITY_MIN_OCR_SIMILARITY = 0.6
CONTINUOUS_IDENTITY_COLOR_DISTANCE_SCALE = math.sqrt(3.0 * (255.0 ** 2))


# -----------------------------
# CLI / generic helpers
# -----------------------------


def str2bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    value = str(value).strip().lower()
    if value in ("yes", "true", "t", "1", "y", "on"):
        return True
    if value in ("no", "false", "f", "0", "n", "off"):
        return False
    raise argparse.ArgumentTypeError(f"Boolean value expected, got: {value}")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(round(float(value)))
    except Exception:
        return default


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def round4(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return round(float(value), 4)
    except Exception:
        return default


def load_json(path: Optional[str]) -> Dict[str, Any]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: str, data: Dict[str, Any]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# -----------------------------
# Text helpers / fuzzy matching
# -----------------------------


def clean_text(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def normalize_match_text(text: Any) -> str:
    text = clean_text(text).lower()
    # Keep letters/numbers/apostrophes. Replace everything else by spaces.
    text = re.sub(r"[^a-z0-9а-яё'’]+", " ", text, flags=re.IGNORECASE)
    text = text.replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def token_set(text: Any) -> set:
    norm = normalize_match_text(text)
    if not norm:
        return set()
    return {t for t in norm.split() if t}


def fuzzy_similarity(a: Any, b: Any) -> float:
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

    # For short OCR phrases, token overlap matters more than full string ratio.
    score = (0.50 * ratio) + (0.35 * overlap) + (0.15 * jaccard)
    return round(float(clamp(score, 0.0, 1.0)), 4)


def words_count(text: Any) -> int:
    return len(normalize_match_text(text).split())


def is_noise_text(text: Any) -> bool:
    text = clean_text(text)
    if len(text) < 2:
        return True
    alnum = sum(ch.isalnum() for ch in text)
    if alnum == 0:
        return True
    if len(text) <= 2 and not re.search(r"[A-Za-zА-Яа-я]", text):
        return True
    return False


def infer_case_style(texts: Sequence[str]) -> str:
    useful = [clean_text(t) for t in texts if clean_text(t)]
    if not useful:
        return "unknown"
    joined = " ".join(useful)
    letters = [ch for ch in joined if ch.isalpha()]
    if not letters:
        return "unknown"
    upper = sum(1 for ch in letters if ch.isupper())
    lower = sum(1 for ch in letters if ch.islower())
    ratio = upper / max(1, upper + lower)
    if ratio > 0.82:
        return "uppercase"
    if ratio < 0.18:
        return "lowercase_or_sentence"
    return "mixed"


# -----------------------------
# Video / frame sampling
# -----------------------------


def read_video_info(video_path: str) -> Dict[str, Any]:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {"path": video_path, "opened": False}
    fps = cap.get(cv2.CAP_PROP_FPS) or None
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = (float(frame_count) / float(fps)) if fps and fps > 0 and frame_count > 0 else None
    cap.release()
    return {
        "path": video_path,
        "opened": True,
        "fps": round(float(fps), 4) if fps else None,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": round(float(duration), 4) if duration is not None else None,
        "aspect_ratio": round(float(width) / float(height), 4) if width and height else None,
        "orientation": "vertical" if height > width else "horizontal" if width > height else "square",
    }


def unique_sorted_timestamps(values: Iterable[float], duration: float, min_gap: float = 0.08) -> List[float]:
    cleaned = []
    for value in values:
        try:
            ts = float(value)
        except Exception:
            continue
        if math.isnan(ts) or math.isinf(ts):
            continue
        ts = clamp(ts, 0.0, max(0.0, duration - 0.03))
        cleaned.append(round(ts, 3))
    cleaned = sorted(set(cleaned))
    final: List[float] = []
    for ts in cleaned:
        if not final or abs(ts - final[-1]) >= min_gap:
            final.append(ts)
    return final


def even_cap_timestamps(timestamps: List[float], max_frames: int) -> List[float]:
    if max_frames <= 0 or len(timestamps) <= max_frames:
        return timestamps
    idxs = np.linspace(0, len(timestamps) - 1, max_frames).round().astype(int).tolist()
    return [timestamps[i] for i in sorted(set(idxs))]


def observation_timestamps(
    duration: float,
    source_fps: float,
    total_frames: int,
    preferred_timestamps: Optional[Iterable[float]] = None,
    observation_fps: float = OBSERVATION_FLOOR_FPS,
) -> List[float]:
    """Union preferred samples with a source-frame-quantized observation floor."""
    if duration <= 0 or source_fps <= 0 or total_frames <= 0 or observation_fps <= 0:
        return []
    last_frame = total_frames - 1
    floor_count = max(1, int(math.ceil(duration * observation_fps - 1e-9)))
    frame_indexes = {
        min(last_frame, max(0, int(round((index / observation_fps) * source_fps))))
        for index in range(floor_count)
    }
    for value in preferred_timestamps or []:
        try:
            timestamp = float(value)
        except (TypeError, ValueError):
            continue
        if math.isnan(timestamp) or math.isinf(timestamp):
            continue
        frame_indexes.add(min(last_frame, max(0, int(round(timestamp * source_fps)))))
    return [round(frame_index / source_fps, 6) for frame_index in sorted(frame_indexes)]


def sample_frames(
    video_path: str,
    output_dir: str,
    every_seconds: float = 1.0,
    max_frames: int = 30,
    clear_frames: bool = False,
    preferred_timestamps: Optional[List[float]] = None,
) -> List[Dict[str, Any]]:
    if clear_frames and os.path.exists(output_dir):
        shutil.rmtree(output_dir, ignore_errors=True)
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if not fps or fps <= 0:
        raise RuntimeError("Could not read video FPS.")
    duration = total / fps
    if duration <= 0:
        raise RuntimeError("Could not read video duration.")

    # max_frames still bounds cue-derived preferences upstream. The validated
    # uniform floor is never globally recapped, which previously discarded it.
    timestamps = observation_timestamps(
        duration=duration,
        source_fps=fps,
        total_frames=total,
        preferred_timestamps=preferred_timestamps,
    )

    target_frames = {
        min(total - 1, max(0, int(round(ts * fps)))): (i, ts)
        for i, ts in enumerate(timestamps)
    }
    frames = []
    for frame_index in range(max(target_frames, default=-1) + 1):
        ok = cap.grab()
        if not ok:
            break
        target = target_frames.get(frame_index)
        if target is None:
            continue
        ok, frame = cap.retrieve()
        if not ok or frame is None:
            continue
        i, ts = target
        frame_path = os.path.join(output_dir, f"frame_{i:03d}_{ts:.2f}s.jpg")
        cv2.imwrite(frame_path, frame)
        frames.append({"index": i, "path": frame_path, "timestamp": round(float(ts), 3)})
    cap.release()
    return frames


# -----------------------------
# Transcript cue loading
# -----------------------------


def cue_from_obj(obj: Dict[str, Any], source: str, idx: int) -> Optional[Dict[str, Any]]:
    text = clean_text(obj.get("text") or obj.get("word") or obj.get("caption") or "")
    start = obj.get("start")
    end = obj.get("end")
    if start is None:
        start = obj.get("timeline_start") or obj.get("start_seconds") or obj.get("timeline_start_seconds")
    if end is None:
        end = obj.get("timeline_end") or obj.get("end_seconds") or obj.get("timeline_end_seconds")
    if not text or start is None or end is None:
        return None
    start_f = safe_float(start, 0.0)
    end_f = safe_float(end, start_f + 0.2)
    if end_f <= start_f:
        end_f = start_f + 0.15
    return {
        "id": str(obj.get("id") or obj.get("subtitle_id") or f"{source}_{idx:04d}"),
        "source": source,
        "text": text,
        "start": round(start_f, 4),
        "end": round(end_f, 4),
        "mid": round((start_f + end_f) / 2.0, 4),
        "duration": round(end_f - start_f, 4),
    }


def extract_transcript_cues(transcript: Dict[str, Any]) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []

    # Preferred: already chunked subtitle candidates/clips.
    for key, source in (("subtitle_candidates", "subtitle_candidates"), ("subtitle_clips", "subtitle_clips"), ("captions", "captions")):
        items = transcript.get(key)
        if isinstance(items, list):
            for i, obj in enumerate(items):
                if isinstance(obj, dict):
                    cue = cue_from_obj(obj, source, i)
                    if cue:
                        cues.append(cue)

    # Segment-level cues.
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
                    if isinstance(word_obj, dict):
                        cue = cue_from_obj(word_obj, "words", len(cues) + j)
                        if cue:
                            cues.append(cue)

    # Top-level word list.
    words = transcript.get("words")
    if isinstance(words, list):
        for i, word_obj in enumerate(words):
            if isinstance(word_obj, dict):
                cue = cue_from_obj(word_obj, "words", i)
                if cue:
                    cues.append(cue)

    # De-duplicate by timing/text.
    seen = set()
    final: List[Dict[str, Any]] = []
    for cue in sorted(cues, key=lambda x: (x["start"], x["end"], x["text"])):
        key = (round(cue["start"], 2), round(cue["end"], 2), normalize_match_text(cue["text"]))
        if key in seen:
            continue
        seen.add(key)
        final.append(cue)
    return final


def build_transcript_context(cues: List[Dict[str, Any]], timestamp: float, window_sec: float = 1.25, max_chars: int = 160) -> Dict[str, Any]:
    nearby = [c for c in cues if c["start"] - window_sec <= timestamp <= c["end"] + window_sec]

    # If no exact nearby cue, use nearest few cues.
    if not nearby and cues:
        scored = sorted(cues, key=lambda c: min(abs(timestamp - c["start"]), abs(timestamp - c["mid"]), abs(timestamp - c["end"])))
        nearby = scored[:5]

    # Build compact context around this time.
    text_parts: List[str] = []
    cue_ids: List[str] = []
    for cue in sorted(nearby, key=lambda c: (c["start"], c["end"])):
        if cue["id"] not in cue_ids:
            cue_ids.append(cue["id"])
        candidate = clean_text(" ".join(text_parts + [cue["text"]]))
        if len(candidate) > max_chars and text_parts:
            break
        text_parts.append(cue["text"])

    return {
        "timestamp": round(float(timestamp), 4),
        "cue_ids": cue_ids,
        "text": clean_text(" ".join(text_parts)),
        "cues": nearby[:12],
    }


def preferred_timestamps_from_cues(
    cues: List[Dict[str, Any]],
    max_frames: int,
    animation_samples_per_cue: int = 5,
    animation_sample_window_sec: float = 0.22,
) -> List[float]:
    """
    Build transcript-aware frame timestamps.

    v5.3 intentionally samples several adjacent frames around the same cue so the
    detector can infer simple caption animations: pop/scale, fade, and slide.
    The final list is still capped by --max-frames through even_cap_timestamps.
    """
    values: List[float] = []
    if not cues:
        return values

    duration_limit = max([safe_float(c.get("end"), 0.0) for c in cues], default=0.0) + 1.0

    # Prefer subtitle candidates/segments over every word if possible. Word-level
    # transcript can be very dense and would starve animation samples after capping.
    primary = [c for c in cues if c.get("source") in {"subtitle_candidates", "subtitle_clips", "segments", "captions"}]
    if not primary:
        primary = cues

    samples_per_cue = max(1, min(9, safe_int(animation_samples_per_cue, 5)))
    window = max(0.04, safe_float(animation_sample_window_sec, 0.22))

    for cue in primary:
        start = safe_float(cue.get("start"), 0.0)
        end = safe_float(cue.get("end"), start + 0.25)
        if end <= start:
            end = start + 0.15
        mid = safe_float(cue.get("mid"), (start + end) / 2.0)
        dur = max(0.03, end - start)

        # Always include semantically useful samples.
        values.extend([mid, start + min(0.05, dur * 0.22), end - min(0.05, dur * 0.22)])

        # Adjacent-frame animation samples. For short word-level captions, sample
        # inside the cue. For longer cues, sample a compact local window around mid.
        if samples_per_cue >= 3:
            if dur <= window * 1.35:
                local = np.linspace(start + min(0.02, dur * 0.15), end - min(0.02, dur * 0.15), samples_per_cue).tolist()
            else:
                local_start = max(start, mid - window / 2.0)
                local_end = min(end, mid + window / 2.0)
                if local_end <= local_start:
                    local_start, local_end = start, end
                local = np.linspace(local_start, local_end, samples_per_cue).tolist()
            values.extend(local)

    return even_cap_timestamps(unique_sorted_timestamps(values, duration=duration_limit, min_gap=0.035), max_frames)


# -----------------------------
# Color helpers / style estimation
# -----------------------------


def ensure_bgr_triplet(value: Any, fallback: Optional[List[int]] = None) -> List[int]:
    if fallback is None:
        fallback = [255, 255, 255]
    if value is None:
        return fallback
    try:
        if hasattr(value, "tolist"):
            value = value.tolist()
        arr = np.asarray(value).flatten()
        if arr.size >= 3:
            return [int(max(0, min(255, arr[0]))), int(max(0, min(255, arr[1]))), int(max(0, min(255, arr[2])))]
        if arr.size == 1:
            v = int(max(0, min(255, arr[0])))
            return [v, v, v]
    except Exception:
        pass
    return fallback


def bgr_to_hex(bgr: Any) -> str:
    b, g, r = ensure_bgr_triplet(bgr)
    return f"#{r:02x}{g:02x}{b:02x}"


def hex_to_rgb(hex_color: Any) -> Optional[List[int]]:
    if not isinstance(hex_color, str):
        return None
    value = hex_color.strip().lstrip("#")
    if len(value) != 6:
        return None
    try:
        return [int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)]
    except Exception:
        return None


def median_hex_color(hex_colors: Sequence[str], fallback: str = "#ffffff") -> str:
    rgbs = []
    for color in hex_colors:
        rgb = hex_to_rgb(color)
        if rgb:
            rgbs.append(rgb)
    if not rgbs:
        return fallback
    arr = np.asarray(rgbs, dtype=np.float32)
    med = np.median(arr, axis=0).astype(int).tolist()
    return f"#{med[0]:02x}{med[1]:02x}{med[2]:02x}"


def color_distance_bgr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    diff = a.astype(np.float32) - b.astype(np.float32)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def cluster_colors_bgr(pixels: np.ndarray, k: int = 4) -> List[Dict[str, Any]]:
    if pixels is None or len(pixels) == 0:
        return []
    pixels = np.asarray(pixels)
    if pixels.ndim != 2 or pixels.shape[1] < 3:
        return []
    pixels = pixels[:, :3]
    if len(pixels) > 6000:
        idx = np.linspace(0, len(pixels) - 1, 6000).round().astype(int)
        pixels = pixels[idx]
    if len(pixels) < 6:
        med = np.median(pixels, axis=0).astype(int).tolist()
        return [{"bgr": med, "hex": bgr_to_hex(med), "ratio": 1.0, "brightness": float(np.mean(med)), "saturation": 0.0}]

    data = np.float32(pixels)
    kk = min(k, len(data))
    try:
        _, labels, centers = cv2.kmeans(
            data,
            kk,
            None,
            (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0),
            4,
            cv2.KMEANS_PP_CENTERS,
        )
        counts = np.bincount(labels.flatten(), minlength=kk)
        clusters = []
        for i, center in enumerate(centers):
            bgr = ensure_bgr_triplet(center.astype(int).tolist())
            hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0][0]
            clusters.append({
                "bgr": bgr,
                "hex": bgr_to_hex(bgr),
                "ratio": round(float(counts[i]) / max(1, int(np.sum(counts))), 4),
                "brightness": round(float(hsv[2]), 4),
                "saturation": round(float(hsv[1]), 4),
                "hue": round(float(hsv[0]), 4),
            })
        return sorted(clusters, key=lambda c: c["ratio"], reverse=True)
    except Exception:
        med = np.median(pixels, axis=0).astype(int).tolist()
        return [{"bgr": med, "hex": bgr_to_hex(med), "ratio": 1.0, "brightness": float(np.mean(med)), "saturation": 0.0}]


def choose_fill_stroke_shadow(
    clusters: List[Dict[str, Any]],
    dark_ratio: float,
    bright_ratio: float,
    saturated_ratio: float = 0.0,
    font_ratio: float = 0.0,
    width_ratio: float = 0.0,
) -> Dict[str, Any]:
    """
    v5.1 color/stroke resolver.

    The v5 bug was selecting skin/background saturation as text fill. For normal
    viral spoken captions, the actual fill is usually the brightest/white cluster
    and the outline/shadow is the darkest cluster. Saturated fill is only trusted
    for large/hook-style text, where colored fill dominates the OCR crop.
    """
    if not clusters:
        return {
            "fill": "#ffffff",
            "stroke": "#000000",
            "shadow": "#000000",
            "stroke_enabled": False,
            "shadow_enabled": False,
            "color_model": "fallback",
        }

    bright = [c for c in clusters if c.get("brightness", 0) >= 185]
    whiteish = [c for c in clusters if c.get("brightness", 0) >= 200 and c.get("saturation", 255) <= 105]
    dark = [c for c in clusters if c.get("brightness", 255) <= 85]
    strong_saturated = [
        c for c in clusters
        if c.get("saturation", 0) >= 115
        and c.get("brightness", 0) >= 75
        and c.get("ratio", 0) >= 0.025
    ]

    is_large_or_hook_like = bool(font_ratio >= 0.052 or width_ratio >= 0.36)

    # Large display captions often contain more crop/background pixels than
    # glyph pixels. Rank plausible foreground colors by visual prominence in
    # the OCR text region instead of allowing the largest saturated cluster to
    # win by area alone. Keep the legacy resolver below when the foreground
    # evidence is not clearly separated.
    def foreground_score(cluster: Dict[str, Any]) -> float:
        return (
            safe_float(cluster.get("brightness"), 0.0)
            + (0.25 * min(180.0, safe_float(cluster.get("saturation"), 0.0)))
            + (200.0 * safe_float(cluster.get("ratio"), 0.0))
        )

    if is_large_or_hook_like:
        plausible_foreground = [
            c for c in clusters
            if c.get("brightness", 0) >= 170
            and c.get("ratio", 0) >= 0.025
        ]
        accent_foreground = [c for c in plausible_foreground if c.get("saturation", 0) >= 30]
        white_foreground = [c for c in plausible_foreground if c.get("saturation", 255) <= 30]
        accent = max(accent_foreground, key=foreground_score, default=None)
        white = max(white_foreground, key=foreground_score, default=None)

        selected = None
        if accent is not None and (white is None or foreground_score(accent) >= foreground_score(white) + 3.0):
            selected = accent
        elif white is not None and strong_saturated:
            saturated_default = max(strong_saturated, key=lambda c: (c.get("ratio", 0), c.get("saturation", 0)))
            if saturated_default.get("brightness", 255) < 150:
                selected = white

        if selected is not None:
            dark_edge = max(dark, key=lambda c: c.get("ratio", 0), default=None)
            edge = dark_edge or next(
                (c for c in sorted(clusters, key=foreground_score, reverse=True) if c is not selected),
                {"hex": "#000000"},
            )
            shadow = dark_edge or edge
            return {
                "fill": selected.get("hex", "#ffffff"),
                "stroke": edge.get("hex", "#000000"),
                "shadow": shadow.get("hex", "#000000"),
                "stroke_enabled": bool(dark_edge is not None or dark_ratio > 0.035),
                "shadow_enabled": bool(dark_ratio > 0.025),
                "color_model": "large_foreground_fill_dark_edge",
            }

    # Large hook captions: red/yellow/etc. fill + white outline + dark shadow.
    if strong_saturated and is_large_or_hook_like:
        fill = sorted(strong_saturated, key=lambda c: (c.get("ratio", 0), c.get("saturation", 0)), reverse=True)[0]
        outline_candidates = [c for c in whiteish or bright if c.get("hex", "").lower() != fill.get("hex", "").lower()]
        stroke = sorted(outline_candidates, key=lambda c: (c.get("brightness", 0), c.get("ratio", 0)), reverse=True)[0] if outline_candidates else (dark[0] if dark else {"hex": "#000000"})
        shadow = dark[0] if dark else {"hex": "#000000"}
        return {
            "fill": fill.get("hex", "#ff0000"),
            "stroke": stroke.get("hex", "#ffffff"),
            "shadow": shadow.get("hex", "#000000"),
            "stroke_enabled": True,
            "shadow_enabled": bool(dark_ratio > 0.025),
            "color_model": "large_saturated_hook_fill",
        }

    # Spoken captions: prefer the light text fill, do not let skin/glass/shirt
    # saturation become the fill.
    if whiteish:
        fill = sorted(whiteish, key=lambda c: (c.get("brightness", 0), c.get("ratio", 0)), reverse=True)[0]
    elif bright:
        fill = sorted(bright, key=lambda c: (c.get("brightness", 0), c.get("ratio", 0)), reverse=True)[0]
    elif strong_saturated:
        # No reliable white pixels. Use saturated fill only as fallback.
        fill = sorted(strong_saturated, key=lambda c: (c.get("ratio", 0), c.get("saturation", 0)), reverse=True)[0]
    else:
        fill = sorted(clusters, key=lambda c: (c.get("brightness", 0), c.get("ratio", 0)), reverse=True)[0]

    stroke = sorted(dark, key=lambda c: (c.get("ratio", 0), -c.get("brightness", 255)), reverse=True)[0] if dark else {"hex": "#000000"}
    return {
        "fill": fill.get("hex", "#ffffff"),
        "stroke": stroke.get("hex", "#000000"),
        "shadow": stroke.get("hex", "#000000"),
        "stroke_enabled": bool(dark_ratio > 0.035),
        "shadow_enabled": bool(dark_ratio > 0.020),
        "color_model": "spoken_light_fill_dark_outline",
    }


# -----------------------------
# OCR parsing
# -----------------------------


def normalize_box(box: Any) -> Optional[List[List[float]]]:
    if box is None:
        return None
    if hasattr(box, "tolist"):
        box = box.tolist()
    if isinstance(box, (list, tuple)) and len(box) == 4 and all(isinstance(v, (int, float, np.integer, np.floating)) for v in box):
        x1, y1, x2, y2 = box
        return [[float(x1), float(y1)], [float(x2), float(y1)], [float(x2), float(y2)], [float(x1), float(y2)]]
    if isinstance(box, (list, tuple)) and len(box) == 8 and all(isinstance(v, (int, float, np.integer, np.floating)) for v in box):
        return [[float(box[0]), float(box[1])], [float(box[2]), float(box[3])], [float(box[4]), float(box[5])], [float(box[6]), float(box[7])]]
    if isinstance(box, (list, tuple)) and len(box) >= 4 and isinstance(box[0], (list, tuple, np.ndarray)):
        points = []
        for p in box[:4]:
            if hasattr(p, "tolist"):
                p = p.tolist()
            if len(p) >= 2:
                points.append([float(p[0]), float(p[1])])
        if len(points) == 4:
            return points
    return None


def get_field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    try:
        return obj[key]
    except Exception:
        pass
    return getattr(obj, key, default)


def parse_old_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed = []
    if not result:
        return parsed
    lines = result
    if isinstance(result, list) and len(result) == 1 and isinstance(result[0], list):
        lines = result[0]
    if not isinstance(lines, list):
        return parsed
    for line in lines:
        try:
            if not isinstance(line, (list, tuple)) or len(line) < 2:
                continue
            box = normalize_box(line[0])
            if not box:
                continue
            text_data = line[1]
            if isinstance(text_data, (list, tuple)) and len(text_data) >= 2:
                text = str(text_data[0])
                confidence = float(text_data[1])
            else:
                continue
            parsed.append((box, text, confidence))
        except Exception:
            continue
    return parsed


def parse_new_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed = []
    if not result:
        return parsed
    pages = result if isinstance(result, list) else [result]
    for page in pages:
        texts = get_field(page, "rec_texts", [])
        scores = get_field(page, "rec_scores", [])
        boxes = get_field(page, "rec_polys", None) or get_field(page, "rec_boxes", None) or get_field(page, "dt_polys", None) or get_field(page, "dt_boxes", None)
        if hasattr(texts, "tolist"):
            texts = texts.tolist()
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if hasattr(boxes, "tolist"):
            boxes = boxes.tolist()
        if not texts or boxes is None:
            continue
        count = min(len(texts), len(scores), len(boxes))
        for i in range(count):
            try:
                box = normalize_box(boxes[i])
                if not box:
                    continue
                parsed.append((box, str(texts[i]), float(scores[i])))
            except Exception:
                continue
    return parsed


def parse_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed = parse_old_paddle_result(result)
    if parsed:
        return parsed
    return parse_new_paddle_result(result)


def configure_paddle_device(ocr_device: str = "auto", gpu_id: int = 0) -> Dict[str, Any]:
    """
    Configure Paddle runtime before PaddleOCR is constructed.

    This script used to rely on PaddleOCR defaults, which can silently run on CPU.
    v5.4 makes the device explicit and records the result in JSON/stdout.
    """
    requested = str(ocr_device or "auto").strip().lower()
    if requested not in {"auto", "cpu", "gpu"}:
        requested = "auto"

    info: Dict[str, Any] = {
        "requested": requested,
        "gpu_id": int(gpu_id),
        "paddle_imported": False,
        "paddle_version": None,
        "compiled_with_cuda": False,
        "selected_device": "unknown",
        "set_device_ok": False,
        "warnings": [],
    }

    try:
        import paddle  # type: ignore
        info["paddle_imported"] = True
        info["paddle_version"] = getattr(paddle, "__version__", None)
        try:
            info["compiled_with_cuda"] = bool(paddle.device.is_compiled_with_cuda())
        except Exception as exc:
            info["warnings"].append(f"could_not_check_cuda_compile: {repr(exc)}")
            info["compiled_with_cuda"] = False

        if requested == "gpu" and not info["compiled_with_cuda"]:
            raise RuntimeError(
                "--ocr-device gpu was requested, but PaddlePaddle is not compiled with CUDA. "
                "Install paddlepaddle-gpu in venv_ocr first."
            )

        if requested in {"auto", "gpu"} and info["compiled_with_cuda"]:
            target = f"gpu:{int(gpu_id)}"
            try:
                paddle.device.set_device(target)
                info["selected_device"] = str(paddle.device.get_device())
                info["set_device_ok"] = True
                return info
            except Exception as exc:
                if requested == "gpu":
                    raise RuntimeError(f"Could not set Paddle device to {target}: {repr(exc)}")
                info["warnings"].append(f"auto_gpu_failed_falling_back_to_cpu: {repr(exc)}")

        try:
            paddle.device.set_device("cpu")
            info["selected_device"] = str(paddle.device.get_device())
            info["set_device_ok"] = True
        except Exception as exc:
            info["warnings"].append(f"could_not_set_cpu_device: {repr(exc)}")
            try:
                info["selected_device"] = str(paddle.device.get_device())
            except Exception:
                info["selected_device"] = "unknown"
        return info

    except Exception as exc:
        if requested == "gpu":
            raise
        info["warnings"].append(f"paddle_runtime_config_failed: {repr(exc)}")
        return info


def create_ocr(lang: str = "en", use_angle_cls: bool = False, ocr_device: str = "auto", gpu_id: int = 0) -> Tuple[Any, Dict[str, Any]]:
    runtime = configure_paddle_device(ocr_device=ocr_device, gpu_id=gpu_id)
    selected = str(runtime.get("selected_device") or "").lower()
    wants_gpu = selected.startswith("gpu")

    # PaddleOCR constructor arguments differ between versions. Try the explicit
    # GPU form first, then newer `device=...`, then legacy-safe fallbacks.
    attempts: List[Dict[str, Any]] = [
        {"lang": lang, "use_angle_cls": bool(use_angle_cls), "use_gpu": wants_gpu, "gpu_id": int(gpu_id), "show_log": False},
        {"lang": lang, "use_angle_cls": bool(use_angle_cls), "device": selected if selected else (f"gpu:{gpu_id}" if wants_gpu else "cpu"), "show_log": False},
        {"lang": lang, "use_angle_cls": bool(use_angle_cls), "use_gpu": wants_gpu, "gpu_id": int(gpu_id)},
        {"lang": lang, "use_angle_cls": bool(use_angle_cls), "show_log": False},
        {"lang": lang, "use_angle_cls": bool(use_angle_cls)},
    ]

    constructor_errors: List[str] = []
    for kwargs in attempts:
        try:
            ocr = PaddleOCR(**kwargs)
            runtime["paddleocr_constructor_kwargs"] = {k: v for k, v in kwargs.items() if k not in {"show_log"}}
            runtime["paddleocr_constructor_used"] = True
            runtime["paddleocr_constructor_errors"] = constructor_errors[-3:]
            return ocr, runtime
        except TypeError as exc:
            constructor_errors.append(f"TypeError with {sorted(kwargs.keys())}: {exc}")
            continue

    # If every attempt failed due TypeError, surface the last real constructor error.
    runtime["paddleocr_constructor_errors"] = constructor_errors
    ocr = PaddleOCR(lang=lang)
    runtime["paddleocr_constructor_kwargs"] = {"lang": lang}
    runtime["paddleocr_constructor_used"] = True
    return ocr, runtime


def run_ocr(ocr: Any, frame_path: str) -> Any:
    return ocr.ocr(frame_path, cls=False)


def _perspective_crop(image: np.ndarray, box: Any) -> Optional[np.ndarray]:
    points = normalize_box(box)
    if not points:
        return None
    source = np.asarray(points, dtype=np.float32)
    width = max(np.linalg.norm(source[0] - source[1]), np.linalg.norm(source[2] - source[3]))
    height = max(np.linalg.norm(source[0] - source[3]), np.linalg.norm(source[1] - source[2]))
    target_w, target_h = max(1, int(round(width))), max(1, int(round(height)))
    target = np.asarray(
        [[0, 0], [target_w - 1, 0], [target_w - 1, target_h - 1], [0, target_h - 1]],
        dtype=np.float32,
    )
    crop = cv2.warpPerspective(image, cv2.getPerspectiveTransform(source, target), (target_w, target_h))
    if crop.size == 0:
        return None
    if crop.shape[0] / max(1, crop.shape[1]) >= 1.5:
        crop = np.rot90(crop)
    return crop


def _smaller_bbox_coverage(left: List[int], right: List[int]) -> float:
    x1, y1 = max(left[0], right[0]), max(left[1], right[1])
    x2, y2 = min(left[2], right[2]), min(left[3], right[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    left_area = max(1, left[2] - left[0]) * max(1, left[3] - left[1])
    right_area = max(1, right[2] - right[0]) * max(1, right[3] - right[1])
    return float(intersection) / min(left_area, right_area)


def refine_merged_ocr_regions(
    ocr: Any,
    frame: np.ndarray,
    parsed_lines: Sequence[Tuple[List[List[float]], str, float]],
    scale: int = 3,
    child_min_confidence: float = 0.5,
    duplicate_coverage: float = 0.8,
    include_provenance: bool = False,
) -> List[Tuple[Any, ...]]:
    """Replace a parent only when crop re-OCR proves at least two child regions."""
    frame_h, frame_w = frame.shape[:2]
    direct: List[Tuple[List[List[float]], str, float]] = []
    refined: List[Tuple[List[List[float]], str, float]] = []
    for parent_box, parent_text, parent_confidence in parsed_lines:
        parent_bbox = box_to_bbox(parent_box, frame_w, frame_h)
        if not parent_bbox or not hasattr(ocr, "text_detector") or not hasattr(ocr, "text_recognizer"):
            direct.append((parent_box, parent_text, parent_confidence))
            continue
        x1, y1, x2, y2 = parent_bbox
        crop = frame[y1:y2, x1:x2]
        try:
            enlarged = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            detector_result = ocr.text_detector(enlarged)
            child_boxes = detector_result[0] if isinstance(detector_result, tuple) else detector_result
            child_boxes = [] if child_boxes is None else list(child_boxes)
            child_crops = [_perspective_crop(enlarged, box) for box in child_boxes]
            usable = [(box, child) for box, child in zip(child_boxes, child_crops) if child is not None]
            recognizer_result = ocr.text_recognizer([child for _, child in usable]) if usable else ([], 0.0)
            recognized = recognizer_result[0] if isinstance(recognizer_result, tuple) else recognizer_result
            children = []
            for (child_box, _), result in zip(usable, recognized or []):
                text = clean_text(result[0] if isinstance(result, (list, tuple)) and result else "")
                confidence = safe_float(result[1] if isinstance(result, (list, tuple)) and len(result) > 1 else 0.0, 0.0)
                normalized = normalize_box(child_box)
                if not text or confidence < child_min_confidence or not normalized:
                    continue
                mapped = [[x1 + point[0] / scale, y1 + point[1] / scale] for point in normalized]
                children.append((mapped, text, confidence))
        except Exception:
            children = []
        if len(children) < 2:
            direct.append((parent_box, parent_text, parent_confidence))
        else:
            refined.extend(children)

    direct_bboxes = [box_to_bbox(box, frame_w, frame_h) for box, _, _ in direct]
    kept_refined: List[Tuple[List[List[float]], str, float]] = []
    kept_bboxes: List[List[int]] = []
    for child in sorted(refined, key=lambda row: safe_float(row[2], 0.0), reverse=True):
        child_bbox = box_to_bbox(child[0], frame_w, frame_h)
        if not child_bbox:
            continue
        if any(box and _smaller_bbox_coverage(child_bbox, box) >= duplicate_coverage for box in direct_bboxes):
            continue
        if any(_smaller_bbox_coverage(child_bbox, box) >= duplicate_coverage for box in kept_bboxes):
            continue
        kept_refined.append(child)
        kept_bboxes.append(child_bbox)
    if include_provenance:
        return [(*row, "direct") for row in direct] + [
            (*row, "crop_refined_child") for row in kept_refined
        ]
    return direct + kept_refined


# -----------------------------
# Style estimation from OCR boxes
# -----------------------------


def box_to_bbox(box: Any, w: int, h: int) -> Optional[List[int]]:
    box = normalize_box(box)
    if not box:
        return None
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    x1 = max(0, int(min(xs)))
    y1 = max(0, int(min(ys)))
    x2 = min(w, int(max(xs)))
    y2 = min(h, int(max(ys)))
    if x2 <= x1 or y2 <= y1:
        return None
    return [x1, y1, x2, y2]


def bbox_to_normalized(bbox: List[int], frame_w: int, frame_h: int) -> List[float]:
    x1, y1, x2, y2 = bbox
    return [round(x1 / frame_w, 4), round(y1 / frame_h, 4), round(x2 / frame_w, 4), round(y2 / frame_h, 4)]


def center_from_bbox(bbox: List[int], frame_w: int, frame_h: int) -> Dict[str, float]:
    x1, y1, x2, y2 = bbox
    return {"x": round(((x1 + x2) / 2) / frame_w, 4), "y": round(((y1 + y2) / 2) / frame_h, 4)}


def position_from_center(cx: float, cy: float) -> Dict[str, str]:
    if cy > 0.68:
        vertical_zone = "bottom"
    elif cy < 0.33:
        vertical_zone = "top"
    else:
        vertical_zone = "middle"
    if cx < 0.35:
        horizontal_align = "left"
    elif cx > 0.65:
        horizontal_align = "right"
    else:
        horizontal_align = "center"
    return {"vertical_zone": vertical_zone, "horizontal_align": horizontal_align}


def estimate_caption_style(frame: np.ndarray, box: Any) -> Dict[str, Any]:
    h, w = frame.shape[:2]
    bbox = box_to_bbox(box, w, h)
    if not bbox:
        return {}
    x1, y1, x2, y2 = bbox

    font_height = y2 - y1
    pad_x = max(6, int(font_height * 0.18))
    pad_y = max(5, int(font_height * 0.22))
    crop = frame[max(0, y1 - pad_y):min(h, y2 + pad_y), max(0, x1 - pad_x):min(w, x2 + pad_x)]
    if crop.size == 0:
        return {}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)

    # Estimate background from crop border, then foreground via contrast from that background.
    border = np.concatenate([
        crop[0:2, :, :].reshape(-1, 3),
        crop[-2:, :, :].reshape(-1, 3),
        crop[:, 0:2, :].reshape(-1, 3),
        crop[:, -2:, :].reshape(-1, 3),
    ], axis=0)
    bg = np.median(border, axis=0).astype(np.float32) if len(border) else np.array([0, 0, 0], dtype=np.float32)
    dist = color_distance_bgr(crop, bg)

    bright_mask = gray >= 180
    dark_mask = gray <= 75
    saturated_mask = (hsv[:, :, 1] >= 75) & (hsv[:, :, 2] >= 55)
    contrast_mask = dist >= 38
    foreground_mask = contrast_mask | bright_mask | saturated_mask | dark_mask

    # Avoid considering the entire crop foreground on noisy backgrounds.
    fg_ratio_raw = float(np.count_nonzero(foreground_mask)) / max(1, foreground_mask.size)
    if fg_ratio_raw > 0.78:
        # Fall back to strongest edge/color pixels.
        foreground_mask = bright_mask | dark_mask | saturated_mask | (dist >= np.percentile(dist, 72))

    text_pixels = crop[foreground_mask]
    clusters = cluster_colors_bgr(text_pixels, k=5)

    dark_ratio = float(np.count_nonzero(dark_mask)) / max(1, dark_mask.size)
    bright_ratio = float(np.count_nonzero(bright_mask)) / max(1, bright_mask.size)
    saturated_ratio = float(np.count_nonzero(saturated_mask)) / max(1, saturated_mask.size)
    contrast_ratio = float(np.count_nonzero(contrast_mask)) / max(1, contrast_mask.size)

    colors = choose_fill_stroke_shadow(clusters, dark_ratio=dark_ratio, bright_ratio=bright_ratio, saturated_ratio=saturated_ratio, font_ratio=float(font_height) / max(1, h), width_ratio=(x2 - x1) / max(1, w))

    center = center_from_bbox(bbox, w, h)
    position = position_from_center(center["x"], center["y"])
    width_ratio = (x2 - x1) / w
    height_ratio = (y2 - y1) / h

    return {
        "bbox": bbox,
        "normalized_bbox": bbox_to_normalized(bbox, w, h),
        "center": center,
        "position": position,
        "estimated_font_height_px": int(font_height),
        "estimated_font_height_ratio": round(float(font_height) / max(1, h), 5),
        "estimated_box_width_ratio": round(float(width_ratio), 4),
        "estimated_box_height_ratio": round(float(height_ratio), 4),
        "estimated_text_color": colors["fill"],
        "estimated_stroke_color": colors["stroke"],
        "estimated_shadow_color": colors["shadow"],
        "has_dark_stroke": bool(colors.get("stroke_enabled") or dark_ratio > 0.045),
        "has_shadow": bool(colors.get("shadow_enabled") or dark_ratio > 0.025),
        "has_bright_text": bool(bright_ratio > 0.018),
        "has_saturated_text": bool(saturated_ratio > 0.018),
        "text_area_ratio": round(float(bright_ratio), 4),
        "dark_area_ratio": round(float(dark_ratio), 4),
        "saturated_area_ratio": round(float(saturated_ratio), 4),
        "contrast_area_ratio": round(float(contrast_ratio), 4),
        "color_clusters": clusters[:5],
        "color_model": colors.get("color_model"),
    }


# -----------------------------
# Candidate scoring and grouping
# -----------------------------


def visual_caption_score(det: Dict[str, Any]) -> float:
    center = det.get("center") or {}
    cx = safe_float(center.get("x"), 0.5)
    cy = safe_float(center.get("y"), 0.5)
    font_ratio = safe_float(det.get("estimated_font_height_ratio"), 0.0)
    width_ratio = safe_float(det.get("estimated_box_width_ratio"), 0.0)
    contrast = safe_float(det.get("contrast_area_ratio"), 0.0)
    dark = 1.0 if det.get("has_dark_stroke") else 0.0
    bright = 1.0 if det.get("has_bright_text") else 0.0
    sat = 1.0 if det.get("has_saturated_text") else 0.0

    center_score = 1.0 - min(1.0, abs(cx - 0.5) / 0.5)
    # Viral captions can be middle or lower-middle. Penalize extreme top UI and sides, not center.
    vertical_score = 1.0
    if cy < 0.18:
        vertical_score = 0.25
    elif cy < 0.30:
        vertical_score = 0.55
    elif cy > 0.92:
        vertical_score = 0.45

    font_score = clamp((font_ratio - 0.012) / 0.075, 0.0, 1.0)
    width_score = clamp((width_ratio - 0.05) / 0.45, 0.0, 1.0)
    style_score = clamp((contrast * 2.0) + (dark * 0.20) + (bright * 0.15) + (sat * 0.25), 0.0, 1.0)

    score = (0.22 * center_score) + (0.17 * vertical_score) + (0.25 * font_score) + (0.16 * width_score) + (0.20 * style_score)
    return round(float(clamp(score, 0.0, 1.0)), 4)


def hook_visual_score(det: Dict[str, Any]) -> float:
    text = clean_text(det.get("text"))
    case = infer_case_style([text])
    font_ratio = safe_float(det.get("estimated_font_height_ratio"), 0.0)
    width_ratio = safe_float(det.get("estimated_box_width_ratio"), 0.0)
    sat = 1.0 if det.get("has_saturated_text") else 0.0
    stroke = 1.0 if det.get("has_dark_stroke") or det.get("estimated_stroke_color") not in (None, "#000000") else 0.0
    center = det.get("center") or {}
    cy = safe_float(center.get("y"), 0.5)
    big = clamp((font_ratio - 0.045) / 0.12, 0.0, 1.0)
    wide = clamp((width_ratio - 0.25) / 0.55, 0.0, 1.0)
    upper = 1.0 if case == "uppercase" else 0.25
    mid = 1.0 if 0.15 <= cy <= 0.88 else 0.25
    score = (0.34 * big) + (0.22 * wide) + (0.16 * upper) + (0.16 * sat) + (0.07 * stroke) + (0.05 * mid)
    return round(float(clamp(score, 0.0, 1.0)), 4)


def classify_caption_candidate(det: Dict[str, Any], context: Dict[str, Any], args: argparse.Namespace) -> Tuple[bool, Dict[str, Any]]:
    text = clean_text(det.get("text"))
    if is_noise_text(text):
        return False, {"reason": "noise_text", "score": 0.0}

    conf = safe_float(det.get("confidence"), 0.0)
    visual = visual_caption_score(det)
    hook = hook_visual_score(det)
    transcript_text = context.get("text") or ""
    transcript_match = fuzzy_similarity(text, transcript_text) if transcript_text else 0.0
    # A compact context can dilute a valid OCR-to-cue match with unrelated
    # nearby words. Preserve that match, but only admit an individual subtitle
    # cue when it is temporally nearby; the existing classifier gates remain
    # authoritative.
    context_timestamp = safe_float(context.get("timestamp"), safe_float(det.get("timestamp"), 0.0))
    best_nearby_individual_match = 0.0
    for cue in context.get("cues") or []:
        if not isinstance(cue, dict) or cue.get("source") != "subtitle_candidates":
            continue
        cue_start = safe_float(cue.get("start"), 0.0)
        cue_end = safe_float(cue.get("end"), cue_start)
        interval_distance = max(0.0, cue_start - context_timestamp, context_timestamp - cue_end)
        if interval_distance <= 0.5:
            best_nearby_individual_match = max(
                best_nearby_individual_match,
                fuzzy_similarity(text, cue.get("text")),
            )
    transcript_match = max(transcript_match, best_nearby_individual_match)

    center = det.get("center") or {}
    cy = safe_float(center.get("y"), 0.0)
    cx = safe_float(center.get("x"), 0.0)
    font_ratio = safe_float(det.get("estimated_font_height_ratio"), 0.0)
    width_ratio = safe_float(det.get("estimated_box_width_ratio"), 0.0)

    top_ui_penalty = 0.22 if cy < args.viral_min_y else 0.0
    side_penalty = 0.16 if (cx < args.viral_min_x or cx > args.viral_max_x) else 0.0

    transcript_boost = transcript_match * 0.42 if args.mode == "viral_transcript_aware" else 0.0
    base = (0.26 * conf) + (0.32 * visual) + transcript_boost - top_ui_penalty - side_penalty
    score = round(float(clamp(base, 0.0, 1.0)), 4)

    is_top_ui_like = bool(
        cy < args.top_ui_caption_max_y
        and font_ratio <= args.top_ui_max_font_ratio
        and hook < args.visual_hook_score_threshold
        and transcript_match < args.top_ui_allow_match_threshold
    )

    is_transcript_caption = bool(
        not is_top_ui_like
        and transcript_match >= args.transcript_match_threshold
        and score >= args.regular_caption_score_threshold
    )

    is_visual_spoken_caption = bool(
        not is_top_ui_like
        and args.enable_visual_spoken_fallback
        and conf >= args.visual_spoken_min_confidence
        and visual >= args.visual_spoken_score_threshold
        and args.visual_spoken_min_y <= cy <= args.visual_spoken_max_y
        and args.visual_spoken_min_x <= cx <= args.visual_spoken_max_x
        and font_ratio >= args.visual_spoken_min_font_ratio
        and width_ratio >= args.visual_spoken_min_width_ratio
        and (det.get("has_dark_stroke") or det.get("has_shadow") or det.get("has_bright_text"))
    )

    is_hook_caption = bool(
        not is_top_ui_like
        and hook >= args.visual_hook_score_threshold
        and conf >= args.hook_min_confidence
        and cy >= args.hook_min_y
    )

    if args.mode == "legacy":
        is_accepted = (
            conf >= args.subtitle_min_confidence
            and args.subtitle_min_x <= cx <= args.subtitle_max_x
            and args.subtitle_min_y <= cy <= args.subtitle_max_y
            and args.subtitle_min_font_height <= safe_int(det.get("estimated_font_height_px"), 0) <= args.subtitle_max_font_height
            and safe_float(det.get("estimated_box_width_ratio"), 0.0) >= args.subtitle_min_width_ratio
            and (not args.require_bright_text or bool(det.get("has_bright_text")))
        )
        reason = "legacy_bottom_caption" if is_accepted else "legacy_rejected"
    else:
        is_accepted = bool(is_transcript_caption or is_visual_spoken_caption or is_hook_caption)
        if is_transcript_caption:
            reason = "transcript_matched_caption"
        elif is_visual_spoken_caption:
            reason = "visual_spoken_caption_fallback"
        elif is_hook_caption:
            reason = "visual_hook_caption"
        elif is_top_ui_like:
            reason = "top_ui_like_text"
        else:
            reason = "low_caption_score"

    return is_accepted, {
        "reason": reason,
        "score": score,
        "visual_score": visual,
        "hook_score": hook,
        "transcript_match_score": transcript_match,
        "matched_context_text": transcript_text,
        "matched_cue_ids": context.get("cue_ids", []),
        "confidence": round(conf, 4),
        "is_top_ui_like": bool(is_top_ui_like),
        "visual_fallback_used": bool(reason == "visual_spoken_caption_fallback"),
    }


def _continuation_geometry(left: Dict[str, Any], right: Dict[str, Any]) -> Tuple[float, float, float, float]:
    left_bbox = left.get("normalized_bbox") or []
    right_bbox = right.get("normalized_bbox") or []
    if len(left_bbox) != 4 or len(right_bbox) != 4:
        return 0.0, float("inf"), float("inf"), float("inf")
    lx1, ly1, lx2, ly2 = [safe_float(value) for value in left_bbox]
    rx1, ry1, rx2, ry2 = [safe_float(value) for value in right_bbox]
    intersection = max(0.0, min(lx2, rx2) - max(lx1, rx1)) * max(0.0, min(ly2, ry2) - max(ly1, ry1))
    left_width, left_height = max(0.0, lx2 - lx1), max(0.0, ly2 - ly1)
    right_width, right_height = max(0.0, rx2 - rx1), max(0.0, ry2 - ry1)
    left_area, right_area = left_width * left_height, right_width * right_height
    union = left_area + right_area - intersection
    iou = intersection / union if union > 0 else 0.0
    center_distance = math.hypot(((lx1 + lx2) - (rx1 + rx2)) / 2.0, ((ly1 + ly2) - (ry1 + ry2)) / 2.0)
    area_ratio = max(left_area, right_area) / min(left_area, right_area) if min(left_area, right_area) > 0 else float("inf")
    left_aspect = left_width / left_height if left_height > 0 else 0.0
    right_aspect = right_width / right_height if right_height > 0 else 0.0
    aspect_ratio = max(left_aspect, right_aspect) / min(left_aspect, right_aspect) if min(left_aspect, right_aspect) > 0 else float("inf")
    return iou, center_distance, area_ratio, aspect_ratio


def _compatible_continuation(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    iou, center_distance, area_ratio, aspect_ratio = _continuation_geometry(left, right)
    return bool(
        iou >= CONTINUATION_MIN_IOU
        and center_distance <= CONTINUATION_MAX_CENTER_DISTANCE
        and area_ratio <= CONTINUATION_MAX_AREA_RATIO
        and aspect_ratio <= CONTINUATION_MAX_ASPECT_RATIO
    )


def _same_visible_caption_text(previous: Any, current: Any) -> bool:
    """OCR-tolerant identity, not a transcript/geometry-based caption identity.

    Text may sharpen or reveal additional words in-place. An unrelated
    replacement at the same coordinates must start a new visual tracklet.
    """
    left, right = normalize_match_text(previous), normalize_match_text(current)
    if not left or not right:
        return False
    if left == right:
        return True
    similarity = difflib.SequenceMatcher(None, left, right).ratio()
    if similarity >= 0.62:
        return True
    left_tokens, right_tokens = left.split(), right.split()
    shorter, longer = (left_tokens, right_tokens) if len(left_tokens) <= len(right_tokens) else (right_tokens, left_tokens)
    return bool(
        shorter and len(shorter[0]) >= 3
        and (longer[:len(shorter)] == shorter or longer[-len(shorter):] == shorter)
    )


def apply_short_caption_continuations(
    frame_results: List[Dict[str, Any]],
    observation_period_sec: float,
    video_duration: float,
) -> None:
    """Annotate accepted observations and admit only compatible low-score tails."""
    active: Dict[str, Dict[str, Any]] = {}
    next_identity = 1
    for frame_result in sorted(frame_results, key=lambda row: safe_float(row.get("timestamp"), 0.0)):
        timestamp = safe_float(frame_result.get("timestamp"), 0.0)
        active = {
            identity: state
            for identity, state in active.items()
            if timestamp - safe_float(state.get("timestamp"), timestamp) <= CONTINUATION_MAX_GAP_SEC + 1e-9
        }
        claimed = set()
        detections = frame_result.get("detections") or []
        ordered = sorted(detections, key=lambda det: not bool(det.get("classifier_accepted")))
        for det in ordered:
            accepted = bool(det.get("classifier_accepted"))
            reason = (det.get("caption_score") or {}).get("reason")
            if not accepted and reason != "low_caption_score":
                continue
            matches = []
            for identity, state in active.items():
                if identity in claimed or not _compatible_continuation(state, det):
                    continue
                # Weak OCR tails may bridge one missed observation, but an
                # accepted, different phrase is never the same caption.
                if accepted and not _same_visible_caption_text(state.get("accepted_text"), det.get("text")):
                    continue
                iou, center_distance, _, _ = _continuation_geometry(state, det)
                matches.append((-iou, center_distance, identity))
            identity = min(matches)[2] if matches else None
            if identity is None:
                if not accepted:
                    continue
                identity = f"caption_tracklet_{next_identity:04d}"
                next_identity += 1

            provenance = (
                "accepted_refined"
                if accepted and det.get("source_provenance") == "crop_refined_child"
                else "accepted_direct"
                if accepted
                else "rejected_visual_continuation"
            )
            role = det.get("caption_role") or active.get(identity, {}).get("role") or "spoken_caption"
            det.update({
                "tracklet_id": identity,
                "observation_provenance": provenance,
                "observed_bbox": list(det.get("bbox") or []),
                "observed_timestamp": round(timestamp, 6),
                "inferred_visibility_end": round(min(video_duration, timestamp + observation_period_sec), 6),
                "visibility_interval_semantics": "half_open",
                "caption_role": role,
            })
            if not accepted:
                det["is_caption_candidate"] = True
                det["is_subtitle_candidate"] = True
            active[identity] = {
                "timestamp": timestamp,
                "normalized_bbox": det.get("normalized_bbox"),
                "role": role,
                "accepted_text": det.get("text") if accepted else active.get(identity, {}).get("accepted_text"),
            }
            claimed.add(identity)
        frame_result["caption_candidates"] = [det for det in detections if det.get("is_caption_candidate")]
        frame_result["subtitle_candidates"] = frame_result["caption_candidates"]


def _continuous_identity_style_compatible(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    required = ("estimated_text_color", "estimated_stroke_color", "estimated_font_height_ratio")
    if any(left.get(field) is None or right.get(field) is None for field in required):
        return False
    left_fill, right_fill = hex_to_rgb(left.get("estimated_text_color")), hex_to_rgb(right.get("estimated_text_color"))
    left_stroke, right_stroke = hex_to_rgb(left.get("estimated_stroke_color")), hex_to_rgb(right.get("estimated_stroke_color"))
    if not left_fill or not right_fill or not left_stroke or not right_stroke:
        return False
    fill_distance = math.dist(left_fill, right_fill) / CONTINUOUS_IDENTITY_COLOR_DISTANCE_SCALE
    stroke_distance = math.dist(left_stroke, right_stroke) / CONTINUOUS_IDENTITY_COLOR_DISTANCE_SCALE
    left_font = safe_float(left.get("estimated_font_height_ratio"), 0.0)
    right_font = safe_float(right.get("estimated_font_height_ratio"), 0.0)
    if min(left_font, right_font) <= 0:
        return False
    font_ratio = max(left_font, right_font) / min(left_font, right_font)
    return bool(
        fill_distance <= CONTINUOUS_IDENTITY_MAX_FILL_DISTANCE
        and stroke_distance <= CONTINUOUS_IDENTITY_MAX_STROKE_DISTANCE
        and font_ratio <= CONTINUOUS_IDENTITY_MAX_FONT_HEIGHT_RATIO
    )


def _continuous_identity_roles_compatible(left: Sequence[Tuple[float, Dict[str, Any]]], right: Sequence[Tuple[float, Dict[str, Any]]]) -> bool:
    left_roles = {item.get("caption_role") for _, item in left if item.get("caption_role")}
    right_roles = {item.get("caption_role") for _, item in right if item.get("caption_role")}
    return bool(left_roles and right_roles and left_roles & right_roles)


def _continuous_identity_ocr_similarity(left: Sequence[Tuple[float, Dict[str, Any]]], right: Sequence[Tuple[float, Dict[str, Any]]]) -> float:
    left_variants = {normalize_match_text(item.get("text")) for _, item in left if normalize_match_text(item.get("text"))}
    right_variants = {normalize_match_text(item.get("text")) for _, item in right if normalize_match_text(item.get("text"))}
    return max(
        (difflib.SequenceMatcher(None, left_text, right_text).ratio() for left_text in left_variants for right_text in right_variants),
        default=0.0,
    )


def apply_continuous_visual_identity_relations(frame_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Relate unambiguous fragmented tracklets without merging their evidence."""
    started = time.perf_counter()
    tracklets: Dict[str, List[Tuple[float, Dict[str, Any]]]] = {}
    for frame_result in frame_results:
        frame_timestamp = safe_float(frame_result.get("timestamp"), 0.0)
        for det in frame_result.get("detections") or []:
            tracklet_id = det.get("tracklet_id")
            if not tracklet_id:
                continue
            timestamp = safe_float(det.get("observed_timestamp"), frame_timestamp)
            tracklets.setdefault(str(tracklet_id), []).append((timestamp, det))
    for observations in tracklets.values():
        observations.sort(key=lambda row: row[0])

    windows: Dict[str, Dict[str, Any]] = {}
    for tracklet_id, observations in tracklets.items():
        windows[tracklet_id] = {
            "observed_start": observations[0][0],
            "last_observed": observations[-1][0],
            "inferred_visibility_end": max(
                safe_float(item.get("inferred_visibility_end"), timestamp) for timestamp, item in observations
            ),
            "first": observations[0][1],
            "last": observations[-1][1],
        }

    temporally_eligible_count = 0
    geometry_compatible_count = 0
    visual_compatible_count = 0
    compatible_pairs: List[Dict[str, Any]] = []
    # ponytail: O(n²) over caption tracklets; add spatial indexing only if measured reel-scale cost requires it.
    for predecessor_id, predecessor in tracklets.items():
        predecessor_window = windows[predecessor_id]
        for successor_id, successor in tracklets.items():
            if predecessor_id == successor_id:
                continue
            successor_window = windows[successor_id]
            gap = successor_window["observed_start"] - predecessor_window["inferred_visibility_end"]
            if gap < -1e-9 or gap > CONTINUOUS_IDENTITY_MAX_GAP_SEC + 1e-9:
                continue
            temporally_eligible_count += 1
            left, right = predecessor_window["last"], successor_window["first"]
            if not _compatible_continuation(left, right):
                continue
            geometry_compatible_count += 1
            if not _continuous_identity_style_compatible(left, right) or not _continuous_identity_roles_compatible(predecessor, successor):
                continue
            visual_compatible_count += 1
            ocr_similarity = _continuous_identity_ocr_similarity(predecessor, successor)
            if ocr_similarity < CONTINUOUS_IDENTITY_MIN_OCR_SIMILARITY:
                continue
            iou, center_distance, area_ratio, aspect_ratio = _continuation_geometry(left, right)
            compatible_pairs.append({
                "predecessor_tracklet_id": predecessor_id,
                "successor_tracklet_id": successor_id,
                "inferred_end_gap_sec": round(float(gap), 6),
                "endpoint_iou": round(float(iou), 6),
                "normalized_center_distance": round(float(center_distance), 6),
                "area_ratio": round(float(area_ratio), 6),
                "aspect_ratio_ratio": round(float(aspect_ratio), 6),
                "ocr_similarity": round(float(ocr_similarity), 6),
            })

    outgoing = {}
    for pair in compatible_pairs:
        outgoing.setdefault(pair["predecessor_tracklet_id"], set()).add(pair["successor_tracklet_id"])
    shortcut_pairs = {
        (predecessor_id, successor_id)
        for predecessor_id, middle_ids in outgoing.items()
        for middle_id in middle_ids
        for successor_id in outgoing.get(middle_id, set())
    }
    compatible_pairs = [
        pair for pair in compatible_pairs
        if (pair["predecessor_tracklet_id"], pair["successor_tracklet_id"]) not in shortcut_pairs
    ]

    successors: Dict[str, List[Dict[str, Any]]] = {}
    predecessors: Dict[str, List[Dict[str, Any]]] = {}
    for pair in compatible_pairs:
        successors.setdefault(pair["predecessor_tracklet_id"], []).append(pair)
        predecessors.setdefault(pair["successor_tracklet_id"], []).append(pair)
    linked_pairs = [
        pair for pair in compatible_pairs
        if len(successors.get(pair["predecessor_tracklet_id"], [])) == 1
        and len(predecessors.get(pair["successor_tracklet_id"], [])) == 1
    ]

    parent = {tracklet_id: tracklet_id for tracklet_id in tracklets}

    def find(tracklet_id: str) -> str:
        while parent[tracklet_id] != tracklet_id:
            parent[tracklet_id] = parent[parent[tracklet_id]]
            tracklet_id = parent[tracklet_id]
        return tracklet_id

    def union(left_id: str, right_id: str) -> None:
        left_root, right_root = find(left_id), find(right_id)
        if left_root != right_root:
            parent[right_root] = left_root

    for pair in linked_pairs:
        union(pair["predecessor_tracklet_id"], pair["successor_tracklet_id"])

    components: Dict[str, List[str]] = {}
    for tracklet_id in tracklets:
        components.setdefault(find(tracklet_id), []).append(tracklet_id)

    relations = []
    for component in components.values():
        if len(component) < 2:
            continue
        ordered_tracklets = sorted(component, key=lambda tracklet_id: (windows[tracklet_id]["observed_start"], tracklet_id))
        first_tracklet = ordered_tracklets[0]
        identity_id = f"continuous_visual_identity_{first_tracklet.rsplit('_', 1)[-1]}"
        observed_start = min(windows[tracklet_id]["observed_start"] for tracklet_id in ordered_tracklets)
        last_observed = max(windows[tracklet_id]["last_observed"] for tracklet_id in ordered_tracklets)
        inferred_end = max(windows[tracklet_id]["inferred_visibility_end"] for tracklet_id in ordered_tracklets)
        relation_links = [
            pair for pair in linked_pairs
            if pair["predecessor_tracklet_id"] in component and pair["successor_tracklet_id"] in component
        ]
        tracklet_windows = [
            {
                "tracklet_id": tracklet_id,
                "observed_start": round(float(windows[tracklet_id]["observed_start"]), 6),
                "last_observed": round(float(windows[tracklet_id]["last_observed"]), 6),
                "inferred_visibility_end": round(float(windows[tracklet_id]["inferred_visibility_end"]), 6),
            }
            for tracklet_id in ordered_tracklets
        ]
        for tracklet_id in ordered_tracklets:
            for _, det in tracklets[tracklet_id]:
                det.update({
                    "continuous_visual_identity_id": identity_id,
                    "continuous_visual_identity_tracklet_ids": list(ordered_tracklets),
                    "continuous_visual_identity_observed_start": round(float(observed_start), 6),
                    "continuous_visual_identity_last_observed": round(float(last_observed), 6),
                    "continuous_visual_identity_inferred_end": round(float(inferred_end), 6),
                    "continuous_visual_identity_interval_semantics": "half_open",
                })
        relations.append({
            "continuous_visual_identity_id": identity_id,
            "tracklet_ids": ordered_tracklets,
            "observed_start": round(float(observed_start), 6),
            "last_observed": round(float(last_observed), 6),
            "inferred_visibility_end": round(float(inferred_end), 6),
            "visibility_interval_semantics": "half_open",
            "tracklet_windows": tracklet_windows,
            "links": relation_links,
        })

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "tracklet_count": len(tracklets),
        "temporally_eligible_pair_count": temporally_eligible_count,
        "geometry_compatible_pair_count": geometry_compatible_count,
        "visual_compatible_pair_count": visual_compatible_count,
        "ocr_compatible_pair_count": len(compatible_pairs),
        "transitive_shortcut_pair_count": len(shortcut_pairs),
        "ambiguous_pair_count": len(compatible_pairs) - len(linked_pairs),
        "linked_pair_count": len(linked_pairs),
        "continuous_visual_identity_count": len(relations),
        "relations": sorted(relations, key=lambda relation: relation["continuous_visual_identity_id"]),
        "runtime_ms": round(float(elapsed_ms), 3),
        "transcript_used_for_eligibility": False,
        "thresholds": {
            "max_gap_sec": CONTINUOUS_IDENTITY_MAX_GAP_SEC,
            "min_iou": CONTINUATION_MIN_IOU,
            "max_center_distance": CONTINUATION_MAX_CENTER_DISTANCE,
            "max_area_ratio": CONTINUATION_MAX_AREA_RATIO,
            "max_aspect_ratio": CONTINUATION_MAX_ASPECT_RATIO,
            "max_fill_distance": CONTINUOUS_IDENTITY_MAX_FILL_DISTANCE,
            "max_stroke_distance": CONTINUOUS_IDENTITY_MAX_STROKE_DISTANCE,
            "max_font_height_ratio": CONTINUOUS_IDENTITY_MAX_FONT_HEIGHT_RATIO,
            "min_ocr_similarity": CONTINUOUS_IDENTITY_MIN_OCR_SIMILARITY,
        },
    }


def merge_bboxes(bboxes: Sequence[List[int]]) -> Optional[List[int]]:
    if not bboxes:
        return None
    return [int(min(b[0] for b in bboxes)), int(min(b[1] for b in bboxes)), int(max(b[2] for b in bboxes)), int(max(b[3] for b in bboxes))]


def group_caption_candidates(candidates: List[Dict[str, Any]], frame_shape: Tuple[int, int, int], y_tolerance: float = 0.05) -> List[Dict[str, Any]]:
    if not candidates:
        return []
    frame_h, frame_w = frame_shape[:2]
    sorted_items = sorted(candidates, key=lambda item: (item.get("center", {}).get("y", 0), item.get("center", {}).get("x", 0)))
    groups: List[Dict[str, Any]] = []

    for item in sorted_items:
        cy = safe_float((item.get("center") or {}).get("y"), 0.0)
        role = item.get("caption_role", "spoken_caption")
        assigned = False
        for group in groups:
            # Keep hook lines grouped separately from spoken captions; allow stacked hook lines to be separate samples.
            if group.get("role") != role:
                continue
            if abs(cy - safe_float(group.get("center_y_mean"), 0.0)) <= y_tolerance:
                group["items"].append(item)
                group["center_y_mean"] = float(np.mean([safe_float((x.get("center") or {}).get("y"), 0.0) for x in group["items"]]))
                assigned = True
                break
        if not assigned:
            groups.append({"center_y_mean": cy, "role": role, "items": [item]})

    final: List[Dict[str, Any]] = []
    for group in groups:
        items = sorted(group["items"], key=lambda item: item.get("bbox", [0, 0, 0, 0])[0])
        bboxes = [item["bbox"] for item in items if item.get("bbox")]
        bbox = merge_bboxes(bboxes)
        if not bbox:
            continue
        center = center_from_bbox(bbox, frame_w, frame_h)
        position = position_from_center(center["x"], center["y"])
        text = clean_text(" ".join(clean_text(item.get("text")) for item in items))
        confidence = float(np.mean([safe_float(item.get("confidence"), 0.0) for item in items]))
        scores = [safe_float((item.get("caption_score") or {}).get("score"), 0.0) for item in items]
        transcript_scores = [safe_float((item.get("caption_score") or {}).get("transcript_match_score"), 0.0) for item in items]
        hook_scores = [safe_float((item.get("caption_score") or {}).get("hook_score"), 0.0) for item in items]
        font_heights = [safe_int(item.get("estimated_font_height_px"), 0) for item in items if item.get("estimated_font_height_px") is not None]
        font_ratios = [safe_float(item.get("estimated_font_height_ratio"), 0.0) for item in items]
        text_colors = [item.get("estimated_text_color") for item in items if item.get("estimated_text_color")]
        stroke_colors = [item.get("estimated_stroke_color") for item in items if item.get("estimated_stroke_color")]
        shadow_colors = [item.get("estimated_shadow_color") for item in items if item.get("estimated_shadow_color")]
        text_area_ratios = [safe_float(item.get("text_area_ratio"), 0.0) for item in items]
        dark_area_ratios = [safe_float(item.get("dark_area_ratio"), 0.0) for item in items]
        saturated_area_ratios = [safe_float(item.get("saturated_area_ratio"), 0.0) for item in items]
        contrast_area_ratios = [safe_float(item.get("contrast_area_ratio"), 0.0) for item in items]
        roles = [item.get("caption_role", "spoken_caption") for item in items]
        role = max(set(roles), key=roles.count) if roles else "spoken_caption"
        reasons = [((item.get("caption_score") or {}).get("reason")) for item in items]
        members = []
        for member_index, item in enumerate(items, start=1):
            member_score = item.get("caption_score") or {}
            members.append({
                "member_id": f"member_{member_index:02d}",
                "text": clean_text(item.get("text")),
                "confidence": round(safe_float(item.get("confidence"), 0.0), 4),
                "caption_score": safe_float(member_score.get("score"), 0.0),
                "transcript_match_score": safe_float(member_score.get("transcript_match_score"), 0.0),
                "hook_score": safe_float(member_score.get("hook_score"), 0.0),
                "candidate_reason": member_score.get("reason"),
                "role": item.get("caption_role", "spoken_caption"),
                "tracklet_id": item.get("tracklet_id"),
                "continuous_visual_identity_id": item.get("continuous_visual_identity_id"),
                "continuous_visual_identity_tracklet_ids": item.get("continuous_visual_identity_tracklet_ids", []),
                "continuous_visual_identity_observed_start": item.get("continuous_visual_identity_observed_start"),
                "continuous_visual_identity_last_observed": item.get("continuous_visual_identity_last_observed"),
                "continuous_visual_identity_inferred_end": item.get("continuous_visual_identity_inferred_end"),
                "continuous_visual_identity_interval_semantics": item.get("continuous_visual_identity_interval_semantics"),
                "observation_provenance": item.get("observation_provenance"),
                "observed_bbox": item.get("observed_bbox"),
                "observed_timestamp": item.get("observed_timestamp"),
                "inferred_visibility_end": item.get("inferred_visibility_end"),
                "bbox": item.get("bbox"),
                "normalized_bbox": item.get("normalized_bbox"),
                "center": item.get("center"),
                "position": item.get("position"),
                "estimated_font_height_px": item.get("estimated_font_height_px"),
                "estimated_font_height_ratio": item.get("estimated_font_height_ratio"),
                "estimated_box_width_ratio": item.get("estimated_box_width_ratio"),
                "estimated_box_height_ratio": item.get("estimated_box_height_ratio"),
                "estimated_text_color": item.get("estimated_text_color"),
                "estimated_stroke_color": item.get("estimated_stroke_color"),
                "estimated_shadow_color": item.get("estimated_shadow_color"),
                "has_dark_stroke": item.get("has_dark_stroke"),
                "has_shadow": item.get("has_shadow"),
                "has_bright_text": item.get("has_bright_text"),
                "has_saturated_text": item.get("has_saturated_text"),
                "text_area_ratio": item.get("text_area_ratio"),
                "dark_area_ratio": item.get("dark_area_ratio"),
                "saturated_area_ratio": item.get("saturated_area_ratio"),
                "contrast_area_ratio": item.get("contrast_area_ratio"),
                "matched_cue_ids": member_score.get("matched_cue_ids", []),
            })

        final.append({
            "text": text,
            "confidence": round(confidence, 4),
            "caption_score": round(float(np.mean(scores)), 4) if scores else None,
            "transcript_match_score": round(float(np.mean(transcript_scores)), 4) if transcript_scores else 0.0,
            "hook_score": round(float(np.mean(hook_scores)), 4) if hook_scores else 0.0,
            "candidate_reason": max(set(reasons), key=reasons.count) if reasons else None,
            "role": role,
            "tracklet_ids": sorted({item.get("tracklet_id") for item in items if item.get("tracklet_id")}),
            "continuous_visual_identity_ids": sorted({item.get("continuous_visual_identity_id") for item in items if item.get("continuous_visual_identity_id")}),
            "observation_provenance": sorted({item.get("observation_provenance") for item in items if item.get("observation_provenance")}),
            "observed_bbox": bbox,
            "observed_timestamp": max((safe_float(item.get("observed_timestamp"), 0.0) for item in items), default=None),
            "inferred_visibility_end": max((safe_float(item.get("inferred_visibility_end"), 0.0) for item in items), default=None),
            "bbox": bbox,
            "normalized_bbox": bbox_to_normalized(bbox, frame_w, frame_h),
            "center": center,
            "position": position,
            "line_count_estimate": len(items),
            "estimated_font_height_px": int(np.median(font_heights)) if font_heights else None,
            "estimated_font_height_ratio": round(float(np.median(font_ratios)), 5) if font_ratios else None,
            "estimated_box_width_ratio": round((bbox[2] - bbox[0]) / frame_w, 4),
            "estimated_box_height_ratio": round((bbox[3] - bbox[1]) / frame_h, 4),
            "estimated_text_color": median_hex_color(text_colors, fallback="#ffffff"),
            "estimated_stroke_color": median_hex_color(stroke_colors, fallback="#000000"),
            "estimated_shadow_color": median_hex_color(shadow_colors, fallback="#000000"),
            "has_dark_stroke": bool(np.mean([1 if item.get("has_dark_stroke") else 0 for item in items]) >= 0.35),
            "has_shadow": bool(np.mean([1 if item.get("has_shadow") else 0 for item in items]) >= 0.35),
            "has_bright_text": bool(np.mean([1 if item.get("has_bright_text") else 0 for item in items]) >= 0.35),
            "has_saturated_text": bool(np.mean([1 if item.get("has_saturated_text") else 0 for item in items]) >= 0.35),
            "text_area_ratio": round(float(np.mean(text_area_ratios)), 5) if text_area_ratios else None,
            "dark_area_ratio": round(float(np.mean(dark_area_ratios)), 5) if dark_area_ratios else None,
            "saturated_area_ratio": round(float(np.mean(saturated_area_ratios)), 5) if saturated_area_ratios else None,
            "contrast_area_ratio": round(float(np.mean(contrast_area_ratios)), 5) if contrast_area_ratios else None,
            "items_count": len(items),
            "matched_cue_ids": sorted(set(sum([(item.get("caption_score") or {}).get("matched_cue_ids", []) for item in items], []))),
            "members": members,
        })
    return final


# -----------------------------
# Style profiles and resolved style
# -----------------------------


def flatten_frame_items(frame_results: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for frame in frame_results:
        out.extend(frame.get(key, []) or [])
    return out



def color_family_from_hex(hex_color: Any) -> str:
    rgb = hex_to_rgb(hex_color)
    if not rgb:
        return "unknown"
    r, g, b = rgb
    bgr = [b, g, r]
    hsv = cv2.cvtColor(np.uint8([[bgr]]), cv2.COLOR_BGR2HSV)[0][0]
    hue, sat, val = float(hsv[0]), float(hsv[1]), float(hsv[2])
    if val >= 205 and sat <= 80:
        return "white"
    if val <= 85:
        return "dark"
    if sat >= 100:
        if hue <= 10 or hue >= 170:
            return "red"
        if 10 < hue <= 28:
            return "orange"
        if 28 < hue <= 45:
            return "yellow"
        if 45 < hue <= 85:
            return "green"
        if 85 < hue <= 135:
            return "blue"
        return "magenta"
    return "neutral"


def position_family(group: Dict[str, Any]) -> str:
    pos = group.get("position") or {}
    vertical = pos.get("vertical_zone", "middle")
    align = pos.get("horizontal_align", "center")
    return f"{vertical}_{align}"

def style_bucket_key(group: Dict[str, Any]) -> str:
    """
    v5.1 profile bucketing.

    Use color families, not exact sampled hex values. OCR crops vary frame to
    frame, and exact hex bucketing split one real style into many profiles.
    """
    role = group.get("role") or "spoken_caption"
    fill_family = color_family_from_hex(group.get("estimated_text_color") or "#ffffff")
    stroke_family = color_family_from_hex(group.get("estimated_stroke_color") or "#000000")
    pos_family = position_family(group)
    case = infer_case_style([group.get("text", "")])
    font_ratio = safe_float(group.get("estimated_font_height_ratio"), 0.0)
    if font_ratio >= 0.10:
        size = "huge"
    elif font_ratio >= 0.055:
        size = "large"
    elif font_ratio >= 0.024:
        size = "medium"
    else:
        size = "small"
    return f"{role}|{fill_family}|{stroke_family}|{pos_family}|{size}|{case}"


def safe_median(values: Sequence[Any], default: Any = None) -> Any:
    clean = []
    for value in values:
        try:
            if value is not None:
                clean.append(float(value))
        except Exception:
            pass
    if not clean:
        return default
    return float(np.median(clean))


def infer_density(groups: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    texts = [clean_text(g.get("text")) for g in groups if clean_text(g.get("text"))]
    if not texts:
        return {"label": "unknown", "median_words_per_group": None, "median_chars_per_group": None}
    wc = [words_count(t) for t in texts]
    cc = [len(t) for t in texts]
    mw = safe_median(wc, None)
    mc = safe_median(cc, None)
    if mw is not None and mw <= 1.25:
        label = "word_by_word"
    elif mw is not None and mw <= 4:
        label = "short_phrase"
    else:
        label = "sentence_or_line"
    return {"label": label, "median_words_per_group": round(mw, 3) if mw is not None else None, "median_chars_per_group": round(mc, 3) if mc is not None else None}


def build_style_profiles(groups: List[Dict[str, Any]], video_info: Dict[str, Any], max_profiles: int = 5) -> List[Dict[str, Any]]:
    if not groups:
        return []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for group in groups:
        buckets.setdefault(style_bucket_key(group), []).append(group)

    profiles: List[Dict[str, Any]] = []
    frame_h = safe_float(video_info.get("height"), 0.0)
    for idx, (key, bucket) in enumerate(sorted(buckets.items(), key=lambda kv: len(kv[1]), reverse=True), start=1):
        centers_x = [safe_float((g.get("center") or {}).get("x"), 0.5) for g in bucket]
        centers_y = [safe_float((g.get("center") or {}).get("y"), 0.5) for g in bucket]
        font_px = [safe_float(g.get("estimated_font_height_px"), 0.0) for g in bucket if g.get("estimated_font_height_px") is not None]
        font_ratio = [safe_float(g.get("estimated_font_height_ratio"), 0.0) for g in bucket if g.get("estimated_font_height_ratio") is not None]
        fill_colors = [g.get("estimated_text_color") for g in bucket if g.get("estimated_text_color")]
        stroke_colors = [g.get("estimated_stroke_color") for g in bucket if g.get("estimated_stroke_color")]
        shadow_colors = [g.get("estimated_shadow_color") for g in bucket if g.get("estimated_shadow_color")]
        texts = [g.get("text") for g in bucket if g.get("text")]
        role_counts: Dict[str, int] = {}
        for g in bucket:
            role = g.get("role") or "spoken_caption"
            role_counts[role] = role_counts.get(role, 0) + 1
        role = max(role_counts, key=role_counts.get)
        cx = safe_median(centers_x, 0.5)
        cy = safe_median(centers_y, 0.72)
        pos = position_from_center(cx, cy)
        stroke_ratio = float(np.mean([1 if g.get("has_dark_stroke") else 0 for g in bucket]))
        shadow_ratio = float(np.mean([1 if g.get("has_shadow") else 0 for g in bucket]))
        sat_ratio = float(np.mean([1 if g.get("has_saturated_text") else 0 for g in bucket]))
        avg_score = safe_median([g.get("caption_score") for g in bucket], 0.0)
        avg_match = safe_median([g.get("transcript_match_score") for g in bucket], 0.0)
        avg_hook = safe_median([g.get("hook_score") for g in bucket], 0.0)
        density = infer_density(bucket)
        case_style = infer_case_style(texts)
        profile_id = f"style_{idx:02d}_{role}"
        font_h_px = int(round(safe_median(font_px, 0))) if font_px else None
        font_h_ratio = safe_median(font_ratio, None)
        if font_h_ratio is None and font_h_px and frame_h:
            font_h_ratio = font_h_px / frame_h
        confidence = clamp((0.45 * min(1.0, len(bucket) / 8.0)) + (0.30 * safe_float(avg_score, 0.0)) + (0.15 * safe_float(avg_match, 0.0)) + (0.10 * safe_float(avg_hook, 0.0)), 0.0, 1.0)
        profile = {
            "style_id": profile_id,
            "bucket_key": key,
            "role": role,
            "sample_count": len(bucket),
            "confidence": {"score": round(float(confidence), 4), "label": "high" if confidence >= 0.72 else "medium" if confidence >= 0.45 else "low"},
            "example_texts": texts[:8],
            "placement": {
                "position": f"{pos['vertical_zone']}_{pos['horizontal_align']}",
                "vertical_zone": pos["vertical_zone"],
                "horizontal_align": pos["horizontal_align"],
                "anchor": {"x": round(float(cx), 4), "y": round(float(cy), 4), "coordinate_space": "normalized_frame"},
                "center_x_std": round(float(np.std(centers_x)), 4) if centers_x else None,
                "center_y_std": round(float(np.std(centers_y)), 4) if centers_y else None,
            },
            "typography": {
                "font_family": "unknown",
                "font_weight": "bold" if (font_h_ratio or 0) >= 0.05 or stroke_ratio >= 0.35 else "semibold_or_regular",
                "font_style": "normal_or_unknown",
                "font_height_px": font_h_px,
                "font_height_ratio": round(float(font_h_ratio), 5) if font_h_ratio is not None else None,
                "case_style": case_style,
                "density": density,
                "line_count_estimate": {"median": safe_median([g.get("line_count_estimate") for g in bucket], None), "max": max([safe_int(g.get("line_count_estimate"), 0) for g in bucket], default=None)},
            },
            "colors": {
                "fill": median_hex_color(fill_colors, fallback="#ffffff"),
                "stroke": median_hex_color(stroke_colors, fallback="#000000"),
                "shadow": median_hex_color(shadow_colors, fallback="#000000"),
                "background": None,
            },
            "stroke": {
                "enabled": bool(stroke_ratio >= 0.25 or median_hex_color(stroke_colors, "#000000") != "#000000"),
                "color": median_hex_color(stroke_colors, fallback="#000000"),
                "width_px_estimate": max(1, int(round((font_h_px or 40) * (0.075 if role == "hook_caption" else 0.055)))) if stroke_ratio >= 0.2 else None,
                "sample_ratio": round(stroke_ratio, 4),
            },
            "shadow": {
                "enabled": bool(shadow_ratio >= 0.2),
                "color": median_hex_color(shadow_colors, fallback="#000000"),
                "opacity_estimate": round(clamp(shadow_ratio, 0.0, 0.85), 4),
                "blur_px_estimate": 2 if shadow_ratio >= 0.2 else None,
            },
            "background_box": {"enabled": False, "style": "none_or_not_detected", "color": None, "opacity": 0.0},
            "animation": {
                "detected": False,
                "style": "unknown_or_static_from_sampling",
                "reason": "v5 detects visual style from sampled frames; true animation requires tracking same cue across adjacent frames.",
            },
            "diagnostics": {
                "avg_caption_score": round(float(avg_score), 4) if avg_score is not None else None,
                "avg_transcript_match_score": round(float(avg_match), 4) if avg_match is not None else None,
                "avg_hook_score": round(float(avg_hook), 4) if avg_hook is not None else None,
                "saturated_sample_ratio": round(sat_ratio, 4),
            },
        }
        profiles.append(profile)
    return profiles[:max_profiles]


def choose_primary_profile(profiles: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not profiles:
        return None
    spoken = [p for p in profiles if p.get("role") == "spoken_caption"]
    if spoken:
        return sorted(spoken, key=lambda p: (p.get("confidence", {}).get("score", 0), p.get("sample_count", 0)), reverse=True)[0]
    return sorted(profiles, key=lambda p: (p.get("confidence", {}).get("score", 0), p.get("sample_count", 0)), reverse=True)[0]


def build_caption_style_resolved(profiles: List[Dict[str, Any]], groups: List[Dict[str, Any]], video_info: Dict[str, Any], cfg: Dict[str, Any]) -> Dict[str, Any]:
    primary = choose_primary_profile(profiles)
    available = bool(primary)
    frames_with = len(set(g.get("frame_index") for g in groups if g.get("frame_index") is not None))
    frames_analyzed = safe_int(cfg.get("frames_analyzed"), 0)
    coverage = frames_with / max(1, frames_analyzed)

    if not primary:
        return {
            "available": False,
            "schema": "caption_style_resolved",
            "schema_version": "3.0",
            "source": "transcript_aware_viral_ocr",
            "confidence": {"label": "none", "score": 0.0, "frame_coverage_ratio": 0.0, "frames_with_subtitles": 0, "frames_analyzed": frames_analyzed, "subtitle_groups_count": 0},
            "placement": {"position": "bottom_center", "vertical_zone": "bottom", "horizontal_align": "center", "anchor": {"x": 0.5, "y": 0.72, "coordinate_space": "normalized_frame"}, "safe_area": {"respect_safe_area": True, "recommended_bottom_margin_ratio": 0.10}},
            "typography": {"font_family": "unknown", "font_weight": "regular_or_unknown", "font_style": "normal_or_unknown", "font_height_px": None, "font_height_ratio": None, "case_style": "unknown", "density": {"label": "unknown"}},
            "colors": {"fill": "#ffffff", "stroke": "#000000", "shadow": "#000000", "background": None},
            "stroke": {"enabled": False, "color": "#000000", "width_px_estimate": None},
            "shadow": {"enabled": False, "color": "#000000", "opacity_estimate": 0.0, "blur_px_estimate": None},
            "background_box": {"enabled": False, "style": "none_or_not_detected", "color": None, "opacity": 0.0},
            "animation": {"detected": False, "style": "unknown", "reason": "no reliable caption samples"},
            "renderer_hints": {"preferred_layer_type": "editable_text", "resolve_target": "SubtitleTrack_or_TextPlus", "openreel_target": "text_layer", "capcut_target": "caption_style", "one_word_mode_compatible": False, "clone_priority": ["placement", "font_height_ratio", "fill_color", "stroke", "shadow", "case_style"]},
            "diagnostics": {"filter_config": cfg},
        }

    score = safe_float(primary.get("confidence", {}).get("score"), 0.0)
    label = "high" if score >= 0.72 else "medium" if score >= 0.45 else "low"
    return {
        "available": True,
        "schema": "caption_style_resolved",
        "schema_version": "3.0",
        "source": "transcript_aware_viral_ocr",
        "primary_style_id": primary.get("style_id"),
        "confidence": {"label": label, "score": round(score, 4), "frame_coverage_ratio": round(coverage, 4), "frames_with_subtitles": frames_with, "frames_analyzed": frames_analyzed, "subtitle_groups_count": len(groups), "profiles_count": len(profiles)},
        "placement": primary.get("placement", {}),
        "typography": primary.get("typography", {}),
        "colors": primary.get("colors", {}),
        "stroke": primary.get("stroke", {}),
        "shadow": primary.get("shadow", {}),
        "background_box": primary.get("background_box", {}),
        "animation": primary.get("animation", {}),
        "renderer_hints": {
            "preferred_layer_type": "editable_text",
            "resolve_target": "SubtitleTrack_or_TextPlus",
            "openreel_target": "text_layer",
            "capcut_target": "caption_style",
            "one_word_mode_compatible": (primary.get("typography", {}).get("density", {}).get("label") == "word_by_word"),
            "supports_multiple_profiles": True,
            "clone_priority": ["placement", "font_height_ratio", "fill_color", "stroke", "shadow", "case_style", "style_profiles"],
        },
        "diagnostics": {"filter_config": cfg, "primary_profile_diagnostics": primary.get("diagnostics", {})},
    }




# -----------------------------
# Per-cue style events
# -----------------------------


def profile_map_by_bucket(profiles: List[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for profile in profiles or []:
        if not isinstance(profile, dict):
            continue
        bucket = profile.get("bucket_key")
        style_id = profile.get("style_id")
        if bucket and style_id:
            mapping[str(bucket)] = str(style_id)
    return mapping


def choose_profile_id_for_group(group: Dict[str, Any], profiles: List[Dict[str, Any]]) -> str:
    """Assign the most likely style profile to a detected caption group."""
    if not profiles:
        return "style_00_unknown"

    bucket = style_bucket_key(group)
    by_bucket = profile_map_by_bucket(profiles)
    if bucket in by_bucket:
        return by_bucket[bucket]

    role = group.get("role") or "spoken_caption"
    same_role = [p for p in profiles if p.get("role") == role]
    pool = same_role or profiles

    def _score(profile: Dict[str, Any]) -> Tuple[float, int]:
        conf = safe_float((profile.get("confidence") or {}).get("score"), 0.0)
        count = safe_int(profile.get("sample_count"), 0)
        return conf, count

    best = sorted(pool, key=_score, reverse=True)[0]
    return str(best.get("style_id") or "style_00_unknown")


def cue_lookup_by_id(transcript_cues: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(cue.get("id")): cue for cue in transcript_cues or [] if cue.get("id") is not None}


def choose_best_cue_for_group(
    group: Dict[str, Any],
    transcript_cues: List[Dict[str, Any]],
    max_window_sec: float = 1.25,
    min_score: float = 0.18,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Choose the transcript/subtitle cue that best explains this visual caption sample."""
    if not transcript_cues:
        return None, {
            "method": "no_transcript",
            "score": 0.0,
            "text_similarity": 0.0,
            "time_score": 0.0,
            "reason": "transcript_cues_unavailable",
        }

    timestamp = safe_float(group.get("timestamp"), 0.0)
    group_text = clean_text(group.get("text"))
    by_id = cue_lookup_by_id(transcript_cues)

    candidate_cues: List[Dict[str, Any]] = []
    for cue_id in group.get("matched_cue_ids", []) or []:
        cue = by_id.get(str(cue_id))
        if cue:
            candidate_cues.append(cue)

    # A truncated nearby-ID list must not hide an exact, concurrent word cue.
    if not any(normalize_match_text(cue["text"]) == normalize_match_text(group_text) for cue in candidate_cues):
        candidate_cues.extend(cue for cue in transcript_cues
                              if cue.get("source") in {"subtitle_candidates", "subtitle_clips", "words"}
                              and normalize_match_text(cue["text"]) == normalize_match_text(group_text)
                              and cue["start"] <= timestamp <= cue["end"]
                              and cue not in candidate_cues)

    if not candidate_cues:
        for cue in transcript_cues:
            start = safe_float(cue.get("start"), 0.0)
            end = safe_float(cue.get("end"), start)
            mid = safe_float(cue.get("mid"), (start + end) / 2.0)
            # Include cues near the sampled frame; this keeps the search local.
            if (start - max_window_sec) <= timestamp <= (end + max_window_sec) or abs(timestamp - mid) <= max_window_sec:
                candidate_cues.append(cue)

    if not candidate_cues and transcript_cues:
        candidate_cues = sorted(
            transcript_cues,
            key=lambda cue: abs(timestamp - safe_float(cue.get("mid"), safe_float(cue.get("start"), 0.0))),
        )[:8]

    best: Optional[Dict[str, Any]] = None
    best_info: Dict[str, Any] = {
        "method": "none",
        "score": 0.0,
        "text_similarity": 0.0,
        "time_score": 0.0,
        "reason": "no_suitable_cue",
    }

    for cue in candidate_cues:
        cue_text = clean_text(cue.get("text"))
        text_sim = fuzzy_similarity(group_text, cue_text)
        start = safe_float(cue.get("start"), 0.0)
        end = safe_float(cue.get("end"), start)
        mid = safe_float(cue.get("mid"), (start + end) / 2.0)
        if start <= timestamp <= end:
            time_score = 1.0
        else:
            dist = min(abs(timestamp - start), abs(timestamp - mid), abs(timestamp - end))
            time_score = clamp(1.0 - (dist / max(0.05, max_window_sec)), 0.0, 1.0)

        # Hook/graphic text often has weaker direct transcript overlap, so keep
        # time locality important. Spoken captions usually win via text_sim.
        score = (0.62 * text_sim) + (0.38 * time_score)

        if score > safe_float(best_info.get("score"), 0.0):
            best = cue
            best_info = {
                "method": "matched_cue_ids" if group.get("matched_cue_ids") else "nearest_time_text",
                "score": round(float(score), 4),
                "text_similarity": round(float(text_sim), 4),
                "time_score": round(float(time_score), 4),
                "reason": "accepted" if score >= min_score else "below_min_score",
            }

    if best and safe_float(best_info.get("score"), 0.0) >= min_score:
        return best, best_info
    return None, best_info


def safe_mode(values: Sequence[Any], default: Any = None) -> Any:
    vals = [v for v in values if v is not None]
    if not vals:
        return default
    counts: Dict[Any, int] = {}
    for value in vals:
        try:
            key = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
        except Exception:
            key = str(value)
        counts[key] = counts.get(key, 0) + 1
    best_key = max(counts, key=counts.get)
    for value in vals:
        try:
            key = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value
        except Exception:
            key = str(value)
        if key == best_key:
            return value
    return vals[0]


def median_bbox(bboxes: Sequence[List[int]]) -> Optional[List[int]]:
    clean = [b for b in bboxes if isinstance(b, list) and len(b) == 4]
    if not clean:
        return None
    arr = np.asarray(clean, dtype=np.float32)
    return [int(round(x)) for x in np.median(arr, axis=0).tolist()]


def estimate_event_animation(
    observations: List[Dict[str, Any]],
    min_samples: int = 3,
    max_samples: int = 7,
) -> Dict[str, Any]:
    """
    Estimate caption animation from adjacent frame observations of the same cue.

    This is intentionally conservative. It does not render animation; it emits a
    reusable animation contract for the downstream FCPXML/Resolve controller:
      - bbox scale changes -> pop / scale
      - text-area/contrast changes -> fade
      - center position drift -> slide

    Reliable detection needs 3-7 close samples. With fewer samples the event is
    marked as unresolved instead of inventing an animation.
    """
    usable = [g for g in observations or [] if isinstance(g, dict)]
    if len(usable) < max(2, int(min_samples)):
        return {
            "detected": False,
            "type": "unknown_or_static_insufficient_samples",
            "style": "unknown_or_static_insufficient_samples",
            "confidence": 0.0,
            "samples": len(usable),
            "required_samples": max(2, int(min_samples)),
            "reason": "needs_3_to_7_adjacent_samples_for_animation_tracking",
            "keyframes": [],
        }

    ordered = sorted(usable, key=lambda g: safe_float(g.get("timestamp"), 0.0))
    if max_samples and len(ordered) > max_samples:
        # Keep first/middle/last-ish observations while limiting noise.
        idxs = np.linspace(0, len(ordered) - 1, max_samples).round().astype(int).tolist()
        ordered = [ordered[i] for i in sorted(set(idxs))]

    timestamps = [safe_float(g.get("timestamp"), 0.0) for g in ordered]
    widths = [safe_float(g.get("estimated_box_width_ratio"), 0.0) for g in ordered]
    heights = [safe_float(g.get("estimated_box_height_ratio"), 0.0) for g in ordered]
    centers_x = [safe_float((g.get("center") or {}).get("x"), 0.5) for g in ordered]
    centers_y = [safe_float((g.get("center") or {}).get("y"), 0.5) for g in ordered]

    # Opacity/visibility proxy. OCR does not expose alpha; use visible text pixel
    # area + contrast as a stable approximation.
    text_area = [safe_float(g.get("text_area_ratio"), 0.0) for g in ordered]
    contrast_area = [safe_float(g.get("contrast_area_ratio"), 0.0) for g in ordered]
    bright_flags = [1.0 if g.get("has_bright_text") else 0.0 for g in ordered]
    opacity_proxy = []
    for ta, ca, bf in zip(text_area, contrast_area, bright_flags):
        opacity_proxy.append(clamp((0.52 * ta * 7.0) + (0.38 * ca * 2.2) + (0.10 * bf), 0.0, 1.0))

    scale = []
    for w, h in zip(widths, heights):
        # Geometric bbox scale proxy. Robust for pop captions where OCR bbox grows.
        scale.append(math.sqrt(max(1e-9, w * h)))

    scale_med = float(np.median(scale)) if scale else 0.0
    scale_min = min(scale) if scale else 0.0
    scale_max = max(scale) if scale else 0.0
    scale_range = (scale_max - scale_min) / max(1e-6, scale_med) if scale else 0.0
    scale_peak_idx = int(np.argmax(scale)) if scale else 0

    opacity_med = float(np.median(opacity_proxy)) if opacity_proxy else 0.0
    opacity_min = min(opacity_proxy) if opacity_proxy else 0.0
    opacity_max = max(opacity_proxy) if opacity_proxy else 0.0
    opacity_range = opacity_max - opacity_min
    opacity_peak_idx = int(np.argmax(opacity_proxy)) if opacity_proxy else 0

    x_delta = max(centers_x) - min(centers_x) if centers_x else 0.0
    y_delta = max(centers_y) - min(centers_y) if centers_y else 0.0
    motion_delta = math.sqrt((x_delta * x_delta) + (y_delta * y_delta))
    first_cx, first_cy = centers_x[0], centers_y[0]
    last_cx, last_cy = centers_x[-1], centers_y[-1]
    direction = "none"
    if motion_delta >= 0.018:
        dx = last_cx - first_cx
        dy = last_cy - first_cy
        if abs(dx) >= abs(dy):
            direction = "right" if dx > 0 else "left"
        else:
            direction = "down" if dy > 0 else "up"

    # Pattern classification.
    has_scale = scale_range >= 0.16
    has_fade = opacity_range >= 0.18
    has_slide = motion_delta >= 0.028
    pop_like = bool(has_scale and 0 < scale_peak_idx < len(scale) - 1 and scale[scale_peak_idx] >= scale[0] and scale[scale_peak_idx] >= scale[-1])

    if pop_like and has_fade:
        anim_type = "pop_fade"
        detected = True
        confidence = 0.40 + min(0.30, scale_range) + min(0.25, opacity_range)
    elif pop_like:
        anim_type = "scale_pop"
        detected = True
        confidence = 0.42 + min(0.40, scale_range)
    elif has_scale:
        anim_type = "scale"
        detected = True
        confidence = 0.36 + min(0.36, scale_range)
    elif has_slide and has_fade:
        anim_type = "slide_fade"
        detected = True
        confidence = 0.38 + min(0.30, motion_delta * 4.0) + min(0.22, opacity_range)
    elif has_slide:
        anim_type = "slide"
        detected = True
        confidence = 0.36 + min(0.42, motion_delta * 5.0)
    elif has_fade:
        anim_type = "fade"
        detected = True
        confidence = 0.34 + min(0.44, opacity_range)
    else:
        anim_type = "static"
        detected = False
        confidence = 0.22

    confidence = clamp(confidence, 0.0, 0.92)

    # Normalized keyframes that a later Resolve/Fusion applier can convert into
    # Text+/Transform keyframes. Scale values are relative to median observed scale.
    def rel_scale(value: float) -> float:
        return round(clamp(value / max(1e-6, scale_med), 0.35, 2.5), 4)

    keyframe_idxs = sorted(set([0, scale_peak_idx, opacity_peak_idx, len(ordered) - 1]))
    keyframes: List[Dict[str, Any]] = []
    start_time = timestamps[0] if timestamps else 0.0
    end_time = timestamps[-1] if timestamps else start_time
    duration = max(1e-6, end_time - start_time)
    for idx in keyframe_idxs:
        keyframes.append({
            "sample_index": idx,
            "timestamp": round(float(timestamps[idx]), 4),
            "relative_time": round(float((timestamps[idx] - start_time) / duration), 4) if duration > 0 else 0.0,
            "scale": rel_scale(scale[idx]),
            "opacity_proxy": round(float(opacity_proxy[idx]), 4),
            "position": {"x": round(float(centers_x[idx]), 4), "y": round(float(centers_y[idx]), 4)},
            "bbox": ordered[idx].get("normalized_bbox") or ordered[idx].get("bbox"),
        })

    return {
        "detected": bool(detected),
        "type": anim_type,
        "style": anim_type,
        "confidence": round(float(confidence), 4),
        "samples": len(ordered),
        "sample_timestamps": [round(float(t), 4) for t in timestamps],
        "metrics": {
            "scale_range_ratio": round(float(scale_range), 4),
            "scale_min_rel": rel_scale(scale_min) if scale else None,
            "scale_max_rel": rel_scale(scale_max) if scale else None,
            "scale_peak_index": scale_peak_idx,
            "opacity_range": round(float(opacity_range), 4),
            "opacity_min": round(float(opacity_min), 4),
            "opacity_max": round(float(opacity_max), 4),
            "opacity_peak_index": opacity_peak_idx,
            "position_delta": {"x": round(float(x_delta), 4), "y": round(float(y_delta), 4), "euclidean": round(float(motion_delta), 4), "direction": direction},
        },
        "keyframes": keyframes,
        "reason": "estimated_from_adjacent_frame_bbox_scale_opacity_position" if detected else "no_strong_scale_fade_or_slide_pattern_detected",
    }


def aggregate_style_event(
    event_id: str,
    observations: List[Dict[str, Any]],
    profile_id: str,
    cue: Optional[Dict[str, Any]],
    match_info: Dict[str, Any],
    visual_identity: Dict[str, Any],
    video_info: Dict[str, Any],
    visual_index: int,
    args: Optional[argparse.Namespace] = None,
) -> Dict[str, Any]:
    observations = sorted(observations, key=lambda g: safe_float(g.get("timestamp"), 0.0))
    best = sorted(
        observations,
        key=lambda g: (
            safe_float(g.get("caption_score"), 0.0),
            safe_float(g.get("transcript_match_score"), 0.0),
            safe_float(g.get("hook_score"), 0.0),
            safe_float(g.get("confidence"), 0.0),
        ),
        reverse=True,
    )[0]

    frame_w = safe_int(video_info.get("width"), 0)
    frame_h = safe_int(video_info.get("height"), 0)

    centers_x = [safe_float((g.get("center") or {}).get("x"), 0.5) for g in observations]
    centers_y = [safe_float((g.get("center") or {}).get("y"), 0.5) for g in observations]
    cx = safe_median(centers_x, safe_float((best.get("center") or {}).get("x"), 0.5))
    cy = safe_median(centers_y, safe_float((best.get("center") or {}).get("y"), 0.5))
    pos = position_from_center(cx, cy)

    bbox = median_bbox([g.get("bbox") for g in observations if g.get("bbox")])
    normalized_bbox = None
    if bbox and frame_w and frame_h:
        normalized_bbox = bbox_to_normalized(bbox, frame_w, frame_h)

    font_px = safe_median([g.get("estimated_font_height_px") for g in observations], best.get("estimated_font_height_px"))
    font_ratio = safe_median([g.get("estimated_font_height_ratio") for g in observations], best.get("estimated_font_height_ratio"))
    width_ratio = safe_median([g.get("estimated_box_width_ratio") for g in observations], best.get("estimated_box_width_ratio"))
    height_ratio = safe_median([g.get("estimated_box_height_ratio") for g in observations], best.get("estimated_box_height_ratio"))

    fill = median_hex_color([g.get("estimated_text_color") for g in observations if g.get("estimated_text_color")], best.get("estimated_text_color") or "#ffffff")
    stroke = median_hex_color([g.get("estimated_stroke_color") for g in observations if g.get("estimated_stroke_color")], best.get("estimated_stroke_color") or "#000000")
    shadow = median_hex_color([g.get("estimated_shadow_color") for g in observations if g.get("estimated_shadow_color")], best.get("estimated_shadow_color") or stroke)

    stroke_ratio = float(np.mean([1 if g.get("has_dark_stroke") else 0 for g in observations]))
    shadow_ratio = float(np.mean([1 if g.get("has_shadow") else 0 for g in observations]))
    sat_ratio = float(np.mean([1 if g.get("has_saturated_text") else 0 for g in observations]))

    observed_timestamps = [
        safe_float(g.get("observed_timestamp"), safe_float(g.get("timestamp"), 0.0))
        for g in observations
    ]
    start = safe_float(visual_identity.get("observed_start"), min(observed_timestamps))
    last_observed = safe_float(visual_identity.get("last_observed"), max(observed_timestamps))
    inferred_ends = [
        safe_float(g.get("inferred_visibility_end"), 0.0)
        for g in observations
        if g.get("inferred_visibility_end") is not None
    ]
    end = safe_float(visual_identity.get("inferred_end"), max(inferred_ends, default=last_observed))
    if end <= start:
        end = start + max(0.15, min(1.0, safe_float(best.get("duration"), 0.35) or 0.35))
    text = clean_text(cue.get("text") if cue else best.get("text"))
    cue_id = cue.get("id") if cue else None
    source = "transcript_annotated_visual_event" if cue else "visual_event_without_transcript_cue"

    role = safe_mode([g.get("role") for g in observations], best.get("role") or "spoken_caption")
    observed_texts = [clean_text(g.get("text")) for g in observations if clean_text(g.get("text"))]
    confidence = clamp(
        (0.35 * safe_median([g.get("caption_score") for g in observations], 0.0))
        + (0.25 * safe_median([g.get("transcript_match_score") for g in observations], 0.0))
        + (0.20 * min(1.0, len(observations) / 3.0))
        + (0.20 * safe_float(best.get("confidence"), 0.0)),
        0.0,
        1.0,
    )

    animation = estimate_event_animation(
        observations,
        min_samples=max(2, safe_int(getattr(args, "animation_min_samples", 3), 3)) if args is not None else 3,
        max_samples=max(3, safe_int(getattr(args, "animation_max_samples", 7), 7)) if args is not None else 7,
    )

    return {
        "event_id": event_id,
        "schema": "caption_style_event",
        "schema_version": "1.2",
        "source": source,
        "cue_id": cue_id,
        "label_source": "transcript_cue" if cue else "image_ocr",
        "text": text,
        "observed_text": clean_text(safe_mode(observed_texts, best.get("text"))),
        "observed_texts": observed_texts[:8],
        "start": round(float(start), 4),
        "end": round(float(end), 4),
        "mid": round(float((start + end) / 2.0), 4),
        "duration": round(float(end - start), 4),
        "visual_event_identity": visual_identity.get("visual_event_identity"),
        "continuous_visual_identity_id": visual_identity.get("continuous_visual_identity_id"),
        "tracklet_ids": visual_identity.get("tracklet_ids", []),
        "observation_provenance": visual_identity.get("observation_provenance", []),
        "observed_start": round(float(start), 4),
        "last_observed": round(float(last_observed), 4),
        "inferred_visual_end": round(float(end), 4),
        "visibility_interval_semantics": "half_open",
        "semantic_reference": {
            "cue_id": cue_id,
            "cue_text": clean_text(cue.get("text")) if cue else None,
            "cue_start": cue.get("start") if cue else None,
            "cue_end": cue.get("end") if cue else None,
            "label_source": "transcript_cue" if cue else "image_ocr",
        },
        "style_profile_id": profile_id,
        "role": role,
        "confidence": {
            "score": round(float(confidence), 4),
            "label": "high" if confidence >= 0.72 else "medium" if confidence >= 0.45 else "low",
            "observations_count": len(observations),
        },
        "match": {
            **(match_info or {}),
            "cue_text": clean_text(cue.get("text")) if cue else None,
        },
        "placement": {
            "position": f"{pos['vertical_zone']}_{pos['horizontal_align']}",
            "vertical_zone": pos["vertical_zone"],
            "horizontal_align": pos["horizontal_align"],
            "anchor": {"x": round(float(cx), 4), "y": round(float(cy), 4), "coordinate_space": "normalized_frame"},
            "bbox": bbox,
            "normalized_bbox": normalized_bbox,
            "estimated_box_width_ratio": round(float(width_ratio), 4) if width_ratio is not None else None,
            "estimated_box_height_ratio": round(float(height_ratio), 4) if height_ratio is not None else None,
        },
        "typography": {
            "font_family": "unknown",
            "font_weight": "bold" if (safe_float(font_ratio, 0.0) >= 0.05 or stroke_ratio >= 0.35) else "semibold_or_regular",
            "font_style": "normal_or_unknown",
            "font_height_px": int(round(font_px)) if font_px is not None else None,
            "font_height_ratio": round(float(font_ratio), 5) if font_ratio is not None else None,
            "case_style": infer_case_style(observed_texts or [text]),
            "density": infer_density(observations),
        },
        "colors": {
            "fill": fill,
            "stroke": stroke,
            "shadow": shadow,
            "background": None,
            "saturated_sample_ratio": round(float(sat_ratio), 4),
        },
        "stroke": {
            "enabled": bool(stroke_ratio >= 0.25 or stroke.lower() != "#000000"),
            "color": stroke,
            "width_px_estimate": max(1, int(round((font_px or 40) * (0.075 if role == "hook_caption" else 0.055)))) if stroke_ratio >= 0.18 else None,
            "sample_ratio": round(float(stroke_ratio), 4),
        },
        "shadow": {
            "enabled": bool(shadow_ratio >= 0.20),
            "color": shadow,
            "opacity_estimate": round(clamp(shadow_ratio, 0.0, 0.85), 4),
            "blur_px_estimate": 2 if shadow_ratio >= 0.20 else None,
        },
        "background_box": {"enabled": False, "style": "none_or_not_detected", "color": None, "opacity": 0.0},
        "animation": animation,
        "layering": {
            "occluded_by_foreground": None,
            "needs_foreground_mask": False,
            "confidence": 0.0,
            "reason": "foreground/background segmentation is not implemented in this detector phase",
        },
        "observations": [
            {
                "timestamp": g.get("timestamp"),
                "frame_index": g.get("frame_index"),
                "text": g.get("text"),
                "bbox": g.get("bbox"),
                "normalized_bbox": g.get("normalized_bbox"),
                "caption_score": g.get("caption_score"),
                "transcript_match_score": g.get("transcript_match_score"),
                "hook_score": g.get("hook_score"),
                "candidate_reason": g.get("candidate_reason"),
                "tracklet_id": g.get("tracklet_id"),
                "continuous_visual_identity_id": g.get("continuous_visual_identity_id"),
                "observation_provenance": g.get("observation_provenance"),
                "observed_timestamp": g.get("observed_timestamp"),
                "inferred_visibility_end": g.get("inferred_visibility_end"),
                "composition": g.get("composition"),
            }
            for g in observations[:12]
        ],
        "renderer_hints": {
            "preferred_layer_type": "editable_text",
            "resolve_target": "TextPlus_or_Title",
            "style_profile_id": profile_id,
            "per_cue_style": True,
            "clone_priority": ["placement", "font_height_ratio", "fill", "stroke", "shadow", "case_style", "animation"],
        },
    }


def build_caption_style_events(
    groups: List[Dict[str, Any]],
    transcript_cues: List[Dict[str, Any]],
    profiles: List[Dict[str, Any]],
    video_info: Dict[str, Any],
    args: argparse.Namespace,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Build one visual event per finalized tracklet or continuous identity."""
    if not groups:
        return [], {
            "enabled": bool(getattr(args, "emit_caption_style_events", True)),
            "events_count": 0,
            "matched_to_transcript_count": 0,
            "visual_only_count": 0,
            "skipped_reason": "no_caption_groups",
        }

    if not bool(getattr(args, "emit_caption_style_events", True)):
        return [], {
            "enabled": False,
            "events_count": 0,
            "matched_to_transcript_count": 0,
            "visual_only_count": 0,
            "skipped_reason": "disabled_by_cli",
        }

    max_window = safe_float(getattr(args, "style_event_match_window_sec", 1.25), 1.25)
    min_score = safe_float(getattr(args, "style_event_min_match_score", 0.18), 0.18)

    buckets: Dict[str, Dict[str, Any]] = {}
    legacy_counter = 0
    for group in sorted(groups, key=lambda g: safe_float(g.get("timestamp"), 0.0)):
        members = group.get("members") or [group]
        for member in members:
            observation = dict(member)
            observation["timestamp"] = group.get("timestamp")
            observation["frame_index"] = group.get("frame_index")
            observation["composition"] = {
                "text": group.get("text"),
                "bbox": group.get("bbox"),
                "tracklet_ids": group.get("tracklet_ids", []),
            }

            continuous_id = observation.get("continuous_visual_identity_id")
            tracklet_id = observation.get("tracklet_id")
            if continuous_id:
                key = f"continuous:{continuous_id}"
                visual_event_identity = str(continuous_id)
            elif tracklet_id:
                key = f"tracklet:{tracklet_id}"
                visual_event_identity = str(tracklet_id)
            else:
                # Backward-compatible fallback for callers with pre-tracklet fixtures.
                legacy_counter += 1
                key = f"legacy:{legacy_counter:04d}"
                visual_event_identity = f"legacy_visual_{legacy_counter:04d}"

            cue, match_info = choose_best_cue_for_group(
                observation, transcript_cues, max_window_sec=max_window, min_score=min_score
            )
            profile_id = choose_profile_id_for_group(observation, profiles)
            bucket = buckets.setdefault(key, {
                "event_id": f"style_event_{visual_event_identity}",
                "visual_event_identity": visual_event_identity,
                "continuous_visual_identity_id": continuous_id,
                "cue": cue,
                "match_info": match_info,
                "profile_id": profile_id,
                "observations": [],
            })
            bucket["observations"].append(observation)
            if safe_float((match_info or {}).get("score"), 0.0) > safe_float((bucket.get("match_info") or {}).get("score"), 0.0):
                bucket["cue"] = cue
                bucket["match_info"] = match_info
            if bucket.get("profile_id") == "style_00_unknown" and profile_id != "style_00_unknown":
                bucket["profile_id"] = profile_id

    events: List[Dict[str, Any]] = []
    for idx, bucket in enumerate(buckets.values(), start=1):
        observations = bucket.get("observations") or []
        continuous_id = bucket.get("continuous_visual_identity_id")
        observed_times = [
            safe_float(item.get("observed_timestamp"), safe_float(item.get("timestamp"), 0.0))
            for item in observations
        ]
        continuous_starts = [
            safe_float(item.get("continuous_visual_identity_observed_start"), 0.0)
            for item in observations
            if item.get("continuous_visual_identity_observed_start") is not None
        ]
        continuous_lasts = [
            safe_float(item.get("continuous_visual_identity_last_observed"), 0.0)
            for item in observations
            if item.get("continuous_visual_identity_last_observed") is not None
        ]
        continuous_ends = [
            safe_float(item.get("continuous_visual_identity_inferred_end"), 0.0)
            for item in observations
            if item.get("continuous_visual_identity_inferred_end") is not None
        ]
        inferred_ends = [
            safe_float(item.get("inferred_visibility_end"), 0.0)
            for item in observations
            if item.get("inferred_visibility_end") is not None
        ]
        tracklet_ids = sorted({
            str(tracklet_id)
            for item in observations
            for tracklet_id in (
                item.get("continuous_visual_identity_tracklet_ids")
                if continuous_id else [item.get("tracklet_id")]
            ) or []
            if tracklet_id
        })
        visual_identity = {
            "visual_event_identity": bucket.get("visual_event_identity"),
            "continuous_visual_identity_id": continuous_id,
            "tracklet_ids": tracklet_ids,
            "observation_provenance": sorted({
                str(item.get("observation_provenance")) for item in observations if item.get("observation_provenance")
            }),
            "observed_start": min(continuous_starts) if continuous_starts else min(observed_times),
            "last_observed": max(continuous_lasts) if continuous_lasts else max(observed_times),
            "inferred_end": max(continuous_ends) if continuous_ends else max(inferred_ends, default=max(observed_times)),
        }
        event = aggregate_style_event(
            event_id=bucket.get("event_id") or f"style_event_{idx:04d}",
            observations=observations,
            profile_id=bucket.get("profile_id") or "style_00_unknown",
            cue=bucket.get("cue"),
            match_info=bucket.get("match_info") or {},
            visual_identity=visual_identity,
            video_info=video_info,
            visual_index=idx,
            args=args,
        )
        events.append(event)

    events = sorted(events, key=lambda e: (safe_float(e.get("start"), 0.0), safe_float(e.get("end"), 0.0), e.get("event_id", "")))
    max_events = safe_int(getattr(args, "max_style_events", 0), 0)
    if max_events and max_events > 0:
        events = events[:max_events]

    matched = sum(1 for e in events if e.get("cue_id") is not None)
    visual_only = len(events) - matched
    by_profile: Dict[str, int] = {}
    by_animation: Dict[str, int] = {}
    animation_detected_count = 0
    for event in events:
        pid = str(event.get("style_profile_id") or "unknown")
        by_profile[pid] = by_profile.get(pid, 0) + 1
        anim = event.get("animation") or {}
        anim_type = str(anim.get("type") or anim.get("style") or "unknown")
        by_animation[anim_type] = by_animation.get(anim_type, 0) + 1
        if anim.get("detected"):
            animation_detected_count += 1

    diagnostics = {
        "enabled": True,
        "events_count": len(events),
        "matched_to_transcript_count": matched,
        "visual_only_count": visual_only,
        "profiles_used_count": len(by_profile),
        "events_by_profile": by_profile,
        "animation_detected_count": animation_detected_count,
        "events_by_animation_type": by_animation,
        "visual_identity_authority": True,
        "continuous_identity_event_count": sum(1 for event in events if event.get("continuous_visual_identity_id")),
        "standalone_tracklet_event_count": sum(1 for event in events if not event.get("continuous_visual_identity_id")),
        "animation_min_samples": safe_int(getattr(args, "animation_min_samples", 3), 3),
        "animation_max_samples": safe_int(getattr(args, "animation_max_samples", 7), 7),
        "match_window_sec": max_window,
        "min_match_score": min_score,
        "max_style_events": max_events,
    }
    return events, diagnostics


# -----------------------------
# Debug overlays
# -----------------------------


def draw_box(image: np.ndarray, bbox: Optional[List[int]], color: Tuple[int, int, int], label: Optional[str] = None, thickness: int = 2) -> None:
    if not bbox:
        return
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cv2.rectangle(image, (x1, y1), (x2, y2), color, thickness)
    if label:
        y_text = max(16, y1 - 7)
        cv2.putText(image, label[:60], (x1, y_text), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)


def save_debug_frame(frame: np.ndarray, frame_result: Dict[str, Any], debug_dir: str, debug_mode: str) -> Optional[str]:
    if debug_mode == "none":
        return None
    os.makedirs(debug_dir, exist_ok=True)
    debug = frame.copy()

    if debug_mode == "all":
        for det in frame_result.get("detections", []):
            if det.get("is_caption_candidate"):
                continue
            score = det.get("caption_score") or {}
            draw_box(debug, det.get("bbox"), (0, 0, 255), f"REJ {score.get('reason','')} {score.get('score',0)}", thickness=1)

    for det in frame_result.get("caption_candidates", []):
        score = det.get("caption_score") or {}
        role = det.get("caption_role", "cap")
        draw_box(debug, det.get("bbox"), (0, 255, 0), f"{role} {score.get('score',0)}", thickness=2)

    for group in frame_result.get("subtitle_groups", []):
        label = f"{group.get('role','caption')} {group.get('caption_score','')} {group.get('text','')}"
        draw_box(debug, group.get("bbox"), (255, 0, 0), label, thickness=3)

    frame_name = os.path.basename(frame_result["frame_path"])
    root, _ = os.path.splitext(frame_name)
    debug_path = os.path.join(debug_dir, f"{root}_debug.jpg")
    cv2.imwrite(debug_path, debug)
    return debug_path


# -----------------------------
# Output summaries
# -----------------------------


def compact_group_for_output(frame_result: Dict[str, Any], group: Dict[str, Any]) -> Dict[str, Any]:
    out = {
        "timestamp": frame_result.get("timestamp"),
        "frame_index": frame_result.get("frame_index"),
        "text": group.get("text"),
        "confidence": group.get("confidence"),
        "caption_score": group.get("caption_score"),
        "transcript_match_score": group.get("transcript_match_score"),
        "hook_score": group.get("hook_score"),
        "candidate_reason": group.get("candidate_reason"),
        "role": group.get("role"),
        "tracklet_ids": group.get("tracklet_ids", []),
        "continuous_visual_identity_ids": group.get("continuous_visual_identity_ids", []),
        "observation_provenance": group.get("observation_provenance", []),
        "observed_bbox": group.get("observed_bbox"),
        "observed_timestamp": group.get("observed_timestamp"),
        "inferred_visibility_end": group.get("inferred_visibility_end"),
        "bbox": group.get("bbox"),
        "normalized_bbox": group.get("normalized_bbox"),
        "center": group.get("center"),
        "position": group.get("position"),
        "line_count_estimate": group.get("line_count_estimate"),
        "estimated_font_height_px": group.get("estimated_font_height_px"),
        "estimated_font_height_ratio": group.get("estimated_font_height_ratio"),
        "estimated_box_width_ratio": group.get("estimated_box_width_ratio"),
        "estimated_box_height_ratio": group.get("estimated_box_height_ratio"),
        "estimated_text_color": group.get("estimated_text_color"),
        "estimated_stroke_color": group.get("estimated_stroke_color"),
        "estimated_shadow_color": group.get("estimated_shadow_color"),
        "has_dark_stroke": group.get("has_dark_stroke"),
        "has_shadow": group.get("has_shadow"),
        "has_bright_text": group.get("has_bright_text"),
        "has_saturated_text": group.get("has_saturated_text"),
        "text_area_ratio": group.get("text_area_ratio"),
        "dark_area_ratio": group.get("dark_area_ratio"),
        "saturated_area_ratio": group.get("saturated_area_ratio"),
        "contrast_area_ratio": group.get("contrast_area_ratio"),
        "matched_cue_ids": group.get("matched_cue_ids", []),
        "members": group.get("members", []),
    }
    return out


def build_summary(groups: List[Dict[str, Any]], frames_analyzed: int, cfg: Dict[str, Any]) -> Dict[str, Any]:
    if not groups:
        return {
            "has_visible_captions": False,
            "position": None,
            "dominant_position": None,
            "subtitle_groups_count": 0,
            "quality": {"label": "none", "subtitle_groups_count": 0, "frames_with_subtitles": 0, "frames_analyzed": frames_analyzed, "frame_coverage_ratio": 0.0},
            "filter_config": cfg,
        }
    centers_x = [safe_float((g.get("center") or {}).get("x"), 0.5) for g in groups]
    centers_y = [safe_float((g.get("center") or {}).get("y"), 0.5) for g in groups]
    frames_with = len(set(g.get("frame_index") for g in groups if g.get("frame_index") is not None))
    coverage = frames_with / max(1, frames_analyzed)
    if len(groups) >= 18 and coverage >= 0.30:
        q = "high"
    elif len(groups) >= 6:
        q = "medium"
    else:
        q = "low"
    cx = safe_median(centers_x, 0.5)
    cy = safe_median(centers_y, 0.72)
    pos = position_from_center(cx, cy)
    position_label = f"{pos['vertical_zone']}_{pos['horizontal_align']}"
    return {
        "has_visible_captions": True,
        "position": position_label,
        "dominant_position": pos,
        "center_x_median": round(float(cx), 4),
        "center_y_median": round(float(cy), 4),
        "center_x_std": round(float(np.std(centers_x)), 4),
        "center_y_std": round(float(np.std(centers_y)), 4),
        "font_height_px_median": int(round(safe_median([g.get("estimated_font_height_px") for g in groups], 0))),
        "font_height_ratio_median": round(float(safe_median([g.get("estimated_font_height_ratio") for g in groups], 0.0)), 5),
        "text_color_median": median_hex_color([g.get("estimated_text_color") for g in groups if g.get("estimated_text_color")], "#ffffff"),
        "stroke_color_median": median_hex_color([g.get("estimated_stroke_color") for g in groups if g.get("estimated_stroke_color")], "#000000"),
        "has_dark_stroke_ratio": round(float(np.mean([1 if g.get("has_dark_stroke") else 0 for g in groups])), 4),
        "has_saturated_text_ratio": round(float(np.mean([1 if g.get("has_saturated_text") else 0 for g in groups])), 4),
        "subtitle_groups_count": len(groups),
        "quality": {"label": q, "subtitle_groups_count": len(groups), "frames_with_subtitles": frames_with, "frames_analyzed": frames_analyzed, "frame_coverage_ratio": round(coverage, 4)},
        "filter_config": cfg,
    }


def build_filter_config(args: argparse.Namespace, frames_analyzed: int = 0) -> Dict[str, Any]:
    return {
        "mode": args.mode,
        "observation_floor_fps": OBSERVATION_FLOOR_FPS,
        "continuation_max_gap_sec": CONTINUATION_MAX_GAP_SEC,
        "continuation_min_iou": CONTINUATION_MIN_IOU,
        "continuation_max_center_distance": CONTINUATION_MAX_CENTER_DISTANCE,
        "continuation_max_area_ratio": CONTINUATION_MAX_AREA_RATIO,
        "continuation_max_aspect_ratio": CONTINUATION_MAX_ASPECT_RATIO,
        "inferred_lifetime_grace_sec": 1.0 / OBSERVATION_FLOOR_FPS,
        "transcript": args.transcript,
        "transcript_match_threshold": args.transcript_match_threshold,
        "regular_caption_score_threshold": args.regular_caption_score_threshold,
        "visual_hook_score_threshold": args.visual_hook_score_threshold,
        "match_window_sec": args.match_window_sec,
        "viral_min_x": args.viral_min_x,
        "viral_max_x": args.viral_max_x,
        "viral_min_y": args.viral_min_y,
        "hook_min_y": args.hook_min_y,
        "enable_visual_spoken_fallback": args.enable_visual_spoken_fallback,
        "visual_spoken_score_threshold": args.visual_spoken_score_threshold,
        "visual_spoken_min_confidence": args.visual_spoken_min_confidence,
        "visual_spoken_min_y": args.visual_spoken_min_y,
        "visual_spoken_max_y": args.visual_spoken_max_y,
        "visual_spoken_min_x": args.visual_spoken_min_x,
        "visual_spoken_max_x": args.visual_spoken_max_x,
        "visual_spoken_min_font_ratio": args.visual_spoken_min_font_ratio,
        "visual_spoken_min_width_ratio": args.visual_spoken_min_width_ratio,
        "top_ui_caption_max_y": args.top_ui_caption_max_y,
        "top_ui_max_font_ratio": args.top_ui_max_font_ratio,
        "top_ui_allow_match_threshold": args.top_ui_allow_match_threshold,
        "max_style_profiles": args.max_style_profiles,
        "emit_caption_style_events": args.emit_caption_style_events,
        "style_event_match_window_sec": args.style_event_match_window_sec,
        "style_event_min_match_score": args.style_event_min_match_score,
        "max_style_events": args.max_style_events,
        # Legacy thresholds kept for backward compatibility.
        "subtitle_min_confidence": args.subtitle_min_confidence,
        "subtitle_min_x": args.subtitle_min_x,
        "subtitle_max_x": args.subtitle_max_x,
        "subtitle_min_y": args.subtitle_min_y,
        "subtitle_max_y": args.subtitle_max_y,
        "subtitle_min_font_height": args.subtitle_min_font_height,
        "subtitle_max_font_height": args.subtitle_max_font_height,
        "subtitle_min_width_ratio": args.subtitle_min_width_ratio,
        "subtitle_min_height_ratio": args.subtitle_min_height_ratio,
        "subtitle_group_y_tolerance": args.subtitle_group_y_tolerance,
        "require_bright_text": args.require_bright_text,
        "save_debug": args.save_debug,
        "debug_mode": args.debug_mode,
        "debug_dir": args.debug_dir,
        "output_mode": args.output_mode,
        "clear_frames": args.clear_frames,
        "ocr_lang": args.ocr_lang,
        "use_angle_cls": args.use_angle_cls,
        "ocr_device": args.ocr_device,
        "ocr_gpu_id": args.ocr_gpu_id,
        "opencv_threads": args.opencv_threads,
        "frames_analyzed": frames_analyzed,
    }


# -----------------------------
# Main run
# -----------------------------


def run(args: argparse.Namespace) -> None:
    started = time.time()
    video_path = args.video
    output_json = args.output
    frame_dir = args.frames
    if safe_int(getattr(args, "opencv_threads", 0), 0) > 0:
        try:
            cv2.setNumThreads(max(1, safe_int(args.opencv_threads, 1)))
        except Exception:
            pass
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    output_dir = os.path.dirname(output_json)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    os.makedirs(frame_dir, exist_ok=True)

    video_info = read_video_info(video_path)
    transcript_data = load_json(args.transcript) if args.transcript and os.path.exists(args.transcript) else {}
    transcript_cues = extract_transcript_cues(transcript_data) if transcript_data else []

    if args.save_debug:
        if args.debug_mode == "none":
            args.debug_mode = "subtitle_only"
        if not args.debug_dir:
            args.debug_dir = os.path.join(output_dir or frame_dir, "debug_caption_style_v5_1")
        os.makedirs(args.debug_dir, exist_ok=True)

    preferred = None
    if args.mode == "viral_transcript_aware" and transcript_cues:
        preferred = preferred_timestamps_from_cues(
            transcript_cues,
            max_frames=max(20, args.max_frames),
            animation_samples_per_cue=args.animation_samples_per_cue if args.enable_caption_animation_detection else 1,
            animation_sample_window_sec=args.animation_sample_window_sec,
        )

    frames = sample_frames(
        video_path=video_path,
        output_dir=frame_dir,
        every_seconds=args.every_seconds,
        max_frames=args.max_frames,
        clear_frames=args.clear_frames,
        preferred_timestamps=preferred,
    )

    cfg = build_filter_config(args, frames_analyzed=len(frames))
    ocr, ocr_runtime = create_ocr(
        lang=args.ocr_lang,
        use_angle_cls=args.use_angle_cls,
        ocr_device=args.ocr_device,
        gpu_id=args.ocr_gpu_id,
    )
    cfg["ocr_runtime"] = ocr_runtime
    frame_results: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []

    for item in frames:
        frame_path = item["path"]
        timestamp = safe_float(item["timestamp"], 0.0)
        frame = cv2.imread(frame_path)
        if frame is None:
            err = {"timestamp": timestamp, "frame_path": frame_path, "error": "Could not read frame."}
            errors.append(err)
            frame_results.append({"timestamp": timestamp, "frame_index": item.get("index"), "frame_path": frame_path, "detections": [], "caption_candidates": [], "subtitle_candidates": [], "subtitle_groups": [], "error": err["error"]})
            continue

        context = build_transcript_context(transcript_cues, timestamp=timestamp, window_sec=args.match_window_sec, max_chars=args.context_max_chars)
        try:
            result = run_ocr(ocr, frame_path)
            parsed_lines = [
                line for line in parse_paddle_result(result)
                if safe_float(line[2], 0.0) >= args.min_confidence
            ]
            parsed_lines = refine_merged_ocr_regions(ocr, frame, parsed_lines, include_provenance=True)
        except Exception as exc:
            err = {"timestamp": timestamp, "frame_path": frame_path, "error": str(exc)}
            errors.append(err)
            frame_results.append({"timestamp": timestamp, "frame_index": item.get("index"), "frame_path": frame_path, "detections": [], "caption_candidates": [], "subtitle_candidates": [], "subtitle_groups": [], "error": str(exc)})
            continue

        detections: List[Dict[str, Any]] = []
        for box, text, confidence, source_provenance in parsed_lines:
            try:
                style = estimate_caption_style(frame, box)
                if not style:
                    continue
            except Exception as exc:
                errors.append({"timestamp": timestamp, "frame_path": frame_path, "text": text, "confidence": round(float(confidence), 4), "error": f"Style estimation failed: {str(exc)}"})
                continue
            det: Dict[str, Any] = {"text": clean_text(text), "confidence": round(float(confidence), 4), "source_provenance": source_provenance, **style}
            is_candidate, score_info = classify_caption_candidate(det, context, args)
            det["classifier_accepted"] = bool(is_candidate)
            det["is_caption_candidate"] = bool(is_candidate)
            det["is_subtitle_candidate"] = bool(is_candidate)  # backward-compatible alias
            det["caption_score"] = score_info
            det["candidate_reason"] = score_info.get("reason")
            if is_candidate:
                det["caption_role"] = "hook_caption" if score_info.get("reason") == "visual_hook_caption" else "spoken_caption"
            detections.append(det)

        frame_result = {
            "timestamp": round(timestamp, 4),
            "frame_index": item.get("index"),
            "frame_path": frame_path,
            "transcript_context": context,
            "detections": detections,
            "caption_candidates": [],
            "subtitle_candidates": [],
            "subtitle_groups": [],
        }
        frame_results.append(frame_result)

    source_fps = safe_float(video_info.get("fps"), OBSERVATION_FLOOR_FPS)
    observation_period_sec = 1.0 / min(OBSERVATION_FLOOR_FPS, source_fps)
    apply_short_caption_continuations(
        frame_results,
        observation_period_sec=observation_period_sec,
        video_duration=safe_float(video_info.get("duration_seconds"), 0.0),
    )
    continuous_visual_identity_diagnostics = apply_continuous_visual_identity_relations(frame_results)
    frame_shape = (safe_int(video_info.get("height"), 0), safe_int(video_info.get("width"), 0), 3)
    for frame_result in frame_results:
        frame_result["subtitle_groups"] = group_caption_candidates(frame_result["caption_candidates"], frame_shape, y_tolerance=args.subtitle_group_y_tolerance)
        for group in frame_result["subtitle_groups"]:
            group.update(timestamp=frame_result["timestamp"], frame_index=frame_result["frame_index"])
        if args.save_debug:
            debug_frame = cv2.imread(frame_result["frame_path"])
            if debug_frame is not None:
                frame_result["debug_frame_path"] = save_debug_frame(debug_frame, frame_result, args.debug_dir, args.debug_mode)

    compact_groups: List[Dict[str, Any]] = []
    for frame_result in frame_results:
        for group in frame_result.get("subtitle_groups", []):
            compact_groups.append(compact_group_for_output(frame_result, group))

    profiles = build_style_profiles(compact_groups, video_info=video_info, max_profiles=args.max_style_profiles)
    summary = build_summary(compact_groups, frames_analyzed=len(frames), cfg=cfg)
    caption_style_resolved = build_caption_style_resolved(profiles, compact_groups, video_info, cfg)
    caption_style_events, style_event_diagnostics = build_caption_style_events(compact_groups, transcript_cues, profiles, video_info, args)

    all_text_count = sum(len(x.get("detections", [])) for x in frame_results)
    candidate_count = sum(len(x.get("caption_candidates", [])) for x in frame_results)
    spoken_count = sum(1 for g in compact_groups if g.get("role") == "spoken_caption")
    hook_count = sum(1 for g in compact_groups if g.get("role") == "hook_caption")

    compact_output = {
        "success": True,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "video_path": video_path,
        "video_info": video_info,
        "frame_count_analyzed": len(frames),
        "ocr": {
            "engine": "PaddleOCR",
            "lang": args.ocr_lang,
            "use_angle_cls": args.use_angle_cls,
            "device_requested": args.ocr_device,
            "gpu_id": args.ocr_gpu_id,
            "runtime": ocr_runtime,
        },
        "min_confidence": args.min_confidence,
        "mode": args.mode,
        "transcript": {
            "path": args.transcript,
            "available": bool(transcript_data),
            "cues_count": len(transcript_cues),
            "sources": sorted(set(c.get("source", "unknown") for c in transcript_cues)),
        },
        "subtitle_style_summary": summary,
        "summary": summary,
        "caption_style_resolved": caption_style_resolved,
        "resolved": caption_style_resolved,
        "caption_style_profiles": profiles,
        "style_profiles": profiles,
        "caption_style_events": caption_style_events,
        "style_events": caption_style_events,
        "caption_style_event_diagnostics": style_event_diagnostics,
        "continuous_visual_identity_diagnostics": continuous_visual_identity_diagnostics,
        "subtitle_groups": compact_groups,
        "caption_groups": compact_groups,
        "debug": {
            "all_text_detections_count": all_text_count,
            "subtitle_candidates_count": candidate_count,
            "caption_candidates_count": candidate_count,
            "subtitle_groups_count": len(compact_groups),
            "spoken_caption_groups_count": spoken_count,
            "hook_caption_groups_count": hook_count,
            "profiles_count": len(profiles),
            "caption_style_events_count": len(caption_style_events),
            "caption_style_events_matched_count": style_event_diagnostics.get("matched_to_transcript_count", 0),
            "caption_style_events_visual_only_count": style_event_diagnostics.get("visual_only_count", 0),
            "caption_animation_detected_count": style_event_diagnostics.get("animation_detected_count", 0),
            "caption_animation_types": style_event_diagnostics.get("events_by_animation_type", {}),
            "resolved_confidence_label": caption_style_resolved.get("confidence", {}).get("label"),
            "resolved_confidence_score": caption_style_resolved.get("confidence", {}).get("score"),
            "resolved_position": caption_style_resolved.get("placement", {}).get("position"),
            "errors_count": len(errors),
            "debug_mode": args.debug_mode if args.save_debug else "none",
            "debug_dir": args.debug_dir if args.save_debug else None,
            "runtime_seconds": round(time.time() - started, 3),
            "ocr_device_requested": args.ocr_device,
            "ocr_device_selected": ocr_runtime.get("selected_device"),
            "paddle_compiled_with_cuda": ocr_runtime.get("compiled_with_cuda"),
        },
        "errors": errors[:20],
    }

    full_output = {**compact_output, "frame_results": frame_results, "errors": errors}

    if args.output_mode == "compact":
        output = compact_output
    elif args.output_mode == "full":
        output = full_output
    elif args.output_mode == "both":
        output = compact_output
        full_debug_path = os.path.splitext(output_json)[0] + "_full_debug.json"
        write_json(full_debug_path, full_output)
        output["debug"]["full_debug_json"] = full_debug_path
    else:
        raise ValueError(f"Unsupported output mode: {args.output_mode}")

    write_json(output_json, output)

    stdout = {
        "success": True,
        "analysis_version": ANALYSIS_VERSION,
        "output_json": output_json,
        "frames_analyzed": len(frames),
        "all_text_detections_count": all_text_count,
        "subtitle_candidates_count": candidate_count,
        "subtitle_groups_count": len(compact_groups),
        "spoken_caption_groups_count": spoken_count,
        "hook_caption_groups_count": hook_count,
        "profiles_count": len(profiles),
        "caption_style_events_count": len(caption_style_events),
        "caption_style_events_matched_count": style_event_diagnostics.get("matched_to_transcript_count", 0),
        "caption_style_events_visual_only_count": style_event_diagnostics.get("visual_only_count", 0),
        "caption_animation_detected_count": style_event_diagnostics.get("animation_detected_count", 0),
        "caption_animation_types": style_event_diagnostics.get("events_by_animation_type", {}),
        "subtitle_position": summary.get("position"),
        "subtitle_summary_confidence": summary.get("quality", {}).get("label"),
        "resolved_position": caption_style_resolved.get("placement", {}).get("position"),
        "resolved_confidence_score": caption_style_resolved.get("confidence", {}).get("score"),
        "resolved_fill_color": caption_style_resolved.get("colors", {}).get("fill"),
        "resolved_stroke_enabled": caption_style_resolved.get("stroke", {}).get("enabled"),
        "transcript_cues_count": len(transcript_cues),
        "errors_count": len(errors),
        "output_mode": args.output_mode,
        "debug_mode": args.debug_mode if args.save_debug else "none",
        "ocr_device_requested": args.ocr_device,
        "ocr_device_selected": ocr_runtime.get("selected_device"),
        "paddle_compiled_with_cuda": ocr_runtime.get("compiled_with_cuda"),
        "paddle_version": ocr_runtime.get("paddle_version"),
    }
    if args.output_mode == "both":
        stdout["full_debug_json"] = output.get("debug", {}).get("full_debug_json")
    print(json.dumps(stdout, ensure_ascii=False))


# -----------------------------
# CLI
# -----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--frames", required=True)
    parser.add_argument("--transcript", default=None, help="Optional transcript JSON. Required for best v5 transcript-aware caption matching.")
    parser.add_argument("--mode", choices=["legacy", "viral", "viral_transcript_aware"], default="viral_transcript_aware")

    parser.add_argument("--every-seconds", type=float, default=0.50)
    parser.add_argument("--max-frames", type=int, default=120)
    parser.add_argument("--min-confidence", type=float, default=0.35)
    parser.add_argument("--ocr-lang", default="en")
    parser.add_argument("--use-angle-cls", type=str2bool, default=False)
    parser.add_argument("--ocr-device", default="auto", choices=["auto", "cpu", "gpu"], help="PaddleOCR device. Use gpu after installing paddlepaddle-gpu in venv_ocr.")
    parser.add_argument("--ocr-gpu-id", type=int, default=0, help="GPU id for PaddleOCR when --ocr-device gpu/auto uses CUDA.")
    parser.add_argument("--opencv-threads", type=int, default=0, help="Optional cap for OpenCV CPU threads. 0 = OpenCV default.")

    # v5 viral/transcript-aware thresholds.
    parser.add_argument("--match-window-sec", type=float, default=1.25)
    parser.add_argument("--context-max-chars", type=int, default=180)
    parser.add_argument("--transcript-match-threshold", type=float, default=0.30)
    parser.add_argument("--regular-caption-score-threshold", type=float, default=0.46)
    parser.add_argument("--visual-hook-score-threshold", type=float, default=0.64)
    parser.add_argument("--hook-min-confidence", type=float, default=0.35)
    parser.add_argument("--viral-min-x", type=float, default=0.10)
    parser.add_argument("--viral-max-x", type=float, default=0.90)
    parser.add_argument("--viral-min-y", type=float, default=0.18)
    parser.add_argument("--hook-min-y", type=float, default=0.08)

    # v5.1 visual fallback and UI guards.
    parser.add_argument("--enable-visual-spoken-fallback", type=str2bool, default=True)
    parser.add_argument("--visual-spoken-score-threshold", type=float, default=0.56)
    parser.add_argument("--visual-spoken-min-confidence", type=float, default=0.55)
    parser.add_argument("--visual-spoken-min-y", type=float, default=0.38)
    parser.add_argument("--visual-spoken-max-y", type=float, default=0.84)
    parser.add_argument("--visual-spoken-min-x", type=float, default=0.12)
    parser.add_argument("--visual-spoken-max-x", type=float, default=0.88)
    parser.add_argument("--visual-spoken-min-font-ratio", type=float, default=0.020)
    parser.add_argument("--visual-spoken-min-width-ratio", type=float, default=0.055)
    parser.add_argument("--top-ui-caption-max-y", type=float, default=0.40)
    parser.add_argument("--top-ui-max-font-ratio", type=float, default=0.018)
    parser.add_argument("--top-ui-allow-match-threshold", type=float, default=0.55)
    parser.add_argument("--max-style-profiles", type=int, default=5)
    parser.add_argument("--emit-caption-style-events", type=str2bool, default=True, help="Emit per-cue caption_style_events for downstream compilers.")
    parser.add_argument("--style-event-match-window-sec", type=float, default=1.25, help="Max temporal distance when assigning visual caption samples to transcript cues.")
    parser.add_argument("--style-event-min-match-score", type=float, default=0.18, help="Minimum time/text score for assigning a visual sample to a transcript cue.")
    parser.add_argument("--max-style-events", type=int, default=0, help="Limit emitted caption_style_events. 0 = unlimited.")
    parser.add_argument("--enable-caption-animation-detection", type=str2bool, default=True, help="Sample adjacent frames and estimate caption animation per style event.")
    parser.add_argument("--animation-samples-per-cue", type=int, default=5, help="Preferred adjacent samples per transcript/subtitle cue for animation detection. Practical range: 3-7.")
    parser.add_argument("--animation-sample-window-sec", type=float, default=0.22, help="Local time window around each cue midpoint for adjacent-frame animation sampling.")
    parser.add_argument("--animation-min-samples", type=int, default=3, help="Minimum same-cue observations required before reporting animation as detected.")
    parser.add_argument("--animation-max-samples", type=int, default=7, help="Maximum observations used per event animation estimate.")

    # Legacy thresholds preserved so old commands do not break.
    parser.add_argument("--subtitle-min-confidence", type=float, default=0.80)
    parser.add_argument("--subtitle-min-x", type=float, default=0.25)
    parser.add_argument("--subtitle-max-x", type=float, default=0.75)
    parser.add_argument("--subtitle-min-y", type=float, default=0.60)
    parser.add_argument("--subtitle-max-y", type=float, default=0.78)
    parser.add_argument("--subtitle-min-font-height", type=int, default=20)
    parser.add_argument("--subtitle-max-font-height", type=int, default=220)
    parser.add_argument("--subtitle-min-width-ratio", type=float, default=0.035)
    parser.add_argument("--subtitle-min-height-ratio", type=float, default=0.006)
    parser.add_argument("--subtitle-group-y-tolerance", type=float, default=0.045)
    parser.add_argument("--ui-reject-max-top-y", type=float, default=0.12)
    parser.add_argument("--ui-reject-min-x", type=float, default=0.05)
    parser.add_argument("--ui-reject-max-x", type=float, default=0.95)
    parser.add_argument("--require-bright-text", type=str2bool, default=False)
    parser.add_argument("--clear-frames", type=str2bool, default=False)

    parser.add_argument("--save-debug", type=str2bool, default=False)
    parser.add_argument("--debug-mode", choices=["none", "subtitle_only", "all"], default="subtitle_only")
    parser.add_argument("--debug-dir", default=None)
    parser.add_argument("--output-mode", choices=["compact", "full", "both"], default="compact")
    return parser


if __name__ == "__main__":
    run(build_arg_parser().parse_args())
