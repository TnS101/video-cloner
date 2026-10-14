from __future__ import annotations

from collections import defaultdict
from itertools import combinations
from statistics import median
from typing import Iterable, Mapping, Sequence

import numpy as np


def _box(value: Sequence[int | float]) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError("bbox must contain x1, y1, x2, y2")
    x1, y1, x2, y2 = (float(item) for item in value)
    if x2 <= x1 or y2 <= y1:
        raise ValueError("bbox must have positive area")
    return x1, y1, x2, y2


def glyph_bounds(bbox: Sequence[int | float], mask: np.ndarray | None = None) -> tuple[float, float, float, float]:
    """Return source-space visible bounds, or the accepted bbox when no aligned mask exists."""
    x1, y1, x2, y2 = _box(bbox)
    if mask is None:
        return x1, y1, x2, y2
    value = np.asarray(mask, dtype=bool)
    rows, columns = np.where(value)
    if not len(rows):
        raise ValueError("glyph mask is empty")
    scale_x = (x2 - x1) / value.shape[1]
    scale_y = (y2 - y1) / value.shape[0]
    return (
        x1 + float(columns.min()) * scale_x,
        y1 + float(rows.min()) * scale_y,
        x1 + float(columns.max() + 1) * scale_x,
        y1 + float(rows.max() + 1) * scale_y,
    )


def mask_overlap_area(
    a_bbox: Sequence[int | float],
    a_mask: np.ndarray,
    b_bbox: Sequence[int | float],
    b_mask: np.ndarray,
) -> int:
    """Count common source pixels for equally scaled, integer-aligned masks."""
    ax1, ay1, ax2, ay2 = _box(a_bbox)
    bx1, by1, bx2, by2 = _box(b_bbox)
    left, top = int(max(ax1, bx1)), int(max(ay1, by1))
    right, bottom = int(min(ax2, bx2)), int(min(ay2, by2))
    if right <= left or bottom <= top:
        return 0
    a = np.asarray(a_mask, dtype=bool)
    b = np.asarray(b_mask, dtype=bool)
    if a.shape != (int(ay2 - ay1), int(ax2 - ax1)) or b.shape != (int(by2 - by1), int(bx2 - bx1)):
        raise ValueError("mask shape must match integer bbox dimensions")
    return int(np.logical_and(
        a[top - int(ay1):bottom - int(ay1), left - int(ax1):right - int(ax1)],
        b[top - int(by1):bottom - int(by1), left - int(bx1):right - int(bx1)],
    ).sum())


def _measurement(values: Sequence[float], height: float) -> dict[str, float]:
    center = float(median(values))
    return {
        "source_pixels": round(center, 6),
        "normalized_to_median_glyph_height": round(center / max(1.0, height), 6),
        "spread_source_pixels": round(float(max(values) - min(values)), 6),
    }


def _relation(
    a: str,
    b: str,
    kind: str,
    frames: Sequence[int],
    *,
    measurement: dict[str, object] | None,
    authority: str,
    consistency: str,
    unresolved_reason: str | None = None,
) -> dict[str, object]:
    return {
        "source_identity": a,
        "target_identity": b,
        "relationship_type": kind,
        "measurement": measurement,
        "unit": "source_frame_pixels_and_dimensionless_normalization" if measurement else None,
        "observations": len(frames),
        "accepted_observations": len(frames),
        "supporting_frames": sorted(set(int(frame) for frame in frames)),
        "supporting_frame_count": len(set(frames)),
        "consistency": consistency,
        "authority": authority,
        "unresolved_reason": unresolved_reason,
    }


