"""Publish one guarded Phase 4B cut-only FCPXML import command."""
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

from resolve_workspace.modules.video_cloner_phase4b_timeline_application import MODE, TASK_ID, parse_fcpxml_contract, sha256

MODULE = "resolve_workspace/modules/video_cloner_phase4b_timeline_application.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def allocate_run_id() -> str:
    now = datetime.now(timezone.utc)
    return f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"


def valid_run_id(value: str) -> bool:
    return re.fullmatch(r"\d{8}T\d{9}Z_[0-9a-f]{32}", value) is not None


def publish(root: Path, fcpxml: Path, expected_sha256: str, project: str, target: str, protected: str | None = None, run_id: str | None = None) -> dict[str, object]:
    root = root.resolve()
    fcpxml = fcpxml.resolve()
    if not (root / "AGENTS.md").is_file() or not (root / MODULE).is_file():
        raise ValueError("repository_contract")
    if sha256(fcpxml) != expected_sha256:
        raise ValueError("fcpxml_hash")
    contract = parse_fcpxml_contract(fcpxml)
    if contract["timeline_name"] != target or not project or (protected and protected == target):
        raise ValueError("explicit_identity_contract")
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    for state in ("pending", "running"):
        active = sorted((queue / state).glob("*.json"))
        if active:
            raise ValueError(f"active_command:{state}:{active[0].name}")
    run_id = run_id or allocate_run_id()
    if not valid_run_id(run_id):
        raise ValueError("run_id")
    operation_id = hashlib.sha256(f"{expected_sha256}\n{project}\n{target}\n{protected or ''}".encode("utf-8")).hexdigest()
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
            "fcpxml_path": str(fcpxml),
            "fcpxml_sha256": expected_sha256,
            "operation_id": operation_id,
            "expected_project": project,
            "target_timeline_name": target,
            "protected_timeline_name": protected,
            "import_permitted": True,
            "replace_existing_timeline": False,
            "save_project": False,
            "expected_clip_count": len(contract["clips"]),
            "expected_duration_frames": contract["duration_frames"],
            "expected_fps": contract["fps"],
        },
    }
    name = f"{TASK_ID}_{run_id}.json"
    pending = queue / "pending" / name
    write_json(pending, command)
    command_hash = sha256(pending)
    write_json(report_dir / "import_command.json", command)
    receipt = {"ok": True, "task_id": TASK_ID, "run_id": run_id, "operation_id": operation_id, "command_path": str(pending.relative_to(root)).replace("\\", "/"), "command_sha256": command_hash, "manual_action_required": "Workspace > Scripts > VC_Run_Agent_Task exactly once"}
    write_json(report_dir / "publication_receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--fcpxml", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--target-timeline", required=True)
    parser.add_argument("--protected-timeline")
    parser.add_argument("--run-id")
    args = parser.parse_args()
    try:
        result = publish(args.root, args.fcpxml, args.sha256, args.project, args.target_timeline, args.protected_timeline, args.run_id)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
