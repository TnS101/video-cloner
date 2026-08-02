#!/usr/bin/env python3
"""Validate Major Step 3B.6C Resolve first/idempotent dense geometry probe reports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

VERSION = "validate_resolve_caption_source_geometry_probe_step_3B_6C_v1_0"
WORKSPACE_VERSION = "resolve_apply_caption_source_geometry_probe_step_3B_6C_v1_0_dense_center_size"
EXPECTED_SCHEMA = "video_cloner_caption_source_geometry_probe_plan"


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


def canonical_hash(value: Dict[str, Any], ignored: Sequence[str] = ()) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    for key in ignored:
        clean.pop(key, None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate(plan: Dict[str, Any], report: Dict[str, Any], requested_mode: str) -> Dict[str, Any]:
    expected_run_mode = "first_application" if requested_mode == "first_application_pass" else "idempotent_second_run"
    failures: List[str] = []
    summary = report.get("summary") or {}
    plan_summary = plan.get("summary") or {}
    probe = plan.get("probe") or {}

    protected_caption_count = int(plan_summary.get("protected_animation_caption_count") or 0)
    protected_target_count = int(plan_summary.get("protected_animation_target_count") or 0)
    target_after = report.get("targets_after") or []

    checks: Dict[str, bool] = {
        "plan_ok": bool(plan.get("ok")),
        "plan_schema": plan.get("schema") == EXPECTED_SCHEMA,
        "plan_hash_valid": str(plan.get("plan_hash") or "") == canonical_hash(plan, ignored=("created_at_unix",)),
        "report_ok": bool(report.get("ok")),
        "workspace_version": report.get("workspace_version") == WORKSPACE_VERSION,
        "report_run_mode": report.get("run_mode") == expected_run_mode,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "probe_scene": report.get("probe_scene_id") == "caption_scene_015",
        "probe_cue": report.get("probe_cue_id") == "sub_114",
        "probe_name": report.get("probe_name") == "VC_TEXTPLUS_0114_sub_114",
        "probe_text": report.get("probe_text") == "AND",
        "probe_contained": bool((report.get("probe_visibility") or {}).get("fully_contained_in_existing_item")),
        "v3_count": int(summary.get("v3_candidate_count") or 0) == 116,
        "scene_context_count": int(summary.get("scene_context_cue_count") or 0) == 2,
        "probe_item_count": int(summary.get("probe_item_count") or 0) == 1,
        "mapped_count": int(summary.get("mapped_count") or 0) == 1,
        "target_key_count": int(summary.get("target_key_count") or 0) == 12,
        "target_key_verified": int(summary.get("target_key_verified_count") or 0) == 12,
        "center_key_count": int(summary.get("center_key_count") or 0) == 6,
        "center_keys_verified": int(summary.get("center_key_verified_count") or 0) == 6,
        "size_key_count": int(summary.get("size_key_count") or 0) == 6,
        "size_keys_verified": int(summary.get("size_key_verified_count") or 0) == 6,
        "all_target_rows_present": len(target_after) == 12 and all(bool(row.get("present")) for row in target_after),
        "only_center_size_targets": sorted(set(str(row.get("input")) for row in target_after)) == ["Center", "Size"],
        "other_v3_count": int(summary.get("non_probe_caption_count") or 0) == 115,
        "other_v3_preserved": int(summary.get("non_probe_caption_verified_count") or 0) == 115,
        "protected_animation_caption_count": int(summary.get("protected_animation_caption_count") or 0) == protected_caption_count,
        "protected_animation_captions_preserved": int(summary.get("protected_animation_verified_count") or 0) == protected_caption_count,
        "protected_animation_target_count": int(summary.get("protected_animation_target_count") or 0) == protected_target_count,
        "protected_animation_targets_preserved": int(summary.get("protected_animation_target_verified_count") or 0) == protected_target_count,
        "timing_mismatch_context_excluded": int(summary.get("timing_mismatch_excluded_count") or 0) == 1,
        "opacity_not_applied": int(summary.get("opacity_proxy_applied_count") or 0) == 0,
        "z_order_not_written": int(summary.get("z_order_write_count") or 0) == 0,
        "timeline_boundaries_not_written": int(summary.get("timeline_boundary_write_count") or 0) == 0,
        "timeline_integrity": int(summary.get("timeline_integrity_failure_count") or 0) == 0,
        "protected_integrity": int(summary.get("protected_integrity_failure_count") or 0) == 0,
        "rollback_not_performed": int(summary.get("rollback_performed_count") or 0) == 0,
        "failed_count": int(summary.get("failed_count") or 0) == 0,
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "no_other_caption_failures": not report.get("other_caption_integrity_failures"),
        "no_report_failures": not report.get("failures"),
        "hard_outline_forbidden": bool((plan.get("safety_contract") or {}).get("hard_outline_default_forbidden")),
    }
    if requested_mode == "first_application_pass":
        checks["first_run_modified"] = int(summary.get("modified_count") or 0) == 1
        checks["first_run_not_already_correct"] = int(summary.get("already_correct_count") or 0) == 0
    else:
        checks["second_run_not_modified"] = int(summary.get("modified_count") or 0) == 0
        checks["second_run_already_correct"] = int(summary.get("already_correct_count") or 0) == 1

    failures.extend(name for name, ok in checks.items() if not ok)
    return {
        "ok": not failures,
        "step": "Major Step 3B.6C",
        "validator_version": VERSION,
        "mode": requested_mode,
        "probe_scene_id": report.get("probe_scene_id"),
        "probe_cue_id": report.get("probe_cue_id"),
        "summary": summary,
        "checks": checks,
        "warnings": report.get("warnings") or [],
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--mode", choices=("first_application_pass", "idempotent_second_run"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    output = Path(args.output).resolve()
    try:
        plan_path = Path(args.plan).resolve()
        report_path = Path(args.report).resolve()
        payload = validate(load_json(plan_path), load_json(report_path), args.mode)
        payload["plan"] = str(plan_path)
        payload["report"] = str(report_path)
        payload["output"] = str(output)
    except Exception as exc:
        payload = {
            "ok": False,
            "step": "Major Step 3B.6C",
            "validator_version": VERSION,
            "mode": args.mode,
            "failures": ["validator_exception"],
            "exception": f"{type(exc).__name__}: {exc}",
            "output": str(output),
        }
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
