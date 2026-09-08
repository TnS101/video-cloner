"""Publish one Resolve command to import the Step 3D lifecycle FCPXML timeline."""
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

TASK_ID = 'DZSQH7AUHJT_STEP_3D_LIFECYCLE_TIMELINE_IMPORT_V3'
MODE = "import_lifecycle_fcpxml_timeline"
MODULE_REL = "resolve_workspace/modules/step_3D_import_lifecycle_timeline.py"
FCPXML_REL = 'data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle.fcpxml'
FCPXML_SHA256 = 'a844dc836fc0c6cd54353dee22ee7f01b90ab6500c441434b2a5a49ebe6636c0'
REPORT_REL = 'data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle_report.json'
VALIDATION_REL = 'data/DZsqH7auhjt/davinci/DZsqH7auhjt_textplus_full_timeline_step_3D_lifecycle_validation.json'
EXPECTED_TIMELINE = 'DZsqH7auhjt_textplus_full_step_3D_lifecycle'


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        for path in sorted((queue / state).glob("*.json")):
            if exclude_run_id and exclude_run_id in path.name:
                continue
            rows.append({
                "path": str(path.relative_to(root)).replace("\\", "/"),
                "sha256": sha256(path),
            })
    return rows


def validate_inputs(root: Path) -> dict[str, Any]:
    fcpxml_path = root / FCPXML_REL
    if not fcpxml_path.is_file() or sha256(fcpxml_path) != FCPXML_SHA256:
        raise ValueError("fcpxml_hash")

    compiler_report = load_json(root / REPORT_REL)
    validation = load_json(root / VALIDATION_REL)
    latest = load_json(root / ".agent/state/latest_accepted.json")

    checks = {
        "compiler_success": compiler_report.get("success") is True,
        "compiler_caption_count": (compiler_report.get("timing") or {}).get("cue_count") == 116,
        "compiler_version": "visual_lifecycle" in str(compiler_report.get("version") or ""),
        "validation_ok": validation.get("ok") is True,
        "validation_caption_count": validation.get("caption_count") == 116,
        "validation_lanes": validation.get("lane_count") == 5
        and validation.get("same_lane_overlap_count") == 0,
        "validation_authority": validation.get("visual_primary_count") == 49
        and validation.get("transcript_fallback_count") == 67,
        "validation_animated": validation.get("animated_visual_lifecycle_count") == 8,
        "target_windows": all(
            ((validation.get("target_results") or {}).get(cue_id) or {}).get("matched") is True
            for cue_id in ("sub_052", "sub_057", "sub_058", "sub_081")
        ),
        "accepted_step": latest.get("accepted_step") == "Step 3D calibration",
        "step_3C_stable": latest.get("step_3C_status") == "ACCEPTED_VISUAL_MOTION_LAYER_STABLE"
        and latest.get("step_3C_idempotent") is True,
        "step_3D_complete": latest.get("step_3D_status") == "TARGETED_VISUAL_LIFECYCLE_REDETECTION_COMPLETE",
        "timeline_unmodified": latest.get("timeline_modified") is False,
        "bridge_ready": latest.get("bridge_ready") is True,
    }
    failures = [name for name, passed in checks.items() if not passed]
    if failures:
        raise ValueError("input_contract:" + ",".join(failures))
    return {
        "ok": True,
        "checks": checks,
        "fcpxml_sha256": FCPXML_SHA256,
        "accepted_state_sha256": sha256(root / ".agent/state/latest_accepted.json"),
    }


def validate_no_conflicts(root: Path) -> None:
    queue = root / ".agent" / "commands"
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
    if not (root / MODULE_REL).is_file():
        raise ValueError("runtime_module_missing")
    for state in ("pending", "running", "completed", "failed"):
        (root / ".agent/commands" / state).mkdir(parents=True, exist_ok=True)

    input_validation = validate_inputs(root)
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
            "fcpxml_path": FCPXML_REL,
            "fcpxml_sha256": FCPXML_SHA256,
            "expected_project": 'New Project 1',
            "source_timeline_name": 'DZsqH7auhjt_textplus_full',
            "imported_timeline_name": EXPECTED_TIMELINE,
            "import_permitted": True,
            "replace_existing_timeline": False,
            "save_project": False,
            "accepted_state_sha256": input_validation["accepted_state_sha256"],
            "command_inventory_before_publication": baseline_commands,
            "input_validation": input_validation,
        },
    }
    write_json(command_path, command)
    command_hash = sha256(command_path)
    write_json(report_dir / "import_command.json", command)
    write_json(report_dir / "publication_receipt.json", {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path.relative_to(root)).replace("\\", "/"),
        "command_sha256": command_hash,
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
