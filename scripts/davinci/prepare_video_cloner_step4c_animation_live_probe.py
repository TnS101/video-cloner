"""Publish the one authoritative STEP 4C disposable animation probe command."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

TASK_ID = "VIDEO_CLONER_STEP4C_ANIMATION_LIVE_PROBE_V1"
MODE = "step4c_animation_live_probe"
MODULE = "resolve_workspace/modules/video_cloner_step4c_animation_live_probe.py"
SOURCES = (
    MODULE,
    "resolve_workspace/resolve_apply_caption_animation_step_3C.py",
    "resolve_workspace/modules/step_3D_native_textplus_title_probe.py",
    "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py",
    "resolve_workspace/VC_Agent_Bridge.py",
    "scripts/davinci/resolve_apply_video_cloner_metadata.py",
)
REEL1 = "DZsqH7auhjt_textplus_visual_first_full_rollout_polish_v4_confirmed74_repair_metrics_v1_occlusion_complete_v4_flash_transition_v4"
REEL2 = "DcJRJtUKScu_standalone_timeline"


def _hash(path: Path) -> str:
    data = path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def build_payload(disposable_name: str, disposable_uid: str | None = None) -> dict[str, Any]:
    payload = {
        "expected_project": "New Project 1", "protected_timelines": [REEL1, REEL2],
        "disposable_timeline_name": disposable_name, "ownership_required": "NEWLY_CREATED",
        "mutation_permitted": True, "cleanup_permitted": False, "workspace_invocations": 1,
    }
    if disposable_uid is not None:
        payload.update({
            "expected_disposable_uid": disposable_uid,
            "ownership_required": "EXISTING_NEWLY_CREATED",
            "reuse_existing_owned_disposable": True,
        })
    return payload


def publish(root: Path, disposable_name: str | None = None, disposable_uid: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    if not (root / "AGENTS.md").is_file():
        raise ValueError("repository_root")
    queue = root / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    if (disposable_name is None) != (disposable_uid is None):
        raise ValueError("existing_disposable_identity")
    for relative in SOURCES:
        if not (root / relative).is_file():
            raise ValueError(f"source_missing:{relative}")

    run_id = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex
    report_dir = root / ".agent/reports" / TASK_ID / run_id
    if report_dir.exists():
        raise ValueError("report_exists")
    report_dir.mkdir(parents=True)
    disposable_name = disposable_name or "VC_STEP4C_ANIMATION_PROBE_" + run_id[-12:]
    if not disposable_name.startswith("VC_STEP4C_ANIMATION_PROBE_"):
        raise ValueError("disposable_name")
    command = {
        "schema_version": 1, "task_id": TASK_ID, "run_id": run_id, "mode": MODE, "module": MODULE,
        "published_at": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "report.json").relative_to(root)).replace("/", "\\"),
        "source_contract": {"version": 1, "algorithm": "sha256_text_lf_normalized", "hashes": {path: _hash(root / path) for path in SOURCES}},
        "payload": build_payload(disposable_name, disposable_uid),
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    _write(report_dir / "command.json", command)
    _write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir),
               "disposable_timeline_name": disposable_name, "manual_action": "Workspace > Scripts > VC_Run_Agent_Task", "workspace_invocations": 1}
    _write(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--existing-disposable-name")
    parser.add_argument("--existing-disposable-uid")
    args = parser.parse_args()
    receipt = publish(Path(args.root), args.existing_disposable_name, args.existing_disposable_uid)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    print("MANUAL_ACTION_REQUIRED: Workspace > Scripts > VC_Run_Agent_Task")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
