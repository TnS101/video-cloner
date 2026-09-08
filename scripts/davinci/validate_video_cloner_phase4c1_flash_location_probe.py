"""Validate completed Flash-location evidence without contacting Resolve."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4c1_flash_location_probe import ACTION, CLASSIFICATIONS, MODE, TASK_ID, ZERO_MUTATIONS, canonical_sha256, validate_identity
from scripts.davinci.prepare_video_cloner_phase4c1_flash_location_probe import MODULE


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(path.name)
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(root: Path, run_id: str) -> tuple[dict, list[str]]:
    root = root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / run_id
    required = ("probe_command.json", "publication_receipt.json", "status.json", "report.json", "run.log")
    failures = [f"missing:{name}" for name in required if not (run_dir / name).is_file() or (run_dir / name).stat().st_size == 0]
    if failures:
        return {"ok": False, "run_id": run_id, "failures": failures}, failures
    command, receipt, status, report = (load(run_dir / name) for name in ("probe_command.json", "publication_receipt.json", "status.json", "report.json"))
    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent" / "commands"
    completed = queue / "completed" / command_name
    locations = [queue / state / command_name for state in ("pending", "running", "completed", "failed") if (queue / state / command_name).is_file()]
    if locations != [completed] or not completed.is_file() or sha256(completed) != receipt.get("command_sha256"):
        failures.append("command_lifecycle")
    payload = command.get("payload") or {}
    operation_id = receipt.get("operation_id")
    if command.get("task") != TASK_ID or command.get("module") != MODULE or command.get("mode") != MODE or payload.get("action") != ACTION or payload.get("operation_id") != operation_id or report.get("operation_id") != operation_id:
        failures.append("command_identity")
    if payload.get("read_only") is not True or payload.get("mutation_permitted") is not False:
        failures.append("read_only_contract")
    identity = payload.get("expected_flash_identity")
    try:
        validate_identity(identity)
        if canonical_sha256(identity) != payload.get("expected_flash_identity_sha256"):
            raise ValueError("hash")
    except Exception:
        failures.append("flash_identity")
    inventory = report.get("timeline_inventory")
    if not isinstance(inventory, list) or report.get("timeline_count") != len(inventory) or any(not isinstance(row, dict) or row.get("timeline_index") != index for index, row in enumerate(inventory, 1)):
        failures.append("timeline_inventory")
    elif sum(int(row.get("video_item_count") or 0) for row in inventory) != report.get("inspected_video_item_count"):
        failures.append("item_inventory")
    expected_target = payload.get("expected_target_timeline_name")
    target_occurrences = sum(row.get("timeline_name") == expected_target for row in inventory) if isinstance(inventory, list) else -1
    if report.get("expected_target_occurrence_count") != target_occurrences:
        failures.append("target_inventory")
    matches = report.get("matches")
    if not isinstance(matches, list):
        failures.append("matches")
        matches = []
    required_signals = ("name_match", "range_match", "duration_match", "neutral_media_match", "fusion_tool_match", "fusion_policy_match")
    for row in matches:
        if not isinstance(row, dict) or row.get("classification") not in {"EXACT_FLASH_MATCH", "PARTIAL_FLASH_MATCH"} or any(type(row.get(key)) is not bool for key in required_signals):
            failures.append("match_surface")
            break
        exact = all(row[key] for key in required_signals)
        meaningful = any(row[key] for key in ("name_match", "range_match", "neutral_media_match", "fusion_tool_match", "fusion_policy_match"))
        if (row["classification"] == "EXACT_FLASH_MATCH") != exact or not meaningful:
            failures.append("match_semantics")
            break
    exact = [row for row in matches if row.get("classification") == "EXACT_FLASH_MATCH"]
    partial = [row for row in matches if row.get("classification") == "PARTIAL_FLASH_MATCH"]
    classification = report.get("classification")
    if classification not in CLASSIFICATIONS:
        failures.append("project_classification")
    elif classification == "FLASH_MULTIPLE_EXACT_MATCHES" and len(exact) <= 1:
        failures.append("multiple_semantics")
    elif classification == "FLASH_EXACT_MATCH_EXPECTED_TARGET" and (len(exact) != 1 or exact[0].get("timeline_name") != expected_target):
        failures.append("expected_target_semantics")
    elif classification == "FLASH_EXACT_MATCH_OTHER_TIMELINE" and (len(exact) != 1 or exact[0].get("timeline_name") == expected_target):
        failures.append("other_timeline_semantics")
    elif classification == "FLASH_PARTIAL_MATCH_ONLY" and (exact or not partial):
        failures.append("partial_semantics")
    elif classification == "FLASH_ABSENT_PROJECT_WIDE" and matches:
        failures.append("absence_semantics")
    if report.get("exact_match_count") != len(exact) or report.get("partial_match_count") != len(partial):
        failures.append("match_counts")
    if status.get("ok") is not True or report.get("ok") is not True or report.get("project_name") != payload.get("expected_project_name"):
        failures.append("completed_probe")
    if report.get("read_only") is not True or report.get("timeline_modified") is not False or report.get("mutation_counts") != ZERO_MUTATIONS:
        failures.append("zero_mutation")
    summary = {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "operation_id": operation_id, "project_name": report.get("project_name"), "timeline_count": report.get("timeline_count"), "classification": classification, "exact_match_count": len(exact), "partial_match_count": len(partial), "mutation_counts": report.get("mutation_counts"), "failures": failures}
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
