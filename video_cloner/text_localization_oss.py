"""Expected-text matching for optional OSS caption-localization fallbacks."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

import numpy as np


def _normalized(value: object) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").lower()))


def text_similarity(expected: object, observed: object) -> float:
    left, right = _normalized(expected), _normalized(observed)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right).ratio()


def _rect(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError("localization_bbox")
    x1, y1, x2, y2 = (float(part) for part in value)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("localization_bbox")
    return x1, y1, x2, y2


def _iou(left: object, right: object) -> float:
    ax1, ay1, ax2, ay2 = _rect(left)
    bx1, by1, bx2, by2 = _rect(right)
    overlap = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - overlap
    return overlap / union if union else 0.0


def anchor_frames(caption: dict[str, Any]) -> list[int]:
    start = int(caption["start_frame"])
    duration = int(caption["duration"])
    if start < 0 or duration < 1:
        raise ValueError("caption_window")
    return sorted({start, start + (duration - 1) // 2, start + duration - 1})


def rank_candidates(
    expected: str,
    candidates: list[dict[str, Any]],
    frame_size: tuple[int, int],
    prior_bbox: list[object] | None = None,
) -> list[dict[str, Any]]:
    height, width = frame_size
    prior = _rect(prior_bbox) if prior_bbox else None
    rows = []
    for candidate in candidates:
        try:
            x1, y1, x2, y2 = _rect(candidate.get("bbox"))
        except ValueError:
            continue
        similarity = text_similarity(expected, candidate.get("text"))
        recognition = max(0.0, min(1.0, float(candidate.get("confidence") or 0.0)))
        center_x, center_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0
        if prior:
            px1, py1, px2, py2 = prior
            distance = np.hypot((center_x - (px1 + px2) / 2.0) / width, (center_y - (py1 + py2) / 2.0) / height)
            location = max(0.0, 1.0 - float(distance) * 2.0)
            geometry = _iou(candidate["bbox"], prior)
        else:
            location = max(0.0, 1.0 - abs(center_x / width - 0.5) - abs(center_y / height - 0.5))
            geometry = min(1.0, (x2 - x1) * (y2 - y1) / max(1.0, width * height * 0.02))
        score = 0.65 * similarity + 0.15 * recognition + 0.12 * location + 0.08 * geometry
        rows.append({**candidate, "text_similarity": round(similarity, 4), "selection_score": round(score, 4)})
    return sorted(rows, key=lambda row: (row["selection_score"], row["text_similarity"], row.get("confidence", 0.0)), reverse=True)


def fallback_event(
    caption: dict[str, Any],
    fps: float,
    frame_size: tuple[int, int],
    detections: dict[int, list[dict[str, Any]]],
    source: str,
    prior_bbox: list[object] | None = None,
) -> dict[str, Any]:
    observations = []
    for frame in anchor_frames(caption):
        ranked = rank_candidates(str(caption["text"]), detections.get(frame) or [], frame_size, prior_bbox)
        if not ranked:
            continue
        best = ranked[0]
        runner_up = ranked[1]["selection_score"] if len(ranked) > 1 else 0.0
        if best["text_similarity"] < 0.5 or best["selection_score"] < 0.55:
            continue
        if best["text_similarity"] < 0.9 and best["selection_score"] - runner_up < 0.08:
            continue
        observations.append(
            {
                "frame": frame,
                "timestamp": frame / fps,
                "bbox": [round(float(part), 3) for part in best["bbox"]],
                "text": str(best.get("text") or ""),
                "recognition_confidence": round(float(best.get("confidence") or 0.0), 4),
                "text_similarity": best["text_similarity"],
                "localization_confidence": best["selection_score"],
                "observation_provenance": f"accepted_{source}",
            }
        )
    if not observations:
        raise ValueError(f"fallback_localization:{caption['ordinal']}")
    confidence = float(np.mean([row["localization_confidence"] for row in observations]))
    return {
        "event_id": f"{source}:{caption['caption_id']}",
        "cue_id": caption["caption_id"],
        "role": "spoken_caption",
        "start": int(caption["start_frame"]) / fps,
        "end": (int(caption["start_frame"]) + int(caption["duration"])) / fps,
        "placement": {"bbox": observations[-1]["bbox"]},
        "confidence": {"score": round(confidence, 4), "observations_count": len(observations)},
        "match": {"score": max(row["text_similarity"] for row in observations)},
        "localization_source": source,
        "localization_confidence": round(confidence, 4),
        "localization_evidence": {
            "first_visible_frame": observations[0]["frame"],
            "last_visible_frame": observations[-1]["frame"],
            "frames": observations,
        },
        "observations": observations,
    }


def easyocr_candidates(reader: Any, frame: np.ndarray) -> list[dict[str, Any]]:
    return [
        {
            "bbox": [float(min(point[0] for point in box)), float(min(point[1] for point in box)), float(max(point[0] for point in box)), float(max(point[1] for point in box))],
            "text": str(text),
            "confidence": float(confidence),
        }
        for box, text, confidence in reader.readtext(frame, detail=1, paragraph=False)
    ]


def paddleocr_candidates(predictor: Any, frame: np.ndarray) -> list[dict[str, Any]]:
    results = list(predictor.predict(frame))
    if not results:
        return []
    payload = results[0].json.get("res") or {}
    return [
        {"bbox": [float(part) for part in box], "text": str(text), "confidence": float(confidence)}
        for box, text, confidence in zip(payload.get("rec_boxes") or [], payload.get("rec_texts") or [], payload.get("rec_scores") or [])
    ]
