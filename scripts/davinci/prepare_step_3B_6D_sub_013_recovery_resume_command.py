"""Validate immutable recovery evidence, then publish one read-only resume command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_RESUME_V1"
SOURCE_TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1"
SOURCE_RUN_ID = "20260802T185045608Z_e574ca97eb634e518481365d1398d3d9"
ABANDONED_RUN_ID = "20260802T170405023Z_ab3714114cde4f9a92e58cebf31cb1a8"
FAILED_RUNTIME_ID = "20260802T145414206Z_a3ef7e0c906a46a4b86a5a5b68dfe379"
CAPTURE_RUN_ID = "20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
PLAN_PATH = ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json"
ALLOWLIST = [
    {
        "cue_id": "sub_013",
        "text": "out",
        "item_identity": "VC_TEXTPLUS_0013_sub_013",
        "property": "Center",
        "local_frame": 2,
        "timeline_frame": 226,
        "raw_key_identifier": 2,
        "current_value": {"1": 0.506203705, "2": 0.52842448, "3": 0.0},
        "target_value": [0.50611111, 0.5284375],
        "modifier": {"OUTS_ID": "Position", "OUTS_DataType": "Point"},
    },
    {
        "cue_id": "sub_013",
        "text": "out",
        "item_identity": "VC_TEXTPLUS_0013_sub_013",
        "property": "Size",
        "local_frame": 2,
        "timeline_frame": 226,
        "raw_key_identifier": 2,
        "current_value": 0.08768857685550001,
        "target_value": 0.087467395905,
        "modifier": {"OUTS_ID": "Value", "OUTS_DataType": "Number"},
    },
]
PREREQUISITE_HASHES = {
    PLAN_PATH: "59f214ebd38777041fc1071812938a0b96b6a995923f4d2b445cac66aa04f098",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1/20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5/operation_current_state_comparison.json": "6e3ea4203fd18e383109e67d1cebea348fe59fcc6af0073457efb95a4ca8f6ed",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_READ_ONLY_STATE_CAPTURE_V1/20260802T162857519Z_00f12542d87548fc8ff76118bcedb4f5/raw_keyframe_inventory.json": "6c747fdc9638ff3a55ad4bcf33561a19d2af2fbd5da50b4b530a69fb58661308",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/recovery_command.json": "a460ac98754dd3e2869b5ad7e319ed426a084246b9f7dca5537ea473f6c8bd25",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/status.json": "4446a936d1df3a8ffc169f0d6d3be2a2926b06a99d58f50efa736cf8af5b8c76",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/report.json": "afa762f60ef86c90e78573781070c9c83336ff1fc773d43492ce0b9bd6f9f4a1",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/pre_recovery_state.json": "ebc337fb335bf747507dee7850efdbe6de394180879c4b51038e2d800ca07274",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/setter_journal.json": "1a526204e3498334698d5419678b651f886a0c2d2a06448af52ecc9822b6baf5",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/FINAL_REPORT.md": "5eb13b1a5da95a885ec4c1bcec867812e006886243d422c0b567b3f73d5a748a",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/run.log": "2ba2ed5437b9535101d78a46c51b4d9d21e018ce24c575b103196d03dc13f4a1",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/FINAL_REPORT.md": "4c75de984299e6511cbe1a8759bef13b81fd14584dc1f6dc393e878c41edfba1",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/runtime_root_cause_classification.json": "79c079d92b8324b23f6ba39f0243c6719da97337f79482add06a124ff159119d",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/recovery_route_recommendation.json": "b4ce999a519cca3187f82df87edbe348bf75908efbef1f8e7cf55a581ca35538",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/persistent_readback_mismatch_analysis.json": "31e0a038c4905c9806f1150ca2a74e12be2dca8ba957d34785d06e4e77bf7397",
    ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_RUNTIME_FAILURE_FORENSICS_V1/forensics_20260802T154500934Z/protected_inventory_comparison.json": "6fcf258c5d9c2deb4a9b864de64c7350a10f1c2090a888b6fe0cb1141470081d",
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
        state_dir = queue_root / state
        if not state_dir.is_dir():
            continue
        for path in state_dir.glob("*.json"):
            if run_id in path.name:
                matches.append(path)
                continue
            try:
                if load_json(path).get("run_id") == run_id:
                    matches.append(path)
            except Exception:
                continue
    return matches


def validate_source_failure(root: Path, queue_root: Path) -> None:
    source_dir = root / ".agent" / "reports" / SOURCE_TASK_ID / SOURCE_RUN_ID
    command = load_json(source_dir / "recovery_command.json")
    status = load_json(source_dir / "status.json")
    report = load_json(source_dir / "report.json")
    journal = load_json(source_dir / "setter_journal.json")
    if command.get("task") != SOURCE_TASK_ID or command.get("run_id") != SOURCE_RUN_ID:
        raise ValueError("source_command_identity")
    payload = command.get("payload") or {}
    if (
        payload.get("failed_run_id") != FAILED_RUNTIME_ID
        or payload.get("read_only_capture_run_id") != CAPTURE_RUN_ID
        or payload.get("plan_hash") != PLAN_HASH
        or payload.get("recovery_allowlist") != ALLOWLIST
    ):
        raise ValueError("source_command_contract")
    if status.get("ok") is not False or status.get("running") is not False:
        raise ValueError("source_status_contract")
    if (
        report.get("ok") is not False
        or report.get("setter_call_count") != 2
        or report.get("effective_mutation_count") != 2
        or report.get("save_call_count") != 0
        or report.get("modifier_mutation_call_count") != 0
        or "ValueError: topology_changed" not in (report.get("failures") or [])
    ):
        raise ValueError("source_report_contract")
    if not isinstance(journal, list) or len(journal) != 2:
        raise ValueError("source_setter_journal_count")
    if [entry.get("operation") for entry in journal] != ALLOWLIST or not all(entry.get("ok") is True for entry in journal):
        raise ValueError("source_setter_journal_contract")
    source_instances = command_instances(queue_root, SOURCE_RUN_ID)
    if len(source_instances) != 1 or source_instances[0].parent.name != "failed":
        raise ValueError("source_failed_lifecycle")
    if sha256(source_instances[0]) != PREREQUISITE_HASHES[
        ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_SUB_013_RECOVERY_PATCH_V1/20260802T185045608Z_e574ca97eb634e518481365d1398d3d9/recovery_command.json"
    ]:
        raise ValueError("source_failed_command_hash")


def validate_no_conflicts(root: Path, queue_root: Path) -> None:
    for state in ("pending", "running"):
        for path in (queue_root / state).glob("*.json"):
            try:
                command = load_json(path)
            except Exception:
                continue
            task = str(command.get("task") or "")
            if "STEP_3B_6D_SUB_013_RECOVERY" in task:
                raise ValueError(f"conflicting_recovery_command:{state}:{path.name}")
    for state in ("pending", "running", "completed", "failed"):
        for path in (queue_root / state).glob(f"*{TASK_ID}*.json"):
            raise ValueError(f"resume_command_already_exists:{state}:{path.name}")
    if (root / ".agent" / "reports" / TASK_ID).exists():
        raise ValueError("resume_report_root_already_exists")
    if command_instances(queue_root, ABANDONED_RUN_ID):
        raise ValueError("abandoned_run_in_queue")
    abandoned_report = root / ".agent" / "reports" / SOURCE_TASK_ID / ABANDONED_RUN_ID
    if abandoned_report.exists():
        raise ValueError("abandoned_run_report_exists")


def validate_publication_fix(root: Path) -> None:
    preparer = root / "scripts" / "davinci" / "prepare_step_3B_6D_sub_013_recovery_command.py"
    source = preparer.read_text(encoding="utf-8")
    compact = "".join(source.split())
    if "ifany((q/s).glob" in compact:
        raise ValueError("publication_fix_missing")


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
    validate_source_failure(root, queue_root)
    validate_no_conflicts(root, queue_root)
    validate_publication_fix(root)
    bridge = root / "resolve_workspace" / "VC_Agent_Bridge.py"
    if not bridge.is_file() or bridge.stat().st_size == 0:
        raise ValueError("bridge_missing")
    plan = load_json(root / PLAN_PATH)
    if plan.get("plan_hash") != PLAN_HASH:
        raise ValueError("plan_semantic_hash")

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
        "module": "resolve_workspace/modules/step_3B_6D_sub_013_recovery_resume.py",
        "mode": "recovery_resume_read_only",
        "status_path": f"{relative_report_dir}/status.json",
        "log_path": f"{relative_report_dir}/run.log",
        "report_path": f"{relative_report_dir}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report_dir,
            "source_task_id": SOURCE_TASK_ID,
            "source_run_id": SOURCE_RUN_ID,
            "failed_runtime_id": FAILED_RUNTIME_ID,
            "read_only_capture_run_id": CAPTURE_RUN_ID,
            "plan_hash": PLAN_HASH,
            "recovery_allowlist": ALLOWLIST,
            "resume_policy": "read_only_validation_of_already_applied_two_setters",
            "prerequisite_hashes": PREREQUISITE_HASHES,
        },
    }
    command_bytes = (json.dumps(command, indent=2, sort_keys=True) + "\n").encode("utf-8")
    final_hash = hashlib.sha256(command_bytes).hexdigest()

    report_command = report_dir / "recovery_command.json"
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
            "command_sha256": final_hash,
            "published_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if command_instances(queue_root, run_id) != [command_path]:
        raise ValueError("duplicate_command_after_publication")
    print(json.dumps({"ok": True, "run_id": run_id, "command_path": str(command_path), "command_sha256": final_hash}))
    print("MANUAL_ACTION_REQUIRED: run Workspace > Scripts > VC_Agent_Bridge exactly once")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
