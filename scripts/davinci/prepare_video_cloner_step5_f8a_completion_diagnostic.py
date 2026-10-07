"""Build local F8A completion evidence and publish one read-only Resolve audit."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.analysis.complete_step5_f8a_evidence import build
TASK_ID = "VIDEO_CLONER_STEP5_F8A_DIAGNOSTIC_COMPLETION_V1"
MODE = "step5_f8a_diagnostic_completion"
MODULE = "resolve_workspace/modules/video_cloner_step5_f8a_completion_diagnostic.py"
CONTRACT = ".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261002T093228130622Z_8a43be1aa99a4e2fa6ec66203b559cbd/step5_f7_compile_contract.json"


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(root: Path = ROOT, now: dt.datetime | None = None) -> dict[str, Any]:
    root = root.resolve()
    queue = root / ".agent/commands"
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    now = now or dt.datetime.now(dt.timezone.utc)
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex
    report_dir = root / ".agent/reports" / TASK_ID / run_id
    local = build(root, report_dir)
    contract = (root / CONTRACT).resolve()
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(root)),
        "log_path": str((report_dir / "run.log").relative_to(root)),
        "report_path": str((report_dir / "bridge_report.json").relative_to(root)),
        "payload": {
            "report_dir": str(report_dir),
            "contract_path": str(contract),
            "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
            "local_evidence": local,
            "persisted_target_mutation_permitted": False,
            "project_save": False,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    _write(report_dir / "command.json", command)
    _write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir), "target_timeline": "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_66203b559cbd", "module": MODULE, "mode": MODE}
    _write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
