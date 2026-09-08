"""Publish one Resolve command to apply accepted positions and animations to the lifecycle timeline."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

TASK_ID = "DZSQH7AUHJT_STEP_3D_LIFECYCLE_VISUAL_LAYER_FUSION_PAGE_RECOVERY_V1"
MODE = "apply_step_3D_visual_layers_fusion_page_recovery_v1"
MODULE_REL = "resolve_workspace/modules/step_3D_apply_visual_layers.py"
SOURCE_TIMELINE_NAME = "DZsqH7auhjt_textplus_full"
TARGET_TIMELINE_NAME = "DZsqH7auhjt_textplus_full_step_3D_lifecycle"
POSITION_HELPER_REL = "resolve_workspace/resolve_apply_caption_position_full_step_3B_5.py"
ANIMATION_HELPER_REL = "resolve_workspace/resolve_apply_caption_animation_step_3C.py"
IMPORT_HELPER_REL = "resolve_workspace/modules/step_3D_import_lifecycle_timeline.py"
POSITION_PLAN_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_position_full_plan_step_3B_5B.json"
ANIMATION_TARGETS_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_animation_step_3C_source_targets.json"
LIFECYCLE_PLAN_REL = "data/DZsqH7auhjt/analysis/DZsqH7auhjt_caption_lifecycle_authority_step_3D_calibrated.json"
FCPXML_REL = "data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml"
SOURCE_HASH_CONTRACT_VERSION = 2
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
CLONE_STRATEGY = "IMPORT_THEN_FUSION_PAGE_LOAD_AND_ORPHAN_RECOVERY_V4"
SOURCE_DEPENDENCY_PATHS = (
    MODULE_REL,
    POSITION_HELPER_REL,
    ANIMATION_HELPER_REL,
    IMPORT_HELPER_REL,
    POSITION_PLAN_REL,
    ANIMATION_TARGETS_REL,
    LIFECYCLE_PLAN_REL,
    FCPXML_REL,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text_lf(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def source_hash_manifest(root: Path) -> dict[str, str]:
    manifest: dict[str, str] = {}
    for relative in SOURCE_DEPENDENCY_PATHS:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"source_missing:{relative}")
        manifest[relative] = sha256_text_lf(path)
    return manifest


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected_json_object:{path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("." + path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    milliseconds = now.microsecond // 1000
    return f"{now:%Y%m%dT%H%M%S}{milliseconds:03d}Z_{uuid4().hex}"


def valid_run_id(value: str) -> bool:
    return re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", value) is not None


def command_inventory(root: Path, exclude_run_id: str = "") -> list[dict[str, Any]]:
    rows = []
    queue = root / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id and exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def latest_successful_import_validation(root: Path) -> dict[str, Any]:
    report_root = root / ".agent/reports/DZSQH7AUHJT_STEP_3D_LIFECYCLE_TIMELINE_IMPORT_V3"
    candidates = sorted(
        report_root.glob("*/lifecycle_timeline_import_validation.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        value = load_json(path)
        if value.get("ok") is True:
            return {"path": str(path.relative_to(root)).replace("\\", "/"), "value": value}
    raise ValueError("successful_import_validation_missing")


def validate_semantic_inputs(root: Path) -> dict[str, Any]:
    source_hashes = source_hash_manifest(root)

    position = load_json(root / POSITION_PLAN_REL)
    lifecycle = load_json(root / LIFECYCLE_PLAN_REL)
    animation = load_json(root / ANIMATION_TARGETS_REL)
    accepted = load_json(root / ".agent/state/latest_accepted.json")
    imported = latest_successful_import_validation(root)
    imported_value = imported["value"]

    position_items = [
        row for row in (position.get("items") or [])
        if isinstance(row, dict) and row.get("rollout_target") is True
    ]
    lifecycle_items = [row for row in (lifecycle.get("layers") or []) if isinstance(row, dict)]
    animation_items = [row for row in (animation.get("items") or []) if isinstance(row, dict)]
    lifecycle_summary = lifecycle.get("summary") or {}
    checks = {
        "position_plan_ok": position.get("ok") is True and len(position_items) == 116,
        "lifecycle_plan_ok": lifecycle.get("ok") is True and len(lifecycle_items) == 116,
        "lifecycle_authority": lifecycle_summary.get("visual_primary_count") == 49
        and lifecycle_summary.get("transcript_fallback_count") == 67,
        "mandatory_queue_empty": lifecycle_summary.get("mandatory_redetection_count") == 0,
        "animation_targets_ok": animation.get("ok") is True
        and len(animation_items) == 8
        and sum(len(row.get("targets") or []) for row in animation_items) == 16,
        "cue_partition": {str(row.get("cue_id")) for row in position_items}
        == {str(row.get("cue_id")) for row in lifecycle_items},
        "accepted_step": accepted.get("accepted_step") == "Step 3D calibration",
        "step_3C_stable": accepted.get("step_3C_status") == "ACCEPTED_VISUAL_MOTION_LAYER_STABLE"
        and accepted.get("step_3C_idempotent") is True,
        "import_technical_pass": imported_value.get("classification") == "ALREADY_IMPORTED_MATCHED"
        and imported_value.get("caption_item_count") == 116
        and imported_value.get("caption_lane_count") == 5
        and imported_value.get("transition_item_count") == 11
        and imported_value.get("source_timeline_unchanged") is True,
        "bridge_ready": accepted.get("bridge_ready") is True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("input_contract:" + ",".join(failures))
    return {
        "ok": True,
        "checks": checks,
        "accepted_state_sha256": sha256(root / ".agent/state/latest_accepted.json"),
        "import_validation_path": imported["path"],
        "source_hash_contract_version": SOURCE_HASH_CONTRACT_VERSION,
        "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
        "source_hashes": source_hashes,
    }


def validate_no_conflicts(root: Path) -> None:
    queue = root / ".agent/commands"
    for state in ("pending", "running"):
        active = sorted((queue / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    for state in ("pending", "running", "completed", "failed"):
        existing = sorted((queue / state).glob(f"*{TASK_ID}*.json"))
        if existing:
            raise ValueError(f"task_command_already_exists:{state}:{existing[0].name}")
    if (root / ".agent/reports" / TASK_ID).exists():
        raise ValueError("task_report_root_already_exists")


def publish(root: Path, run_id: str | None = None) -> Path:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    if not (root / "resolve_workspace/VC_Agent_Bridge.py").is_file():
        raise ValueError("bridge_missing")
    for state in ("pending", "running", "completed", "failed"):
        (root / ".agent/commands" / state).mkdir(parents=True, exist_ok=True)

    input_validation = validate_semantic_inputs(root)
    validate_no_conflicts(root)
    baseline_commands = command_inventory(root)
    run_id = run_id or allocate_run_id()
    if not valid_run_id(run_id):
        raise ValueError("run_id")

    relative_report_dir = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report_dir
    report_dir.mkdir(parents=True, exist_ok=False)
    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = root / ".agent/commands/pending" / command_name
    command = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": MODULE_REL,
        "mode": MODE,
        "status_path": f"{relative_report_dir}/status.json",
        "log_path": f"{relative_report_dir}/run.log",
        "report_path": f"{relative_report_dir}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report_dir,
            "expected_project": "New Project 1",
            "source_timeline_name": SOURCE_TIMELINE_NAME,
            "target_timeline_name": TARGET_TIMELINE_NAME,
            "apply_permitted": True,
            "create_timeline": False,
            "delete_timeline": False,
            "save_project": True,
            "clone_source_fusion_comps": True,
            "clone_strategy": CLONE_STRATEGY,
            "activate_fusion_page": True,
            "accepted_state_sha256": input_validation["accepted_state_sha256"],
            "source_hash_contract_version": input_validation["source_hash_contract_version"],
            "source_hash_algorithm": input_validation["source_hash_algorithm"],
            "source_hashes": input_validation["source_hashes"],
            "command_inventory_before_publication": baseline_commands,
            "input_validation": input_validation,
        },
    }
    write_json(command_path, command)
    command_hash = sha256(command_path)
    write_json(report_dir / "visual_layer_command.json", command)
    write_json(report_dir / "publication_receipt.json", {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("\\", "/"),
        "command_sha256": command_hash,
        "source_hash_contract_version": SOURCE_HASH_CONTRACT_VERSION,
        "source_hash_algorithm": SOURCE_HASH_ALGORITHM,
        "source_dependency_count": len(SOURCE_DEPENDENCY_PATHS),
        "pending_observed": command_path.is_file(),
        "manual_action_required": "Run Workspace > Scripts > VC_Run_Agent_Task exactly once.",
    })
    print(json.dumps({
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path),
        "command_sha256": command_hash,
        "manual_action_required": "Run Workspace > Scripts > VC_Run_Agent_Task exactly once.",
    }, indent=2))
    return command_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        publish(args.root, args.run_id)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
