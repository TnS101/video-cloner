from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont


def source_visible_scoring_text(evidence: Mapping[str, object], events: Iterable[Mapping[str, object]]) -> dict[str, object]:
    """Resolve font-scoring text from source-visible bbox evidence, never transcript semantics."""
    explicit = evidence.get("font_scoring_text_authority")
    if isinstance(explicit, Mapping) and str(explicit.get("authority") or "").startswith("SOURCE_VISIBLE_PIXELS_"):
        return dict(explicit)
    observations = [row for row in evidence.get("observations", []) if row.get("accepted") and row.get("bbox")]
    if not observations:
        return {"text": None, "authority": "UNRESOLVED", "reason": "no_accepted_target_observations"}

    def iou(left: list[int], right: list[int]) -> float:
        width = max(0, min(left[2], right[2]) - max(left[0], right[0]))
        height = max(0, min(left[3], right[3]) - max(left[1], right[1]))
        intersection = width * height
        union = (left[2] - left[0]) * (left[3] - left[1]) + (right[2] - right[0]) * (right[3] - right[1]) - intersection
        return intersection / max(1, union)

    candidates = []
    target_time = float(np.median([row["timestamp"] for row in observations]))
    target_boxes = [row["bbox"] for row in observations]
    for event in events:
        text = str(event.get("observed_text") or "").strip()
        boxes = [row["bbox"] for row in event.get("observations", []) if row.get("bbox")]
        placement = event.get("placement") if isinstance(event.get("placement"), Mapping) else {}
        if not boxes and placement.get("bbox"):
            boxes = [placement["bbox"]]
        if not text or not boxes or not float(event.get("start", target_time)) <= target_time <= float(event.get("end", target_time)):
            continue
        overlap = max(iou(left, right) for left in target_boxes for right in boxes)
        if overlap >= 0.50:
            candidates.append((overlap, text.casefold(), str(event.get("event_id") or ""), text))
    candidates.sort(key=lambda row: (-row[0], row[1], row[2]))
    if not candidates:
        return {"text": None, "authority": "UNRESOLVED", "reason": "no_source_visible_text_bbox_match"}
    if len(candidates) > 1 and candidates[0][0] == candidates[1][0] and candidates[0][1] != candidates[1][1]:
        return {"text": None, "authority": "UNRESOLVED", "reason": "ambiguous_source_visible_text_bbox_match"}
    overlap, _, event_id, text = candidates[0]
    return {
        "text": text, "authority": "SOURCE_VISIBLE_OBSERVED_TEXT_BBOX_MATCH", "reason": None,
        "source_event_id": event_id, "bbox_iou": round(overlap, 6),
    }


def discover_installed_fonts(font_dirs: Iterable[str | Path] | None = None) -> list[dict[str, object]]:
    roots = [Path(path) for path in (font_dirs or [Path(r"C:\Windows\Fonts")])]
    fonts: dict[tuple[str, str], dict[str, object]] = {}
    for path in sorted(p for root in roots if root.is_dir() for p in root.iterdir() if p.suffix.lower() in {".ttf", ".otf"}):
        try:
            family, style = ImageFont.truetype(str(path), 32).getname()
        except OSError:
            continue
        if any(token in f"{family} {style}".casefold() for token in ("wingdings", "webdings", "symbol", "icons", "emoji", "marlett", "mdl2", "fluent")):
            continue
        key = (family.casefold(), style.casefold())
        fonts.setdefault(key, {
            "family": family,
            "style": style,
            "weight": _weight(style),
            "path": path,
            "renderer_compatible": True,
        })
    return sorted(fonts.values(), key=lambda row: (str(row["family"]).casefold(), str(row["style"]).casefold(), str(row["path"])))


def _weight(style: str) -> str:
    value = style.casefold().replace(" ", "")
    for token, label in (
        ("black", "Black"), ("heavy", "Black"), ("extrabold", "ExtraBold"),
        ("semibold", "SemiBold"), ("demibold", "SemiBold"), ("bold", "Bold"),
        ("medium", "Medium"), ("light", "Light"), ("thin", "Thin"),
    ):
        if token in value:
            return label
    return "Regular"


