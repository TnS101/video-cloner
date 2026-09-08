"""Publish one Workspace command for the corrected Step 3D TextPlus carrier proof."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any, Dict

TASK_ID = "DZSQH7AUHJT_STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
MODE = "STEP_3D_TEXTPLUS_CARRIER_PROBE_V2"
MODULE = "resolve_workspace/modules/step_3D_textplus_carrier_probe_v2.py"
SOURCE_HASH_ALGORITHM = "sha256_text_lf_normalized"
SOURCE_PATHS = (
    MODULE,
    "resolve_workspace/modules/step_3D_textplus_carrier_probe.py",
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
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
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

    queue = root / ".agent" / "commands"
    task_report_root = root / ".agent" / "reports" / TASK_ID
    task_report_root.mkdir(parents=True, exist_ok=True)
    for state in ("pending", "running", "completed", "failed"):
        state_dir = queue / state
        state_dir.mkdir(parents=True, exist_ok=True)
        if list(state_dir.glob(f"*{TASK_ID}*.json")):
            raise ValueError(f"task_command_exists:{state}")

    run_id = run_id_now()
    report_dir = task_report_root / run_id
    report_dir.mkdir(parents=True, exist_ok=False)

    suffix = run_id[-12:]
    timeline_name = f"VC_STEP3D_TEXTPLUS_V2_{suffix}"
    item_name = f"VC_STEP3D_TEXTPLUS_V2_ITEM_{suffix}"
    hashes = {
        relative: normalized_sha256(root / relative)
        for relative in SOURCE_PATHS
    }
    accepted_hash = raw_sha256(root / ACCEPTED_STATE)

    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": utc_now(),
        "artifacts_dir": str(report_dir.relative_to(root)).replace("/", "\\"),
        "status_path": str(
            (report_dir / "status.json").relative_to(root)
        ).replace("/", "\\"),
        "log_path": str(
            (report_dir / "run.log").relative_to(root)
        ).replace("/", "\\"),
        "report_path": str(
            (report_dir / "report.json").relative_to(root)
        ).replace("/", "\\"),
        "accepted_state_path": ACCEPTED_STATE.replace("/", "\\"),
        "accepted_state_sha256": accepted_hash,
        "source_contract": {
            "version": 1,
            "algorithm": SOURCE_HASH_ALGORITHM,
            "hashes": hashes,
        },
        "probe": {
            "source_timeline": "DZsqH7auhjt_textplus_full",
            "timeline_name": timeline_name,
            "item_name": item_name,
            "target_track": 5,
            "target_start_frame": 430,
            "duration_frames": 48,
            "text": "VC_TEXTPLUS_CARRIER_PROBE_V2",
            "center_keyframes": {
                "0": [0.50, 0.50],
                "3": [0.42, 0.58],
            },
            "expected_save_calls": 2,
            "cleanup_required": True,
            "workspace_invocations": 1,
        },
    }

    command_name = f"{TASK_ID}_{run_id}.json"
    command_path = queue / "pending" / command_name
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
