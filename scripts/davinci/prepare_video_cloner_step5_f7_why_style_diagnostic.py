"""Publish one bounded live F7 ``why?`` style diagnostic command."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
TASK_ID = "VIDEO_CLONER_STEP5_F7_WHY_STYLE_LIVE_DIAGNOSTIC_V1"
MODE = "diagnose_why_style"
MODULE = "resolve_workspace/modules/video_cloner_step5_f7_why_style_diagnostic.py"
SOURCE_RUN = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F7_FRESH_RESOLVE_VALIDATION_REBUILD_V1/20261001T140614151053Z_b432bedf0ba545639b653549b4ffc5ba"
CONTRACT = SOURCE_RUN / "step5_f7_compile_contract.json"
BASELINE = ROOT / ".agent/reports/VIDEO_CLONER_STEP5A_REAL_TEXTPLUS_COMPILE_20260928/20260928T190000000Z_real_textplus_compile/step5a_cutonly_baseline.fcpxml"
TARGET_PREFIX = "VIDEO_CLONER_F7_WHY_STYLE_PROBE_"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish(now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or dt.datetime.now(dt.timezone.utc)
    module = ROOT / MODULE
    if not module.is_file() or not CONTRACT.is_file() or not BASELINE.is_file():
        raise ValueError("required_input")
    contract = json.loads(CONTRACT.read_text(encoding="utf-8-sig"))
    why = [row for row in contract.get("objects", []) if row.get("source_identity") == "recovered_display_object_why_0001"]
    if len(why) != 1 or why[0]["text"]["value"] != "why?" or why[0]["advanced_effects"]["shadow"] != "STYLE_UNRESOLVED_F5":
        raise ValueError("why_authority")
    queue = ROOT / ".agent/commands"
    for state in ("pending", "running", "completed", "failed"):
        (queue / state).mkdir(parents=True, exist_ok=True)
    active = [path for state in ("pending", "running") for path in (queue / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + uuid.uuid4().hex
    target = TARGET_PREFIX + run_id[-12:]
    report_dir = ROOT / ".agent/reports" / TASK_ID / run_id
    report_dir.mkdir(parents=True)
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(ROOT)).replace("/", "\\"),
        "log_path": str((report_dir / "run.log").relative_to(ROOT)).replace("/", "\\"),
        "report_path": str((report_dir / "bridge_report.json").relative_to(ROOT)).replace("/", "\\"),
        "payload": {
            "contract_path": str(CONTRACT),
            "contract_sha256": sha(CONTRACT),
            "baseline_fcpxml": str(BASELINE),
            "baseline_fcpxml_sha256": sha(BASELINE),
            "report_dir": str(report_dir),
            "target_timeline": target,
        },
    }
    command_path = queue / "pending" / f"{TASK_ID}_{run_id}.json"
    write(report_dir / "command.json", command)
    write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir), "target_timeline": target}
    write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