def infer_pair_relationships(
    a: str,
    b: str,
    observations: Iterable[Mapping[str, object]],
    *,
    physical_word: bool = False,
) -> list[dict[str, object]]:
    """Infer editor-neutral pair constraints from co-visible source geometry."""
    rows = sorted(observations, key=lambda row: int(row["frame"]))
    if not rows and not physical_word:
        return []
    frames = [int(row["frame"]) for row in rows]
    result = []
    if rows:
        result.append(_relation(
            a, b, "CO_VISIBLE", frames,
            measurement={"frame_count": len(set(frames))},
            authority="SOURCE_DERIVED", consistency="STATIC_RELATIONSHIP",
        ))
    if physical_word:
        result.append(_relation(
            a, b, "PHYSICAL_WORD_FRAGMENT", frames,
            measurement={"identities_merged": False}, authority="ACCEPTED_SOURCE_PROVEN",
            consistency="STATIC_RELATIONSHIP", unresolved_reason=None if rows else "no_shared_accepted_observation",
        ))
    if not rows:
        return result

    bounds = []
    exact = True
    for row in rows:
        a_mask = row.get("a_mask")
        b_mask = row.get("b_mask")
        exact &= a_mask is not None and b_mask is not None
        bounds.append((
            glyph_bounds(row["a_bbox"], a_mask),
            glyph_bounds(row["b_bbox"], b_mask),
            row,
        ))
    heights = [(abox[3] - abox[1] + bbox[3] - bbox[1]) / 2.0 for abox, bbox, _ in bounds]
    glyph_height = float(median(heights))
    baseline_offsets = [bbox[3] - abox[3] for abox, bbox, _ in bounds]
    baseline = _measurement(baseline_offsets, glyph_height)
    baseline_stable = baseline["spread_source_pixels"] <= max(2.0, glyph_height * 0.20)
    baseline_kind = "SAME_BASELINE" if abs(float(baseline["normalized_to_median_glyph_height"])) <= 0.20 else "BASELINE_OFFSET"
    result.append(_relation(
        a, b, baseline_kind, frames, measurement={
            **baseline,
            "semantics": "visible_glyph_bottom_alignment_proxy",
            "typographic_baseline_exact": False,
        },
        authority="SOURCE_SUPPORTED_VISUAL_BASELINE_PROXY" if exact else "ACCEPTED_BBOX_VISUAL_BASELINE_PROXY",
        consistency="STATIC_RELATIONSHIP" if baseline_stable else "ANIMATED_OR_TIME_VARYING_RELATIONSHIP",
    ))

    dx = [((bbox[0] + bbox[2]) - (abox[0] + abox[2])) / 2.0 for abox, bbox, _ in bounds]
    dy = [((bbox[1] + bbox[3]) - (abox[1] + abox[3])) / 2.0 for abox, bbox, _ in bounds]
    x_gaps = [max(0.0, max(abox[0], bbox[0]) - min(abox[2], bbox[2])) for abox, bbox, _ in bounds]
    y_gaps = [max(0.0, max(abox[1], bbox[1]) - min(abox[3], bbox[3])) for abox, bbox, _ in bounds]
    x_overlap = [
        max(0.0, min(abox[2], bbox[2]) - max(abox[0], bbox[0]))
        / max(1.0, min(abox[2] - abox[0], bbox[2] - bbox[0]))
        for abox, bbox, _ in bounds
    ]
    y_overlap = [
        max(0.0, min(abox[3], bbox[3]) - max(abox[1], bbox[1]))
        / max(1.0, min(abox[3] - abox[1], bbox[3] - bbox[1]))
        for abox, bbox, _ in bounds
    ]
    axis_gap = float(median(x_gaps)) - float(median(y_gaps))
    axis_overlap = float(median(y_overlap)) - float(median(x_overlap))
    horizontal = axis_overlap > 0 or (
        axis_overlap == 0
        and (axis_gap > 0 or (axis_gap == 0 and abs(float(median(dx))) >= abs(float(median(dy)))))
    )
    if horizontal:
        a_before_b = median(dx) >= 0
        gaps = [(bbox[0] - abox[2]) if a_before_b else (abox[0] - bbox[2]) for abox, bbox, _ in bounds]
        gap = _measurement(gaps, glyph_height)
        gap_stable = gap["spread_source_pixels"] <= max(2.0, glyph_height * 0.25)
        consistency = "STATIC_RELATIONSHIP" if gap_stable else "ANIMATED_OR_TIME_VARYING_RELATIONSHIP"
        left, right = (a, b) if a_before_b else (b, a)
        result.append(_relation(left, right, "LEFT_OF", frames, measurement=None, authority="SOURCE_DERIVED", consistency=consistency))
        result.append(_relation(left, right, "HORIZONTAL_GAP", frames, measurement={
            **gap,
            "semantics": "visible_glyph_edge_gap" if exact else "accepted_observation_bbox_edge_gap",
        }, authority="SOURCE_DERIVED_GLYPH_GEOMETRY" if exact else "PROVISIONAL_ACCEPTED_BBOX_PROXY", consistency=consistency))
    else:
        a_above_b = median(dy) >= 0
        gaps = [(bbox[1] - abox[3]) if a_above_b else (abox[1] - bbox[3]) for abox, bbox, _ in bounds]
        gap = _measurement(gaps, glyph_height)
        gap_stable = gap["spread_source_pixels"] <= max(2.0, glyph_height * 0.25)
        consistency = "STATIC_RELATIONSHIP" if gap_stable else "ANIMATED_OR_TIME_VARYING_RELATIONSHIP"
        above, below = (a, b) if a_above_b else (b, a)
        result.append(_relation(above, below, "ABOVE", frames, measurement=None, authority="SOURCE_DERIVED", consistency=consistency))
        result.append(_relation(above, below, "VERTICAL_GAP", frames, measurement={
            **gap,
            "semantics": "visible_glyph_edge_gap" if exact else "accepted_observation_bbox_edge_gap",
        }, authority="SOURCE_DERIVED_GLYPH_GEOMETRY" if exact else "PROVISIONAL_ACCEPTED_BBOX_PROXY", consistency=consistency))

    overlap_areas = []
    overlap_ratios = []
    front = []
    for abox, bbox, row in bounds:
        if row.get("overlap_area_px") is not None:
            area = int(row["overlap_area_px"])
            ratio = float(row.get("overlap_ratio") or 0.0)
        elif row.get("a_mask") is not None and row.get("b_mask") is not None:
            area = mask_overlap_area(row["a_bbox"], row["a_mask"], row["b_bbox"], row["b_mask"])
            smaller = min(int(np.asarray(row["a_mask"], dtype=bool).sum()), int(np.asarray(row["b_mask"], dtype=bool).sum()))
            ratio = area / max(1, smaller)
        else:
            area = 0
            ratio = 0.0
        overlap_areas.append(area)
        overlap_ratios.append(ratio)
        if row.get("front_identity") in (a, b):
            front.append(str(row["front_identity"]))
    positive = [index for index, area in enumerate(overlap_areas) if area > 0]
    if positive:
        persistent = len(positive) == len(rows)
        result.append(_relation(
            a, b, "OVERLAPS", [frames[index] for index in positive],
            measurement={
                "median_overlap_area_source_px": round(float(median(overlap_areas[index] for index in positive)), 6),
                "median_overlap_ratio_of_smaller_glyph": round(float(median(overlap_ratios[index] for index in positive)), 6),
                "persistence": "PERSISTENT" if persistent else "TRANSIENT",
            },
            authority="SOURCE_DERIVED_OWNERSHIP_OR_MASK", consistency="STATIC_RELATIONSHIP" if persistent else "TRANSIENT_RELATIONSHIP",
        ))
        if front and len(front) == len(positive) and len(set(front)) == 1:
            foreground = front[0]
            background = b if foreground == a else a
            result.append(_relation(
                foreground, background, "Z_ORDER", [frames[index] for index in positive],
                measurement={"foreground_identity": foreground, "background_identity": background},
                authority="SOURCE_DERIVED_DIRECTIONAL_OCCLUSION", consistency="STATIC_RELATIONSHIP",
            ))
        else:
            result.append(_relation(
                a, b, "Z_ORDER_UNRESOLVED", [frames[index] for index in positive], measurement=None,
                authority="UNRESOLVED", consistency="UNRESOLVED",
                unresolved_reason="overlap_has_no_consistent_directional_ownership_evidence",
            ))
    return result


