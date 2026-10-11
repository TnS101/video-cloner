"""Publish the OSS-004 five-target motion/VFX representative batch."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_RELATIVE = "resolve_workspace/modules/oss004_motion_vfx_representative_batch.py"
MOTION_RELATIVE = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_motion.json"
TRANSITION_RELATIVE = "data/DZatr0EJt4B/analysis/DZatr0EJt4B_transitions.json"
spec = importlib.util.spec_from_file_location("vc_oss004_batch", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss004_batch")
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
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    motion, transitions = root / MOTION_RELATIVE, root / TRANSITION_RELATIVE
    if _sha256(motion) != "fa15d4299d9a9fc970cffd911a2c7ae824422c66fe9de9ba284d5f5e84a40c87" or _sha256(transitions) != "5474e9619798dd93d43381182614adbe8669320697429a83af9141c1fffd1298":
        raise ValueError("canonical_authority_hash")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / runtime.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1, "task": runtime.TASK_ID, "run_id": run_id, "module": MODULE_RELATIVE, "mode": runtime.MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log", "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "expected_project": runtime.rep.EXPECTED_PROJECT,
            "baseline_timeline": runtime.BASELINE_NAME, "baseline_uid": runtime.BASELINE_UID,
            "derivative_timeline": runtime.DERIVATIVE_NAME, "target_ids": [row["id"] for row in runtime.RECIPES],
            "motion_authority_path": str(motion), "motion_authority_sha256": _sha256(motion),
            "transition_authority_path": str(transitions), "transition_authority_sha256": _sha256(transitions),
            "hyperframes_repository": "heygen-com/hyperframes", "hyperframes_commit": "46f6cb356785bed79e1ce7b79d7e7accc697786a", "hyperframes_license": "Apache-2.0",
            "resolve_repository": "samuelgursky/davinci-resolve-mcp", "resolve_commit": "94c7a885d53f13be78522ce96561a9e9e21d64c5", "resolve_license": "MIT",
            "retiming_mutation": False, "retain_after_verification": True, "save_after_verification": True,
            "module_sha256": _sha256(root / MODULE_RELATIVE),
        },
    }
    pending = queue / "pending" / f"{runtime.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": runtime.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
