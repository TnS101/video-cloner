#!/usr/bin/env python3
"""Validate immutable Step 3B.6D runtime, queue, persistence, and idempotency evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
TARGETS = {"sub_007": "While", "sub_013": "out", "sub_110": "looks", "sub_114": "AND"}
REQUIRED_JSON = (
    "runtime_command.json", "prerequisite_hash_validation.json", "status.json", "report.json",
    "accepted_plan_identity_report.json", "preflight_report.json", "four_target_pre_state_snapshot.json",
    "phase_1_mutation_manifest.json", "phase_1_persistent_post_state.json", "readback_comparison.json",
    "phase_2_idempotency_report.json", "non_target_mutation_audit.json",
    "protected_inventory_comparison.json", "four_cue_visual_review_checklist.json",
)


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"not_object:{path.name}")
    return value


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def validate(root: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    failures: list[str] = []
    values: dict[str, dict[str, Any]] = {}
    inventory = []
    for name in REQUIRED_JSON:
        path = report_dir / name
        valid = False
        try:
            values[name] = load(path)
            valid = path.stat().st_size > 0
        except Exception:
            failures.append(f"artifact:{name}")
        inventory.append({"path": str(path.relative_to(root)), "exists": path.is_file(), "non_zero": path.is_file() and path.stat().st_size > 0, "valid_json_object": valid, "sha256": sha(path) if path.is_file() else None})
    log = report_dir / "run.log"
    if not log.is_file() or log.stat().st_size == 0:
        failures.append("artifact:run.log")
    else:
        inventory.append({"path": str(log.relative_to(root)), "exists": True, "non_zero": True, "sha256": sha(log)})
    if failures:
        return {"ok": False, "inventory": inventory}, failures

    for name, value in values.items():
        if name not in {"status.json", "runtime_command.json"} and (value.get("task_id") != TASK_ID or value.get("run_id") != run_id):
            failures.append(f"identity:{name}")
    command = values["runtime_command.json"]
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("module") != "resolve_workspace/modules/step_3B_6D_runtime_execution.py":
        failures.append("command_identity")
    payload = command.get("payload") or {}
    if payload.get("plan_hash") != PLAN_HASH or payload.get("allowed_properties") != ["Center", "Size"] or payload.get("forbidden_properties") != ["Blend", "unknown_or_other"]:
        failures.append("command_contract")
    status, runtime = values["status.json"], values["report.json"]
    if status.get("run_id") != run_id or status.get("ok") is not True or status.get("running") is not False:
        failures.append("status")
    if runtime.get("ok") is not True or runtime.get("plan_hash") != PLAN_HASH or runtime.get("blend_operation_count") != 0 or runtime.get("persistent_readback_matched") is not True or runtime.get("non_target_preserved") is not True:
        failures.append("runtime_report")
    identity = values["accepted_plan_identity_report.json"]
    if identity.get("plan_hash") != PLAN_HASH or identity.get("cue_ids") != list(TARGETS) or identity.get("operation_counts") != {"Center": 18, "Size": 18, "Blend": 0, "other": 0, "total": 36}:
        failures.append("plan_identity")
    preflight = values["preflight_report.json"]
    if preflight.get("ok") is not True or preflight.get("all_targets_validated_before_first_setter") is not True or preflight.get("target_count") != 4 or preflight.get("non_target_count") != 112 or preflight.get("caption_count") != 116:
        failures.append("preflight")
    prestate = values["four_target_pre_state_snapshot.json"]
    preitems = prestate.get("items") or []
    if len(preitems) != 4 or {row.get("cue_id"): row.get("text") for row in preitems} != TARGETS or next((row for row in preitems if row.get("cue_id") == "sub_114"), {}).get("state") != "already_correct":
        failures.append("prestate")
    phase1 = values["phase_1_mutation_manifest.json"]
    operations = phase1.get("operations") or []
    if phase1.get("ok") is not True or phase1.get("blend_operation_count") != 0 or phase1.get("setter_call_count") != len(operations) or phase1.get("effective_mutation_count") != sum(1 for row in operations if row.get("ok")):
        failures.append("phase1_counts")
    if any(row.get("input") not in {"Center", "Size"} or row.get("cue_id") not in TARGETS for row in operations):
        failures.append("phase1_allowlist")
    if any(row.get("cue_id") == "sub_114" for row in operations):
        failures.append("sub_114_setter")
    readback = values["readback_comparison.json"]
    targets = readback.get("targets") or []
    if readback.get("ok") is not True or readback.get("expected_operation_count") != 36 or readback.get("matched_operation_count") != 36 or (readback.get("Center"), readback.get("Size"), readback.get("Blend"), readback.get("other")) != (18, 18, 0, 0) or len(targets) != 36 or not all(row.get("present") for row in targets):
        failures.append("persistent_readback")
    phase2 = values["phase_2_idempotency_report.json"]
    phase2_ops = phase2.get("operations") or []
    if phase2.get("ok") is not True or phase2.get("same_runtime_boundary") is not True or phase2.get("evaluated_operation_count") != 36 or phase2.get("setter_call_count") != 0 or phase2.get("effective_mutation_count") != 0 or phase2.get("blend_operation_count") != 0 or phase2.get("timeline_modified") is not False or len(phase2_ops) != 36 or any(row.get("operation") != "compared_and_skipped" for row in phase2_ops):
        failures.append("phase2")
    audit = values["non_target_mutation_audit.json"]
    if audit.get("ok") is not True or audit.get("non_target_expected") != 112 or audit.get("non_target_changes") or audit.get("target_forbidden_changes") or audit.get("track_before") != audit.get("track_after"):
        failures.append("non_target_audit")
    protected = values["protected_inventory_comparison.json"]
    if protected.get("ok") is not True or protected.get("protected_animation_before") != protected.get("protected_animation_after"):
        failures.append("protected_inventory")
    checklist = values["four_cue_visual_review_checklist.json"]
    cues = checklist.get("cues") or []
    if checklist.get("visual_approval_pending") is not True or len(cues) != 4 or {row.get("cue_id"): row.get("text") for row in cues} != TARGETS:
        failures.append("visual_checklist")
    if (report_dir / "rollback_evidence.json").exists():
        failures.append("rollback_invoked_on_success")

    queue_matches = []
    expected_name = f"{TASK_ID}_{run_id}.json"
    for state in ("pending", "running", "completed", "failed"):
        path = root / ".agent" / "commands" / state / expected_name
        if path.exists():
            queue_matches.append({"state": state, "path": str(path.relative_to(root)), "sha256": sha(path), "command": load(path)})
    lifecycle_ok = len(queue_matches) == 1 and queue_matches[0]["state"] == "completed" and queue_matches[0]["command"].get("run_id") == run_id and queue_matches[0]["command"].get("task") == TASK_ID
    if not lifecycle_ok:
        failures.append("command_lifecycle")
    lifecycle = {"ok": lifecycle_ok, "task_id": TASK_ID, "run_id": run_id, "expected_command_count": 1, "matching_command_count": len(queue_matches), "matches": queue_matches}
    validation = {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "plan_hash": PLAN_HASH, "same_command_and_run": lifecycle_ok, "phase_1_setter_call_count": phase1.get("setter_call_count"), "phase_1_effective_mutation_count": phase1.get("effective_mutation_count"), "phase_2_setter_call_count": 0, "phase_2_effective_mutation_count": 0, "phase_2_timeline_modified": False, "blend_operation_count": 0, "persistent_match_count": readback.get("matched_operation_count"), "non_target_preserved": audit.get("ok"), "visual_approval_pending": True, "failures": failures}
    write(report_dir / "command_lifecycle_inventory.json", lifecycle)
    write(report_dir / "runtime_artifact_validation.json", {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "plan_hash": PLAN_HASH, "inventory": inventory, "failures": failures})
    write(report_dir / "phase_2_idempotency_validation.json", validation)
    return validation, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root.resolve(), args.run_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
