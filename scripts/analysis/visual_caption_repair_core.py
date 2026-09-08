"""Generic source-pixel caption repair primitives.

This module intentionally contains no reel IDs, cue IDs, transcript timing, or
Resolve-specific code.  It turns noisy source-video text observations into
stable visual authority.  The design rules are:

* source pixels decide visibility and geometry;
* a tracked text candidate is selected, never the union of every nearby edge;
* static source text becomes a static hold, so detector noise cannot create
  bounce, shimmer, or flicker;
* size is calibrated robustly across a reel instead of trusting per-cue
  outliers;
* fill colour is sampled from the selected source glyph region;
* decorative text with no direct cue mapping may be reconciled from nearby
  canonical text sequence, but sibling text is never blindly duplicated.
"""
from __future__ import annotations

import math
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

import cv2
import numpy as np


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _median(values: Iterable[float], default: float = 0.0) -> float:
    seq = [float(v) for v in values]
    return float(median(seq)) if seq else float(default)


def mad(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    center = _median(values)
    return _median([abs(float(v) - center) for v in values])


def bbox_iou(a: Sequence[float] | None, b: Sequence[float] | None) -> float:
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    ax0, ay0, ax1, ay1 = [float(v) for v in a]
    bx0, by0, bx1, by1 = [float(v) for v in b]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    union = area_a + area_b - inter
    return inter / union if union > 0.0 else 0.0


def _bbox_center(bbox: Sequence[float]) -> tuple[float, float]:
    return ((float(bbox[0]) + float(bbox[2])) * 0.5, (float(bbox[1]) + float(bbox[3])) * 0.5)


def _bbox_size(bbox: Sequence[float]) -> tuple[float, float]:
    return (max(1.0, float(bbox[2]) - float(bbox[0])), max(1.0, float(bbox[3]) - float(bbox[1])))


def _border_background(crop: np.ndarray) -> np.ndarray:
    if crop.size == 0:
        return np.zeros(3, dtype=np.float32)
    top = crop[0, :, :]
    bottom = crop[-1, :, :]
    left = crop[:, 0, :]
    right = crop[:, -1, :]
    border = np.concatenate([top, bottom, left, right], axis=0).astype(np.float32)
    return np.median(border, axis=0)


def text_width_prior_px(text: str, measured_height_px: float) -> float:
    """Estimate a conservative word width from glyph count and text height.

    Historic caption bboxes are useful search seeds, but they can represent a
    whole phrase, neighbouring layer, or style-event envelope instead of the
    current token.  This prior is intentionally typography-agnostic: it uses
    only broad glyph classes and the measured source text height.
    """
    height = max(6.0, float(measured_height_px))
    visible = [ch for ch in str(text or "") if not ch.isspace()]
    spaces = sum(1 for ch in str(text or "") if ch.isspace())
    if not visible:
        return height * 0.70
    units = 0.0
    for ch in visible:
        if ch in "ilI1|!.,:'`;":
            units += 0.34
        elif ch in "mwMW@%&":
            units += 0.88
        elif ch.isdigit():
            units += 0.58
        else:
            units += 0.60
    units += spaces * 0.32
    return max(height * 0.28, height * units)


def normalise_text_geometry(
    text: str,
    expected_width_px: float,
    expected_height_px: float,
) -> dict[str, Any]:
    """Turn possibly broad historic geometry into a token-sized detector prior.

    The historic width is retained when it is compatible with the text/height
    aspect prior.  Grossly broad or narrow widths are replaced by the neutral
    text prior rather than being allowed to suppress otherwise valid source
    glyph candidates.  No reel, cue, font family, or word-specific rule is
    involved.
    """
    height = max(8.0, float(expected_height_px))
    historic = max(2.0, float(expected_width_px))
    prior = text_width_prior_px(text, height)
    ratio = historic / max(prior, 1.0)
    if 0.45 <= ratio <= 2.20:
        width = historic
        source = "historic_bbox_compatible"
    else:
        width = prior
        source = "text_height_aspect_repair"
    return {
        "expected_width_px": round(max(8.0, width), 4),
        "expected_height_px": round(height, 4),
        "historic_width_px": round(historic, 4),
        "text_width_prior_px": round(prior, 4),
        "historic_to_text_ratio": round(ratio, 6),
        "width_source": source,
    }


def ocr_source_presence(
    source_cue_ids: Sequence[str],
    tracks_by_cue: Mapping[str, Mapping[str, Any]],
    frame_width: int,
    frame_height: int,
) -> dict[str, Any]:
    """Classify source presence from OCR/continuity observations.

    Cue/transcript timing is not part of the acceptance test. Once semantic OCR
    observations exist, their source frames define the visual window. Geometry
    without semantic source evidence is never promoted by this function.
    """
    cue_ids = [str(value) for value in source_cue_ids if str(value)]
    covered = [dict(tracks_by_cue[cue_id]) for cue_id in cue_ids if cue_id in tracks_by_cue]
    if not covered:
        return {
            "status": "not_evaluated",
            "source_track_ids": [],
            "reasons": ["no_semantic_source_track"],
            "cue_window_coverage_used_as_authority": False,
        }

    qualified: list[dict[str, Any]] = []
    rejected_reasons: list[str] = []
    for row in covered:
        confidence = row.get("confidence") if isinstance(row.get("confidence"), Mapping) else {}
        direct = int(confidence.get("direct_ocr_frame_count") or 0)
        dense = int(confidence.get("dense_observation_count") or 0)
        similarity = float(confidence.get("median_text_similarity") or 0.0)
        ocr_confidence = float(confidence.get("median_ocr_confidence") or 0.0)
        if direct >= 1 and dense >= 2 and similarity >= 0.62 and ocr_confidence >= 0.24:
            qualified.append(row)
        else:
            rejected_reasons.extend(str(value) for value in row.get("fallback_reasons") or [] if str(value))
            if direct < 1:
                rejected_reasons.append("no_direct_ocr_seed")
            if dense < 2:
                rejected_reasons.append("insufficient_dense_observations")
            if similarity < 0.62:
                rejected_reasons.append("median_text_similarity_below_0_62")
            if ocr_confidence < 0.24:
                rejected_reasons.append("median_ocr_confidence_below_0_24")

    if not qualified:
        return {
            "status": "unresolved",
            "source_track_ids": [str(row.get("cue_id") or "") for row in covered],
            "reasons": sorted(set(rejected_reasons)) or ["semantic_source_track_not_confirmed"],
            "cue_window_coverage_used_as_authority": False,
        }

    tracked: dict[int, dict[str, Any]] = {}
    direct_count = 0
    dense_count = 0
    similarities: list[float] = []
    confidences: list[float] = []
    for row in qualified:
        confidence = row.get("confidence") if isinstance(row.get("confidence"), Mapping) else {}
        direct_count += int(confidence.get("direct_ocr_frame_count") or 0)
        dense_count += int(confidence.get("dense_observation_count") or 0)
        similarities.append(float(confidence.get("median_text_similarity") or 0.0))
        confidences.append(float(confidence.get("median_ocr_confidence") or 0.0))
        for item in row.get("frame_observations") or []:
            if not isinstance(item, Mapping):
                continue
            bbox = item.get("normalized_bbox")
            if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
                continue
            try:
                values = [float(value) for value in bbox]
                frame = int(item.get("timeline_frame"))
            except (TypeError, ValueError):
                continue
            if not (0.0 <= values[0] < values[2] <= 1.0 and 0.0 <= values[1] < values[3] <= 1.0):
                continue
            abs_bbox = [
                values[0] * frame_width,
                values[1] * frame_height,
                values[2] * frame_width,
                values[3] * frame_height,
            ]
            score = float(item.get("assignment_score") or item.get("ocr_confidence") or item.get("text_similarity") or 0.0)
            candidate = {
                "bbox": [round(value, 4) for value in abs_bbox],
                "base_score": round(clamp(score, 0.0, 1.0), 8),
                "method": str(item.get("method") or "ocr"),
                "semantic_source_track": str(row.get("cue_id") or ""),
            }
            prior = tracked.get(frame)
            if prior is None or float(candidate["base_score"]) > float(prior.get("base_score") or 0.0):
                tracked[frame] = candidate

    if len(tracked) < 2:
        return {
            "status": "unresolved",
            "source_track_ids": [str(row.get("cue_id") or "") for row in qualified],
            "reasons": ["insufficient_valid_source_observations"],
            "cue_window_coverage_used_as_authority": False,
        }

    frames = sorted(tracked)
    peak_frame = max(frames, key=lambda frame: float(tracked[frame].get("base_score") or 0.0))
    return {
        "status": "confirmed",
        "source_track_ids": [str(row.get("cue_id") or "") for row in qualified],
        "window": [frames[0], frames[-1] + 1],
        "selected_frames": frames,
        "peak_frame": int(peak_frame),
        "peak_score": round(float(tracked[peak_frame].get("base_score") or 0.0), 8),
        "tracked": tracked,
        "direct_ocr_frame_count": direct_count,
        "dense_observation_count": dense_count,
        "median_text_similarity": round(_median(similarities), 6),
        "median_ocr_confidence": round(_median(confidences), 6),
        "cue_window_coverage_used_as_authority": False,
        "reasons": [],
    }

def _candidate_score(
    bbox: Sequence[int],
    seed_px: tuple[float, float],
    expected_width_px: float,
    expected_height_px: float,
    edge_density: float,
) -> float:
    cx, cy = _bbox_center(bbox)
    width, height = _bbox_size(bbox)
    dx = abs(cx - seed_px[0]) / max(35.0, expected_width_px * 0.75)
    dy = abs(cy - seed_px[1]) / max(24.0, expected_height_px * 1.2)
    width_error = abs(math.log(max(width, 1.0) / max(expected_width_px, 1.0)))
    height_error = abs(math.log(max(height, 1.0) / max(expected_height_px, 1.0)))
    geometry = math.exp(-(0.50 * dx + 0.85 * dy + 0.45 * width_error + 0.70 * height_error))
    density = clamp(edge_density * 2.5, 0.0, 1.0)
    return clamp(0.82 * geometry + 0.18 * density, 0.0, 1.0)


def frame_candidates(
    frame: np.ndarray,
    center_top_origin: Sequence[float],
    expected_width_px: float,
    expected_height_px: float,
    *,
    max_candidates: int = 10,
) -> list[dict[str, Any]]:
    """Return ranked word-like source regions around a visual seed.

    Detection is deliberately colour-agnostic.  It uses local contrast and
    edge support so a wrong historic fill colour cannot hide the real word.
    Horizontal morphology connects glyph strokes into word-sized candidates,
    while the expected text geometry keeps neighbouring words separable.
    """
    if frame is None or frame.size == 0:
        return []
    height, width = frame.shape[:2]
    sx = clamp(float(center_top_origin[0]), 0.0, 1.0) * width
    sy = clamp(float(center_top_origin[1]), 0.0, 1.0) * height
    ew = max(22.0, float(expected_width_px))
    eh = max(8.0, float(expected_height_px))

    half_w = int(round(clamp(ew * 1.30 + 42.0, 90.0, width * 0.46)))
    half_h = int(round(clamp(eh * 2.20 + 34.0, 62.0, height * 0.24)))
    x0, x1 = max(0, int(round(sx)) - half_w), min(width, int(round(sx)) + half_w + 1)
    y0, y1 = max(0, int(round(sy)) - half_h), min(height, int(round(sy)) + half_h + 1)
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return []

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    gradient = cv2.magnitude(gx, gy)
    bg = _border_background(crop)
    colour_delta = np.linalg.norm(crop.astype(np.float32) - bg.reshape(1, 1, 3), axis=2)

    edge = gradient >= 18.0
    contrast = colour_delta >= 14.0
    mask = (edge & contrast).astype(np.uint8) * 255
    mask = cv2.dilate(mask, np.ones((3, 3), dtype=np.uint8), iterations=1)
    close_w = max(3, int(round(eh * 0.16)))
    word_mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, close_w), dtype=np.uint8))

    count, _, stats, _ = cv2.connectedComponentsWithStats((word_mask > 0).astype(np.uint8), connectivity=8)
    rows: list[dict[str, Any]] = []
    roi_area = max(1, crop.shape[0] * crop.shape[1])
    for idx in range(1, count):
        bx, by, bw, bh, area = [int(v) for v in stats[idx]]
        if area < 9 or area > roi_area * 0.34:
            continue
        if bh < max(4.0, eh * 0.20) or bh > eh * 2.25:
            continue
        if bw < 2 or bw > ew * 1.85:
            continue
        abs_bbox = [x0 + bx, y0 + by, x0 + bx + bw, y0 + by + bh]
        cx, cy = _bbox_center(abs_bbox)
        if abs(cy - sy) > max(40.0, eh * 1.75):
            continue
        if abs(cx - sx) > max(95.0, ew * 1.10):
            continue
        local_edge = edge[by : by + bh, bx : bx + bw]
        edge_density = float(local_edge.mean()) if local_edge.size else 0.0
        score = _candidate_score(abs_bbox, (sx, sy), ew, eh, edge_density)
        rows.append(
            {
                "bbox": abs_bbox,
                "base_score": round(score, 8),
                "edge_density": round(edge_density, 8),
                "roi": [x0, y0, x1, y1],
            }
        )

    # When morphology merges two neighbouring words, also derive narrower
    # candidates from contours.  Width matching decides whether the full word
    # or a narrower cluster fits the current canonical token.
    contours, _ = cv2.findContours((mask > 0).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    fragments = []
    for contour in contours:
        bx, by, bw, bh = cv2.boundingRect(contour)
        if bw >= 2 and bh >= max(3, int(eh * 0.16)) and bh <= eh * 2.0:
            fragments.append((bx, by, bw, bh))
    fragments.sort(key=lambda r: (r[1] + r[3] * 0.5, r[0]))
    for i, first in enumerate(fragments):
        line = [first]
        first_cy = first[1] + first[3] * 0.5
        for nxt in fragments[i + 1 : i + 12]:
            nxt_cy = nxt[1] + nxt[3] * 0.5
            if abs(nxt_cy - first_cy) > eh * 0.55:
                continue
            prev = line[-1]
            gap = nxt[0] - (prev[0] + prev[2])
            if gap > max(18.0, eh * 0.55):
                break
            line.append(nxt)
            lx0 = min(r[0] for r in line)
            ly0 = min(r[1] for r in line)
            lx1 = max(r[0] + r[2] for r in line)
            ly1 = max(r[1] + r[3] for r in line)
            bw, bh = lx1 - lx0, ly1 - ly0
            if bw > ew * 1.85:
                break
            if bw < ew * 0.30:
                continue
            abs_bbox = [x0 + lx0, y0 + ly0, x0 + lx1, y0 + ly1]
            local_edge = edge[ly0:ly1, lx0:lx1]
            edge_density = float(local_edge.mean()) if local_edge.size else 0.0
            score = _candidate_score(abs_bbox, (sx, sy), ew, eh, edge_density)
            rows.append({"bbox": abs_bbox, "base_score": round(score, 8), "edge_density": round(edge_density, 8), "roi": [x0, y0, x1, y1]})

    # Deduplicate near-identical boxes.
    rows.sort(key=lambda row: float(row["base_score"]), reverse=True)
    deduped: list[dict[str, Any]] = []
    for row in rows:
        if any(bbox_iou(row["bbox"], old["bbox"]) >= 0.88 for old in deduped):
            continue
        deduped.append(row)
        if len(deduped) >= max_candidates:
            break
    return deduped


def choose_tracked_candidate(candidates: Sequence[Mapping[str, Any]], previous_bbox: Sequence[float] | None) -> dict[str, Any] | None:
    if not candidates:
        return None
    if not previous_bbox:
        return dict(candidates[0])
    px, py = _bbox_center(previous_bbox)
    pw, ph = _bbox_size(previous_bbox)
    best = None
    best_score = -1e9
    for raw in candidates:
        row = dict(raw)
        bbox = row.get("bbox")
        if not bbox:
            continue
        cx, cy = _bbox_center(bbox)
        jump = math.hypot(cx - px, cy - py) / max(8.0, ph)
        size_w, size_h = _bbox_size(bbox)
        size_jump = abs(math.log(size_h / max(ph, 1.0))) + 0.35 * abs(math.log(size_w / max(pw, 1.0)))
        score = float(row.get("base_score") or 0.0) + 0.55 * bbox_iou(previous_bbox, bbox) - 0.10 * jump - 0.08 * size_jump
        if score > best_score:
            best_score = score
            best = row
    if best is None:
        return None
    best["tracking_score"] = round(float(best_score), 8)
    return best


def track_candidate_series(
    candidate_rows: Mapping[int, Sequence[Mapping[str, Any]]],
    seed_window: Sequence[int],
) -> dict[int, dict[str, Any] | None]:
    frames = sorted(int(frame) for frame in candidate_rows)
    if not frames:
        return {}
    seed_start, seed_end = int(seed_window[0]), int(seed_window[1])
    anchor_pool = [f for f in frames if seed_start <= f < seed_end and candidate_rows.get(f)]
    if not anchor_pool:
        anchor_pool = [f for f in frames if candidate_rows.get(f)]
    if not anchor_pool:
        return {f: None for f in frames}

    # Anchor on a candidate that is supported by neighbouring frames, not on
    # the single highest raw score.  This prevents a nearby word/background
    # edge from stealing identity for one frame.
    anchor_choice: tuple[float, int, dict[str, Any]] | None = None
    frame_set = set(frames)
    for frame in anchor_pool:
        for raw in candidate_rows.get(frame) or []:
            bbox = raw.get("bbox")
            if not bbox:
                continue
            support = 0.0
            for neighbour in (frame - 1, frame + 1):
                if neighbour not in frame_set:
                    continue
                support += max((bbox_iou(bbox, other.get("bbox")) for other in candidate_rows.get(neighbour) or []), default=0.0)
            score = float(raw.get("base_score") or 0.0) + 0.35 * support
            candidate = (score, frame, dict(raw))
            if anchor_choice is None or candidate[0] > anchor_choice[0]:
                anchor_choice = candidate
    if anchor_choice is None:
        return {f: None for f in frames}
    _, anchor, anchor_row = anchor_choice
    chosen: dict[int, dict[str, Any] | None] = {f: None for f in frames}
    chosen[anchor] = anchor_row

    prev = chosen[anchor].get("bbox") if chosen[anchor] else None
    for frame in [f for f in frames if f > anchor]:
        item = choose_tracked_candidate(candidate_rows.get(frame) or [], prev)
        chosen[frame] = item
        if item is not None and float(item.get("base_score") or 0.0) >= 0.12:
            prev = item.get("bbox")
    prev = chosen[anchor].get("bbox") if chosen[anchor] else None
    for frame in sorted([f for f in frames if f < anchor], reverse=True):
        item = choose_tracked_candidate(candidate_rows.get(frame) or [], prev)
        chosen[frame] = item
        if item is not None and float(item.get("base_score") or 0.0) >= 0.12:
            prev = item.get("bbox")
    return chosen


def derive_visibility_window(
    tracked: Mapping[int, Mapping[str, Any] | None],
    seed_window: Sequence[int],
) -> dict[str, Any]:
    frames = sorted(int(f) for f in tracked)
    scores = {f: float((tracked.get(f) or {}).get("base_score") or 0.0) for f in frames}
    if not scores or max(scores.values(), default=0.0) <= 0.0:
        return {"ok": False, "window": None, "selected_frames": [], "peak_score": 0.0}
    peak = max(scores.values())
    high = max(0.20, peak * 0.48)
    low = max(0.11, peak * 0.28)
    active = [f for f in frames if scores[f] >= low]
    runs: list[list[int]] = []
    for frame in active:
        if not runs or frame != runs[-1][-1] + 1:
            runs.append([frame])
        else:
            runs[-1].append(frame)
    valid = []
    for run in runs:
        high_count = sum(1 for f in run if scores[f] >= high)
        if high_count >= 2 or (len(run) == 1 and scores[run[0]] >= max(0.72, peak * 0.86)):
            valid.append(run)
    if not valid:
        return {"ok": False, "window": None, "selected_frames": [], "peak_score": round(peak, 8), "high_threshold": round(high, 8), "low_threshold": round(low, 8)}
    seed_start, seed_end = int(seed_window[0]), int(seed_window[1])
    def rank(run: Sequence[int]) -> tuple[float, float]:
        overlap = sum(1 for f in run if seed_start <= f < seed_end)
        distance = 0 if overlap else min(abs(run[-1] - seed_start), abs(run[0] - (seed_end - 1)))
        return (sum(scores[f] for f in run) + overlap * 1.7 - distance * 0.10, -distance)
    run = max(valid, key=rank)
    return {
        "ok": True,
        "window": [int(run[0]), int(run[-1]) + 1],
        "selected_frames": [int(f) for f in run],
        "peak_score": round(peak, 8),
        "high_threshold": round(high, 8),
        "low_threshold": round(low, 8),
        "peak_frame": int(max(run, key=lambda f: scores[f])),
    }


def _linear_fit(frames: Sequence[int], values: Sequence[float]) -> tuple[float, float, float]:
    if len(frames) < 2:
        return 0.0, float(values[0]) if values else 0.0, 0.0
    x = np.asarray(frames, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    slope, intercept = np.polyfit(x, y, 1)
    predicted = slope * x + intercept
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-9 else 1.0
    return float(slope), float(intercept), clamp(r2, -1.0, 1.0)


def build_size_calibration(seed_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ratios: list[tuple[str, float]] = []
    for row in seed_rows:
        try:
            size = float(row.get("base_size") or 0.0)
            expected_h = float(row.get("expected_height_px") or 0.0)
        except (TypeError, ValueError):
            continue
        family = str(row.get("font_family") or "").strip()
        if 0.015 <= size <= 0.22 and 6.0 <= expected_h <= 220.0:
            ratios.append((family, size / expected_h))
    global_ratio = _median([value for _, value in ratios], 0.0018)
    # Robustly remove cross-reel/cue outliers before calculating font-family
    # calibration.  A family with too few samples deliberately falls back to
    # the global median rather than trusting a single pathological cue.
    global_values = [value for _, value in ratios]
    global_mad = mad(global_values)
    if global_mad > 0:
        filtered = [value for value in global_values if abs(value - global_ratio) <= max(global_mad * 4.0, global_ratio * 0.55)]
        if filtered:
            global_ratio = _median(filtered, global_ratio)
    by_font: dict[str, float] = {}
    families = sorted(set(family for family, _ in ratios if family))
    for family in families:
        values = [value for name, value in ratios if name == family]
        if len(values) < 3:
            continue
        center = _median(values)
        spread = mad(values)
        clean = [v for v in values if spread <= 1e-12 or abs(v - center) <= max(spread * 3.5, center * 0.45)]
        if len(clean) >= 3:
            by_font[family] = _median(clean, center)
    return {"global_ratio": global_ratio, "font_ratios": by_font, "sample_count": len(ratios)}


def calibrated_application_size(font_family: str, measured_height_px: float, calibration: Mapping[str, Any]) -> float:
    ratio = float((calibration.get("font_ratios") or {}).get(font_family) or calibration.get("global_ratio") or 0.0018)
    return clamp(float(measured_height_px) * ratio, 0.018, 0.22)


def sample_fill_hex(frame: np.ndarray, bbox: Sequence[int]) -> tuple[str, float]:
    if frame is None or frame.size == 0 or not bbox or len(bbox) != 4:
        return "", 0.0
    height, width = frame.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in bbox]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(width, x1), min(height, y1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return "", 0.0
    pad = max(2, int(round((y1 - y0) * 0.20)))
    bx0, by0 = max(0, x0 - pad), max(0, y0 - pad)
    bx1, by1 = min(width, x1 + pad), min(height, y1 + pad)
    around = frame[by0:by1, bx0:bx1]
    bg = _border_background(around)
    crop = frame[y0:y1, x0:x1]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad = cv2.magnitude(gx, gy)
    delta = np.linalg.norm(crop.astype(np.float32) - bg.reshape(1, 1, 3), axis=2)
    mask = (delta >= 24.0) & (grad >= 10.0)
    pixels = crop[mask]
    if len(pixels) < 8:
        return "", 0.0
    quant = (pixels.astype(np.int16) // 24) * 24 + 12
    quant = np.clip(quant, 0, 255).astype(np.uint8)
    bins, counts = np.unique(quant.reshape(-1, 3), axis=0, return_counts=True)
    best_idx = int(np.argmax(counts))
    bgr = bins[best_idx].astype(int)
    confidence = float(counts[best_idx]) / max(1, int(counts.sum()))
    b, g, r = [int(v) for v in bgr]
    return f"#{r:02x}{g:02x}{b:02x}", round(confidence, 6)


def stabilise_path(
    tracked: Mapping[int, Mapping[str, Any] | None],
    window: Sequence[int],
    frame_width: int,
    frame_height: int,
    font_family: str,
    calibration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    start, end = int(window[0]), int(window[1])
    frames = list(range(start, end))
    observed = []
    for frame in frames:
        row = tracked.get(frame)
        if row and row.get("bbox"):
            bbox = row["bbox"]
            cx, cy = _bbox_center(bbox)
            _, bh = _bbox_size(bbox)
            observed.append((frame, cx, cy, bh, bbox))
    if not observed:
        raise ValueError("no_source_geometry")

    obs_frames = [r[0] for r in observed]
    xs = [r[1] for r in observed]
    ys = [r[2] for r in observed]
    hs = [r[3] for r in observed]
    median_x, median_y, median_h = _median(xs), _median(ys), _median(hs)
    sx, ix, r2x = _linear_fit(obs_frames, xs)
    sy, iy, r2y = _linear_fit(obs_frames, ys)
    sh, ih, r2h = _linear_fit(obs_frames, hs)
    span = max(obs_frames) - min(obs_frames) if len(obs_frames) > 1 else 0
    displacement_x = abs(sx * span)
    displacement_y = abs(sy * span)
    move_threshold = max(2.5, median_h * 0.13)
    position_dynamic = bool(
        (displacement_x >= move_threshold and r2x >= 0.68)
        or (displacement_y >= move_threshold and r2y >= 0.68)
    )
    height_change = abs(sh * span)
    size_dynamic = bool(height_change >= max(2.5, median_h * 0.13) and r2h >= 0.72)

    base_size = calibrated_application_size(font_family, median_h, calibration)
    result: list[dict[str, Any]] = []
    for frame in frames:
        if position_dynamic:
            cx = sx * frame + ix if displacement_x >= move_threshold and r2x >= 0.68 else median_x
            cy = sy * frame + iy if displacement_y >= move_threshold and r2y >= 0.68 else median_y
        else:
            cx, cy = median_x, median_y
        if size_dynamic:
            height_px = clamp(sh * frame + ih, median_h * 0.70, median_h * 1.30)
            size = calibrated_application_size(font_family, height_px, calibration)
        else:
            height_px = median_h
            size = base_size
        result.append(
            {
                "timeline_frame": frame,
                "position_top_origin": [round(clamp(cx / frame_width, 0.0, 1.0), 6), round(clamp(cy / frame_height, 0.0, 1.0), 6)],
                "position_fusion": [round(clamp(cx / frame_width, 0.0, 1.0), 6), round(clamp(1.0 - cy / frame_height, 0.0, 1.0), 6)],
                "application_size_candidate": round(size, 12),
                "size_scale": round(size / max(base_size, 1e-9), 6),
                # Fade fidelity is a separate later problem.  Using source
                # detector score as per-frame alpha created the reported
                # flicker, so this repair authority explicitly emits a hold.
                "opacity_factor": 1.0,
            }
        )
    metrics = {
        "position_model": "source_linear_motion" if position_dynamic else "source_static_hold",
        "size_model": "source_linear_scale" if size_dynamic else "source_static_hold",
        "opacity_model": "hold_no_synthetic_flicker",
        "median_bbox_height_px": round(median_h, 4),
        "position_r2": [round(r2x, 6), round(r2y, 6)],
        "size_r2": round(r2h, 6),
        "displacement_px": [round(displacement_x, 4), round(displacement_y, 4)],
        "height_change_px": round(height_change, 4),
        "jitter_mad_px": [round(mad(xs), 4), round(mad(ys), 4), round(mad(hs), 4)],
    }
    return result, metrics


def reconcile_unmapped_script_text(
    token: Mapping[str, Any],
    neighbour_rows: Sequence[Mapping[str, Any]],
    *,
    blocked_texts: Sequence[str] = (),
    max_gap_frames: int = 16,
) -> dict[str, Any]:
    """Resolve an unmapped decorative script layer from nearby text sequence.

    This is not OCR and does not hard-code any word.  It is only used when the
    visual layer has no cue mapping, is script-like, and nearby canonical cues
    provide a temporally contiguous candidate.  Width/height of the source
    visual layer selects between one-, two-, and three-token candidates.
    """
    role = (str(token.get("role") or "") + " " + str(token.get("visual_kind") or "")).lower()
    font = token.get("font") if isinstance(token.get("font"), Mapping) else {}
    style = token.get("style_lock") if isinstance(token.get("style_lock"), Mapping) else {}
    font_class = str(style.get("font_class") or "").lower()
    family = str(font.get("font_family") or "").lower()
    if "script" not in role and "script" not in font_class and "script" not in family:
        return {"ok": False, "method": "not_script_layer", "text": str(token.get("display_text") or "")}
    anchor = token.get("source_pixel_anchor") if isinstance(token.get("source_pixel_anchor"), Mapping) else {}
    bbox = anchor.get("source_bbox_px_540x960")
    if not isinstance(bbox, list) or len(bbox) != 4:
        return {"ok": False, "method": "missing_source_bbox", "text": str(token.get("display_text") or "")}
    width, height = _bbox_size(bbox)
    actual_aspect = width / max(height, 1.0)
    window = token.get("visual_window") or []
    if not isinstance(window, list) or len(window) != 2:
        return {"ok": False, "method": "missing_visual_window", "text": str(token.get("display_text") or "")}
    start = int(window[0])
    blocked = {str(v).strip().casefold() for v in blocked_texts if str(v).strip()}
    eligible = []
    for row in neighbour_rows:
        text = str(row.get("canonical_text") or "").strip()
        rwindow = row.get("visual_window") or []
        if not text or text.casefold() in blocked or not isinstance(rwindow, list) or len(rwindow) != 2:
            continue
        rstart, rend = int(rwindow[0]), int(rwindow[1])
        if rend < start - max_gap_frames or rstart > start + 8:
            continue
        eligible.append((rstart, rend, text, str(row.get("instance_id") or "")))
    eligible.sort(key=lambda r: (r[0], r[1]))

    # If the visual layer's current text is independently corroborated by a
    # nearby canonical instance, keep it.  This handles single decorative
    # glyphs without asking source-aspect heuristics to infer their width.
    current_text = str(token.get("display_text") or "").strip()
    if current_text and current_text.casefold() not in blocked:
        exact = min(
            (row for row in eligible if row[2].casefold() == current_text.casefold()),
            key=lambda row: abs(start - row[0]),
            default=None,
        )
        if exact is not None:
            return {
                "ok": True,
                "method": "nearby_canonical_exact_text",
                "text": exact[2],
                "source_instance_ids": [exact[3]],
                "aspect_error": None,
                "gap_frames": max(0, start - exact[1]),
                "score": 0.0,
            }

    candidates = []
    for end_index in range(len(eligible)):
        for count in (1, 2, 3):
            begin = end_index - count + 1
            if begin < 0:
                continue
            seq = eligible[begin : end_index + 1]
            if any(seq[i + 1][0] - seq[i][1] > max_gap_frames for i in range(len(seq) - 1)):
                continue
            latest_end = max(r[1] for r in seq)
            gap = max(0, start - latest_end)
            text = " ".join(r[2] for r in seq)
            # Script glyphs are narrower than bold geometric sans.  This ratio
            # is deliberately a font-class prior, not a word-specific rule.
            predicted_aspect = max(0.30, len(text) * 0.33)
            aspect_error = abs(math.log(max(predicted_aspect, 0.01) / max(actual_aspect, 0.01)))
            score = aspect_error + gap * 0.035 - (count - 1) * 0.06
            candidates.append((score, text, [r[3] for r in seq], aspect_error, gap))
    if not candidates:
        return {"ok": False, "method": "no_nearby_sequence", "text": str(token.get("display_text") or "")}
    score, text, ids, aspect_error, gap = min(candidates, key=lambda r: r[0])
    ok = bool(aspect_error <= 0.62 and gap <= max_gap_frames)
    return {
        "ok": ok,
        "method": "nearby_canonical_sequence_by_source_aspect" if ok else "sequence_low_confidence",
        "text": text if ok else str(token.get("display_text") or ""),
        "source_instance_ids": ids if ok else [],
        "aspect_error": round(aspect_error, 6),
        "gap_frames": int(gap),
        "score": round(float(score), 6),
    }
