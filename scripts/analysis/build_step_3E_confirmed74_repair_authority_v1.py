#!/usr/bin/env python3
"""Build the locked source-confirmed 74-caption repair authority.

The authority is deliberately smaller than the structural caption inventory.
It combines the 47 source-confirmed rows from the universal repair authority
with the 27 rows later confirmed by targeted semantic OCR. The 23 unresolved
rows remain excluded. Three redundant structural rows represented by accepted
protected composites are marked for removal and are never recreated.

For newly confirmed rows, source-pixel selected frames provide the visibility
window and semantic OCR bboxes provide geometry. Geometry is stabilised into a
static hold unless a strong linear source-motion signal is present. Detector
score never becomes opacity. Fill may be corrected only from source glyph
pixels with generic confidence/consistency gates. Transcript timing is never
authoritative and Resolve is not modified by this builder.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_V1"
UNIVERSAL = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_v1.json")
UNIVERSAL_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/universal_visual_repair_authority_validation.json")
SEMANTIC = Path("artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_v1.json")
SEMANTIC_VALIDATION = Path("artifacts/DZSQH7AUHJT_STEP_3E_SEMANTIC_SOURCE_COVERAGE_V1/semantic_source_coverage_validation.json")
CORE = Path("scripts/analysis/visual_caption_repair_core.py")
OUTPUT = Path("artifacts/DZSQH7AUHJT_STEP_3E_CONFIRMED74_REPAIR_AUTHORITY_V1/confirmed74_repair_authority_v1.json")

EXPECTED_TOTAL = 117
EXPECTED_PROTECTED = 17
EXPECTED_EXISTING_CONFIRMED = 47
EXPECTED_NEW_CONFIRMED = 27
EXPECTED_REPAIR = 74
EXPECTED_UNRESOLVED = 23
EXPECTED_COMPOSITE_STRUCTURAL = 3
EXPECTED_STRUCTURAL = 100
EXPECTED_PHYSICAL_TEXTPLUS = 114
MIN_EXISTING_FILL_CONFIDENCE = 0.15
MIN_NEW_SINGLE_FILL_CONFIDENCE = 0.15
MIN_NEW_MULTI_FILL_CONFIDENCE = 0.06
MIN_NEW_MULTI_FILL_CONSISTENCY = 0.60


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValueError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_core(repo_root: Path):
    path = repo_root / CORE
    spec = importlib.util.spec_from_file_location("vc_confirmed74_core", path)
    require(spec is not None and spec.loader is not None, "core_import_spec")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def linear_fit(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float, float]:
    require(len(xs) == len(ys) and len(xs) > 0, "linear_fit_input")
    if len(xs) == 1:
        return 0.0, float(ys[0]), 0.0
    mx = sum(float(v) for v in xs) / len(xs)
    my = sum(float(v) for v in ys) / len(ys)
    denom = sum((float(x) - mx) ** 2 for x in xs)
    if denom <= 1e-12:
        return 0.0, my, 0.0
    slope = sum((float(x) - mx) * (float(y) - my) for x, y in zip(xs, ys)) / denom
    intercept = my - slope * mx
    fitted = [slope * float(x) + intercept for x in xs]
    ss_res = sum((float(y) - pred) ** 2 for y, pred in zip(ys, fitted))
    ss_tot = sum((float(y) - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 1.0
    return float(slope), float(intercept), float(r2)


def hex_rgb(value: str) -> tuple[int, int, int]:
    text = str(value or "").strip().lower()
    require(len(text) == 7 and text.startswith("#"), f"hex:{value}")
    return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))


def weighted_median(values: Sequence[tuple[float, float]]) -> float:
    require(bool(values), "weighted_median_empty")
    rows = sorted((float(value), max(0.0, float(weight))) for value, weight in values)
    total = sum(weight for _, weight in rows)
    if total <= 1e-12:
        return float(statistics.median(value for value, _ in rows))
    acc = 0.0
    for value, weight in rows:
        acc += weight
        if acc >= total / 2.0:
            return value
    return rows[-1][0]


def robust_fill_choice(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [
        {"hex": str(row.get("hex") or "").lower(), "confidence": float(row.get("confidence") or 0.0)}
        for row in samples
        if str(row.get("hex") or "").startswith("#") and float(row.get("confidence") or 0.0) > 0.0
    ]
    if not valid:
        return {"fill_hex": "", "confidence": 0.0, "support_count": 0, "consistency": 0.0, "apply": False}
    groups = Counter(row["hex"] for row in valid)
    best_hex, support = sorted(groups.items(), key=lambda item: (-item[1], item[0]))[0]
    best_rows = [row for row in valid if row["hex"] == best_hex]
    confidence = float(statistics.median(row["confidence"] for row in best_rows))
    consistency = support / len(valid)
    apply = (
        (len(valid) == 1 and confidence >= MIN_NEW_SINGLE_FILL_CONFIDENCE)
        or (
            len(valid) >= 2
            and confidence >= MIN_NEW_MULTI_FILL_CONFIDENCE
            and consistency >= MIN_NEW_MULTI_FILL_CONSISTENCY
        )
    )
    return {
        "fill_hex": best_hex,
        "confidence": round(confidence, 6),
        "support_count": int(support),
        "sample_count": len(valid),
        "consistency": round(consistency, 6),
        "apply": bool(apply),
    }


def existing_fill_repair(style: Mapping[str, Any]) -> dict[str, Any]:
    fill_hex = str(style.get("source_sampled_fill_hex") or "").lower()
    confidence = float(style.get("source_sampled_fill_confidence") or 0.0)
    apply = bool(fill_hex.startswith("#") and confidence >= MIN_EXISTING_FILL_CONFIDENCE)
    return {
        "fill_hex": fill_hex,
        "confidence": round(confidence, 6),
        "support_count": 1 if fill_hex else 0,
        "sample_count": 1 if fill_hex else 0,
        "consistency": 1.0 if fill_hex else 0.0,
        "source": "universal_source_pixel_fill_sample",
        "apply": apply,
    }


def semantic_geometry_path(
    coverage_row: Mapping[str, Any],
    universal_row: Mapping[str, Any],
    frame_height: int,
    calibration: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = [int(v) for v in (coverage_row.get("search_prior") or {}).get("source_pixel_selected_frames") or []]
    require(bool(selected), f"selected_frames:{coverage_row.get('instance_id')}")
    selected = sorted(set(selected))
    require(selected == list(range(selected[0], selected[-1] + 1)), f"selected_frames_not_dense:{coverage_row.get('instance_id')}")
    observations = [row for row in coverage_row.get("semantic_observations") or [] if isinstance(row, Mapping)]
    require(bool(observations), f"semantic_observations:{coverage_row.get('instance_id')}")
    frames = [int(row["timeline_frame"]) for row in observations]
    centers_x: list[float] = []
    centers_y: list[float] = []
    heights: list[float] = []
    for row in observations:
        bbox = [float(v) for v in row.get("normalized_bbox") or []]
        require(len(bbox) == 4, f"semantic_bbox:{coverage_row.get('instance_id')}")
        require(0.0 <= bbox[0] < bbox[2] <= 1.0 and 0.0 <= bbox[1] < bbox[3] <= 1.0, f"semantic_bbox_range:{coverage_row.get('instance_id')}")
        centers_x.append((bbox[0] + bbox[2]) / 2.0)
        centers_y.append((bbox[1] + bbox[3]) / 2.0)
        heights.append(bbox[3] - bbox[1])
    median_x = float(statistics.median(centers_x))
    median_y = float(statistics.median(centers_y))
    median_h = float(statistics.median(heights))
    sx, ix, r2x = linear_fit(frames, centers_x)
    sy, iy, r2y = linear_fit(frames, centers_y)
    sh, ih, r2h = linear_fit(frames, heights)
    span = max(frames) - min(frames) if len(frames) > 1 else 0
    displacement_x = abs(sx * span)
    displacement_y = abs(sy * span)
    position_threshold = max(0.0030, median_h * 0.13)
    position_dynamic = bool(
        len(frames) >= 4
        and (
            (displacement_x >= position_threshold and r2x >= 0.75)
            or (displacement_y >= position_threshold and r2y >= 0.75)
        )
    )
    height_change = abs(sh * span)
    size_threshold = max(0.0025, median_h * 0.13)
    size_dynamic = bool(len(frames) >= 4 and height_change >= size_threshold and r2h >= 0.82)
    style = universal_row.get("style") if isinstance(universal_row.get("style"), Mapping) else {}
    family = str(style.get("font_family") or "")
    ratio = float((calibration.get("font_ratios") or {}).get(family) or calibration.get("global_ratio") or 0.0018)

    result: list[dict[str, Any]] = []
    base_size = clamp(median_h * frame_height * ratio, 0.018, 0.22)
    for frame in selected:
        if position_dynamic:
            cx = sx * frame + ix if displacement_x >= position_threshold and r2x >= 0.75 else median_x
            cy = sy * frame + iy if displacement_y >= position_threshold and r2y >= 0.75 else median_y
        else:
            cx, cy = median_x, median_y
        if size_dynamic:
            height_norm = clamp(sh * frame + ih, median_h * 0.70, median_h * 1.30)
            size = clamp(height_norm * frame_height * ratio, 0.018, 0.22)
        else:
            size = base_size
        result.append(
            {
                "timeline_frame": int(frame),
                "position_top_origin": [round(clamp(cx, 0.0, 1.0), 6), round(clamp(cy, 0.0, 1.0), 6)],
                "position_fusion": [round(clamp(cx, 0.0, 1.0), 6), round(clamp(1.0 - cy, 0.0, 1.0), 6)],
                "application_size_candidate": round(float(size), 12),
                "size_scale": round(float(size) / max(base_size, 1e-9), 6),
                "opacity_factor": 1.0,
            }
        )
    metrics = {
        "position_model": "source_linear_motion" if position_dynamic else "source_static_hold",
        "size_model": "source_linear_scale" if size_dynamic else "source_static_hold",
        "opacity_model": "hold_no_synthetic_flicker",
        "semantic_observation_count": len(observations),
        "median_bbox_height_norm": round(median_h, 8),
        "position_r2": [round(r2x, 6), round(r2y, 6)],
        "size_r2": round(r2h, 6),
        "displacement_norm": [round(displacement_x, 8), round(displacement_y, 8)],
        "height_change_norm": round(height_change, 8),
    }
    return result, metrics


def sample_semantic_fill(cap: Any, core: Any, coverage_row: Mapping[str, Any], frame_width: int, frame_height: int) -> dict[str, Any]:
    import cv2  # imported lazily so pure unit tests can import this module without OpenCV

    samples: list[dict[str, Any]] = []
    for observation in coverage_row.get("semantic_observations") or []:
        source_frame = int(observation.get("source_frame") or -1)
        bbox = [float(v) for v in observation.get("normalized_bbox") or []]
        if source_frame < 0 or len(bbox) != 4:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, source_frame)
        ok, frame = cap.read()
        if not ok or frame is None:
            continue
        pixel_bbox = [bbox[0] * frame_width, bbox[1] * frame_height, bbox[2] * frame_width, bbox[3] * frame_height]
        fill_hex, confidence = core.sample_fill_hex(frame, pixel_bbox)
        if fill_hex:
            samples.append({"source_frame": source_frame, "hex": fill_hex.lower(), "confidence": float(confidence)})
    choice = robust_fill_choice(samples)
    choice["source"] = "semantic_ocr_bbox_source_glyph_pixels"
    choice["samples"] = samples
    return choice


def validate_document(document: Mapping[str, Any]) -> dict[str, Any]:
    summary = document.get("summary") if isinstance(document.get("summary"), Mapping) else {}
    repair = [row for row in document.get("repair_instances") or [] if isinstance(row, Mapping)]
    unresolved = [row for row in document.get("preserve_unresolved") or [] if isinstance(row, Mapping)]
    composite = [row for row in document.get("remove_composite_structural") or [] if isinstance(row, Mapping)]
    protected = [row for row in document.get("protected_v4") or [] if isinstance(row, Mapping)]
    repair_names = [str(row.get("target_name") or "") for row in repair]
    structural_other = [str(row.get("target_name") or "") for row in unresolved + composite]
    frame_rows = sum(int(row.get("explicit_frame_row_count") or 0) for row in repair)
    checks = {
        "task_identity": document.get("task_id") == TASK_ID,
        "repair_count": len(repair) == EXPECTED_REPAIR,
        "repair_unique": len(set(repair_names)) == EXPECTED_REPAIR and all(repair_names),
        "existing_plus_new": summary.get("existing_source_confirmed") == EXPECTED_EXISTING_CONFIRMED and summary.get("new_semantic_source_confirmed") == EXPECTED_NEW_CONFIRMED,
        "unresolved_count": len(unresolved) == EXPECTED_UNRESOLVED,
        "composite_structural_count": len(composite) == EXPECTED_COMPOSITE_STRUCTURAL,
        "protected_count": len(protected) == EXPECTED_PROTECTED,
        "structural_partition": len(repair) + len(unresolved) + len(composite) == EXPECTED_STRUCTURAL,
        "scope_disjoint": not (set(repair_names) & set(structural_other)) and len(set(structural_other)) == len(structural_other),
        "dense_paths": all(
            [int(frame["timeline_frame"]) for frame in row.get("frame_path") or []]
            == list(range(int(row["visual_window"][0]), int(row["visual_window"][1])))
            and int(row.get("explicit_frame_row_count") or 0) == len(row.get("frame_path") or [])
            for row in repair
        ),
        "no_synthetic_opacity": all(all(float(frame.get("opacity_factor") or 0.0) == 1.0 for frame in row.get("frame_path") or []) for row in repair),
        "frame_rows_match": summary.get("explicit_repair_frame_rows") == frame_rows and frame_rows > 0,
        "physical_textplus_target": summary.get("expected_physical_textplus_count") == EXPECTED_PHYSICAL_TEXTPLUS,
        "transcript_timing_false": document.get("policy", {}).get("transcript_timing_authority") is False,
        "unresolved_excluded": document.get("policy", {}).get("unresolved_rows_receive_repair_geometry") is False,
        "composite_not_recreated": document.get("policy", {}).get("composite_structural_rows_recreated") is False,
        "fade_deferred": document.get("policy", {}).get("fade_polish_deferred") is True,
        "resolve_unmodified": document.get("policy", {}).get("resolve_modified") is False,
        "rollout_locked": document.get("policy", {}).get("repair_rollout_authorized") is False,
    }
    return {"checks": checks, "ok": all(checks.values()), "explicit_repair_frame_rows": frame_rows}


def build(repo_root: Path, output_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    universal_path = repo_root / UNIVERSAL
    semantic_path = repo_root / SEMANTIC
    for path in (universal_path, repo_root / UNIVERSAL_VALIDATION, semantic_path, repo_root / SEMANTIC_VALIDATION, repo_root / CORE):
        require(path.is_file(), f"missing_input:{path}")
    universal = load_json(universal_path)
    universal_validation = load_json(repo_root / UNIVERSAL_VALIDATION)
    semantic = load_json(semantic_path)
    semantic_validation = load_json(repo_root / SEMANTIC_VALIDATION)
    require(universal.get("ok") is True and universal_validation.get("ok") is True, "universal_not_valid")
    require(semantic.get("ok") is True and semantic_validation.get("ok") is True, "semantic_not_valid")
    require((universal.get("summary") or {}).get("total_instances") == EXPECTED_TOTAL, "universal_total")
    require((universal.get("summary") or {}).get("source_confirmed_repair_instances") == EXPECTED_EXISTING_CONFIRMED, "universal_confirmed")
    require((semantic.get("summary") or {}).get("source_confirmed_instances") == EXPECTED_NEW_CONFIRMED, "semantic_confirmed")
    require((semantic.get("summary") or {}).get("source_unresolved_instances") == EXPECTED_UNRESOLVED, "semantic_unresolved")
    require((semantic.get("summary") or {}).get("source_absent_or_nonsemantic_instances") == EXPECTED_COMPOSITE_STRUCTURAL, "semantic_composite")
    require(universal.get("policy", {}).get("transcript_timing_authority") is False, "universal_transcript")
    require(semantic.get("policy", {}).get("transcript_timing_authority") is False, "semantic_transcript")

    universal_rows = [row for row in universal.get("instances") or [] if isinstance(row, Mapping)]
    universal_map = {str(row.get("instance_id") or ""): row for row in universal_rows}
    existing_rows = [row for row in universal_rows if row.get("presence_status") == "source_confirmed" and row.get("repair_action") == "repair_from_source_evidence"]
    protected_rows = [row for row in universal_rows if row.get("presence_status") == "protected_existing" and row.get("repair_action") == "preserve_existing"]
    require(len(existing_rows) == EXPECTED_EXISTING_CONFIRMED, "existing_rows")
    require(len(protected_rows) == EXPECTED_PROTECTED, "protected_rows")

    coverage_rows = [row for row in semantic.get("coverage") or [] if isinstance(row, Mapping)]
    new_rows = [row for row in coverage_rows if row.get("coverage_status") == "source_confirmed"]
    unresolved_rows = [row for row in coverage_rows if row.get("coverage_status") == "source_unresolved"]
    composite_rows = [row for row in coverage_rows if row.get("coverage_status") == "source_absent_or_nonsemantic"]
    require(len(new_rows) == EXPECTED_NEW_CONFIRMED, "new_rows")
    require(len(unresolved_rows) == EXPECTED_UNRESOLVED, "unresolved_rows")
    require(len(composite_rows) == EXPECTED_COMPOSITE_STRUCTURAL, "composite_rows")

    source_info = semantic.get("inputs", {}).get("source_video") if isinstance(semantic.get("inputs", {}).get("source_video"), Mapping) else {}
    source_rel = Path(str(source_info.get("path") or "input/DZsqH7auhjt.mp4").replace("\\", "/"))
    source_path = repo_root / source_rel
    require(source_path.is_file(), f"source_video:{source_path}")
    if source_info.get("sha256"):
        require(sha256(source_path) == str(source_info["sha256"]), "source_video_sha256")

    import cv2

    cap = cv2.VideoCapture(str(source_path))
    require(cap.isOpened(), "source_video_open")
    frame_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    frame_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    require(frame_width > 0 and frame_height > 0, "source_video_dimensions")
    core = load_core(repo_root)
    calibration = universal.get("calibration") if isinstance(universal.get("calibration"), Mapping) else {}

    repair_instances: list[dict[str, Any]] = []
    try:
        for row in existing_rows:
            frame_path = [dict(frame) for frame in row.get("frame_path") or []]
            require(bool(frame_path), f"existing_path:{row.get('instance_id')}")
            style = dict(row.get("style") or {})
            repair_instances.append(
                {
                    "instance_id": str(row["instance_id"]),
                    "target_name": str(row["target_name"]),
                    "canonical_text": str(row.get("canonical_text") or ""),
                    "authority_source": "universal_source_confirmed",
                    "visual_window": [int(v) for v in row.get("visual_window") or []],
                    "frame_path": frame_path,
                    "explicit_frame_row_count": len(frame_path),
                    "motion": dict(row.get("motion") or {}),
                    "font": {"font_family": str(style.get("font_family") or ""), "font_style": str(style.get("font_style") or "")},
                    "fill_repair": existing_fill_repair(style),
                    "source_cue_ids": [str(v) for v in row.get("source_cue_ids") or []],
                    "transcript_timing_authority": False,
                }
            )
        for coverage_row in new_rows:
            instance_id = str(coverage_row.get("instance_id") or "")
            source_row = universal_map.get(instance_id)
            require(isinstance(source_row, Mapping), f"new_missing_universal:{instance_id}")
            frame_path, motion = semantic_geometry_path(coverage_row, source_row, frame_height, calibration)
            style = source_row.get("style") if isinstance(source_row.get("style"), Mapping) else {}
            fill_repair = sample_semantic_fill(cap, core, coverage_row, frame_width, frame_height)
            repair_instances.append(
                {
                    "instance_id": instance_id,
                    "target_name": str(coverage_row.get("target_name") or ""),
                    "canonical_text": str(coverage_row.get("canonical_text") or ""),
                    "authority_source": "semantic_source_confirmed_plus_source_pixel_visibility",
                    "visual_window": [int(frame_path[0]["timeline_frame"]), int(frame_path[-1]["timeline_frame"]) + 1],
                    "frame_path": frame_path,
                    "explicit_frame_row_count": len(frame_path),
                    "motion": motion,
                    "font": {"font_family": str(style.get("font_family") or ""), "font_style": str(style.get("font_style") or "")},
                    "fill_repair": fill_repair,
                    "source_cue_ids": [str(v) for v in coverage_row.get("source_cue_ids") or []],
                    "semantic_observation_count": int(coverage_row.get("semantic_observation_count") or 0),
                    "transcript_timing_authority": False,
                }
            )
    finally:
        cap.release()

    repair_instances = sorted(repair_instances, key=lambda row: str(row["instance_id"]))
    preserve_unresolved = sorted(
        [
            {
                "instance_id": str(row.get("instance_id") or ""),
                "target_name": str(row.get("target_name") or ""),
                "canonical_text": str(row.get("canonical_text") or ""),
                "reason": "semantic_source_unresolved_preserve_existing",
            }
            for row in unresolved_rows
        ],
        key=lambda row: row["instance_id"],
    )
    remove_composite = sorted(
        [
            {
                "instance_id": str(row.get("instance_id") or ""),
                "target_name": str(row.get("target_name") or ""),
                "canonical_text": str(row.get("canonical_text") or ""),
                "protected_composite": dict(row.get("protected_composite") or {}),
                "reason": "redundant_structural_row_represented_by_accepted_protected_composite",
            }
            for row in composite_rows
        ],
        key=lambda row: row["instance_id"],
    )
    protected_v4 = sorted(
        [
            {
                "instance_id": str(row.get("instance_id") or ""),
                "target_name": str(row.get("target_name") or ""),
                "canonical_text": str(row.get("canonical_text") or ""),
            }
            for row in protected_rows
        ],
        key=lambda row: row["target_name"],
    )

    frame_rows = sum(len(row["frame_path"]) for row in repair_instances)
    dynamic_position = sum(1 for row in repair_instances if (row.get("motion") or {}).get("position_model") == "source_linear_motion")
    dynamic_size = sum(1 for row in repair_instances if (row.get("motion") or {}).get("size_model") == "source_linear_scale")
    fill_override = sum(1 for row in repair_instances if (row.get("fill_repair") or {}).get("apply") is True)
    document: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "primary_authority": "source_pixels_plus_semantic_confirmation",
            "transcript_timing_authority": False,
            "geometry_only_cannot_promote_semantics": True,
            "unresolved_rows_receive_repair_geometry": False,
            "composite_structural_rows_recreated": False,
            "detector_score_used_as_opacity": False,
            "static_geometry_collapses_detector_jitter": True,
            "source_fill_override_requires_generic_evidence_gate": True,
            "fade_polish_deferred": True,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
            "per_cue_hardcoded_overrides": False,
        },
        "inputs": {
            "universal_authority": {"path": str(UNIVERSAL), "sha256": sha256(universal_path), "semantic_sha256": universal.get("semantic_sha256")},
            "universal_validation": {"path": str(UNIVERSAL_VALIDATION), "sha256": sha256(repo_root / UNIVERSAL_VALIDATION)},
            "semantic_coverage": {"path": str(SEMANTIC), "sha256": sha256(semantic_path), "semantic_sha256": semantic.get("semantic_sha256")},
            "semantic_validation": {"path": str(SEMANTIC_VALIDATION), "sha256": sha256(repo_root / SEMANTIC_VALIDATION)},
            "source_video": {"path": str(source_rel), "sha256": sha256(source_path), "width": frame_width, "height": frame_height},
        },
        "repair_instances": repair_instances,
        "preserve_unresolved": preserve_unresolved,
        "remove_composite_structural": remove_composite,
        "protected_v4": protected_v4,
        "summary": {
            "structural_rows": EXPECTED_TOTAL,
            "structural_nonprotected_rows": EXPECTED_STRUCTURAL,
            "protected_v4": EXPECTED_PROTECTED,
            "existing_source_confirmed": EXPECTED_EXISTING_CONFIRMED,
            "new_semantic_source_confirmed": EXPECTED_NEW_CONFIRMED,
            "repair_instances": len(repair_instances),
            "preserve_unresolved": len(preserve_unresolved),
            "remove_composite_structural": len(remove_composite),
            "expected_physical_textplus_count": EXPECTED_PHYSICAL_TEXTPLUS,
            "explicit_repair_frame_rows": frame_rows,
            "dynamic_position_instances": dynamic_position,
            "dynamic_size_instances": dynamic_size,
            "fill_override_instances": fill_override,
            "resolve_modified": False,
            "repair_rollout_authorized": False,
        },
        "semantic_sha256": "",
        "next_boundary": "STEP_3E_CONFIRMED74_ISOLATED_REPAIR_ROLLOUT_AFTER_AUTHORITY_VALIDATION",
    }
    validation = validate_document(document)
    require(validation["ok"], "authority_validation:" + ",".join(key for key, ok in validation["checks"].items() if not ok))
    document["semantic_sha256"] = canonical_sha256({key: value for key, value in document.items() if key != "semantic_sha256"})
    write_json(output_path, document)
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    output = args.output or (args.root / OUTPUT)
    try:
        result = build(args.root, output)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "path": str(output), "summary": result["summary"], "semantic_sha256": result["semantic_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
