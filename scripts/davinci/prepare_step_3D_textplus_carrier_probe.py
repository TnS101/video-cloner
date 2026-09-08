"""Publish one Workspace command for the Step 3D genuine TextPlus carrier probe."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_TEXTPLUS_CARRIER_PROBE_V1"
MODE = "STEP_3D_TEXTPLUS_CARRIER_PROBE"
MODULE = "resolve_workspace/modules/step_3D_textplus_carrier_probe.py"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/resolve_apply_video_cloner_metadata.py",
    "resolve_workspace/resolve_apply_caption_animation_step_3C.py",
    "resolve_workspace/VC_Agent_Bridge.py",
)
ACCEPTED_STATE = ".agent/state/latest_accepted.json"


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

    task_report_root = root / ".agent" / "reports" / TASK_ID
    task_report_root.mkdir(parents=True, exist_ok=True)
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        state_dir = queue / state
        if state_dir.is_dir() and list(state_dir.glob(f"*{TASK_ID}*.json")):
            raise ValueError(f"task_command_exists:{state}")

    run_id = run_id_now()
    report_dir = task_report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)
    pending_dir = queue / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    for state in ("running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)

    timeline_name = f"VC_STEP3D_TEXTPLUS_PROBE_{run_id[-12:]}"
    item_name = f"VC_STEP3D_TEXTPLUS_ITEM_{run_id[-12:]}"
    hashes = {relative: normalized_sha256(root / relative) for relative in SOURCE_PATHS}
    accepted_hash = raw_sha256(root / ACCEPTED_STATE)

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
        "accepted_state_sha256": accepted_hash,
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": hashes,
        },
        "probe": {
            "timeline_name": timeline_name,
            "item_name": item_name,
            "text": "VC_TEXTPLUS_CARRIER_PROBE",
            "target_track": 1,
            "duration_frames": 48,
            "keyframe_input": "Center",
            "keyframe_frame": 0,
            "keyframe_value": [0.42, 0.58],
            "expected_save_calls": 2,
            "cleanup_required": True,
        },
    }

    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = pending_dir / command_name
    if command_path.exists():
        raise ValueError("command_collision")
    write_json(report_dir / "probe_command.json", command)
    write_json(command_path, command)
    receipt = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "published_at": command["published_at"],
        "command_path": str(command_path),
        "command_sha256": raw_sha256(command_path),
        "report_dir": str(report_dir),
        "source_contract": command["source_contract"],
        "accepted_state_sha256": accepted_hash,
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
