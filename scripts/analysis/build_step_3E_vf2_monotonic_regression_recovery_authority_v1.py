#!/usr/bin/env python3
"""Build a monotonic Visual Fidelity V2 regression-recovery authority.

This authority deliberately starts from the last visually superior post-metrics
timeline. It does not consume the failed V2 target as a source. It authorizes
only three source-backed changes:
1) one generic sparse-short-anchor quarantine removal,
2) Center-only recovery for 13 semantic rows plus one visual companion, and
3) the three already-approved protected exit Center trajectories.

Every other Text+ property remains baseline-preserved. No Size, Fill, case,
opacity, clip-range, track, font, outline, shadow, or layout mutation is
authorized here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping, Sequence

TASK_ID = "DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1"
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_VF2_MONOTONIC_REGRESSION_RECOVERY_AUTHORITY_V1/"
    "vf2_monotonic_regression_recovery_authority_v1.json"
)
ROLLOUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_V2_RESOLVE_ROLLOUT_AUTHORITY_V1/"
    "visual_fidelity_v2_resolve_rollout_authority_v1.json"
)
CLASSIFICATION = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_SOURCE_CLASSIFICATION_V1/"
    "unresolved_source_classification_v1.json"
)
FINAL_AUDIT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_FINAL_UNRESOLVED9_VISUAL_AUDIT_V1/"
    "final_unresolved9_visual_audit_v1.json"
)
RECOVERY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNRESOLVED_VISUAL_LAYER_RECOVERY_V1/"
    "unresolved_visual_layer_recovery_v1.json"
)
VF2 = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_VISUAL_FIDELITY_AUTHORITY_V2/"
    "visual_fidelity_authority_v2.json"
)

EXPECTED_SOURCE_PHYSICAL = 114
EXPECTED_TARGET_PHYSICAL = 113
EXPECTED_STRUCTURAL_SOURCE = 97
EXPECTED_STRUCTURAL_TARGET = 96
EXPECTED_PROTECTED = 17
EXPECTED_RECOVERED_CENTER = 14
EXPECTED_PROTECTED_EXITS = 3
EXPECTED_QUARANTINE = 1


class BuildError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise BuildError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise BuildError(f"expected_object:{path}")
    return value


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _canvas_candidates(normalized_bbox: Sequence[float], pixel_bbox: Sequence[float]) -> tuple[list[float], list[float]]:
    if len(normalized_bbox) != 4 or len(pixel_bbox) != 4:
        return [], []
    widths: list[float] = []
    heights: list[float] = []
    for n, p in zip((normalized_bbox[0], normalized_bbox[2]), (pixel_bbox[0], pixel_bbox[2])):
        n = float(n); p = float(p)
        if abs(n) > 0.05 and p > 0:
            widths.append(p / n)
    for n, p in zip((normalized_bbox[1], normalized_bbox[3]), (pixel_bbox[1], pixel_bbox[3])):
        n = float(n); p = float(p)
        if abs(n) > 0.05 and p > 0:
            heights.append(p / n)
    return widths, heights


def infer_reference_canvas(classification: Mapping[str, Any], final_audit: Mapping[str, Any]) -> dict[str, Any]:
    """Infer the detector reference canvas from pixel bboxes + normalized OCR bboxes.

    The prior rollout incorrectly assumed the original 1080x1920 source size even
    though recovered tracking bboxes were measured on the detector's downscaled
    reference canvas. Infer that canvas from evidence instead of hard-coding a
    video resolution.
    """
    width_candidates: list[float] = []
    height_candidates: list[float] = []
    evidence_rows = 0

    for row in classification.get("classifications") or []:
        if not isinstance(row, Mapping) or row.get("classification") != "source_semantic_track_recovered":
            continue
        anchor = row.get("exact_source_ocr_anchor") or {}
        tracking = row.get("source_pixel_tracking") or {}
        normalized = anchor.get("normalized_bbox") or []
        pixel = tracking.get("anchor_bbox_ref") or []
        wc, hc = _canvas_candidates(normalized, pixel)
        if wc and hc:
            width_candidates.extend(wc); height_candidates.extend(hc); evidence_rows += 1

    for row in final_audit.get("audits") or []:
        if not isinstance(row, Mapping) or row.get("classification") != "recovered_semantic":
            continue
        tracking = row.get("source_pixel_tracking") or {}
        anchor_frame = int(tracking.get("anchor_frame") or -1)
        anchor_bbox = tracking.get("anchor_bbox_ref") or []
        observations = [
            x for x in (row.get("semantic_observations") or [])
            if isinstance(x, Mapping) and int(x.get("timeline_frame") or -2) == anchor_frame
        ]
        if not observations:
            observations = [x for x in (row.get("semantic_observations") or []) if isinstance(x, Mapping)]
        if observations:
            wc, hc = _canvas_candidates(observations[0].get("normalized_bbox") or [], anchor_bbox)
            if wc and hc:
                width_candidates.extend(wc); height_candidates.extend(hc); evidence_rows += 1

    require(evidence_rows >= 5, f"canvas_evidence_rows:{evidence_rows}")
    width = float(median(width_candidates))
    height = float(median(height_candidates))
    require(width > 100 and height > 100, "canvas_geometry")
    # Cross-row consistency is a hard evidence gate.
    width_dev = max(abs(v - width) / width for v in width_candidates)
    height_dev = max(abs(v - height) / height for v in height_candidates)
    require(width_dev <= 0.035 and height_dev <= 0.035, f"canvas_consistency:{width_dev:.6f}:{height_dev:.6f}")
    return {
        "width": round(width, 6),
        "height": round(height, 6),
        "evidence_rows": evidence_rows,
        "width_candidate_count": len(width_candidates),
        "height_candidate_count": len(height_candidates),
        "max_relative_width_deviation": round(width_dev, 8),
        "max_relative_height_deviation": round(height_dev, 8),
        "basis": "pixel_bbox_divided_by_same_frame_normalized_ocr_bbox",
    }


def bbox_center_fusion(bbox: Sequence[float], canvas: Mapping[str, Any]) -> list[float]:
    require(len(bbox) == 4, "bbox")
    x0, y0, x1, y1 = [float(v) for v in bbox]
    require(x1 > x0 and y1 > y0, "bbox_geometry")
    width = float(canvas["width"]); height = float(canvas["height"])
    result = [((x0 + x1) * 0.5) / width, 1.0 - (((y0 + y1) * 0.5) / height)]
    require(all(0.0 <= v <= 1.0 for v in result), f"center_range:{result}")
    return [round(v, 6) for v in result]


def median_center(rows: Sequence[Mapping[str, Any]], canvas: Mapping[str, Any]) -> list[float]:
    centers = [
        bbox_center_fusion(row.get("source_bbox_ref") or row.get("bbox_ref") or [], canvas)
        for row in rows
    ]
    require(bool(centers), "center_rows")
    return [round(float(median([v[0] for v in centers])), 6), round(float(median([v[1] for v in centers])), 6)]


def _legacy_median_center(plan: Mapping[str, Any]) -> list[float]:
    vals = [x.get("value") for x in (plan.get("position_keys") or []) if isinstance(x, Mapping)]
    vals = [v for v in vals if isinstance(v, list) and len(v) == 2]
    require(bool(vals), f"legacy_center:{plan.get('instance_id')}")
    return [round(float(median([float(v[0]) for v in vals])), 6), round(float(median([float(v[1]) for v in vals])), 6)]


def build(root: Path, output: Path) -> dict[str, Any]:
    root = root.resolve()
    for rel in (ROLLOUT, CLASSIFICATION, FINAL_AUDIT, RECOVERY, VF2):
        require((root / rel).is_file(), f"missing:{rel}")

    rollout = load_json(root / ROLLOUT)
    classification = load_json(root / CLASSIFICATION)
    final_audit = load_json(root / FINAL_AUDIT)
    recovery = load_json(root / RECOVERY)
    vf2 = load_json(root / VF2)

    require(rollout.get("ok") is True, "rollout_authority")
    require(classification.get("ok") is True, "classification")
    require(final_audit.get("ok") is True, "final_audit")
    require(recovery.get("ok") is True, "recovery")
    require(vf2.get("ok") is True, "vf2")

    canvas = infer_reference_canvas(classification, final_audit)
    # The old faulty authority normalized the exact same pixel-space rows using
    # the full source resolution. Prove the inferred canvas is materially
    # different so this correction cannot silently become a no-op.
    rollout_plans = [dict(x) for x in rollout.get("recreate_plans") or [] if isinstance(x, Mapping)]
    by_instance = {str(x.get("instance_id") or ""): x for x in rollout_plans}

    recovered_rows: list[dict[str, Any]] = []

    for row in classification.get("classifications") or []:
        if not isinstance(row, Mapping) or row.get("classification") != "source_semantic_track_recovered":
            continue
        iid = str(row.get("instance_id") or "")
        plan = by_instance.get(iid)
        require(plan is not None and str(plan.get("kind") or "").startswith("semantic_recovered_"), f"classification_plan:{iid}")
        strong = [dict(x) for x in ((row.get("source_pixel_tracking") or {}).get("strong_run") or []) if isinstance(x, Mapping)]
        center = median_center(strong, canvas)
        legacy = _legacy_median_center(plan)
        recovered_rows.append({
            "instance_id": iid,
            "target_name": str(plan["target_name"]),
            "kind": "semantic_recovered_classification",
            "center_value": center,
            "legacy_faulty_center_value": legacy,
            "source_support_frames": [int(x["timeline_frame"]) for x in strong],
            "authorized_properties": ["Center"],
        })

    for row in final_audit.get("audits") or []:
        if not isinstance(row, Mapping) or row.get("classification") != "recovered_semantic":
            continue
        iid = str(row.get("instance_id") or "")
        plan = by_instance.get(iid)
        require(plan is not None and str(plan.get("kind") or "").startswith("semantic_recovered_"), f"audit_plan:{iid}")
        strong = [dict(x) for x in ((row.get("source_pixel_tracking") or {}).get("strong_run") or []) if isinstance(x, Mapping)]
        center = median_center(strong, canvas)
        legacy = _legacy_median_center(plan)
        recovered_rows.append({
            "instance_id": iid,
            "target_name": str(plan["target_name"]),
            "kind": "semantic_recovered_final_audit",
            "center_value": center,
            "legacy_faulty_center_value": legacy,
            "source_support_frames": [int(x["timeline_frame"]) for x in strong],
            "authorized_properties": ["Center"],
        })

    companions = [
        x for x in (recovery.get("classifications") or [])
        if isinstance(x, Mapping) and x.get("classification") == "source_visual_companion_recovered"
    ]
    require(len(companions) == 1, f"companion_count:{len(companions)}")
    row = companions[0]
    iid = str(row.get("instance_id") or "")
    plan = by_instance.get(iid)
    require(plan is not None and plan.get("kind") == "visual_companion_recovered", "companion_plan")
    path = [dict(x) for x in row.get("frame_path") or [] if isinstance(x, Mapping)]
    center = median_center(path, canvas)
    legacy = _legacy_median_center(plan)
    recovered_rows.append({
        "instance_id": iid,
        "target_name": str(plan["target_name"]),
        "kind": "visual_companion_recovered",
        "center_value": center,
        "legacy_faulty_center_value": legacy,
        "source_support_frames": [int(x["timeline_frame"]) for x in path],
        "authorized_properties": ["Center"],
    })

    require(len(recovered_rows) == EXPECTED_RECOVERED_CENTER, f"recovered_center_count:{len(recovered_rows)}")
    require(len({x["target_name"] for x in recovered_rows}) == EXPECTED_RECOVERED_CENTER, "recovered_center_duplicates")
    # The old failure should be explained by a large systematic correction.
    distances = [
        math.hypot(
            float(x["center_value"][0]) - float(x["legacy_faulty_center_value"][0]),
            float(x["center_value"][1]) - float(x["legacy_faulty_center_value"][1]),
        )
        for x in recovered_rows
    ]
    require(min(distances) > 0.15, f"legacy_geometry_not_materially_wrong:{min(distances):.6f}")

    quarantine = [dict(x) for x in rollout.get("quarantine_remove") or [] if isinstance(x, Mapping)]
    exits = [dict(x) for x in rollout.get("protected_exit_updates") or [] if isinstance(x, Mapping)]
    require(len(quarantine) == EXPECTED_QUARANTINE, "quarantine_count")
    require(len(exits) == EXPECTED_PROTECTED_EXITS, "exit_count")

    structural_names = {
        str(x.get("target_name") or "") for x in rollout_plans
    } | {
        str(x.get("target_name") or "") for x in rollout.get("preserve_unresolved") or [] if isinstance(x, Mapping)
    } | {
        str(x.get("target_name") or "") for x in quarantine
    }
    require("" not in structural_names and len(structural_names) == EXPECTED_STRUCTURAL_SOURCE, f"structural_names:{len(structural_names)}")

    center_names = {x["target_name"] for x in recovered_rows}
    quarantine_names = {str(x["target_name"]) for x in quarantine}
    exit_names = {str(x["target_name"]) for x in exits}
    require(not (center_names & quarantine_names), "center_quarantine_overlap")
    # Protected target names are a Resolve-runtime inventory concern. The accepted
    # VF2 offline artifact intentionally leaves target_name blank for many
    # protected visual tokens, so do not fabricate those names here. The runtime
    # proves that all three exit targets are members of the actual 17 protected
    # items before any mutation.

    unchanged_structural = sorted(structural_names - center_names - quarantine_names)
    require(len(unchanged_structural) == 82, f"unchanged_structural:{len(unchanged_structural)}")

    result: dict[str, Any] = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "ok": True,
        "policy": {
            "source_timeline": "last_visually_superior_post_metrics_baseline",
            "failed_v2_target_may_be_used_as_source": False,
            "monotonic_non_regression": True,
            "default_property_action": "preserve",
            "authorized_mutation_properties": ["Center", "quarantine_removal"],
            "size_mutation_authorized": False,
            "fill_mutation_authorized": False,
            "case_mutation_authorized": False,
            "font_mutation_authorized": False,
            "opacity_mutation_authorized": False,
            "clip_range_mutation_authorized": False,
            "track_mutation_authorized": False,
            "layout_mutation_authorized": False,
            "occlusion_relocation_authorized": False,
            "transcript_timing_authority": False,
            "geometry_only_semantic_promotion": False,
            "visual_approval_required": True,
            "further_rollout_authorized": False,
            "resolve_modified": False,
        },
        "inputs": {
            str(rel): {"path": str(rel), "sha256": raw_sha256(root / rel)}
            for rel in (ROLLOUT, CLASSIFICATION, FINAL_AUDIT, RECOVERY, VF2)
        },
        "reference_canvas": canvas,
        "center_corrections": recovered_rows,
        "quarantine_remove": quarantine,
        "protected_exit_updates": exits,
        "unchanged_structural_target_names": unchanged_structural,
        "unchanged_protected_count": 14,
        "summary": {
            "source_physical_textplus": EXPECTED_SOURCE_PHYSICAL,
            "source_structural_textplus": EXPECTED_STRUCTURAL_SOURCE,
            "source_protected_textplus": EXPECTED_PROTECTED,
            "center_corrections": EXPECTED_RECOVERED_CENTER,
            "protected_exit_updates": EXPECTED_PROTECTED_EXITS,
            "quarantine_removed": EXPECTED_QUARANTINE,
            "unchanged_structural": len(unchanged_structural),
            "unchanged_protected": 14,
            "target_structural_textplus": EXPECTED_STRUCTURAL_TARGET,
            "target_protected_textplus": EXPECTED_PROTECTED,
            "target_physical_textplus": EXPECTED_TARGET_PHYSICAL,
            "recreated_textplus": 0,
            "size_updates": 0,
            "fill_updates": 0,
            "case_updates": 0,
            "opacity_updates": 0,
            "clip_range_updates": 0,
            "track_updates": 0,
            "occlusion_moves": 0,
            "resolve_modified": False,
            "further_rollout_authorized": False,
        },
        "semantic_sha256": "",
    }
    result["semantic_sha256"] = canonical_sha256({k: v for k, v in result.items() if k != "semantic_sha256"})
    write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or (root / DEFAULT_OUTPUT)).resolve()
    result = build(root, output)
    print(json.dumps(result["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
