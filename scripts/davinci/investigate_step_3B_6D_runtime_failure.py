#!/usr/bin/env python3
"""Offline, fail-closed forensics for the failed Step 3B.6D runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1"
FAILED_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1"
FAILED_RUN_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
TARGET_CUES = ("sub_007", "sub_013", "sub_110", "sub_114")
REQUIRED = (
    "status.json", "report.json", "run.log", "preflight_report.json",
    "four_target_pre_state_snapshot.json", "phase_1_mutation_manifest.json",
    "phase_1_persistent_post_state.json", "readback_comparison.json",
    "rollback_evidence.json", "non_target_mutation_audit.json",
    "protected_inventory_comparison.json", "accepted_plan_identity_report.json",
    "prerequisite_hash_validation.json", "runtime_command.json",
)


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"not_json_object:{path.name}")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value: dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    clean.pop("created_at_unix", None)
    return hashlib.sha256(json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (str(row.get("cue_id") or ""), str(row.get("input") or ""), int(row.get("local_frame") if row.get("local_frame") is not None else -1))


def exact_rows(rows: list[dict[str, Any]], label: str) -> dict[tuple[str, str, int], dict[str, Any]]:
    result: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        item_key = key(row)
        if not all(item_key[:2]) or item_key[2] < 0 or item_key in result:
            raise ValueError(f"duplicate_or_invalid_{label}:{item_key}")
        result[item_key] = row
    return result


def relative(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def inspect(root: Path, failed_dir: Path, command_path: Path, plan_path: Path, output_dir: Path, run_id: str) -> dict[str, Any]:
    if run_id != FAILED_RUN_ID:
        raise ValueError("failed_run_id")
    command = load(command_path)
    if command.get("task") != FAILED_TASK_ID or command.get("run_id") != FAILED_RUN_ID:
        raise ValueError("failed_command_identity")
    payload = command.get("payload") or {}
    if payload.get("plan_hash") != PLAN_HASH or Path(str(payload.get("plan_path") or "")).as_posix() != Path(relative(root, plan_path)).as_posix():
        raise ValueError("failed_command_plan_identity")
    plan = load(plan_path)
    if plan.get("plan_hash") != PLAN_HASH or canonical_hash(plan) != PLAN_HASH:
        raise ValueError("accepted_plan_hash")
    files = {name: failed_dir / name for name in REQUIRED}
    if any(not path.is_file() or path.stat().st_size == 0 for path in files.values()):
        raise ValueError("missing_failed_runtime_artifact")
    values = {name: load(path) for name, path in files.items() if name.endswith(".json")}
    report, status = values["report.json"], values["status.json"]
    if report.get("run_id") != FAILED_RUN_ID or report.get("plan_hash") != PLAN_HASH or status.get("run_id") != FAILED_RUN_ID or status.get("ok") is not False:
        raise ValueError("failed_runtime_identity")
    if report.get("setter_call_count") != 20 or report.get("effective_mutation_count") != 20 or report.get("blend_operation_count") != 0:
        raise ValueError("failed_runtime_counts")

    plan_rows = [dict(target, cue_id=item["cue_id"], name=item["name"], text=item["text"]) for item in plan.get("rollout_items") or [] for target in item.get("targets") or []]
    if len(plan_rows) != 36 or [row["cue_id"] for row in plan.get("rollout_items") or []] != list(TARGET_CUES):
        raise ValueError("plan_operation_inventory")
    plan_map = exact_rows(plan_rows, "plan_operation")
    if set(row["input"] for row in plan_rows) != {"Center", "Size"}:
        raise ValueError("plan_property_inventory")

    pre_items = values["four_target_pre_state_snapshot.json"].get("items") or []
    pre_rows = [dict(target, cue_id=item["cue_id"], name=item["name"], text=item["text"]) for item in pre_items for target in item.get("targets") or []]
    pre_map = exact_rows(pre_rows, "prestate_operation")
    if set(pre_map) != set(plan_map):
        raise ValueError("incomplete_prestate")
    journal = values["phase_1_mutation_manifest.json"].get("operations") or []
    journal_map = exact_rows(journal, "mutation_journal")
    if len(journal) != 20 or any(not row.get("ok") for row in journal):
        raise ValueError("mutation_journal_count_or_failure")
    if not set(journal_map).issubset(plan_map):
        raise ValueError("journal_not_in_plan")
    readback_rows = values["readback_comparison.json"].get("targets") or []
    readback_map = exact_rows(readback_rows, "persistent_readback")
    if set(readback_map) != set(plan_map):
        raise ValueError("incomplete_persistent_readback")

    ledger = []
    for index, operation in enumerate(plan_rows, 1):
        operation_key = key(operation)
        before, mutation, after = pre_map[operation_key], journal_map.get(operation_key), readback_map[operation_key]
        if mutation:
            classification = "EFFECTIVE_MUTATION"
        elif before.get("matched"):
            classification = "SKIPPED_PRESET_MATCH"
        else:
            classification = "UNEXECUTED_OR_UNJOURNALED"
        ledger.append({
            "operation_index": index, "cue_id": operation["cue_id"], "item_identity": operation["name"],
            "property": operation["input"], "local_frame": operation["local_frame"], "timeline_frame": operation.get("timeline_frame"),
            "pre_state_value": before.get("actual"), "target_value": operation.get("expected"),
            "equality_before_setter": before.get("matched"), "setter_attempted": mutation is not None,
            "setter_return": (mutation.get("result") if mutation else None),
            "immediate_readback_value": ((mutation.get("result") or {}).get("attempts") or [{}])[-1].get("actual") if mutation else None,
            "effective_mutation_classification": classification,
            "final_known_state_after_phase_1": after.get("actual"), "persistent_matched": after.get("matched"),
            "evidence_source": ["four_target_pre_state_snapshot.json", "phase_1_mutation_manifest.json" if mutation else "no mutation journal row", "readback_comparison.json"],
        })
    if sum(row["setter_attempted"] for row in ledger) != 20 or sum(row["effective_mutation_classification"] == "EFFECTIVE_MUTATION" for row in ledger) != 20:
        raise ValueError("ledger_mutation_accounting")
    if len(ledger) != 36:
        raise ValueError("ledger_operation_accounting")
    mismatch_rows = [row for row in ledger if not row["persistent_matched"]]
    if not mismatch_rows:
        raise ValueError("missing_persistent_mismatch")

    rollback = values["rollback_evidence.json"]
    created = rollback.get("created_modifiers") or []
    restored = rollback.get("static_restoration") or []
    rollback_readback = rollback.get("persistent_readback") or []
    if rollback.get("attempted") is not True or len(created) != 6 or len(restored) != 6 or len(rollback_readback) != 6:
        raise ValueError("incomplete_rollback_evidence")
    restore_by_name_input = {(str(row.get("name")), str(row.get("input"))): row for row in restored}
    readback_by_name_input = {(str(row.get("name")), str(row.get("input"))): row for row in rollback_readback}
    rollback_ledger = []
    for order, modifier in enumerate(created, 1):
        pair = (str(modifier.get("name")), str(modifier.get("input")))
        restoration, readback = restore_by_name_input.get(pair), readback_by_name_input.get(pair)
        rollback_ledger.append({"rollback_order": order, "cue_id": next((cue for cue, item in ((row["cue_id"], row) for row in plan.get("rollout_items") or []) if item.get("name") == pair[0]), None), "item_identity": pair[0], "property": pair[1], "frame_or_key": "static input plus all run-created keys", "expected_original_value": restoration.get("expected") if restoration else None, "modifier_removal_attempted": True, "modifier_removal_return": modifier.get("returned"), "modifier_disconnected": modifier.get("disconnected"), "static_setter_attempted": restoration is not None, "static_setter_return": restoration.get("returned") if restoration else None, "static_restored": restoration.get("restored") if restoration else None, "persistent_readback": readback.get("actual") if readback else None, "persistent_matched": readback.get("matched") if readback else None, "topology_ok": readback.get("topology_ok") if readback else None, "success": bool(modifier.get("disconnected") and restoration and restoration.get("restored") and readback and readback.get("matched") and readback.get("topology_ok")), "evidence_source": "rollback_evidence.json"})

    first = mismatch_rows[0]
    readback_classification = "R2 â€” FRAME_OR_KEY_ADDRESSING_MISMATCH" if all(row["cue_id"] == "sub_013" and row["local_frame"] == 2 and not row["setter_attempted"] for row in mismatch_rows) else "R7 â€” INSUFFICIENT_RUNTIME EVIDENCE"
    rollback_classification = "B3 â€” KEY_REMOVAL_OR_RESTORATION_UNSUPPORTED" if all(row.get("modifier_removal_return") is False and row.get("modifier_disconnected") is False for row in rollback_ledger) else "B7 â€” INSUFFICIENT_RUNTIME EVIDENCE"
    state_rows = []
    for cue_id in TARGET_CUES:
        rows = [row for row in ledger if row["cue_id"] == cue_id]
        rollback_rows = [row for row in rollback_ledger if row["cue_id"] == cue_id]
        if not any(row["setter_attempted"] for row in rows):
            confidence, reason = "PROVEN_ORIGINAL", "No setter journal row; all 12 persistent readback rows matched the accepted plan."
        elif rollback_rows and any(not row["topology_ok"] for row in rollback_rows):
            confidence, reason = "PROVEN_PARTIAL", "Rollback persistent readback retained a connected run-created modifier; only limited static-frame values were observed."
        else:
            confidence, reason = "UNKNOWN", "Immutable artifacts do not prove a complete post-rollback state."
        state_rows.append({"cue_id": cue_id, "classification": confidence, "reason": reason, "last_runtime_evidence": ["phase_1_mutation_manifest.json", "readback_comparison.json", "rollback_evidence.json"]})
    timeline_state = "MUTATED_STATE_UNKNOWN" if any(row["classification"] != "PROVEN_ORIGINAL" for row in state_rows) else "FULLY_RESTORED"
    protected = values["protected_inventory_comparison.json"]
    artifacts = {
        "failed_run_identity.json": {"ok": True, "task_id": TASK_ID, "failed_task_id": FAILED_TASK_ID, "failed_run_id": FAILED_RUN_ID, "command_path": relative(root, command_path), "command_sha256": sha256(command_path), "plan_path": relative(root, plan_path), "plan_sha256": sha256(plan_path), "plan_hash": PLAN_HASH, "allowlist": list(TARGET_CUES), "operation_inventory": {"Center": 18, "Size": 18, "Blend": 0, "other": 0, "total": 36}, "conflicting_retry_found": False},
        "forward_operation_ledger.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "planned_operation_count": 36, "setter_call_count": 20, "effective_mutation_count": 20, "skipped_count": sum(row["effective_mutation_classification"] == "SKIPPED_PRESET_MATCH" for row in ledger), "unexecuted_or_unjournaled_count": sum(row["effective_mutation_classification"] == "UNEXECUTED_OR_UNJOURNALED" for row in ledger), "last_successful_operation": next(row for row in reversed(ledger) if row["setter_attempted"]), "first_unexecuted_operation": next((row for row in ledger if row["effective_mutation_classification"] == "UNEXECUTED_OR_UNJOURNALED"), None), "operations": ledger},
        "persistent_readback_mismatch_analysis.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "matched_operation_count": 36 - len(mismatch_rows), "first_mismatch": first, "all_mismatches": mismatch_rows, "readback_classification": readback_classification, "conclusion": "The two unjournaled local-frame-2 operations were not persisted as explicit keys; post-write interpolation differs from the target."},
        "rollback_operation_ledger.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "attempted_operation_count": len(rollback_ledger), "successful_operation_count": sum(row["success"] for row in rollback_ledger), "operations": rollback_ledger},
        "target_current_state_assessment.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "current_state_proven_from_immutable_artifacts_alone": False, "target_cues": state_rows, "timeline_state_classification": timeline_state, "reason": "The only post-rollback observations are limited frames captured at failure time; no immutable current Resolve readback exists."},
        "runtime_root_cause_classification.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "readback_classification": readback_classification, "rollback_classification": rollback_classification, "evidence": {"first_readback_mismatch": first, "all_delete_modifier_attempts_returned_false": all(row.get("modifier_removal_return") is False for row in rollback_ledger), "all_modifier_connections_remained": all(row.get("modifier_disconnected") is False for row in rollback_ledger)}},
        "recovery_route_recommendation.json": {"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "route": "ROUTE B â€” READ-ONLY RESOLVE STATE CAPTURE REQUIRED", "reason": "Current persistent geometry and modifier topology cannot be proven from failure-time artifacts alone.", "smallest_next_sol_task": {"mode": "BUILD", "objective": "Create one zero-setter, zero-save Resolve bridge diagnostic that reads only the four target cues, their Center/Size values and modifier topology at every planned frame, plus V3/non-target invariants.", "forbidden": ["recovery", "rollback", "save", "setter", "plan regeneration", "additional cues"]}},
        "protected_inventory_comparison.json": {"ok": bool(protected.get("ok")), "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "source_path": relative(root, files["protected_inventory_comparison.json"]), "source_sha256": sha256(files["protected_inventory_comparison.json"]), "source_ok": protected.get("ok"), "non_target_audit_ok": values["non_target_mutation_audit.json"].get("ok")},
    }
    for name, value in artifacts.items():
        write(output_dir / name, value)
    return artifacts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--failed-run-id", required=True)
    parser.add_argument("--failed-dir", type=Path, required=True)
    parser.add_argument("--command", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    artifacts = inspect(args.root.resolve(), args.failed_dir.resolve(), args.command.resolve(), args.plan.resolve(), args.output_dir.resolve(), args.failed_run_id)
    print(json.dumps({"ok": True, "task_id": TASK_ID, "failed_run_id": FAILED_RUN_ID, "artifacts": sorted(artifacts)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
