"""Publish the one disposable OSS-001 Resolve compatibility command."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from resolve_workspace.modules import oss001_nested_textplus_compat as compat


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT) -> dict[str, str]:
    root = root.resolve()
    queue = root / ".agent" / "commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent" / "reports" / compat.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1,
        "task": compat.TASK_ID,
        "run_id": run_id,
        "module": "resolve_workspace/modules/oss001_nested_textplus_compat.py",
        "mode": compat.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "expected_project": "New Project 1",
            "source_timeline": compat.SOURCE_TIMELINE,
            "target_timeline": compat.TARGET_TIMELINE,
            "requested_track": compat.REQUESTED_TRACK,
            "requested_offset": compat.REQUESTED_OFFSET,
            "requested_duration": compat.REQUESTED_DURATION,
            "cleanup_required": True,
            "save_project": False,
        },
    }
    pending = queue / "pending" / f"{compat.TASK_ID}_{run_id}.json"
    _write_json(report / "command.json", command)
    _write_json(pending, command)
    return {"task_id": compat.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
