#!/usr/bin/env python3
"""Validate the dedicated read-only Step 3B.6C idempotency evidence run."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

VERSION = "validate_caption_source_geometry_step_3B_6C_idempotency_evidence_regeneration_v1_0"
COMPATIBLE_VALIDATOR_VERSION = "validate_resolve_caption_source_geometry_probe_step_3B_6C_v1_0"
WORKSPACE_VERSION = "resolve_read_caption_source_geometry_step_3B_6C_idempotency_evidence_v1_0"
TASK_ID = "DZSQH7AUHJT_STEP_3B_6C_IDEMPOTENCY_EVIDENCE_REGENERATION_V1"


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def same_path(value: Any, expected: Path) -> bool:
    return isinstance(value, str) and bool(value) and Path(value).resolve() == expected.resolve()


def validate(plan: dict[str, Any], report: dict[str, Any], plan_path: Path, report_path: Path, run_id: str) -> dict[str, Any]:
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    targets = report.get("targets_after") if isinstance(report.get("targets_after"), list) else []
    artifact_keys = ("pre_state_path", "post_state_path", "comparison_path", "no_effective_change_path")
    artifacts: dict[str, Any] = {}
    for key in artifact_keys:
        path = Path(str(report.get(key) or ""))
        artifacts[key] = load_json(path) if path.is_file() else None
    comparison = artifacts["comparison_path"] or {}
    pre_state, post_state = artifacts["pre_state_path"], artifacts["post_state_path"]
    checks = {
        "plan_ok": plan.get("ok") is True,
        "plan_hash_match": report.get("plan_hash") == plan.get("plan_hash"),
        "report_ok": report.get("ok") is True and not report.get("failures"),
        "task_id": report.get("task_id") == TASK_ID,
        "run_id": report.get("run_id") == run_id,
        "workspace_version": report.get("workspace_version") == WORKSPACE_VERSION,
        "run_mode": report.get("run_mode") == "idempotent_second_run",
        "video": report.get("video_id") == "DZsqH7auhjt",
        "project": report.get("project_name") == "New Project 1",
        "timeline": report.get("timeline_name") == "DZsqH7auhjt_textplus_full",
        "track": report.get("track_type") == "video" and int(report.get("track_index") or 0) == 3,
        "cue": report.get("probe_cue_id") == "sub_114" and report.get("probe_text") == "AND" and report.get("probe_name") == "VC_TEXTPLUS_0114_sub_114",
        "timing": (report.get("probe_visibility") or {}).get("timeline_item_start") == 888 and (report.get("probe_visibility") or {}).get("timeline_item_end") == 894,
        "resolve_connected": report.get("resolve_connected") is True,
        "unique_target": report.get("target_resolved_uniquely") is True,
        "persistent_match": report.get("persistent_state_matched") is True,
        "target_count": len(targets) == 12 and int(summary.get("target_key_verified_count") or 0) == 12,
        "property_set": sorted({row.get("input") for row in targets}) == ["Center", "Size"],
        "all_targets_present": bool(targets) and all(row.get("present") is True and row.get("matched") is True for row in targets),
        "zero_effective_mutations": int(report.get("effective_mutation_count", -1)) == 0 and int(summary.get("modified_count", -1)) == 0,
        "all_operations_skipped": int(report.get("expected_operation_count") or 0) == 12 and int(report.get("compared_operation_count") or 0) == 12 and int(report.get("skipped_operation_count") or 0) == 12,
        "zero_setters": int(report.get("setter_call_count", -1)) == 0 and int(report.get("center_setter_call_count", -1)) == 0 and int(report.get("size_setter_call_count", -1)) == 0,
        "no_blend": int(report.get("blend_operation_count", -1)) == 0 and all(row.get("input") != "Blend" for row in targets),
        "timeline_unmodified": report.get("timeline_modified") is False,
        "track_integrity": (report.get("track_integrity") or {}).get("ok") is True,
        "v3_integrity": (report.get("v3_track_integrity") or {}).get("ok") is True and int(summary.get("v3_candidate_count") or 0) == 116,
        "pre_post_equal": report.get("pre_post_semantically_identical") is True and pre_state is not None and pre_state == post_state,
        "comparison_ok": comparison.get("ok") is True and int(comparison.get("effective_mutation_count", -1)) == 0 and int(comparison.get("setter_call_count", -1)) == 0 and int(comparison.get("blend_operation_count", -1)) == 0,
        "artifact_run_ids": all((payload or {}).get("run_id") == run_id for payload in artifacts.values()),
        "report_binding": same_path(report.get("plan_path"), plan_path),
    }
    failures = [name for name, passed in checks.items() if not passed]
    return {"ok": not failures, "step": "Major Step 3B.6C", "validator_version": COMPATIBLE_VALIDATOR_VERSION, "evidence_regeneration_validator_version": VERSION, "mode": "idempotent_second_run", "task_id": TASK_ID, "run_id": run_id, "probe_scene_id": report.get("probe_scene_id"), "probe_cue_id": report.get("probe_cue_id"), "summary": summary, "checks": checks, "failures": failures, "plan": str(plan_path.resolve()), "report": str(report_path.resolve())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    try:
        payload = validate(load_json(args.plan.resolve()), load_json(args.report.resolve()), args.plan.resolve(), args.report.resolve(), args.run_id)
    except Exception as exc:
        payload = {"ok": False, "step": "Major Step 3B.6C", "validator_version": COMPATIBLE_VALIDATOR_VERSION, "evidence_regeneration_validator_version": VERSION, "mode": "idempotent_second_run", "task_id": TASK_ID, "run_id": args.run_id, "failures": ["validator_exception"], "exception": f"{type(exc).__name__}: {exc}", "plan": str(args.plan.resolve()), "report": str(args.report.resolve())}
    payload["output"] = str(output)
    write_json(output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
