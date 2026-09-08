"""Validate the live read-only sub_082 boundary preflight evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_SUB_082_LIVE_BOUNDARY_PREFLIGHT_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6E_V3_BOUNDARY_TIMING_STRATEGY_ASSESSMENT_V3"
SOURCE_RUN_ID = "20260803T135506176634Z_1ef963ee80834a36b8965fc01bad065e"
TECHNICAL_VERDICT = "LIVE_READ_ONLY_BOUNDARY_PREFLIGHT_COMPLETE"
ALLOWED_CLASSIFICATIONS = {
    "DIRECT_END_SETTER_EXPOSED_PERSISTENCE_ROLLBACK_UNPROVEN",
    "GENERIC_SETTER_EXPOSED_BOUNDARY_CONTRACT_UNPROVEN",
    "NO_BOUNDARY_MUTATION_API_SURFACE_EXPOSED",
}
PROPOSED_OPERATION = {"field": "end_frame", "from": 656, "to": 657, "delta_frames": 1}
REQUIRED = (
    "preflight_command.json",
    "publication_receipt.json",
    "source_assessment_validation.json",
    "project_timeline_identity.json",
    "v3_track_inventory.json",
    "target_adjacency_snapshot.json",
    "source_visibility_contract.json",
    "boundary_api_capability_inventory.json",
    "protected_target_window_audit.json",
    "target_fusion_baseline.json",
    "mutation_prohibition_audit.json",
    "preflight_classification.json",
    "lifecycle_runtime_observation.json",
    "status.json",
    "report.json",
    "run.log",
)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command_inventory(root: Path, exclude_run_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def validate(root: Path, run_id: str) -> tuple[dict[str, Any], list[str]]:
    root = root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / run_id
    failures: list[str] = []
    for name in REQUIRED:
        path = run_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing_or_empty:{name}")
    if failures:
        return {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": failures}, failures

    command = load_json(run_dir / "preflight_command.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    source = load_json(run_dir / "source_assessment_validation.json")
    identity = load_json(run_dir / "project_timeline_identity.json")
    inventory = load_json(run_dir / "v3_track_inventory.json")
    adjacency = load_json(run_dir / "target_adjacency_snapshot.json")
    visibility = load_json(run_dir / "source_visibility_contract.json")
    capability = load_json(run_dir / "boundary_api_capability_inventory.json")
    protected = load_json(run_dir / "protected_target_window_audit.json")
    fusion = load_json(run_dir / "target_fusion_baseline.json")
    audit = load_json(run_dir / "mutation_prohibition_audit.json")
    preflight = load_json(run_dir / "preflight_classification.json")
    lifecycle = load_json(run_dir / "lifecycle_runtime_observation.json")
    status = load_json(run_dir / "status.json")
    report = load_json(run_dir / "report.json")

    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent" / "commands"
    completed = queue / "completed" / command_name
    instances = [
        queue / state / command_name
        for state in ("pending", "running", "completed", "failed")
        if (queue / state / command_name).is_file()
    ]
    if instances != [completed]:
        failures.append("command_lifecycle_not_uniquely_completed")
    command_hash = sha256(completed) if completed.is_file() else None
    if command_hash != receipt.get("command_sha256") or command_hash != lifecycle.get("running_command_sha256"):
        failures.append("command_hash_lineage")
    if command.get("task") != TASK_ID or command.get("run_id") != run_id or command.get("mode") != "live_read_only_boundary_preflight":
        failures.append("command_identity")
    payload = command.get("payload") or {}
    if (
        payload.get("source_task_id") != SOURCE_TASK_ID
        or payload.get("source_run_id") != SOURCE_RUN_ID
        or payload.get("mutation_permitted") is not False
        or payload.get("proposed_operation") != PROPOSED_OPERATION
    ):
        failures.append("command_contract")
    if receipt.get("pending_observed") is not True or lifecycle.get("running_observed") is not True:
        failures.append("pending_running_observation")
    if status.get("ok") is not True or status.get("running") is not False or status.get("run_id") != run_id:
        failures.append("status_contract")

    if (
        source.get("ok") is not True
        or source.get("source_task_id") != SOURCE_TASK_ID
        or source.get("source_run_id") != SOURCE_RUN_ID
        or (source.get("candidate") or {}).get("cue_id") != "sub_082"
        or (source.get("candidate") or {}).get("current_range") != [649, 656]
        or (source.get("candidate") or {}).get("proposed_range") != [649, 657]
    ):
        failures.append("source_assessment_contract")

    item_rows = identity.get("items") or {}
    expected_items = {
        "sub_081": {"name": "VC_TEXTPLUS_0081_sub_081", "start": 646, "end": 649, "text": "the"},
        "sub_082": {"name": "VC_TEXTPLUS_0082_sub_082", "start": 649, "end": 656, "text": "blocks."},
        "sub_083": {"name": "VC_TEXTPLUS_0083_sub_083", "start": 659, "end": 665, "text": "That's"},
    }
    identity_ok = (
        identity.get("ok") is True
        and (identity.get("identity") or {}).get("project") == "New Project 1"
        and (identity.get("identity") or {}).get("timeline") == "DZsqH7auhjt_textplus_full"
        and (identity.get("identity") or {}).get("video_track") == 3
        and identity.get("v3_count") == 116
    )
    for cue_id, expected in expected_items.items():
        row = item_rows.get(cue_id) or {}
        identity_ok = identity_ok and all(row.get(key) == value for key, value in expected.items())
    if not identity_ok:
        failures.append("live_identity_contract")

    if (
        inventory.get("ok") is not True
        or inventory.get("v3_count") != 116
        or inventory.get("unique_name_count") != 116
        or len(inventory.get("items") or []) != 116
    ):
        failures.append("v3_inventory_contract")

    if (
        adjacency.get("ok") is not True
        or (adjacency.get("previous") or {}).get("cue_id") != "sub_081"
        or (adjacency.get("previous") or {}).get("end") != 649
        or (adjacency.get("target") or {}).get("cue_id") != "sub_082"
        or (adjacency.get("target") or {}).get("start") != 649
        or (adjacency.get("target") or {}).get("end") != 656
        or (adjacency.get("next") or {}).get("cue_id") != "sub_083"
        or (adjacency.get("next") or {}).get("start") != 659
        or adjacency.get("current_gap_after_target_frames") != 3
        or adjacency.get("proposed_gap_after_target_frames") != 2
        or adjacency.get("proposed_operation") != PROPOSED_OPERATION
        or adjacency.get("proposed_overlap_count") != 0
    ):
        failures.append("adjacency_contract")

    if (
        visibility.get("ok") is not True
        or visibility.get("cue_id") != "sub_082"
        or visibility.get("first_visible_frame") != 649
        or visibility.get("last_visible_frame") != 656
        or visibility.get("expected_visible_frames") != list(range(649, 657))
        or visibility.get("dense_visible_frame_coverage_complete") is not True
        or visibility.get("current_item_range") != [649, 656]
        or visibility.get("proposed_item_range") != [649, 657]
    ):
        failures.append("source_visibility_contract")

    method_rows = capability.get("methods") or []
    methods = {row.get("method"): row for row in method_rows if isinstance(row, dict)}
    if (
        capability.get("ok") is not True
        or capability.get("classification") not in ALLOWED_CLASSIFICATIONS
        or set(methods) != {"GetStart", "GetEnd", "GetDuration", "GetProperty", "SetStart", "SetEnd", "SetProperty"}
        or any(row.get("invoked") is not False for row in methods.values())
        or capability.get("mutation_method_invocation_count") != 0
        or capability.get("persistence_proven") is not False
        or capability.get("rollback_proven") is not False
        or capability.get("mutation_authorized") is not False
    ):
        failures.append("capability_inventory_contract")

    if (
        protected.get("ok") is not True
        or protected.get("protected_cues_in_window") != ["sub_081"]
        or protected.get("target_sub_082_protected") is not False
        or protected.get("next_sub_083_protected") is not False
        or protected.get("sub_081_modifier_connected") is not True
        or protected.get("sub_081_target_count") != 2
        or protected.get("sub_081_verified_target_count") != 2
        or protected.get("protected_target_mutation_count") != 0
        or any(row.get("matched") is not True for row in (protected.get("sub_081_targets") or []))
    ):
        failures.append("protected_window_contract")

    fusion_before = fusion.get("before") or {}
    if (
        fusion.get("ok") is not True
        or (fusion_before.get("item") or {}).get("name") != "VC_TEXTPLUS_0082_sub_082"
        or (fusion_before.get("item") or {}).get("start") != 649
        or (fusion_before.get("item") or {}).get("end") != 656
        or fusion_before.get("styled_text") != "blocks."
        or set((fusion_before.get("inputs") or {})) != {"Center", "Size"}
    ):
        failures.append("target_fusion_baseline_contract")

    if (
        audit.get("ok") is not True
        or audit.get("v3_inventory_unchanged") is not True
        or audit.get("target_fusion_unchanged") is not True
        or audit.get("adjacency_unchanged") is not True
        or audit.get("identity_unchanged") is not True
        or audit.get("accepted_state_unchanged") is not True
        or audit.get("non_current_command_inventory_unchanged") is not True
        or audit.get("boundary_setter_call_count") != 0
        or audit.get("generic_setter_call_count") != 0
        or audit.get("set_input_call_count") != 0
        or audit.get("save_call_count") != 0
        or audit.get("modifier_mutation_call_count") != 0
        or audit.get("effective_mutation_count") != 0
        or audit.get("timeline_modified") is not False
    ):
        failures.append("mutation_prohibition_contract")

    classification = preflight.get("classification")
    if (
        preflight.get("ok") is not True
        or preflight.get("technical_verdict") != TECHNICAL_VERDICT
        or classification not in ALLOWED_CLASSIFICATIONS
        or preflight.get("candidate_cue_id") != "sub_082"
        or preflight.get("candidate_operation") != PROPOSED_OPERATION
        or preflight.get("live_state_matches_offline_strategy") is not True
        or preflight.get("adjacency_safe_for_proposed_range") is not True
        or preflight.get("protected_window_verified") is not True
        or preflight.get("persistence_proven") is not False
        or preflight.get("rollback_proven") is not False
        or preflight.get("mutation_authorized") is not False
    ):
        failures.append("preflight_classification_contract")

    if (
        report.get("ok") is not True
        or report.get("task_id") != TASK_ID
        or report.get("run_id") != run_id
        or report.get("technical_verdict") != TECHNICAL_VERDICT
        or report.get("classification") != classification
        or report.get("candidate_cue_id") != "sub_082"
        or report.get("candidate_operation") != PROPOSED_OPERATION
        or report.get("v3_count") != 116
        or report.get("protected_target_verified_count") != 2
        or report.get("boundary_setter_call_count") != 0
        or report.get("generic_setter_call_count") != 0
        or report.get("set_input_call_count") != 0
        or report.get("save_call_count") != 0
        or report.get("modifier_mutation_call_count") != 0
        or report.get("effective_mutation_count") != 0
        or report.get("timeline_modified") is not False
        or report.get("mutation_authorized") is not False
        or report.get("persistence_proven") is not False
        or report.get("rollback_proven") is not False
        or report.get("accepted_state_unchanged") is not True
    ):
        failures.append("report_contract")

    latest_path = root / ".agent" / "state" / "latest_accepted.json"
    current_latest_hash = sha256(latest_path) if latest_path.is_file() else None
    if current_latest_hash != payload.get("accepted_state_sha256") or current_latest_hash != audit.get("accepted_state_sha256_after"):
        failures.append("accepted_state_hash")
    expected_non_current = payload.get("command_inventory_before_publication")
    actual_non_current = command_inventory(root, run_id)
    if actual_non_current != expected_non_current or actual_non_current != audit.get("non_current_command_inventory_after"):
        failures.append("non_current_command_inventory")
    if list((queue / "pending").glob("*.json")) or list((queue / "running").glob("*.json")):
        failures.append("active_command_after_run")

    result = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(completed.relative_to(root)).replace("\\", "/") if completed.is_file() else None,
        "command_sha256": command_hash,
        "lifecycle": ["pending", "running", "completed"] if not failures else None,
        "technical_verdict": TECHNICAL_VERDICT if not failures else None,
        "classification": classification if not failures else None,
        "candidate_cue_id": "sub_082",
        "candidate_operation": PROPOSED_OPERATION,
        "v3_count": inventory.get("v3_count"),
        "current_gap_after_target_frames": adjacency.get("current_gap_after_target_frames"),
        "proposed_gap_after_target_frames": adjacency.get("proposed_gap_after_target_frames"),
        "protected_target_verified_count": protected.get("sub_081_verified_target_count"),
        "mutation_method_invocation_count": capability.get("mutation_method_invocation_count"),
        "effective_mutation_count": report.get("effective_mutation_count"),
        "timeline_modified": report.get("timeline_modified"),
        "persistence_proven": False,
        "rollback_proven": False,
        "mutation_authorized": False,
        "next_boundary": preflight.get("next_boundary") if not failures else None,
        "failures": failures,
    }
    return result, failures


def final_report(result: dict[str, Any]) -> str:
    return "\n".join([
        "# Approach",
        "",
        "Published one canonical read-only Resolve command, captured the live sub_082 TimelineItem API surface and V3 adjacency, verified the protected sub_081 Step 3C targets, and reacquired all state without invoking any setter or save API.",
        "",
        "# Files changed",
        "",
        f"Only the completed command lifecycle and immutable evidence under `.agent/reports/{TASK_ID}/{result['run_id']}/`.",
        "",
        "# Key evidence",
        "",
        f"- Run ID: `{result['run_id']}`.",
        f"- Classification: `{result.get('classification')}`.",
        "- Live identity: New Project 1 / DZsqH7auhjt_textplus_full / V3 / 116 items.",
        "- Adjacency: sub_081 [646,649), sub_082 [649,656), sub_083 [659,665).",
        "- Proposed future operation remains end frame 656 -> 657; current/proposed gaps to sub_083 are 3/2 frames.",
        "- Protected sub_081 Step 3C targets verified: 2/2.",
        "- Setter/save/modifier calls: 0; effective mutations: 0; timeline_modified=false.",
        "- Persistence proven: NO. Rollback proven: NO. Mutation authorized: NO.",
        "",
        "# PASS or FAIL",
        "",
        "PASS — STEP_3B.6E_SUB_082_LIVE_BOUNDARY_PREFLIGHT_COMPLETE",
        "",
        "# Exact blocker or next boundary",
        "",
        str(result.get("next_boundary") or "No next boundary was produced."),
        "",
        "Manual visual approval required: NO",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id)
    run_dir = args.root.resolve() / ".agent" / "reports" / TASK_ID / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "preflight_validation.json", result)
    if not failures:
        (run_dir / "FINAL_REPORT.md").write_text(final_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
