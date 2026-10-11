"""Expected-text matching for optional OSS caption-localization fallbacks."""
from __future__ import annotations

import re
from hashlib import sha1
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


def phrase_lattice(captions: list[dict[str, Any]], ordinal: int, radius: int = 3) -> list[dict[str, Any]]:
    by_ordinal = {int(row["ordinal"]): row for row in captions}
    if ordinal not in by_ordinal:
        raise ValueError(f"caption_ordinal:{ordinal}")
    lowest, highest = max(min(by_ordinal), ordinal - radius), min(max(by_ordinal), ordinal + radius)
    spans = {(ordinal, ordinal), (ordinal - 1, ordinal), (ordinal, ordinal + 1), (ordinal - 1, ordinal + 1)}
    for length in range(2, 5):
        for start in range(max(lowest, ordinal - length + 1), min(ordinal, highest - length + 1) + 1):
            spans.add((start, start + length - 1))
    rows = []
    for start, end in sorted(spans):
        ordinals = list(range(max(lowest, start), min(highest, end) + 1))
        if ordinal not in ordinals or any(value not in by_ordinal for value in ordinals):
            continue
        tokens = [str(by_ordinal[value]["text"]) for value in ordinals]
        rows.append({"ordinals": ordinals, "tokens": tokens, "text": " ".join(tokens)})
    return rows


def _proximity(left: object, right: object, frame_size: tuple[int, int]) -> float:
    height, width = frame_size
    ax1, ay1, ax2, ay2 = _rect(left)
    bx1, by1, bx2, by2 = _rect(right)
    distance = np.hypot(((ax1 + ax2) - (bx1 + bx2)) / (2.0 * width), ((ay1 + ay2) - (by1 + by2)) / (2.0 * height))
    return max(_iou(left, right), max(0.0, 1.0 - float(distance) * 2.2))


def _candidate_clusters(candidates: list[dict[str, Any]], frame_size: tuple[int, int]) -> list[dict[str, Any]]:
    height, width = frame_size
    usable = []
    for candidate in candidates:
        try:
            bbox = _rect(candidate.get("bbox"))
        except ValueError:
            continue
        x1, y1, x2, y2 = bbox
        if _normalized(candidate.get("text")) and (x2 - x1) * (y2 - y1) <= width * height * 0.2 and y2 - y1 <= height * 0.25:
            usable.append({**candidate, "bbox": list(bbox)})
    groups: list[list[dict[str, Any]]] = []
    for candidate in usable:
        x1, y1, x2, y2 = candidate["bbox"]
        for group in groups:
            gx1 = min(row["bbox"][0] for row in group)
            gy1 = min(row["bbox"][1] for row in group)
            gx2 = max(row["bbox"][2] for row in group)
            gy2 = max(row["bbox"][3] for row in group)
            horizontal_gap = max(0.0, max(gx1, x1) - min(gx2, x2))
            vertical_gap = max(0.0, max(gy1, y1) - min(gy2, y2))
            if horizontal_gap <= width * 0.08 and vertical_gap <= height * 0.055:
                group.append(candidate)
                break
        else:
            groups.append([candidate])
    rows = []
    for group in groups:
        ordered = sorted(group, key=lambda row: ((row["bbox"][1] + row["bbox"][3]) / 2.0, row["bbox"][0]))
        rows.append(
            {
                "bbox": [
                    min(row["bbox"][0] for row in group), min(row["bbox"][1] for row in group),
                    max(row["bbox"][2] for row in group), max(row["bbox"][3] for row in group),
                ],
                "text": " ".join(str(row["text"]) for row in ordered),
                "confidence": float(np.mean([float(row.get("confidence") or 0.0) for row in group])),
                "layout_regions": [row["bbox"] for row in ordered],
            }
        )
    return rows


