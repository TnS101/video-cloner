#!/usr/bin/env python3
"""Validate universal source-visual repair authority without Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

TASK_ID = "DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1"
EXPECTED_TOTAL = 117
EXPECTED_V4 = 17
DEFAULT_AUTHORITY = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/"
    "universal_visual_repair_authority_v1.json"
)
DEFAULT_OUTPUT = Path(
    "artifacts/DZSQH7AUHJT_STEP_3E_UNIVERSAL_VISUAL_REPAIR_AUTHORITY_V1/"
    "universal_visual_repair_authority_validation.json"
)


class ValidationError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ValidationError(code)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    require(isinstance(value, dict), f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_frame_path(row: Mapping[str, Any]) -> int:
    window = row.get("visual_window")
    path = row.get("frame_path")
    require(isinstance(window, list) and len(window) == 2 and int(window[1]) > int(window[0]), f"window:{row.get('instance_id')}")
    require(isinstance(path, list) and len(path) == int(window[1]) - int(window[0]), f"dense:{row.get('instance_id')}")
    frames = [int(item.get("timeline_frame")) for item in path]
    require(frames == list(range(int(window[0]), int(window[1]))), f"frame_order:{row.get('instance_id')}")
    motion = row.get("motion") if isinstance(row.get("motion"), Mapping) else {}
    positions = []
    sizes = []
    for item in path:
        pos = item.get("position_fusion")
        require(isinstance(pos, list) and len(pos) == 2 and all(0.0 <= float(v) <= 1.0 for v in pos), "position")
        size = float(item.get("application_size_candidate") or 0.0)
        require(0.018 <= size <= 0.22, f"size_bounds:{row.get('instance_id')}:{size}")
        require(float(item.get("opacity_factor")) == 1.0, f"synthetic_opacity:{row.get('instance_id')}")
        positions.append(tuple(round(float(v), 6) for v in pos))
        sizes.append(round(size, 9))
    if motion.get("position_model") == "source_static_hold":
        require(len(set(positions)) == 1, f"static_position_not_hold:{row.get('instance_id')}")
    if motion.get("size_model") == "source_static_hold":
        require(len(set(sizes)) == 1, f"static_size_not_hold:{row.get('instance_id')}")
    require(motion.get("opacity_model") == "hold_no_synthetic_flicker", f"opacity_model:{row.get('instance_id')}")
    evidence = row.get("source_pixel_evidence") if isinstance(row.get("source_pixel_evidence"), Mapping) else {}
    require(evidence.get("peak_bbox") is not None, f"peak_bbox:{row.get('instance_id')}")
    require(float(evidence.get("peak_score") or 0.0) > 0.0, f"peak_score:{row.get('instance_id')}")
    return len(path)


def validate_instance_row(row: Mapping[str, Any]) -> tuple[str, int]:
    instance_id = str(row.get("instance_id") or "")
    require(row.get("transcript_timing_authority") is False, f"row_transcript_timing:{instance_id}")
    status = str(row.get("presence_status") or "")
    allowed = {"protected_existing", "source_confirmed", "source_unresolved", "source_not_evaluated"}
    require(status in allowed, f"presence_status:{instance_id}:{status}")
    evidence = row.get("source_pixel_evidence") if isinstance(row.get("source_pixel_evidence"), Mapping) else {}

    if status == "protected_existing":
        require(row.get("repair_action") == "preserve_existing", f"protected_action:{instance_id}")
        require(row.get("visual_timing_authority") == "approved_source_visual_authority_v4", f"protected_authority:{instance_id}")
        require(evidence.get("evidence_kind") == "approved_v4_source_visual_authority", f"protected_evidence:{instance_id}")
        require(not row.get("frame_path"), f"protected_repair_path:{instance_id}")
        return status, 0

    if status == "source_confirmed":
        require(row.get("repair_action") == "repair_from_source_evidence", f"confirmed_action:{instance_id}")
        require(row.get("visual_timing_authority") == "source_ocr_continuity_observations", f"confirmed_authority:{instance_id}")
        require(evidence.get("evidence_kind") == "ocr_continuity", f"confirmed_evidence:{instance_id}")
        require(int(evidence.get("direct_ocr_frame_count") or 0) >= 1, f"confirmed_direct_ocr:{instance_id}")
        require(int(evidence.get("dense_observation_count") or 0) >= 2, f"confirmed_dense_obs:{instance_id}")
        require(float(evidence.get("median_text_similarity") or 0.0) >= 0.62, f"confirmed_similarity:{instance_id}")
        require(float(evidence.get("median_ocr_confidence") or 0.0) >= 0.24, f"confirmed_ocr_confidence:{instance_id}")
        require(evidence.get("cue_window_coverage_used_as_authority") is False, f"confirmed_timing_leak:{instance_id}")
        return status, validate_frame_path(row)

    require(row.get("repair_action") == "exclude_from_repair", f"excluded_action:{instance_id}")
    require(row.get("visual_timing_authority") == "unresolved_source_presence", f"excluded_authority:{instance_id}")
    require(row.get("visual_window") is None, f"excluded_visual_window:{instance_id}")
    require(not row.get("frame_path"), f"excluded_repair_path:{instance_id}")
    require(evidence.get("evidence_kind") == "semantic_presence_gate", f"excluded_evidence:{instance_id}")
    semantic = evidence.get("semantic_presence") if isinstance(evidence.get("semantic_presence"), Mapping) else {}
    reasons = evidence.get("reasons")
    require(isinstance(reasons, list) and bool(reasons), f"excluded_reason:{instance_id}")
    require(semantic.get("cue_window_coverage_used_as_authority") is False, f"excluded_timing_leak:{instance_id}")
    expected_semantic = "unresolved" if status == "source_unresolved" else "not_evaluated"
    require(semantic.get("status") == expected_semantic, f"excluded_semantic_status:{instance_id}")
    return status, 0


def validate(repo_root: Path, authority_path: Path) -> dict[str, Any]:
    authority = load_json(authority_path)
    require(authority.get("task_id") == TASK_ID and authority.get("ok") is True, "identity")
    require(int(authority.get("schema_version") or 0) == 2, "schema_version")
    policy = authority.get("policy") if isinstance(authority.get("policy"), Mapping) else {}
    require(policy.get("core_is_reel_agnostic") is True, "reel_agnostic")
    require(policy.get("primary_authority") == "source_video_pixels", "primary_authority")
    require(policy.get("transcript_timing_authority") is False, "transcript_timing")
    require(policy.get("raw_detector_score_controls_opacity") is False, "raw_opacity")
    require(policy.get("static_source_motion_collapses_to_hold") is True, "static_hold")
    require(policy.get("per_cue_hardcoded_overrides") is False, "hardcoded_overrides")
    require(policy.get("structural_caption_count_requires_positive_visual_presence") is False, "structural_presence_contract")
    require(policy.get("unresolved_source_presence_is_valid") is True, "unresolved_contract")
    require(policy.get("geometry_only_cannot_authorize_repair") is True, "geometry_semantic_gate")
    require(policy.get("approved_v4_authority_is_preserved") is True, "v4_preserved")
    require(policy.get("resolve_modified") is False and policy.get("repair_rollout_authorized") is False, "mutation_lock")

    rows = authority.get("instances")
    require(isinstance(rows, list) and len(rows) == EXPECTED_TOTAL, f"instance_count:{len(rows) if isinstance(rows, list) else -1}")
    names = [str(row.get("target_name") or "") for row in rows]
    require(all(names) and len(set(names)) == EXPECTED_TOTAL, "target_identity")

    counts = {name: 0 for name in ("protected_existing", "source_confirmed", "source_unresolved", "source_not_evaluated")}
    total_frames = 0
    for row in rows:
        status, frame_count = validate_instance_row(row)
        counts[status] += 1
        total_frames += frame_count

    require(counts["protected_existing"] == EXPECTED_V4, "protected_v4_count")
    require(sum(counts.values()) == EXPECTED_TOTAL, "presence_partition")
    require(counts["source_unresolved"] + counts["source_not_evaluated"] > 0, "unexpected_full_repair_authority")

    summary = authority.get("summary") if isinstance(authority.get("summary"), Mapping) else {}
    require(int(summary.get("total_instances") or 0) == EXPECTED_TOTAL, "summary_total")
    require(int(summary.get("protected_existing_instances") or 0) == counts["protected_existing"], "summary_protected")
    require(int(summary.get("source_confirmed_repair_instances") or 0) == counts["source_confirmed"], "summary_confirmed")
    require(int(summary.get("source_unresolved_instances") or 0) == counts["source_unresolved"], "summary_unresolved")
    require(int(summary.get("source_not_evaluated_instances") or 0) == counts["source_not_evaluated"], "summary_not_evaluated")
    require(int(summary.get("repair_ready_instances") or 0) == counts["source_confirmed"], "summary_repair_ready")
    require(int(summary.get("hold_opacity_instances") or 0) == counts["source_confirmed"], "summary_hold_opacity")
    require(summary.get("resolve_modified") is False and summary.get("repair_rollout_authorized") is False, "summary_mutation_lock")
    expected_hash = canonical_sha256({k: v for k, v in authority.items() if k != "semantic_sha256"})
    require(authority.get("semantic_sha256") == expected_hash, "semantic_sha256")

    return {
        "schema_version": 2,
        "task_id": TASK_ID,
        "ok": True,
        "authority_path": str(authority_path.relative_to(repo_root)),
        "checks": {
            "all_117_structural_rows_accounted": True,
            "positive_visual_presence_not_forced": True,
            "source_confirmed_rows_have_semantic_ocr_evidence": True,
            "cue_window_coverage_not_timing_authority": True,
            "unconfirmed_rows_excluded_from_repair": True,
            "geometry_only_not_run_as_authority": True,
            "protected_v4_preserved": True,
            "static_motion_collapsed_for_repair_rows": True,
            "raw_pixel_score_not_used_as_opacity": True,
            "no_per_cue_hardcoded_overrides": True,
            "transcript_timing_false": True,
            "resolve_modified_false": True,
            "repair_rollout_unauthorized": True,
            "semantic_hash_valid": True,
        },
        "counts": {
            "instances": EXPECTED_TOTAL,
            "protected_existing": counts["protected_existing"],
            "source_confirmed_repair": counts["source_confirmed"],
            "source_unresolved": counts["source_unresolved"],
            "source_not_evaluated": counts["source_not_evaluated"],
            "explicit_repair_frame_rows": total_frames,
            "static_position_instances": int(summary.get("static_position_instances") or 0),
            "dynamic_position_instances": int(summary.get("dynamic_position_instances") or 0),
            "static_size_instances": int(summary.get("static_size_instances") or 0),
            "dynamic_size_instances": int(summary.get("dynamic_size_instances") or 0),
            "composite_text_reconciled_count": int(summary.get("composite_text_reconciled_count") or 0),
        },
        "next_boundary": "STEP_3E_EXPAND_SOURCE_SEMANTIC_COVERAGE_BEFORE_REPAIR_ROLLOUT",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--authority", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    authority = args.authority.resolve() if args.authority else root / DEFAULT_AUTHORITY
    output = args.output.resolve() if args.output else root / DEFAULT_OUTPUT
    try:
        result = validate(root, authority)
        write_json(output, result)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL {TASK_ID}: {type(exc).__name__}: {exc}")
        return 1
    print(
        f"PASS {TASK_ID}: instances={result['counts']['instances']} "
        f"confirmed={result['counts']['source_confirmed_repair']} "
        f"unresolved={result['counts']['source_unresolved']} "
        f"not_evaluated={result['counts']['source_not_evaluated']}"
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
