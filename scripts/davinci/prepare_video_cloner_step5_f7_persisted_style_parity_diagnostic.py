"""Publish one read-only diagnostic for the persisted failed F7 timeline."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "VIDEO_CLONER_STEP5_F7_PERSISTED_STYLE_PARITY_DIAGNOSTIC_V1"
MODE = "inspect_persisted_style_parity"
MODULE = "resolve_workspace/modules/video_cloner_step5_f7_persisted_style_parity_diagnostic.py"
SOURCE_RUN_ID = "20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd"
TARGET_TIMELINE = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd"
CONTRACT = f".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/{SOURCE_RUN_ID}/step5_f7_compile_contract.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT, now: dt.datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    now = now or dt.datetime.now(dt.timezone.utc)
    contract = root / CONTRACT
    module = root / MODULE
    if not (root / "AGENTS.md").is_file() or not contract.is_file() or not module.is_file():
        raise ValueError("required_input")
    command_root = root / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        (command_root / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (command_root / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex
    report_dir = root / ".agent/reports" / TASK_ID / run_id
    if report_dir.exists():
        raise ValueError("report_exists")
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(root)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(root)).replace("/", "\\"),
        "report_path": str((report_dir / "bridge_report.json").relative_to(root)).replace("/", "\\"),
        "payload": {
            "source_run_id": SOURCE_RUN_ID,
            "target_timeline": TARGET_TIMELINE,
            "contract_path": str(contract),
            "contract_sha256": sha(contract),
            "report_dir": str(report_dir),
            "read_only": True,
        },
    }
    command_path = command_root / "pending" / f"{TASK_ID}_{run_id}.json"
    write(report_dir / "command.json", command)
    write(command_path, command)
    receipt = {
        "task_id": TASK_ID,
        "run_id": run_id,
        "command_path": str(command_path),
        "report_dir": str(report_dir),
        "module": MODULE,
        "mode": MODE,
        "target_timeline": TARGET_TIMELINE,
        "source_run_id": SOURCE_RUN_ID,
        "read_only": True,
    }
    write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))

