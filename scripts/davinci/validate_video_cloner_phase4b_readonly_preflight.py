"""Validate completed Phase 4B preflight evidence without contacting Resolve."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4b_readonly_preflight import ACTION, MODE, TASK_ID
from resolve_workspace.modules.video_cloner_phase4b_timeline_application import parse_fcpxml_contract, sha256
from scripts.davinci.prepare_video_cloner_phase4b_readonly_preflight import MODULE

READINESS = {
    "READY_PHASE4B_FIRST_IMPORT",
    "READY_PHASE4B_IDEMPOTENT_REUSE",
    "BLOCKED_PHASE4B_DUPLICATE_TARGET",
    "BLOCKED_PHASE4B_TARGET_CONTRACT_MISMATCH",
    "BLOCKED_PHASE4B_NO_CURRENT_PROJECT",
    "BLOCKED_PHASE4B_SIGNATURE_BASELINE",
    "BLOCKED_PHASE4B_MEDIA_POOL_UNAVAILABLE",
    "BLOCKED_PHASE4B_RESOLVE_NOT_CONNECTED",
}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(path.name)
    return value


def validate(root: Path, run_id: str) -> tuple[dict, list[str]]:
    root = root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / run_id
    required = ("preflight_command.json", "publication_receipt.json", "status.json", "report.json", "run.log")
    failures = [f"missing:{name}" for name in required if not (run_dir / name).is_file() or (run_dir / name).stat().st_size == 0]
    if failures:
        return {"ok": False, "run_id": run_id, "failures": failures}, failures
    command, receipt, status, report = (load(run_dir / name) for name in ("preflight_command.json", "publication_receipt.json", "status.json", "report.json"))
    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent" / "commands"
    completed = queue / "completed" / command_name
    locations = [queue / state / command_name for state in ("pending", "running", "completed", "failed") if (queue / state / command_name).is_file()]
    if locations != [completed] or not completed.is_file() or sha256(completed) != receipt.get("command_sha256"):
        failures.append("command_lifecycle")
    payload = command.get("payload") or {}
    expected_operation = receipt.get("operation_id")
    if command.get("task") != TASK_ID or command.get("module") != MODULE or command.get("mode") != MODE or payload.get("action") != ACTION or payload.get("operation_id") != expected_operation or report.get("operation_id") != expected_operation:
        failures.append("command_identity")
    if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
        failures.append("command_read_only_contract")
    try:
        artifact = Path(str(payload.get("fcpxml_path") or "")).resolve()
        contract = parse_fcpxml_contract(artifact)
        if sha256(artifact) != payload.get("fcpxml_sha256") or payload.get("target_timeline_name") != contract["timeline_name"] or (payload.get("expected_clip_count"), payload.get("expected_duration_frames"), payload.get("expected_fps")) != (len(contract["clips"]), contract["duration_frames"], contract["fps"]):
            failures.append("artifact_contract")
    except Exception:
        failures.append("artifact_contract")
    readiness = report.get("readiness")
    if not isinstance(readiness, str) or (readiness not in READINESS and re.fullmatch(r"BLOCKED_PHASE4B_[A-Z0-9_]+", readiness) is None):
        failures.append("readiness")
    target_count = report.get("target_occurrence_count")
    if type(target_count) is not int or target_count < 0:
        failures.append("target_occurrence_count")
    if readiness == "READY_PHASE4B_FIRST_IMPORT" and target_count != 0:
        failures.append("first_import_semantics")
    if readiness == "READY_PHASE4B_IDEMPOTENT_REUSE" and (target_count != 1 or (report.get("target_validation") or {}).get("ok") is not True):
        failures.append("reuse_semantics")
    if readiness == "BLOCKED_PHASE4B_DUPLICATE_TARGET" and (type(target_count) is not int or target_count <= 1):
        failures.append("duplicate_semantics")
    names = report.get("timeline_names")
    inventory = report.get("non_target_timeline_inventory")
    target = payload.get("target_timeline_name")
    if not isinstance(names, list) or report.get("timeline_count") != len(names) or report.get("duplicate_name_counts") != dict(sorted(Counter(names).items())):
        failures.append("timeline_inventory")
    if not isinstance(inventory, list) or any(row.get("name") == target or re.fullmatch(r"[0-9a-f]{64}", str(row.get("signature") or "")) is None for row in inventory if isinstance(row, dict)) or any(not isinstance(row, dict) for row in inventory):
        failures.append("non_target_signatures")
    if readiness and readiness not in {"BLOCKED_PHASE4B_NO_CURRENT_PROJECT", "BLOCKED_PHASE4B_RESOLVE_NOT_CONNECTED"} and not report.get("project_name"):
        failures.append("current_project")
    zero = {"imports": 0, "selections": 0, "creates": 0, "deletes": 0, "renames": 0, "media_imports": 0, "saves": 0}
    if status.get("ok") is not True or report.get("ok") is not True or report.get("read_only") is not True or report.get("timeline_modified") is not False or report.get("mutation_counts") != zero:
        failures.append("zero_mutation")
    summary = {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "operation_id": expected_operation, "readiness": readiness, "project_name": report.get("project_name"), "target_occurrence_count": target_count, "timeline_count": report.get("timeline_count"), "non_target_timeline_inventory": inventory, "mutation_counts": report.get("mutation_counts"), "failures": failures}
    return summary, failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id)
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
