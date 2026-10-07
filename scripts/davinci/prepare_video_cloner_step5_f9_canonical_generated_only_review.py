"""Validate F9 canonical output and publish one generated-only review command."""
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

from resolve_workspace.modules import video_cloner_step5_f9_canonical_generated_only_review as runtime

TASK_ID = runtime.TASK_ID
MODE = runtime.MODE
MODULE = "resolve_workspace/modules/video_cloner_step5_f9_canonical_generated_only_review.py"
SOURCE_RUN = ROOT / ".agent/reports/VIDEO_CLONER_STEP5_F9_CANONICAL_DISPLAY_OWNERSHIP_REBUILD_V1/20261003T111956566999Z_69524834b9114b7e830a9b911376265e"
SOURCE_TIMELINE = "VIDEO_CLONER_STEP5A_TEXTPLUS_VALIDATION_F7_CANONICAL_69524834b911"
SOURCE_TIMELINE_UID = "c6d2e51e-a4e9-4de5-87f5-55c9893a8e7f"
ARTIFACTS = {
    "contract": SOURCE_RUN / "first/step5_f9_canonical_compile_contract.json",
    "audit": SOURCE_RUN / "first/step5_f9_ownership_audit.json",
    "validation": SOURCE_RUN / "step5_f9_canonical_validation.json",
}


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object:{path}")
    return value


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def preflight() -> dict[str, Any]:
    bridge = _read(SOURCE_RUN / "bridge_report.json")
    contract, audit, validation = (_read(ARTIFACTS[name]) for name in ("contract", "audit", "validation"))
    cases = runtime.canonical_case_check(contract, audit, validation)
    count = int(contract.get("object_count") or 0)
    result = {
        "source_machine_pass": bridge.get("ok") is True and validation.get("pass") is True,
        "source_timeline": bridge.get("validation_timeline"),
        "canonical_textplus_count": count,
        "persisted_textplus_count": validation.get("persisted_renderable_objects"),
        "canonical_case_check": cases,
        "missing": validation.get("missing_objects"),
        "unexpected": validation.get("unexpected_extra_objects"),
        "protected_source_mutation_planned": False,
        "canonical_source_mutation_planned": False,
    }
    result["pass"] = result["source_machine_pass"] and result["source_timeline"] == {"name": SOURCE_TIMELINE, "unique_id": SOURCE_TIMELINE_UID} and count > 0 and result["persisted_textplus_count"] == count and result["missing"] == 0 and result["unexpected"] == 0 and cases["all_pass"]
    return result


def publish(now: dt.datetime | None = None) -> dict[str, Any]:
    active = [path for state in ("pending", "running") for path in (ROOT / ".agent/commands" / state).glob("*.json")]
    if active:
        raise ValueError(f"active_command:{active[0].name}")
    check = preflight()
    if not check["pass"]:
        raise ValueError("canonical_preflight")
    now = now or dt.datetime.now(dt.timezone.utc)
    unique = uuid.uuid4().hex
    run_id = now.strftime("%Y%m%dT%H%M%S%fZ") + "_" + unique
    review_timeline = "VIDEO_CLONER_STEP5_F9_CANONICAL_GENERATED_ONLY_REVIEW_" + unique[:12]
    report_dir = ROOT / ".agent/reports" / TASK_ID / run_id
    payload: dict[str, Any] = {
        "report_dir": str(report_dir),
        "source_timeline": SOURCE_TIMELINE,
        "source_timeline_uid": SOURCE_TIMELINE_UID,
        "review_timeline": review_timeline,
        "background_strategy": "NO_MEDIA_UNDERLAY_NEUTRAL_BLACK_VIEWER",
        "project_save": True,
    }
    for name, path in ARTIFACTS.items():
        payload[f"{name}_path"] = str(path.resolve())
        payload[f"{name}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    command = {
        "schema_version": 1,
        "task_id": TASK_ID,
        "run_id": run_id,
        "mode": MODE,
        "module": MODULE,
        "published_at": now.isoformat().replace("+00:00", "Z"),
        "status_path": str((report_dir / "status.json").relative_to(ROOT)),
        "log_path": str((report_dir / "run.log").relative_to(ROOT)),
        "report_path": str((report_dir / "bridge_report.json").relative_to(ROOT)),
        "payload": payload,
    }
    command_path = ROOT / ".agent/commands/pending" / f"{TASK_ID}_{run_id}.json"
    _write(report_dir / "preflight.json", check)
    _write(report_dir / "command.json", command)
    _write(command_path, command)
    receipt = {"task_id": TASK_ID, "run_id": run_id, "command_path": str(command_path), "report_dir": str(report_dir), "source_timeline": SOURCE_TIMELINE, "review_timeline": review_timeline, "module": MODULE, "mode": MODE, "expected_textplus_count": check["canonical_textplus_count"]}
    _write(report_dir / "publication_receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    print(json.dumps(publish(), indent=2, sort_keys=True))
