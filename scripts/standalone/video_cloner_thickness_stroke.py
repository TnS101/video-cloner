from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np


WEIGHTS = ("LIGHT", "REGULAR", "SEMIBOLD", "BOLD", "BLACK")


def project_bbox_to_crop(
    crop_bbox: Iterable[int],
    foreign_bbox: Iterable[int],
    crop_shape: tuple[int, int],
) -> np.ndarray:
    """Project a source-space bbox into the target crop without inventing pixels."""
    x1, y1, x2, y2 = (int(value) for value in crop_bbox)
    fx1, fy1, fx2, fy2 = (int(value) for value in foreign_bbox)
    mask = np.zeros(crop_shape, dtype=bool)
    left, top = max(x1, fx1), max(y1, fy1)
    right, bottom = min(x2, fx2), min(y2, fy2)
    if right > left and bottom > top:
        mask[top - y1:bottom - y1, left - x1:right - x1] = True
    return mask


def build_crop_ownership(
    target_fill: np.ndarray,
    foreign_identity_masks: Iterable[np.ndarray] = (),
    ambiguous_or_occluded_masks: Iterable[np.ndarray] = (),
) -> dict[str, np.ndarray]:
    """Return mutually exclusive crop-space ownership classes, failing closed."""
    target_fill = np.asarray(target_fill, dtype=bool)
    foreign = np.zeros_like(target_fill)
    unknown = np.zeros_like(target_fill)
    for mask in foreign_identity_masks:
        value = np.asarray(mask, dtype=bool)
        if value.shape != target_fill.shape:
            raise ValueError("foreign identity mask shape does not match target crop")
        foreign |= value
    for mask in ambiguous_or_occluded_masks:
        value = np.asarray(mask, dtype=bool)
        if value.shape != target_fill.shape:
            raise ValueError("unknown/occluded mask shape does not match target crop")
        unknown |= value
    unknown &= ~foreign
    target = target_fill & ~foreign & ~unknown
    usable_background = ~(target | foreign | unknown)
    return {
        "TARGET_OWNED": target,
        "FOREIGN_IDENTITY": foreign,
        "UNKNOWN_OR_OCCLUDED": unknown,
        "USABLE_BACKGROUND": usable_background,
    }


def segment_fill_core(crop_bgr: np.ndarray, fill_hex: str, threshold: float = 70.0) -> np.ndarray:
    """Return a crop-aligned fill mask; unlike the frozen glyph helper this is not tightened."""
    value = fill_hex.strip().lstrip("#")
    if crop_bgr.size == 0 or len(value) != 6:
        return np.zeros(crop_bgr.shape[:2] or (1, 1), dtype=bool)
    bgr = np.array([int(value[4:6], 16), int(value[2:4], 16), int(value[0:2], 16)], np.float32)
    distance = np.linalg.norm(crop_bgr.astype(np.float32) - bgr, axis=2)
    mask = cv2.morphologyEx((distance <= threshold).astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    kept = np.zeros_like(mask)
    minimum = max(2, round(mask.size * 0.0015))
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] >= minimum:
            kept[labels == label] = 1
    return kept.astype(bool)


def measure_glyph_thickness(mask: np.ndarray) -> dict[str, float | int] | None:
    mask = np.asarray(mask, dtype=bool)
    if int(mask.sum()) < 24:
        return None
    rows, columns = np.where(mask)
    mask = mask[rows.min():rows.max() + 1, columns.min():columns.max() + 1]
    distance = cv2.distanceTransform(np.pad(mask, 1).astype(np.uint8), cv2.DIST_L2, 5)[1:-1, 1:-1]
    peaks = mask & (distance >= cv2.dilate(distance, np.ones((3, 3), np.uint8)) - 1e-6) & (distance >= 1.0)
    values = 2.0 * distance[peaks]
    if len(values) < 3:
        return None
    return {
        "median_px": round(float(np.median(values)), 6),
        "p25_px": round(float(np.percentile(values, 25)), 6),
        "p75_px": round(float(np.percentile(values, 75)), 6),
        "normalized_to_glyph_height": round(float(np.median(values)) / max(1, mask.shape[0]), 6),
        "glyph_height_px": int(mask.shape[0]),
        "medial_sample_count": int(len(values)),
    }


def _weight_category(value: str) -> str:
    normalized = value.casefold().replace(" ", "")
    if "black" in normalized or "heavy" in normalized:
        return "BLACK"
    if "bold" in normalized:
        return "BOLD"
    if "semibold" in normalized or "demibold" in normalized:
        return "SEMIBOLD"
    if "light" in normalized or "thin" in normalized:
        return "LIGHT"
    return "REGULAR"


