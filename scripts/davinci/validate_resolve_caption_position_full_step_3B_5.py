#!/usr/bin/env python3
"""Validate Major Step 3B.5B Resolve first/idempotent reports."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

VERSION = "validate_resolve_caption_position_full_step_3B_5B_v1_0"
WORKSPACE_VERSION = "resolve_caption_position_step_3B_5B_v1_0_full_source_position_rollout"


def load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def canonical_hash(value: Dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--mode", choices=("first_application_pass", "idempotent_second_run"), required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    plan_path = Path(args.plan).resolve()
    report_path = Path(args.report).resolve()
    output_path = Path(args.output).resolve()
    failures: List[str] = []
    try:
        plan = load_json(plan_path)
        report = load_json(report_path)
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.5B", "validator_version": VERSION, "mode": args.mode, "failures": [f"load_failed:{type(exc).__name__}:{exc}"]}
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 1

    expected_run_mode = "first_application" if args.mode == "first_application_pass" else "idempotent_second_run"
    summary = report.get("summary") or {}
    checks = {
        "plan_ok": bool(plan.get("ok")),
        "plan_hash_valid": plan.get("plan_hash") == canonical_hash(plan),
        "report_ok": bool(report.get("ok")),
        "workspace_version": report.get("workspace_version") == WORKSPACE_VERSION,
        "report_run_mode": report.get("run_mode") == expected_run_mode,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "v3_candidate_count": int(summary.get("v3_candidate_count") or 0) == 116,
        "plan_item_count": int(summary.get("plan_item_count") or 0) == 116,
        "rollout_target_count": int(summary.get("rollout_target_count") or 0) == 116,
        "direct_event_count": int(summary.get("direct_event_position_count") or 0) == 66,
        "near_group_count": int(summary.get("near_group_position_count") or 0) == 33,
        "interpolated_count": int(summary.get("interpolated_position_count") or 0) == 16,
        "nearest_event_count": int(summary.get("nearest_event_position_count") or 0) == 1,
        "mapped_count": int(summary.get("mapped_count") or 0) == 116,
        "position_requested_count": int(summary.get("position_requested_count") or 0) == 116,
        "position_verified_count": int(summary.get("position_verified_count") or 0) == 116,
        "static_position_count": int(summary.get("static_position_count") or 0) == 112,
        "static_position_verified": int(summary.get("static_position_verified_count") or 0) == 112,
        "translated_caption_count": int(summary.get("translated_center_animation_caption_count") or 0) == 4,
        "translated_caption_verified": int(summary.get("translated_center_animation_verified_count") or 0) == 4,
        "translated_keyframe_count": int(summary.get("translated_center_keyframe_count") or 0) == 8,
        "translated_keyframe_verified": int(summary.get("translated_center_keyframe_verified_count") or 0) == 8,
        "source_direct_verified": int(summary.get("direct_event_position_verified_count") or 0) == 66,
        "source_near_verified": int(summary.get("near_group_position_verified_count") or 0) == 33,
        "source_interpolated_verified": int(summary.get("interpolated_position_verified_count") or 0) == 16,
        "source_nearest_verified": int(summary.get("nearest_event_position_verified_count") or 0) == 1,
        "fill_preserved": int(summary.get("protected_fill_verified_count") or 0) == 116,
        "effects_preserved": int(summary.get("protected_effect_verified_count") or 0) == 116,
        "size_preserved": int(summary.get("protected_size_verified_count") or 0) == 116,
        "identity_preserved": int(summary.get("protected_identity_verified_count") or 0) == 116,
        "layout_preserved": int(summary.get("protected_layout_verified_count") or 0) == 116,
        "animation_target_count": int(summary.get("expected_animation_target_count") or 0) == 16,
        "animation_targets_verified": int(summary.get("expected_animation_target_verified_count") or 0) == 16,
        "identity_integrity": int(summary.get("identity_integrity_failure_count") or 0) == 0,
        "style_integrity": int(summary.get("style_integrity_failure_count") or 0) == 0,
        "layout_integrity": int(summary.get("layout_integrity_failure_count") or 0) == 0,
        "animation_integrity": int(summary.get("animation_integrity_failure_count") or 0) == 0,
        "timeline_integrity": int(summary.get("timeline_integrity_failure_count") or 0) == 0,
        "rollback_not_performed": int(summary.get("rollback_performed_count") or 0) == 0,
        "failed_count": int(summary.get("failed_count") or 0) == 0,
        "track_integrity": bool((report.get("track_integrity") or {}).get("ok")),
        "v3_track_integrity": bool((report.get("v3_track_integrity") or {}).get("ok")),
        "no_report_failures": not report.get("failures"),
        "all_items_accounted": int(summary.get("modified_count") or 0) + int(summary.get("already_correct_count") or 0) == 116,
    }
    if args.mode == "first_application_pass":
        checks["first_run_has_modifications"] = int(summary.get("modified_count") or 0) > 0
        checks["accepted_probe_already_correct"] = int(summary.get("already_correct_count") or 0) >= 1
    else:
        checks["second_run_modified_count"] = int(summary.get("modified_count") or 0) == 0
        checks["second_run_already_correct_count"] = int(summary.get("already_correct_count") or 0) == 116

    failures.extend(key for key, passed in checks.items() if not passed)
    payload = {
        "ok": not failures,
        "step": "Major Step 3B.5B",
        "validator_version": VERSION,
        "mode": args.mode,
        "plan": str(plan_path),
        "report": str(report_path),
        "summary": summary,
        "checks": checks,
        "warnings": report.get("warnings") or [],
        "failures": failures,
        "output": str(output_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
