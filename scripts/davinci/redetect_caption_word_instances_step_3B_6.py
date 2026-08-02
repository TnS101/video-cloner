#!/usr/bin/env python3
"""Major Step 3B.6B — dense source-video word-instance re-detection.

Read-only analysis step. It processes every frame in the 15 flagged caption scenes,
uses transcript-constrained PaddleOCR detections plus short-gap template tracking,
and emits per-word source tracks for geometry, scale, position and opacity proxies.

The script never connects to Resolve and never edits the timeline.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# Must be defined before importing PaddleOCR / paddle.
os.environ.setdefault("FLAGS_use_onednn", "0")
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

VERSION = "redetect_caption_word_instances_step_3B_6B_v1_0_dense_paddle_track"
SCHEMA = "video_cloner_caption_word_instance_tracks"
SCHEMA_VERSION = "1.0"
EXPECTED_V3_COUNT = 116
EXPECTED_TARGET_COUNT = 75
EXPECTED_SCENE_COUNT = 15

try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception as exc:  # pragma: no cover - runtime dependency gate
    raise SystemExit(
        "Missing OpenCV/Numpy in the selected Python environment. "
        "Run this step with Virtual Environments\\venv_ocr\\Scripts\\python.exe. "
        f"Original import error: {exc}"
    )

PaddleOCR = None  # loaded lazily so --self-test does not require the OCR runtime


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(value, encoding="utf-8", newline="\n")
    tmp.replace(path)


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    for key in ("tracks_hash", "validation_hash", "checkpoint_hash", *ignored):
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def finite(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def normalize_text(value: Any) -> str:
    text = str(value or "").lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return " ".join(text.split())


def compact_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_text(value))


def text_similarity(a: Any, b: Any) -> float:
    aa, bb = compact_text(a), compact_text(b)
    if not aa or not bb:
        return 0.0
    ratio = SequenceMatcher(None, aa, bb).ratio()
    if aa == bb:
        return 1.0
    if aa in bb or bb in aa:
        ratio = max(ratio, min(len(aa), len(bb)) / max(len(aa), len(bb)))
    return round(float(clamp(ratio, 0.0, 1.0)), 6)


def bbox_valid(box: Any) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) < 4:
        return False
    vals = [finite(v) for v in box[:4]]
    if any(v is None for v in vals):
        return False
    x1, y1, x2, y2 = [float(v) for v in vals]
    return x2 > x1 and y2 > y1


def bbox_iou(a: Sequence[float], b: Sequence[float]) -> float:
    ax1, ay1, ax2, ay2 = [float(v) for v in a]
    bx1, by1, bx2, by2 = [float(v) for v in b]
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    denom = area_a + area_b - inter
    return inter / denom if denom > 0 else 0.0


def bbox_center(box: Sequence[float]) -> Tuple[float, float]:
    return ((float(box[0]) + float(box[2])) / 2.0, (float(box[1]) + float(box[3])) / 2.0)


def bbox_size(box: Sequence[float]) -> Tuple[float, float]:
    return (float(box[2]) - float(box[0]), float(box[3]) - float(box[1]))


def normalized_bbox(box: Sequence[float], width: int, height: int) -> List[float]:
    return [
        round(float(box[0]) / width, 8),
        round(float(box[1]) / height, 8),
        round(float(box[2]) / width, 8),
        round(float(box[3]) / height, 8),
    ]


def normalized_center(box: Sequence[float], width: int, height: int) -> List[float]:
    cx, cy = bbox_center(box)
    return [round(cx / width, 8), round(cy / height, 8)]


def source_frame_for_timeline_frame(timeline_frame: int, plan_fps: float, video_fps: float) -> int:
    return int(round((float(timeline_frame) / plan_fps) * video_fps))


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, np.generic):
        return value.item()
    return value


# ---------------------------------------------------------------------------
# PaddleOCR compatibility
# ---------------------------------------------------------------------------

def normalize_quad(box: Any) -> Optional[List[List[float]]]:
    if hasattr(box, "tolist"):
        box = box.tolist()
    if not isinstance(box, (list, tuple)):
        return None
    points: List[List[float]] = []
    for point in box:
        if hasattr(point, "tolist"):
            point = point.tolist()
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            x, y = finite(point[0]), finite(point[1])
            if x is not None and y is not None:
                points.append([float(x), float(y)])
    return points[:4] if len(points) >= 4 else None


def parse_old_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed: List[Tuple[List[List[float]], str, float]] = []
    roots = result if isinstance(result, list) else [result]
    for root in roots:
        if not isinstance(root, list):
            continue
        for item in root:
            if not isinstance(item, (list, tuple)) or len(item) < 2:
                continue
            quad = normalize_quad(item[0])
            payload = item[1]
            if quad and isinstance(payload, (list, tuple)) and len(payload) >= 2:
                score = finite(payload[1])
                if score is not None:
                    parsed.append((quad, str(payload[0]), float(score)))
    return parsed


def parse_new_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed: List[Tuple[List[List[float]], str, float]] = []
    roots = result if isinstance(result, list) else [result]
    for root in roots:
        data = root
        if hasattr(root, "json"):
            try:
                data = root.json
                if callable(data):
                    data = data()
            except Exception:
                pass
        if hasattr(data, "to_dict"):
            try:
                data = data.to_dict()
            except Exception:
                pass
        if not isinstance(data, dict):
            continue
        if isinstance(data.get("res"), dict):
            data = data["res"]
        texts = data.get("rec_texts") or data.get("texts") or []
        scores = data.get("rec_scores") or data.get("scores") or []
        boxes = data.get("rec_polys") or data.get("dt_polys") or data.get("polys") or []
        if hasattr(texts, "tolist"):
            texts = texts.tolist()
        if hasattr(scores, "tolist"):
            scores = scores.tolist()
        if hasattr(boxes, "tolist"):
            boxes = boxes.tolist()
        count = min(len(texts), len(scores), len(boxes)) if texts and boxes is not None else 0
        for index in range(count):
            quad = normalize_quad(boxes[index])
            score = finite(scores[index])
            if quad and score is not None:
                parsed.append((quad, str(texts[index]), float(score)))
    return parsed


def parse_paddle_result(result: Any) -> List[Tuple[List[List[float]], str, float]]:
    parsed = parse_old_paddle_result(result)
    return parsed if parsed else parse_new_paddle_result(result)


def create_ocr(lang: str, device: str, gpu_id: int) -> Tuple[Any, Dict[str, Any]]:
    global PaddleOCR
    if PaddleOCR is None:
        try:
            from paddleocr import PaddleOCR as _PaddleOCR  # type: ignore
            PaddleOCR = _PaddleOCR
        except Exception as exc:
            raise RuntimeError(
                "Missing PaddleOCR in the selected Python environment. "
                "Use Virtual Environments\\venv_ocr\\Scripts\\python.exe. "
                f"Original import error: {exc}"
            )
    device = str(device or "auto").lower()
    want_gpu = device == "gpu"
    if device == "auto":
        try:
            import paddle  # type: ignore
            want_gpu = bool(paddle.device.is_compiled_with_cuda())
        except Exception:
            want_gpu = False
    selected = f"gpu:{gpu_id}" if want_gpu else "cpu"
    attempts: List[Dict[str, Any]] = []
    constructors = [
        {
            "lang": lang,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "device": selected,
        },
        {"lang": lang, "use_angle_cls": False, "show_log": False, "use_gpu": want_gpu, "gpu_id": gpu_id},
        {"lang": lang, "use_angle_cls": False, "show_log": False},
        {"lang": lang, "use_angle_cls": False},
        {"lang": lang},
    ]
    last_error: Optional[Exception] = None
    for kwargs in constructors:
        try:
            engine = PaddleOCR(**kwargs)
            attempts.append({"kwargs": kwargs, "ok": True})
            return engine, {"engine": "PaddleOCR", "selected_device": selected, "constructor": kwargs, "attempts": attempts}
        except Exception as exc:
            last_error = exc
            attempts.append({"kwargs": kwargs, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    raise RuntimeError(f"Could not initialize PaddleOCR. Last error: {last_error}")


def run_ocr(engine: Any, frame: np.ndarray, temp_dir: Path, token: str) -> Any:
    try:
        return engine.ocr(frame, cls=False)
    except TypeError:
        try:
            return engine.ocr(frame)
        except Exception:
            pass
    except Exception:
        pass
    if hasattr(engine, "predict"):
        try:
            return engine.predict(frame)
        except Exception:
            pass
    path = temp_dir / f"ocr_{token}.jpg"
    cv2.imwrite(str(path), frame)
    try:
        try:
            return engine.ocr(str(path), cls=False)
        except TypeError:
            return engine.ocr(str(path))
    finally:
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Candidate generation / matching
# ---------------------------------------------------------------------------
@dataclass
class Candidate:
    candidate_id: str
    text: str
    confidence: float
    bbox: List[float]
    source_text: str
    source_kind: str
    source_index: int
    split_token_index: Optional[int] = None
    split_token_count: Optional[int] = None


def quad_to_bbox(quad: Sequence[Sequence[float]], scale_x: float, scale_y: float, width: int, height: int) -> Optional[List[float]]:
    xs = [float(point[0]) * scale_x for point in quad]
    ys = [float(point[1]) * scale_y for point in quad]
    x1, y1 = max(0.0, min(xs)), max(0.0, min(ys))
    x2, y2 = min(float(width - 1), max(xs)), min(float(height - 1), max(ys))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return [x1, y1, x2, y2]


def split_line_tokens(text: str, bbox: Sequence[float]) -> List[Tuple[str, List[float]]]:
    tokens = re.findall(r"[A-Za-z0-9']+", str(text or ""))
    if len(tokens) <= 1:
        return []
    x1, y1, x2, y2 = [float(v) for v in bbox]
    total_chars = sum(max(1, len(compact_text(token))) for token in tokens)
    # Preserve a small inter-token gap while splitting a Paddle line box.
    gap_units = max(0, len(tokens) - 1) * 0.55
    denom = total_chars + gap_units
    cursor = x1
    width = x2 - x1
    result: List[Tuple[str, List[float]]] = []
    for index, token in enumerate(tokens):
        units = max(1, len(compact_text(token)))
        token_width = width * units / denom
        result.append((token, [cursor, y1, min(x2, cursor + token_width), y2]))
        cursor += token_width + (width * 0.55 / denom if index < len(tokens) - 1 else 0.0)
    return result


def build_candidates(
    parsed: Sequence[Tuple[List[List[float]], str, float]],
    scale_x: float,
    scale_y: float,
    width: int,
    height: int,
    min_confidence: float,
) -> List[Candidate]:
    candidates: List[Candidate] = []
    for index, (quad, text, confidence) in enumerate(parsed):
        conf = float(confidence)
        if conf < min_confidence:
            continue
        bbox = quad_to_bbox(quad, scale_x, scale_y, width, height)
        if not bbox:
            continue
        bw, bh = bbox_size(bbox)
        area_ratio = (bw * bh) / max(1.0, width * height)
        if area_ratio < 0.00002 or area_ratio > 0.45:
            continue
        clean = normalize_text(text)
        if not clean:
            continue
        candidates.append(Candidate(f"line_{index}", clean, conf, bbox, str(text), "ocr_line", index))
        splits = split_line_tokens(text, bbox)
        for token_index, (token, token_bbox) in enumerate(splits):
            candidates.append(
                Candidate(
                    f"line_{index}_token_{token_index}",
                    normalize_text(token),
                    max(0.0, conf - 0.03),
                    token_bbox,
                    str(text),
                    "ocr_line_split_token",
                    index,
                    token_index,
                    len(splits),
                )
            )
    return candidates


def temporal_score(frame: int, cue: Dict[str, Any], scene: Dict[str, Any]) -> float:
    start, end = int(cue.get("start") or 0), int(cue.get("end") or 0)
    if start - 2 <= frame <= end + 2:
        return 1.0
    midpoint = (start + end) / 2.0
    scene_span = max(1.0, float(scene.get("end_frame", end)) - float(scene.get("start_frame", start)))
    distance = abs(frame - midpoint) / scene_span
    return float(math.exp(-4.0 * distance))


def dimension_score(candidate: Candidate, cue_text: str, frame_width: int, frame_height: int) -> float:
    width, height = bbox_size(candidate.bbox)
    if height <= 0:
        return 0.0
    aspect = width / height
    expected = max(0.55, 0.62 * max(1, len(compact_text(cue_text))))
    ratio = max(aspect, expected) / max(0.001, min(aspect, expected))
    score = math.exp(-0.55 * max(0.0, ratio - 1.0))
    area_ratio = (width * height) / max(1.0, frame_width * frame_height)
    if area_ratio > 0.28:
        score *= 0.25
    return float(clamp(score, 0.0, 1.0))


def continuity_score(candidate: Candidate, previous_bbox: Optional[Sequence[float]], frame_width: int, frame_height: int) -> float:
    if not previous_bbox:
        return 0.5
    iou = bbox_iou(candidate.bbox, previous_bbox)
    cx, cy = bbox_center(candidate.bbox)
    px, py = bbox_center(previous_bbox)
    distance = math.hypot((cx - px) / max(1, frame_width), (cy - py) / max(1, frame_height))
    proximity = math.exp(-10.0 * distance)
    return float(clamp(0.65 * iou + 0.35 * proximity, 0.0, 1.0))


def candidate_score(
    candidate: Candidate,
    cue: Dict[str, Any],
    scene: Dict[str, Any],
    frame: int,
    previous_bbox: Optional[Sequence[float]],
    frame_width: int,
    frame_height: int,
) -> Dict[str, float]:
    similarity = text_similarity(cue.get("text"), candidate.text)
    if similarity < 0.30:
        return {"score": 0.0, "text_similarity": similarity}
    cue_start = int(cue.get("start") or 0)
    cue_end = int(cue.get("end") or cue_start)
    # A new OCR seed may begin only near its cue. Once seeded, continuity may
    # legitimately keep a kinetic-typography word visible for the rest of the scene.
    if previous_bbox is None and (frame < cue_start - 2 or frame > cue_end + 6):
        return {"score": 0.0, "text_similarity": similarity, "temporal_gate": 0.0}
    tscore = temporal_score(frame, cue, scene)
    cscore = continuity_score(candidate, previous_bbox, frame_width, frame_height)
    dscore = dimension_score(candidate, str(cue.get("text") or ""), frame_width, frame_height)
    source_bonus = 0.04 if candidate.source_kind == "ocr_line_split_token" and similarity >= 0.80 else 0.0
    score = (
        0.58 * similarity
        + 0.14 * clamp(candidate.confidence, 0.0, 1.0)
        + 0.10 * tscore
        + 0.10 * cscore
        + 0.08 * dscore
        + source_bonus
    )
    return {
        "score": round(float(clamp(score, 0.0, 1.0)), 6),
        "text_similarity": similarity,
        "temporal_score": round(tscore, 6),
        "continuity_score": round(cscore, 6),
        "dimension_score": round(dscore, 6),
    }


def assign_candidates(
    candidates: Sequence[Candidate],
    cues: Sequence[Dict[str, Any]],
    scene: Dict[str, Any],
    frame: int,
    previous_boxes: Dict[str, Sequence[float]],
    frame_width: int,
    frame_height: int,
    min_assignment_score: float,
    min_text_similarity: float,
) -> Dict[str, Dict[str, Any]]:
    scored: List[Tuple[float, str, int, Dict[str, float]]] = []
    for cue in cues:
        cue_id = str(cue.get("cue_id") or "")
        for index, candidate in enumerate(candidates):
            detail = candidate_score(candidate, cue, scene, frame, previous_boxes.get(cue_id), frame_width, frame_height)
            if detail.get("score", 0.0) >= min_assignment_score and detail.get("text_similarity", 0.0) >= min_text_similarity:
                scored.append((float(detail["score"]), cue_id, index, detail))
    scored.sort(key=lambda row: (row[0], row[3].get("text_similarity", 0.0), candidates[row[2]].confidence), reverse=True)
    used_cues: set[str] = set()
    used_candidates: set[int] = set()
    used_full_lines: set[int] = set()
    used_split_tokens: set[Tuple[int, int]] = set()
    lines_with_split_assignments: set[int] = set()
    assignments: Dict[str, Dict[str, Any]] = {}
    for score, cue_id, candidate_index, detail in scored:
        if cue_id in used_cues or candidate_index in used_candidates:
            continue
        candidate = candidates[candidate_index]
        if candidate.source_kind == "ocr_line":
            if candidate.source_index in used_full_lines or candidate.source_index in lines_with_split_assignments:
                continue
        elif candidate.source_kind == "ocr_line_split_token":
            token_key = (candidate.source_index, int(candidate.split_token_index or 0))
            if candidate.source_index in used_full_lines or token_key in used_split_tokens:
                continue
        used_cues.add(cue_id)
        used_candidates.add(candidate_index)
        if candidate.source_kind == "ocr_line":
            used_full_lines.add(candidate.source_index)
        elif candidate.source_kind == "ocr_line_split_token":
            lines_with_split_assignments.add(candidate.source_index)
            used_split_tokens.add((candidate.source_index, int(candidate.split_token_index or 0)))
        assignments[cue_id] = {
            "method": "ocr",
            "candidate_id": candidate.candidate_id,
            "bbox": [round(float(v), 4) for v in candidate.bbox],
            "ocr_text": candidate.text,
            "ocr_source_text": candidate.source_text,
            "ocr_confidence": round(float(candidate.confidence), 6),
            "candidate_kind": candidate.source_kind,
            "assignment_score": round(score, 6),
            **detail,
        }
    return assignments


# ---------------------------------------------------------------------------
# Tracking, geometry and opacity proxy
# ---------------------------------------------------------------------------

def safe_crop(frame: np.ndarray, bbox: Sequence[float], padding: int = 0) -> Optional[np.ndarray]:
    height, width = frame.shape[:2]
    x1 = max(0, int(math.floor(float(bbox[0]))) - padding)
    y1 = max(0, int(math.floor(float(bbox[1]))) - padding)
    x2 = min(width, int(math.ceil(float(bbox[2]))) + padding)
    y2 = min(height, int(math.ceil(float(bbox[3]))) + padding)
    if x2 <= x1 or y2 <= y1:
        return None
    crop = frame[y1:y2, x1:x2]
    return crop if crop.size else None


def template_track(previous_frame: np.ndarray, frame: np.ndarray, previous_bbox: Sequence[float]) -> Optional[Dict[str, Any]]:
    height, width = frame.shape[:2]
    template = safe_crop(previous_frame, previous_bbox)
    if template is None or min(template.shape[:2]) < 4:
        return None
    x1, y1, x2, y2 = [float(v) for v in previous_bbox]
    bw, bh = x2 - x1, y2 - y1
    pad_x = max(12, int(round(bw * 0.40)))
    pad_y = max(12, int(round(bh * 0.55)))
    sx1, sy1 = max(0, int(x1) - pad_x), max(0, int(y1) - pad_y)
    sx2, sy2 = min(width, int(x2) + pad_x), min(height, int(y2) + pad_y)
    search = frame[sy1:sy2, sx1:sx2]
    if search.size == 0:
        return None
    template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    template_edge = cv2.Canny(template_gray, 50, 140)
    search_gray = cv2.cvtColor(search, cv2.COLOR_BGR2GRAY)
    search_edge = cv2.Canny(search_gray, 50, 140)
    best: Optional[Dict[str, Any]] = None
    for scale in (0.88, 0.94, 1.0, 1.06, 1.12):
        tw = max(4, int(round(template_edge.shape[1] * scale)))
        th = max(4, int(round(template_edge.shape[0] * scale)))
        if tw >= search_edge.shape[1] or th >= search_edge.shape[0]:
            continue
        resized = cv2.resize(template_edge, (tw, th), interpolation=cv2.INTER_LINEAR)
        result = cv2.matchTemplate(search_edge, resized, cv2.TM_CCOEFF_NORMED)
        _, max_value, _, max_location = cv2.minMaxLoc(result)
        candidate = {
            "score": float(max_value),
            "bbox": [
                float(sx1 + max_location[0]),
                float(sy1 + max_location[1]),
                float(sx1 + max_location[0] + tw),
                float(sy1 + max_location[1] + th),
            ],
            "scale": scale,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    if best and best["score"] >= 0.58:
        best["method"] = "template_track"
        return best
    return None


def opacity_contrast_proxy(frame: np.ndarray, bbox: Sequence[float]) -> float:
    crop = safe_crop(frame, bbox, padding=2)
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    border = np.concatenate(
        [gray[:2, :].reshape(-1), gray[-2:, :].reshape(-1), gray[:, :2].reshape(-1), gray[:, -2:].reshape(-1)]
    )
    bg = float(np.median(border)) if border.size else float(np.median(gray))
    contrast = np.abs(gray.astype(np.float32) - bg)
    edges = cv2.Canny(gray, 45, 135)
    contrast_score = float(np.percentile(contrast, 85)) / 255.0
    edge_score = float(np.count_nonzero(edges)) / max(1, edges.size)
    return round(float(clamp(0.72 * contrast_score + 0.28 * min(1.0, edge_score * 8.0), 0.0, 1.0)), 6)


def interpolate_track_observations(observations: List[Dict[str, Any]], max_gap: int) -> List[Dict[str, Any]]:
    if len(observations) < 2:
        return observations
    by_frame = {int(item["timeline_frame"]): dict(item) for item in observations}
    frames = sorted(by_frame)
    for left, right in zip(frames, frames[1:]):
        gap = right - left - 1
        if gap <= 0 or gap > max_gap:
            continue
        a, b = by_frame[left], by_frame[right]
        for offset in range(1, gap + 1):
            ratio = offset / (gap + 1)
            bbox = [float(a["bbox_px"][i]) * (1.0 - ratio) + float(b["bbox_px"][i]) * ratio for i in range(4)]
            frame = left + offset
            by_frame[frame] = {
                "timeline_frame": frame,
                "source_frame": int(round(float(a["source_frame"]) * (1.0 - ratio) + float(b["source_frame"]) * ratio)),
                "method": "interpolated_short_gap",
                "bbox_px": [round(value, 4) for value in bbox],
                "ocr_text": None,
                "ocr_confidence": None,
                "text_similarity": None,
                "assignment_score": round(min(float(a.get("assignment_score") or 0.0), float(b.get("assignment_score") or 0.0)) * 0.85, 6),
                "tracking_score": None,
                "raw_opacity_proxy": round(float(a.get("raw_opacity_proxy") or 0.0) * (1.0 - ratio) + float(b.get("raw_opacity_proxy") or 0.0) * ratio, 6),
            }
    return [by_frame[frame] for frame in sorted(by_frame)]


def robust_track_cleanup(observations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if len(observations) < 4:
        return observations
    centers = np.array([bbox_center(item["bbox_px"]) for item in observations], dtype=np.float64)
    sizes = np.array([bbox_size(item["bbox_px"]) for item in observations], dtype=np.float64)
    median_center = np.median(centers, axis=0)
    median_size = np.median(sizes, axis=0)
    mad_center = np.median(np.abs(centers - median_center), axis=0) + 1.0
    mad_size = np.median(np.abs(sizes - median_size), axis=0) + 1.0
    cleaned: List[Dict[str, Any]] = []
    for item, center, size in zip(observations, centers, sizes):
        center_z = float(np.max(np.abs(center - median_center) / mad_center))
        size_z = float(np.max(np.abs(size - median_size) / mad_size))
        method = str(item.get("method") or "")
        # OCR observations are kept under a looser bound; tracking outliers are removed aggressively.
        limit = 10.0 if method == "ocr" else 6.0
        if center_z <= limit and size_z <= limit:
            cleaned.append(item)
    return cleaned if cleaned else observations


def finalize_track(
    cue: Dict[str, Any],
    scene: Dict[str, Any],
    observations: List[Dict[str, Any]],
    frame_width: int,
    frame_height: int,
    max_interp_gap: int,
) -> Dict[str, Any]:
    observations = robust_track_cleanup(observations)
    observations = interpolate_track_observations(observations, max_interp_gap)
    heights = [bbox_size(item["bbox_px"])[1] for item in observations if bbox_valid(item.get("bbox_px"))]
    widths = [bbox_size(item["bbox_px"])[0] for item in observations if bbox_valid(item.get("bbox_px"))]
    median_height = float(np.median(heights)) if heights else 0.0
    median_width = float(np.median(widths)) if widths else 0.0
    max_opacity = max([float(item.get("raw_opacity_proxy") or 0.0) for item in observations] + [0.001])
    dense: List[Dict[str, Any]] = []
    for item in observations:
        bbox = [float(value) for value in item["bbox_px"]]
        width, height = bbox_size(bbox)
        scale = math.sqrt(max(1e-8, width * height) / max(1e-8, median_width * median_height)) if median_width and median_height else 1.0
        dense.append(
            {
                **item,
                "bbox_px": [round(value, 4) for value in bbox],
                "normalized_bbox": normalized_bbox(bbox, frame_width, frame_height),
                "position": normalized_center(bbox, frame_width, frame_height),
                "scale_proxy": round(float(scale), 6),
                "opacity_proxy": round(float(clamp(float(item.get("raw_opacity_proxy") or 0.0) / max_opacity, 0.0, 1.0)), 6),
            }
        )
    direct = [item for item in dense if item.get("method") == "ocr"]
    tracked = [item for item in dense if item.get("method") == "template_track"]
    cue_start, cue_end = int(cue.get("start") or 0), int(cue.get("end") or 0)
    own_frames = set(range(cue_start, max(cue_start, cue_end) + 1))
    observed_own = {int(item["timeline_frame"]) for item in dense if int(item["timeline_frame"]) in own_frames}
    own_coverage = len(observed_own) / max(1, len(own_frames))
    scene_frames = set(range(int(scene.get("start_frame") or cue_start), int(scene.get("end_frame") or cue_end) + 1))
    observed_scene = {int(item["timeline_frame"]) for item in dense if int(item["timeline_frame"]) in scene_frames}
    scene_coverage = len(observed_scene) / max(1, len(scene_frames))
    similarities = [float(item.get("text_similarity")) for item in direct if item.get("text_similarity") is not None]
    confidences = [float(item.get("ocr_confidence")) for item in direct if item.get("ocr_confidence") is not None]
    assignment_scores = [float(item.get("assignment_score")) for item in direct if item.get("assignment_score") is not None]
    accepted = (
        len(direct) >= 1
        and len(dense) >= 2
        and own_coverage >= 0.45
        and (float(np.median(similarities)) if similarities else 0.0) >= 0.62
        and (float(np.median(confidences)) if confidences else 0.0) >= 0.24
    )
    reasons: List[str] = []
    if len(direct) < 1:
        reasons.append("no_direct_ocr_seed")
    if len(dense) < 2:
        reasons.append("insufficient_dense_observations")
    if own_coverage < 0.45:
        reasons.append("cue_window_coverage_below_0_45")
    if (float(np.median(similarities)) if similarities else 0.0) < 0.62:
        reasons.append("median_text_similarity_below_0_62")
    if (float(np.median(confidences)) if confidences else 0.0) < 0.24:
        reasons.append("median_ocr_confidence_below_0_24")
    return {
        "cue_id": cue.get("cue_id"),
        "cue_index": cue.get("cue_index"),
        "text": cue.get("text"),
        "style_profile_id": cue.get("style_profile_id"),
        "scene_id": scene.get("scene_id"),
        "cue_start_frame": cue_start,
        "cue_end_frame": cue_end,
        "accepted_source_instance": bool(accepted),
        "source_exactness": "source_redetected_dense_word_instance" if accepted else "unresolved_not_source_exact",
        "confidence": {
            "direct_ocr_frame_count": len(direct),
            "template_tracked_frame_count": len(tracked),
            "dense_observation_count": len(dense),
            "cue_window_coverage": round(own_coverage, 6),
            "scene_window_coverage": round(scene_coverage, 6),
            "median_text_similarity": round(float(np.median(similarities)), 6) if similarities else 0.0,
            "median_ocr_confidence": round(float(np.median(confidences)), 6) if confidences else 0.0,
            "median_assignment_score": round(float(np.median(assignment_scores)), 6) if assignment_scores else 0.0,
            "label": "high" if accepted and len(direct) >= 3 and own_coverage >= 0.75 else "medium" if accepted else "unresolved",
        },
        "fallback_reasons": reasons,
        "geometry": {
            "median_bbox_width_px": round(median_width, 4),
            "median_bbox_height_px": round(median_height, 4),
            "first_visible_frame": int(dense[0]["timeline_frame"]) if dense else None,
            "last_visible_frame": int(dense[-1]["timeline_frame"]) if dense else None,
        },
        "frame_observations": dense,
    }


# ---------------------------------------------------------------------------
# Debug rendering
# ---------------------------------------------------------------------------

def draw_scene_overlay(frame: np.ndarray, frame_number: int, scene_tracks: Dict[str, List[Dict[str, Any]]], cue_texts: Dict[str, str]) -> np.ndarray:
    canvas = frame.copy()
    for cue_id, observations in scene_tracks.items():
        item = next((row for row in observations if int(row.get("timeline_frame") or -1) == frame_number), None)
        if not item or not bbox_valid(item.get("bbox_px")):
            continue
        x1, y1, x2, y2 = [int(round(v)) for v in item["bbox_px"]]
        cv2.rectangle(canvas, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f"{cue_id}:{cue_texts.get(cue_id, '')} {item.get('method', '')}"
        cv2.putText(canvas, label[:42], (x1, max(16, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 255, 0), 1, cv2.LINE_AA)
    cv2.putText(canvas, f"timeline frame {frame_number}", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
    return canvas


def resize_for_sheet(frame: np.ndarray, max_width: int = 520) -> np.ndarray:
    height, width = frame.shape[:2]
    if width <= max_width:
        return frame
    scale = max_width / width
    return cv2.resize(frame, (max_width, max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)


def build_contact_sheet(images: Sequence[np.ndarray], columns: int = 3) -> Optional[np.ndarray]:
    if not images:
        return None
    normalized = [resize_for_sheet(image) for image in images]
    cell_h = max(image.shape[0] for image in normalized)
    cell_w = max(image.shape[1] for image in normalized)
    rows = int(math.ceil(len(normalized) / columns))
    sheet = np.zeros((rows * cell_h, columns * cell_w, 3), dtype=np.uint8)
    for index, image in enumerate(normalized):
        row, col = divmod(index, columns)
        sheet[row * cell_h : row * cell_h + image.shape[0], col * cell_w : col * cell_w + image.shape[1]] = image
    return sheet


# ---------------------------------------------------------------------------
# Status/log/checkpoint
# ---------------------------------------------------------------------------

def append_log(path: Path, event: str, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {"timestamp_unix": time.time(), "event": event, **payload}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(json_safe(row), ensure_ascii=False) + "\n")


def update_status(path: Path, **payload: Any) -> None:
    write_json(path, {"version": VERSION, "updated_at_unix": time.time(), **json_safe(payload)})


def checkpoint_compatible(checkpoint: Dict[str, Any], plan_hash: str, video_hash: str) -> bool:
    return (
        checkpoint.get("version") == VERSION
        and checkpoint.get("plan_hash") == plan_hash
        and checkpoint.get("video_sha256") == video_hash
        and isinstance(checkpoint.get("completed_scenes"), list)
    )


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def read_video_info(video_path: Path) -> Dict[str, Any]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video: {video_path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise RuntimeError("Source-video metadata is incomplete.")
    return {
        "path": str(video_path),
        "fps": round(fps, 8),
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration_seconds": round(frame_count / fps, 8),
        "is_proxy": "proxy" in video_path.stem.lower(),
    }


def resize_for_ocr(frame: np.ndarray, max_side: int) -> Tuple[np.ndarray, float, float]:
    height, width = frame.shape[:2]
    longest = max(height, width)
    if max_side <= 0 or longest <= max_side:
        return frame, 1.0, 1.0
    scale = max_side / longest
    resized = cv2.resize(frame, (max(1, int(round(width * scale))), max(1, int(round(height * scale)))), interpolation=cv2.INTER_AREA)
    return resized, width / resized.shape[1], height / resized.shape[0]


def read_frame(cap: Any, source_frame: int) -> Optional[np.ndarray]:
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(source_frame)))
    ok, frame = cap.read()
    return frame if ok and frame is not None else None


def process_scene(
    scene: Dict[str, Any],
    cues: List[Dict[str, Any]],
    video_path: Path,
    video_info: Dict[str, Any],
    plan_fps: float,
    engine: Any,
    args: argparse.Namespace,
    temp_dir: Path,
    debug_dir: Path,
    status_path: Path,
    log_path: Path,
    scene_index: int,
    scene_count: int,
) -> Dict[str, Any]:
    scene_id = str(scene.get("scene_id") or f"scene_{scene_index:03d}")
    start = int(scene.get("start_frame") or 0)
    end = int(scene.get("end_frame") or start)
    cue_by_id = {str(cue.get("cue_id")): cue for cue in cues}
    cue_texts = {cue_id: str(cue.get("text") or "") for cue_id, cue in cue_by_id.items()}
    observations: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    previous_boxes: Dict[str, Sequence[float]] = {}
    previous_frame: Optional[np.ndarray] = None
    last_direct_frame: Dict[str, int] = {}
    representative_frames: Dict[int, np.ndarray] = {}
    total_frames = max(1, end - start + 1)
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open source video for scene {scene_id}")
    errors: List[Dict[str, Any]] = []
    ocr_detection_count = 0
    assignment_count = 0
    tracking_count = 0
    try:
        for offset, timeline_frame in enumerate(range(start, end + 1)):
            source_frame = source_frame_for_timeline_frame(timeline_frame, plan_fps, float(video_info["fps"]))
            frame = read_frame(cap, source_frame)
            if frame is None:
                errors.append({"timeline_frame": timeline_frame, "source_frame": source_frame, "error": "frame_read_failed"})
                continue
            height, width = frame.shape[:2]
            ocr_frame, scale_x, scale_y = resize_for_ocr(frame, args.ocr_max_side)
            assignments: Dict[str, Dict[str, Any]] = {}
            if (timeline_frame - start) % max(1, args.ocr_stride) == 0:
                try:
                    result = run_ocr(engine, ocr_frame, temp_dir, f"{scene_id}_{timeline_frame}")
                    parsed = parse_paddle_result(result)
                    candidates = build_candidates(parsed, scale_x, scale_y, width, height, args.min_ocr_confidence)
                    ocr_detection_count += len(candidates)
                    assignments = assign_candidates(
                        candidates,
                        cues,
                        scene,
                        timeline_frame,
                        previous_boxes,
                        width,
                        height,
                        args.min_assignment_score,
                        args.min_text_similarity,
                    )
                except Exception as exc:
                    errors.append({"timeline_frame": timeline_frame, "source_frame": source_frame, "error": f"ocr_failed:{type(exc).__name__}:{exc}"})
            # Add direct OCR assignments.
            for cue_id, assignment in assignments.items():
                bbox = assignment["bbox"]
                assignment_count += 1
                last_direct_frame[cue_id] = timeline_frame
                previous_boxes[cue_id] = bbox
                observations[cue_id].append(
                    {
                        "timeline_frame": timeline_frame,
                        "source_frame": source_frame,
                        **assignment,
                        "bbox_px": bbox,
                        "tracking_score": None,
                        "raw_opacity_proxy": opacity_contrast_proxy(frame, bbox),
                    }
                )
            # Track cues missed by OCR for a short bounded gap.
            if previous_frame is not None:
                for cue in cues:
                    cue_id = str(cue.get("cue_id") or "")
                    if cue_id in assignments or cue_id not in previous_boxes:
                        continue
                    direct_frame = last_direct_frame.get(cue_id)
                    if direct_frame is None or timeline_frame - direct_frame > args.max_track_gap:
                        continue
                    tracked = template_track(previous_frame, frame, previous_boxes[cue_id])
                    if not tracked:
                        continue
                    bbox = tracked["bbox"]
                    previous_boxes[cue_id] = bbox
                    tracking_count += 1
                    observations[cue_id].append(
                        {
                            "timeline_frame": timeline_frame,
                            "source_frame": source_frame,
                            "method": "template_track",
                            "bbox_px": [round(float(v), 4) for v in bbox],
                            "ocr_text": None,
                            "ocr_source_text": None,
                            "ocr_confidence": None,
                            "candidate_kind": None,
                            "assignment_score": round(float(tracked["score"]) * 0.82, 6),
                            "text_similarity": None,
                            "tracking_score": round(float(tracked["score"]), 6),
                            "raw_opacity_proxy": opacity_contrast_proxy(frame, bbox),
                        }
                    )
            # Keep a few representative frames for the scene contact sheet.
            representative_targets = {start, int(round((start + end) / 2)), end}
            if timeline_frame in representative_targets:
                representative_frames[timeline_frame] = frame.copy()
            previous_frame = frame
            percent = ((offset + 1) / total_frames) * 100.0
            update_status(
                status_path,
                ok=False,
                running=True,
                step="Major Step 3B.6B",
                stage="dense_word_instance_redetection",
                scene_id=scene_id,
                scene_index=scene_index,
                scene_count=scene_count,
                current_frame=timeline_frame,
                scene_start_frame=start,
                scene_end_frame=end,
                scene_percent=round(percent, 2),
            )
            if offset % 5 == 0 or timeline_frame == end:
                print(f"[{scene_index}/{scene_count}] {scene_id}: frame {timeline_frame}/{end} ({percent:.1f}%)", flush=True)
    finally:
        cap.release()

    finalized: List[Dict[str, Any]] = []
    for cue in cues:
        cue_id = str(cue.get("cue_id") or "")
        finalized.append(finalize_track(cue, scene, observations.get(cue_id, []), int(video_info["width"]), int(video_info["height"]), args.max_interpolation_gap))

    # Source-supported ordering proxy: first visible frame, then smaller text above larger text.
    visible = [track for track in finalized if track.get("geometry", {}).get("first_visible_frame") is not None]
    visible.sort(key=lambda track: (track["geometry"]["first_visible_frame"], -float(track["geometry"].get("median_bbox_height_px") or 0.0), int(track.get("cue_index") or 0)))
    for order, track in enumerate(visible):
        track["scene_membership"] = {
            "scene_id": scene_id,
            "z_order_index_proxy": order,
            "z_order_method": "first_visible_frame_then_size_proxy",
            "z_order_confidence": "low_requires_scene_probe",
        }
    for track in finalized:
        if "scene_membership" not in track:
            track["scene_membership"] = {
                "scene_id": scene_id,
                "z_order_index_proxy": None,
                "z_order_method": "unresolved",
                "z_order_confidence": "none",
            }

    scene_track_map = {str(track["cue_id"]): track.get("frame_observations") or [] for track in finalized}
    debug_images: List[np.ndarray] = []
    for frame_number in sorted(representative_frames):
        debug_images.append(draw_scene_overlay(representative_frames[frame_number], frame_number, scene_track_map, cue_texts))
    contact_sheet = build_contact_sheet(debug_images)
    debug_path = debug_dir / f"{scene_id}_contact_sheet.jpg"
    if contact_sheet is not None:
        debug_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(debug_path), contact_sheet, [int(cv2.IMWRITE_JPEG_QUALITY), 90])

    accepted_count = sum(1 for track in finalized if track.get("accepted_source_instance"))
    result = {
        "scene_id": scene_id,
        "start_frame": start,
        "end_frame": end,
        "cue_count": len(cues),
        "accepted_cue_count": accepted_count,
        "unresolved_cue_count": len(cues) - accepted_count,
        "accepted_ratio": round(accepted_count / max(1, len(cues)), 6),
        "ocr_candidate_count": ocr_detection_count,
        "direct_assignment_count": assignment_count,
        "template_tracking_count": tracking_count,
        "debug_contact_sheet": str(debug_path) if debug_path.exists() else None,
        "errors": errors,
        "tracks": finalized,
    }
    append_log(log_path, "scene_completed", {"scene_id": scene_id, "accepted": accepted_count, "total": len(cues), "errors": len(errors)})
    return result


def build_summary(payload: Dict[str, Any]) -> str:
    summary = payload.get("summary") or {}
    lines = [
        "Video Cloner — Major Step 3B.6B dense word-instance re-detection",
        "",
        f"Source video: {payload.get('source_video')}",
        f"OCR device: {(payload.get('ocr') or {}).get('selected_device')}",
        f"Flagged scenes processed: {summary.get('scene_count')}",
        f"Target cues processed: {summary.get('target_cue_count')}",
        f"Accepted source instances: {summary.get('accepted_source_instance_count')}",
        f"Unresolved source instances: {summary.get('unresolved_source_instance_count')}",
        f"Direct OCR observations: {summary.get('direct_ocr_observation_count')}",
        f"Template-tracked observations: {summary.get('template_tracked_observation_count')}",
        f"Dense frame observations: {summary.get('dense_frame_observation_count')}",
        f"Scenes ready for a geometry probe: {summary.get('scene_probe_ready_count')}",
        f"Preferred next probe scene: {summary.get('preferred_probe_scene_id')}",
        "",
        "Decision:",
        "- This step is read-only and does not modify Resolve.",
        "- Accepted cues may be used by Step 3B.6C.",
        "- Unresolved cues remain explicitly non-source-exact; they are not silently replaced with group boxes.",
        "- Z-order is only a low-confidence appearance-order proxy until the scene probe is visually approved.",
    ]
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> Dict[str, Any]:
    started = time.time()
    plan_path = Path(args.redetection_plan).resolve()
    audit_path = Path(args.audit).resolve()
    audit_validation_path = Path(args.audit_validation).resolve()
    video_path = Path(args.video).resolve()
    output_path = Path(args.output).resolve()
    summary_path = Path(args.summary).resolve()
    debug_dir = Path(args.debug_dir).resolve()
    status_path = Path(args.status).resolve()
    log_path = Path(args.log).resolve()
    checkpoint_path = Path(args.checkpoint).resolve()

    plan = load_json(plan_path)
    audit = load_json(audit_path)
    audit_validation = load_json(audit_validation_path)
    failures: List[str] = []
    warnings: List[str] = []
    if not plan.get("ok") or plan.get("schema") != "video_cloner_caption_scene_redetection_plan":
        failures.append("redetection_plan_gate_failed")
    if not audit.get("ok") or not audit_validation.get("ok"):
        failures.append("step_3B_6A_gate_failed")
    if plan.get("source_audit_hash") != audit.get("audit_hash"):
        failures.append("audit_hash_mismatch")
    if int((audit.get("summary") or {}).get("dense_word_instance_redetection_required_count") or 0) != EXPECTED_TARGET_COUNT:
        failures.append("target_count_gate_failed")
    scenes = [scene for scene in (plan.get("scenes") or []) if isinstance(scene, dict)]
    targets = [cue for cue in (plan.get("cue_targets") or []) if isinstance(cue, dict)]
    if len(scenes) != EXPECTED_SCENE_COUNT:
        failures.append(f"scene_count_mismatch:{len(scenes)}")
    if len(targets) != EXPECTED_TARGET_COUNT:
        failures.append(f"target_count_mismatch:{len(targets)}")
    if not video_path.exists():
        failures.append(f"source_video_missing:{video_path}")
    if "proxy" in video_path.stem.lower() and not args.allow_proxy:
        failures.append("proxy_video_forbidden_for_source_exact_redetection")
    if failures:
        payload = {
            "ok": False,
            "step": "Major Step 3B.6B",
            "version": VERSION,
            "failures": failures,
            "warnings": warnings,
            "timeline_modified": False,
            "runtime_seconds": round(time.time() - started, 3),
        }
        write_json(output_path, payload)
        write_text(summary_path, build_summary(payload))
        update_status(status_path, ok=False, running=False, step="Major Step 3B.6B", stage="preflight_failed", failures=failures)
        return payload

    plan_hash = str(plan.get("plan_hash") or canonical_hash(plan))
    video_hash = file_sha256(video_path)
    video_info = read_video_info(video_path)
    if abs(float(video_info["fps"]) - float(plan.get("frame_rate") or 24.0)) > 2.0:
        warnings.append("Source-video FPS differs materially from the plan FPS; time-based frame mapping is being used.")
    if bool(video_info.get("is_proxy")):
        warnings.append("Proxy video used. Results cannot be promoted as source exact without rerunning on the original MP4.")

    if args.clear_debug and debug_dir.exists():
        shutil.rmtree(debug_dir, ignore_errors=True)
    debug_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.resume and log_path.exists():
        log_path.unlink()
    append_log(log_path, "run_started", {"version": VERSION, "video": str(video_path), "plan_hash": plan_hash})
    update_status(status_path, ok=False, running=True, step="Major Step 3B.6B", stage="initializing_ocr", scene_count=len(scenes))
    print("Initializing PaddleOCR. The first run can take longer while models are loaded...", flush=True)
    engine, ocr_info = create_ocr(args.ocr_lang, args.ocr_device, args.ocr_gpu_id)
    append_log(log_path, "ocr_initialized", ocr_info)

    target_by_id = {str(cue.get("cue_id")): cue for cue in targets}
    completed: Dict[str, Dict[str, Any]] = {}
    if args.resume and checkpoint_path.exists():
        checkpoint = load_json(checkpoint_path)
        if checkpoint_compatible(checkpoint, plan_hash, video_hash):
            completed = {str(item.get("scene_id")): item for item in checkpoint.get("completed_scenes") or [] if isinstance(item, dict)}
            print(f"Resuming from checkpoint: {len(completed)} completed scene(s).", flush=True)
        else:
            warnings.append("Existing checkpoint was incompatible and was ignored.")

    scene_results: List[Dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="vc_step_3b6b_") as temp_name:
        temp_dir = Path(temp_name)
        for index, scene in enumerate(scenes, start=1):
            scene_id = str(scene.get("scene_id") or "")
            if scene_id in completed:
                scene_result = completed[scene_id]
                scene_results.append(scene_result)
                print(f"[{index}/{len(scenes)}] {scene_id}: reused from checkpoint", flush=True)
                continue
            cues = [target_by_id[cue_id] for cue_id in scene.get("cue_ids") or [] if cue_id in target_by_id]
            scene_result = process_scene(
                scene,
                cues,
                video_path,
                video_info,
                float(plan.get("frame_rate") or 24.0),
                engine,
                args,
                temp_dir,
                debug_dir,
                status_path,
                log_path,
                index,
                len(scenes),
            )
            scene_results.append(scene_result)
            completed[scene_id] = scene_result
            checkpoint_payload = {
                "ok": True,
                "step": "Major Step 3B.6B checkpoint",
                "version": VERSION,
                "plan_hash": plan_hash,
                "video_sha256": video_hash,
                "completed_scenes": [completed[key] for key in sorted(completed)],
            }
            checkpoint_payload["checkpoint_hash"] = canonical_hash(checkpoint_payload)
            write_json(checkpoint_path, checkpoint_payload)

    tracks = [track for scene in scene_results for track in scene.get("tracks") or []]
    accepted = [track for track in tracks if track.get("accepted_source_instance")]
    unresolved = [track for track in tracks if not track.get("accepted_source_instance")]
    direct_obs = sum(int((track.get("confidence") or {}).get("direct_ocr_frame_count") or 0) for track in tracks)
    tracked_obs = sum(int((track.get("confidence") or {}).get("template_tracked_frame_count") or 0) for track in tracks)
    dense_obs = sum(int((track.get("confidence") or {}).get("dense_observation_count") or 0) for track in tracks)
    ready_scenes = [scene for scene in scene_results if float(scene.get("accepted_ratio") or 0.0) >= args.scene_probe_ready_ratio]
    preferred = None
    # Prefer the known complex back/hand scene if it is ready; otherwise use the best scene.
    scene_008 = next((scene for scene in ready_scenes if scene.get("scene_id") == "caption_scene_008"), None)
    if scene_008:
        preferred = "caption_scene_008"
    elif ready_scenes:
        preferred = sorted(ready_scenes, key=lambda scene: (float(scene.get("accepted_ratio") or 0.0), int(scene.get("cue_count") or 0)), reverse=True)[0].get("scene_id")

    payload: Dict[str, Any] = {
        "ok": True,
        "step": "Major Step 3B.6B",
        "version": VERSION,
        "schema": SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "created_at_unix": time.time(),
        "source_video": str(video_path),
        "source_video_sha256": video_hash,
        "source_video_info": video_info,
        "redetection_plan": str(plan_path),
        "redetection_plan_hash": plan_hash,
        "source_audit": str(audit_path),
        "source_audit_hash": audit.get("audit_hash"),
        "ocr": ocr_info,
        "configuration": {
            "ocr_stride": args.ocr_stride,
            "ocr_max_side": args.ocr_max_side,
            "min_ocr_confidence": args.min_ocr_confidence,
            "min_assignment_score": args.min_assignment_score,
            "min_text_similarity": args.min_text_similarity,
            "max_track_gap": args.max_track_gap,
            "max_interpolation_gap": args.max_interpolation_gap,
            "scene_probe_ready_ratio": args.scene_probe_ready_ratio,
        },
        "required_output_contract": plan.get("required_output_contract"),
        "effect_policy": plan.get("effect_policy"),
        "summary": {
            "v3_item_count": EXPECTED_V3_COUNT,
            "scene_count": len(scene_results),
            "target_cue_count": len(tracks),
            "accepted_source_instance_count": len(accepted),
            "unresolved_source_instance_count": len(unresolved),
            "direct_ocr_observation_count": direct_obs,
            "template_tracked_observation_count": tracked_obs,
            "dense_frame_observation_count": dense_obs,
            "scene_probe_ready_count": len(ready_scenes),
            "preferred_probe_scene_id": preferred,
            "full_exact_geometry_rollout_ready": len(unresolved) == 0,
            "timeline_modified": False,
        },
        "scenes": scene_results,
        "tracks": tracks,
        "warnings": warnings
        + ([f"{len(unresolved)} cue(s) remain unresolved and must not be presented as source exact."] if unresolved else []),
        "failures": [],
        "timeline_modified": False,
        "runtime_seconds": round(time.time() - started, 3),
    }
    payload["tracks_hash"] = canonical_hash(payload)
    write_json(output_path, payload)
    write_text(summary_path, build_summary(payload))
    update_status(
        status_path,
        ok=True,
        running=False,
        step="Major Step 3B.6B",
        stage="complete",
        output=str(output_path),
        summary=payload["summary"],
        runtime_seconds=payload["runtime_seconds"],
    )
    append_log(log_path, "run_completed", {"summary": payload["summary"], "runtime_seconds": payload["runtime_seconds"]})
    print(json.dumps({"ok": True, "step": payload["step"], "summary": payload["summary"], "output": str(output_path)}, indent=2), flush=True)
    return payload


def self_test() -> None:
    bbox = [100.0, 50.0, 400.0, 120.0]
    tokens = split_line_tokens("the BACK", bbox)
    assert len(tokens) == 2 and tokens[0][1][2] < tokens[1][1][0]
    candidates = [Candidate("a", "back", 0.92, [210, 50, 400, 120], "the BACK", "ocr_line_split_token", 0)]
    cue = {"cue_id": "sub_063", "text": "back", "start": 474, "end": 480}
    scene = {"start_frame": 474, "end_frame": 521}
    assigned = assign_candidates(candidates, [cue], scene, 476, {}, 1080, 1920, 0.55, 0.55)
    assert "sub_063" in assigned
    observations = [
        {"timeline_frame": 1, "source_frame": 1, "bbox_px": [0, 0, 10, 10], "method": "ocr", "raw_opacity_proxy": 0.5, "assignment_score": 0.9},
        {"timeline_frame": 3, "source_frame": 3, "bbox_px": [2, 0, 12, 10], "method": "ocr", "raw_opacity_proxy": 1.0, "assignment_score": 0.9},
    ]
    interpolated = interpolate_track_observations(observations, 2)
    assert [item["timeline_frame"] for item in interpolated] == [1, 2, 3]
    print("SELF-TEST PASS")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--redetection-plan")
    parser.add_argument("--audit")
    parser.add_argument("--audit-validation")
    parser.add_argument("--video")
    parser.add_argument("--output")
    parser.add_argument("--summary")
    parser.add_argument("--debug-dir")
    parser.add_argument("--status")
    parser.add_argument("--log")
    parser.add_argument("--checkpoint")
    parser.add_argument("--ocr-lang", default="en")
    parser.add_argument("--ocr-device", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--ocr-gpu-id", type=int, default=0)
    parser.add_argument("--ocr-stride", type=int, default=1)
    parser.add_argument("--ocr-max-side", type=int, default=1600)
    parser.add_argument("--min-ocr-confidence", type=float, default=0.20)
    parser.add_argument("--min-assignment-score", type=float, default=0.55)
    parser.add_argument("--min-text-similarity", type=float, default=0.55)
    parser.add_argument("--max-track-gap", type=int, default=3)
    parser.add_argument("--max-interpolation-gap", type=int, default=2)
    parser.add_argument("--scene-probe-ready-ratio", type=float, default=0.70)
    parser.add_argument("--allow-proxy", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--clear-debug", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.self_test:
        self_test()
        return 0
    required = ("redetection_plan", "audit", "audit_validation", "video", "output", "summary", "debug_dir", "status", "log", "checkpoint")
    missing = [name for name in required if not getattr(args, name)]
    if missing:
        raise SystemExit(f"Missing required arguments: {', '.join(missing)}")
    try:
        payload = run(args)
        return 0 if payload.get("ok") else 1
    except Exception as exc:
        tb = traceback.format_exc()
        error_payload = {
            "ok": False,
            "step": "Major Step 3B.6B",
            "version": VERSION,
            "run_mode": "exception",
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback": tb,
            "failures": ["redetection_exception"],
            "timeline_modified": False,
        }
        try:
            write_json(Path(args.output).resolve(), error_payload)
        except Exception:
            pass
        try:
            update_status(
                Path(args.status).resolve(),
                ok=False,
                running=False,
                step="Major Step 3B.6B",
                stage="exception",
                failures=error_payload["failures"],
                exception=error_payload["exception"],
                traceback=tb,
            )
        except Exception:
            pass
        try:
            append_log(Path(args.log).resolve(), "run_exception", error_payload)
        except Exception:
            pass
        print(tb, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
