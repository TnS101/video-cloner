"""Publish the final three-transition Reel #3 rollout command."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[2]
MODULE_RELATIVE = "resolve_workspace/modules/oss003_final_transition_rollout.py"
DRT_MODULE_RELATIVE = "resolve_workspace/modules/oss003_native_blur_drt.py"
TEMPLATE_RELATIVE = ".agent/reports/OSS003_NATIVE_BLUR_AUTO_B80_V1/20261011T130946582Z_0d071b6f8542403d8a51b0ac8d669580/blur_dissolve_template.xml"
spec = importlib.util.spec_from_file_location("vc_oss003_final", ROOT / MODULE_RELATIVE)
if spec is None or spec.loader is None:
    raise ImportError("cannot_load_oss003_final")
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
    template = root / TEMPLATE_RELATIVE
    if not template.is_file() or _sha256(template) != runtime.TEMPLATE_SHA256:
        raise ValueError("donor_template_identity")
    now = datetime.now(timezone.utc)
    run_id = f"{now:%Y%m%dT%H%M%S}{now.microsecond // 1000:03d}Z_{uuid4().hex}"
    report = root / ".agent/reports" / runtime.TASK_ID / run_id
    relative_report = report.relative_to(root).as_posix()
    command = {
        "schema_version": 1, "task": runtime.TASK_ID, "run_id": run_id, "module": MODULE_RELATIVE, "mode": runtime.MODE,
        "status_path": f"{relative_report}/status.json", "log_path": f"{relative_report}/run.log", "report_path": f"{relative_report}/report.json",
        "payload": {
            "repository_root": str(root), "expected_project": runtime.rep.EXPECTED_PROJECT,
            "production_timeline": runtime.rep.EXPECTED_TIMELINE, "production_uid": runtime.rep.EXPECTED_TIMELINE_UID,
            "final_timeline": runtime.FINAL_NAME,
            "boundaries": [{"relative_frame": cut, "duration_frames": duration, "type": "Blur Dissolve"} for cut, duration in runtime.BOUNDARIES],
            "donor_template_path": str(template), "donor_template_sha256": runtime.TEMPLATE_SHA256,
            "oss_repository": "samuelgursky/davinci-resolve-mcp", "oss_commit": "94c7a885d53f13be78522ce96561a9e9e21d64c5",
            "oss_path": "resolve-advanced/vendor/drp-format/place-transition.js", "oss_license": "MIT",
            "retain_after_import": True, "save_after_readback": True, "fusion_debt_policy": "defer_nonblocking",
            "module_sha256": _sha256(root / MODULE_RELATIVE), "drt_module_sha256": _sha256(root / DRT_MODULE_RELATIVE),
        },
    }
    pending = queue / "pending" / f"{runtime.TASK_ID}_{run_id}.json"
    _write(report / "command.json", command)
    _write(pending, command)
    return {"task_id": runtime.TASK_ID, "run_id": run_id, "command_path": pending.relative_to(root).as_posix()}


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
