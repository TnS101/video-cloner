"""Offline final validation for the read-only sub_013 recovery resume run."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_RESUME_V1"
SOURCE_RUN_ID = "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9"
REQUIRED = [
    "recovery_command.json",
    "publication_receipt.json",
    "status.json",
    "report.json",
    "run.log",
    "resume_lineage_validation.json",
    "persistent_post_recovery_state.json",
    "operation_current_state_comparison.json",
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
        (run_dir / "recovery_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        return 1

    command = load_json(run_dir / "recovery_command.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    status = load_json(run_dir / "status.json")
    report = load_json(run_dir / "report.json")
    lineage = load_json(run_dir / "resume_lineage_validation.json")
    comparison = load_json(run_dir / "operation_current_state_comparison.json")
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
        or report.get("technical_verdict") != "TECHNICAL_PASS — MANUAL_VISUAL_APPROVAL_REQUIRED"
        or report.get("source_run_id") != SOURCE_RUN_ID
        or report.get("source_setter_call_count") != 2
        or report.get("source_effective_mutation_count") != 2
        or report.get("current_run_setter_call_count") != 0
        or report.get("current_run_effective_mutation_count") != 0
        or report.get("save_call_count") != 0
        or report.get("modifier_mutation_call_count") != 0
        or report.get("blend_operation_count") != 0
        or report.get("timeline_modified") is not False
    ):
        failures.append("report_contract")
    if lineage.get("ok") is not True or lineage.get("exact_two_allowlisted_corrections") is not True:
        failures.append("lineage_contract")
    operations = comparison.get("operations") or []
    if (
        comparison.get("operation_count") != 36
        or comparison.get("current_target") != 36
        or comparison.get("current_other") != 0
        or comparison.get("missing") != 0
        or comparison.get("ambiguous") != 0
        or comparison.get("blend") != 0
        or comparison.get("other_property") != 0
        or len(operations) != 36
        or any(item.get("classification") != "CURRENT_TARGET" for item in operations)
    ):
        failures.append("full_36_operation_contract")
    if topology.get("ok") is not True or topology.get("v3_candidate_count") != 116:
        failures.append("topology_contract")
    if (
        protected.get("ok") is not True
        or protected.get("protected_operation_count") != 34
        or protected.get("protected_current_target") != 34
        or protected.get("recovered_operation_count") != 2
        or protected.get("recovered_current_target") != 2
        or protected.get("non_target_write_count") != 0
    ):
        failures.append("protected_state_contract")
    expected_phase3 = {
        "ok": True,
        "setter_calls": 0,
        "center_setters": 0,
        "size_setters": 0,
        "effective_mutations": 0,
        "blend_operations": 0,
        "modifier_mutations": 0,
        "timeline_modified": False,
        "current_target": 36,
        "current_other": 0,
        "missing": 0,
        "ambiguous": 0,
        "structural_topology_unchanged": True,
    }
    if phase3 != expected_phase3:
        failures.append("phase3_contract")

    result = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": args.run_id,
        "command_path": str(completed_path.relative_to(root)).replace("\\", "/") if completed_path.is_file() else None,
        "command_sha256": command_hash,
        "lifecycle": ["pending", "running", "completed"] if not failures else None,
        "source_exact_two_corrections": lineage.get("exact_two_allowlisted_corrections") is True,
        "current_run_setters": report.get("current_run_setter_call_count"),
        "full_plan_current_target": comparison.get("current_target"),
        "phase3": phase3,
        "manual_visual_approval_required": True,
        "failures": failures,
    }
    (run_dir / "recovery_validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
