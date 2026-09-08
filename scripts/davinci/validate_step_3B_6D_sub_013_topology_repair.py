"""Offline validation for the bounded sub_013 topology repair."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_TOPOLOGY_REPAIR_V1"
SOURCE_RESUME_RUN_ID = "20260803T084043222Z_eee718d810174f3595316a82d477f8e3"
TECHNICAL_VERDICT = "TOPOLOGY_RESTORED — STEP_3B_6D_DIRECT_FRAME_ACCEPTANCE_REQUIRES_CLOUD_REVIEW"
REQUIRED = [
    "topology_repair_command.json",
    "publication_receipt.json",
    "status.json",
    "report.json",
    "run.log",
    "topology_repair_pre_state.json",
    "key_deletion_journal.json",
    "topology_repair_post_state.json",
    "direct_frame_state_comparison.json",
    "address_resolved_operation_comparison.json",
    "topology_preservation_audit.json",
    "protected_state_audit.json",
    "phase3_idempotency_report.json",
    "lifecycle_runtime_observation.json",
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / args.run_id
    failures: list[str] = []
    for name in REQUIRED:
        path = run_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing_or_empty:{name}")
    if failures:
        result = {"ok": False, "task_id": TASK_ID, "run_id": args.run_id, "failures": failures}
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "topology_repair_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 1

    command = load_json(run_dir / "topology_repair_command.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    status = load_json(run_dir / "status.json")
    report = load_json(run_dir / "report.json")
    pre_state = load_json(run_dir / "topology_repair_pre_state.json")
    journal = load_json(run_dir / "key_deletion_journal.json")
    post_state = load_json(run_dir / "topology_repair_post_state.json")
    direct = load_json(run_dir / "direct_frame_state_comparison.json")
    resolved = load_json(run_dir / "address_resolved_operation_comparison.json")
    topology = load_json(run_dir / "topology_preservation_audit.json")
    protected = load_json(run_dir / "protected_state_audit.json")
    phase3 = load_json(run_dir / "phase3_idempotency_report.json")
    running_observation = load_json(run_dir / "lifecycle_runtime_observation.json")

    command_name = f"{TASK_ID}_{args.run_id}.json"
    queue_root = root / ".agent" / "commands"
    completed_path = queue_root / "completed" / command_name
    instances = [
        queue_root / state / command_name
        for state in ("pending", "running", "completed", "failed")
        if (queue_root / state / command_name).is_file()
    ]
    if instances != [completed_path]:
        failures.append("command_lifecycle_not_uniquely_completed")
    command_hash = sha256(completed_path) if completed_path.is_file() else None
    if command_hash != receipt.get("command_sha256") or command_hash != running_observation.get("running_command_sha256"):
        failures.append("command_hash_lineage")
    if command.get("task") != TASK_ID or command.get("run_id") != args.run_id:
        failures.append("command_identity")
    if receipt.get("pending_observed") is not True or running_observation.get("running_observed") is not True:
        failures.append("pending_running_observation")
    if status.get("ok") is not True or status.get("running") is not False or status.get("run_id") != args.run_id:
        failures.append("status_contract")

    if (
        report.get("ok") is not True
        or report.get("technical_verdict") != TECHNICAL_VERDICT
        or report.get("step_3B_6D_acceptance_status") != "BLOCKED_PENDING_CLOUD_REVIEW"
        or report.get("source_resume_run_id") != SOURCE_RESUME_RUN_ID
        or report.get("value_setter_call_count") != 0
        or report.get("key_delete_call_count") != 2
        or report.get("effective_mutation_count") != 2
        or report.get("save_call_count") != 0
        or report.get("modifier_mutation_call_count") != 0
        or report.get("blend_operation_count") != 0
        or report.get("timeline_modified") is not True
        or report.get("topology_restored") is not True
        or report.get("accepted_state_unchanged") is not True
    ):
        failures.append("report_contract")

    pre_summary = pre_state.get("direct_frame_summary") or {}
    if pre_summary.get("operation_count") != 36 or pre_summary.get("current_target") != 36 or pre_summary.get("current_other") != 0:
        failures.append("pre_repair_state_contract")

    if not isinstance(journal, list) or len(journal) != 2:
        failures.append("key_deletion_journal_count")
    else:
        expected_properties = ["Center", "Size"]
        if [entry.get("property") for entry in journal] != expected_properties:
            failures.append("key_deletion_order")
        for entry in journal:
            if (
                entry.get("cue_id") != "sub_013"
                or entry.get("deleted_time") != 2.0
                or entry.get("ok") is not True
                or entry.get("retained_values_unchanged") is not True
                or (entry.get("before_topology") or {}).get("raw_keyframe_structure")
                != {"1": 0.0, "2": 1.0, "3": 2.0, "4": 3.0, "5": 4.0}
                or (entry.get("after_topology") or {}).get("raw_keyframe_structure")
                != {"1": 0.0, "2": 1.0, "3": 3.0, "4": 4.0}
            ):
                failures.append(f"key_deletion_contract:{entry.get('property')}")

    direct_operations = direct.get("operations") or []
    direct_other = [item for item in direct_operations if item.get("classification") == "CURRENT_OTHER"]
    if (
        direct.get("operation_count") != 36
        or direct.get("current_target") != 34
        or direct.get("current_other") != 2
        or direct.get("missing") != 0
        or direct.get("ambiguous") != 0
        or len(direct_operations) != 36
        or {(item.get("cue_id"), item.get("property"), item.get("local_frame")) for item in direct_other}
        != {("sub_013", "Center", 2), ("sub_013", "Size", 2)}
    ):
        failures.append("direct_frame_restored_interpolation_contract")

    resolved_operations = resolved.get("operations") or []
    raw_resolved = [item for item in resolved_operations if item.get("addressing") == "capture_raw_key_identity"]
    if (
        resolved.get("operation_count") != 36
        or resolved.get("current_target") != 36
        or resolved.get("current_other") != 0
        or len(resolved_operations) != 36
        or any(item.get("classification") != "CURRENT_TARGET" for item in resolved_operations)
        or len(raw_resolved) != 2
        or {(item.get("property"), item.get("raw_key_identifier"), item.get("raw_time")) for item in raw_resolved}
        != {("Center", 2, 1.0), ("Size", 2, 1.0)}
    ):
        failures.append("address_resolved_36_operation_contract")

    if (
        topology.get("ok") is not True
        or topology.get("v3_candidate_count") != 116
        or len(topology.get("deleted_keys") or []) != 2
        or topology.get("actual_after") != topology.get("expected_after")
    ):
        failures.append("topology_restoration_contract")

    if (
        protected.get("ok") is not True
        or protected.get("protected_operation_count") != 34
        or protected.get("protected_values_unchanged") is not True
        or protected.get("value_setter_call_count") != 0
        or protected.get("key_delete_call_count") != 2
        or protected.get("non_target_write_count") != 0
        or protected.get("blend_operation_count") != 0
        or protected.get("modifier_mutation_call_count") != 0
    ):
        failures.append("protected_state_contract")

    expected_phase3 = {
        "ok": True,
        "value_setter_calls": 0,
        "key_delete_calls": 0,
        "effective_mutations": 0,
        "blend_operations": 0,
        "modifier_mutations": 0,
        "timeline_modified": False,
        "structural_topology_restored": True,
        "direct_frame_current_target": 34,
        "direct_frame_current_other": 2,
        "address_resolved_current_target": 36,
        "address_resolved_current_other": 0,
    }
    if phase3 != expected_phase3:
        failures.append("phase3_contract")

    post_direct = post_state.get("direct_frame_summary") or {}
    post_resolved = post_state.get("address_resolved_summary") or {}
    if post_direct.get("current_target") != 34 or post_direct.get("current_other") != 2:
        failures.append("post_direct_summary")
    if post_resolved.get("current_target") != 36 or post_resolved.get("current_other") != 0:
        failures.append("post_resolved_summary")

    accepted_state = root / ".agent" / "state" / "latest_accepted.json"
    accepted_hash = sha256(accepted_state) if accepted_state.is_file() else None
    if accepted_hash != post_state.get("accepted_state_sha256"):
        failures.append("accepted_state_hash")

    result = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": args.run_id,
        "command_path": str(completed_path.relative_to(root)).replace("\\", "/") if completed_path.is_file() else None,
        "command_sha256": command_hash,
        "lifecycle": ["pending", "running", "completed"] if not failures else None,
        "topology_restored": topology.get("ok") is True,
        "key_delete_call_count": report.get("key_delete_call_count"),
        "value_setter_call_count": report.get("value_setter_call_count"),
        "direct_frame_result": {"current_target": direct.get("current_target"), "current_other": direct.get("current_other")},
        "address_resolved_result": {"current_target": resolved.get("current_target"), "current_other": resolved.get("current_other")},
        "phase3": phase3,
        "technical_verdict": TECHNICAL_VERDICT if not failures else None,
        "step_3B_6D_acceptance_status": "BLOCKED_PENDING_CLOUD_REVIEW",
        "manual_visual_approval_required": True,
        "failures": failures,
    }
    (run_dir / "topology_repair_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