def _association_candidate(
    candidate: dict[str, Any],
    lattice: list[dict[str, Any]],
    frame_size: tuple[int, int],
    prior_boxes: list[list[object]],
) -> dict[str, Any]:
    detected = _normalized(candidate["text"])
    text_score = max((text_similarity(row["text"], detected) for row in lattice), default=0.0)
    nearby_tokens = {
        _normalized(token)
        for row in lattice
        for token in row["tokens"]
        if _normalized(token)
    }
    matched_tokens = sorted(token for token in nearby_tokens if token in detected or text_similarity(token, detected) >= 0.72)
    neighbor_score = min(1.0, len(matched_tokens) / 2.0)
    style_score = max((_proximity(candidate["bbox"], bbox, frame_size) for bbox in prior_boxes), default=0.0)
    height, width = frame_size
    x1, y1, x2, y2 = _rect(candidate["bbox"])
    center_x, center_y = (x1 + x2) / (2.0 * width), (y1 + y2) / (2.0 * height)
    geometry_score = max(0.0, 1.0 - abs(center_x - 0.5) * 1.2 - abs(center_y - 0.5) * 0.55)
    local_score = 0.35 * text_score + 0.15 * neighbor_score + 0.25 * style_score + 0.15 * geometry_score + 0.10 * float(candidate["confidence"])
    return {
        **candidate,
        "text_score": round(text_score, 4),
        "neighbor_score": round(neighbor_score, 4),
        "style_score": round(style_score, 4),
        "geometry_score": round(geometry_score, 4),
        "matched_tokens": matched_tokens,
        "local_score": round(local_score, 4),
    }


def associate_caption(
    captions: list[dict[str, Any]],
    caption: dict[str, Any],
    fps: float,
    frame_size: tuple[int, int],
    detections: dict[int, list[dict[str, Any]]],
    source: str,
    priors: list[dict[str, Any]],
) -> dict[str, Any]:
    ordinal = int(caption["ordinal"])
    lattice = phrase_lattice(captions, ordinal)
    prior_boxes = [row["bbox"] for row in priors if isinstance(row.get("bbox"), list) and len(row["bbox"]) == 4]
    observations = []
    ambiguous_frames = []
    for frame in anchor_frames(caption):
        ranked = sorted(
            (_association_candidate(row, lattice, frame_size, prior_boxes) for row in _candidate_clusters(detections.get(frame) or [], frame_size)),
            key=lambda row: row["local_score"],
            reverse=True,
        )
        if not ranked:
            continue
        best = ranked[0]
        if len(ranked) > 1 and best["local_score"] - ranked[1]["local_score"] < 0.045 and _proximity(best["bbox"], ranked[1]["bbox"], frame_size) < 0.35:
            ambiguous_frames.append(frame)
            continue
        observations.append({"frame": frame, "timestamp": frame / fps, **best})
    if not observations:
        raise ValueError(f"association_missing:{ordinal}")
    anchor = max(
        observations,
        key=lambda row: (
            sum(
                text_similarity(row["text"], other["text"]) >= 0.45 or _proximity(row["bbox"], other["bbox"], frame_size) >= 0.75
                for other in observations
            ),
            row["local_score"],
        ),
    )
    observations = [
        row for row in observations
        if text_similarity(anchor["text"], row["text"]) >= 0.45 or _proximity(anchor["bbox"], row["bbox"], frame_size) >= 0.75
    ]
    persistence = len(observations) / len(anchor_frames(caption))
    continuity = float(np.mean([_proximity(left["bbox"], right["bbox"], frame_size) for left, right in zip(observations, observations[1:])])) if len(observations) > 1 else 0.0
    text_score = max(row["text_score"] for row in observations)
    neighbor_score = max(row["neighbor_score"] for row in observations)
    style_score = float(np.mean([row["style_score"] for row in observations]))
    timing_score = 1.0 if prior_boxes else 0.5
    score = 0.20 * text_score + 0.10 * neighbor_score + 0.20 * timing_score + 0.20 * continuity + 0.20 * style_score + 0.10 * persistence
    if score < 0.62 or (text_score < 0.2 and (persistence < 2 / 3 or continuity < 0.55 or style_score < 0.35)):
        raise ValueError(f"association_confidence:{ordinal}:{score:.4f}")
    detected_phrase = max(observations, key=lambda row: (row["confidence"], len(_normalized(row["text"]))))["text"]
    matched = sorted({_normalized(token) for row in observations for token in row["matched_tokens"]})
    token_ordinals = sorted(
        {
            value
            for row in lattice
            for value, token in zip(row["ordinals"], row["tokens"])
            if _normalized(token) in matched
        }
        | {ordinal}
    )
    identity = sha1(f"{source}|{_normalized(detected_phrase)}|{round(np.mean([row['bbox'][1] for row in observations]) / frame_size[0], 1)}".encode()).hexdigest()[:12]
    evidence_rows = [
        {
            "frame": row["frame"], "timestamp": round(row["timestamp"], 6), "bbox": [round(float(part), 3) for part in row["bbox"]],
            "layout_regions": row["layout_regions"], "detected_text": row["text"], "visibility_confidence": round(float(row["local_score"]), 4),
        }
        for row in observations
    ]
    return {
        "event_id": f"cross_authority:{source}:{caption['caption_id']}",
        "cue_id": caption["caption_id"],
        "role": "spoken_caption",
        "start": int(caption["start_frame"]) / fps,
        "end": (int(caption["start_frame"]) + int(caption["duration"])) / fps,
        "placement": {"bbox": evidence_rows[-1]["bbox"]},
        "confidence": {"score": round(score, 4), "observations_count": len(evidence_rows)},
        "match": {"score": round(max(text_score, neighbor_score), 4)},
        "localization_source": source,
        "localization_confidence": round(score, 4),
        "composition_id": f"composition_{identity}",
        "source_caption_ordinals": token_ordinals,
        "expected_tokens": [str(next(row["text"] for row in captions if int(row["ordinal"]) == value)) for value in token_ordinals],
        "detected_phrase": detected_phrase,
        "ambiguous_frames": ambiguous_frames,
        "localization_evidence": {
            "first_visible_frame": evidence_rows[0]["frame"], "last_visible_frame": evidence_rows[-1]["frame"],
            "tokens_simultaneously_visible": matched, "frames": evidence_rows,
        },
        "observations": [
            {"frame": row["frame"], "timestamp": row["timestamp"], "bbox": row["bbox"], "observation_provenance": f"accepted_cross_authority_{source}"}
            for row in evidence_rows
        ],
    }


