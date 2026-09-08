"""Publish one immutable Reel #2 Phase 4B read-only preflight command."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from resolve_workspace.modules.video_cloner_phase4b_readonly_preflight import ACTION, MODE, TASK_ID
from resolve_workspace.modules.video_cloner_phase4b_timeline_application import parse_fcpxml_contract, sha256

MODULE = "resolve_workspace/modules/video_cloner_phase4b_readonly_preflight.py"
ARTIFACT = "data/DcJRJtUKScu/davinci/DcJRJtUKScu_standalone_timeline.fcpxml"
ARTIFACT_SHA256 = "5957572c093d8dd3dbc95a3512559fc180402b5b359c8bc4a39fd131a8a1eae4"
TARGET = "DcJRJtUKScu_standalone_timeline"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def publish(root: Path, run_id: str | None = None) -> dict[str, object]:
    root = root.resolve()
    artifact = (root / ARTIFACT).resolve()
    if not (root / "AGENTS.md").is_file() or not (root / MODULE).is_file():
        raise ValueError("repository_contract")
    if sha256(artifact) != ARTIFACT_SHA256:
        raise ValueError("fcpxml_hash")
    contract = parse_fcpxml_contract(artifact)
    if contract["timeline_name"] != TARGET or (len(contract["clips"]), contract["duration_frames"], contract["fps"]) != (14, 854, 24):
        raise ValueError("artifact_contract")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    for state in ("pending", "running"):
        active = sorted((queue / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    run_id = run_id or allocate_run_id()
    if re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", run_id) is None:
        raise ValueError("run_id")
    operation_id = hashlib.sha256(f"{ACTION}\n{ARTIFACT_SHA256}\n{TARGET}".encode()).hexdigest()
    relative_report = f".agent/reports/{TASK_ID}/{run_id}"
    report_dir = root / relative_report
    report_dir.mkdir(parents=True, exist_ok=False)
    command = {
        "schema_version": 1,
        "task": TASK_ID,
        "run_id": run_id,
        "module": MODULE,
        "mode": MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "report_dir": relative_report,
            "action": ACTION,
            "operation_id": operation_id,
            "read_only": True,
            "mutation_permitted": False,
            "fcpxml_path": str(artifact),
            "fcpxml_sha256": ARTIFACT_SHA256,
            "target_timeline_name": TARGET,
            "expected_clip_count": 14,
            "expected_duration_frames": 854,
            "expected_fps": 24,
        },
    }
    name = f"{TASK_ID}_{run_id}.json"
    pending = queue / "pending" / name
    write_json(pending, command)
    write_json(report_dir / "preflight_command.json", command)
    receipt = {
        "ok": True,
        "task_id": TASK_ID,
        "run_id": run_id,
        "operation_id": operation_id,
        "command_path": str(pending.relative_to(root)).replace("\\", "/"),
        "command_sha256": sha256(pending),
        "command_count": 1,
        "manual_action_required": "Workspace > Scripts > VC_Run_Agent_Task exactly once",
    }
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        result = publish(args.root, args.run_id)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
