"""Publish the keep-on-import OSS-003 native boundary-80 proof."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_RELATIVE = "resolve_workspace/modules/oss003_native_b80_persist.py"
spec = importlib.util.spec_from_file_location("vc_oss003_native_persist", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss003_native_persist")
persist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(persist)
PATCHED_RELATIVE = persist.PATCHED_RELATIVE


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
    patched = root / PATCHED_RELATIVE
    persist.validate_patched_drt(patched)
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / persist.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1, "task": persist.TASK_ID, "run_id": run_id, "module": MODULE_RELATIVE, "mode": persist.MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log", "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "expected_project": persist.rep.EXPECTED_PROJECT,
            "production_timeline": persist.rep.EXPECTED_TIMELINE, "production_uid": persist.rep.EXPECTED_TIMELINE_UID,
            "proof_timeline": persist.PROOF_NAME, "boundary_relative": persist.BOUNDARY, "duration_frames": persist.DURATION,
            "patched_drt_path": str(patched), "patched_drt_sha256": persist.PATCHED_SHA256,
            "top_level_container": persist.TOP_LEVEL_CONTAINER, "retain_after_import": True,
            "save_after_readback": True, "module_sha256": _sha256(root / MODULE_RELATIVE),
        },
    }
    pending = queue / "pending" / f"{persist.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": persist.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix(), "patched_drt": PATCHED_RELATIVE}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
