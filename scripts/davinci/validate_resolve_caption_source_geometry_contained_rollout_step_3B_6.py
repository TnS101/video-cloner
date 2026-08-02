#!/usr/bin/env python3
"""Validate Major Step 3B.6D Resolve first/idempotent reports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

VERSION = "validate_resolve_caption_source_geometry_contained_rollout_step_3B_6D_v1_0"
WORKSPACE_VERSION = "resolve_apply_caption_source_geometry_contained_rollout_step_3B_6D_v1_0"
SCHEMA = "video_cloner_caption_source_geometry_contained_rollout_plan"


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
    expected_mode = "first_application" if requested_mode == "first_application_pass" else "idempotent_second_run"
    summary = report.get("summary") or {}
    plan_summary = plan.get("summary") or {}
    items_after = report.get("items_after") or []
    failures: List[str] = []
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "plan_schema": plan.get("schema") == SCHEMA,
        "plan_hash_valid": str(plan.get("plan_hash") or "") == canonical_hash(plan, ignored=("created_at_unix",)),
        "report_ok": bool(report.get("ok")),
        "workspace_version": report.get("workspace_version") == WORKSPACE_VERSION,
        "run_mode": report.get("run_mode") == expected_mode,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "v3_count": int(summary.get("v3_candidate_count") or 0) == 116,
        "accepted_count": int(summary.get("accepted_source_instance_count") or 0) == 45,
        "unresolved_count": int(summary.get("unresolved_source_instance_count") or 0) == 30,
        "timing_mismatch_excluded": int(summary.get("timing_mismatch_excluded_count") or 0) == 41,
        "rollout_count": int(summary.get("rollout_item_count") or 0) == 4,
        "mapped_count": int(summary.get("mapped_count") or 0) == 4,
        "target_count": int(summary.get("target_key_count") or 0) == 42,
        "all_targets_verified": int(summary.get("target_key_verified_count") or 0) == 42,
        "center_count": int(summary.get("center_key_count") or 0) == 18 and int(summary.get("center_key_verified_count") or 0) == 18,
        "size_count": int(summary.get("size_key_count") or 0) == 18 and int(summary.get("size_key_verified_count") or 0) == 18,
        "blend_count": int(summary.get("blend_key_count") or 0) == 6 and int(summary.get("blend_key_verified_count") or 0) == 6,
        "items_after_present": len(items_after) == 4 and all(bool(row.get("all_present")) for row in items_after),
        "non_rollout_preserved": int(summary.get("non_rollout_caption_count") or 0) == 112 and int(summary.get("non_rollout_caption_verified_count") or 0) == 112,
        "protected_animation_caption_count": int(summary.get("protected_animation_caption_count") or 0) == int(plan_summary.get("protected_animation_caption_count") or 0) == 8,
        "protected_animation_captions": int(summary.get("protected_animation_verified_count") or 0) == 8,
        "protected_animation_target_count": int(summary.get("protected_animation_target_count") or 0) == int(plan_summary.get("protected_animation_target_count") or 0) == 16,
        "protected_animation_targets": int(summary.get("protected_animation_target_verified_count") or 0) == 16,
        "opacity_proxy_not_applied": int(summary.get("opacity_proxy_applied_count") or 0) == 0,
        "binary_visibility_written": int(summary.get("binary_visibility_target_count") or 0) == 6,
        "z_order_not_written": int(summary.get("z_order_write_count") or 0) == 0,
        "boundaries_not_written": int(summary.get("timeline_boundary_write_count") or 0) == 0,
        "timeline_integrity": int(summary.get("timeline_integrity_failure_count") or 0) == 0,
        "protected_integrity": int(summary.get("protected_integrity_failure_count") or 0) == 0,
        "rollback_not_performed": int(summary.get("rollback_performed_count") or 0) == 0,
        "failed_count": int(summary.get("failed_count") or 0) == 0,
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "no_report_failures": not report.get("failures"),
        "hard_outline_forbidden": bool((plan.get("safety_contract") or {}).get("hard_outline_default_forbidden")),
    }
    if requested_mode == "first_application_pass":
        checks["first_modified"] = int(summary.get("modified_count") or 0) == 3
        checks["first_already_correct"] = int(summary.get("already_correct_count") or 0) == 1
    else:
        checks["second_modified"] = int(summary.get("modified_count") or 0) == 0
        checks["second_already_correct"] = int(summary.get("already_correct_count") or 0) == 4
    failures.extend(name for name, ok in checks.items() if not ok)
    return {
        "ok": not failures,
        "step": "Major Step 3B.6D",
        "validator_version": VERSION,
        "mode": requested_mode,
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
        payload.update({"plan": str(plan_path), "report": str(report_path), "output": str(output)})
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.6D", "validator_version": VERSION, "mode": args.mode, "failures": ["validator_exception"], "exception": f"{type(exc).__name__}: {exc}", "output": str(output)}
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