def infer_thickness(
    source_mask: np.ndarray,
    candidate_mask: np.ndarray,
    metadata_weight: str,
    *,
    font_authority: str,
    evidence_classification: str,
    mask_confidence: float,
) -> dict[str, object]:
    source = measure_glyph_thickness(source_mask)
    candidate = measure_glyph_thickness(candidate_mask)
    intrinsic = _weight_category(metadata_weight)
    intrinsic_authority = (
        "AUTHORITATIVE_FONT_WEIGHT" if font_authority == "AUTHORITATIVE_FONT_RANKING"
        else "PROVISIONAL_FONT_WEIGHT" if font_authority == "PROVISIONAL_FONT_RANKING"
        else "NO_AUTHORITATIVE_FONT_WEIGHT"
    )
    if source is None or candidate is None:
        return {
            "status": "NO_AUTHORITATIVE_THICKNESS_INFERENCE",
            "reason": "insufficient_glyph_structure",
            "intrinsic_weight_category": intrinsic if intrinsic_authority != "NO_AUTHORITATIVE_FONT_WEIGHT" else None,
            "intrinsic_weight_authority": intrinsic_authority,
            "observed_visual_weight_category": None,
        }
    candidate_at_source = float(candidate["median_px"]) * float(source["glyph_height_px"]) / max(1, int(candidate["glyph_height_px"]))
    ratio = float(source["median_px"]) / max(1e-6, candidate_at_source)
    index = WEIGHTS.index(intrinsic)
    shift = -2 if ratio < 0.72 else -1 if ratio < 0.88 else 2 if ratio > 1.35 else 1 if ratio > 1.12 else 0
    observed = WEIGHTS[max(0, min(len(WEIGHTS) - 1, index + shift))]
    source_spread = (float(source["p75_px"]) - float(source["p25_px"])) / max(1e-6, float(source["median_px"]))
    stable_measurement = (
        source_spread <= 0.75
        and 0.04 <= float(source["normalized_to_glyph_height"]) <= 0.45
        and 0.25 <= ratio <= 2.0
    )
    source_status = (
        "AUTHORITATIVE_THICKNESS_INFERENCE"
        if evidence_classification == "CLEAN_MULTI_FRAME_EVIDENCE" and mask_confidence >= 0.40 and stable_measurement
        else "PROVISIONAL_THICKNESS_INFERENCE"
    )
    if not stable_measurement and (ratio < 0.25 or ratio > 2.0):
        observed = None
    if intrinsic_authority == "NO_AUTHORITATIVE_FONT_WEIGHT":
        observed = None
        source_status = "PROVISIONAL_THICKNESS_INFERENCE"
    elif intrinsic_authority != "AUTHORITATIVE_FONT_WEIGHT" and source_status == "AUTHORITATIVE_THICKNESS_INFERENCE":
        source_status = "PROVISIONAL_THICKNESS_INFERENCE"
    return {
        "status": source_status,
        "reason": None if source_status == "AUTHORITATIVE_THICKNESS_INFERENCE" else "font_source_or_measurement_is_not_authoritative",
        "source": source,
        "candidate": candidate,
        "candidate_median_at_source_height_px": round(candidate_at_source, 6),
        "source_to_candidate_thickness_ratio": round(ratio, 6),
        "source_thickness_spread_ratio": round(source_spread, 6),
        "intrinsic_weight_category": intrinsic if intrinsic_authority != "NO_AUTHORITATIVE_FONT_WEIGHT" else None,
        "intrinsic_weight_authority": intrinsic_authority,
        "observed_visual_weight_category": observed,
    }


