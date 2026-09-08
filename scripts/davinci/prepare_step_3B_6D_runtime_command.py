#!/usr/bin/env python3
"""Validate accepted inputs and atomically publish the single Step 3B.6D command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

TASK_ID = "DZSQH7AUHJT_STEP_3B_6D_RUNTIME_EXECUTION_V1"
PLAN_HASH = "ee6a8fdffbff0f6dc08381ec9180a3bd163aada3bbacf6c6c50d2d6616bdffaf"
PLAN_PATH = ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prepared_plan_one.json"
PLAN_FILE_SHA256 = "59f214ebd38777041fc1071812938a0b96b6a995923f4d2b445cac66aa04f098"
PREREQUISITES = [
    {"path": ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/FINAL_REPORT.md", "sha256": "ef7f3a816b4645c86d4c0e26ed8e0b9c082a3fee7b72a865aa6a8e1b7d07e990"},
    {"path": ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/prerequisite_hash_validation.json", "sha256": "68a77541038ccb4d343e1681f53346fca67a0b118c157bfa00779f4f91f97592"},
    {"path": ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/executable_operation_inventory.json", "sha256": "9a3cf8eb5e39574af50ed5ac9f7bbe5c8c5843e60782c28b309f8f0140ee670b"},
    {"path": ".agent/reports/DZSQH7AUHJT_STEP_3B_6D_BLEND_EXCLUSION_PATCH_V1/20260802T141800914Z_a48873102fbb4280b0c779f8efa94ab1/excluded_operation_inventory.json", "sha256": "faf59ad3a032c9e90a53d39dc08bb702da7acd361c9710b0f8a44b2751c76bf8"},
    {"path": "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_source_geometry_step_3B_6C_idempotency_report.json", "sha256": "c80df451e150207dcfe353acf5b2ead80e2ba50dbec9b55b5b8af5f3642aadfc"},
    {"path": "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_source_geometry_step_3B_6C_idempotency_validation.json", "sha256": "5f5d07695f7fbd456cb7bcbae8dc69e2687fc4da3cb2c4ec641ee29a843b8e5b"},
    {"path": "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_position_full_step_3B_5B_idempotency_report.json", "sha256": "7fd42e11a74f961adf09ea9d7b228b53f9a64fb568de8775322a01bee645f44e"},
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"not_json_object:{path}")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def canonical_hash(value: dict[str, Any]) -> str:
    clean = dict(value)
    clean.pop("plan_hash", None)
    clean.pop("created_at_unix", None)
    raw = json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_command(root: Path, run_id: str) -> dict[str, Any]:
    report_rel = f".agent/reports/{TASK_ID}/{run_id}"
    return {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/step_3B_6D_runtime_execution.py",
        "mode": "contained_geometry_first_application_and_in_run_idempotency",
        "status_path": f"{report_rel}/status.json",
        "log_path": f"{report_rel}/run.log",
        "report_path": f"{report_rel}/report.json",
        "payload": {
            "repository_root": str(root), "report_dir": report_rel,
            "video_id": "DZsqH7auhjt", "project_name": "New Project 1",
            "timeline_name": "DZsqH7auhjt_textplus_full", "track_type": "video",
            "track_index": 3, "expected_v3_count": 116,
            "plan_path": PLAN_PATH, "plan_file_sha256": PLAN_FILE_SHA256,
            "accepted_v3_inventory_path": "data/DZsqH7auhjt/davinci/DZsqH7auhjt_resolve_position_full_step_3B_5B_idempotency_report.json",
            "plan_hash": PLAN_HASH, "allowed_properties": ["Center", "Size"],
            "forbidden_properties": ["Blend", "unknown_or_other"],
            "value_tolerance": 1e-5, "save_settle_sec": 1.5,
            "prerequisites": PREREQUISITES,
        },
    }


def validate_inputs(root: Path) -> list[dict[str, Any]]:
    results = []
    for row in [{"path": PLAN_PATH, "sha256": PLAN_FILE_SHA256}, *PREREQUISITES]:
        path = (root / row["path"]).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("outside_repository") from exc
        actual = sha256(path) if path.is_file() else None
        results.append({**row, "exists": path.is_file(), "actual_sha256": actual, "matched": actual == row["sha256"]})
    if not all(row["matched"] for row in results):
        raise ValueError("prerequisite_hash")
    plan = load_json(root / PLAN_PATH)
    if plan.get("plan_hash") != PLAN_HASH or canonical_hash(plan) != PLAN_HASH:
        raise ValueError("plan_semantic_hash")
    summary = plan.get("summary") or {}
    counts = (summary.get("center_target_count"), summary.get("size_target_count"), summary.get("blend_target_count"), summary.get("other_property_target_count"), summary.get("total_target_count"))
    if counts != (18, 18, 0, 0, 36):
        raise ValueError("operation_inventory")
    cue_ids = [row.get("cue_id") for row in plan.get("rollout_items") or []]
    if cue_ids != ["sub_007", "sub_013", "sub_110", "sub_114"]:
        raise ValueError("cue_inventory")
    return results


def publish(root: Path, run_id: str) -> Path:
    if not re.fullmatch(r"[0-9]{8}T[0-9]{9}Z_[0-9a-f]{32}", run_id):
        raise ValueError("run_id_format")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    if any(path for state in ("pending", "running") for path in (queue / state).glob("*.json")):
        raise ValueError("conflicting_active_command")
    for state in ("running", "completed", "failed"):
        for path in (queue / state).glob("*.json"):
            try:
                if load_json(path).get("run_id") == run_id:
                    raise ValueError("duplicate_run_id")
            except json.JSONDecodeError:
                continue
    report_dir = root / ".agent" / "reports" / TASK_ID / run_id
    if report_dir.exists():
        raise ValueError("conflicting_report_directory")
    report_dir.mkdir(parents=True)
    results = validate_inputs(root)
    command = build_command(root, run_id)
    write_json(report_dir / "prerequisite_hash_validation.json", {"ok": True, "task_id": TASK_ID, "run_id": run_id, "plan_hash": PLAN_HASH, "results": results})
    write_json(report_dir / "runtime_command.json", command)
    destination = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write_json(destination, command)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    destination = publish(root, args.run_id)
    print(json.dumps({"ok": True, "task_id": TASK_ID, "run_id": args.run_id, "command_path": str(destination), "command_count": 1}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
