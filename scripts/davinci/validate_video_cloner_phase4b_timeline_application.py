"""Validate one completed Phase 4B bridge run without contacting Resolve."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4b_timeline_application import TASK_ID, parse_fcpxml_contract, sha256

REQUIRED = ("import_command.json", "publication_receipt.json", "pre_timeline_inventory.json", "target_timeline_snapshot.json", "protected_timeline_evidence.json", "timeline_import_result.json", "status.json", "report.json", "run.log")


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(path.name)
    return value


def validate(root: Path, run_id: str, expected_classification: str | None = None) -> tuple[dict, list[str]]:
    root = root.resolve()
    run_dir = root / ".agent" / "reports" / TASK_ID / run_id
    failures = [f"missing:{name}" for name in REQUIRED if not (run_dir / name).is_file() or (run_dir / name).stat().st_size == 0]
    if failures:
        return {"ok": False, "run_id": run_id, "failures": failures}, failures
    command, receipt, status, report = (load(run_dir / name) for name in ("import_command.json", "publication_receipt.json", "status.json", "report.json"))
    target = load(run_dir / "target_timeline_snapshot.json")
    protection = load(run_dir / "protected_timeline_evidence.json")
    result = load(run_dir / "timeline_import_result.json")
    before = load(run_dir / "pre_timeline_inventory.json").get("timelines") or []
    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent" / "commands"
    completed = queue / "completed" / command_name
    locations = [queue / state / command_name for state in ("pending", "running", "completed", "failed") if (queue / state / command_name).is_file()]
    if locations != [completed] or not completed.is_file() or sha256(completed) != receipt.get("command_sha256"):
        failures.append("command_lifecycle")
    payload = command.get("payload") or {}
    if command.get("task") != TASK_ID or payload.get("replace_existing_timeline") is not False or payload.get("save_project") is not False or payload.get("import_permitted") is not True:
        failures.append("command_contract")
    try:
        fcpxml = Path(str(payload.get("fcpxml_path") or "")).resolve()
        contract = parse_fcpxml_contract(fcpxml)
        expected = {"expected_clip_count": len(contract["clips"]), "expected_duration_frames": contract["duration_frames"], "expected_fps": contract["fps"]}
        if sha256(fcpxml) != payload.get("fcpxml_sha256") or any(type(payload.get(key)) is not int or payload.get(key) != value for key, value in expected.items()) or payload.get("target_timeline_name") != contract["timeline_name"]:
            failures.append("artifact_contract")
    except Exception:
        contract = None
        failures.append("artifact_contract")
    classification = report.get("classification")
    if classification not in {"NEW_ISOLATED_TIMELINE_IMPORTED", "ALREADY_VALID_REUSED"} or (expected_classification and classification != expected_classification):
        failures.append("classification")
    if status.get("ok") is not True or report.get("ok") is not True or report.get("failures") not in ([], None):
        failures.append("runtime_status")
    forbidden = ((target.get("forbidden_operation_counts") or {}))
    if contract is None or target.get("ok") is not True or target.get("clip_count") != len(contract["clips"]) or target.get("fps") != contract["fps"] or target.get("duration_frames") != contract["duration_frames"] or any(forbidden.values()):
        failures.append("target_contract")
    after = result.get("timeline_inventory_after") or []
    target_name = payload.get("target_timeline_name")
    key = lambda row: (row.get("name"), row.get("signature"))
    non_target_before = [row for row in before if row.get("name") != target_name]
    non_target_after = [row for row in after if row.get("name") != target_name]
    expected_delta = 1 if classification == "NEW_ISOLATED_TIMELINE_IMPORTED" else 0
    expected_before_targets = 0 if expected_delta else 1
    inventory_ok = (
        sum(row.get("name") == target_name for row in before) == expected_before_targets
        and sum(row.get("name") == target_name for row in after) == 1
        and len(after) - len(before) == expected_delta
        and Counter(map(key, non_target_before)) == Counter(map(key, non_target_after))
    )
    evidence_inventory_ok = (
        result.get("timeline_inventory_before") == before
        and protection.get("inventory_before") == before
        and protection.get("inventory_after") == after
        and protection.get("inventory_delta") == expected_delta
    )
    if protection.get("ok") is not True or protection.get("unchanged") is not True or protection.get("before") != non_target_before or protection.get("after") != non_target_after or not inventory_ok or not evidence_inventory_ok:
        failures.append("non_target_inventory")
    if report.get("import_call_count") != expected_delta or result.get("import_call_count") != expected_delta:
        failures.append("import_semantics")
    if result.get("ok") is not True or result.get("save_project_count") != 0 or result.get("fcpxml_sha256") != payload.get("fcpxml_sha256") or report.get("project_name") != payload.get("expected_project") or result.get("project_name") != payload.get("expected_project") or report.get("target_timeline_name") != target_name or result.get("target_timeline_name") != target_name:
        failures.append("result_contract")
    summary = {"ok": not failures, "task_id": TASK_ID, "run_id": run_id, "classification": classification, "project_name": report.get("project_name"), "target_timeline_name": report.get("target_timeline_name"), "protected_timeline_name": report.get("protected_timeline_name"), "clip_count": target.get("clip_count"), "fps": target.get("fps"), "duration_frames": target.get("duration_frames"), "forbidden_operation_counts": forbidden, "protected_timeline_unchanged": protection.get("unchanged"), "import_call_count": report.get("import_call_count"), "save_project_count": report.get("save_project_count"), "operation_id": report.get("operation_id"), "failures": failures}
    return summary, failures


def final_report(result: dict) -> str:
    return "\n".join([
        "# Approach",
        "",
        "Imported or safely reused the exact-hash Phase 4A cut-only FCPXML through the repository Resolve bridge, validated every source/timeline range, and proved the accepted timeline remained unchanged.",
        "",
        "# Files changed",
        "",
        "The live run created only the isolated target timeline and immutable task evidence.",
        "",
        "# Commands run",
        "",
        "Prepare command, one bridge invocation, persistent Resolve readback, and offline validation.",
        "",
        "# Key evidence",
        "",
        f"- Run ID: `{result.get('run_id')}`.",
        f"- Classification: `{result.get('classification')}`.",
        f"- Project: `{result.get('project_name')}`.",
        f"- Target timeline: `{result.get('target_timeline_name')}`; {result.get('clip_count')} clips, {result.get('fps')} fps, {result.get('duration_frames')} frames.",
        f"- All pre-existing non-target timelines unchanged: `{result.get('protected_timeline_unchanged')}`.",
        f"- Import calls: `{result.get('import_call_count')}`; SaveProject calls: `{result.get('save_project_count')}`.",
        f"- Forbidden-operation counts: `{json.dumps(result.get('forbidden_operation_counts') or {}, sort_keys=True)}`.",
        "",
        "# PASS or FAIL",
        "",
        "PASS — PASS_PHASE4B_RESOLVE_TIMELINE_APPLICATION_V1",
        "",
        "# Exact blocker or remaining risk",
        "",
        "None within Phase 4B. The project was intentionally not explicitly saved.",
        "",
        "Manual visual approval required: NO",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-classification")
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id, args.expected_classification)
    run_dir = args.root.resolve() / ".agent" / "reports" / TASK_ID / args.run_id
    (run_dir / "validation.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not failures:
        (run_dir / "FINAL_REPORT.md").write_text(final_report(result), encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
