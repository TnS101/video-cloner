"""Validate exact drift evidence, then publish one bounded topology-repair command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_TOPOLOGY_REPAIR_V1"
SOURCE_RECOVERY_RUN_ID = "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9"
SOURCE_RESUME_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_RESUME_V1"
SOURCE_RESUME_RUN_ID = "20260803T084043222Z_eee718d810174f3595316a82d477f8e3"
CAPTURE_RUN_ID = "20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
PLAN_PATH = ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json"
RESUME_COMMAND_SHA256 = "7273e9cd9f2353de299550fb514bbdaa35135541ae93db1b1155f9b5b6be8e42"
PREREQUISITE_HASHES = {
    PLAN_PATH: "59f214ebd38777041fc1071812938a0b96b6a995923f4d2b445cac66aa04f098",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1/20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5/operation_current_state_comparison.json": "6e3ea4203fd18e383109e67d1cebea348fe59fcc6af0073457efb95a4ca8f6ed",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1/20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5/raw_keyframe_inventory.json": "6c747fdc9638ff3a55ad4bcf33561a19d2af2fbd5da50b4b530a69fb58661308",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/setter_journal.json": "1a526204e3498334698d5419678b651f886a0c2d2a06448af52ecc9822b6baf5",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/report.json": "afa762f60ef86c90e78573781070c9c83336ff1fc773d43492ce0b9bd6f9f4a1",
    f".agent/reports/{SOURCE_RESUME_TASK_ID}/{SOURCE_RESUME_RUN_ID}/resume_lineage_validation.json": "6fcdfe31f114a4f499112bea55d49a46a2c58ff9e61d9403afe9d4ee2a738228",
    f".agent/reports/{SOURCE_RESUME_TASK_ID}/{SOURCE_RESUME_RUN_ID}/topology_preservation_audit.json": "5336fd6842dc26b1510b38c6f68c5acef5e1dbbba9d9ebddedea730f14a7abc6",
    f".agent/reports/{SOURCE_RESUME_TASK_ID}/{SOURCE_RESUME_RUN_ID}/FINAL_REPORT.md": "323124076deb30c50feeccb59813c4b75df5d7b2e4ef7ffdd4a9934c0c847cab",
    ".agent/state/resolve_bridge_installation.json": "be8f9a340a53781549f759fbd249df85a01f39e19f91067bfc8d2f9a0c8e6f0c",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name("." + path.name + ".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def validate_hashes(root: Path) -> None:
    for relative_path, expected_hash in PREREQUISITE_HASHES.items():
        path = root / relative_path
        if not path.is_file() or sha256(path) != expected_hash:
            raise ValueError(f"prerequisite_hash:{relative_path}")


def command_instances(queue_root: Path, run_id: str) -> list[Path]:
    matches: list[Path] = []
    for state in ("pending", "running", "completed", "failed"):
        for path in (queue_root / state).glob("*.json"):
            if run_id in path.name:
                matches.append(path)
                continue
            try:
                if load_json(path).get("run_id") == run_id:
                    matches.append(path)
            except Exception:
                continue
    return matches


def validate_resume_failure(root: Path, queue_root: Path) -> None:
    instances = command_instances(queue_root, SOURCE_RESUME_RUN_ID)
    if len(instances) != 1 or instances[0].parent.name != "failed" or sha256(instances[0]) != RESUME_COMMAND_SHA256:
        raise ValueError("resume_failed_lifecycle")
    command = load_json(instances[0])
    if command.get("task") != SOURCE_RESUME_TASK_ID or command.get("run_id") != SOURCE_RESUME_RUN_ID:
        raise ValueError("resume_command_identity")
    report_dir = root / ".agent" / "reports" / SOURCE_RESUME_TASK_ID / SOURCE_RESUME_RUN_ID
    topology = load_json(report_dir / "topology_preservation_audit.json")
    lineage = load_json(report_dir / "resume_lineage_validation.json")
    final_report = (report_dir / "FINAL_REPORT.md").read_text(encoding="utf-8-sig")
    if topology.get("ok") is not False or topology.get("v3_candidate_count") != 116:
        raise ValueError("resume_topology_status")
    if lineage.get("ok") is not True or lineage.get("exact_two_allowlisted_corrections") is not True:
        raise ValueError("resume_lineage_status")
    if "structural_topology_drift" not in final_report or "Fresh setters: 0" not in final_report and "zero setters" not in final_report.lower():
        raise ValueError("resume_final_report_contract")
    current = topology.get("current") or {}
    expected = topology.get("expected") or {}
    for property_name in ("Center", "Size"):
        if (current.get("sub_013") or {}).get(property_name, {}).get("raw_keyframe_structure") != {
            "1": 0.0,
            "2": 1.0,
            "3": 2.0,
            "4": 3.0,
            "5": 4.0,
        }:
            raise ValueError(f"resume_current_topology:{property_name}")
        if (expected.get("sub_013") or {}).get(property_name, {}).get("raw_keyframe_structure") != {
            "1": 0.0,
            "2": 1.0,
            "3": 3.0,
            "4": 4.0,
        }:
            raise ValueError(f"resume_expected_topology:{property_name}")


def validate_no_conflicts(root: Path, queue_root: Path) -> None:
    for state in ("pending", "running"):
        active = list((queue_root / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    for state in ("pending", "running", "completed", "failed"):
        existing = list((queue_root / state).glob(f"*{TASK_ID}*.json"))
        if existing:
            raise ValueError(f"topology_repair_command_already_exists:{state}:{existing[0].name}")
    if (root / ".agent" / "reports" / TASK_ID).exists():
        raise ValueError("topology_repair_report_root_already_exists")


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    milliseconds = now.microsecond // 1000
    return f"{now:%Y%m%dT%H%M%S}{milliseconds:03d}Z_{uuid4().hex}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    queue_root = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue_root / state).mkdir(parents=True, exist_ok=True)

    validate_hashes(root)
    validate_resume_failure(root, queue_root)
    validate_no_conflicts(root, queue_root)
    bridge = root / "resolve_workspace" / "VC_Agent_Bridge.py"
    if not bridge.is_file() or bridge.stat().st_size == 0:
        raise ValueError("bridge_missing")
    if load_json(root / PLAN_PATH).get("plan_hash") != PLAN_HASH:
        raise ValueError("plan_semantic_hash")
    accepted_state = root / ".agent" / "state" / "latest_accepted.json"
    accepted_state_hash = sha256(accepted_state) if accepted_state.is_file() else None

    run_id = allocate_run_id()
    relative_report_dir = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report_dir
    report_dir.mkdir(parents=True, exist_ok=False)
    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = queue_root / "pending" / command_name
    command: dict[str, Any] = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/step_3B_6D_sub_013_topology_repair.py",
        "mode": "topology_repair",
        "status_path": f"{relative_report_dir}/status.json",
        "log_path": f"{relative_report_dir}/run.log",
        "report_path": f"{relative_report_dir}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report_dir,
            "source_recovery_run_id": SOURCE_RECOVERY_RUN_ID,
            "source_resume_run_id": SOURCE_RESUME_RUN_ID,
            "read_only_capture_run_id": CAPTURE_RUN_ID,
            "plan_hash": PLAN_HASH,
            "repair_policy": "delete_exact_two_erroneous_time_2_keys_then_validate_capture_raw_addressing",
            "prerequisite_hashes": PREREQUISITE_HASHES,
            "accepted_state_sha256": accepted_state_hash,
            "mutation_allowlist": [
                {"cue_id": "sub_013", "property": "Center", "action": "delete_key", "time": 2.0},
                {"cue_id": "sub_013", "property": "Size", "action": "delete_key", "time": 2.0},
            ],
            "forbidden_mutations": [
                "value setter",
                "Blend",
                "modifier creation/deletion",
                "connection change",
                "any key except sub_013 Center/Size time 2.0",
                "SaveProject",
                "timeline restructuring",
            ],
        },
    }
    command_bytes = (json.dumps(command, indent=2, sort_keys=True) + "\n").encode("utf-8")
    command_hash = hashlib.sha256(command_bytes).hexdigest()
    report_command = report_dir / "topology_repair_command.json"
    temp_command = command_path.with_name("." + command_path.name + ".tmp")
    report_command.write_bytes(command_bytes)
    temp_command.write_bytes(command_bytes)
    os.replace(temp_command, command_path)
    write_json(
        report_dir / "publication_receipt.json",
        {
            "task_id": TASK_ID,
            "run_id": run_id,
            "pending_observed": command_path.is_file(),
            "pending_command_path": str(command_path.relative_to(root)).replace("\\", "/"),
            "command_sha256": command_hash,
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if command_instances(queue_root, run_id) != [command_path]:
        raise ValueError("duplicate_command_after_publication")
    print(json.dumps({"ok": True, "run_id": run_id, "command_path": str(command_path), "command_sha256": command_hash}))
    print("MANUAL_ACTION_REQUIRED: run Workspace > Scripts > VC_Agent_Bridge exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
