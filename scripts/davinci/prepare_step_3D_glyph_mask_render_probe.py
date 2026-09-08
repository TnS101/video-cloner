"""Publish one Resolve Workspace command for the glyph-mask render probe."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_GLYPH_MASK_RENDER_PROBE_V1"
MODE = "STEP_3D_GLYPH_MASK_RENDER_PROBE"
MODULE = "resolve_workspace/modules/step_3D_glyph_mask_render_probe.py"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/step_3D_full_lifecycle_textplus_rollout.py",
    "resolve_workspace/modules/step_3D_visual_instance_correction.py",
    "resolve_workspace/modules/step_3D_media_backed_fusion_clone.py",
    "resolve_workspace/modules/step_3D_existing_textplus_clone_probe.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)
ACCEPTED_STATE = ".agent/state/latest_accepted.json"
V5_TASK_ID = "DZSQH7AUHJT_STEP_3D_FULL_LIFECYCLE_TEXTPLUS_ROLLOUT_V5"
V5_RUN_ID = "20260805T202712503703Z_e039870f2fb44156a6c662d1df9c2a77"
V5_REPORT = f".agent/reports/{V5_TASK_ID}/{V5_RUN_ID}/report.json"
V5_PLAN = f".agent/reports/{V5_TASK_ID}/{V5_RUN_ID}/rollout_plan.json"
SOURCE_TIMELINE = "DZsqH7auhjt_textplus_full_step_3D_complete"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}_{uuid.uuid4().hex}"


def normalized_sha256(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def raw_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def active_commands(root: Path) -> list[Path]:
    queue = root / ".agent" / "commands"
    out = []
    for state in ("pending", "running"):
        directory = queue / state
        if directory.is_dir():
            out.extend(sorted(directory.glob("*.json")))
    return out


def validate_v5_contract(root: Path) -> Dict[str, Any]:
    report_path = root / V5_REPORT
    plan_path = root / V5_PLAN
    if not report_path.is_file() or not plan_path.is_file():
        raise ValueError("v5_evidence_missing")
    report = load_json(report_path)
    plan = load_json(plan_path)
    instances = plan.get("instances") if isinstance(plan.get("instances"), list) else []
    names = [str(row.get("target_name") or "") for row in instances if isinstance(row, dict)]
    checks = {
        "task_id": report.get("task_id") == V5_TASK_ID,
        "run_id": report.get("run_id") == V5_RUN_ID,
        "ok": report.get("ok") is True,
        "timeline": report.get("final_timeline_name") == SOURCE_TIMELINE,
        "kept": report.get("final_timeline_kept") is True,
        "persistent": report.get("persistent_instance_count") == 115,
        "plan_count": len(instances) == 115,
        "target_names": len(names) == 115 and len(set(names)) == 115 and all(names),
    }
    if not all(checks.values()):
        raise ValueError(f"v5_contract:{checks}")
    return checks


def publish(root: Path) -> Dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    active = active_commands(root)
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    for relative in (*SOURCE_PATHS, ACCEPTED_STATE):
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")
    v5_checks = validate_v5_contract(root)

    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
        if list((queue / state).glob(f"*{TASK_ID}*.json")):
            raise ValueError(f"task_command_exists:{state}")
    task_report_root = root / ".agent" / "reports" / TASK_ID
    if task_report_root.exists():
        raise ValueError("task_report_exists")
    task_report_root.mkdir(parents=True)

    run_id = run_id_now()
    report_dir = task_report_root / run_id
    report_dir.mkdir()
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "report.json").relative_to(root)).replace("/", "\\"),
        "accepted_state_path": ACCEPTED_STATE.replace("/", "\\"),
        "accepted_state_sha256": raw_sha256(root / ACCEPTED_STATE),
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS},
        },
        "probe": {
            "source_timeline_name": SOURCE_TIMELINE,
            "v5_task_id": V5_TASK_ID,
            "v5_run_id": V5_RUN_ID,
            "frame_in": 420,
            "frame_out": 462,
            "target_frame_in": 428,
            "target_frame_out": 451,
            "expected_frame_count": 43,
            "expected_textplus_count": 115,
            "render_policy": "lossless_image_sequence_only",
            "cleanup_on_success": True,
            "cleanup_on_failure": True,
            "workspace_invocation_count": 1,
        },
    }
    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = queue / "pending" / command_name
    write_json(report_dir / "glyph_probe_command.json", command)
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "published_at": command["published_at"],
        "command_path": str(command_path),
        "command_sha256": raw_sha256(command_path),
        "report_dir": str(report_dir),
        "v5_contract": v5_checks,
        "source_contract": command["source_contract"],
        "accepted_state_sha256": command["accepted_state_sha256"],
        "manual_action": "Workspace > Scripts > VC_Run_Agent_Task",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    receipt = publish(Path(args.root))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    print("MANUAL_ACTION_REQUIRED: Workspace > Scripts > VC_Run_Agent_Task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
