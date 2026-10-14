"""Publish the focused OSS004 visible-effects command."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_RELATIVE = "resolve_workspace/modules/oss004_visible_effects.py"
spec = importlib.util.spec_from_file_location("vc_oss004_visible", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss004_visible")
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT) -> dict[str, str]:
    root = root.resolve()
    queue = root / ".agent/commands"
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / runtime.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1,
        "task": runtime.TASK_ID,
        "run_id": run_id,
        "module": MODULE_RELATIVE,
        "mode": runtime.MODE,
        "status_path": f"{relative_report}/status.json",
        "log_path": f"{relative_report}/run.log",
        "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root),
            "expected_project": runtime.rep.EXPECTED_PROJECT,
            "baseline_timeline": runtime.BASELINE_NAME,
            "baseline_uid": runtime.BASELINE_UID,
            "donor_timeline": runtime.DONOR_NAME,
            "derivative_timeline": runtime.DERIVATIVE_NAME,
            "module_sha256": _sha256(root / MODULE_RELATIVE),
        },
    }
    pending = queue / "pending" / f"{runtime.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": runtime.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