def build_composition_graph(
    identities: Sequence[Mapping[str, object]],
    composition_hints: Mapping[str, str],
    physical_word_groups: Sequence[Mapping[str, object]] = (),
    ownership_overlaps: Mapping[tuple[str, str], Sequence[Mapping[str, object]]] | None = None,
) -> dict[str, object]:
    """Build sparse compositions; transcript text is never used for membership."""
    by_id = {str(row["identity"]): row for row in identities}
    accepted = {
        identity: {int(item["source_frame"]): item for item in row.get("observations", []) if item.get("accepted") and item.get("bbox")}
        for identity, row in by_id.items()
    }
    hinted = defaultdict(list)
    for identity, hint in composition_hints.items():
        if identity in by_id and hint:
            hinted[str(hint)].append(identity)
    parent = {identity: identity for identity in by_id}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    overlaps = ownership_overlaps or {}
    physical_pairs = set()
    for group in physical_word_groups:
        if not group.get("joint_evidence_available"):
            continue
        members = [str(value) for value in group.get("member_identities", []) if str(value) in by_id]
        for left, right in combinations(sorted(members), 2):
            physical_pairs.add((left, right))

    pair_relationships = []
    candidate_pairs = set(physical_pairs)
    for members in hinted.values():
        candidate_pairs.update(combinations(sorted(set(members)), 2))
    for left, right in sorted(candidate_pairs):
        shared = sorted(set(accepted[left]) & set(accepted[right]))
        observations = []
        overlap_rows = {int(row["frame"]): row for row in overlaps.get((left, right), overlaps.get((right, left), []))}
        for frame in shared:
            a_bbox = accepted[left][frame]["bbox"]
            b_bbox = accepted[right][frame]["bbox"]
            row = {"frame": frame, "a_bbox": a_bbox, "b_bbox": b_bbox, **overlap_rows.get(frame, {})}
            observations.append(row)
        physical = (left, right) in physical_pairs
        relations = infer_pair_relationships(left, right, observations, physical_word=physical)
        if not relations:
            continue
        if physical or shared:
            union(left, right)
            pair_relationships.extend(relations)

    components = defaultdict(list)
    for identity in sorted(by_id):
        components[find(identity)].append(identity)
    compositions = []
    membership = set()
    for members in sorted((value for value in components.values() if len(value) > 1), key=lambda value: tuple(value)):
        supporting = sorted({frame for identity in members for frame in accepted[identity]})
        composition_id = f"composition_{len(compositions) + 1:04d}"
        compositions.append({
            "composition_id": composition_id,
            "member_identities": members,
            "visible_source_frame_range": [supporting[0], supporting[-1]] if supporting else None,
            "supporting_frames": supporting,
            "authority": "SOURCE_DERIVED_MEMBERSHIP",
        })
        membership.update(members)
    return {
        "coordinate_model": {
            "space": "decoded_source_frame_pixels",
            "bbox_semantics": "accepted observation visible-text extent [x1,y1,x2,y2), used as proxy when aligned glyph masks are unavailable",
            "mask_semantics": "boolean source-visible glyph or frozen ownership evidence when supplied",
            "normalization": "source pixels divided by median visible glyph height",
            "renderer_coordinates_authoritative": False,
        },
        "compositions": compositions,
        "relationships": sorted(pair_relationships, key=lambda row: (
            str(row["source_identity"]), str(row["target_identity"]), str(row["relationship_type"]), tuple(row["supporting_frames"]),
        )),
        "standalone_identities": sorted(set(by_id) - membership),
    }