def detect_outline_observation(
    crop_bgr: np.ndarray,
    fill_mask: np.ndarray,
    unknown_mask: np.ndarray | None = None,
) -> dict[str, object]:
    fill_mask = np.asarray(fill_mask, dtype=bool)
    unknown = np.zeros_like(fill_mask) if unknown_mask is None else np.asarray(unknown_mask, dtype=bool)
    if crop_bgr.shape[:2] != fill_mask.shape or unknown.shape != fill_mask.shape or int(fill_mask.sum()) < 24:
        return {"status": "UNRESOLVED_EDGE_EVIDENCE", "present": None, "reason": "insufficient_or_misaligned_fill_core"}
    rows, columns = np.where(fill_mask)
    glyph_height = int(rows.max() - rows.min() + 1)
    maximum = max(4, min(12, round(glyph_height * 0.12)))
    distance = cv2.distanceTransform((~fill_mask).astype(np.uint8), cv2.DIST_L2, 5)
    near = (distance > 0.2) & (distance <= maximum) & ~unknown
    pixels = crop_bgr[near]
    if len(pixels) < 24:
        return {"status": "UNRESOLVED_EDGE_EVIDENCE", "present": None, "reason": "insufficient_known_edge_pixels"}
    quantized = (pixels // 24).astype(np.int16)
    colors, counts = np.unique(quantized, axis=0, return_counts=True)
    fill_color = np.median(crop_bgr[fill_mask], axis=0)
    best = None
    for index in np.argsort(counts)[-8:]:
        members = pixels[np.all(quantized == colors[index], axis=1)]
        color = np.median(members, axis=0)
        if float(np.linalg.norm(color - fill_color)) < 35.0:
            continue
        matches = np.linalg.norm(crop_bgr.astype(np.float32) - color.astype(np.float32), axis=2) <= 34.0
        support = []
        for band_index in range(1, maximum + 5):
            band = (distance > band_index - 1) & (distance <= band_index) & ~unknown
            support.append(float((matches & band).sum()) / max(1, int(band.sum())))
        for width in range(1, maximum + 1):
            inner = float(np.mean(support[:width]))
            outer = float(np.mean(support[width + 1:min(len(support), width + 4)]))
            candidate = (inner - outer, inner, -outer, -width, color, support, matches)
            if best is None or candidate[:4] > best[:4]:
                best = candidate
    if best is None:
        return {"status": "UNRESOLVED_EDGE_EVIDENCE", "present": None, "reason": "no_color_separated_edge_candidate"}
    score, inner, negative_outer, negative_width, color, support, matches = best
    width = -negative_width
    outer = -negative_outer
    stroke_mask = matches & (distance > 0.2) & (distance <= width) & ~unknown
    result = {
        "score": round(float(score), 6), "inner_support": round(float(inner), 6),
        "outer_support": round(float(outer), 6), "width_px": int(width),
        "color_bgr": [int(round(value)) for value in color],
        "known_edge_pixel_count": int(near.sum()), "unknown_edge_pixel_count": int(((distance > 0.2) & (distance <= maximum) & unknown).sum()),
        "stroke_mask": stroke_mask,
    }
    if width >= 2 and score >= 0.15 and inner >= 0.18 and outer <= 0.22:
        return {**result, "status": "CANDIDATE_STROKE_EVIDENCE", "present": True, "reason": None}
    if score <= 0.06 or inner <= 0.12:
        return {**result, "status": "NO_STROKE_EVIDENCE", "present": False, "reason": None}
    return {**result, "status": "UNRESOLVED_EDGE_EVIDENCE", "present": None, "reason": "anti_aliasing_background_or_shadow_ambiguity"}


def aggregate_outline_observations(observations: Iterable[dict[str, object]]) -> dict[str, object]:
    rows = list(observations)
    positive = [row for row in rows if row.get("present") is True]
    negative = [row for row in rows if row.get("present") is False]
    if len(positive) >= 2 and len(positive) / max(1, len(rows)) >= 0.5:
        colors = np.asarray([row["color_bgr"] for row in positive], dtype=np.float32)
        color = np.median(colors, axis=0)
        widths = np.asarray([row["width_px"] for row in positive], dtype=np.float32)
        stable_color = bool(np.max(np.linalg.norm(colors - color, axis=1)) <= 55.0)
        stable_width = bool(np.max(np.abs(widths - np.median(widths))) <= max(1.5, 0.5 * float(np.median(widths))))
        if stable_color and stable_width:
            b, g, r = (int(round(value)) for value in color)
            return {
                "status": "PROVISIONAL_STROKE_INFERENCE", "present": True,
                "width_px_source_space": round(float(np.median(widths)), 6),
                "color_hex": f"#{r:02x}{g:02x}{b:02x}",
                "supporting_observation_count": len(positive), "observation_count": len(rows),
                "reason": "visual_human_review_required",
            }
    if len(rows) >= 2 and len(negative) == len(rows):
        return {
            "status": "PROVISIONAL_NO_STROKE_INFERENCE", "present": False,
            "width_px_source_space": 0.0, "color_hex": None,
            "supporting_observation_count": len(negative), "observation_count": len(rows),
            "reason": "absence_requires_visual_human_review",
        }
    return {
        "status": "NO_AUTHORITATIVE_STROKE_INFERENCE", "present": None,
        "width_px_source_space": None, "color_hex": None,
        "supporting_observation_count": len(positive), "observation_count": len(rows),
        "reason": "inconsistent_or_ambiguous_edge_evidence",
    }