def lifecycle_proposals(events: list[dict[str, Any]], frame_size: tuple[int, int]) -> list[dict[str, Any]]:
    """Group nearby associated tokens into bounded visual compositions."""
    ordered = sorted(events, key=lambda row: (int(row["source_caption_ordinals"][0]), int(row["localization_evidence"]["first_visible_frame"])))
    groups: list[list[dict[str, Any]]] = []
    for event in ordered:
        first = int(event["localization_evidence"]["first_visible_frame"])
        bbox = event["localization_evidence"]["frames"][0]["bbox"]
        for group in reversed(groups[-2:]):
            prior = group[-1]
            prior_last = int(prior["localization_evidence"]["last_visible_frame"])
            prior_bbox = prior["localization_evidence"]["frames"][-1]["bbox"]
            ordinal_gap = min(event["source_caption_ordinals"]) - max(prior["source_caption_ordinals"])
            shared_tokens = bool(set(event["source_caption_ordinals"]) & set(prior["source_caption_ordinals"]))
            same_phrase = text_similarity(event["detected_phrase"], prior["detected_phrase"]) >= 0.45
            if 0 <= ordinal_gap <= 3 and first - prior_last <= 12 and _proximity(bbox, prior_bbox, frame_size) >= 0.62 and (shared_tokens or same_phrase):
                group.append(event)
                break
        else:
            groups.append([event])

    proposals = []
    for index, group in enumerate(groups, 1):
        ordinals = sorted({int(value) for event in group for value in event["source_caption_ordinals"]})
        frames = [row for event in group for row in event["localization_evidence"]["frames"]]
        first, last = min(int(row["frame"]) for row in frames), max(int(row["frame"]) for row in frames)
        proposals.append(
            {
                "composition_id": f"lifecycle_{index:03d}",
                "token_ordinals": ordinals,
                "visible_start": first,
                "visible_end": last,
                "token_visibility": {
                    str(ordinal): {
                        "appears": min(int(event["localization_evidence"]["first_visible_frame"]) for event in group if ordinal in event["source_caption_ordinals"]),
                        "remains_visible_until": max(int(event["localization_evidence"]["last_visible_frame"]) for event in group if ordinal in event["source_caption_ordinals"]),
                        "joins_previous_composition": ordinal != ordinals[0],
                        "next_word_joins": ordinal != ordinals[-1],
                        "disappears": max(int(event["localization_evidence"]["last_visible_frame"]) for event in group if ordinal in event["source_caption_ordinals"]),
                    }
                    for ordinal in ordinals
                },
                "layout_regions": [row["layout_regions"] for row in sorted(frames, key=lambda row: int(row["frame"]))],
                "association_provenance": sorted({str(event["localization_source"]) for event in group}),
                "association_confidence": round(float(np.mean([event["localization_confidence"] for event in group])), 4),
            }
        )
    return proposals