@lru_cache(maxsize=4096)
def render_text_mask(text: str, font_path: str | Path, size: int = 96) -> np.ndarray:
    font = ImageFont.truetype(str(font_path), size)
    canvas = Image.new("L", (max(256, size * max(2, len(text))), size * 3), 0)
    ImageDraw.Draw(canvas).text((size // 2, size // 2), text, font=font, fill=255)
    return _tight(np.asarray(canvas) > 24)


def source_text_mask(crop_bgr: np.ndarray, fill_hex: str, threshold: float = 92.0) -> tuple[np.ndarray, float]:
    if crop_bgr.size == 0:
        return np.zeros((1, 1), dtype=bool), 0.0
    fill = np.array([int(fill_hex[index:index + 2], 16) for index in (1, 3, 5)], dtype=np.float32)
    rgb = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB).astype(np.float32)
    distance = np.linalg.norm(rgb - fill, axis=2)
    mask = (distance <= threshold).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    minimum = max(2, round(mask.size * 0.0015))
    kept = np.zeros_like(mask)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= minimum:
            kept[labels == label] = 1
    tight = _tight(kept > 0)
    coverage = float(kept.mean())
    separation = float(np.clip((np.median(distance[kept == 0]) - np.median(distance[kept > 0])) / 128.0, 0.0, 1.0)) if kept.any() and (~kept.astype(bool)).any() else 0.0
    area_confidence = float(np.clip(coverage / 0.08, 0.0, 1.0) * np.clip((0.70 - coverage) / 0.35, 0.0, 1.0))
    return tight, round(area_confidence * separation, 4)


def measure_source_observation(
    crop_bgr: np.ndarray,
    fill_hex: str,
    *,
    frame: int,
    timestamp: float,
    bbox: list[int],
    overlap_risk: float = 0.0,
    transition_risk: float = 0.0,
    occlusion_mask: np.ndarray | None = None,
) -> dict[str, object]:
    """Measure one source frame without claiming it is clean glyph evidence."""
    mask, foreground_confidence = source_text_mask(crop_bgr, fill_hex, threshold=70.0)
    unknown_mask = np.zeros_like(mask, dtype=bool)
    if occlusion_mask is not None and np.asarray(occlusion_mask).any():
        unknown_mask = cv2.resize(
            np.asarray(occlusion_mask, dtype=np.uint8),
            (mask.shape[1], mask.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        ) > 0
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY) if crop_bgr.size else np.zeros((1, 1), np.uint8)
    blur_score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur_quality = float(np.clip(blur_score / 120.0, 0.0, 1.0))
    coverage = float(mask.mean()) if mask.size > 1 or mask.any() else 0.0
    contamination = float(np.clip(
        0.55 * overlap_risk
        + 0.25 * transition_risk
        + 0.20 * max(0.0, (coverage - 0.55) / 0.35),
        0.0,
        1.0,
    ))
    reasons = []
    if not mask.any() or foreground_confidence < 0.08:
        reasons.append("low_foreground_confidence")
    if blur_quality < 0.08:
        reasons.append("blurred")
    if coverage > 0.78:
        reasons.append("background_leakage")
    if overlap_risk > 0.82:
        reasons.append("overlap_risk")
    if transition_risk > 0.82:
        reasons.append("partial_entry_or_exit")
    return {
        "frame": int(frame),
        "timestamp": round(float(timestamp), 6),
        "bbox": [int(value) for value in bbox],
        "mask": mask,
        "unknown_mask": unknown_mask,
        "foreground_confidence": round(float(foreground_confidence), 6),
        "contamination_score": round(contamination, 6),
        "overlap_risk": round(float(overlap_risk), 6),
        "blur_score": round(blur_score, 6),
        "blur_quality": round(blur_quality, 6),
        "accepted": not reasons,
        "reason": "accepted" if not reasons else "+".join(reasons),
    }


def aggregate_source_masks(observations: Iterable[dict[str, object]]) -> dict[str, object]:
    """Deterministically combine stable glyph pixels using translation + uniform scale only."""
    ordered = sorted(
        observations,
        key=lambda row: (
            int(row.get("frame", 0)),
            float(row.get("timestamp", 0.0)),
            tuple(int(value) for value in row.get("bbox", [])),
        ),
    )
    accepted = [
        row for row in ordered
        if row.get("accepted", True)
        and float(row.get("foreground_confidence", 0.0)) >= 0.08
        and float(row.get("contamination_score", 0.0)) <= 0.72
        and float(row.get("blur_quality", 0.0)) >= 0.08
        and np.asarray(row.get("mask"), dtype=bool).any()
    ]
    if not accepted:
        return {
            "mask": np.zeros((1, 1), dtype=bool),
            "foreground_mask": np.zeros((1, 1), dtype=bool),
            "background_mask": np.zeros((1, 1), dtype=bool),
            "unknown_mask": np.ones((1, 1), dtype=bool),
            "candidate_frame_count": len(ordered),
            "usable_frame_count": 0,
            "accepted_frame_ratio": 0.0,
            "temporal_agreement": 0.0,
            "contour_stability": 0.0,
            "separation_score": 0.0,
            "confidence": 0.0,
            "artifact_penalty": 0.0,
            "unknown_ratio": 1.0,
            "status": "CONTAMINATED_EVIDENCE" if ordered else "INSUFFICIENT_EVIDENCE",
            "observations": ordered,
            "alignment": "bbox_translation_plus_uniform_height_scale",
            "non_uniform_scale_ratio": 1.0,
        }

    tight_masks = [_tight(np.asarray(row["mask"], dtype=bool)) for row in accepted]
    target_height = max(1, int(round(float(np.median([mask.shape[0] for mask in tight_masks])))))
    resized = []
    resized_unknown = []
    for row, mask in zip(accepted, tight_masks):
        scale = target_height / max(1, mask.shape[0])
        width = max(1, int(round(mask.shape[1] * scale)))
        resized.append(cv2.resize(mask.astype(np.uint8), (width, target_height), interpolation=cv2.INTER_NEAREST) > 0)
        unknown = np.asarray(row.get("unknown_mask", np.zeros_like(row["mask"])), dtype=bool)
        unknown = cv2.resize(unknown.astype(np.uint8), (width, target_height), interpolation=cv2.INTER_NEAREST) > 0
        resized_unknown.append(unknown)
    canvas_width = max(mask.shape[1] for mask in resized)
    canvases = []
    unknown_canvases = []
    for mask, unknown in zip(resized, resized_unknown):
        canvas = np.zeros((target_height, canvas_width), dtype=bool)
        unknown_canvas = np.zeros_like(canvas)
        left = (canvas_width - mask.shape[1]) // 2
        canvas[:, left:left + mask.shape[1]] = mask
        unknown_canvas[:, left:left + unknown.shape[1]] = unknown
        canvases.append(canvas)
        unknown_canvases.append(unknown_canvas)
    weights = np.array([
        max(0.01, float(row["foreground_confidence"]))
        * (1.0 - float(row["contamination_score"]))
        * (0.5 + 0.5 * float(row["blur_quality"]))
        for row in accepted
    ], dtype=np.float64)
    frequency = np.average(np.stack(canvases).astype(np.float64), axis=0, weights=weights)
    unknown_frequency = np.average(np.stack(unknown_canvases).astype(np.float64), axis=0, weights=weights)
    foreground = frequency >= (0.60 if len(canvases) > 1 else 0.01)
    unknown = ((frequency > 0.25) & ~foreground) | (unknown_frequency >= 0.65)
    foreground &= ~unknown
    artifact_mask, artifact_penalty = _residual_artifacts(foreground)
    foreground &= ~artifact_mask
    unknown |= artifact_mask
    occupied = foreground | unknown
    if occupied.any():
        rows, cols = np.where(occupied)
        bounds = (slice(rows.min(), rows.max() + 1), slice(cols.min(), cols.max() + 1))
        foreground, unknown = foreground[bounds], unknown[bounds]
    background = ~(foreground | unknown)
    aggregate = foreground
    agreements = [compare_masks(aggregate, mask)["iou"] for mask in resized]
    agreement = float(np.median(agreements))
    accepted_ratio = len(accepted) / max(1, len(ordered))
    separation = float(np.median([float(row["foreground_confidence"]) for row in accepted]))
    contamination = float(np.mean([float(row["contamination_score"]) for row in accepted]))
    frame_support = math.sqrt(min(1.0, len(accepted) / 3.0))
    unknown_ratio = float(unknown.mean())
    confidence = float(np.clip(
        frame_support * (0.30 * accepted_ratio + 0.35 * agreement + 0.35 * separation)
        * (1.0 - contamination) * (1.0 - 0.55 * unknown_ratio) * (1.0 - artifact_penalty),
        0.0,
        1.0,
    ))
    if unknown_ratio > 0.75 or artifact_penalty > 0.30:
        status = "CONTAMINATED_EVIDENCE"
    elif len(accepted) >= 2 and confidence >= 0.28:
        status = "CLEAN_MULTI_FRAME_EVIDENCE"
    elif len(accepted) == 1 and confidence >= 0.25:
        status = "CLEAN_SINGLE_FRAME_EVIDENCE"
    else:
        status = "PARTIAL_EVIDENCE"
    return {
        "mask": aggregate,
        "foreground_mask": foreground,
        "background_mask": background,
        "unknown_mask": unknown,
        "candidate_frame_count": len(ordered),
        "usable_frame_count": len(accepted),
        "accepted_frame_ratio": round(accepted_ratio, 6),
        "temporal_agreement": round(agreement, 6),
        "contour_stability": round(agreement, 6),
        "separation_score": round(separation, 6),
        "mean_overlap_risk": round(float(np.mean([float(row["overlap_risk"]) for row in accepted])), 6),
        "confidence": round(confidence, 6),
        "artifact_penalty": round(artifact_penalty, 6),
        "unknown_ratio": round(unknown_ratio, 6),
        "status": status,
        "observations": ordered,
        "alignment": "bbox_translation_plus_uniform_height_scale",
        "non_uniform_scale_ratio": 1.0,
    }


def compare_known_regions(
    foreground: np.ndarray,
    background: np.ndarray,
    unknown: np.ndarray,
    candidate: np.ndarray,
) -> dict[str, float | int]:
    """Compare a candidate only where source evidence is authoritative."""
    foreground = np.asarray(foreground, dtype=bool)
    background = np.asarray(background, dtype=bool)
    unknown = np.asarray(unknown, dtype=bool)
    if foreground.shape != background.shape or foreground.shape != unknown.shape:
        raise ValueError("tri-state evidence masks must have the same shape")
    candidate = np.asarray(candidate, dtype=bool)
    scale = foreground.shape[0] / max(1, candidate.shape[0])
    width = max(1, round(candidate.shape[1] * scale))
    resized = cv2.resize(candidate.astype(np.uint8), (width, foreground.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    canvas = np.zeros_like(foreground)
    left = (foreground.shape[1] - width) // 2
    source_left, candidate_left = max(0, left), max(0, -left)
    span = min(foreground.shape[1] - source_left, width - candidate_left)
    if span > 0:
        canvas[:, source_left:source_left + span] = resized[:, candidate_left:candidate_left + span]
    known = (foreground | background) & ~unknown
    mismatches = (foreground & ~canvas) | (background & canvas)
    foreground_mismatch_count = int((foreground & ~canvas & known).sum())
    background_mismatch_count = int((background & canvas & known).sum())
    mismatch_count = foreground_mismatch_count + background_mismatch_count
    known_count = int(known.sum())
    foreground_count = int((foreground & known).sum())
    background_count = int((background & known).sum())
    foreground_accuracy = 1.0 - foreground_mismatch_count / max(1, foreground_count)
    background_accuracy = 1.0 - background_mismatch_count / max(1, background_count)
    return {
        "known_pixel_count": known_count,
        "unknown_pixel_count": int(unknown.sum()),
        "mismatch_count": mismatch_count,
        "foreground_mismatch_count": foreground_mismatch_count,
        "background_mismatch_count": background_mismatch_count,
        "foreground_accuracy": round(foreground_accuracy, 6),
        "background_accuracy": round(background_accuracy, 6),
        "score": round(0.70 * foreground_accuracy + 0.30 * background_accuracy, 6),
    }


def known_region_evidence_gate(
    foreground: np.ndarray,
    background: np.ndarray,
    unknown: np.ndarray,
    *,
    usable_frame_count: int,
) -> tuple[bool, str | None]:
    foreground = np.asarray(foreground, dtype=bool)
    background = np.asarray(background, dtype=bool)
    unknown = np.asarray(unknown, dtype=bool)
    if foreground.shape != background.shape or foreground.shape != unknown.shape:
        return False, "tri_state_shape_mismatch"
    if usable_frame_count <= 0:
        return False, "zero_usable_observations"
    foreground_count = int(foreground.sum())
    if foreground_count < 24:
        return False, "insufficient_known_foreground_pixels"
    rows, columns = np.where(foreground)
    if len(set(rows)) < 4 or len(set(columns)) < 4:
        return False, "insufficient_discriminative_glyph_structure"
    known_count = int((foreground | background).sum())
    if known_count < 64:
        return False, "insufficient_known_region"
    if float(unknown.mean()) > 0.90:
        return False, "unknown_region_dominates"
    return True, None


def rank_font_candidates_known_regions(
    text: str,
    foreground: np.ndarray,
    background: np.ndarray,
    unknown: np.ndarray,
    fonts: list[dict[str, object]],
    limit: int = 5,
) -> tuple[list[dict[str, object]], int]:
    """Rank installed fonts only against authoritative source pixels."""
    foreground = np.asarray(foreground, dtype=bool)
    tight_foreground = _tight(foreground)
    source_aspect = tight_foreground.shape[1] / max(1, tight_foreground.shape[0])
    coarse_height = min(32, foreground.shape[0])
    coarse_width = max(1, round(foreground.shape[1] * coarse_height / max(1, foreground.shape[0])))
    coarse_size = (coarse_width, coarse_height)
    coarse_evidence = tuple(
        cv2.resize(mask.astype(np.uint8), coarse_size, interpolation=cv2.INTER_NEAREST) > 0
        for mask in (foreground, np.asarray(background, dtype=bool), np.asarray(unknown, dtype=bool))
    )
    rendered = []
    for font in fonts:
        if not font_supports_text(font["path"], text):
            continue
        try:
            mask = render_text_mask(text, font["path"])
        except OSError:
            continue
        aspect = mask.shape[1] / max(1, mask.shape[0])
        coarse_score = float(compare_known_regions(*coarse_evidence, mask)["score"])
        rendered.append((-coarse_score, abs(math.log(max(aspect, 1e-6) / max(source_aspect, 1e-6))), str(font["family"]).casefold(), str(font["style"]).casefold(), font, mask))
    compared = sorted(rendered, key=lambda row: row[:4])[:min(max(16, limit), len(rendered))]
    ranking = []
    for _, _, _, _, font, mask in compared:
        metrics = compare_known_regions(foreground, background, unknown, mask)
        ranking.append({
            "family": font["family"], "style": font["style"], "weight": font["weight"],
            "renderer_compatible": font["renderer_compatible"], **metrics,
        })
    ranking.sort(key=lambda row: (-float(row["score"]), str(row["family"]).casefold(), str(row["style"]).casefold()))
    return ranking[:limit], len(compared)


def known_region_ranking_authority(
    ranking: list[dict[str, object]],
    *,
    evidence_gate_passed: bool,
    evidence_gate_reason: str | None,
    evidence_classification: str,
    unknown_ratio: float,
) -> tuple[str, str | None]:
    if not evidence_gate_passed:
        return "NO_AUTHORITATIVE_FONT_RANKING", evidence_gate_reason
    if len(ranking) < 2:
        return "NO_AUTHORITATIVE_FONT_RANKING", "insufficient_font_candidates"
    top_score = float(ranking[0]["score"])
    margin = top_score - float(ranking[1]["score"])
    if evidence_classification == "CONTAMINATED_EVIDENCE" and (unknown_ratio > 0.50 or margin < 0.02):
        return "NO_AUTHORITATIVE_FONT_RANKING", "contaminated_region_not_discriminative"
    if top_score >= 0.55 and margin >= 0.01:
        return "AUTHORITATIVE_FONT_RANKING", None
    return "PROVISIONAL_FONT_RANKING", "candidate_scores_not_decisive"


def _residual_artifacts(mask: np.ndarray) -> tuple[np.ndarray, float]:
    mask = np.asarray(mask, dtype=bool)
    artifact = np.zeros_like(mask)
    if not mask.any():
        return artifact, 0.0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    minimum = max(2, round(mask.size * 0.0015))
    for label in range(1, count):
        x, y, width, height, area = stats[label]
        suspicious_strip = width >= 0.35 * mask.shape[1] and height <= max(2, 0.08 * mask.shape[0])
        if area < minimum or suspicious_strip:
            artifact[labels == label] = True
    penalty = min(0.75, float(artifact.sum()) / max(1, int(mask.sum())) * 2.5)
    return artifact, penalty


def compare_masks(source: np.ndarray, candidate: np.ndarray) -> dict[str, float]:
    source = _tight(source)
    candidate = _tight(candidate)
    scale = source.shape[0] / max(1, candidate.shape[0])
    width = max(1, round(candidate.shape[1] * scale))
    resized = cv2.resize(candidate.astype(np.uint8), (width, source.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    canvas_width = max(source.shape[1], resized.shape[1])
    left_source = (canvas_width - source.shape[1]) // 2
    left_candidate = (canvas_width - resized.shape[1]) // 2
    source_canvas = np.zeros((source.shape[0], canvas_width), dtype=bool)
    candidate_canvas = np.zeros_like(source_canvas)
    source_canvas[:, left_source:left_source + source.shape[1]] = source
    candidate_canvas[:, left_candidate:left_candidate + resized.shape[1]] = resized
    intersection = np.logical_and(source_canvas, candidate_canvas).sum()
    union = np.logical_or(source_canvas, candidate_canvas).sum()
    iou = float(intersection / max(1, union))
    source_aspect = source.shape[1] / max(1, source.shape[0])
    candidate_aspect = candidate.shape[1] / max(1, candidate.shape[0])
    aspect_error = abs(math.log(max(candidate_aspect, 1e-6) / max(source_aspect, 1e-6)))
    width_error = abs(resized.shape[1] - source.shape[1]) / max(1, source.shape[1])
    density_error = abs(float(source.mean()) - float(candidate.mean()))
    distance_to_candidate = cv2.distanceTransform((~candidate_canvas).astype(np.uint8), cv2.DIST_L2, 3)
    distance_to_source = cv2.distanceTransform((~source_canvas).astype(np.uint8), cv2.DIST_L2, 3)
    contour_distance = (
        float(distance_to_candidate[source_canvas].mean()) if source_canvas.any() else canvas_width
    ) + (
        float(distance_to_source[candidate_canvas].mean()) if candidate_canvas.any() else canvas_width
    )
    contour_similarity = math.exp(-3.0 * contour_distance / max(1.0, math.hypot(*source_canvas.shape)))
    score = (
        0.45 * iou
        + 0.20 * contour_similarity
        + 0.20 * math.exp(-aspect_error)
        + 0.10 * math.exp(-4.0 * density_error)
        + 0.05 * max(0.0, 1.0 - width_error)
    )
    return {
        "score": round(score, 6),
        "iou": round(iou, 6),
        "contour_similarity": round(contour_similarity, 6),
        "width_error": round(width_error, 6),
        "aspect_ratio_error": round(aspect_error, 6),
        "density_error": round(density_error, 6),
        "uniform_scale": round(scale, 6),
        "non_uniform_scale_ratio": 1.0,
        "source_aspect_ratio": round(source_aspect, 6),
        "candidate_aspect_ratio": round(candidate_aspect, 6),
        "final_width": int(resized.shape[1]),
        "final_height": int(resized.shape[0]),
        "natural_width": int(candidate.shape[1]),
        "natural_height": int(candidate.shape[0]),
    }


def rank_font_candidates(text: str, source_mask: np.ndarray, fonts: list[dict[str, object]], limit: int = 5) -> list[dict[str, object]]:
    rendered = []
    source_aspect = source_mask.shape[1] / max(1, source_mask.shape[0])
    source_density = float(source_mask.mean())
    for font in fonts:
        if not font_supports_text(font["path"], text):
            continue
        try:
            mask = render_text_mask(text, font["path"])
        except OSError:
            continue
        aspect = mask.shape[1] / max(1, mask.shape[0])
        coarse = abs(math.log(max(aspect, 1e-6) / max(source_aspect, 1e-6))) + abs(float(mask.mean()) - source_density)
        rendered.append((coarse, str(font["family"]).casefold(), str(font["style"]).casefold(), font, mask))
    top = sorted(rendered, key=lambda row: row[:3])[:min(28, len(rendered))]
    ranked = []
    for _, _, _, font, mask in top:
        metrics = compare_masks(source_mask, mask)
        ranked.append({
            "family": font["family"], "style": font["style"], "weight": font["weight"],
            "renderer_compatible": font["renderer_compatible"], "_path": font["path"], **metrics,
        })
    return sorted(ranked, key=lambda row: (-float(row["score"]), str(row["family"]).casefold(), str(row["style"]).casefold()))[:limit]


def font_supports_text(font_path: str | Path, text: str) -> bool:
    codepoints = _font_codepoints(str(font_path))
    return bool(codepoints) and all(character.isspace() or ord(character) in codepoints for character in text)


@lru_cache(maxsize=None)
def _font_codepoints(font_path: str) -> frozenset[int]:
    try:
        font = TTFont(font_path, lazy=True)
        codepoints = {codepoint for table in font["cmap"].tables for codepoint in table.cmap}
        font.close()
    except Exception:
        return frozenset()
    return frozenset(codepoints)


def authority_classification(ranking: list[dict[str, object]], mask_confidence: float) -> tuple[str, str]:
    if not ranking or mask_confidence < 0.12:
        return "UNRESOLVED_FONT_STYLE", "LOW"
    score = float(ranking[0]["score"])
    margin = score - float(ranking[1]["score"]) if len(ranking) > 1 else score
    if mask_confidence >= 0.55 and score >= 0.64 and margin >= 0.025:
        return "BEST_AVAILABLE_FONT_MATCH_HIGH", "HIGH"
    if mask_confidence >= 0.45 and score >= 0.62 and margin >= 0.015:
        return "BEST_AVAILABLE_FONT_MATCH_MEDIUM", "MEDIUM"
    if mask_confidence >= 0.25 and score >= 0.56:
        return "BEST_AVAILABLE_FONT_MATCH_LOW", "LOW"
    return "UNRESOLVED_FONT_STYLE", "LOW"


def _tight(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask, dtype=bool)
    rows, cols = np.where(mask)
    if not len(rows):
        return np.zeros((1, 1), dtype=bool)
    return mask[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
