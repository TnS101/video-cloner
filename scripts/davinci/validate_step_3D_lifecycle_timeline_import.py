"""Validate the imported Step 3D lifecycle comparison timeline."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

TASK_ID = 'DZSQH7AUHJT_STEP_3D_LIFECYCLE_TIMELINE_IMPORT_V3'
MODE = "import_lifecycle_fcpxml_timeline"
IMPORTED_TIMELINE_NAME = 'DZsqH7auhjt_textplus_full_step_3D_lifecycle'
SOURCE_TIMELINE_NAME = 'DZsqH7auhjt_textplus_full'
FCPXML_SHA256 = 'a844dc836fc0c6cd54353dee22ee7f01b90ab6500c441434b2a5a49ebe6636c0'
TARGET_WINDOWS = {
    "sub_052": [430, 452],
    "sub_057": [454, 493],
    "sub_058": [456, 492],
    "sub_081": [628, 656],
}
REQUIRED = (
    "import_command.json",
    "publication_receipt.json",
    "imported_timeline_snapshot.json",
    "source_timeline_protection.json",
    "timeline_import_result.json",
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
    rows = []
    queue = root / ".agent/commands"
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
    run_dir = root / ".agent/reports" / TASK_ID / run_id
    failures = []
    for name in REQUIRED:
        path = run_dir / name
        if not path.is_file() or path.stat().st_size == 0:
            failures.append(f"missing_or_empty:{name}")
    if failures:
        return {"ok": False, "task_id": TASK_ID, "run_id": run_id, "failures": failures}, failures

    command = load_json(run_dir / "import_command.json")
    receipt = load_json(run_dir / "publication_receipt.json")
    imported = load_json(run_dir / "imported_timeline_snapshot.json")
    protection = load_json(run_dir / "source_timeline_protection.json")
    import_result = load_json(run_dir / "timeline_import_result.json")
    status = load_json(run_dir / "status.json")
    report = load_json(run_dir / "report.json")

    command_name = f"{TASK_ID}_{run_id}.json"
    queue = root / ".agent/commands"
    completed = queue / "completed" / command_name
    instances = [
        queue / state / command_name
        for state in ("pending", "running", "completed", "failed")
        if (queue / state / command_name).is_file()
    ]
    if instances != [completed]:
        failures.append("command_lifecycle_not_completed")
    command_hash = sha256(completed) if completed.is_file() else None
    if command_hash != receipt.get("command_sha256"):
        failures.append("command_hash_lineage")

    payload = command.get("payload") or {}
    if (
        command.get("task") != TASK_ID
        or command.get("run_id") != run_id
        or command.get("mode") != MODE
        or payload.get("import_permitted") is not True
        or payload.get("replace_existing_timeline") is not False
        or payload.get("save_project") is not False
        or payload.get("fcpxml_sha256") != FCPXML_SHA256
    ):
        failures.append("command_contract")
    if status.get("ok") is not True or status.get("running") is not False:
        failures.append("status_contract")

    classification = report.get("classification")
    if classification not in {"NEW_TIMELINE_IMPORTED", "ALREADY_IMPORTED_MATCHED"}:
        failures.append("classification")
    if report.get("ok") is not True or report.get("failures") not in ([], None):
        failures.append("runtime_report")
    if (
        report.get("imported_timeline_name") != IMPORTED_TIMELINE_NAME
        or report.get("current_timeline_name") != IMPORTED_TIMELINE_NAME
        or report.get("source_timeline_modified") is not False
        or report.get("caption_item_count") != 116
        or report.get("caption_lane_count") != 5
        or report.get("base_video_item_count") != 22
        or report.get("transition_item_count") != 11
        or report.get("save_call_count") != 0
        or report.get("visual_approval_required") is not True
    ):
        failures.append("runtime_counts")

    if (
        imported.get("ok") is not True
        or imported.get("timeline_name") != IMPORTED_TIMELINE_NAME
        or imported.get("caption_item_count") != 116
        or imported.get("caption_lane_count") != 5
        or imported.get("base_video_item_count") != 22
        or imported.get("transition_item_count") != 11
        or len(imported.get("base_video_track_indices") or []) != 1
        or imported.get("transition_track_indices") != imported.get("base_video_track_indices")
        or len(imported.get("caption_track_indices") or []) != 5
        or set(imported.get("base_video_track_indices") or [])
           & set(imported.get("caption_track_indices") or [])
        or imported.get("unmatched_video_item_count") != 0
    ):
        failures.append("imported_timeline_contract")
    target_results = imported.get("target_results") or {}
    for cue_id, window in TARGET_WINDOWS.items():
        row = target_results.get(cue_id) or {}
        if row.get("actual_window") != window or row.get("matched") is not True:
            failures.append(f"target_window:{cue_id}")

    if (
        protection.get("ok") is not True
        or protection.get("source_timeline_name") != SOURCE_TIMELINE_NAME
        or protection.get("source_timeline_unchanged") is not True
        or protection.get("source_before") != protection.get("source_after")
        or protection.get("save_call_count") != 0
    ):
        failures.append("source_timeline_protection")

    if (
        import_result.get("ok") is not True
        or import_result.get("fcpxml_sha256") != FCPXML_SHA256
        or import_result.get("imported_timeline_name") != IMPORTED_TIMELINE_NAME
        or import_result.get("current_timeline_name") != IMPORTED_TIMELINE_NAME
        or import_result.get("visual_approval_required") is not True
    ):
        failures.append("import_result_contract")

    latest_path = root / ".agent/state/latest_accepted.json"
    latest_hash = sha256(latest_path) if latest_path.is_file() else None
    if latest_hash != payload.get("accepted_state_sha256"):
        failures.append("accepted_state_changed")
    expected_commands = payload.get("command_inventory_before_publication")
    actual_commands = command_inventory(root, run_id)
    if actual_commands != expected_commands:
        failures.append("non_current_command_inventory_changed")
    if list((queue / "pending").glob("*.json")) or list((queue / "running").glob("*.json")):
        failures.append("active_command_after_run")

    result = {
        "ok": not failures,
        "task_id": TASK_ID,
        "run_id": run_id,
        "classification": classification if not failures else None,
        "command_sha256": command_hash,
        "imported_timeline_name": IMPORTED_TIMELINE_NAME,
        "current_timeline_name": report.get("current_timeline_name"),
        "caption_item_count": report.get("caption_item_count"),
        "caption_lane_count": report.get("caption_lane_count"),
        "base_video_track_indices": imported.get("base_video_track_indices"),
        "transition_item_count": report.get("transition_item_count"),
        "transition_track_indices": imported.get("transition_track_indices"),
        "caption_track_indices": imported.get("caption_track_indices"),
        "source_timeline_unchanged": protection.get("source_timeline_unchanged"),
        "target_results": target_results,
        "visual_approval_required": True,
        "next_boundary": "Compare the imported timeline visually with the original timeline, especially COME/that/KNOWS/the lifecycle windows.",
        "failures": failures,
    }
    return result, failures


def final_report(result: dict[str, Any]) -> str:
    return "\n".join([
        "# Approach",
        "",
        "Imported the calibrated Step 3D lifecycle FCPXML as a separate Resolve timeline, selected it for review, validated 116 caption items across five lanes, and proved that the original timeline remained unchanged.",
        "",
        "# Key evidence",
        "",
        f"- Run ID: `{result['run_id']}`.",
        f"- Classification: `{result.get('classification')}`.",
        f"- Imported timeline: `{IMPORTED_TIMELINE_NAME}`.",
        "- Base clips: 22; native transitions: 11; captions: 116 across five lifecycle lanes.",
        "- Original timeline unchanged: true.",
        "- Approved windows preserved: sub_052 [430,452), sub_057 [454,493), sub_058 [456,492), sub_081 [628,656).",
        "- Project was not explicitly saved by the command.",
        "",
        "# PASS or FAIL",
        "",
        "PASS — STEP_3D_LIFECYCLE_TIMELINE_IMPORTED_FOR_VISUAL_REVIEW",
        "",
        "# Next boundary",
        "",
        "Visually compare the imported timeline with the original timeline before accepting it or replacing any timeline.",
        "",
        "Manual visual approval required: YES",
        "",
    ])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    result, failures = validate(args.root, args.run_id)
    run_dir = args.root.resolve() / ".agent/reports" / TASK_ID / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "lifecycle_timeline_import_validation.json", result)
    if not failures:
        (run_dir / "FINAL_REPORT.md").write_text(final_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


if __name__ == "__main__":
    raise SystemExit(main())
