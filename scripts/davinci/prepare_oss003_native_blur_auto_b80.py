"""Publish one donor-harvested native Blur Dissolve automation proof."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_RELATIVE = "resolve_workspace/modules/oss003_native_blur_auto_b80.py"
DRT_MODULE_RELATIVE = "resolve_workspace/modules/oss003_native_blur_drt.py"
CROSS_RELATIVE = ".agent/reports/OSS003_NATIVE_BOUNDARY80_TRANSITION_V1/20261011T122841727Z_865b583a4be84ab69e7e9ab6955d0ce3/native_b80_patched.drt"
spec = importlib.util.spec_from_file_location("vc_oss003_blur_auto", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss003_blur_auto")
auto = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auto)


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
    cross = root / CROSS_RELATIVE
    if _sha256(cross) != auto.CROSS_SHA256:
        raise ValueError("cross_drt_identity")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / auto.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1, "task": auto.TASK_ID, "run_id": run_id, "module": MODULE_RELATIVE, "mode": auto.MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log", "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "expected_project": auto.rep.EXPECTED_PROJECT,
            "production_timeline": auto.rep.EXPECTED_TIMELINE, "production_uid": auto.rep.EXPECTED_TIMELINE_UID,
            "donor_timeline": auto.DONOR_NAME, "donor_uid": auto.DONOR_UID, "proof_timeline": auto.PROOF_NAME,
            "boundary_relative": auto.BOUNDARY, "duration_frames": auto.DURATION, "transition_type": "blur-dissolve",
            "cross_drt_path": str(cross), "cross_drt_sha256": auto.CROSS_SHA256,
            "oss_repository": "samuelgursky/davinci-resolve-mcp", "oss_commit": "94c7a885d53f13be78522ce96561a9e9e21d64c5",
            "oss_path": "resolve-advanced/vendor/drp-format/place-transition.js", "oss_license": "MIT",
            "retain_after_import": True, "save_after_readback": True,
            "module_sha256": _sha256(root / MODULE_RELATIVE), "drt_module_sha256": _sha256(root / DRT_MODULE_RELATIVE),
        },
    }
    pending = queue / "pending" / f"{auto.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": auto.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
